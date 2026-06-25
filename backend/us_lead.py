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

import bisect
import threading
import time
from datetime import date, datetime, timedelta
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
# Point-in-time lead score — 과거 시점 재현 (backtest 엄밀 측정용)
#   compute_us_lead 는 '현재' 점수만 준다. backtest 는 과거 KR 거래일 d 시점에서
#   "그날 아침 가용했던" US 선행점수가 필요하다. us_daily_prices 일별 overnight 으로
#   as-of 재현. 가용 규칙: US 거래일 < KR 거래일(미국 종가는 KR 익일 개장 전 확정)
#   → 미래 참조 없음. 무데이터/매핑없음 = None.
# ---------------------------------------------------------------------------
def _load_overnight_series() -> dict[str, list[tuple[str, float]]]:
    """{ticker: [(date_iso, overnight_ret)]} 날짜 오름차순. DB 미가용 시 {}."""
    try:
        import db
        import models
        from sqlalchemy import select
    except Exception:
        return {}
    out: dict[str, list[tuple[str, float]]] = {}
    try:
        s = db.get_session_factory()()
        try:
            rows = s.execute(
                select(models.UsDailyPrice.ticker,
                       models.UsDailyPrice.trading_date,
                       models.UsDailyPrice.overnight_return_pct)
                .order_by(models.UsDailyPrice.trading_date)
            ).all()
        finally:
            s.close()
    except Exception:
        return {}
    for tk, td, ret in rows:
        if ret is None or td is None:
            continue
        out.setdefault(tk, []).append((td.isoformat(), float(ret)))
    return out


def load_pit_context() -> tuple[dict, dict]:
    """backtest PIT 재측정용 1회 로드: (overnight_series, sector_members)."""
    return _load_overnight_series(), _load_sector_members()


def sector_lead_score_asof(sector: str, kr_date: str,
                           series: dict, members: dict) -> Optional[float]:
    """KR 거래일 kr_date(YYYYMMDD 또는 ISO) 아침 기준 섹터 US 선행점수(0~100).

    각 멤버 종목의 'US 거래일 < kr_date' 중 가장 최근 overnight 을 가중평균.
    미래 참조 없음(엄격 부등호). 데이터/매핑 없으면 None.
    """
    import bisect

    mem = members.get(sector)
    if not mem:
        return None
    iso = kr_date if "-" in kr_date else f"{kr_date[:4]}-{kr_date[4:6]}-{kr_date[6:8]}"
    meta = {s["ticker"]: s for s in US_UNIVERSE}
    num = den = 0.0
    for ticker, _lag in mem:
        sd = series.get(ticker)
        if not sd:
            continue
        dates = [d for d, _ in sd]
        j = bisect.bisect_left(dates, iso) - 1  # 가장 최근 US date < kr_date
        if j < 0:
            continue
        ret = sd[j][1]
        w = float(meta.get(ticker, {}).get("weight", 1.0))
        num += ret * w
        den += w
    if den == 0:
        return None
    return _clamp_score(50 + (num / den) * LEAD_SCORE_GAIN)


def get_opening_gap_context(force: bool = False) -> dict:
    """US 야간 등락 → KR 시초가 갭 '예상' 컨텍스트 (gap_signal_intake 공급용, 섹터 단위).

    개별 갭 신호 행(KrOpeningGapSignal) 스키마는 건드리지 않고, list_signals 응답에
    섹터 단위 보조 블록으로 표면화한다. expected_gap_bias = 섹터 가중평균
    overnight_return_pct(%) — KR 익일 개장 방향 힌트(예: NVDA/MU 밤사이 +2% → 반도체 갭 상방).
    데이터 없으면 sectors={} + note. (data-accuracy: 무데이터 섹터는 표면화하지 않음.)

    반환: {asof, sectors: {kr_sector: {lead_score, expected_gap_bias, lead_lag_days,
                                       top_movers[], evidence}}, note}
    """
    r = compute_us_lead(force=force)
    sectors: dict[str, dict] = {}
    for sec, sc in r["sectors"].items():
        if sc.get("n", 0) == 0:
            continue
        sectors[sec] = {
            "lead_score": sc["lead_score"],
            "expected_gap_bias": sc.get("avg_overnight_pct"),
            "lead_lag_days": sc.get("lead_lag_days"),
            "top_movers": sc.get("top_movers", []),
            "evidence": sc.get("evidence"),
        }
    return {"asof": r.get("asof"), "sectors": sectors, "note": r.get("note")}


# ---------------------------------------------------------------------------
# 룩백 상관 잡 — us_kr_lead_link.corr (US overnight[D] vs KR 섹터 ret[D 이후 lag번째 세션])
# ---------------------------------------------------------------------------
# us_lead 섹터 키(반도체/AI) → sector_rotation 의 KR 섹터 대표종목 키 매핑.
# (us_kr_lead_link.kr_sector 는 iter_lead_links() 의 '반도체'·'AI' 만 존재.)
US_LEAD_TO_ROTATION_SECTOR: dict[str, str] = {"반도체": "반도체", "AI": "AI 생태계"}
MIN_CORR_N = 10            # 표본 < 이 값이면 corr 미산출(NULL 유지 — 날조 금지)
CORR_LOOKBACK_DAYS = 180   # daily_prices / us_daily_prices 룩백 창


def _pearson(xs: list[float], ys: list[float]) -> Optional[float]:
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / (sxx ** 0.5 * syy ** 0.5)


def _kr_sector_daily_returns(s, codes: list[str], since: date) -> dict[date, float]:
    """KR 섹터 일별 수익률 {date: 구성종목 일수익률 평균(%)} — daily_prices(종가) 기준."""
    import models
    from sqlalchemy import select

    per_date: dict[date, list[float]] = {}
    for code in codes:
        rows = s.execute(
            select(models.DailyPrice.trading_date, models.DailyPrice.close_price)
            .where(models.DailyPrice.stock_code == code,
                   models.DailyPrice.trading_date >= since)
            .order_by(models.DailyPrice.trading_date.asc())
        ).all()
        prev: Optional[float] = None
        for d, c in rows:
            try:
                c = float(c)
            except (TypeError, ValueError):
                prev = None
                continue
            if prev is not None and prev > 0:
                per_date.setdefault(d, []).append((c - prev) / prev * 100.0)
            prev = c
    return {d: sum(v) / len(v) for d, v in per_date.items() if v}


def compute_lead_corr(lookback_days: int = CORR_LOOKBACK_DAYS) -> dict:
    """us_kr_lead_link.corr 산출·UPSERT — US 선행 ↔ KR 섹터 시차 상관.

    US 거래일 D 의 overnight_return_pct(밤사이 결과)를, D '이후' lead_lag_days 번째 KR
    거래 세션의 섹터 수익률과 짝지어 Pearson 상관을 계산한다. 미·한 거래 캘린더 차이는
    'D 직후 KR 세션' 시프트로 흡수한다(주말·공휴일 자동 처리). 표본 < MIN_CORR_N 이면
    corr 를 갱신하지 않는다(데이터 부족 — 날조 금지). DB 미가용 시 {ok:False}.

    반환: {ok, updated, skipped:[{ticker,sector,n,reason}], asof, lookback_days}
    """
    try:
        import db
        import models
        from sqlalchemy import select
    except Exception as exc:
        return {"ok": False, "error": f"import 실패: {type(exc).__name__}"}

    try:
        import sector_rotation
        rotation_sectors = sector_rotation.SECTORS
    except Exception as exc:
        return {"ok": False, "error": f"sector_rotation 로드 실패: {type(exc).__name__}"}

    since = date.today() - timedelta(days=lookback_days)
    updated = 0
    skipped: list[dict] = []
    try:
        with db.session_scope() as s:
            # US overnight 시계열 (ticker → [(date, ret)] 오름차순)
            us_rows = s.execute(
                select(models.UsDailyPrice.ticker,
                       models.UsDailyPrice.trading_date,
                       models.UsDailyPrice.overnight_return_pct)
                .where(models.UsDailyPrice.trading_date >= since)
                .order_by(models.UsDailyPrice.trading_date.asc())
            ).all()
            us_by_ticker: dict[str, list[tuple[date, float]]] = {}
            for t, d, ret in us_rows:
                if ret is None:
                    continue
                us_by_ticker.setdefault(t, []).append((d, float(ret)))

            # KR 섹터 수익률 캐시 (rotation 섹터 키 단위로 1회만 계산)
            kr_cache: dict[str, tuple[dict[date, float], list[date]]] = {}

            def _kr_for(us_sector: str):
                rot = US_LEAD_TO_ROTATION_SECTOR.get(us_sector)
                codes = rotation_sectors.get(rot) if rot else None
                if not codes:
                    return None
                if rot not in kr_cache:
                    rmap = _kr_sector_daily_returns(s, codes, since)
                    kr_cache[rot] = (rmap, sorted(rmap.keys()))
                return kr_cache[rot]

            links = s.execute(select(models.UsKrLeadLink)).scalars().all()
            for lk in links:
                us_series = us_by_ticker.get(lk.us_ticker, [])
                kr = _kr_for(lk.kr_sector)
                if kr is None:
                    skipped.append({"ticker": lk.us_ticker, "sector": lk.kr_sector,
                                    "n": 0, "reason": "KR 섹터 매핑/데이터 없음"})
                    continue
                kr_ret, kr_dates = kr
                lag = int(lk.lead_lag_days or DEFAULT_LEAD_LAG_DAYS)
                xs: list[float] = []
                ys: list[float] = []
                for d, ret in us_series:
                    # D 직후 lag 번째 KR 세션
                    i = bisect.bisect_right(kr_dates, d) + (lag - 1)
                    if 0 <= i < len(kr_dates):
                        xs.append(ret)
                        ys.append(kr_ret[kr_dates[i]])
                if len(xs) < MIN_CORR_N:
                    skipped.append({"ticker": lk.us_ticker, "sector": lk.kr_sector,
                                    "n": len(xs), "reason": f"표본<{MIN_CORR_N}"})
                    continue
                c = _pearson(xs, ys)
                if c is None:
                    skipped.append({"ticker": lk.us_ticker, "sector": lk.kr_sector,
                                    "n": len(xs), "reason": "분산 0"})
                    continue
                lk.corr = round(c, 4)
                updated += 1
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    return {"ok": True, "updated": updated, "skipped": skipped,
            "asof": date.today().isoformat(), "lookback_days": lookback_days}


# ---------------------------------------------------------------------------
# 후속 통합 작업 — 배선 완료 (2026-06-18, us-leaders-lead-lag).
#   sector_rotation / market_compass / kr_opening_gap / corr 4건 배선됨.
#   AI 예측 엔진 통합·regime_analogs 조건화는 각 전담 세션 소관(여기서 미처리).
# ---------------------------------------------------------------------------
# DONE(sector_rotation): get_lead_scores() → sector_rotation.compute_sector_rotation 의
#       보조 보정(usLead breakdown/usLeadScore detail, 보수적 ±bias). 무데이터면 무영향.
# DONE(market_compass): compute_us_lead() → market_compass usLead 블록 + 1단계 regime 보조신호.
# DONE(kr_opening_gap): get_opening_gap_context() → gap_signal_intake.list_signals usLeadContext.
# DONE(corr): compute_lead_corr() — us_kr_lead_link.corr UPSERT (US overnight ↔ KR 섹터 시차 상관).
# TODO(regime_analogs): 6D kNN(닷컴) **불변** — 확률 출력만 US 선행으로 조건화(별도 전담 세션).
# TODO(ai_prediction_engine): 시그널 적중 추적/피드백 루프 통합(별도 전담 세션).


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    if len(sys.argv) > 1 and sys.argv[1] == "corr":
        print(json.dumps(compute_lead_corr(), ensure_ascii=False, indent=2))
    else:
        r = compute_us_lead(force=True)
        print(json.dumps(r, ensure_ascii=False, indent=2))
