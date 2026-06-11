"""short_selling.py

종목별 일별 공매도 데이터 수집 + 급증 판정 모듈.

데이터 소스 (둘 다 거래소 원천 데이터):
  1. KIS OpenAPI 공매도 일별추이 (TR FHPST04830000) — 공매도 체결수량/비중, T+1 공표.
     읽기 전용 시세 조회만 사용 (주문 없음, 킬스위치 무관).
  2. KRX 정보데이터시스템 — 공매도 잔고수량/잔고비중, T+2 공표.
     data.krx.co.kr 로그인 필수 → KRX_ID/KRX_PW 환경변수 필요 (set-krx-env.ps1).
     미설정 시 잔고는 수집하지 않고 NULL 유지 (거래량만으로 급증 판정).

교차검증: KRX 자격증명이 있으면 KIS 공매도 수량 ↔ KRX 공매도 거래량을
겹치는 날짜로 대조하고 1% 초과 차이를 호출자에 반환한다 (잘못된 데이터로
매매 판단을 하지 않기 위한 원칙 — 불일치는 자동 수정하지 않고 알림만).

저장: models.ShortSellingDaily (stock_code + trade_date 유니크)
소비: supply_demand.fetch_supply_demand_batch → scoring_engine 위험2 (short_sell_surge_3d)
"""

from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime
from typing import Any

logger = logging.getLogger(__name__)

# ─── 급증 판정 기준 (결정론 — 임의 해석 없이 아래 수치로만 판정) ──────────────
SURGE_RATIO_MULT = 1.5    # 최근 3일 공매도 비중이 기준선(직전 20일 평균)의 1.5배 이상
SURGE_RATIO_FLOOR = 3.0   # 공매도 비중 절대 하한 (%) — 미미한 비중의 배수 급증 오탐 방지
SURGE_BALANCE_MULT = 1.1  # 잔고 최종일이 기준선 평균의 1.1배 이상
MIN_ROWS_FOR_JUDGE = 8    # 판정 최소 데이터 일수 (기준선 5일 + 최근 3일) — 미만이면 미판정(N/A)


def _parse_yyyymmdd(s: str) -> date | None:
    try:
        return datetime.strptime(s.strip(), "%Y%m%d").date()
    except Exception:
        return None


# ─── KIS 공매도 거래량 수집 ───────────────────────────────────────────────────

def sync_kis_short_sale(
    db,
    stock_codes: list[str],
    *,
    app_key: str,
    app_secret: str,
    is_paper: bool = False,
    live_base_url: str = "",
    paper_base_url: str = "",
    days: int = 30,
    sleep_s: float = 0.12,
) -> tuple[int, int, list[str]]:
    """KIS 공매도 일별추이를 short_selling_daily에 upsert.

    잔고 컬럼(balance_*)은 건드리지 않는다 (KRX 수집이 별도 관리).
    Returns: (성공 종목 수, upsert 행 수, 실패 종목 리스트)
    실패 목록 표기: 조회 오류는 코드 그대로, 정상 응답이지만 공매도 데이터가
    없는 종목(공매도 비대상/체결 없음)은 "코드(EMPTY)" — 오류와 구분.
    """
    import kis_client
    import models
    from sqlalchemy.dialects.mysql import insert as mysql_insert

    kw: dict[str, Any] = {
        "app_key": app_key,
        "app_secret": app_secret,
        "is_paper": is_paper,
    }
    if live_base_url:
        kw["live_base_url"] = live_base_url
    if paper_base_url:
        kw["paper_base_url"] = paper_base_url

    ok_codes = 0
    upserted = 0
    failed: list[str] = []

    for code in stock_codes:
        try:
            rows = kis_client.inquire_short_sale(code=code, days=days, **kw)
        except Exception as exc:
            logger.warning("KIS 공매도 조회 실패 %s: %s", code, exc)
            failed.append(code)
            time.sleep(sleep_s)
            continue

        batch = []
        for r in rows:
            d = _parse_yyyymmdd(str(r.get("date") or ""))
            if d is None:
                continue
            batch.append({
                "stock_code": code,
                "trade_date": d,
                "short_qty": int(r.get("shortQty") or 0),
                "short_ratio": float(r.get("shortRatio") or 0.0),
                "close_price": float(r.get("close") or 0.0) or None,
            })

        if batch:
            stmt = mysql_insert(models.ShortSellingDaily.__table__).values(batch)
            stmt = stmt.on_duplicate_key_update(
                short_qty=stmt.inserted.short_qty,
                short_ratio=stmt.inserted.short_ratio,
                close_price=stmt.inserted.close_price,
            )
            db.execute(stmt)
            upserted += len(batch)
            ok_codes += 1
        else:
            failed.append(f"{code}(EMPTY)")

        time.sleep(sleep_s)  # KIS rate limit 보호

    db.commit()
    return ok_codes, upserted, failed


# ─── KRX 공매도 잔고 수집 (KRX_ID/KRX_PW 필요) ───────────────────────────────

def krx_credentials_available() -> bool:
    return bool(os.getenv("KRX_ID") and os.getenv("KRX_PW"))


def sync_krx_balance(
    db,
    stock_codes: list[str],
    *,
    start: date,
    end: date,
    sleep_s: float = 0.3,
) -> tuple[int, int, list[str], list[str]]:
    """KRX 공매도 잔고를 short_selling_daily에 upsert (잔고 컬럼만 갱신).

    교차검증: 같은 구간의 KRX 공매도 거래량을 KIS 수집값(short_qty)과 대조,
    1% 초과 차이 발견 시 mismatches 리스트로 반환 (자동 수정하지 않음).

    Returns: (성공 종목 수, upsert 행 수, 실패 종목, 교차검증 불일치 메시지)
    """
    import models
    from sqlalchemy import select
    from sqlalchemy.dialects.mysql import insert as mysql_insert

    if not krx_credentials_available():
        logger.info("KRX_ID/KRX_PW 미설정 — 공매도 잔고 수집 건너뜀 (거래량만 사용)")
        return 0, 0, list(stock_codes), []

    from pykrx import stock as krx_stock

    s_str = start.strftime("%Y%m%d")
    e_str = end.strftime("%Y%m%d")

    ok_codes = 0
    upserted = 0
    failed: list[str] = []
    mismatches: list[str] = []

    for code in stock_codes:
        # ── 잔고 ──────────────────────────────────────────────────────────
        try:
            bal = krx_stock.get_shorting_balance_by_date(s_str, e_str, code)
        except Exception as exc:
            logger.warning("KRX 잔고 조회 실패 %s: %s", code, exc)
            failed.append(code)
            time.sleep(sleep_s)
            continue

        if bal is None or bal.empty:
            failed.append(code)
            time.sleep(sleep_s)
            continue

        batch = []
        for idx, row in bal.iterrows():
            d = idx.date() if hasattr(idx, "date") else idx
            try:
                qty = int(row.get("공매도잔고", 0) or 0)
                ratio = float(row.get("비중", 0.0) or 0.0)
            except Exception:
                continue
            batch.append({
                "stock_code": code,
                "trade_date": d,
                "short_qty": 0,        # insert 시 기본값 — 중복이면 갱신하지 않음
                "short_ratio": 0.0,
                "balance_qty": qty,
                "balance_ratio": ratio,
            })

        if batch:
            stmt = mysql_insert(models.ShortSellingDaily.__table__).values(batch)
            stmt = stmt.on_duplicate_key_update(
                balance_qty=stmt.inserted.balance_qty,
                balance_ratio=stmt.inserted.balance_ratio,
            )
            db.execute(stmt)
            upserted += len(batch)
            ok_codes += 1

        # ── 교차검증: KRX 거래량 ↔ KIS short_qty ──────────────────────────
        try:
            vol = krx_stock.get_shorting_volume_by_date(s_str, e_str, code)
            if vol is not None and not vol.empty:
                kis_rows = db.execute(
                    select(models.ShortSellingDaily.trade_date, models.ShortSellingDaily.short_qty)
                    .where(
                        models.ShortSellingDaily.stock_code == code,
                        models.ShortSellingDaily.trade_date >= start,
                        models.ShortSellingDaily.trade_date <= end,
                        models.ShortSellingDaily.short_qty > 0,
                    )
                ).all()
                kis_map = {d: int(q) for d, q in kis_rows}
                for idx, row in vol.iterrows():
                    d = idx.date() if hasattr(idx, "date") else idx
                    krx_qty = int(row.get("공매도", row.get("거래량", 0)) or 0)
                    kis_qty = kis_map.get(d)
                    if kis_qty and krx_qty and abs(krx_qty - kis_qty) / krx_qty * 100 > 1.0:
                        mismatches.append(
                            f"VOLUME-MISMATCH {code} {d} KIS={kis_qty} KRX={krx_qty}"
                        )
        except Exception as exc:
            logger.debug("KRX 거래량 교차검증 실패 %s: %s", code, exc)

        time.sleep(sleep_s)  # KRX 차단 방지

    db.commit()
    return ok_codes, upserted, failed, mismatches


# ─── 급증 판정 ────────────────────────────────────────────────────────────────

def compute_short_surge_flags(
    db,
    stock_codes: list[str],
    *,
    lookback_days: int = 45,
) -> dict[str, dict[str, Any]]:
    """short_selling_daily 기반 종목별 공매도 급증 플래그 계산.

    판정 규칙 (결정론):
      - 데이터 MIN_ROWS_FOR_JUDGE(8) 거래일 미만 → 해당 종목 키 자체를 생략
        (스코어링에서 N/A 유지 — 모르는 것은 안전으로 간주하지 않음)
      - 거래량 급증: 최근 3거래일 모두
          short_ratio >= max(기준선 평균 × SURGE_RATIO_MULT, SURGE_RATIO_FLOOR)
        (기준선 = 최근 3일을 제외한 직전 최대 20거래일의 short_ratio 평균)
      - 잔고 급증: balance_qty가 3일 연속 증가 AND
          최종일 balance_qty >= 기준선 평균 × SURGE_BALANCE_MULT
        (잔고 데이터가 기준선 3일 + 최근 3일 미만이면 잔고 판정 생략)
      - short_sell_surge_3d = 거래량 급증 OR 잔고 급증

    Returns: {stock_code: {"short_sell_surge_3d": bool, "short_surge_note": str}}
    """
    import models
    from sqlalchemy import select

    if not stock_codes:
        return {}

    rows = db.execute(
        select(
            models.ShortSellingDaily.stock_code,
            models.ShortSellingDaily.trade_date,
            models.ShortSellingDaily.short_ratio,
            models.ShortSellingDaily.balance_qty,
        )
        .where(models.ShortSellingDaily.stock_code.in_(stock_codes))
        .order_by(models.ShortSellingDaily.stock_code, models.ShortSellingDaily.trade_date)
    ).all()

    by_code: dict[str, list] = {}
    for code, d, ratio, bal in rows:
        by_code.setdefault(str(code), []).append((d, float(ratio or 0.0), bal))

    out: dict[str, dict[str, Any]] = {}
    for code, series in by_code.items():
        series = series[-lookback_days:]
        if len(series) < MIN_ROWS_FOR_JUDGE:
            continue  # 미판정 → 스코어링 N/A

        ratios = [r for _, r, _ in series]
        recent3 = ratios[-3:]
        baseline = ratios[:-3][-20:]
        base_avg = sum(baseline) / len(baseline) if baseline else 0.0
        threshold = max(base_avg * SURGE_RATIO_MULT, SURGE_RATIO_FLOOR)
        vol_surge = base_avg > 0 and all(r >= threshold for r in recent3)

        bal_series = [int(b) for _, _, b in series if b is not None]
        bal_surge = False
        if len(bal_series) >= 6:
            b3 = bal_series[-3:]
            bal_base = bal_series[:-3][-20:]
            bal_base_avg = sum(bal_base) / len(bal_base) if bal_base else 0.0
            bal_surge = (
                b3[0] < b3[1] < b3[2]
                and bal_base_avg > 0
                and b3[2] >= bal_base_avg * SURGE_BALANCE_MULT
            )

        surge = vol_surge or bal_surge
        note = (
            f"비중 최근3일={[round(r, 2) for r in recent3]}% "
            f"기준선평균={base_avg:.2f}% 임계={threshold:.2f}% → 거래량급증={vol_surge}"
        )
        if bal_series:
            note += f", 잔고급증={bal_surge}"
        else:
            note += ", 잔고데이터없음(KRX 미수집)"

        out[code] = {
            "short_sell_surge_3d": bool(surge),
            "short_surge_note": note,
        }

    return out
