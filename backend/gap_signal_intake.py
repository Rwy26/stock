"""KR 시초가 갭 신호 적재 엔진 — premarket-scanner 결과를 MOON STOCK DB로 올린다.

설계 합의(2026-06-14):
  - 소스: premarket-scanner/kr_gap_scanner.sh 가 내보내는 kr_gap_gappers_YYYY-MM-DD.json
    (네이버 모바일 API → 시초가 갭 재계산 + 종목 뉴스 촉매). 소스는 건드리지 않는다.
  - 신호 생성: 09:05 적재(ingest) + 16:10 확정 daily_prices 기준 재확인(reconcile) 둘 다.
  - 등급(tier): 갭%+거래대금+촉매유무 → A/B/C 결정론 산출.
  - 라벨: '시초가 갭 신호(스크리닝)' — 매수추천 아님.

가드레일 (협상 불가):
  1. 촉매는 LLM 요약·참고치 → catalyst_verified=False 고정 + 근거 헤드라인 병기.
  2. 적재 시점에 갭/가격을 네이버 siseJson 기준으로 재확인. 어긋나면 siseJson 우선
     (siseJson 은 daily_prices 의 원천 — fetch_daily_prices.py 와 동일 소스).
  3. 제외는 exclusion_engine 경유. 제외 적중 시 이 테이블에 저장하지 않고(완전제외)
     excluded_stocks 인덱스에만 남긴다. 과열조치·섹터ETF·주도주는 제외 금지(엔진이 보장).
"""
from __future__ import annotations

import ast
import logging
import math
from datetime import date, datetime, timedelta

import httpx
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

import exclusion_engine
import models

logger = logging.getLogger("gap_signal")

DISCLAIMER = "참고용 스크리닝 신호 · 미검증 촉매 · 매수추천 아님"
CATALYST_SOURCE = "naver_news_llm"

# ─── 등급(tier) 임계값 (사용자 확정 2026-06-14) ─────────────────────────────
#   A: 갭 ≥ 9% AND 거래대금 ≥ 500억 AND 촉매 있음
#   B: (갭 ≥ 7% OR 거래대금 ≥ 100억) AND 촉매 있음, 또는 갭 ≥ 9%
#   C: 나머지 (스캐너 통과분: 갭>5%·가격>1,000·거래대금>10억)
TIER_A_GAP = 9.0
TIER_A_VALUE = 50_000_000_000.0   # 500억원
TIER_B_GAP = 7.0
TIER_B_VALUE = 10_000_000_000.0   # 100억원


_table_ready = False


def _ensure_table() -> None:
    """kr_opening_gap_signals 테이블 보장 — 스케줄 스크립트가 백엔드와 독립 실행될 때 대비.

    (실행 중인 백엔드는 startup 의 create_all 로 이미 생성하지만, 스크립트 단독 실행 시
    필요. exclusion_engine._ensure_table 과 동일 패턴.)
    """
    global _table_ready
    if _table_ready:
        return
    import db

    models.Base.metadata.create_all(db.get_engine(), tables=[models.KrOpeningGapSignal.__table__])
    _table_ready = True


def compute_tier(gap_pct: float | None, trade_value_krw: float | None, has_catalyst: bool) -> str:
    """갭%·거래대금·촉매유무로 A/B/C 등급을 결정론적으로 산출."""
    gap = float(gap_pct or 0.0)
    val = float(trade_value_krw or 0.0)
    if gap >= TIER_A_GAP and val >= TIER_A_VALUE and has_catalyst:
        return "A"
    if ((gap >= TIER_B_GAP or val >= TIER_B_VALUE) and has_catalyst) or gap >= TIER_A_GAP:
        return "B"
    return "C"


# ─── 네이버 siseJson 정합성 재확인 (가드레일 2) ─────────────────────────────
# fetch_daily_prices.py 와 동일한 원천(네이버 siseJson)·동일한 행 검증을 사용한다.
# daily_prices 는 이 소스로 16:10 에 적재되므로, siseJson 직접 조회가 곧 daily_prices 기준이다.

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


def _valid_row(r: dict) -> bool:
    """fetch_daily_prices.valid_row 와 동일 규칙."""
    vals = (r["open"], r["high"], r["low"], r["close"])
    if any(v is None or (isinstance(v, float) and math.isnan(v)) or v <= 0 for v in vals):
        return False
    if r["volume"] is None or r["volume"] < 0:
        return False
    if r["high"] < max(r["open"], r["close"]) or r["low"] > min(r["open"], r["close"]):
        return False
    if r["volume"] == 0 and r["open"] == r["high"] == r["low"] == r["close"]:
        return False
    return True


def _fetch_naver_daily(code: str, start: date, end: date) -> list[dict] | None:
    """네이버 siseJson 원시 일봉(오름차순). 실패 시 None — 호출측에서 재확인 보류."""
    try:
        resp = httpx.get(
            "https://api.finance.naver.com/siseJson.naver",
            params={
                "symbol": code, "requestType": 1,
                "startTime": start.strftime("%Y%m%d"),
                "endTime": end.strftime("%Y%m%d"),
                "timeframe": "day",
            },
            headers=_HEADERS, timeout=15,
        )
        resp.raise_for_status()
        raw = ast.literal_eval(resp.text.strip())
    except Exception:
        return None
    rows: list[dict] = []
    for item in raw[1:]:  # [0]은 헤더
        try:
            rows.append({
                "date": datetime.strptime(str(item[0]), "%Y%m%d").date(),
                "open": int(item[1]), "high": int(item[2]),
                "low": int(item[3]), "close": int(item[4]),
                "volume": int(item[5]),
            })
        except (ValueError, IndexError, TypeError):
            continue
    rows.sort(key=lambda r: r["date"])
    return rows


def reconcile_gap(code: str, session_date: date) -> dict | None:
    """session_date 의 시초가 갭을 네이버 siseJson 으로 재확인.

    session_date 봉(시가)과 그 직전 거래일 봉(전일 종가)을 찾아
    gap = (open - prev_close)/prev_close*100 를 재계산해 반환한다.
    session_date 봉 또는 직전 거래일이 없으면 None(재확인 보류 → price_verified=False).
    """
    rows = _fetch_naver_daily(code, session_date - timedelta(days=15), session_date)
    if not rows:
        return None
    rows = [r for r in rows if _valid_row(r)]
    idx = next((i for i, r in enumerate(rows) if r["date"] == session_date), None)
    if idx is None or idx == 0:
        return None
    cur = rows[idx]
    prev_close = float(rows[idx - 1]["close"])
    if prev_close <= 0:
        return None
    open_price = float(cur["open"])
    return {
        "open_price": open_price,
        "prev_close": prev_close,
        "price": float(cur["close"]),
        "volume": int(cur["volume"]),
        "gap_pct": round((open_price - prev_close) / prev_close * 100.0, 2),
    }


# ─── 적재 (09:05) ────────────────────────────────────────────────────────────

def ingest_gappers(db: Session, gappers: list[dict], session_date: date) -> dict:
    """스캐너 gappers 를 검증·정합성 재확인 후 kr_opening_gap_signals 에 UPSERT.

    제외 종목(거래정지/정리매매/관리종목/스팩/우선주/리츠 등)은 저장하지 않고
    excluded_stocks 인덱스에만 남긴다(exclusion_engine.gate). 보호 종목은 통과.
    """
    _ensure_table()
    ingested = 0
    excluded = 0
    verified = 0
    skipped: list[str] = []
    excluded_codes: list[str] = []

    for g in gappers:
        code = str(g.get("code") or "").strip()
        if not code:
            continue
        name = str(g.get("name") or "").strip()

        # 가드레일 3: 제외 게이트. 제외 적중 시 저장 스킵(완전제외) — 인덱스는 gate 가 유지.
        # (섹터ETF·주도주·ETF/ETN 은 gate 가 통과시킴 = 제외 금지)
        try:
            exclusion_engine.gate(db, code, name)
        except exclusion_engine.ExcludedStockError:
            excluded += 1
            excluded_codes.append(code)
            continue

        # 가드레일 2: 네이버 siseJson 으로 갭/가격 재확인 (어긋나면 siseJson 우선)
        rec = reconcile_gap(code, session_date)
        if rec is not None:
            gap_pct = rec["gap_pct"]
            open_price = rec["open_price"]
            prev_close = rec["prev_close"]
            price = rec["price"]
            volume = rec["volume"]
            price_verified = True
            verified += 1
        else:
            # 재확인 보류 — 스캐너 값 유지하되 price_verified=False 로 명시
            gap_pct = float(g.get("gap_pct") or 0.0)
            open_price = _as_float(g.get("open_price"))
            prev_close = _as_float(g.get("prev_close"))
            price = _as_float(g.get("price"))
            volume = _as_int(g.get("volume"))
            price_verified = False
            skipped.append(code)

        trade_value = _as_float(g.get("trade_value_krw"))
        catalyst = (str(g.get("catalyst")).strip() or None) if g.get("catalyst") else None
        has_catalyst = bool(catalyst)
        # catalyst_type 은 스캐너가 제공할 때만 채운다 — 없으면 null(분류를 날조하지 않음).
        catalyst_type = g.get("catalyst_type") or None
        headlines = g.get("headlines") if isinstance(g.get("headlines"), list) else None
        tier = compute_tier(gap_pct, trade_value, has_catalyst)

        row = db.execute(
            select(models.KrOpeningGapSignal).where(
                models.KrOpeningGapSignal.session_date == session_date,
                models.KrOpeningGapSignal.stock_code == code,
            ).limit(1)
        ).scalar_one_or_none()
        if row is None:
            row = models.KrOpeningGapSignal(session_date=session_date, stock_code=code)
            db.add(row)
        row.name = name or row.name
        row.signal_type = "opening_gap"
        row.rank = _as_int(g.get("rank"))
        row.tier = tier
        row.gap_pct = float(gap_pct)
        row.price = price
        row.open_price = open_price
        row.prev_close = prev_close
        row.volume = volume
        row.trade_value_krw = trade_value
        row.catalyst = catalyst
        row.catalyst_type = catalyst_type
        row.catalyst_verified = False           # 가드레일 1: 항상 False
        row.catalyst_source = CATALYST_SOURCE
        row.headlines = headlines
        row.price_verified = price_verified
        row.disclaimer = DISCLAIMER
        ingested += 1

    db.commit()
    if excluded:
        exclusion_engine.get_exclusions(db, force=True)
    logger.info(
        "갭 신호 적재 %s: ingested=%d verified=%d excluded=%d unverified=%d",
        session_date, ingested, verified, excluded, len(skipped),
    )
    return {
        "session_date": session_date.isoformat(),
        "ingested": ingested,
        "price_verified": verified,
        "excluded": excluded,
        "excluded_codes": excluded_codes,
        "unverified": skipped,
    }


# ─── 재확인 (16:10) ───────────────────────────────────────────────────────────

def reconcile_signals(db: Session, session_date: date) -> dict:
    """저장된 session_date 신호의 갭/가격을 확정 siseJson 기준으로 재확인·갱신."""
    _ensure_table()
    rows = db.execute(
        select(models.KrOpeningGapSignal).where(
            models.KrOpeningGapSignal.session_date == session_date
        )
    ).scalars().all()
    updated = 0
    verified = 0
    for row in rows:
        rec = reconcile_gap(row.stock_code, session_date)
        if rec is None:
            continue
        row.gap_pct = float(rec["gap_pct"])
        row.open_price = rec["open_price"]
        row.prev_close = rec["prev_close"]
        row.price = rec["price"]
        row.volume = rec["volume"]
        row.price_verified = True
        has_catalyst = bool(row.catalyst)
        row.tier = compute_tier(row.gap_pct, row.trade_value_krw, has_catalyst)
        updated += 1
        verified += 1
    db.commit()
    logger.info("갭 신호 재확인 %s: rows=%d updated=%d", session_date, len(rows), updated)
    return {
        "session_date": session_date.isoformat(),
        "rows": len(rows),
        "updated": updated,
        "price_verified": verified,
    }


# ─── 조회 (사용자 갭 신호 탭) ─────────────────────────────────────────────────

def list_signals(db: Session, session_date: date | None = None) -> dict:
    """session_date(없으면 최신 일자)의 갭 신호를 갭% 내림차순으로 반환."""
    _ensure_table()
    if session_date is None:
        session_date = db.execute(
            select(models.KrOpeningGapSignal.session_date)
            .order_by(desc(models.KrOpeningGapSignal.session_date))
            .limit(1)
        ).scalar_one_or_none()
    if session_date is None:
        return {"date": None, "items": [], "note": "갭 신호 데이터 없음"}

    rows = db.execute(
        select(models.KrOpeningGapSignal, models.Stock.name)
        .outerjoin(models.Stock, models.Stock.code == models.KrOpeningGapSignal.stock_code)
        .where(models.KrOpeningGapSignal.session_date == session_date)
        .order_by(desc(models.KrOpeningGapSignal.gap_pct))
    ).all()

    items = [{
        "code": r.stock_code,
        "name": stock_name or r.name or r.stock_code,
        "tier": r.tier,
        "gapPct": float(r.gap_pct or 0.0),
        "price": float(r.price) if r.price is not None else None,
        "open": float(r.open_price) if r.open_price is not None else None,
        "prevClose": float(r.prev_close) if r.prev_close is not None else None,
        "volume": int(r.volume) if r.volume is not None else None,
        "tradeValueKrw": float(r.trade_value_krw) if r.trade_value_krw is not None else None,
        "catalyst": r.catalyst,
        "catalystType": r.catalyst_type,
        "catalystVerified": bool(r.catalyst_verified),
        "catalystSource": r.catalyst_source,
        "headlines": r.headlines or [],
        "priceVerified": bool(r.price_verified),
        "disclaimer": r.disclaimer or DISCLAIMER,
    } for r, stock_name in rows]

    return {
        "date": session_date.isoformat(),
        "items": items,
        "note": "시초가 갭 신호(스크리닝) — 매수추천 아님 · 촉매는 LLM 요약(미검증)",
    }


# ─── 내부 헬퍼 ────────────────────────────────────────────────────────────────

def _as_float(v) -> float | None:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _as_int(v) -> int | None:
    try:
        if v is None:
            return None
        return int(v)
    except (TypeError, ValueError):
        return None
