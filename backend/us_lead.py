"""us_lead.py — 미국 선행종목 → KR 섹터 'US 선행 점수' 협업 허브 (us-leaders-lead-lag).

한국 반도체/AI 섹터에 선행하는 미국 종목(NVDA·MU·GOOGL 등)의 밤사이 수익률
(us_daily_prices.overnight_return_pct)을 가중평균해 KR 섹터별 lead score(0~100, 50=중립)를
**결정론적으로** 산출한다. global_macro 와 동일한 캐시·evidence 규약을 따른다(LLM 미호출).

이 모듈은 **공통 인터페이스만 노출**한다 — 다른 엔진(sector_rotation·market_compass·
kr_opening_gap·regime_analogs)이 import 해서 쓸 수 있게 하되, 실제 배선은 'AI 예측 엔진'
전담 세션의 후속 작업이다(파일 하단 TODO). 유니버스(US_UNIVERSE)·선행 링크(LEAD_LINKS)는
이 파일이 단일 소스이며, scripts/us_leaders_sync.py 가 이를 us_stocks/us_kr_lead_link 로 시드한다.

원칙(data-accuracy): 무데이터 섹터는 중립(50) + evidence 'N/A', 모든 점수에 원천값 동반.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Optional

# ---------------------------------------------------------------------------
# 유니버스 (단일 소스 — 확장은 여기에 한 줄 추가). kr_sector_lead = 1차 선행 KR 섹터.
#   weight = 섹터 lead score 가중(주도력·시총·KR 상관 직관 반영). 지수(SOXX/SMH/^IXIC)는
#   섹터 방향성 확인용으로 포함하되 단일종목보다 낮은 가중.
# ---------------------------------------------------------------------------
US_UNIVERSE: list[dict] = [
    # 반도체 메모리 (→ 삼성전자·SK하이닉스)
    {"ticker": "MU",    "name": "Micron Technology",       "kr_sector_lead": "반도체", "weight": 1.3},
    {"ticker": "WDC",   "name": "Western Digital",         "kr_sector_lead": "반도체", "weight": 0.8},
    {"ticker": "STX",   "name": "Seagate Technology",      "kr_sector_lead": "반도체", "weight": 0.6},
    # 반도체 로직/팹리스
    {"ticker": "NVDA",  "name": "NVIDIA",                  "kr_sector_lead": "반도체", "weight": 1.5},
    {"ticker": "AMD",   "name": "Advanced Micro Devices",  "kr_sector_lead": "반도체", "weight": 1.0},
    {"ticker": "AVGO",  "name": "Broadcom",                "kr_sector_lead": "반도체", "weight": 1.0},
    {"ticker": "QCOM",  "name": "Qualcomm",                "kr_sector_lead": "반도체", "weight": 0.8},
    {"ticker": "ARM",   "name": "Arm Holdings",            "kr_sector_lead": "반도체", "weight": 0.7},
    {"ticker": "INTC",  "name": "Intel",                   "kr_sector_lead": "반도체", "weight": 0.7},
    {"ticker": "TSM",   "name": "TSMC (ADR)",              "kr_sector_lead": "반도체", "weight": 1.2},
    # 반도체 장비 (→ 한미반도체 등)
    {"ticker": "AMAT",  "name": "Applied Materials",       "kr_sector_lead": "반도체", "weight": 0.9},
    {"ticker": "LRCX",  "name": "Lam Research",            "kr_sector_lead": "반도체", "weight": 0.9},
    {"ticker": "KLAC",  "name": "KLA Corporation",         "kr_sector_lead": "반도체", "weight": 0.8},
    {"ticker": "ASML",  "name": "ASML Holding (ADR)",      "kr_sector_lead": "반도체", "weight": 1.0},
    # AI 하이퍼스케일러 (수요 — AI capex)
    {"ticker": "GOOGL", "name": "Alphabet",                "kr_sector_lead": "AI",    "weight": 1.2},
    {"ticker": "MSFT",  "name": "Microsoft",               "kr_sector_lead": "AI",    "weight": 1.2},
    {"ticker": "AMZN",  "name": "Amazon",                  "kr_sector_lead": "AI",    "weight": 1.0},
    {"ticker": "META",  "name": "Meta Platforms",          "kr_sector_lead": "AI",    "weight": 1.0},
    # 지수 (방향성 확인용)
    {"ticker": "SOXX",  "name": "iShares Semiconductor ETF", "kr_sector_lead": "반도체", "weight": 1.0},
    {"ticker": "SMH",   "name": "VanEck Semiconductor ETF",  "kr_sector_lead": "반도체", "weight": 1.0},
    {"ticker": "^IXIC", "name": "NASDAQ Composite",          "kr_sector_lead": "AI",    "weight": 0.8},
]

# 1차 선행 외 추가 선행 섹터(교차 링크). AI 가속기 공급사·HBM 메모리는 KR AI 섹터도 선행한다.
#   (us_ticker, kr_sector, lead_lag_days). 1차 링크는 US_UNIVERSE.kr_sector_lead 에서 자동 파생.
CROSS_LEAD_LINKS: list[tuple[str, str, int]] = [
    ("NVDA", "AI", 1),
    ("AVGO", "AI", 1),
    ("AMD",  "AI", 1),
    ("ARM",  "AI", 1),
    ("TSM",  "AI", 1),
    ("MU",   "AI", 1),   # HBM 메모리 → AI 수요 동조
    ("SMH",  "AI", 1),
]

DEFAULT_LEAD_LAG_DAYS = 1   # US 종가 → KR 익일 개장

# 점수 스케일: lead_score = clamp(50 + 가중평균 overnight% × GAIN). +2% 평균 → ~+8pt.
LEAD_SCORE_GAIN = 4.0
TOP_MOVERS_N = 3


def iter_universe() -> list[dict]:
    """US 유니버스(시드용). us_leaders_sync 가 us_stocks UPSERT 에 사용."""
    return list(US_UNIVERSE)


def iter_lead_links() -> list[tuple[str, str, int]]:
    """(us_ticker, kr_sector, lead_lag_days) 시드 목록 — 1차(파생) + 교차 링크, 중복 제거."""
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str, int]] = []
    for s in US_UNIVERSE:
        sec = s.get("kr_sector_lead")
        if not sec:
            continue
        key = (s["ticker"], sec)
        if key not in seen:
            seen.add(key)
            out.append((s["ticker"], sec, DEFAULT_LEAD_LAG_DAYS))
    for t, sec, lag in CROSS_LEAD_LINKS:
        key = (t, sec)
        if key not in seen:
            seen.add(key)
            out.append((t, sec, lag))
    return out


# ---------------------------------------------------------------------------
# 캐시 (global_macro 규칙과 동일: 장중 30분 / 장외 8시간)
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_cache: Optional[dict] = None
_cache_ts: float = 0.0


def _ttl() -> int:
    now = datetime.now()
    if now.weekday() < 5 and (9 * 60 <= now.hour * 60 + now.minute <= 15 * 60 + 30):
        return 1800
    return 28800


def _clamp_score(raw: float) -> int:
    return int(max(0, min(100, round(raw))))


# ---------------------------------------------------------------------------
# 데이터 로드 — 각 active 종목의 최신 overnight_return_pct + 메타. 실패 시 빈 dict.
# ---------------------------------------------------------------------------
def _load_latest() -> tuple[dict, Optional[str]]:
    """반환: ({ticker: {name, weight, kr_sector_lead, ret, date}}, asof_iso|None).

    각 종목의 가장 최근 거래일(us_daily_prices) 행을 쓴다. DB 미가용/무데이터면 ({}, None).
    """
    try:
        import db
        import models
        from sqlalchemy import select
    except Exception:
        return {}, None

    meta = {s["ticker"]: s for s in US_UNIVERSE}
    out: dict[str, dict] = {}
    asof: Optional[str] = None
    try:
        s = db.get_session_factory()()
        try:
            stocks = s.execute(
                select(models.UsStock).where(models.UsStock.active.is_(True))
            ).scalars().all()
            for st in stocks:
                row = s.execute(
                    select(
                        models.UsDailyPrice.trading_date,
                        models.UsDailyPrice.overnight_return_pct,
                    )
                    .where(models.UsDailyPrice.ticker == st.ticker)
                    .order_by(models.UsDailyPrice.trading_date.desc())
                    .limit(1)
                ).first()
                if row is None:
                    continue
                tdate, ret = row
                if ret is None:
                    continue
                out[st.ticker] = {
                    "name": st.name or meta.get(st.ticker, {}).get("name") or st.ticker,
                    "weight": float(st.weight) if st.weight is not None else 1.0,
                    "kr_sector_lead": st.kr_sector_lead,
                    "ret": float(ret),
                    "date": tdate.isoformat() if tdate else None,
                }
                if tdate and (asof is None or tdate.isoformat() > asof):
                    asof = tdate.isoformat()
        finally:
            s.close()
    except Exception:
        return {}, None
    return out, asof


def _load_sector_members() -> dict[str, list[tuple[str, int]]]:
    """us_kr_lead_link → {kr_sector: [(us_ticker, lead_lag_days)]}. DB 미가용 시 코드 파생값."""
    try:
        import db
        import models
        from sqlalchemy import select

        s = db.get_session_factory()()
        try:
            rows = s.execute(
                select(models.UsKrLeadLink.kr_sector,
                       models.UsKrLeadLink.us_ticker,
                       models.UsKrLeadLink.lead_lag_days)
            ).all()
        finally:
            s.close()
        if rows:
            members: dict[str, list[tuple[str, int]]] = {}
            for sec, t, lag in rows:
                members.setdefault(sec, []).append((t, int(lag or DEFAULT_LEAD_LAG_DAYS)))
            return members
    except Exception:
        pass
    # 폴백: 코드 파생 링크 (DB 시드 전이라도 동작)
    members = {}
    for t, sec, lag in iter_lead_links():
        members.setdefault(sec, []).append((t, lag))
    return members


# ---------------------------------------------------------------------------
# 섹터 lead score 산출
# ---------------------------------------------------------------------------
def _sector_score(latest: dict, members: list[tuple[str, int]]) -> dict:
    num = den = 0.0
    movers: list[dict] = []
    lags: set[int] = set()
    for ticker, lag in members:
        d = latest.get(ticker)
        if not d:
            continue
        w = d["weight"]
        num += d["ret"] * w
        den += w
        lags.add(lag)
        movers.append({"ticker": ticker, "name": d["name"], "pct": round(d["ret"], 2)})
    if den == 0:
        return {"lead_score": 50, "avg_overnight_pct": None, "n": 0,
                "top_movers": [], "lead_lag_days": DEFAULT_LEAD_LAG_DAYS, "evidence": "N/A(데이터 없음)"}
    avg = num / den
    score = _clamp_score(50 + avg * LEAD_SCORE_GAIN)
    movers.sort(key=lambda m: abs(m["pct"]), reverse=True)
    top = movers[:TOP_MOVERS_N]
    ev = "밤사이 " + ", ".join(f"{m['name']} {m['pct']:+}%" for m in top)
    ev += f" (가중평균 {avg:+.2f}%, n={len(movers)})"
    return {
        "lead_score": score,
        "avg_overnight_pct": round(avg, 2),
        "n": len(movers),
        "top_movers": top,
        "lead_lag_days": min(lags) if lags else DEFAULT_LEAD_LAG_DAYS,
        "evidence": ev,
    }


def compute_us_lead(force: bool = False) -> dict:
    """KR 섹터별 'US 선행 점수' 산출 — 협업 허브 진입점.

    반환:
      {
        "asof": <us_daily_prices 최신 거래일 ISO | None>,
        "sectors": {sector: {lead_score(0~100), avg_overnight_pct, n, top_movers[], lead_lag_days, evidence}},
        "composite": int(0~100, 섹터 lead score 단순평균),
        "evidence": {sector: str},
        "note": <데이터 없음 안내 | None>,
        "cached": bool,
      }
    무데이터(수집 전)면 모든 섹터 50 중립 + note. global_macro 와 동일 캐시 TTL.
    """
    global _cache, _cache_ts
    with _lock:
        if not force and _cache is not None and (time.time() - _cache_ts) < _ttl():
            return _cache

    latest, asof = _load_latest()
    members = _load_sector_members()

    sectors: dict[str, dict] = {}
    evidence: dict[str, str] = {}
    for sector, mem in members.items():
        sc = _sector_score(latest, mem)
        sectors[sector] = sc
        evidence[sector] = sc["evidence"]

    scored = [v["lead_score"] for v in sectors.values() if v["n"] > 0]
    composite = _clamp_score(sum(scored) / len(scored)) if scored else 50
    note = None if latest else "us_daily_prices 비어있음 — scripts/us_leaders_sync.py 미실행(중립 50 폴백)"

    result = {
        "asof": asof,
        "sectors": sectors,
        "composite": composite,
        "evidence": evidence,
        "note": note,
        "cached": False,
    }
    with _lock:
        _cache = {**result, "cached": True}
        _cache_ts = time.time()
    return result


# ---------------------------------------------------------------------------
# 공통 인터페이스 (다른 엔진이 import 해서 쓰는 얇은 헬퍼)
# ---------------------------------------------------------------------------
def get_sector_lead_score(sector: str, force: bool = False) -> Optional[int]:
    """KR 섹터의 US 선행 점수(0~100). 데이터 없으면 None(50 폴백 강요 안 함 — 호출측 판단)."""
    r = compute_us_lead(force=force)
    sc = r["sectors"].get(sector)
    if not sc or sc.get("n", 0) == 0:
        return None
    return sc["lead_score"]


def get_lead_scores(force: bool = False) -> dict[str, int]:
    """{sector: lead_score} (데이터 있는 섹터만). sector_rotation/market_compass 입력용."""
    r = compute_us_lead(force=force)
    return {sec: sc["lead_score"] for sec, sc in r["sectors"].items() if sc.get("n", 0) > 0}


# ---------------------------------------------------------------------------
# 후속 통합 작업 (인터페이스만 노출 — 실제 배선은 'AI 예측 엔진' 전담 세션)
# ---------------------------------------------------------------------------
# TODO(sector_rotation): get_lead_scores() 를 sector_rotation.py 의 거시/모멘텀 레이어 입력으로
#       추가 — KR 섹터 점수에 미국 선행 보정(섹터별 lead_score 50 기준 가감).
# TODO(market_compass): compute_us_lead() 결과를 시장 나침반 순환 사다리/거시 매핑 단계에 표면화.
# TODO(kr_opening_gap): 선행 섹터 lead_score 를 KrOpeningGapSignal 컨텍스트로 공급(시초가 갭 해석).
# TODO(regime_analogs): 6D kNN(닷컴) **불변** — 확률 출력만 US 선행으로 조건화(엔진 내부 DIMS 미변경).
# TODO(corr): us_kr_lead_link.corr 를 룩백 상관(US ret[t-lag] vs KR 섹터 ret[t])으로 채우는 잡.


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    r = compute_us_lead(force=True)
    print(json.dumps(r, ensure_ascii=False, indent=2))
