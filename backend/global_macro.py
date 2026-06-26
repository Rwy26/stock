"""global_macro.py — 글로벌 매크로 투자심리 점수 엔진 (스펙 §2 · §7).

8대 점수(0~100, 50=중립) → composite(가중평균) → flow(구간 라벨) → 확률(1w/1m/3m) →
한국 7섹터 매핑을 **결정론적으로** 산출한다. LLM은 호출하지 않는다(해석은 market_compass LLM 단계).

원칙(스펙 §0): 모든 출력 수치에 원천값 evidence 동반, 무데이터는 중립(50) 폴백 + evidence 'N/A'.
캐시 TTL 은 market_compass 와 동일(장중 30분 / 장외 8시간).
"""

from __future__ import annotations

import math
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional

KST = ZoneInfo("Asia/Seoul")  # 장중 판정·표시 기준 시장 시간

import global_macro_feeds as feeds

# ---------------------------------------------------------------------------
# 상수 (스펙 §7.1 · §7.2)
# ---------------------------------------------------------------------------
SCORE_KEYS = ["liquidity", "growth", "inflation", "ai_cycle",
              "geopolitics", "risk_appetite", "us_equity", "kr_equity"]

# 종합 가중치 — 위험선호·유동성 선행 가중 (합 1.00, 스펙 §7.1)
COMPOSITE_WEIGHTS = {
    "risk_appetite": 0.22,
    "liquidity":     0.20,
    "ai_cycle":      0.16,
    "growth":        0.12,
    "inflation":     0.10,
    "geopolitics":   0.10,
    "us_equity":     0.06,
    "kr_equity":     0.04,
}

FLOW_BANDS = [(20, "매우약세"), (40, "약세"), (60, "중립"), (80, "강세"), (101, "매우강세")]

PROB_DECAY = {"1w": 1.0, "1m": 0.7, "3m": 0.5}   # 기간감쇠 (장기일수록 50%로 수렴)
PHASE2_MIN_SAMPLES = 60                            # 빈도 기반 자동 전환 임계 (거래일)
ANALOG_BAND = 8.0                                  # composite ±8pt 유사국면

# ---------------------------------------------------------------------------
# 캐시 (market_compass 규칙과 동일)
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_cache: Optional[dict] = None
_cache_ts: float = 0.0


def _ttl() -> int:
    now = datetime.now(KST)
    if now.weekday() < 5 and (9 * 60 <= now.hour * 60 + now.minute <= 15 * 60 + 30):
        return 1800
    return 28800


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------
def _clamp_score(raw: float) -> int:
    return int(max(0, min(100, round(raw))))


def _g(mkt: dict, name: str, field: str) -> Optional[float]:
    """market internals 안전 게터."""
    d = mkt.get(name)
    return d.get(field) if isinstance(d, dict) else None


def _pred(pred: dict, key: str) -> Optional[float]:
    row = pred.get(key) or {}
    return row.get("consensus")


# ---------------------------------------------------------------------------
# 점수 산출 — 각 함수: (score:int, evidence:list[str])
#   score = clamp(50 + Σ기여, 0, 100). 결측 입력은 기여 0 + evidence 'N/A'.
# ---------------------------------------------------------------------------
def _liquidity(pred, mkt, econ) -> tuple[int, list[str]]:
    c, ev = 0.0, []
    cut = _pred(pred, "fed_cut_next")
    if cut is not None:
        c += (cut - 50) * 0.40
        ev.append(f"Fed 인하확률 {cut}% (예측시장)")
    else:
        ev.append("Fed 인하확률 N/A(pred:N/A)")
    path = _pred(pred, "fed_path_eoy")
    if path is not None:
        ev.append(f"연말 금리경로 내재확률 {path}%")
    t10c = _g(mkt, "US10Y", "chg20d_pct")
    if t10c is not None:
        c += -t10c * 1.0
        ev.append(f"US10Y 20일 {t10c:+}% (상승=긴축)")
    dxyc = _g(mkt, "DXY", "chg20d_pct")
    if dxyc is not None:
        c += -dxyc * 1.5
        ev.append(f"DXY 20일 {dxyc:+}% (달러강세=긴축)")
    return _clamp_score(50 + c), ev


def _growth(pred, mkt, econ) -> tuple[int, list[str]]:
    c, ev = 0.0, []
    gdp = econ.get("gdp_qoq", {})
    if gdp.get("surprise"):
        c += gdp["surprise"] * 8
        ev.append(f"GDP {gdp.get('actual')}% surprise={gdp['surprise']:+d} (예상 {gdp.get('consensus')})")
    elif gdp.get("actual") is not None:
        ev.append(f"GDP {gdp.get('actual')}% (consensus N/A)")
    une = econ.get("unemployment", {})
    if une.get("actual") is not None:
        c += -une.get("surprise", 0) * 6
        ev.append(f"실업률 {une['actual']}% surprise={une.get('surprise', 0):+d}")
    ism = econ.get("ism_mfg", {})
    if ism.get("actual") is not None:
        c += (ism["actual"] - 50) * 0.5
        ev.append(f"ISM 제조업 {ism['actual']} ({'확장' if ism['actual'] >= 50 else '위축'})")
    rec = _pred(pred, "recession_2026")
    if rec is not None:
        c += -(rec - 50) * 0.40
        ev.append(f"경기침체 확률 {rec}% (예측시장)")
    else:
        ev.append("경기침체 확률 N/A(pred:N/A)")
    if not ev:
        ev.append("경기지표 N/A")
    return _clamp_score(50 + c), ev


def _inflation(pred, mkt, econ) -> tuple[int, list[str]]:
    """점수↑ = 물가안정."""
    c, ev = 0.0, []
    cpi = econ.get("cpi_yoy", {})
    if cpi.get("actual") is not None:
        c += -cpi.get("surprise", 0) * 8
        ev.append(f"CPI {cpi['actual']}% YoY surprise={cpi.get('surprise', 0):+d} (상회=물가압박)")
    core = econ.get("core_cpi", {})
    if core.get("actual") is not None:
        c += -core.get("surprise", 0) * 6
        ev.append(f"근원 CPI {core['actual']}% surprise={core.get('surprise', 0):+d}")
    cpithr = _pred(pred, "cpi_threshold")
    if cpithr is not None:
        c += -(cpithr - 50) * 0.30
        ev.append(f"CPI>3% 확률 {cpithr}% (예측시장)")
    wti = _g(mkt, "WTI", "chg5d_pct")
    if wti is not None:
        c += -wti * 0.60
        ev.append(f"WTI 5일 {wti:+}% (상승=물가압박)")
    if not ev:
        ev.append("물가지표 N/A")
    return _clamp_score(50 + c), ev


def _ai_cycle(pred, mkt, econ, news) -> tuple[int, list[str]]:
    c, ev = 0.0, []
    nas = _g(mkt, "NASDAQ", "chg20d_pct")
    if nas is not None:
        c += nas * 1.2
        ev.append(f"나스닥 20일 {nas:+}%")
    sp = _g(mkt, "SP500", "chg20d_pct")
    if sp is not None:
        c += sp * 0.4
        ev.append(f"S&P500 20일 {sp:+}%")
    ai_t = (news.get("by_topic") or {}).get("ai")
    if ai_t:
        c += ai_t["score_avg"] * 6
        ev.append(f"AI 뉴스감성 {ai_t['score_avg']:+} (n={ai_t['n']})")
    if not ev:
        ev.append("AI 사이클 데이터 N/A")
    return _clamp_score(50 + c), ev


def _geopolitics(pred, mkt, econ, news) -> tuple[int, list[str]]:
    """점수↑ = 지정학 리스크 완화."""
    c, ev = 0.0, []
    geo = _pred(pred, "geopol_mideast")
    if geo is not None:
        c += (geo - 50) * 0.40
        ev.append(f"중동 분쟁완화 확률 {geo}% (예측시장)")
    else:
        ev.append("중동 분쟁 예측시장 N/A(pred:N/A)")
    shut = _pred(pred, "us_gov_shutdown")
    if shut is not None:
        c += -(shut - 50) * 0.30
        ev.append(f"셧다운/부채한도 확률 {shut}%")
    gold = _g(mkt, "Gold", "chg5d_pct")
    if gold is not None:
        c += -gold * 0.80
        ev.append(f"금 5일 {gold:+}% (급등=리스크회피)")
    geo_t = (news.get("by_topic") or {}).get("지정학")
    if geo_t:
        c += geo_t["score_avg"] * 5
        ev.append(f"지정학 뉴스감성 {geo_t['score_avg']:+} (n={geo_t['n']})")
    return _clamp_score(50 + c), ev


def _risk_appetite(pred, mkt, econ) -> tuple[int, list[str]]:
    c, ev = 0.0, []
    vix = _g(mkt, "VIX", "last")
    if vix is not None:
        if vix < 20:
            c += (20 - vix) * 1.5
        elif vix > 25:
            c += -(vix - 25) * 1.5
        ev.append(f"VIX {vix} ({'안정' if vix < 20 else '경계' if vix > 25 else '중립'})")
    btc = _g(mkt, "BTC", "chg5d_pct")
    if btc is not None:
        c += btc * 0.30
        ev.append(f"BTC 5일 {btc:+}%")
    sp = _g(mkt, "SP500", "chg20d_pct")
    if sp is not None:
        c += sp * 1.0
        ev.append(f"S&P500 20일 {sp:+}%")
    rec = _pred(pred, "recession_2026")
    if rec is not None:
        c += -(rec - 50) * 0.20
    shut = _pred(pred, "us_gov_shutdown")
    if shut is not None:
        c += -(shut - 50) * 0.20
    if not ev:
        ev.append("위험선호 데이터 N/A")
    return _clamp_score(50 + c), ev


def _us_equity(mkt, risk, liq) -> tuple[int, list[str]]:
    c, ev = 0.0, []
    moms = []
    for nm in ("SP500", "NASDAQ", "Russell"):
        m = _g(mkt, nm, "chg20d_pct")
        if m is not None:
            moms.append(m)
    if moms:
        mom = sum(moms) / len(moms)
        c += mom * 1.0
        ev.append(f"미 지수 20일 모멘텀 평균 {mom:+.2f}%")
    c += (risk - 50) * 0.20 + (liq - 50) * 0.15
    ev.append(f"위험선호 {risk}·유동성 {liq} 가중 반영")
    return _clamp_score(50 + c), ev


def _kr_equity(mkt, us_eq, ai) -> tuple[int, list[str]]:
    c, ev = 0.0, []
    moms = []
    for nm in ("KOSPI", "KOSDAQ"):
        m = _g(mkt, nm, "chg20d_pct")
        if m is not None:
            moms.append(m)
    if moms:
        mom = sum(moms) / len(moms)
        c += mom * 1.0
        ev.append(f"코스피/코스닥 20일 모멘텀 평균 {mom:+.2f}%")
    c += (us_eq - 50) * 0.40
    ev.append(f"미국증시 {us_eq} ×0.4 동조")
    c += (ai - 50) * 0.20
    ev.append(f"반도체(AI사이클 {ai}) 반영")
    dxyc = _g(mkt, "DXY", "chg5d_pct")
    if dxyc is not None:
        c += dxyc * 0.20   # 달러강세=원화약세=수출주 환차익(소폭 +)
        ev.append(f"DXY 5일 {dxyc:+}% (원화약세 환효과)")
    return _clamp_score(50 + c), ev


# ---------------------------------------------------------------------------
# 한국 7섹터 매핑 (스펙 §2.4)
#   규칙: (factor, weight, inverse). inverse=True 면 (100-점수) 사용(지정학 역수 등),
#   factor="__neutral__" 는 상수 50(중립 기준). 섹터점수 = clamp(Σ weight·유효값).
# ---------------------------------------------------------------------------
KR_SECTOR_RULES: dict[str, list[tuple]] = {
    "반도체":  [("ai_cycle", 0.5, False), ("risk_appetite", 0.5, False)],
    "AI":      [("ai_cycle", 0.6, False), ("risk_appetite", 0.4, False)],
    "방산":    [("geopolitics", 0.5, True), ("growth", 0.5, False)],   # 지정학 역수=리스크↑ 수혜
    "조선":    [("geopolitics", 0.4, True), ("growth", 0.6, False)],
    "2차전지": [("liquidity", 0.5, False), ("growth", 0.5, False)],    # 금리역수=유동성
    "금융":    [("liquidity", 0.5, False), ("growth", 0.5, False)],
    "바이오":  [("__neutral__", 0.5, False), ("risk_appetite", 0.5, False)],  # 중립 기준
}

# 매트릭스 행(글로벌 펙터) 표시 순서·라벨
KR_FACTOR_LABELS = {
    "risk_appetite": "위험선호", "liquidity": "유동성", "ai_cycle": "AI 사이클",
    "growth": "경기", "geopolitics": "지정학", "__neutral__": "중립기준",
}
KR_FACTOR_ORDER = ["risk_appetite", "liquidity", "ai_cycle", "growth", "geopolitics", "__neutral__"]


def _eff_value(scores: dict, factor: str, inverse: bool) -> float:
    base = 50.0 if factor == "__neutral__" else float(scores.get(factor, 50))
    return 100.0 - base if inverse else base


def _kr_sectors(s: dict) -> dict[str, int]:
    out = {}
    for sector, rules in KR_SECTOR_RULES.items():
        out[sector] = _clamp_score(sum(w * _eff_value(s, f, inv) for f, w, inv in rules))
    return out


def _kr_sector_matrix(s: dict) -> dict:
    """펙터×섹터 영향 매트릭스 (히트맵용). 어떤 글로벌 펙터가 어떤 섹터를 얼마나 움직였는지.

    cell.value = 유효값(역수 반영, 50=중립) · cell.contribution = weight·유효값(섹터 점수 기여분).
    used factor 만 행으로 반환.
    """
    used = [f for f in KR_FACTOR_ORDER
            if any(f == rf for rules in KR_SECTOR_RULES.values() for rf, _, _ in rules)]
    cells: dict[str, dict] = {}
    for sector, rules in KR_SECTOR_RULES.items():
        row: dict[str, dict] = {}
        for f, w, inv in rules:
            val = _eff_value(s, f, inv)
            row[f] = {
                "weight": w,
                "value": round(val, 1),                 # 역수 반영된 유효값 (50=중립)
                "rawScore": 50 if f == "__neutral__" else s.get(f),
                "inverse": inv,
                "contribution": round(w * val, 1),
            }
        cells[sector] = row
    return {
        "factors": used,
        "factorLabels": {f: KR_FACTOR_LABELS[f] for f in used},
        "sectors": list(KR_SECTOR_RULES.keys()),
        "cells": cells,
    }


# ---------------------------------------------------------------------------
# 종합 · 자금흐름 · 확률 (스펙 §2.3 · §7.2)
# ---------------------------------------------------------------------------
def _composite(scores: dict) -> int:
    return _clamp_score(sum(scores[k] * w for k, w in COMPOSITE_WEIGHTS.items()))


def _flow_label(composite: int) -> str:
    for hi, label in FLOW_BANDS:
        if composite < hi:
            return label
    return "매우강세"


def _prob_deterministic(scores: dict) -> dict:
    """Phase 1: 결정론 로지스틱 (스펙 §7.2). method=deterministic, n=null."""
    mom = (scores["us_equity"] + scores["kr_equity"]) / 2.0
    z = 0.45 * (scores["risk_appetite"] - 50) + 0.30 * (scores["liquidity"] - 50) + 0.25 * (mom - 50)
    out: dict = {"method": "deterministic", "n": None}
    for period, decay in PROB_DECAY.items():
        zp = z * decay
        up = int(round(100 / (1 + math.exp(-zp / 18))))
        up = max(0, min(100, up))
        out[period] = {"up": up, "down": 100 - up}
    return out


def _prob_frequency(composite: int) -> Optional[dict]:
    """Phase 2: 표본≥60이면 유사국면(composite ±8) 전방 상승빈도로 교체. 미달 시 None.

    상승빈도 = 과거 동일국면 대비 N거래일 후 composite 상승 비율(가용 시계열 기준).
    """
    try:
        import db
        import models
        from sqlalchemy import select

        s = db.get_session_factory()()
        try:
            rows = s.execute(
                select(models.MacroSentimentDaily.trade_date, models.MacroSentimentDaily.composite)
                .order_by(models.MacroSentimentDaily.trade_date.asc())
            ).all()
        finally:
            s.close()
    except Exception:
        return None

    series = [int(c) for _, c in rows if c is not None]
    if len(series) < PHASE2_MIN_SAMPLES:
        return None

    horizons = {"1w": 1, "1m": 20, "3m": 60}
    out: dict = {"method": "frequency"}
    n_used = 0
    for period, h in horizons.items():
        ups = total = 0
        for i in range(len(series) - h):
            if abs(series[i] - composite) <= ANALOG_BAND:
                total += 1
                if series[i + h] > series[i]:
                    ups += 1
        if total > 0:
            up = int(round(ups / total * 100))
            out[period] = {"up": up, "down": 100 - up}
            n_used = max(n_used, total)
        else:
            # 해당 기간 유사표본 없음 → 중립 명시
            out[period] = {"up": 50, "down": 50}
    out["n"] = n_used
    if n_used == 0:
        return None
    return out


# ---------------------------------------------------------------------------
# 위험 신호 (결정론 탐지 — 수집 데이터에서 위험 조건을 룰로 판정, 근거 동반)
#   level: "위험"(danger) > "경고"(warning) > "주의"(caution). 없으면 "정상" 1건.
#   모든 신호는 원천값을 detail 에 명시(데이터 정확성 원칙 — 추정 금지).
# ---------------------------------------------------------------------------
_LEVEL_RANK = {"위험": 3, "경고": 2, "주의": 1, "정상": 0}


def _risk_signals(scores: dict, mkt: dict, pred: dict, prob: dict) -> list[dict]:
    sig: list[dict] = []

    def add(level, title, detail):
        sig.append({"level": level, "title": title, "detail": detail})

    # --- 종합/점수 기반 ---
    comp = _composite(scores)
    if comp < 20:
        add("위험", "종합심리 매우약세", f"composite {comp}/100 — 자금흐름 전반 위축(20 미만)")
    elif comp < 40:
        add("경고", "종합심리 약세", f"composite {comp}/100 — 약세 국면(40 미만)")

    thresholds = [
        ("risk_appetite", "위험선호 위축", "Risk-Off — VIX·신용·BTC·S&P 종합", 25, 35),
        ("liquidity", "유동성 긴축", "Fed경로·US10Y·DXY 종합 — 연료 부족", 25, 35),
        ("growth", "경기 둔화", "GDP·실업·ISM·침체확률 종합", 25, 35),
        ("inflation", "물가 재점화", "점수↓=물가압박 (CPI·유가·근원)", 25, 35),
        ("geopolitics", "지정학 리스크 고조", "점수↓=리스크확대 (예측시장·뉴스·Gold)", 25, 35),
    ]
    for key, title, why, dlvl, wlvl in thresholds:
        v = scores.get(key)
        if v is None:
            continue
        if v < dlvl:
            add("위험", title, f"{title.split()[0]} {v}/100 — {why}")
        elif v < wlvl:
            add("경고", title, f"{title.split()[0]} {v}/100 — {why}")

    # --- 시장 내부 신호 ---
    if mkt.get("yield_inverted"):
        sp = mkt.get("spread_10y_2y")
        add("경고", "장단기 금리 역전", f"US10Y-US2Y 스프레드 {sp}%p (<0) — 과거 경기침체 선행 신호")
    vix = (mkt.get("VIX") or {}).get("last") if isinstance(mkt.get("VIX"), dict) else None
    if vix is not None:
        if vix >= 30:
            add("위험", "변동성 급등(VIX)", f"VIX {vix} — 공포 구간(30↑)")
        elif vix >= 25:
            add("경고", "변동성 경계(VIX)", f"VIX {vix} — 경계 구간(25↑)")
        elif vix >= 20:
            add("주의", "변동성 상승(VIX)", f"VIX {vix} — 중립 상단(20↑)")
    gold = (mkt.get("Gold") or {}).get("chg5d_pct") if isinstance(mkt.get("Gold"), dict) else None
    if gold is not None and gold >= 3:
        add("주의", "안전자산 쏠림", f"금 5일 +{gold}% — 위험회피 자금 유입")
    dxy = (mkt.get("DXY") or {}).get("chg20d_pct") if isinstance(mkt.get("DXY"), dict) else None
    if dxy is not None and dxy >= 3:
        add("주의", "달러 강세 압박", f"DXY 20일 +{dxy}% — 신흥국·원화 긴축 압박")
    wti = (mkt.get("WTI") or {}).get("chg5d_pct") if isinstance(mkt.get("WTI"), dict) else None
    if wti is not None and wti >= 7:
        add("주의", "유가 급등", f"WTI 5일 +{wti}% — 인플레 재자극 가능")

    # --- 예측시장 기반 ---
    rec = _pred(pred, "recession_2026")
    if rec is not None and rec >= 50:
        add("경고", "경기침체 베팅 우위", f"침체 확률 {rec}% — 예측시장 과반(50%↑)")
    shut = _pred(pred, "us_gov_shutdown")
    if shut is not None and shut >= 50:
        add("주의", "셧다운/부채한도 리스크", f"확률 {shut}% — 캘린더 리스크")

    # --- 확률 기반 ---
    wk = prob.get("1w") if isinstance(prob.get("1w"), dict) else None
    if wk and wk.get("down", 0) > wk.get("up", 0):
        add("주의", "단기 하방 우위", f"1주 하락확률 {wk['down']}% > 상승확률 {wk['up']}% ({'빈도 n=' + str(prob.get('n')) if prob.get('method') == 'frequency' else '로지스틱'})")

    if not sig:
        add("정상", "특이 위험 신호 없음", "탐지 룰 임계 미달 — 현재 결정론 위험 신호 없음")

    sig.sort(key=lambda x: _LEVEL_RANK[x["level"]], reverse=True)
    return sig


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------
def compute_global_macro(force: bool = False) -> dict:
    global _cache, _cache_ts
    with _lock:
        if not force and _cache is not None and (time.time() - _cache_ts) < _ttl():
            return _cache

    pred = feeds.fetch_prediction_consensus()
    mkt = feeds.fetch_market_internals()
    econ = feeds.fetch_econ_surprises()
    news = feeds.fetch_news_sentiment()

    evidence: dict[str, list[str]] = {}
    scores: dict[str, int] = {}

    scores["liquidity"], evidence["liquidity"] = _liquidity(pred, mkt, econ)
    scores["growth"], evidence["growth"] = _growth(pred, mkt, econ)
    scores["inflation"], evidence["inflation"] = _inflation(pred, mkt, econ)
    scores["ai_cycle"], evidence["ai_cycle"] = _ai_cycle(pred, mkt, econ, news)
    scores["geopolitics"], evidence["geopolitics"] = _geopolitics(pred, mkt, econ, news)
    scores["risk_appetite"], evidence["risk_appetite"] = _risk_appetite(pred, mkt, econ)
    scores["us_equity"], evidence["us_equity"] = _us_equity(mkt, scores["risk_appetite"], scores["liquidity"])
    scores["kr_equity"], evidence["kr_equity"] = _kr_equity(mkt, scores["us_equity"], scores["ai_cycle"])

    composite = _composite(scores)
    flow = _flow_label(composite)

    prob = _prob_frequency(composite) or _prob_deterministic(scores)
    kr_sectors = _kr_sectors(scores)
    kr_sector_matrix = _kr_sector_matrix(scores)
    risk_signals = _risk_signals(scores, mkt, pred, prob)

    result = {
        "asof": datetime.now(KST).isoformat(timespec="seconds"),
        "scores": scores,
        "composite": composite,
        "flow": flow,
        "probabilities": prob,
        "kr_sectors": kr_sectors,
        "kr_sector_matrix": kr_sector_matrix,
        "risk_signals": risk_signals,
        "inputs": {
            "prediction": pred,
            "market": mkt,
            "econ": econ,
            "news": news,
        },
        "evidence": evidence,
        "weights": COMPOSITE_WEIGHTS,
        "cached": False,
    }
    with _lock:
        _cache = {**result, "cached": True}
        _cache_ts = time.time()
    return result


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    r = compute_global_macro(force=True)
    print(json.dumps({k: r[k] for k in ("asof", "scores", "composite", "flow",
                                        "probabilities", "kr_sectors", "evidence")},
                     ensure_ascii=False, indent=2))
