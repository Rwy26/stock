from __future__ import annotations

import json
import mimetypes
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

import auth
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

app = FastAPI(title="Apollo Stock Trading System")


_kis_refresh_stop = threading.Event()
_autotrade_stop = threading.Event()


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


def _kis_account_product_code_from_prefix(prefix: str | None) -> str | None:
    # 요구사항상 계좌 앞 8자리만 저장하므로 상품코드는 01로 가정
    if not prefix:
        return None
    p = str(prefix).strip()
    if len(p) < 8:
        return None
    return "01"


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
    account_prefix = (str(getattr(profile, "account_prefix", "") or "").strip())
    prdt_cd = _kis_account_product_code_from_prefix(account_prefix)

    if not app_key or not app_secret or not account_prefix or not prdt_cd:
        return False, "KIS 프로필(appKey/appSecret/accountPrefix) 설정 필요"

    if (not is_paper) and (not settings.autotrading_live_orders):
        return False, "실계좌 주문은 AUTOTRADING_LIVE_ORDERS=1 설정이 필요합니다."

    try:
        resp = kis_client.place_cash_order(
            app_key=app_key,
            app_secret=app_secret,
            is_paper=is_paper,
            account_prefix=account_prefix,
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


def _run_sa_engine_tick(db: Session, *, user_id: int, profile, now: datetime) -> None:
    assert models is not None

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

    # buy minimal: if holdings < 5, buy 1 share of top recommendation not held
    open_pos = db.execute(
        select(models.SaAutoTradingPosition)
        .where(models.SaAutoTradingPosition.user_id == user_id, models.SaAutoTradingPosition.closed_at.is_(None))
    ).scalars().all()
    if len(open_pos) >= 5:
        return

    held = {str(p.stock_code) for p in open_pos}
    code = _pick_top_recommendation_code(db, exclude_codes=held)
    if not code:
        return

    ok, msg = _place_market_order_and_log(
        db=db,
        user_id=user_id,
        engine="sa",
        side="buy",
        stock_code=code,
        qty=1,
        profile=profile,
    )
    db.add(models.AutomationEngineLog(user_id=user_id, engine="sa", event=("buy" if ok else "error"), message=msg))
    if ok:
        # create a new position; avg_buy will be unknown until fill (set 0 for now)
        db.add(models.SaAutoTradingPosition(user_id=user_id, stock_code=code, qty=1, avg_buy=0.0))


def _run_plus_engine_tick(db: Session, *, user_id: int, profile, now: datetime) -> None:
    assert models is not None

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
    if len(open_pos) >= 5:
        return

    held = {str(p.stock_code) for p in open_pos}
    code = _pick_top_recommendation_code(db, exclude_codes=held)
    if not code:
        return

    ok, msg = _place_market_order_and_log(
        db=db,
        user_id=user_id,
        engine="plus",
        side="buy",
        stock_code=code,
        qty=1,
        profile=profile,
    )
    db.add(models.AutomationEngineLog(user_id=user_id, engine="plus", event=("buy" if ok else "error"), message=msg))
    if ok:
        db.add(models.PlusAutoTradingPosition(user_id=user_id, stock_code=code, qty=1, avg_buy=0.0))


def _autotrade_tick_loop() -> None:
    """Dry-run engine scheduler.

    - Runs every minute during market hours.
    - Reads per-user enabled flags.
    - Writes a simple tick log (no orders are placed).
    """

    time.sleep(2.0)

    while not _autotrade_stop.is_set():
        try:
            if settings.autotrading_kill_switch:
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


@app.on_event("shutdown")
def _shutdown_kis_refresh() -> None:
    _kis_refresh_stop.set()
    _autotrade_stop.set()

REPO_ROOT = Path(__file__).resolve().parents[1]
MOCK_DIR = REPO_ROOT / "frontend-prototype" / "mock"

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


def _read_mock_json(filename: str) -> dict:
    path = MOCK_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=500, detail=f"Mock file missing: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"Invalid JSON in mock file: {filename}") from exc


@app.get("/api/portfolio")
def get_portfolio(current_user=Depends(get_current_user)):
    if apollo_db is None or models is None:
        return _read_mock_json("portfolio.sample.json")

    user_id = int(current_user.id)
    db: Session = apollo_db.get_session_factory()()
    try:
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

        profile = db.execute(select(models.KisProfile).where(models.KisProfile.user_id == user_id)).scalar_one_or_none()

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

        return {"asOf": datetime.now().isoformat(), "positions": payload_positions}
    finally:
        db.close()


@app.get("/api/recommendations")
def get_recommendations(_current_user=Depends(get_current_user)):
    if apollo_db is None or models is None:
        return _read_mock_json("recommendations.sample.json")

    today = date.today()
    db: Session = apollo_db.get_session_factory()()
    try:
        # Realtime prices are per-user (KIS credentials).
        # We don't require them for recommendations list, but if the user is logged in
        # and has profile set (required by UX), we prefer KIS.
        # For safety, failures fall back to DB unless KIS_STRICT_PRICE=1.
        user_profile = None
        try:
            # _current_user is required by auth; keep mypy happy.
            user_id = int(getattr(_current_user, "id"))
            user_profile = db.execute(select(models.KisProfile).where(models.KisProfile.user_id == user_id)).scalar_one_or_none()
        except Exception:
            user_profile = None

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

        items: list[dict] = []
        for rank, score_total, stock_code, name in rows:
            price, change_rate = _get_realtime_price_and_change(db, user_profile, stock_code)
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

        # Keep the API stable even when DB is empty.
        if not items:
            return _read_mock_json("recommendations.sample.json")

        return {"date": today.isoformat(), "items": items}
    finally:
        db.close()


@app.get("/api/watchlist")
def get_watchlist(current_user=Depends(get_current_user)):
    if apollo_db is None or models is None:
        return _read_mock_json("watchlist.sample.json")

    user_id = int(current_user.id)
    db: Session = apollo_db.get_session_factory()()
    try:
        profile = db.execute(select(models.KisProfile).where(models.KisProfile.user_id == user_id)).scalar_one_or_none()

        rows = db.execute(
            select(models.Watchlist.stock_code, models.Stock.name)
            .join(models.Stock, models.Stock.code == models.Watchlist.stock_code)
            .where(models.Watchlist.user_id == user_id)
            .order_by(desc(models.Watchlist.created_at))
        ).all()

        items: list[dict] = []
        for stock_code, name in rows:
            price, change_rate = _get_realtime_price_and_change(db, profile, stock_code)
            score = _get_latest_score_total(db, stock_code)
            items.append(
                {
                    "name": name,
                    "code": stock_code,
                    "price": float(price),
                    "changeRate": float(change_rate),
                    "score": int(score),
                }
            )

        # Keep stable behavior for empty DB.
        if not items:
            return _read_mock_json("watchlist.sample.json")

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
        stock = session.execute(select(models.Stock).where(models.Stock.code == code)).scalar_one_or_none()
        if stock is None:
            raise HTTPException(status_code=404, detail="Stock not found")

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
                # Don't expose token, just validate we can obtain one quickly.
                try:
                    kis_client.get_access_token(
                        app_key=str(profile.app_key),
                        app_secret=str(profile.app_secret),
                        is_paper=bool(profile.is_paper),
                        live_base_url=settings.kis_live_base_url,
                        paper_base_url=settings.kis_paper_base_url,
                        timeout_seconds=3.0,
                    )
                    kis_connected = True
                except Exception:
                    kis_connected = False
        finally:
            db.close()

    return {
        "asOf": datetime.now().isoformat(),
        "kpis": {
            "totalValue": {"amount": 184_380_000, "deltaPct": 2.41},
            "totalInvested": {"amount": 161_000_000, "deltaPct": 1.04},
            "pnl": {"amount": 23_380_000, "deltaPct": 14.52},
            "cash": {"amount": 39_640_000, "label": "가용 가능"},
        },
        "topRecommendations": [
            {"name": "삼성전자", "code": "005930", "score": 91},
            {"name": "SK하이닉스", "code": "000660", "score": 88},
            {"name": "현대차", "code": "005380", "score": 85},
            {"name": "KB금융", "code": "105560", "score": 84},
            {"name": "POSCO홀딩스", "code": "005490", "score": 83},
        ],
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
def search_stocks(q: str | None = None, market: str | None = None, sort: str | None = None):
    # Minimal mock for wiring the Stock Search screen.
    universe = [
        {"name": "삼성전자", "code": "005930", "price": 72100, "changeRate": 1.02, "score": 91},
        {"name": "SK하이닉스", "code": "000660", "price": 210500, "changeRate": 2.12, "score": 88},
        {"name": "현대차", "code": "005380", "price": 221500, "changeRate": -0.35, "score": 85},
        {"name": "팬오션", "code": "028670", "price": 6180, "changeRate": -0.64, "score": 62},
    ]

    filtered = universe
    if q:
        q_norm = q.strip().lower()
        if q_norm:
            filtered = [
                item
                for item in filtered
                if q_norm in item["name"].lower() or q_norm in item["code"].lower()
            ]

    # market/sort are accepted to match UI controls; not applied in mock.
    return {"items": filtered, "q": q or "", "market": market or "", "sort": sort or ""}


@app.get("/api/stocks/{code}")
def stock_detail(code: str):
    items = search_stocks(q=code)["items"]
    if not items:
        raise HTTPException(status_code=404, detail="Stock not found")
    item = items[0]
    return {
        **item,
        "indicators": {
            "value": 24,
            "flow": 22,
            "profit": 19,
            "growth": 5,
            "tech": 17,
        },
    }


@app.get("/api/version")
def get_version():
    return {"service": "apollo-backend", "mock": True}


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
        return {
            "userId": int(user_id),
            "appKey": (profile.app_key if profile else None),
            "accountPrefix": (profile.account_prefix if profile else None),
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

        if account_prefix_raw is not None:
            profile.account_prefix = (str(account_prefix_raw).strip() or None)

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
        return {
            "nickname": (user.nickname if user else None),
            "kis": {
                "appKey": (profile.app_key if profile else None),
                "hasAppSecret": has_app_secret,
                "accountPrefix": (profile.account_prefix if profile else None),
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
    account_prefix = (payload.get("accountPrefix") or payload.get("accountNo") or "").strip() or None
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
        profile.account_prefix = account_prefix
        profile.is_paper = is_paper

    return {"ok": True}


DIST_DIR = REPO_ROOT / "frontend" / "dist"


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
