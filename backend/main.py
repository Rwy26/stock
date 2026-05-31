from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import secrets
import string
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPBearer
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

import kis_client

try:
    import db as apollo_db
except Exception:  # pragma: no cover
    apollo_db = None

try:
    import models
except Exception:  # pragma: no cover
    models = None

try:
    import scoring_engine as _scoring_engine
except Exception:  # pragma: no cover
    _scoring_engine = None

import auth
from pipeline_paths import get_pipeline_paths
from settings import settings


bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(credentials=Depends(bearer_scheme)):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")

    token = auth.require_bearer(credentials)
    payload = auth.decode_access_token(token, secret=settings.jwt_secret)
    sub = payload.get("sub")
    if sub is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    try:
        user_id = int(sub)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    db: Session = apollo_db.get_session_factory()()
    try:
        user = db.execute(select(models.User).where(models.User.id == user_id)).scalar_one_or_none()
        if user is None or not user.is_active:
            raise HTTPException(status_code=401, detail="Invalid token")
        return user
    finally:
        db.close()


def require_admin(current_user=Depends(get_current_user)):
    role = getattr(current_user, "role", "user")
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return current_user


def get_current_user_for_refresh(credentials=Depends(bearer_scheme)):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")

    token = auth.require_bearer(credentials)
    # Allow a small grace window for recently-expired tokens.
    payload = auth.decode_access_token_allow_expired(token, secret=settings.jwt_secret, max_expired_seconds=60 * 60 * 24)
    sub = payload.get("sub")
    if sub is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    try:
        user_id = int(sub)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    db: Session = apollo_db.get_session_factory()()
    try:
        user = db.execute(select(models.User).where(models.User.id == user_id)).scalar_one_or_none()
        if user is None or not user.is_active:
            raise HTTPException(status_code=401, detail="Invalid token")
        return user
    finally:
        db.close()

app = FastAPI(title="MOON STOCK")


_kis_refresh_stop = threading.Event()
_autotrade_stop = threading.Event()
_recommendations_stop = threading.Event()
_engine_skip_last_ts: dict[tuple[int, str, str], float] = {}
_plus_last_rotation_check_ts: dict[int, float] = {}

# Runtime override for kill switch (admin-only).
# - None: use env-based settings.autotrading_kill_switch
# - True/False: override at runtime (no restart)
_runtime_kill_switch: bool | None = None


def _is_kill_switch_on() -> bool:
    if _runtime_kill_switch is None:
        return bool(settings.autotrading_kill_switch)
    return bool(_runtime_kill_switch)


def _log_engine_skip_rate_limited(
    db: Session,
    *,
    user_id: int,
    engine: str,
    reason: str,
    message: str,
    now_ts: float,
    min_interval_seconds: float = 600.0,
) -> None:
    """Write an engine skip log with basic in-process rate limiting."""

    assert models is not None
    key = (int(user_id), str(engine), str(reason))
    last = float(_engine_skip_last_ts.get(key, 0.0) or 0.0)
    if now_ts - last < float(min_interval_seconds):
        return
    _engine_skip_last_ts[key] = now_ts
    db.add(models.AutomationEngineLog(user_id=int(user_id), engine=str(engine), event="skip", message=str(message)))


def _kis_refresh_loop() -> None:
    """Best-effort hourly KIS token warm-up.

    Keeps cached KIS tokens fresh without requiring manual restarts.
    """

    time.sleep(2.0)

    while not _kis_refresh_stop.is_set():
        try:
            if apollo_db is not None and models is not None:
                db: Session = apollo_db.get_session_factory()()
                try:
                    rows = db.execute(
                        select(models.KisProfile.app_key, models.KisProfile.app_secret, models.KisProfile.is_paper)
                        .where(models.KisProfile.app_key.is_not(None), models.KisProfile.app_secret.is_not(None))
                    ).all()
                finally:
                    db.close()

                unique_profiles: dict[tuple[str, bool], str] = {}
                for app_key, app_secret, is_paper in rows:
                    ak = (str(app_key).strip() if app_key is not None else "")
                    sec = (str(app_secret).strip() if app_secret is not None else "")
                    if not ak or not sec:
                        continue
                    unique_profiles[(ak, bool(is_paper))] = sec

                for (ak, is_paper), sec in unique_profiles.items():
                    try:
                        _token, remaining = kis_client.get_access_token(
                            app_key=ak,
                            app_secret=sec,
                            is_paper=is_paper,
                            live_base_url=settings.kis_live_base_url,
                            paper_base_url=settings.kis_paper_base_url,
                            timeout_seconds=5.0,
                        )
                        if int(remaining) <= 60 * 60:
                            kis_client.get_access_token(
                                app_key=ak,
                                app_secret=sec,
                                is_paper=is_paper,
                                force_refresh=True,
                                live_base_url=settings.kis_live_base_url,
                                paper_base_url=settings.kis_paper_base_url,
                                timeout_seconds=5.0,
                            )
                    except Exception:
                        continue
        except Exception:
            pass

        _kis_refresh_stop.wait(timeout=60 * 60)


def _generate_recommendations_for_date(
    db: Session,
    *,
    rec_date: date,
    limit: int = 200,
) -> tuple[int, str | None]:
    """Populate Recommendation rows for rec_date using latest available IndicatorScore.

    Returns (upserted_count, score_date_used_iso).
    """

    assert models is not None

    score_date = db.execute(
        select(func.max(models.IndicatorScore.scoring_date)).where(models.IndicatorScore.scoring_date <= rec_date)
    ).scalar_one_or_none()
    if not score_date:
        return 0, None

    rows = db.execute(
        select(models.IndicatorScore.stock_code, models.IndicatorScore.score_total)
        .where(models.IndicatorScore.scoring_date == score_date)
        .order_by(desc(models.IndicatorScore.score_total), desc(models.IndicatorScore.created_at))
        .limit(int(limit))
    ).all()

    if not rows:
        return 0, str(score_date)

    upserted = 0
    for rank, (stock_code, score_total) in enumerate(rows, start=1):
        code = str(stock_code)
        score = int(score_total or 0)

        existing = db.execute(
            select(models.Recommendation)
            .where(models.Recommendation.rec_date == rec_date, models.Recommendation.stock_code == code)
            .limit(1)
        ).scalar_one_or_none()
        if existing is None:
            db.add(models.Recommendation(rec_date=rec_date, stock_code=code, score_total=score, rank=int(rank)))
        else:
            existing.score_total = score
            existing.rank = int(rank)
        upserted += 1

    return upserted, str(score_date)


def _recommendations_loop() -> None:
    """Periodic recommendations refresh.

    Keeps today's Recommendation rows populated from latest IndicatorScore.
    """

    time.sleep(3.0)
    while not _recommendations_stop.is_set():
        try:
            if apollo_db is not None and models is not None:
                db: Session = apollo_db.get_session_factory()()
                try:
                    today = date.today()
                    count, _score_date = _generate_recommendations_for_date(db, rec_date=today, limit=200)
                    if count:
                        db.commit()
                finally:
                    db.close()
        except Exception:
            pass

        # Refresh every 6 hours.
        _recommendations_stop.wait(timeout=60 * 60 * 6)


def _is_market_open(now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
    t = now.time()
    start = datetime(now.year, now.month, now.day, 9, 0, 0).time()
    # Keep the loop running a bit after close so liquidation at 15:20 can still run
    # even if the 1-minute scheduler is not perfectly aligned.
    end = datetime(now.year, now.month, now.day, 15, 30, 0).time()
    return start <= t <= end


def _should_sa_friday_liquidate(now: datetime) -> bool:
    # Friday 15:15 이후 전량 청산
    if now.weekday() != 4:
        return False
    return now.time() >= datetime(now.year, now.month, now.day, 15, 15, 0).time()


def _should_daily_close_liquidate(now: datetime) -> bool:
    # 15:20 이후 잔여 포지션 정리
    return now.time() >= datetime(now.year, now.month, now.day, 15, 20, 0).time()


def _parse_kis_account(value: str | None) -> tuple[str | None, str | None]:
    """Parse stored account field into (CANO, ACNT_PRDT_CD).

    We store in DB as either:
    - "12345678" (CANO only) -> product defaults to "01" for ordering
    - "12345678-01" or "1234567801" -> both parts
    """

    if value is None:
        return None, None
    raw = str(value).strip()
    if not raw:
        return None, None

    raw = raw.replace(" ", "")
    cano: str | None = None
    prdt: str | None = None

    if "-" in raw:
        left, right = raw.split("-", 1)
        cano = left.strip() or None
        prdt = right.strip() or None
    elif len(raw) == 10 and raw.isdigit():
        cano = raw[:8]
        prdt = raw[8:]
    else:
        cano = raw
        prdt = None

    if cano is not None:
        cano = "".join([c for c in cano if c.isdigit()])
        if len(cano) >= 8:
            cano = cano[:8]
        if len(cano) != 8:
            cano = None

    if prdt is not None:
        prdt = "".join([c for c in prdt if c.isdigit()])
        if prdt:
            prdt = prdt.zfill(2)[:2]
        else:
            prdt = None

    return cano, prdt


def _format_kis_account(cano: str | None, prdt: str | None) -> str | None:
    if not cano:
        return None
    c = "".join([x for x in str(cano).strip() if x.isdigit()])
    if len(c) != 8:
        return None
    if prdt is None:
        return c
    p = "".join([x for x in str(prdt).strip() if x.isdigit()])
    if not p:
        return c
    p = p.zfill(2)[:2]
    return f"{c}-{p}"


def _to_float_amount(v) -> float:
    try:
        return float(str(v).replace(",", "").strip() or 0)
    except Exception:
        return 0.0


def _to_int_amount(v) -> int:
    try:
        return int(float(str(v).replace(",", "").strip() or 0))
    except Exception:
        return 0


def _fetch_kis_balance(profile, *, timeout_seconds: float = 10.0) -> dict | None:
    """Fetch KIS balance/holdings for the given profile (read-only).

    This is safe for both paper and live profiles because it performs inquiry only.
    Ordering APIs remain guarded by AUTOTRADING_LIVE_ORDERS.
    """

    app_key = (str(getattr(profile, "app_key", "") or "").strip())
    app_secret = (str(getattr(profile, "app_secret", "") or "").strip())
    is_paper = bool(getattr(profile, "is_paper", False))
    stored = (str(getattr(profile, "account_prefix", "") or "").strip())
    cano, prdt_cd = _parse_kis_account(stored)
    if prdt_cd is None:
        prdt_cd = "01"

    if not app_key or not app_secret or not cano:
        return None

    return kis_client.inquire_balance(
        app_key=app_key,
        app_secret=app_secret,
        is_paper=is_paper,
        account_prefix=cano,
        account_product_code=prdt_cd,
        live_base_url=settings.kis_live_base_url,
        paper_base_url=settings.kis_paper_base_url,
        timeout_seconds=float(timeout_seconds),
    )


def _extract_kis_balance_kpis(balance: dict) -> tuple[int, int, int, int]:
    """Return (total_value, total_invested, pnl, cash) from inquire_balance payload."""

    out2 = balance.get("output2")
    if isinstance(out2, list):
        out2 = out2[0] if out2 else {}
    if not isinstance(out2, dict):
        out2 = {}

    total_value = _to_int_amount(out2.get("tot_evlu_amt") or out2.get("TOT_EVLU_AMT") or out2.get("tot_evlu_amt") or 0)
    total_invested = _to_int_amount(out2.get("pchs_amt_smtl") or out2.get("PCHS_AMT_SMTL") or out2.get("pchs_amt") or 0)
    pnl = _to_int_amount(out2.get("evlu_pfls_smtl") or out2.get("EVLU_PFLS_SMTL") or out2.get("evlu_pfls") or 0)
    cash = _to_int_amount(out2.get("dnca_tot_amt") or out2.get("DNCA_TOT_AMT") or out2.get("dnca_tot_amt") or 0)

    # Fallback if certain fields are missing.
    if pnl == 0 and total_value and total_invested:
        pnl = int(total_value - total_invested)

    return int(total_value), int(total_invested), int(pnl), int(cash)


def _sync_portfolio_from_kis(db: Session, *, user_id: int, profile, balance: dict | None = None) -> tuple[int, int]:
    """Best-effort sync: KIS holdings -> portfolio table.

    Returns (upserted_count, deleted_count).
    """

    assert models is not None

    if balance is None:
        balance = _fetch_kis_balance(profile, timeout_seconds=10.0)

    if not balance:
        return 0, 0

    holdings = balance.get("output1") or []

    desired: dict[str, tuple[int, float]] = {}
    stock_names: dict[str, str] = {}
    for item in holdings:
        try:
            code = str(item.get("pdno") or item.get("PDNO") or "").strip()
            if not code:
                continue
            name = str(
                item.get("prdt_name")
                or item.get("PRDT_NAME")
                or item.get("prdt_abrv_name")
                or item.get("PRDT_ABRV_NAME")
                or item.get("hts_kor_isnm")
                or item.get("HTS_KOR_ISNM")
                or ""
            ).strip()
            qty = _to_int_amount(item.get("hldg_qty") or item.get("HLDG_QTY") or 0)
            if qty <= 0:
                continue
            avg = _to_float_amount(item.get("pchs_avg_pric") or item.get("PCHS_AVG_PRIC") or 0)
            desired[code] = (qty, avg)
            if name:
                stock_names.setdefault(code, name)
        except Exception:
            continue

    if not desired:
        # If KIS says no holdings, clear portfolio.
        existing_positions = db.execute(select(models.PortfolioPosition).where(models.PortfolioPosition.user_id == int(user_id))).scalars().all()
        deleted = 0
        for p in existing_positions:
            db.delete(p)
            deleted += 1
        return 0, deleted

    # If we already have Stock rows but they were inserted with placeholder names (code),
    # upgrade them to real names from KIS holdings when available.
    if stock_names:
        try:
            existing_stocks = (
                db.execute(select(models.Stock).where(models.Stock.code.in_(list(stock_names.keys())))).scalars().all()
            )
            for s in existing_stocks:
                try:
                    code = str(getattr(s, "code"))
                    new_name = (stock_names.get(code) or "").strip()
                    if not new_name:
                        continue
                    cur_name = str(getattr(s, "name", "") or "").strip()
                    if (not cur_name) or (cur_name == code):
                        s.name = new_name
                except Exception:
                    continue
        except Exception:
            pass

    # Ensure stocks rows exist (FK safety).
    # KIS can return holdings for codes we have never seen before;
    # without a corresponding stocks row, portfolio upserts will fail.
    codes = sorted(desired.keys())
    existing_stock_codes = set(c for (c,) in db.execute(select(models.Stock.code).where(models.Stock.code.in_(codes))).all())
    missing_codes = [c for c in codes if c not in existing_stock_codes]
    if missing_codes:
        try:
            from sqlalchemy.dialects.mysql import insert as mysql_insert

            rows = [{"code": c, "name": (stock_names.get(c) or c), "market": None} for c in missing_codes]
            db.execute(mysql_insert(models.Stock.__table__).values(rows).prefix_with("IGNORE"))
        except Exception:
            # Best-effort only; fall back to filtering if insert fails.
            pass

    existing_stock_codes = set(c for (c,) in db.execute(select(models.Stock.code).where(models.Stock.code.in_(codes))).all())
    desired = {c: v for c, v in desired.items() if c in existing_stock_codes}
    if not desired:
        # Don't delete/clear if the only issue is missing stock master rows.
        return 0, 0

    existing = {
        str(p.stock_code): p
        for p in db.execute(select(models.PortfolioPosition).where(models.PortfolioPosition.user_id == int(user_id))).scalars().all()
    }

    upserted = 0
    for code, (qty, avg) in desired.items():
        pos = existing.get(code)
        if pos is None:
            db.add(
                models.PortfolioPosition(
                    user_id=int(user_id),
                    stock_code=code,
                    qty=int(qty),
                    avg_buy=float(avg),
                    buy_date=date.today(),
                )
            )
        else:
            pos.qty = int(qty)
            pos.avg_buy = float(avg)
            if pos.buy_date is None:
                pos.buy_date = date.today()
        upserted += 1

    deleted = 0
    for code, pos in existing.items():
        if code not in desired:
            db.delete(pos)
            deleted += 1

    return upserted, deleted


def _place_market_order_and_log(
    *,
    db: Session,
    user_id: int,
    engine: str,
    side: str,
    stock_code: str,
    qty: int,
    profile,
) -> tuple[bool, str]:
    """Place KIS market order and write Sa/Plus trade logs.

    Returns (ok, message).
    """

    app_key = (str(getattr(profile, "app_key", "") or "").strip())
    app_secret = (str(getattr(profile, "app_secret", "") or "").strip())
    is_paper = bool(getattr(profile, "is_paper", False))
    stored = (str(getattr(profile, "account_prefix", "") or "").strip())
    cano, prdt_cd = _parse_kis_account(stored)
    if prdt_cd is None:
        prdt_cd = "01"

    if not app_key or not app_secret or not cano or not prdt_cd:
        return False, "KIS 프로필(appKey/appSecret/accountPrefix) 설정 필요"

    if (not is_paper) and (not settings.autotrading_live_orders):
        return False, "실계좌 주문은 AUTOTRADING_LIVE_ORDERS=1 설정이 필요합니다."

    try:
        resp = kis_client.place_cash_order(
            app_key=app_key,
            app_secret=app_secret,
            is_paper=is_paper,
            account_prefix=cano,
            account_product_code=prdt_cd,
            side=("buy" if side == "buy" else "sell"),
            code=stock_code,
            qty=int(qty),
            order_type="market",
            live_base_url=settings.kis_live_base_url,
            paper_base_url=settings.kis_paper_base_url,
            timeout_seconds=10.0,
        )

        odno = None
        try:
            output = resp.get("output") or {}
            odno = output.get("ODNO") or output.get("odno")
        except Exception:
            odno = None

        msg = (f"주문 성공" + (f" (ODNO={odno})" if odno else ""))

        if engine == "sa":
            db.add(
                models.SaAutoTradingLog(
                    user_id=int(user_id),
                    stock_code=stock_code,
                    action=("buy" if side == "buy" else "sell"),
                    qty=int(qty),
                    price=None,
                    message=msg,
                )
            )
        elif engine == "plus":
            db.add(
                models.PlusAutoTradingLog(
                    user_id=int(user_id),
                    stock_code=stock_code,
                    action=("buy" if side == "buy" else "sell"),
                    qty=int(qty),
                    price=None,
                    message=msg,
                )
            )

        # Best-effort sync of filled qty/avg from KIS holdings.
        try:
            bal = kis_client.inquire_balance(
                app_key=app_key,
                app_secret=app_secret,
                is_paper=is_paper,
                account_prefix=cano,
                account_product_code=prdt_cd,
                live_base_url=settings.kis_live_base_url,
                paper_base_url=settings.kis_paper_base_url,
                timeout_seconds=10.0,
            )
            holdings = bal.get("output1") or []
            holding_qty = 0
            holding_avg = 0.0
            for item in holdings:
                try:
                    pdno = str(item.get("pdno") or item.get("PDNO") or "").strip()
                    if pdno != stock_code:
                        continue
                    q = str(item.get("hldg_qty") or item.get("HLDG_QTY") or "0").replace(",", "").strip()
                    a = str(item.get("pchs_avg_pric") or item.get("PCHS_AVG_PRIC") or "0").replace(",", "").strip()
                    holding_qty = int(float(q or 0))
                    holding_avg = float(a or 0)
                    break
                except Exception:
                    continue

            if engine == "sa":
                pos = db.execute(
                    select(models.SaAutoTradingPosition)
                    .where(
                        models.SaAutoTradingPosition.user_id == int(user_id),
                        models.SaAutoTradingPosition.stock_code == stock_code,
                        models.SaAutoTradingPosition.closed_at.is_(None),
                    )
                ).scalar_one_or_none()
                if holding_qty > 0:
                    if pos is None:
                        pos = models.SaAutoTradingPosition(user_id=int(user_id), stock_code=stock_code, qty=int(holding_qty), avg_buy=float(holding_avg))
                        db.add(pos)
                    else:
                        pos.qty = int(holding_qty)
                        pos.avg_buy = float(holding_avg)
                else:
                    if pos is not None and side == "sell":
                        pos.closed_at = datetime.now()

            elif engine == "plus":
                pos = db.execute(
                    select(models.PlusAutoTradingPosition)
                    .where(
                        models.PlusAutoTradingPosition.user_id == int(user_id),
                        models.PlusAutoTradingPosition.stock_code == stock_code,
                        models.PlusAutoTradingPosition.closed_at.is_(None),
                    )
                ).scalar_one_or_none()
                if holding_qty > 0:
                    if pos is None:
                        pos = models.PlusAutoTradingPosition(user_id=int(user_id), stock_code=stock_code, qty=int(holding_qty), avg_buy=float(holding_avg))
                        db.add(pos)
                    else:
                        pos.qty = int(holding_qty)
                        pos.avg_buy = float(holding_avg)
                else:
                    if pos is not None and side == "sell":
                        pos.closed_at = datetime.now()
        except Exception:
            pass

        return True, msg
    except Exception as exc:
        err = str(exc)
        if engine == "sa":
            db.add(
                models.SaAutoTradingLog(
                    user_id=int(user_id),
                    stock_code=stock_code,
                    action=("buy" if side == "buy" else "sell"),
                    qty=int(qty),
                    price=None,
                    message=f"주문 실패: {err}",
                )
            )
        elif engine == "plus":
            db.add(
                models.PlusAutoTradingLog(
                    user_id=int(user_id),
                    stock_code=stock_code,
                    action=("buy" if side == "buy" else "sell"),
                    qty=int(qty),
                    price=None,
                    message=f"주문 실패: {err}",
                )
            )
        return False, err


def _pick_top_recommendation_code(db: Session, *, exclude_codes: set[str]) -> str | None:
    assert models is not None
    today = date.today()
    rows = db.execute(
        select(models.Recommendation.stock_code)
        .where(models.Recommendation.rec_date == today)
        .order_by(models.Recommendation.rank.is_(None), models.Recommendation.rank, desc(models.Recommendation.score_total))
        .limit(50)
    ).all()
    for (code,) in rows:
        c = str(code)
        if c and c not in exclude_codes:
            return c
    return None


def _parse_positive_int_like(value: object | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return int(value) if value > 0 else None
    if isinstance(value, float):
        if not (value > 0):
            return None
        return int(value)
    if isinstance(value, str):
        s = value.strip().replace(",", "")
        if not s:
            return None
        for prefix in ("₩", "KRW", "krw"):
            if s.startswith(prefix):
                s = s[len(prefix) :].strip()
        try:
            n = int(float(s))
            return n if n > 0 else None
        except Exception:
            return None
    return None


def _run_sa_engine_tick(db: Session, *, user_id: int, profile, now: datetime) -> None:
    assert models is not None

    # Apply per-user config (maxPositions + budget-based sizing).
    max_positions = 5
    cfg_obj: dict | None = None
    try:
        cfg = db.execute(
            select(models.SaAutoTradingConfig.config).where(models.SaAutoTradingConfig.user_id == int(user_id))
        ).scalar_one_or_none()
        if isinstance(cfg, dict):
            cfg_obj = cfg
            raw = cfg.get("maxPositions")
            if raw is not None:
                max_positions = int(raw)
    except Exception:
        max_positions = 5
        cfg_obj = None
    if max_positions < 1:
        max_positions = 1
    if max_positions > 50:
        max_positions = 50

    # liquidation rules
    if _should_sa_friday_liquidate(now) or _should_daily_close_liquidate(now):
        open_pos = db.execute(
            select(models.SaAutoTradingPosition)
            .where(models.SaAutoTradingPosition.user_id == user_id, models.SaAutoTradingPosition.closed_at.is_(None))
        ).scalars().all()
        for p in open_pos:
            ok, msg = _place_market_order_and_log(
                db=db,
                user_id=user_id,
                engine="sa",
                side="sell",
                stock_code=str(p.stock_code),
                qty=int(p.qty),
                profile=profile,
            )
            db.add(models.AutomationEngineLog(user_id=user_id, engine="sa", event=("sell" if ok else "error"), message=msg))
            if ok:
                p.closed_at = datetime.now()
        return

    # buy minimal: if holdings < max_positions, buy 1 share of top recommendation not held
    open_pos = db.execute(
        select(models.SaAutoTradingPosition)
        .where(models.SaAutoTradingPosition.user_id == user_id, models.SaAutoTradingPosition.closed_at.is_(None))
    ).scalars().all()
    if len(open_pos) >= max_positions:
        return

    held = {str(p.stock_code) for p in open_pos}
    code = _pick_top_recommendation_code(db, exclude_codes=held)
    if not code:
        return

    qty = 1
    try:
        per_budget = _parse_positive_int_like((cfg_obj or {}).get("perStockBudget"))
        total_budget = _parse_positive_int_like((cfg_obj or {}).get("totalBudget"))
        if per_budget is None and total_budget is not None and max_positions > 0:
            per_budget = max(0, int(total_budget // max_positions))
        if per_budget is not None and per_budget > 0:
            price, _cr = _get_realtime_price_and_change(db, profile, code)
            if float(price) <= 0:
                _log_engine_skip_rate_limited(
                    db,
                    user_id=int(user_id),
                    engine="sa",
                    reason="price",
                    message=f"buy skipped: price unavailable (code={code})",
                    now_ts=time.time(),
                )
                return
            qty = int(per_budget // float(price))
            if qty < 1:
                _log_engine_skip_rate_limited(
                    db,
                    user_id=int(user_id),
                    engine="sa",
                    reason="budget",
                    message=f"buy skipped: budget too small (code={code}, perStockBudget={per_budget}, price={float(price):.2f})",
                    now_ts=time.time(),
                )
                return
            if qty > 1000:
                qty = 1000
    except Exception:
        # Conservative: if sizing fails under a budget, skip the buy.
        if _parse_positive_int_like((cfg_obj or {}).get("perStockBudget")) is not None or _parse_positive_int_like((cfg_obj or {}).get("totalBudget")) is not None:
            _log_engine_skip_rate_limited(
                db,
                user_id=int(user_id),
                engine="sa",
                reason="sizing",
                message=f"buy skipped: sizing failed (code={code})",
                now_ts=time.time(),
            )
            return
        qty = 1

    ok, msg = _place_market_order_and_log(
        db=db,
        user_id=user_id,
        engine="sa",
        side="buy",
        stock_code=code,
        qty=qty,
        profile=profile,
    )
    db.add(models.AutomationEngineLog(user_id=user_id, engine="sa", event=("buy" if ok else "error"), message=msg))
    if ok:
        # create a new position; avg_buy will be unknown until fill (set 0 for now)
        db.add(models.SaAutoTradingPosition(user_id=user_id, stock_code=code, qty=int(qty), avg_buy=0.0))


def _run_plus_engine_tick(db: Session, *, user_id: int, profile, now: datetime) -> None:
    assert models is not None

    # Apply per-user config (maxPositions + budget-based sizing).
    max_positions = 5
    cfg_obj: dict | None = None
    try:
        cfg = db.execute(
            select(models.PlusAutoTradingConfig.config).where(models.PlusAutoTradingConfig.user_id == int(user_id))
        ).scalar_one_or_none()
        if isinstance(cfg, dict):
            cfg_obj = cfg
            raw = cfg.get("maxPositions")
            if raw is not None:
                max_positions = int(raw)
    except Exception:
        max_positions = 5
        cfg_obj = None
    if max_positions < 1:
        max_positions = 1
    if max_positions > 50:
        max_positions = 50

    # Throttle plus rotation checks by user-configured interval.
    rotation_minutes = None
    try:
        rotation_minutes = _parse_positive_int_like((cfg_obj or {}).get("rotationCheckMinutes"))
    except Exception:
        rotation_minutes = None
    if rotation_minutes is not None:
        if rotation_minutes < 1:
            rotation_minutes = 1
        if rotation_minutes > 24 * 60:
            rotation_minutes = 24 * 60

        # Only throttle the buy/rotation logic, not liquidation.
        now_ts = time.time()
        last = float(_plus_last_rotation_check_ts.get(int(user_id), 0.0) or 0.0)
        if now_ts - last < float(rotation_minutes) * 60.0:
            _log_engine_skip_rate_limited(
                db,
                user_id=int(user_id),
                engine="plus",
                reason="rotation",
                message=f"tick skipped: rotation interval not reached (rotationCheckMinutes={rotation_minutes})",
                now_ts=now_ts,
            )
            return
        _plus_last_rotation_check_ts[int(user_id)] = now_ts

    if _should_daily_close_liquidate(now):
        open_pos = db.execute(
            select(models.PlusAutoTradingPosition)
            .where(models.PlusAutoTradingPosition.user_id == user_id, models.PlusAutoTradingPosition.closed_at.is_(None))
        ).scalars().all()
        for p in open_pos:
            ok, msg = _place_market_order_and_log(
                db=db,
                user_id=user_id,
                engine="plus",
                side="sell",
                stock_code=str(p.stock_code),
                qty=int(p.qty),
                profile=profile,
            )
            db.add(models.AutomationEngineLog(user_id=user_id, engine="plus", event=("sell" if ok else "error"), message=msg))
            if ok:
                p.closed_at = datetime.now()
        return

    open_pos = db.execute(
        select(models.PlusAutoTradingPosition)
        .where(models.PlusAutoTradingPosition.user_id == user_id, models.PlusAutoTradingPosition.closed_at.is_(None))
    ).scalars().all()
    if len(open_pos) >= max_positions:
        return

    held = {str(p.stock_code) for p in open_pos}
    code = _pick_top_recommendation_code(db, exclude_codes=held)
    if not code:
        return

    qty = 1
    try:
        per_budget = _parse_positive_int_like((cfg_obj or {}).get("perStockBudget"))
        total_budget = _parse_positive_int_like((cfg_obj or {}).get("totalBudget"))
        if per_budget is None and total_budget is not None and max_positions > 0:
            per_budget = max(0, int(total_budget // max_positions))
        if per_budget is not None and per_budget > 0:
            price, _cr = _get_realtime_price_and_change(db, profile, code)
            if float(price) <= 0:
                _log_engine_skip_rate_limited(
                    db,
                    user_id=int(user_id),
                    engine="plus",
                    reason="price",
                    message=f"buy skipped: price unavailable (code={code})",
                    now_ts=time.time(),
                )
                return
            qty = int(per_budget // float(price))
            if qty < 1:
                _log_engine_skip_rate_limited(
                    db,
                    user_id=int(user_id),
                    engine="plus",
                    reason="budget",
                    message=f"buy skipped: budget too small (code={code}, perStockBudget={per_budget}, price={float(price):.2f})",
                    now_ts=time.time(),
                )
                return
            if qty > 1000:
                qty = 1000
    except Exception:
        if _parse_positive_int_like((cfg_obj or {}).get("perStockBudget")) is not None or _parse_positive_int_like((cfg_obj or {}).get("totalBudget")) is not None:
            _log_engine_skip_rate_limited(
                db,
                user_id=int(user_id),
                engine="plus",
                reason="sizing",
                message=f"buy skipped: sizing failed (code={code})",
                now_ts=time.time(),
            )
            return
        qty = 1

    ok, msg = _place_market_order_and_log(
        db=db,
        user_id=user_id,
        engine="plus",
        side="buy",
        stock_code=code,
        qty=qty,
        profile=profile,
    )
    db.add(models.AutomationEngineLog(user_id=user_id, engine="plus", event=("buy" if ok else "error"), message=msg))
    if ok:
        db.add(models.PlusAutoTradingPosition(user_id=user_id, stock_code=code, qty=int(qty), avg_buy=0.0))


def _autotrade_tick_loop() -> None:
    """Dry-run engine scheduler.

    - Runs every minute during market hours.
    - Reads per-user enabled flags.
    - Writes a simple tick log (no orders are placed).
    """

    time.sleep(2.0)

    last_portfolio_sync: dict[int, float] = {}

    while not _autotrade_stop.is_set():
        try:
            if _is_kill_switch_on():
                _autotrade_stop.wait(timeout=60)
                continue

            if apollo_db is None or models is None:
                _autotrade_stop.wait(timeout=60)
                continue

            now = datetime.now()
            if not _is_market_open(now):
                _autotrade_stop.wait(timeout=60)
                continue

            db: Session = apollo_db.get_session_factory()()
            try:
                sa_users = db.execute(
                    select(models.SaAutoTradingConfig.user_id).where(models.SaAutoTradingConfig.enabled.is_(True))
                ).all()
                plus_users = db.execute(
                    select(models.PlusAutoTradingConfig.user_id).where(models.PlusAutoTradingConfig.enabled.is_(True))
                ).all()

                sa_ids = {int(uid) for (uid,) in sa_users}
                plus_ids = {int(uid) for (uid,) in plus_users}
                all_ids = sorted(sa_ids.union(plus_ids))

                for uid in all_ids:
                    # profile is per-user
                    profile = db.execute(select(models.KisProfile).where(models.KisProfile.user_id == int(uid))).scalar_one_or_none()

                    # Periodic best-effort portfolio sync (covers manual trades & partial fills).
                    try:
                        now_ts = time.time()
                        last = float(last_portfolio_sync.get(int(uid), 0.0) or 0.0)
                        if now_ts - last >= 300:
                            upserted, deleted = _sync_portfolio_from_kis(db, user_id=int(uid), profile=profile)
                            if upserted or deleted:
                                db.add(
                                    models.AutomationEngineLog(
                                        user_id=int(uid),
                                        engine="basic",
                                        event="sync",
                                        message=f"portfolio synced: upserted={upserted}, deleted={deleted}",
                                    )
                                )
                            last_portfolio_sync[int(uid)] = now_ts
                    except Exception as exc:
                        db.add(
                            models.AutomationEngineLog(
                                user_id=int(uid),
                                engine="basic",
                                event="error",
                                message=f"portfolio sync failed: {exc}",
                            )
                        )

                    if uid in sa_ids:
                        try:
                            db.add(models.AutomationEngineLog(user_id=int(uid), engine="sa", event="tick", message=None))
                            _run_sa_engine_tick(db, user_id=int(uid), profile=profile, now=now)
                        except Exception as exc:
                            db.add(models.AutomationEngineLog(user_id=int(uid), engine="sa", event="error", message=str(exc)))

                    if uid in plus_ids:
                        try:
                            db.add(models.AutomationEngineLog(user_id=int(uid), engine="plus", event="tick", message=None))
                            _run_plus_engine_tick(db, user_id=int(uid), profile=profile, now=now)
                        except Exception as exc:
                            db.add(models.AutomationEngineLog(user_id=int(uid), engine="plus", event="error", message=str(exc)))

                db.commit()
            except Exception:
                db.rollback()
            finally:
                db.close()
        except Exception:
            pass

        _autotrade_stop.wait(timeout=60)


@app.on_event("startup")
def _startup_kis_refresh() -> None:
    # Ensure pipeline directories exist (data/artifacts/runs/logs/tmp) under PIPELINE_ROOT.
    # This is idempotent and keeps path usage centralized.
    try:
        get_pipeline_paths().ensure_dirs()
    except Exception as exc:
        # Avoid crashing the whole API if the pipeline disk is unavailable.
        # Call sites that write to these paths will still surface errors.
        print(f"[pipeline] failed to ensure pipeline dirs under {settings.pipeline_root}: {exc}")

    # Ensure any newly added tables exist (dev-friendly; idempotent).
    try:
        if apollo_db is not None and models is not None:
            engine = apollo_db.get_engine()
            models.AutomationEngineLog.__table__.create(bind=engine, checkfirst=True)
    except Exception:
        pass

    t = threading.Thread(target=_kis_refresh_loop, name="kis-token-refresh", daemon=True)
    t.start()

    t2 = threading.Thread(target=_autotrade_tick_loop, name="autotrade-tick", daemon=True)
    t2.start()

    t3 = threading.Thread(target=_recommendations_loop, name="recommendations-refresh", daemon=True)
    t3.start()


@app.on_event("shutdown")
def _shutdown_kis_refresh() -> None:
    _kis_refresh_stop.set()
    _autotrade_stop.set()
    _recommendations_stop.set()

REPO_ROOT = Path(__file__).resolve().parents[1]

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/portfolio")
def get_portfolio(current_user=Depends(get_current_user)):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")

    user_id = int(current_user.id)
    db: Session = apollo_db.get_session_factory()()
    try:
        profile = db.execute(select(models.KisProfile).where(models.KisProfile.user_id == user_id)).scalar_one_or_none()

        # Read-only best-effort sync from KIS so portfolio reflects manual trades.
        balance = None
        has_kis = bool(profile and profile.app_key and profile.app_secret)
        try:
            if profile is not None:
                balance = _fetch_kis_balance(profile, timeout_seconds=8.0)
                if balance:
                    upserted, deleted = _sync_portfolio_from_kis(db, user_id=user_id, profile=profile, balance=balance)
                    if upserted or deleted:
                        db.commit()
        except Exception:
            balance = None

        if settings.kis_strict_balance:
            if not has_kis:
                raise HTTPException(status_code=400, detail="KIS 연결 필요")
            if not balance:
                raise HTTPException(status_code=503, detail="KIS 잔고 조회 실패")

        positions = db.execute(
            select(
                models.PortfolioPosition.stock_code,
                models.PortfolioPosition.qty,
                models.PortfolioPosition.avg_buy,
                models.PortfolioPosition.buy_date,
                models.Stock.name,
            )
            .join(models.Stock, models.Stock.code == models.PortfolioPosition.stock_code)
            .where(models.PortfolioPosition.user_id == user_id)
            .order_by(models.PortfolioPosition.stock_code)
        ).all()

        payload_positions: list[dict] = []
        for stock_code, qty, avg_buy, buy_date, name in positions:
            current, _change_rate = _get_realtime_price_and_change(db, profile, stock_code)
            payload_positions.append(
                {
                    "name": name,
                    "code": stock_code,
                    "qty": int(qty),
                    "avgBuy": float(avg_buy),
                    "current": float(current),
                    "buyDate": (buy_date or date.today()).isoformat(),
                }
            )

        cash = None
        if balance:
            try:
                _total_value, _total_invested, _pnl, cash_amt = _extract_kis_balance_kpis(balance)
                cash = int(cash_amt)
            except Exception:
                cash = None

        return {"asOf": datetime.now().isoformat(), "positions": payload_positions, "cash": cash}
    finally:
        db.close()


@app.get("/api/recommendations")
def get_recommendations(_current_user=Depends(get_current_user)):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")

    today = date.today()
    db: Session = apollo_db.get_session_factory()()
    try:
        # Realtime prices are per-user (KIS credentials).
        # In strict mode, require KIS profile and do not fall back to DB prices.
        user_profile = None
        try:
            # _current_user is required by auth; keep mypy happy.
            user_id = int(getattr(_current_user, "id"))
            user_profile = db.execute(select(models.KisProfile).where(models.KisProfile.user_id == user_id)).scalar_one_or_none()
        except Exception:
            user_profile = None

        if settings.kis_strict_price:
            if not (user_profile and getattr(user_profile, "app_key", None) and getattr(user_profile, "app_secret", None)):
                raise HTTPException(status_code=400, detail="KIS 연결 필요")

        rows = db.execute(
            select(
                models.Recommendation.rank,
                models.Recommendation.score_total,
                models.Recommendation.stock_code,
                models.Stock.name,
            )
            .join(models.Stock, models.Stock.code == models.Recommendation.stock_code)
            .where(models.Recommendation.rec_date == today)
            .order_by(models.Recommendation.rank.is_(None), models.Recommendation.rank, desc(models.Recommendation.score_total))
        ).all()

        # Fallback: if recommendations table is empty for today, use indicator scores.
        if not rows:
            rows = db.execute(
                select(
                    func.null().label("rank"),
                    models.IndicatorScore.score_total,
                    models.IndicatorScore.stock_code,
                    models.Stock.name,
                )
                .join(models.Stock, models.Stock.code == models.IndicatorScore.stock_code)
                .where(models.IndicatorScore.scoring_date == today)
                .order_by(desc(models.IndicatorScore.score_total), desc(models.IndicatorScore.created_at))
                .limit(30)
            ).all()

        items: list[dict] = []
        kis_error: str | None = None
        for rank, score_total, stock_code, name in rows:
            price, change_rate = 0.0, 0.0
            try:
                price, change_rate = _get_realtime_price_and_change(db, user_profile, stock_code)
            except Exception as exc:
                if kis_error is None:
                    kis_error = str(exc)
            items.append(
                {
                    "rank": int(rank or 0),
                    "name": name,
                    "code": stock_code,
                    "score": int(score_total),
                    "price": float(price),
                    "changeRate": float(change_rate),
                }
            )

        return {"date": today.isoformat(), "items": items, "priceError": kis_error}
    finally:
        db.close()


@app.get("/api/recommendations/king")
def get_king_recommendations(_current_user=Depends(get_current_user)):
    """KING 카테고리: 섹터 순환 분석 → 상위 2개 섹터 + 해당 섹터 대표 ETF 정보 + 최고점수 종목.

    - scoring_engine.compute_king_sectors() 로 KOSPI 대비 섹터 ETF 알파 계산
    - DB IndicatorScore에서 오늘 스코어링된 종목 중 score_total 최고 종목 반환
    """
    if _scoring_engine is None:
        raise HTTPException(status_code=503, detail="scoring_engine module not available")
    if apollo_db is None or models is None:
        raise HTTPException(status_code=503, detail="DB module not available")

    try:
        top_sectors = _scoring_engine.compute_king_sectors(top_n=2)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"섹터 분석 실패: {exc}") from exc

    # DB에서 오늘 기준 최고점수 종목 (상위 10개)
    today = date.today()
    db: Session = apollo_db.get_session_factory()()
    try:
        rows = db.execute(
            select(
                models.IndicatorScore.stock_code,
                models.Stock.name,
                models.IndicatorScore.score_total,
                models.IndicatorScore.details,
            )
            .join(models.Stock, models.Stock.code == models.IndicatorScore.stock_code)
            .where(models.IndicatorScore.scoring_date == today)
            .order_by(desc(models.IndicatorScore.score_total))
            .limit(10)
        ).all()
        top_stocks = [
            {
                "code": r.stock_code,
                "name": r.name,
                "score_total": r.score_total,
                "eligible": bool(
                    r.details and r.details.get("recommendation_eligible", False)
                ),
                "eps_growth": r.details and r.details.get("eps_growth_value"),
                "eps_growth_note": r.details and r.details.get("eps_growth_note"),
            }
            for r in rows
        ]
    finally:
        db.close()

    return {
        "king_sectors": top_sectors,
        "top_stocks": top_stocks,
        "scored_date": today.isoformat(),
        "note": "KING: KOSPI 초과수익 상위 2개 섹터 ETF + 당일 최고점수 종목",
    }


@app.get("/api/watchlist")
def get_watchlist(current_user=Depends(get_current_user)):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")

    user_id = int(current_user.id)
    db: Session = apollo_db.get_session_factory()()
    try:
        profile = db.execute(select(models.KisProfile).where(models.KisProfile.user_id == user_id)).scalar_one_or_none()

        if settings.kis_strict_price:
            if not (profile and getattr(profile, "app_key", None) and getattr(profile, "app_secret", None)):
                raise HTTPException(status_code=400, detail="KIS 연결 필요")

        rows = db.execute(
            select(models.Watchlist.stock_code, models.Stock.name, models.StockInterest.tags)
            .join(models.Stock, models.Stock.code == models.Watchlist.stock_code)
            .outerjoin(
                models.StockInterest,
                (models.StockInterest.stock_code == models.Watchlist.stock_code)
                & (models.StockInterest.user_id == user_id),
            )
            .where(models.Watchlist.user_id == user_id)
            .order_by(desc(models.Watchlist.created_at))
        ).all()

        _SIGNAL_TAGS = {"외국인수급", "기관수급"}

        def _extract_sector(raw_tags) -> str:
            import json as _json
            tags = raw_tags
            if isinstance(tags, str):
                try:
                    tags = _json.loads(tags)
                except Exception:
                    return "기타"
            if not isinstance(tags, list) or not tags:
                return "기타"
            for tag in tags:
                segment = str(tag).split("|")[0].strip()
                if segment not in _SIGNAL_TAGS:
                    return segment
            return "기타수급"

        items: list[dict] = []
        for stock_code, name, raw_tags in rows:
            try:
                price, change_rate = _get_realtime_price_and_change(db, profile, stock_code)
            except Exception:
                price, change_rate = 0, 0.0
            score = _get_latest_score_total(db, stock_code)
            items.append(
                {
                    "name": name,
                    "code": stock_code,
                    "price": float(price),
                    "changeRate": float(change_rate),
                    "score": int(score),
                    "sector": _extract_sector(raw_tags),
                }
            )

        return {"items": items}
    finally:
        db.close()


@app.post("/api/watchlist")
def add_watchlist_item(payload: dict = Body(...), current_user=Depends(get_current_user)):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")
    code = (payload.get("code") or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="code is required")

    user_id = int(current_user.id)
    with apollo_db.session_scope() as session:
        # In strict mode, validate code via KIS quote to ensure this is a real instrument.
        if settings.kis_strict_price:
            profile = session.execute(select(models.KisProfile).where(models.KisProfile.user_id == user_id)).scalar_one_or_none()
            if not (profile and getattr(profile, "app_key", None) and getattr(profile, "app_secret", None)):
                raise HTTPException(status_code=400, detail="KIS 연결 필요")
            try:
                kis_client.inquire_price(
                    app_key=str(profile.app_key),
                    app_secret=str(profile.app_secret),
                    is_paper=bool(getattr(profile, "is_paper", False)),
                    code=code,
                    live_base_url=settings.kis_live_base_url,
                    paper_base_url=settings.kis_paper_base_url,
                    timeout_seconds=5.0,
                )
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"유효하지 않은 종목코드 또는 시세 조회 실패: {exc}") from exc

        stock = session.execute(select(models.Stock).where(models.Stock.code == code)).scalar_one_or_none()
        if stock is None:
            # Allow adding new codes; create a placeholder stock row.
            session.add(models.Stock(code=code, name=code, market=None))

        exists = session.execute(
            select(models.Watchlist.id).where(models.Watchlist.user_id == user_id, models.Watchlist.stock_code == code)
        ).first()
        if not exists:
            session.add(models.Watchlist(user_id=user_id, stock_code=code))

    return {"ok": True}


@app.delete("/api/watchlist/{code}")
def remove_watchlist_item(code: str, current_user=Depends(get_current_user)):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")
    code = code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="code is required")

    user_id = int(current_user.id)
    with apollo_db.session_scope() as session:
        row = session.execute(
            select(models.Watchlist).where(models.Watchlist.user_id == user_id, models.Watchlist.stock_code == code)
        ).scalar_one_or_none()
        if row is None:
            return {"ok": True}
        session.delete(row)

    return {"ok": True}


def _get_latest_price_and_change(db: Session, stock_code: str) -> tuple[float, float]:
    """Return (latest_close, change_rate_pct) based on the newest two daily_prices."""

    assert models is not None

    prices = db.execute(
        select(models.DailyPrice.trading_date, models.DailyPrice.close_price)
        .where(models.DailyPrice.stock_code == stock_code)
        .order_by(desc(models.DailyPrice.trading_date))
        .limit(2)
    ).all()
    if not prices:
        return 0.0, 0.0
    latest_close = float(prices[0].close_price)
    if len(prices) < 2:
        return latest_close, 0.0
    prev_close = float(prices[1].close_price)
    if prev_close == 0:
        return latest_close, 0.0
    return latest_close, round(((latest_close - prev_close) / prev_close) * 100.0, 2)


def _get_realtime_price_and_change(
    db: Session,
    profile: object | None,
    stock_code: str,
) -> tuple[float, float]:
    """Prefer KIS real-time price. Fallback to DB daily_prices if configured."""

    if models is None:
        return 0.0, 0.0

    app_key = getattr(profile, "app_key", None)
    app_secret = getattr(profile, "app_secret", None)
    is_paper = bool(getattr(profile, "is_paper", False))

    if app_key and app_secret:
        try:
            quote = kis_client.inquire_price(
                app_key=str(app_key),
                app_secret=str(app_secret),
                is_paper=is_paper,
                code=stock_code,
                live_base_url=settings.kis_live_base_url,
                paper_base_url=settings.kis_paper_base_url,
            )
            return float(quote.price), float(quote.change_rate)
        except Exception:
            if settings.kis_strict_price:
                raise

    # Fallback: DB daily_prices (dev only). NOTE: production should set KIS_STRICT_PRICE=1.
    return _get_latest_price_and_change(db, stock_code)


def _get_latest_score_total(db: Session, stock_code: str) -> int:
    assert models is not None
    row = db.execute(
        select(models.IndicatorScore.score_total)
        .where(models.IndicatorScore.stock_code == stock_code)
        .order_by(desc(models.IndicatorScore.scoring_date), desc(models.IndicatorScore.created_at))
        .limit(1)
    ).first()
    if not row:
        return 0
    return int(row[0] or 0)


@app.get("/api/dashboard")
def get_dashboard(current_user=Depends(get_current_user)):
    # Keep the structure stable for the existing UI.
    user_id = int(current_user.id)

    sa_on = False
    plus_on = False
    sv_on = False
    kis_connected = False
    sa_trades_today = 0
    plus_trades_today = 0
    sv_trades_today = 0

    balance = None
    has_kis_profile = False
    top_recommendations: list[dict] = []
    if apollo_db is not None and models is not None:
        db: Session = apollo_db.get_session_factory()()
        try:
            sa_cfg = db.execute(select(models.SaAutoTradingConfig).where(models.SaAutoTradingConfig.user_id == user_id)).scalar_one_or_none()
            plus_cfg = db.execute(select(models.PlusAutoTradingConfig).where(models.PlusAutoTradingConfig.user_id == user_id)).scalar_one_or_none()
            sv_cfg = db.execute(select(models.SvAgentConfig).where(models.SvAgentConfig.user_id == user_id)).scalar_one_or_none()
            sa_on = bool(sa_cfg.enabled) if sa_cfg else False
            plus_on = bool(plus_cfg.enabled) if plus_cfg else False
            sv_on = bool(sv_cfg.enabled) if sv_cfg else False

            start_dt = datetime.combine(date.today(), datetime.min.time())
            end_dt = start_dt + timedelta(days=1)

            try:
                sa_trades_today = int(
                    db.execute(
                        select(func.count())
                        .select_from(models.SaAutoTradingLog)
                        .where(
                            models.SaAutoTradingLog.user_id == user_id,
                            models.SaAutoTradingLog.at >= start_dt,
                            models.SaAutoTradingLog.at < end_dt,
                        )
                    ).scalar_one()
                    or 0
                )
            except Exception:
                sa_trades_today = 0

            try:
                plus_trades_today = int(
                    db.execute(
                        select(func.count())
                        .select_from(models.PlusAutoTradingLog)
                        .where(
                            models.PlusAutoTradingLog.user_id == user_id,
                            models.PlusAutoTradingLog.at >= start_dt,
                            models.PlusAutoTradingLog.at < end_dt,
                        )
                    ).scalar_one()
                    or 0
                )
            except Exception:
                plus_trades_today = 0

            # SV Agent trades are not yet logged in a dedicated table in this codebase.
            sv_trades_today = 0

            profile = db.execute(select(models.KisProfile).where(models.KisProfile.user_id == user_id)).scalar_one_or_none()
            if profile and profile.app_key and profile.app_secret:
                has_kis_profile = True
                # Prefer full balance inquiry for the dashboard KPIs.
                try:
                    balance = _fetch_kis_balance(profile, timeout_seconds=5.0)
                    kis_connected = True
                except Exception:
                    kis_connected = False

            # Prefer real recommendations from DB.
            try:
                today = date.today()
                rec_rows = db.execute(
                    select(
                        models.Recommendation.rank,
                        models.Recommendation.score_total,
                        models.Recommendation.stock_code,
                        models.Stock.name,
                    )
                    .join(models.Stock, models.Stock.code == models.Recommendation.stock_code)
                    .where(models.Recommendation.rec_date == today)
                    .order_by(models.Recommendation.rank.is_(None), models.Recommendation.rank, desc(models.Recommendation.score_total))
                    .limit(5)
                ).all()

                if not rec_rows:
                    rec_rows = db.execute(
                        select(
                            func.null().label("rank"),
                            models.IndicatorScore.score_total,
                            models.IndicatorScore.stock_code,
                            models.Stock.name,
                        )
                        .join(models.Stock, models.Stock.code == models.IndicatorScore.stock_code)
                        .where(models.IndicatorScore.scoring_date == today)
                        .order_by(desc(models.IndicatorScore.score_total), desc(models.IndicatorScore.created_at))
                        .limit(5)
                    ).all()

                for rank, score_total, stock_code, name in rec_rows:
                    top_recommendations.append(
                        {
                            "name": str(name),
                            "code": str(stock_code),
                            "score": int(score_total or 0),
                        }
                    )
            except Exception:
                top_recommendations = []
        finally:
            db.close()

    # Real-data only: do not serve any sample KPIs.
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")
    if not has_kis_profile:
        raise HTTPException(status_code=400, detail="KIS 연결 필요")
    if not balance:
        raise HTTPException(status_code=503, detail="KIS 잔고 조회 실패")

    try:
        total_value, total_invested, pnl, cash_amt = _extract_kis_balance_kpis(balance)
        pnl_pct = 0.0
        if total_invested:
            pnl_pct = round((float(pnl) / float(total_invested)) * 100.0, 2)
        kpis = {
            "totalValue": {"amount": int(total_value), "deltaPct": pnl_pct},
            "totalInvested": {"amount": int(total_invested), "deltaPct": 0.0},
            "pnl": {"amount": int(pnl), "deltaPct": pnl_pct},
            "cash": {"amount": int(cash_amt), "label": "가용 가능"},
        }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"KIS 잔고 파싱 실패: {exc}") from exc

    return {
        "asOf": datetime.now().isoformat(),
        "kpis": kpis,
        "topRecommendations": top_recommendations,
        "automation": {
            "basic": {"on": False, "label": "OFF / 0건"},
            "sa": {"on": sa_on, "label": ("ON" if sa_on else "OFF") + f" / {sa_trades_today}건"},
            "plus": {"on": plus_on, "label": ("ON" if plus_on else "OFF") + f" / {plus_trades_today}건"},
            "svAgent": {"on": sv_on, "label": ("ON" if sv_on else "OFF") + f" / {sv_trades_today}건"},
        },
        "kis": {"connected": kis_connected, "label": ("KIS 실시간 연결" if kis_connected else "KIS 연결 필요")},
    }


@app.get("/api/kis/token-status")
def kis_token_status(current_user=Depends(get_current_user)):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")

    user_id = int(current_user.id)
    db: Session = apollo_db.get_session_factory()()
    try:
        profile = db.execute(select(models.KisProfile).where(models.KisProfile.user_id == user_id)).scalar_one_or_none()
        app_key = (str(profile.app_key).strip() if profile and profile.app_key else "")
        app_secret = (str(profile.app_secret).strip() if profile and profile.app_secret else "")
        is_paper = bool(profile.is_paper) if profile else False

        if not app_key or not app_secret:
            return {
                "ok": True,
                "hasProfile": False,
                "tradeType": ("모의투자" if is_paper else "실계좌"),
                "expiresIn": None,
                "asOf": datetime.now().isoformat(),
            }

        try:
            _token, expires_in = kis_client.get_access_token(
                app_key=app_key,
                app_secret=app_secret,
                is_paper=is_paper,
                live_base_url=settings.kis_live_base_url,
                paper_base_url=settings.kis_paper_base_url,
                timeout_seconds=5.0,
            )
            return {
                "ok": True,
                "hasProfile": True,
                "tradeType": ("모의투자" if is_paper else "실계좌"),
                "expiresIn": int(expires_in),
                "asOf": datetime.now().isoformat(),
            }
        except Exception as exc:
            return {
                "ok": False,
                "hasProfile": True,
                "tradeType": ("모의투자" if is_paper else "실계좌"),
                "expiresIn": None,
                "error": str(exc),
                "asOf": datetime.now().isoformat(),
            }
    finally:
        db.close()


@app.post("/api/admin/recommendations/generate-today")
def admin_generate_recommendations_today(_admin=Depends(require_admin)):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")

    db: Session = apollo_db.get_session_factory()()
    try:
        today = date.today()
        count, score_date = _generate_recommendations_for_date(db, rec_date=today, limit=200)
        db.commit()
        return {"ok": True, "date": today.isoformat(), "scoreDate": score_date, "upserted": int(count)}
    finally:
        db.close()


# ─── Scoring Engine Endpoints ─────────────────────────────────────────────────

@app.get("/api/admin/scoring/status")
def admin_scoring_status(_admin=Depends(require_admin)):
    """3-Tier 스코어링 엔진 상태 및 최근 실행 정보."""
    if _scoring_engine is None:
        return {"available": False, "reason": "scoring_engine 모듈 로드 실패"}

    if apollo_db is None or models is None:
        return {"available": True, "db": False, "reason": "DB 모듈 없음"}

    db: Session = apollo_db.get_session_factory()()
    try:
        latest_date = db.execute(
            select(func.max(models.IndicatorScore.scoring_date))
        ).scalar_one_or_none()
        total_scored = db.execute(
            select(func.count(models.IndicatorScore.id))
            .where(models.IndicatorScore.scoring_date == latest_date)
        ).scalar_one_or_none() if latest_date else 0
        total_stocks = db.execute(select(func.count(models.Stock.code))).scalar_one_or_none()
    finally:
        db.close()

    return {
        "available": True,
        "module_loaded": _scoring_engine is not None,
        "latest_scoring_date": latest_date.isoformat() if latest_date else None,
        "scored_count": int(total_scored or 0),
        "total_stocks": int(total_stocks or 0),
        "tiers": {
            "tier1": "섹터 알파 (Alpha, Sharpe, 수급 – KIS 필요)",
            "tier2": "바닥 탈출 (MA골든크로스, 볼린저, 거래량폭등, 다이버전스, 실적)",
            "tier3": "급락 위험 필터 (거래량고갈, 공매도, Bearish다이버전스, 음봉, 162% 과열)",
        },
        "scoring_weights": {
            "score_tech (Tier2)": "×3",
            "score_flow (수급)": "×3",
            "score_value (Tier1 알파)": "×2",
            "score_profit (실적)": "×1",
            "score_growth (Tier3 역점수)": "×1",
            "max_total": 100,
        },
    }


@app.post("/api/admin/scoring/run")
def admin_scoring_run(
    payload: dict = Body(default={}),
    _admin=Depends(require_admin),
):
    """3-Tier 스코어링 실행 후 IndicatorScore 저장.

    Body (선택):
    {
        "codes": ["005930", "000660", ...],   // 없으면 DB 전체 종목
        "max_workers": 4,
        "prefetch_fundamentals": true,        // yfinance EPS 사전 조회 (기본 true)
        "fetch_supply_demand": true,          // KIS+DART 수급/실적 자동 수집 (기본 true)
        "supply_demand_map": { ... }          // 수동 주입 (있으면 자동 수집 덮어쓰기)
    }
    """
    if _scoring_engine is None:
        raise HTTPException(status_code=503, detail="scoring_engine 모듈 없음")
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB 모듈 없음")

    max_workers           = int(payload.get("max_workers", 4))
    supply_demand_map: dict = dict(payload.get("supply_demand_map") or {})
    codes: list[str] | None = payload.get("codes")
    fetch_sd: bool = bool(payload.get("fetch_supply_demand", True))
    prefetch_fund: bool = bool(payload.get("prefetch_fundamentals", True))

    db: Session = apollo_db.get_session_factory()()
    try:
        if not codes:
            rows = db.execute(select(models.Stock.code)).scalars().all()
            codes = list(rows)
        if not codes:
            return {"ok": True, "upserted": 0, "msg": "스코어링 대상 종목 없음"}

        # ── KIS + DART 수급/실적 자동 수집 ─────────────────────────────────
        if fetch_sd:
            try:
                from supply_demand import fetch_supply_demand_batch
                sd_auto = fetch_supply_demand_batch(
                    codes,
                    kis_app_key=settings.kis_app_key if hasattr(settings, "kis_app_key") else "",
                    kis_app_secret=settings.kis_app_secret if hasattr(settings, "kis_app_secret") else "",
                    kis_is_paper=True,
                    kis_live_base_url=settings.kis_live_base_url,
                    kis_paper_base_url=settings.kis_paper_base_url,
                    dart_api_key=settings.dart_api_key,
                    max_workers=min(max_workers, 6),
                    use_db_cache=True,
                    db_session=db,
                )
                # supply_demand_map 수동 값이 자동 값보다 우선
                for code, auto_data in sd_auto.items():
                    merged = dict(auto_data)
                    merged.update(supply_demand_map.get(code) or {})
                    supply_demand_map[code] = merged
            except Exception as exc:
                logger.warning("수급 자동 수집 실패 (스코어링은 계속): %s", exc)
    finally:
        db.close()

    today = date.today()
    results = _scoring_engine.run_batch(
        codes,
        scoring_date=today,
        supply_demand_map=supply_demand_map,
        max_workers=min(max_workers, 8),
        prefetch_fundamentals=prefetch_fund,
    )

    # DB 저장
    upserted = 0
    db2: Session = apollo_db.get_session_factory()()
    try:
        for res in results:
            existing = db2.execute(
                select(models.IndicatorScore)
                .where(
                    models.IndicatorScore.stock_code == res.stock_code,
                    models.IndicatorScore.scoring_date == res.scoring_date,
                )
            ).scalar_one_or_none()

            if existing is None:
                db2.add(models.IndicatorScore(
                    stock_code=res.stock_code,
                    scoring_date=res.scoring_date,
                    score_value=res.score_value,
                    score_flow=res.score_flow,
                    score_profit=res.score_profit,
                    score_growth=res.score_growth,
                    score_tech=res.score_tech,
                    score_total=res.score_total,
                    details=res.details,
                ))
            else:
                existing.score_value  = res.score_value
                existing.score_flow   = res.score_flow
                existing.score_profit = res.score_profit
                existing.score_growth = res.score_growth
                existing.score_tech   = res.score_tech
                existing.score_total  = res.score_total
                existing.details      = res.details
            upserted += 1

        db2.commit()

        # 추천 테이블도 갱신
        _generate_recommendations_for_date(db2, rec_date=today, limit=200)
        db2.commit()
    finally:
        db2.close()

    eligible = [r for r in results if (r.details or {}).get("recommendation_eligible")]
    top10 = [
        {
            "code": r.stock_code,
            "score": r.score_total,
            "tech": r.score_tech,
            "value": r.score_value,
            "growth": r.score_growth,
        }
        for r in sorted(results, key=lambda x: x.score_total, reverse=True)[:10]
    ]
    return {
        "ok": True,
        "date": today.isoformat(),
        "total_scored": len(results),
        "upserted": upserted,
        "eligible_count": len(eligible),
        "top10": top10,
    }


@app.post("/api/admin/scoring/preview")
def admin_scoring_preview(
    payload: dict = Body(...),
    _admin=Depends(require_admin),
):
    """단일 종목 스코어 미리보기 (DB 저장 없음, 즉시 반환).

    Body: { "code": "005930", "supply_demand": { ... } }
    """
    if _scoring_engine is None:
        raise HTTPException(status_code=503, detail="scoring_engine 모듈 없음")

    code = (payload.get("code") or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="종목코드(code) 필요")

    supply_demand = payload.get("supply_demand") or {}

    try:
        result = _scoring_engine.compute_stock_score(
            code,
            scoring_date=date.today(),
            supply_demand=supply_demand,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"스코어링 오류: {exc}") from exc

    return {
        "code": result.stock_code,
        "date": result.scoring_date.isoformat(),
        "scores": {
            "tech":   result.score_tech,
            "flow":   result.score_flow,
            "value":  result.score_value,
            "profit": result.score_profit,
            "growth": result.score_growth,
            "total":  result.score_total,
        },
        "eligible": (result.details or {}).get("recommendation_eligible", False),
        "tier2_met": (result.details or {}).get("tier2_met_count", 0),
        "tier3_risk": (result.details or {}).get("tier3_risk_count", 0),
        "details": result.details,
    }


@app.get("/api/admin/supply-demand/{stock_code}")
def admin_supply_demand_preview(
    stock_code: str,
    _admin=Depends(require_admin),
):
    """단일 종목 수급 데이터 실시간 조회 (KIS + DART).

    KIS/DART 키가 없으면 각 필드 빈 값.
    """
    code = stock_code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="종목코드 필요")

    try:
        from supply_demand import fetch_supply_demand_batch
        result = fetch_supply_demand_batch(
            [code],
            kis_app_key=getattr(settings, "kis_app_key", ""),
            kis_app_secret=getattr(settings, "kis_app_secret", ""),
            kis_is_paper=True,
            kis_live_base_url=settings.kis_live_base_url,
            kis_paper_base_url=settings.kis_paper_base_url,
            dart_api_key=settings.dart_api_key,
            max_workers=2,
            use_db_cache=False,
        )
        return {"code": code, "data": result.get(code, {})}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"수급 조회 오류: {exc}") from exc


@app.get("/api/automation/sa")
def get_sa_config(current_user=Depends(get_current_user)):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")
    user_id = int(current_user.id)
    db: Session = apollo_db.get_session_factory()()
    try:
        cfg = db.execute(select(models.SaAutoTradingConfig).where(models.SaAutoTradingConfig.user_id == user_id)).scalar_one_or_none()
        return {
            "enabled": bool(cfg.enabled) if cfg else False,
            "config": (cfg.config if cfg else None),
            "updatedAt": (cfg.updated_at.isoformat() if cfg and cfg.updated_at else None),
        }
    finally:
        db.close()


@app.post("/api/automation/sa")
def upsert_sa_config(payload: dict = Body(...), current_user=Depends(get_current_user)):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")
    user_id = int(current_user.id)
    enabled = bool(payload.get("enabled", False))
    config = payload.get("config")

    with apollo_db.session_scope() as session:
        cfg = session.execute(select(models.SaAutoTradingConfig).where(models.SaAutoTradingConfig.user_id == user_id)).scalar_one_or_none()
        if cfg is None:
            cfg = models.SaAutoTradingConfig(user_id=user_id)
            session.add(cfg)
        cfg.enabled = enabled
        cfg.config = config if isinstance(config, dict) or config is None else {"value": config}

    return {"ok": True}


@app.get("/api/automation/plus")
def get_plus_config(current_user=Depends(get_current_user)):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")
    user_id = int(current_user.id)
    db: Session = apollo_db.get_session_factory()()
    try:
        cfg = db.execute(select(models.PlusAutoTradingConfig).where(models.PlusAutoTradingConfig.user_id == user_id)).scalar_one_or_none()
        return {
            "enabled": bool(cfg.enabled) if cfg else False,
            "config": (cfg.config if cfg else None),
            "updatedAt": (cfg.updated_at.isoformat() if cfg and cfg.updated_at else None),
        }
    finally:
        db.close()


@app.post("/api/automation/plus")
def upsert_plus_config(payload: dict = Body(...), current_user=Depends(get_current_user)):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")
    user_id = int(current_user.id)
    enabled = bool(payload.get("enabled", False))
    config = payload.get("config")

    with apollo_db.session_scope() as session:
        cfg = session.execute(select(models.PlusAutoTradingConfig).where(models.PlusAutoTradingConfig.user_id == user_id)).scalar_one_or_none()
        if cfg is None:
            cfg = models.PlusAutoTradingConfig(user_id=user_id)
            session.add(cfg)
        cfg.enabled = enabled
        cfg.config = config if isinstance(config, dict) or config is None else {"value": config}

    return {"ok": True}


@app.get("/api/automation/sa/positions")
def get_sa_positions(include_closed: bool = False, current_user=Depends(get_current_user)):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")

    user_id = int(current_user.id)
    db: Session = apollo_db.get_session_factory()()
    try:
        stmt = (
            select(models.SaAutoTradingPosition, models.Stock.name)
            .outerjoin(models.Stock, models.Stock.code == models.SaAutoTradingPosition.stock_code)
            .where(models.SaAutoTradingPosition.user_id == user_id)
        )
        if not include_closed:
            stmt = stmt.where(models.SaAutoTradingPosition.closed_at.is_(None))
        rows = db.execute(stmt.order_by(desc(models.SaAutoTradingPosition.opened_at))).all()

        items: list[dict] = []
        for pos, name in rows:
            current, _change_rate = _get_latest_price_and_change(db, str(pos.stock_code))
            avg_buy = float(pos.avg_buy or 0.0)
            pnl_pct = None
            if avg_buy > 0 and current > 0:
                pnl_pct = round(((current - avg_buy) / avg_buy) * 100.0, 2)
            items.append(
                {
                    "id": int(pos.id),
                    "name": (name or str(pos.stock_code)),
                    "code": str(pos.stock_code),
                    "qty": int(pos.qty or 0),
                    "avgBuy": avg_buy,
                    "current": float(current),
                    "pnlPct": pnl_pct,
                    "openedAt": (pos.opened_at.isoformat() if pos.opened_at else None),
                    "closedAt": (pos.closed_at.isoformat() if pos.closed_at else None),
                }
            )

        return {"asOf": datetime.now().isoformat(), "items": items}
    finally:
        db.close()


@app.get("/api/automation/sa/logs")
def get_sa_logs(limit: int = 100, current_user=Depends(get_current_user)):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")

    limit = int(limit or 100)
    if limit < 1:
        limit = 1
    if limit > 500:
        limit = 500

    user_id = int(current_user.id)
    db: Session = apollo_db.get_session_factory()()
    try:
        rows = db.execute(
            select(models.SaAutoTradingLog, models.Stock.name)
            .outerjoin(models.Stock, models.Stock.code == models.SaAutoTradingLog.stock_code)
            .where(models.SaAutoTradingLog.user_id == user_id)
            .order_by(desc(models.SaAutoTradingLog.at))
            .limit(limit)
        ).all()

        items: list[dict] = []
        for log, name in rows:
            items.append(
                {
                    "id": int(log.id),
                    "at": (log.at.isoformat() if log.at else None),
                    "action": str(log.action),
                    "name": (name or str(log.stock_code)),
                    "code": str(log.stock_code),
                    "qty": (int(log.qty) if log.qty is not None else None),
                    "price": (float(log.price) if log.price is not None else None),
                    "message": (str(log.message) if log.message else None),
                }
            )

        return {"asOf": datetime.now().isoformat(), "items": items}
    finally:
        db.close()


@app.get("/api/automation/plus/positions")
def get_plus_positions(include_closed: bool = False, current_user=Depends(get_current_user)):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")

    user_id = int(current_user.id)
    db: Session = apollo_db.get_session_factory()()
    try:
        stmt = (
            select(models.PlusAutoTradingPosition, models.Stock.name)
            .outerjoin(models.Stock, models.Stock.code == models.PlusAutoTradingPosition.stock_code)
            .where(models.PlusAutoTradingPosition.user_id == user_id)
        )
        if not include_closed:
            stmt = stmt.where(models.PlusAutoTradingPosition.closed_at.is_(None))
        rows = db.execute(stmt.order_by(desc(models.PlusAutoTradingPosition.opened_at))).all()

        items: list[dict] = []
        for pos, name in rows:
            current, _change_rate = _get_latest_price_and_change(db, str(pos.stock_code))
            avg_buy = float(pos.avg_buy or 0.0)
            pnl_pct = None
            if avg_buy > 0 and current > 0:
                pnl_pct = round(((current - avg_buy) / avg_buy) * 100.0, 2)
            items.append(
                {
                    "id": int(pos.id),
                    "name": (name or str(pos.stock_code)),
                    "code": str(pos.stock_code),
                    "qty": int(pos.qty or 0),
                    "avgBuy": avg_buy,
                    "current": float(current),
                    "pnlPct": pnl_pct,
                    "openedAt": (pos.opened_at.isoformat() if pos.opened_at else None),
                    "closedAt": (pos.closed_at.isoformat() if pos.closed_at else None),
                }
            )

        return {"asOf": datetime.now().isoformat(), "items": items}
    finally:
        db.close()


@app.get("/api/automation/plus/logs")
def get_plus_logs(limit: int = 100, current_user=Depends(get_current_user)):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")

    limit = int(limit or 100)
    if limit < 1:
        limit = 1
    if limit > 500:
        limit = 500

    user_id = int(current_user.id)
    db: Session = apollo_db.get_session_factory()()
    try:
        rows = db.execute(
            select(models.PlusAutoTradingLog, models.Stock.name)
            .outerjoin(models.Stock, models.Stock.code == models.PlusAutoTradingLog.stock_code)
            .where(models.PlusAutoTradingLog.user_id == user_id)
            .order_by(desc(models.PlusAutoTradingLog.at))
            .limit(limit)
        ).all()

        items: list[dict] = []
        for log, name in rows:
            items.append(
                {
                    "id": int(log.id),
                    "at": (log.at.isoformat() if log.at else None),
                    "action": str(log.action),
                    "name": (name or str(log.stock_code)),
                    "code": str(log.stock_code),
                    "qty": (int(log.qty) if log.qty is not None else None),
                    "price": (float(log.price) if log.price is not None else None),
                    "message": (str(log.message) if log.message else None),
                }
            )

        return {"asOf": datetime.now().isoformat(), "items": items}
    finally:
        db.close()


@app.get("/api/automation/sv")
def get_sv_config(current_user=Depends(get_current_user)):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")
    user_id = int(current_user.id)
    db: Session = apollo_db.get_session_factory()()
    try:
        cfg = db.execute(select(models.SvAgentConfig).where(models.SvAgentConfig.user_id == user_id)).scalar_one_or_none()
        return {
            "enabled": bool(cfg.enabled) if cfg else False,
            "config": (cfg.config if cfg else None),
            "updatedAt": (cfg.updated_at.isoformat() if cfg and cfg.updated_at else None),
        }
    finally:
        db.close()


@app.post("/api/automation/sv")
def upsert_sv_config(payload: dict = Body(...), current_user=Depends(get_current_user)):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")
    user_id = int(current_user.id)
    enabled = bool(payload.get("enabled", False))
    config = payload.get("config")

    with apollo_db.session_scope() as session:
        cfg = session.execute(select(models.SvAgentConfig).where(models.SvAgentConfig.user_id == user_id)).scalar_one_or_none()
        if cfg is None:
            cfg = models.SvAgentConfig(user_id=user_id)
            session.add(cfg)
        cfg.enabled = enabled
        cfg.config = config if isinstance(config, dict) or config is None else {"value": config}

    return {"ok": True}


@app.get("/api/stocks/search")
def search_stocks(
    q: str | None = None,
    market: str | None = None,
    sort: str | None = None,
    screen: str | None = None,
    current_user=Depends(get_current_user),
):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")

    user_id = int(current_user.id)
    q_norm      = (q      or "").strip()
    market_norm = (market or "").strip().upper()
    screen_norm = (screen or "").strip().lower()

    # ── 스크린별 점수 컬럼 매핑 ──────────────────────────────────────────────
    # models.IndicatorScore 에 해당 컬럼이 없을 경우 score_total 로 fallback
    SCREEN_SORT: dict[str, str] = {
        "leading":       "score_total",   # 주도 섹터: 종합점수 상위
        "big_buy":       "score_flow",    # 대량 매수: 수급 점수 상위
        "bottom_escape": "score_tech",    # 바닥 탈출: 기술 점수 상위
        "crash_risk":    "score_total",   # 급락 위험: 종합점수 하위 (역정렬)
    }

    def _score_col(col_name: str):
        """IndicatorScore 에서 col_name 컬럼을 가져오되, 없으면 score_total."""
        return getattr(models.IndicatorScore, col_name, models.IndicatorScore.score_total)

    db: Session = apollo_db.get_session_factory()()
    try:
        profile = db.execute(select(models.KisProfile).where(models.KisProfile.user_id == user_id)).scalar_one_or_none()
        if not (profile and getattr(profile, "app_key", None) and getattr(profile, "app_secret", None)):
            raise HTTPException(status_code=400, detail="KIS 연결 필요")

        score_date = db.execute(select(func.max(models.IndicatorScore.scoring_date))).scalar_one_or_none()
        if not score_date:
            raise HTTPException(status_code=503, detail="지표 점수 데이터가 없습니다")

        stmt = (
            select(models.Stock.code, models.Stock.name, models.IndicatorScore.score_total)
            .join(models.IndicatorScore, models.IndicatorScore.stock_code == models.Stock.code)
            .where(models.IndicatorScore.scoring_date == score_date)
        )

        if market_norm in {"KOSPI", "KOSDAQ"}:
            stmt = stmt.where(models.Stock.market == market_norm)

        if q_norm:
            like_code = f"{q_norm}%"
            like_name = f"%{q_norm}%"
            stmt = stmt.where((models.Stock.code.like(like_code)) | (models.Stock.name.like(like_name)))

        # ── 스크린별 최소 점수 필터 ──────────────────────────────────────────
        # 각 스크린이 서로 다른 모집단을 선택하도록 조건 구분
        if screen_norm == "leading":
            # 주도 섹터: 이미 강한 종합 우량주
            stmt = stmt.where(models.IndicatorScore.score_total >= 60)
        elif screen_norm == "big_buy":
            # 대량 매수: 수급이 급등했으나 아직 주도주 아닌 종목 (조기 매집 포착)
            stmt = stmt.where(models.IndicatorScore.score_flow >= 7)
            stmt = stmt.where(models.IndicatorScore.score_total < 60)
        elif screen_norm == "bottom_escape":
            # 바닥 탈출: 기술적 반등 신호가 있으나 아직 종합 점수 낮은 종목 (실질 바닥 탈출)
            stmt = stmt.where(models.IndicatorScore.score_tech >= 6)
            stmt = stmt.where(models.IndicatorScore.score_total < 55)
        elif screen_norm == "crash_risk":
            # 급락 위험: Negative Filter 역점수 낮음 = 위험 신호 다수
            stmt = stmt.where(models.IndicatorScore.score_growth <= 3)

        # ── 스크린 정렬 ──────────────────────────────────────────────────────
        if screen_norm == "crash_risk":
            # 급락 위험: 점수 낮은 종목 우선 (위험 신호 상위)
            sort_col = _score_col(SCREEN_SORT.get(screen_norm, "score_total"))
            stmt = stmt.order_by(sort_col, models.Stock.code)
        elif screen_norm in SCREEN_SORT:
            sort_col = _score_col(SCREEN_SORT[screen_norm])
            stmt = stmt.order_by(desc(sort_col), models.Stock.code)
        else:
            stmt = stmt.order_by(desc(models.IndicatorScore.score_total), models.Stock.code)

        rows = db.execute(stmt.limit(30)).all()

        items: list[dict] = []
        for code, name, score_total in rows:
            try:
                quote = kis_client.inquire_price(
                    app_key=str(profile.app_key),
                    app_secret=str(profile.app_secret),
                    is_paper=bool(getattr(profile, "is_paper", False)),
                    code=str(code),
                    live_base_url=settings.kis_live_base_url,
                    paper_base_url=settings.kis_paper_base_url,
                    timeout_seconds=5.0,
                )
            except Exception as exc:
                raise HTTPException(status_code=503, detail=f"KIS 시세 조회 실패: {exc}") from exc

            items.append(
                {
                    "name": str(name),
                    "code": str(code),
                    "price": float(quote.price),
                    "changeRate": float(quote.change_rate),
                    "score": int(score_total or 0),
                }
            )

        return {"items": items, "screen": screen_norm or None}
    finally:
        db.close()


@app.get("/api/stocks/{code}")
def stock_detail(code: str, current_user=Depends(get_current_user)):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")
    stock_code = (code or "").strip()
    if not stock_code:
        raise HTTPException(status_code=400, detail="code is required")

    user_id = int(current_user.id)
    db: Session = apollo_db.get_session_factory()()
    try:
        profile = db.execute(select(models.KisProfile).where(models.KisProfile.user_id == user_id)).scalar_one_or_none()
        if not (profile and getattr(profile, "app_key", None) and getattr(profile, "app_secret", None)):
            raise HTTPException(status_code=400, detail="KIS 연결 필요")

        stock = db.execute(select(models.Stock).where(models.Stock.code == stock_code)).scalar_one_or_none()
        if stock is None:
            raise HTTPException(status_code=404, detail="Stock not found")

        score_row = db.execute(
            select(models.IndicatorScore)
            .where(models.IndicatorScore.stock_code == stock_code)
            .order_by(desc(models.IndicatorScore.scoring_date), desc(models.IndicatorScore.created_at))
            .limit(1)
        ).scalar_one_or_none()

        try:
            quote = kis_client.inquire_price(
                app_key=str(profile.app_key),
                app_secret=str(profile.app_secret),
                is_paper=bool(getattr(profile, "is_paper", False)),
                code=stock_code,
                live_base_url=settings.kis_live_base_url,
                paper_base_url=settings.kis_paper_base_url,
                timeout_seconds=5.0,
            )
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"KIS 시세 조회 실패: {exc}") from exc

        score_total = int(getattr(score_row, "score_total", 0) or 0)
        return {
            "name": str(stock.name),
            "code": stock_code,
            "price": float(quote.price),
            "changeRate": float(quote.change_rate),
            "score": score_total,
            "indicators": {
                "value": int(getattr(score_row, "score_value", 0) or 0),
                "flow": int(getattr(score_row, "score_flow", 0) or 0),
                "profit": int(getattr(score_row, "score_profit", 0) or 0),
                "growth": int(getattr(score_row, "score_growth", 0) or 0),
                "tech": int(getattr(score_row, "score_tech", 0) or 0),
            },
        }
    finally:
        db.close()


@app.get("/api/stocks/{code}/daily")
def stock_daily_prices(code: str, limit: int = 400, current_user=Depends(get_current_user)):
    """DB-backed daily OHLCV for fast in-app charts.

    This endpoint intentionally does NOT call KIS, so the UI can render charts
    even when real-time quote/token is temporarily unavailable.
    """

    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")

    stock_code = (code or "").strip()
    if not stock_code:
        raise HTTPException(status_code=400, detail="code is required")

    lim = int(limit or 0)
    if lim <= 0:
        lim = 400
    lim = min(max(lim, 50), 2000)

    db: Session = apollo_db.get_session_factory()()
    try:
        rows = db.execute(
            select(
                models.DailyPrice.trading_date,
                models.DailyPrice.open_price,
                models.DailyPrice.high_price,
                models.DailyPrice.low_price,
                models.DailyPrice.close_price,
                models.DailyPrice.volume,
            )
            .where(models.DailyPrice.stock_code == stock_code)
            .order_by(desc(models.DailyPrice.trading_date))
            .limit(lim)
        ).all()

        # Return ascending time order for chart libraries.
        items: list[dict] = []
        for trading_date, o, h, l, c, v in reversed(rows):
            items.append(
                {
                    "time": (trading_date.isoformat() if trading_date else None),
                    "open": float(o),
                    "high": float(h),
                    "low": float(l),
                    "close": float(c),
                    "volume": int(v or 0),
                }
            )

        return {"code": stock_code, "items": items}
    finally:
        db.close()


@app.get("/api/version")
def get_version():
    return {"service": "apollo-backend"}


@app.get("/api/db/health")
def db_health():
    if apollo_db is None:
        raise HTTPException(status_code=500, detail="DB module not available")
    try:
        return apollo_db.healthcheck()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"DB healthcheck failed: {exc}") from exc


@app.get("/api/kis/health")
def kis_health(current_user=Depends(get_current_user)):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")

    user_id = int(current_user.id)
    db: Session = apollo_db.get_session_factory()()
    try:
        profile = db.execute(select(models.KisProfile).where(models.KisProfile.user_id == user_id)).scalar_one_or_none()
        if profile is None or not profile.app_key or not profile.app_secret:
            raise HTTPException(status_code=400, detail="KIS profile not configured")

        try:
            _token, expires_in = kis_client.get_access_token(
                app_key=str(profile.app_key),
                app_secret=str(profile.app_secret),
                is_paper=bool(profile.is_paper),
                live_base_url=settings.kis_live_base_url,
                paper_base_url=settings.kis_paper_base_url,
            )
        except kis_client.KisError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        return {
            "ok": True,
            "isPaper": bool(profile.is_paper),
            "baseUrl": (settings.kis_paper_base_url if profile.is_paper else settings.kis_live_base_url),
            "tokenExpiresIn": int(expires_in),
        }
    finally:
        db.close()


@app.get("/api/kis/quote/{code}")
def kis_quote(code: str, current_user=Depends(get_current_user)):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")

    user_id = int(current_user.id)
    db: Session = apollo_db.get_session_factory()()
    try:
        profile = db.execute(select(models.KisProfile).where(models.KisProfile.user_id == user_id)).scalar_one_or_none()
        if profile is None or not profile.app_key or not profile.app_secret:
            raise HTTPException(status_code=400, detail="KIS profile not configured")
        try:
            quote = kis_client.inquire_price(
                app_key=str(profile.app_key),
                app_secret=str(profile.app_secret),
                is_paper=bool(profile.is_paper),
                code=code,
                live_base_url=settings.kis_live_base_url,
                paper_base_url=settings.kis_paper_base_url,
            )
        except kis_client.KisError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        return {
            "code": quote.code,
            "price": quote.price,
            "change": quote.change,
            "changeRate": quote.change_rate,
            "asOf": quote.as_of,
            "source": "kis",
        }
    finally:
        db.close()


@app.post("/api/auth/login")
def login(request: Request, payload: dict = Body(...)):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")

    email = (payload.get("email") or "").strip()
    password = payload.get("password") or ""
    if not email or not password:
        raise HTTPException(status_code=400, detail="email and password are required")

    db: Session = apollo_db.get_session_factory()()
    try:
        user = db.execute(select(models.User).where(models.User.email == email)).scalar_one_or_none()
        if user is None or not user.is_active:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        if not auth.verify_password(password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        # Record login history (best-effort; should never block login).
        try:
            ip = request.client.host if request.client else None
            user_agent = request.headers.get("user-agent")
            db.add(models.LoginHistory(user_id=int(user.id), event="login", ip=ip, user_agent=user_agent))
            db.commit()
        except Exception:
            db.rollback()

        token = auth.create_access_token(subject=str(user.id), secret=settings.jwt_secret, expires_minutes=settings.jwt_expire_minutes)
        return {
            "accessToken": token,
            "tokenType": "bearer",
            "user": {
                "id": int(user.id),
                "email": user.email,
                "nickname": user.nickname,
                "role": user.role,
            },
        }
    finally:
        db.close()


@app.post("/api/dev/auto-login")
def dev_auto_login(request: Request):
    """Local-only convenience endpoint to skip the login screen.

    Guardrails:
    - Disabled by default; requires ALLOW_LOCAL_AUTO_LOGIN=1
    - Only accepts loopback clients (127.0.0.1 / ::1)
    - Issues a normal JWT for an existing, active user (LOCAL_AUTO_LOGIN_EMAIL)

    This endpoint must never be enabled on publicly reachable hosts.
    """

    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")

    if not getattr(settings, "allow_local_auto_login", False):
        raise HTTPException(status_code=404, detail="Not Found")

    client_ip = request.client.host if request.client else None
    if client_ip not in {"127.0.0.1", "::1"}:
        raise HTTPException(status_code=403, detail="Forbidden")

    email = (getattr(settings, "local_auto_login_email", "administrator") or "administrator").strip()
    if not email:
        raise HTTPException(status_code=400, detail="LOCAL_AUTO_LOGIN_EMAIL is empty")

    db: Session = apollo_db.get_session_factory()()
    try:
        user = db.execute(select(models.User).where(models.User.email == email)).scalar_one_or_none()
        if user is None or not user.is_active:
            raise HTTPException(status_code=404, detail="Auto-login user not found or inactive")

        # Record login history (best-effort).
        try:
            user_agent = request.headers.get("user-agent")
            db.add(models.LoginHistory(user_id=int(user.id), event="login", ip=client_ip, user_agent=user_agent))
            db.commit()
        except Exception:
            db.rollback()

        token = auth.create_access_token(subject=str(user.id), secret=settings.jwt_secret, expires_minutes=settings.jwt_expire_minutes)
        return {
            "accessToken": token,
            "tokenType": "bearer",
            "user": {
                "id": int(user.id),
                "email": user.email,
                "nickname": user.nickname,
                "role": user.role,
            },
        }
    finally:
        db.close()


@app.post("/api/auth/refresh")
def refresh_token(current_user=Depends(get_current_user_for_refresh)):
    """Issue a new access token for the current user.

    This endpoint exists mainly for admin-token auto refresh (14-3), but it is safe
    for any authenticated user.
    """

    token = auth.create_access_token(subject=str(current_user.id), secret=settings.jwt_secret, expires_minutes=settings.jwt_expire_minutes)
    return {
        "accessToken": token,
        "tokenType": "bearer",
        "user": {
            "id": int(current_user.id),
            "email": current_user.email,
            "nickname": current_user.nickname,
            "role": current_user.role,
        },
    }


@app.post("/api/auth/logout")
def logout(request: Request, current_user=Depends(get_current_user)):
    """Record logout history (best-effort)."""

    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")

    db: Session = apollo_db.get_session_factory()()
    try:
        try:
            ip = request.client.host if request.client else None
            user_agent = request.headers.get("user-agent")
            db.add(models.LoginHistory(user_id=int(current_user.id), event="logout", ip=ip, user_agent=user_agent))
            db.commit()
        except Exception:
            db.rollback()
        return {"ok": True}
    finally:
        db.close()


@app.get("/api/admin/users")
def admin_list_users(_admin=Depends(require_admin)):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")

    db: Session = apollo_db.get_session_factory()()
    try:
        rows = db.execute(
            select(models.User, models.KisProfile.id)
            .outerjoin(models.KisProfile, models.KisProfile.user_id == models.User.id)
            .order_by(desc(models.User.created_at))
        ).all()
        return {
            "items": [
                {
                    "id": int(u.id),
                    "email": u.email,
                    "nickname": u.nickname,
                    "role": u.role,
                    "isActive": bool(u.is_active),
                    "kisConfigured": bool(profile_id is not None),
                    "createdAt": (u.created_at.isoformat() if u.created_at else None),
                }
                for (u, profile_id) in rows
            ]
        }
    finally:
        db.close()


@app.post("/api/admin/users")
def admin_create_user(payload: dict = Body(...), _admin=Depends(require_admin)):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")

    email = (payload.get("email") or "").strip()
    password = payload.get("password") or ""
    nickname = (payload.get("nickname") or "").strip() or None
    role = (payload.get("role") or "user").strip() or "user"
    is_active = payload.get("isActive")
    if is_active is None:
        is_active = True
    if isinstance(is_active, str):
        is_active = is_active.strip().lower() not in {"0", "false", "no", "off", ""}
    else:
        is_active = bool(is_active)

    if not email or not password:
        raise HTTPException(status_code=400, detail="email and password are required")
    if role not in {"user", "admin"}:
        raise HTTPException(status_code=400, detail="role must be 'user' or 'admin'")

    db: Session = apollo_db.get_session_factory()()
    try:
        existing = db.execute(select(models.User).where(models.User.email == email)).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(status_code=409, detail="Email already exists")

        user = models.User(
            email=email,
            nickname=nickname,
            password_hash=auth.hash_password(password),
            role=role,
            is_active=is_active,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        return {
            "id": int(user.id),
            "email": user.email,
            "nickname": user.nickname,
            "role": user.role,
            "isActive": bool(user.is_active),
            "kisConfigured": False,
            "createdAt": (user.created_at.isoformat() if user.created_at else None),
        }
    finally:
        db.close()


@app.get("/api/admin/users/{user_id}/kis-profile")
def admin_get_user_kis_profile(user_id: int, _admin=Depends(require_admin)):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")

    db: Session = apollo_db.get_session_factory()()
    try:
        user = db.execute(select(models.User).where(models.User.id == int(user_id))).scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        profile = db.execute(select(models.KisProfile).where(models.KisProfile.user_id == int(user_id))).scalar_one_or_none()
        cano, prdt = _parse_kis_account(profile.account_prefix if profile else None)
        return {
            "userId": int(user_id),
            "appKey": (profile.app_key if profile else None),
            "accountPrefix": cano,
            "accountProductCode": (prdt or "01") if cano else None,
            "tradeType": ("모의투자" if (profile and profile.is_paper) else "실계좌"),
            "hasAppSecret": bool(profile and profile.app_secret),
        }
    finally:
        db.close()


@app.put("/api/admin/users/{user_id}/kis-profile")
def admin_upsert_user_kis_profile(user_id: int, payload: dict = Body(...), _admin=Depends(require_admin)):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")

    # NOTE: treat missing keys as "no change" to avoid wiping existing values.
    app_key_raw = payload.get("appKey", None)
    app_secret_raw = payload.get("appSecret", None)
    account_prefix_raw = payload.get("accountPrefix", payload.get("accountNo", None))
    account_prdt_raw = payload.get("accountProductCode", payload.get("accountPrdtCd", None))
    trade_type_raw = payload.get("tradeType", None)

    with apollo_db.session_scope() as session:
        user = session.execute(select(models.User).where(models.User.id == int(user_id))).scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        profile = session.execute(select(models.KisProfile).where(models.KisProfile.user_id == int(user_id))).scalar_one_or_none()
        if profile is None:
            profile = models.KisProfile(user_id=int(user_id))
            session.add(profile)

        if app_key_raw is not None:
            profile.app_key = (str(app_key_raw).strip() or None)

        if (account_prefix_raw is not None) or (account_prdt_raw is not None):
            existing_cano, existing_prdt = _parse_kis_account(profile.account_prefix)
            next_cano = existing_cano
            next_prdt = existing_prdt

            if account_prefix_raw is not None:
                next_cano, embedded_prdt = _parse_kis_account(str(account_prefix_raw))
                if embedded_prdt:
                    next_prdt = embedded_prdt

            if account_prdt_raw is not None:
                raw = str(account_prdt_raw).strip()
                if raw:
                    next_prdt = raw

            profile.account_prefix = _format_kis_account(next_cano, next_prdt)

        if trade_type_raw is not None:
            trade_type = str(trade_type_raw).strip() or "실계좌"
            profile.is_paper = trade_type != "실계좌"

        if app_secret_raw is not None:
            # Do not return the secret via any endpoint; only allow overwriting when explicitly provided.
            app_secret = str(app_secret_raw).strip()
            if app_secret:
                profile.app_secret = app_secret

        return {
            "ok": True,
            "userId": int(user_id),
            "kisConfigured": bool(profile.app_key and profile.app_secret and profile.account_prefix),
        }


@app.put("/api/admin/users/{user_id}/activation")
def admin_set_user_activation(user_id: int, payload: dict = Body(...), _admin=Depends(require_admin)):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")

    if "isActive" not in payload:
        raise HTTPException(status_code=400, detail="isActive is required")

    is_active = payload.get("isActive")
    if isinstance(is_active, str):
        is_active = is_active.strip().lower() not in {"0", "false", "no", "off", ""}
    else:
        is_active = bool(is_active)

    with apollo_db.session_scope() as session:
        user = session.execute(select(models.User).where(models.User.id == int(user_id))).scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        user.is_active = bool(is_active)
        return {"ok": True, "userId": int(user_id), "isActive": bool(user.is_active)}


@app.post("/api/admin/users/{user_id}/reset-password")
def admin_reset_user_password(user_id: int, payload: dict = Body(default={}), _admin=Depends(require_admin)):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")

    requested = payload.get("password") if isinstance(payload, dict) else None
    new_password = (str(requested).strip() if requested is not None else "")
    generated = False
    if not new_password:
        alphabet = string.ascii_letters + string.digits
        new_password = "".join(secrets.choice(alphabet) for _ in range(12))
        generated = True

    with apollo_db.session_scope() as session:
        user = session.execute(select(models.User).where(models.User.id == int(user_id))).scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        user.password_hash = auth.hash_password(new_password)

        return {
            "ok": True,
            "userId": int(user_id),
            "tempPassword": (new_password if generated else None),
        }


@app.get("/api/admin/users/{user_id}/automation")
def admin_get_user_automation(user_id: int, _admin=Depends(require_admin)):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")

    db: Session = apollo_db.get_session_factory()()
    try:
        user = db.execute(select(models.User).where(models.User.id == int(user_id))).scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        sa_cfg = db.execute(select(models.SaAutoTradingConfig).where(models.SaAutoTradingConfig.user_id == int(user_id))).scalar_one_or_none()
        plus_cfg = db.execute(select(models.PlusAutoTradingConfig).where(models.PlusAutoTradingConfig.user_id == int(user_id))).scalar_one_or_none()
        sv_cfg = db.execute(select(models.SvAgentConfig).where(models.SvAgentConfig.user_id == int(user_id))).scalar_one_or_none()

        return {
            "userId": int(user_id),
            "saEnabled": bool(sa_cfg.enabled) if sa_cfg else False,
            "plusEnabled": bool(plus_cfg.enabled) if plus_cfg else False,
            "svEnabled": bool(sv_cfg.enabled) if sv_cfg else False,
        }
    finally:
        db.close()


@app.put("/api/admin/users/{user_id}/automation")
def admin_set_user_automation(user_id: int, payload: dict = Body(...), _admin=Depends(require_admin)):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")

    allowed_keys = {"saEnabled", "plusEnabled", "svEnabled"}
    if not isinstance(payload, dict) or not any(k in payload for k in allowed_keys):
        raise HTTPException(status_code=400, detail="Provide at least one of saEnabled, plusEnabled, svEnabled")

    def coerce_bool(v) -> bool:
        if isinstance(v, str):
            return v.strip().lower() not in {"0", "false", "no", "off", ""}
        return bool(v)

    with apollo_db.session_scope() as session:
        user = session.execute(select(models.User).where(models.User.id == int(user_id))).scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        sa_cfg = session.execute(select(models.SaAutoTradingConfig).where(models.SaAutoTradingConfig.user_id == int(user_id))).scalar_one_or_none()
        plus_cfg = session.execute(select(models.PlusAutoTradingConfig).where(models.PlusAutoTradingConfig.user_id == int(user_id))).scalar_one_or_none()
        sv_cfg = session.execute(select(models.SvAgentConfig).where(models.SvAgentConfig.user_id == int(user_id))).scalar_one_or_none()

        if "saEnabled" in payload:
            if sa_cfg is None:
                sa_cfg = models.SaAutoTradingConfig(user_id=int(user_id))
                session.add(sa_cfg)
            sa_cfg.enabled = coerce_bool(payload.get("saEnabled"))

        if "plusEnabled" in payload:
            if plus_cfg is None:
                plus_cfg = models.PlusAutoTradingConfig(user_id=int(user_id))
                session.add(plus_cfg)
            plus_cfg.enabled = coerce_bool(payload.get("plusEnabled"))

        if "svEnabled" in payload:
            if sv_cfg is None:
                sv_cfg = models.SvAgentConfig(user_id=int(user_id))
                session.add(sv_cfg)
            sv_cfg.enabled = coerce_bool(payload.get("svEnabled"))

        return {
            "ok": True,
            "userId": int(user_id),
            "saEnabled": bool(sa_cfg.enabled) if sa_cfg else False,
            "plusEnabled": bool(plus_cfg.enabled) if plus_cfg else False,
            "svEnabled": bool(sv_cfg.enabled) if sv_cfg else False,
        }


@app.get("/api/admin/login-history")
def admin_login_history(limit: int = 200, startDate: str = None, endDate: str = None, _admin=Depends(require_admin)):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")

    limit = max(1, min(int(limit or 200), 1000))

    start_dt = None
    end_dt_exclusive = None
    try:
        if startDate:
            d = date.fromisoformat(startDate)
            start_dt = datetime.combine(d, datetime.min.time())
        if endDate:
            d = date.fromisoformat(endDate)
            end_dt_exclusive = datetime.combine(d + timedelta(days=1), datetime.min.time())
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid startDate/endDate; expected YYYY-MM-DD") from exc

    db: Session = apollo_db.get_session_factory()()
    try:
        stmt = (
            select(models.LoginHistory, models.User.email)
            .outerjoin(models.User, models.User.id == models.LoginHistory.user_id)
            .order_by(desc(models.LoginHistory.at))
        )

        if start_dt is not None:
            stmt = stmt.where(models.LoginHistory.at >= start_dt)
        if end_dt_exclusive is not None:
            stmt = stmt.where(models.LoginHistory.at < end_dt_exclusive)

        stmt = stmt.limit(limit)
        rows = db.execute(
            stmt
        ).all()
        return {
            "items": [
                {
                    "id": int(r.id),
                    "userId": (int(r.user_id) if r.user_id is not None else None),
                    "email": email,
                    "event": r.event,
                    "ip": r.ip,
                    "userAgent": r.user_agent,
                    "at": (r.at.isoformat() if r.at else None),
                }
                for (r, email) in rows
            ]
        }
    finally:
        db.close()


@app.get("/api/admin/engine-logs")
def admin_engine_logs(
    limit: int = 200,
    userId: int = None,
    engine: str = None,
    event: str = None,
    _admin=Depends(require_admin),
):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")

    limit = max(1, min(int(limit or 200), 1000))

    db: Session = apollo_db.get_session_factory()()
    try:
        stmt = (
            select(models.AutomationEngineLog, models.User.email)
            .outerjoin(models.User, models.User.id == models.AutomationEngineLog.user_id)
            .order_by(desc(models.AutomationEngineLog.at))
        )

        if userId is not None:
            stmt = stmt.where(models.AutomationEngineLog.user_id == int(userId))
        if engine:
            stmt = stmt.where(models.AutomationEngineLog.engine == str(engine))
        if event:
            stmt = stmt.where(models.AutomationEngineLog.event == str(event))

        stmt = stmt.limit(limit)
        rows = db.execute(stmt).all()
        return {
            "items": [
                {
                    "id": int(r.id),
                    "userId": int(r.user_id),
                    "email": email,
                    "engine": r.engine,
                    "event": r.event,
                    "message": r.message,
                    "at": (r.at.isoformat() if r.at else None),
                }
                for (r, email) in rows
            ]
        }
    finally:
        db.close()


@app.post("/api/admin/engine/kill-switch")
def admin_set_runtime_kill_switch(payload: dict = Body(...), _admin=Depends(require_admin)):
    """Set a runtime kill switch override (no restart).

    Payload:
    - {"enabled": true}  -> force kill switch ON
    - {"enabled": false} -> force kill switch OFF
    - {"enabled": null}  -> reset to env-based settings
    """

    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")

    global _runtime_kill_switch
    enabled = payload.get("enabled")
    prev = _runtime_kill_switch
    if enabled is None:
        _runtime_kill_switch = None
    else:
        _runtime_kill_switch = bool(enabled)

    try:
        with apollo_db.session_scope() as session:
            session.add(
                models.AutomationEngineLog(
                    user_id=int(_admin.id),
                    engine="basic",
                    event="kill_switch",
                    message=(
                        f"runtime kill switch changed: {prev} -> {_runtime_kill_switch}; "
                        f"env={bool(settings.autotrading_kill_switch)}; effective={_is_kill_switch_on()}"
                    ),
                )
            )
    except Exception:
        pass

    return {
        "ok": True,
        "runtimeKillSwitch": _runtime_kill_switch,
        "envKillSwitch": bool(settings.autotrading_kill_switch),
        "effectiveKillSwitch": _is_kill_switch_on(),
    }


@app.post("/api/admin/engine/tick-once")
def admin_engine_tick_once(payload: dict = Body(...), _admin=Depends(require_admin)):
    """Run a single engine tick for validation/debug.

    Safety:
    - Block when paper trading profile is used (would place paper orders).
    - Block when AUTOTRADING_LIVE_ORDERS=1 (would allow real orders).

    Intended for confirming that config changes are picked up by the engine loop.
    """

    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")

    raw_user_id = payload.get("userId")
    if raw_user_id is None:
        raise HTTPException(status_code=400, detail="userId is required")
    try:
        user_id = int(raw_user_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="userId must be an integer") from exc

    engines_raw = payload.get("engines")
    if engines_raw is None:
        engines = ["sa", "plus"]
    elif isinstance(engines_raw, str):
        engines = [engines_raw]
    elif isinstance(engines_raw, list):
        engines = [str(x) for x in engines_raw]
    else:
        raise HTTPException(status_code=400, detail="engines must be a string or list")

    allowed = {"sa", "plus"}
    engines = [e for e in engines if e in allowed]
    if not engines:
        raise HTTPException(status_code=400, detail="engines must include 'sa' and/or 'plus'")

    if settings.autotrading_live_orders:
        raise HTTPException(status_code=400, detail="Manual tick is disabled when AUTOTRADING_LIVE_ORDERS=1")

    if _is_kill_switch_on():
        raise HTTPException(status_code=400, detail="Manual tick is disabled when AUTOTRADING_KILL_SWITCH=1")

    now = datetime.now()

    def _effective_max_positions(cfg_obj: dict | None) -> int:
        max_positions = 5
        try:
            raw = (cfg_obj or {}).get("maxPositions")
            if raw is not None:
                max_positions = int(raw)
        except Exception:
            max_positions = 5
        if max_positions < 1:
            max_positions = 1
        if max_positions > 50:
            max_positions = 50
        return int(max_positions)

    def _effective_budgets(cfg_obj: dict | None) -> dict:
        return {
            "perStockBudget": _parse_positive_int_like((cfg_obj or {}).get("perStockBudget")),
            "totalBudget": _parse_positive_int_like((cfg_obj or {}).get("totalBudget")),
        }

    with apollo_db.session_scope() as session:
        user = session.execute(select(models.User).where(models.User.id == int(user_id))).scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        profile = session.execute(select(models.KisProfile).where(models.KisProfile.user_id == int(user_id))).scalar_one_or_none()
        if profile is not None and bool(getattr(profile, "is_paper", False)):
            raise HTTPException(status_code=400, detail="Manual tick is disabled for paper trading profiles")

        # Log a marker so we can correlate config->tick outside market hours.
        try:
            sa_cfg = session.execute(select(models.SaAutoTradingConfig).where(models.SaAutoTradingConfig.user_id == int(user_id))).scalar_one_or_none()
            plus_cfg = session.execute(select(models.PlusAutoTradingConfig).where(models.PlusAutoTradingConfig.user_id == int(user_id))).scalar_one_or_none()

            sa_cfg_obj = (sa_cfg.config if sa_cfg else None)
            if not isinstance(sa_cfg_obj, dict):
                sa_cfg_obj = None
            plus_cfg_obj = (plus_cfg.config if plus_cfg else None)
            if not isinstance(plus_cfg_obj, dict):
                plus_cfg_obj = None

            snap = {
                "saEnabled": bool(sa_cfg.enabled) if sa_cfg else False,
                "plusEnabled": bool(plus_cfg.enabled) if plus_cfg else False,
                "saConfig": (sa_cfg.config if sa_cfg else None),
                "plusConfig": (plus_cfg.config if plus_cfg else None),
                "saEffective": {"maxPositions": _effective_max_positions(sa_cfg_obj), **_effective_budgets(sa_cfg_obj)},
                "plusEffective": {"maxPositions": _effective_max_positions(plus_cfg_obj), **_effective_budgets(plus_cfg_obj)},
            }
            session.add(
                models.AutomationEngineLog(
                    user_id=int(user_id),
                    engine="basic",
                    event="manual_tick",
                    message=f"manual tick requested; engines={engines}; snapshot={snap}",
                )
            )
        except Exception:
            pass

        ran: list[str] = []
        for e in engines:
            if e == "sa":
                try:
                    session.add(models.AutomationEngineLog(user_id=int(user_id), engine="sa", event="manual_tick", message=None))
                    _run_sa_engine_tick(session, user_id=int(user_id), profile=profile, now=now)
                    ran.append("sa")
                except Exception as exc:
                    session.add(models.AutomationEngineLog(user_id=int(user_id), engine="sa", event="error", message=str(exc)))
            elif e == "plus":
                try:
                    session.add(models.AutomationEngineLog(user_id=int(user_id), engine="plus", event="manual_tick", message=None))
                    _run_plus_engine_tick(session, user_id=int(user_id), profile=profile, now=now)
                    ran.append("plus")
                except Exception as exc:
                    session.add(models.AutomationEngineLog(user_id=int(user_id), engine="plus", event="error", message=str(exc)))

    return {"ok": True, "userId": int(user_id), "engines": ran, "at": now.isoformat()}


@app.get("/api/profile")
def get_profile(current_user=Depends(get_current_user)):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")

    user_id = int(current_user.id)
    db: Session = apollo_db.get_session_factory()()
    try:
        user = db.execute(select(models.User).where(models.User.id == user_id)).scalar_one_or_none()
        profile = db.execute(select(models.KisProfile).where(models.KisProfile.user_id == user_id)).scalar_one_or_none()
        has_app_secret = bool(profile and profile.app_secret and str(profile.app_secret).strip())
        cano, prdt = _parse_kis_account(profile.account_prefix if profile else None)
        return {
            "nickname": (user.nickname if user else None),
            "kis": {
                "appKey": (profile.app_key if profile else None),
                "hasAppSecret": has_app_secret,
                "accountPrefix": cano,
                "accountProductCode": (prdt or "01") if cano else None,
                "tradeType": ("모의투자" if (profile and profile.is_paper) else "실계좌"),
            },
        }
    finally:
        db.close()


@app.post("/api/profile")
def upsert_profile(payload: dict = Body(...), current_user=Depends(get_current_user)):
    if apollo_db is None or models is None:
        raise HTTPException(status_code=500, detail="DB module not available")

    user_id = int(current_user.id)
    nickname = (payload.get("nickname") or "").strip() or None
    app_key = (payload.get("appKey") or "").strip() or None
    raw_secret = payload.get("appSecret")
    app_secret = (str(raw_secret).strip() if raw_secret is not None else "")
    account_prefix_raw = (payload.get("accountPrefix") or payload.get("accountNo") or "").strip() or None
    account_prdt_raw = (payload.get("accountProductCode") or payload.get("accountPrdtCd") or "").strip() or None
    trade_type = (payload.get("tradeType") or "").strip() or "실계좌"
    is_paper = trade_type != "실계좌"

    with apollo_db.session_scope() as session:
        user = session.execute(select(models.User).where(models.User.id == user_id)).scalar_one_or_none()
        if user is not None:
            user.nickname = nickname

        profile = session.execute(select(models.KisProfile).where(models.KisProfile.user_id == user_id)).scalar_one_or_none()
        if profile is None:
            profile = models.KisProfile(user_id=user_id)
            session.add(profile)

        profile.app_key = app_key
        if app_secret:
            profile.app_secret = app_secret
        # Normalize and store as "CANO-PRDT" when product code is provided.
        embedded_cano, embedded_prdt = _parse_kis_account(account_prefix_raw)
        cano = embedded_cano
        prdt = embedded_prdt
        if account_prdt_raw:
            prdt = account_prdt_raw
        profile.account_prefix = _format_kis_account(cano, prdt)
        profile.is_paper = is_paper

    return {"ok": True}


# ---------------------------------------------------------------------------
# Macro Data – US Treasury Yields & Dollar Index
# ---------------------------------------------------------------------------

@app.get("/api/macro/us-bonds")
def get_macro_us_bonds():
    """미국채 10년·30년 일봉 + 도미넌스(10Y/30Y%) + 볼린저밴드(20,2) + RSI(14).

    데이터 소스: Yahoo Finance (^TNX, ^TYX) — yfinance
    인증 불필요 (공개 매크로 데이터).
    """
    try:
        import yfinance as yf  # type: ignore
        import pandas as pd    # type: ignore
        import math

        raw = yf.download("^TNX ^TYX", period="72d", interval="1d",
                          progress=False, auto_adjust=False)
        close = raw["Close"]
        opn   = raw["Open"]
        high  = raw["High"]
        low   = raw["Low"]

        tnx_c = close["^TNX"].dropna()
        tyx_c = close["^TYX"].dropna()

        # ── Bollinger 20 / 2σ on TNX ──────────────────────────────────────
        sma20  = tnx_c.rolling(20).mean()
        std20  = tnx_c.rolling(20).std()
        bb_up  = sma20 + 2 * std20
        bb_lo  = sma20 - 2 * std20

        # ── RSI 14 on TNX ─────────────────────────────────────────────────
        delta = tnx_c.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rs    = gain / loss.replace(0, float("nan"))
        rsi14 = 100 - (100 / (1 + rs))

        def ts(idx):
            return idx.strftime("%Y-%m-%d")

        def _v(val):
            return None if (val is None or (isinstance(val, float) and math.isnan(val))) else round(float(val), 4)

        # ── build OHLCV for TNX ───────────────────────────────────────────
        tnx_rows = []
        for i in tnx_c.index:
            o = _v(opn["^TNX"].get(i))
            h = _v(high["^TNX"].get(i))
            l = _v(low["^TNX"].get(i))
            c = _v(tnx_c.get(i))
            if c is None:
                continue
            tnx_rows.append({"time": ts(i), "open": o or c, "high": h or c, "low": l or c, "close": c})

        tyx_rows = []
        for i in tyx_c.index:
            c = _v(tyx_c.get(i))
            if c is None:
                continue
            tyx_rows.append({"time": ts(i), "value": c})

        # ── dominance (10Y / 30Y * 100) ───────────────────────────────────
        dom_rows = []
        for i in tnx_c.index:
            t10 = _v(tnx_c.get(i))
            t30 = _v(tyx_c.get(i))
            if t10 is None or t30 is None or t30 == 0:
                continue
            dom_rows.append({"time": ts(i), "value": round(t10 / t30 * 100, 4)})

        bb_rows = []
        for i in tnx_c.index:
            c  = _v(tnx_c.get(i))
            u  = _v(bb_up.get(i))
            m  = _v(sma20.get(i))
            lo = _v(bb_lo.get(i))
            if c is None or u is None:
                continue
            bb_rows.append({"time": ts(i), "upper": u, "middle": m, "lower": lo})

        rsi_rows = []
        for i in rsi14.index:
            v = _v(rsi14.get(i))
            if v is None:
                continue
            rsi_rows.append({"time": ts(i), "value": v})

        return {
            "asOf": ts(tnx_c.index[-1]) if len(tnx_c) else None,
            "tnx":  tnx_rows,
            "tyx":  tyx_rows,
            "dominance": dom_rows,
            "bb":   bb_rows,
            "rsi":  rsi_rows,
        }

    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"us-bonds 데이터 조회 실패: {exc}") from exc


@app.get("/api/macro/dxy")
def get_macro_dxy():
    """달러 인덱스(DXY) 일봉 OHLCV.

    데이터 소스: Yahoo Finance (DX-Y.NYB) — yfinance
    인증 불필요.
    """
    try:
        import yfinance as yf  # type: ignore
        import math

        raw = yf.download("DX-Y.NYB", period="72d", interval="1d",
                          progress=False, auto_adjust=False)

        def ts(idx):
            return idx.strftime("%Y-%m-%d")

        def _v(val):
            return None if (val is None or (isinstance(val, float) and math.isnan(val))) else round(float(val), 4)

        rows = []
        opn_s  = raw["Open"]["DX-Y.NYB"]
        high_s = raw["High"]["DX-Y.NYB"]
        low_s  = raw["Low"]["DX-Y.NYB"]
        close_s = raw["Close"]["DX-Y.NYB"]

        for i in close_s.index:
            o  = _v(float(opn_s[i]))
            h  = _v(float(high_s[i]))
            lo = _v(float(low_s[i]))
            c  = _v(float(close_s[i]))
            if c is None:
                continue
            rows.append({"time": ts(i), "open": o or c, "high": h or c, "low": lo or c, "close": c})

        return {
            "asOf": ts(raw.index[-1]) if len(raw) else None,
            "ohlcv": rows,
        }

    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"DXY 데이터 조회 실패: {exc}") from exc


# ---------------------------------------------------------------------------
# Sector Rotation Engine
# ---------------------------------------------------------------------------
try:
    import sector_rotation as _sector_rotation  # type: ignore
except Exception:  # pragma: no cover
    _sector_rotation = None  # type: ignore[assignment]


@app.get("/api/sector-rotation")
def get_sector_rotation(force: bool = False):
    """KOSPI 섹터 로테이션 나침반.

    7-Layer 점수: 매크로(15%) + 외국인수급(25%) + 기관수급(20%)
                  + 모멘텀(20%) + 뉴스(5%) + 거래대금(10%) + 스마트머니(5%)

    ?force=true 로 캐시 무시 강제 재계산 (약 20~40초 소요)
    인증 불필요.
    """
    if _sector_rotation is None:
        raise HTTPException(status_code=503, detail="sector_rotation 모듈 로드 실패")
    try:
        return _sector_rotation.compute_sector_rotation(force=force)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"섹터 로테이션 계산 실패: {exc}") from exc


DIST_DIR = REPO_ROOT / "frontend" / "dist"


# ---------------------------------------------------------------------------
# AI Chart Analysis
# ---------------------------------------------------------------------------

try:
    import chart_analysis as _chart_analysis
except Exception:  # pragma: no cover
    _chart_analysis = None  # type: ignore[assignment]


from fastapi import UploadFile, File as FastAPIFile
from pydantic import BaseModel as _BaseModel, Field as _Field
from typing import Optional as _Optional, List as _List


def _resolve_ai_provider() -> tuple[str, str, str]:
    """Returns (provider, api_key, model). Auto-selects based on configured keys.

    Priority (auto mode): Gemini → Groq → OpenAI
    """
    ai_prov = os.environ.get("AI_PROVIDER", settings.ai_provider).strip().lower() or "auto"
    gemini_key = os.environ.get("GEMINI_API_KEY", settings.gemini_api_key).strip()
    groq_key = os.environ.get("GROQ_API_KEY", settings.groq_api_key).strip()
    openai_key = os.environ.get("OPENAI_API_KEY", settings.openai_api_key).strip()

    if ai_prov == "auto":
        if gemini_key:
            return "gemini", gemini_key, settings.gemini_model
        if groq_key:
            return "groq", groq_key, settings.groq_model
        if openai_key:
            return "openai", openai_key, settings.openai_model
        return "none", "", ""
    if ai_prov == "gemini":
        return "gemini", gemini_key, settings.gemini_model
    if ai_prov == "groq":
        return "groq", groq_key, settings.groq_model
    return "openai", openai_key, settings.openai_model


class ChartAnalysisRequest(_BaseModel):
    symbol: str = _Field(..., description="\uc885\ubaa9\ucf54\ub4dc (\uc608: '005930', '005930.KS', 'AAPL')")
    period: str = _Field("6mo", description="\uc870\ud68c \uae30\uac04: 1mo/3mo/6mo/1y/2y/5y")
    interval: str = _Field("1d", description="\ubd09 \ub2e8\uc704: 1d/1wk/1mo")
    ohlcv_records: _Optional[_List[dict]] = _Field(None, description="\uc9c1\uc811 OHLCV \ub370\uc774\ud130 \uc81c\uacf5 (JSON array)")


class ChartAnalysisCSVRequest(_BaseModel):
    symbol: str = _Field(..., description="\uc885\ubaa9\ucf54\ub4dc \ub610\ub294 \uc885\ubaa9\uba85 (\uc2dd\ubcc4\uc6a9)")


@app.post("/api/ai/chart-analysis")
async def ai_chart_analysis(
    req: ChartAnalysisRequest,
    _current_user=Depends(get_current_user),
):
    """AI 차트 분석 (yfinance 데이터 또는 직접 제공 OHLCV).

    - symbol만 지정하면 Yahoo Finance에서 데이터 자동 수집
    - ohlcv_records를 제공하면 해당 데이터로 분석
    """
    if _chart_analysis is None:
        raise HTTPException(status_code=503, detail="chart_analysis module not available")

    provider, api_key, model = _resolve_ai_provider()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="AI API key not configured. Set GEMINI_API_KEY / GROQ_API_KEY / OPENAI_API_KEY in backend/.env",
        )

    try:
        result = _chart_analysis.analyze_chart(
            symbol=req.symbol.strip(),
            api_key=api_key,
            model=model,
            provider=provider,
            yfinance_period=req.period if req.ohlcv_records is None else None,
            yfinance_interval=req.interval,
            ohlcv_records=req.ohlcv_records,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"분석 중 오류 발생: {exc}") from exc

    return result


@app.post("/api/ai/chart-analysis/upload")
async def ai_chart_analysis_upload(
    symbol: str,
    file: UploadFile = FastAPIFile(..., description="TradingView CSV 파일"),
    _current_user=Depends(get_current_user),
):
    """TradingView에서 내보낸 CSV 파일을 업로드하여 AI 분석.

    TradingView 차트 → 내보내기 → CSV 다운로드 후 이 엔드포인트에 업로드하세요.
    CSV 형식: time,open,high,low,close[,volume]
    """
    if _chart_analysis is None:
        raise HTTPException(status_code=503, detail="chart_analysis module not available")

    provider, api_key, model = _resolve_ai_provider()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="AI API key not configured. Set GEMINI_API_KEY / GROQ_API_KEY / OPENAI_API_KEY in backend/.env",
        )

    content_type = (file.content_type or "").lower()
    if file.filename and not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="CSV 파일만 업로드 가능합니다")

    MAX_SIZE = 5 * 1024 * 1024  # 5 MB
    raw = await file.read(MAX_SIZE + 1)
    if len(raw) > MAX_SIZE:
        raise HTTPException(status_code=413, detail="파일 크기가 5MB를 초과합니다")

    try:
        result = _chart_analysis.analyze_chart(
            symbol=symbol.strip(),
            api_key=api_key,
            model=model,
            provider=provider,
            csv_content=raw,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"분석 중 오류 발생: {exc}") from exc

    return result


@app.get("/api/ai/chart-analysis/status")
def ai_chart_analysis_status(_current_user=Depends(get_current_user)):
    """AI 차트 분석 기능 사용 가능 여부 확인."""
    provider, api_key, model = _resolve_ai_provider()
    return {
        "available": _chart_analysis is not None and bool(api_key),
        "active_provider": provider if api_key else "none",
        "active_model": model,
        "openai_configured": bool(os.environ.get("OPENAI_API_KEY", settings.openai_api_key).strip()),
        "gemini_configured": bool(os.environ.get("GEMINI_API_KEY", settings.gemini_api_key).strip()),
        "groq_configured": bool(os.environ.get("GROQ_API_KEY", settings.groq_api_key).strip()),
        "module_loaded": _chart_analysis is not None,
    }


class _AiKeyBody(_BaseModel):
    api_key: str
    provider: str = "openai"  # "openai" | "gemini" | "groq"


@app.post("/api/ai/chart-analysis/set-key")
def ai_chart_set_key(body: _AiKeyBody, _current_user=Depends(get_current_user)):
    """AI API 키를 backend/.env에 저장하고 런타임에 즉시 적용."""
    key = body.api_key.strip()
    provider = body.provider.strip().lower()

    # Validate key prefix (Gemini prefix check is optional – key format varies)
    prefix_map = {"openai": "sk-", "groq": "gsk_"}
    prefix = prefix_map.get(provider, "")
    if prefix and not key.startswith(prefix):
        raise HTTPException(
            status_code=400,
            detail=f"올바른 {provider.title()} API 키가 아닙니다 ({prefix}로 시작해야 함)",
        )

    env_var_map = {"openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY"}
    settings_attr_map = {"openai": "openai_api_key", "gemini": "gemini_api_key", "groq": "groq_api_key"}
    env_var = env_var_map.get(provider, "OPENAI_API_KEY")
    attr = settings_attr_map.get(provider, "openai_api_key")

    env_path = REPO_ROOT / "backend" / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    found = False
    for i, line in enumerate(lines):
        if line.startswith(f"{env_var}="):
            lines[i] = f"{env_var}={key}"
            found = True
            break
    if not found:
        lines.append(f"{env_var}={key}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Apply at runtime immediately
    os.environ[env_var] = key
    object.__setattr__(settings, attr, key)

    return {"ok": True, "message": f"{provider.title()} API 키가 저장되었습니다", "provider": provider}


@app.get("/api/ai/diagnose")
def ai_diagnose(_current_user=Depends(get_current_user)):
    """AI 파이프라인 단계별 진단.

    각 단계를 순서대로 점검하여 어느 단계에서 실패했는지 명확히 보여줍니다:
    1. chart_analysis 모듈 로드
    2. API 키 설정 여부
    3. 실제 AI API 연결 테스트 (소형 프롬프트 전송)
    """
    steps: list[dict] = []

    # ── Step 1: Module loaded ──────────────────────────────────────────────
    if _chart_analysis is not None:
        steps.append({"step": "모듈 로드", "ok": True,  "msg": "chart_analysis 정상 로드됨"})
    else:
        steps.append({"step": "모듈 로드", "ok": False, "msg": "chart_analysis 모듈 import 실패 – uvicorn 로그 확인"})
        return {"ok": False, "steps": steps}

    # ── Step 2: API key ────────────────────────────────────────────────────
    provider, api_key, model = _resolve_ai_provider()
    if api_key:
        key_preview = api_key[:6] + "..." + api_key[-4:] if len(api_key) > 10 else "***"
        steps.append({"step": "API 키", "ok": True,  "msg": f"{provider} ({model}) 키 감지됨 [{key_preview}]"})
    else:
        steps.append({"step": "API 키", "ok": False, "msg": "API 키 없음 – 🔑 API 키 설정에서 Gemini/Groq 키를 저장하세요"})
        return {"ok": False, "steps": steps}

    # ── Step 3: Connectivity test (lightweight prompt) ────────────────────
    try:
        res = _chart_analysis.test_ai_connection(api_key=api_key, model=model, provider=provider)
        steps.append({
            "step": "API 연결",
            "ok": True,
            "msg": f"{provider} 응답 정상 – {res.get('latency_ms', '?')}ms",
        })
    except Exception as exc:
        steps.append({"step": "API 연결", "ok": False, "msg": str(exc)})
        return {"ok": False, "steps": steps, "provider": provider, "model": model}

    return {"ok": True, "steps": steps, "provider": provider, "model": model}


@app.post("/api/ai/chart-analysis/image")
async def ai_chart_analysis_image(
    symbol: str,
    files: list[UploadFile] = FastAPIFile(..., description="TradingView 차트 스크린샷 (PNG/JPG, 최대 6개)"),
    extra_context: str | None = None,
    _current_user=Depends(get_current_user),
):
    """TradingView 차트 스크린샷을 업로드하여 AI 종합 분석.

    - 여러 타임프레임(일봉·4H·1H 등) 이미지를 동시에 업로드 가능 (최대 6개)
    - GPT-4o Vision으로 차트를 직접 보고 분석
    - 기업 분석 / 기술적 분석 / 상승 이유 / 목표가 / 수급·손절가 포함

    사용법:
      1. TradingView 차트에서 스크린샷 (카메라 아이콘 또는 Alt+S)
      2. 여러 타임프레임 이미지를 함께 업로드
    """
    if _chart_analysis is None:
        raise HTTPException(status_code=503, detail="chart_analysis module not available")

    provider, api_key, model = _resolve_ai_provider()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="AI API key not configured. Set GEMINI_API_KEY / GROQ_API_KEY / OPENAI_API_KEY in backend/.env",
        )

    if not files:
        raise HTTPException(status_code=400, detail="최소 1개 이상의 이미지를 업로드하세요")
    if len(files) > 6:
        raise HTTPException(status_code=400, detail="이미지는 최대 6개까지 업로드 가능합니다")

    ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB per image

    image_files: list[tuple[str, bytes]] = []
    image_hashes: list[str] = []
    for upload in files:
        fname = (upload.filename or "chart.png").lower()
        ext = "." + fname.rsplit(".", 1)[-1] if "." in fname else ""
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"지원하지 않는 파일 형식: {ext}. PNG, JPG, WEBP만 가능합니다",
            )
        raw = await upload.read(MAX_IMAGE_SIZE + 1)
        if len(raw) > MAX_IMAGE_SIZE:
            raise HTTPException(status_code=413, detail=f"{upload.filename}: 파일 크기가 10MB를 초과합니다")
        image_files.append((upload.filename or "chart.png", raw))
        image_hashes.append(hashlib.sha256(raw).hexdigest()[:16])

    # For vision: Gemini uses gemini-2.5-flash, OpenAI needs gpt-4o
    if provider == "openai" and model == "gpt-4o-mini":
        vision_model = "gpt-4o"
    elif provider == "gemini":
        vision_model = model  # gemini-2.5-flash supports vision
    else:
        vision_model = model

    try:
        result = _chart_analysis.analyze_chart_images(
            symbol=symbol.strip(),
            image_files=image_files,
            api_key=api_key,
            model=vision_model,
            provider=provider,
            extra_context=extra_context,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"이미지 분석 중 오류 발생: {exc}") from exc

    # ── AI 분석 결과 캐시 저장 ──────────────────────────────────────────────
    if apollo_db is not None and models is not None:
        try:
            stock_code_clean = symbol.strip()
            sig = str(result.get("signal", "") or "").upper() if isinstance(result, dict) else ""
            conf = result.get("confidence") if isinstance(result, dict) else None
            upsid = result.get("upside_probability") if isinstance(result, dict) else None
            sname = result.get("stock_name") or result.get("company") if isinstance(result, dict) else None

            db_cache: Session = apollo_db.get_session_factory()()
            try:
                existing = db_cache.execute(
                    select(models.AiAnalysisCache).where(
                        models.AiAnalysisCache.stock_code == stock_code_clean
                    )
                ).scalar_one_or_none()
                now_utc = datetime.utcnow()
                if existing is None:
                    db_cache.add(models.AiAnalysisCache(
                        stock_code=stock_code_clean,
                        stock_name=sname,
                        analyzed_at=now_utc,
                        signal=sig or None,
                        confidence=float(conf) if conf is not None else None,
                        upside_probability=float(upsid) if upsid is not None else None,
                        result_json=result if isinstance(result, dict) else None,
                        image_hashes=image_hashes,
                    ))
                else:
                    existing.stock_name = sname or existing.stock_name
                    existing.analyzed_at = now_utc
                    existing.signal = sig or None
                    existing.confidence = float(conf) if conf is not None else None
                    existing.upside_probability = float(upsid) if upsid is not None else None
                    existing.result_json = result if isinstance(result, dict) else None
                    existing.image_hashes = image_hashes
                db_cache.commit()
            finally:
                db_cache.close()
        except Exception as _cache_err:
            # 캐시 저장 실패는 무시 (분석 결과 반환에 영향 없음)
            pass

    return result


# ─── AI 분석 캐시 API ─────────────────────────────────────────────────────────

_SIGNAL_ORDER = {"STRONG_BUY": 1, "BUY": 2, "HOLD": 3, "SELL": 4, "STRONG_SELL": 5}


@app.get("/api/ai/analysis-cache")
def get_ai_analysis_cache(_current_user=Depends(get_current_user)):
    """AI 차트 분석 캐시 전체 목록 — signal 강도 순 정렬 (STRONG_BUY 우선).

    상승 추세가 강한 종목부터 정렬됩니다.
    """
    if apollo_db is None or models is None:
        raise HTTPException(status_code=503, detail="DB module not available")

    db: Session = apollo_db.get_session_factory()()
    try:
        rows = db.execute(
            select(models.AiAnalysisCache).order_by(
                desc(models.AiAnalysisCache.analyzed_at)
            )
        ).scalars().all()

        items = []
        for r in rows:
            items.append({
                "stock_code": r.stock_code,
                "stock_name": r.stock_name,
                "analyzed_at": r.analyzed_at.isoformat() if r.analyzed_at else None,
                "signal": r.signal,
                "confidence": r.confidence,
                "upside_probability": r.upside_probability,
                "image_hashes": r.image_hashes,
                # 전체 result_json도 포함 (프론트에서 요약 표시)
                "summary": (r.result_json or {}).get("summary") if r.result_json else None,
                "target_price": (r.result_json or {}).get("target_price") if r.result_json else None,
                "stop_loss": (r.result_json or {}).get("stop_loss") if r.result_json else None,
                "entry_price": (r.result_json or {}).get("entry_price") if r.result_json else None,
            })

        # signal 강도 순 정렬 (STRONG_BUY=1 → 먼저)
        items.sort(key=lambda x: _SIGNAL_ORDER.get(x.get("signal") or "", 99))

        return {"items": items, "total": len(items)}
    finally:
        db.close()


@app.get("/api/ai/analysis-cache/{stock_code}")
def get_ai_analysis_cache_detail(
    stock_code: str,
    _current_user=Depends(get_current_user),
):
    """특정 종목의 AI 분석 캐시 상세 조회 (result_json 포함)."""
    if apollo_db is None or models is None:
        raise HTTPException(status_code=503, detail="DB module not available")

    db: Session = apollo_db.get_session_factory()()
    try:
        row = db.execute(
            select(models.AiAnalysisCache).where(
                models.AiAnalysisCache.stock_code == stock_code.strip()
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"{stock_code} 분석 캐시 없음")
        return {
            "stock_code": row.stock_code,
            "stock_name": row.stock_name,
            "analyzed_at": row.analyzed_at.isoformat() if row.analyzed_at else None,
            "signal": row.signal,
            "confidence": row.confidence,
            "upside_probability": row.upside_probability,
            "image_hashes": row.image_hashes,
            "result_json": row.result_json,
        }
    finally:
        db.close()


@app.delete("/api/ai/analysis-cache/{stock_code}")
def delete_ai_analysis_cache(
    stock_code: str,
    _current_user=Depends(require_admin),
):
    """특정 종목의 AI 분석 캐시 삭제 (admin 전용)."""
    if apollo_db is None or models is None:
        raise HTTPException(status_code=503, detail="DB module not available")

    with apollo_db.session_scope() as session:
        row = session.execute(
            select(models.AiAnalysisCache).where(
                models.AiAnalysisCache.stock_code == stock_code.strip()
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"{stock_code} 분석 캐시 없음")
        session.delete(row)

    return {"deleted": stock_code}


@app.get("/{full_path:path}")
def serve_frontend(full_path: str):
    # If frontend is not built, don't pretend it exists.
    if not DIST_DIR.exists():
        raise HTTPException(status_code=404, detail="frontend dist not found; run `npm run build` in ./frontend")

    # Never hijack API and service endpoints.
    blocked = (
        full_path == "health"
        or full_path == "openapi.json"
        or full_path.startswith("api")
        or full_path.startswith("docs")
        or full_path.startswith("redoc")
    )
    if blocked:
        raise HTTPException(status_code=404, detail="Not Found")

    dist_root = DIST_DIR.resolve()
    if full_path == "":
        candidate = dist_root / "index.html"
    else:
        candidate = (DIST_DIR / full_path).resolve()

    # Prevent path traversal.
    if dist_root not in candidate.parents and candidate != dist_root:
        raise HTTPException(status_code=404, detail="Not Found")

    if candidate.exists() and candidate.is_file():
        media_type, _ = mimetypes.guess_type(str(candidate))
        return FileResponse(candidate, media_type=media_type)

    # SPA fallback: return index.html for client-side routes.
    index = dist_root / "index.html"
    if not index.exists():
        raise HTTPException(status_code=500, detail="frontend dist is missing index.html")
    return FileResponse(index, media_type="text/html")
