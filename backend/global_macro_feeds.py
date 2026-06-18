"""global_macro_feeds.py — 글로벌 매크로 투자심리 지수 수집 레이어 (스펙 §1).

원천 데이터 4종을 수집한다. **모든 함수는 실패 시 예외를 던지지 않고 해당 필드를 None 으로
반환**한다(데이터 정확성 원칙: 잘못된 값보다 N/A). 점수화/캐시는 호출측(global_macro.py)이 담당.

  1. 예측시장 (Polymarket gamma-api / Kalshi trade-api v2 / Metaculus api2, 전부 무인증 읽기)
  2. 글로벌 시장 데이터 (yfinance 15심볼 + 10Y-2Y 스프레드)
  3. 경제지표 surprise (FRED API[선택] + macro_consensus.json)
  4. 뉴스 감성 (기존 news_collector 재사용, 키워드 분류)

실엔드포인트 확정(2026-06-13 실조회):
  - Kalshi: https://api.elections.kalshi.com/trade-api/v2  (필드 yes_bid_dollars/yes_ask_dollars).
    확인된 활성 시리즈: KXRATECUT(금리인하), KXFED(기준금리 밴드), KXCPIYOY(CPI YoY),
    KXGDP(실질GDP), KXU3(실업률). recession/shutdown/지정학 시리즈는 현재 미개설 → N/A.
  - Polymarket gamma-api / Metaculus api2: 일부 네트워크에서 DNS 차단/403(Cloudflare) 발생 →
    fail-soft 로 None 폴백, 가용 소스(주로 Kalshi)로 재정규화한다(스펙 §2.2).
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Optional

import httpx

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------
_TIMEOUT = 10.0
_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

POLYMARKET_BASE = "https://gamma-api.polymarket.com"
KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
METACULUS_BASE = "https://www.metaculus.com/api2"

# 예측시장 가중치 (스펙 §2.2, 고정). 결측 시 가용분으로 재정규화는 global_macro 측에서 수행.
PREDICTION_WEIGHTS = {"polymarket": 0.4, "kalshi": 0.4, "metaculus": 0.2}

# ---------------------------------------------------------------------------
# 시한부 정책·선거 국면 가중 (미 중간선거 2026-11-03 까지)
#   ※ 날짜 하드코딩 단일 소스 — 다른 모듈은 election_window_active()/ELECTION_WINDOW_UNTIL 만 참조.
#   윈도우 동안 정치·Fed 성격 예측 타깃에 한해 Polymarket 0.6 / Kalshi 0.4 (Metaculus 제외)를
#   적용한다. 윈도우 종료(2026-11-04+) 시 _weights_for 가 자동으로 기본 가중으로 복귀하므로
#   별도 정리 작업이 필요 없다. 비정치 타깃은 항상 기본 PREDICTION_WEIGHTS 유지.
# ---------------------------------------------------------------------------
ELECTION_WINDOW_UNTIL = date(2026, 11, 3)

# 정치·Fed 성격 타깃 (윈도우 동안 가중 오버라이드 대상). 선거 관련 타깃을 PREDICTION_TARGETS 에
# 추가할 경우 그 key 도 여기에 등록하면 자동으로 오버라이드를 받는다.
POLICY_PREDICTION_TARGETS = {"fed_cut_next", "fed_path_eoy", "us_gov_shutdown", "house_majority_dem"}

# 윈도우 가중 (Metaculus 제외 — 정치·Fed 는 Polymarket 유동성이 압도적). 결측분 재정규화는
# fetch_prediction_consensus 가 가용 소스만으로 동일 규칙으로 처리.
POLICY_PREDICTION_WEIGHTS = {"polymarket": 0.6, "kalshi": 0.4}


def election_window_active(today: Optional[date] = None) -> bool:
    """오늘이 중간선거 시한부 윈도우(≤ ELECTION_WINDOW_UNTIL) 안인가."""
    return (today or date.today()) <= ELECTION_WINDOW_UNTIL


def _weights_for(target_key: str, today: Optional[date] = None) -> tuple[dict, str]:
    """타깃별 예측시장 소스 가중 + 모드 라벨. 정치·Fed 타깃 & 윈도우 내 → 정책 가중."""
    if target_key in POLICY_PREDICTION_TARGETS and election_window_active(today):
        return POLICY_PREDICTION_WEIGHTS, "policy_window"
    return PREDICTION_WEIGHTS, "default"

# 추적 이벤트 6개 (스펙 §7.4). slug/ticker/id 는 실조회로 확정.
#   kalshi: {"market": "<티커>"} 단일 시장 또는 {"series": "<시리즈>", "pick": ...} 자동선택.
#     pick="nearest_half" → Yes확률이 0.5 에 가장 가까운 임계 시장(시장 내재 중심값),
#     pick={"threshold": x} → 제목의 임계치(%)가 x 에 가장 가까운 시장.
#   polymarket_slug / metaculus_id 는 해당 소스 가용 시 사용(미가용 네트워크에선 N/A).
PREDICTION_TARGETS: list[dict] = [
    {
        "key": "recession_2026",
        "polymarket_slug": "us-recession-in-2026",
        "kalshi": None,                       # 현재 Kalshi 미개설 시리즈
        "metaculus_id": None,
        "feeds_into": ["growth", "risk_appetite"],
        "label": "미국 경기침체 (2026년 내)",
    },
    {
        "key": "fed_cut_next",
        "polymarket_slug": "fed-rate-cut-in-2026",
        "kalshi": {"market": "KXRATECUT-26DEC31"},   # "2027 이전 금리 인하?" — 확인됨
        "metaculus_id": None,
        "feeds_into": ["liquidity"],
        "label": "Fed 금리 인하 (연내)",
    },
    {
        "key": "fed_path_eoy",
        "polymarket_slug": None,
        "kalshi": {"series": "KXFED", "pick": "nearest_half"},  # 기준금리 밴드 — 확인됨
        "metaculus_id": None,
        "feeds_into": ["liquidity", "inflation"],
        "label": "연말 기준금리 경로",
    },
    {
        "key": "geopol_mideast",
        "polymarket_slug": "iran-israel-ceasefire-in-2026",
        "kalshi": None,
        "metaculus_id": None,
        "feeds_into": ["geopolitics"],
        "label": "이란·중동 분쟁 확전/종결",
    },
    {
        "key": "cpi_threshold",
        "polymarket_slug": None,
        "kalshi": {"series": "KXCPIYOY", "pick": {"threshold": 3.0}},  # CPI YoY > 3% — 확인됨
        "metaculus_id": None,
        "feeds_into": ["inflation"],
        "label": "헤드라인 CPI YoY > 3%",
    },
    {
        "key": "us_gov_shutdown",
        "polymarket_slug": "us-government-shutdown-in-2026",
        "kalshi": None,
        "metaculus_id": None,
        "feeds_into": ["risk_appetite", "geopolitics"],
        "label": "미 정부 셧다운/부채한도",
    },
]

# 글로벌 시장 심볼 (스펙 §1.2). US2Y 는 ^IRX(13주 T-bill)로 대용.
MARKET_SYMBOLS: dict[str, str] = {
    "VIX": "^VIX", "DXY": "DX-Y.NYB", "US10Y": "^TNX", "US2Y": "^IRX",
    "WTI": "CL=F", "Brent": "BZ=F", "Gold": "GC=F", "Copper": "HG=F",
    "SP500": "^GSPC", "NASDAQ": "^IXIC", "Russell": "^RUT",
    "KOSPI": "^KS11", "KOSDAQ": "^KQ11", "BTC": "BTC-USD", "ETH": "ETH-USD",
}

# FRED 시리즈 (스펙 §7.3). consensus(예상치)는 FRED 부재 → macro_consensus.json 에서 로드.
FRED_SERIES: dict[str, dict] = {
    "cpi_yoy":   {"id": "CPIAUCSL", "kind": "yoy",  "label": "헤드라인 CPI YoY"},
    "core_cpi":  {"id": "CPILFESL", "kind": "yoy",  "label": "근원 CPI YoY"},
    "ppi_yoy":   {"id": "PPIACO",   "kind": "yoy",  "label": "PPI YoY"},
    "unemployment": {"id": "UNRATE", "kind": "level", "label": "실업률(U-3)"},
    "gdp_qoq":   {"id": "GDPC1",    "kind": "qoq_annual", "label": "실질 GDP QoQ(연율)"},
    "ism_mfg":   {"id": "NAPM",     "kind": "level", "label": "ISM 제조업 PMI"},  # FRED 중단 가능 → None
}

_CONSENSUS_PATH = Path(__file__).resolve().parent / "macro_consensus.json"


# ---------------------------------------------------------------------------
# 1.1 예측시장
# ---------------------------------------------------------------------------
def _poly_yes_prob(slug: Optional[str]) -> Optional[float]:
    """Polymarket gamma-api: slug 시장의 Yes 확률(0~100). 실패 시 None."""
    if not slug:
        return None
    try:
        r = httpx.get(f"{POLYMARKET_BASE}/markets", params={"slug": slug},
                      headers=_UA, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        m = data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) else None)
        if not m:
            return None
        prices = m.get("outcomePrices")
        outcomes = m.get("outcomes")
        if isinstance(prices, str):
            prices = json.loads(prices)
        if isinstance(outcomes, str):
            outcomes = json.loads(outcomes)
        if not prices:
            return None
        idx = 0
        if outcomes:
            for i, o in enumerate(outcomes):
                if str(o).strip().lower() == "yes":
                    idx = i
                    break
        return round(float(prices[idx]) * 100, 1)
    except Exception:
        return None


def _kalshi_mid(market: dict) -> Optional[float]:
    """Kalshi 시장 객체 → Yes 중간값(0~100). 신·구 필드(_dollars/cents) 모두 대응."""
    bid = market.get("yes_bid_dollars")
    ask = market.get("yes_ask_dollars")
    if bid is None and ask is None:
        # 구 API: 센트 단위
        bid = market.get("yes_bid")
        ask = market.get("yes_ask")
        if bid is not None:
            bid = float(bid) / 100.0
        if ask is not None:
            ask = float(ask) / 100.0
    vals = [float(v) for v in (bid, ask) if v not in (None, "")]
    if not vals:
        return None
    return round(sum(vals) / len(vals) * 100, 1)


def _parse_threshold(market: dict) -> Optional[float]:
    """Kalshi 임계치(%) 추출 — 티커 접미 -Tx.x 우선, 없으면 제목 정규식."""
    t = str(market.get("ticker") or "")
    mt = re.search(r"-T(-?\d+(?:\.\d+)?)", t)
    if mt:
        return float(mt.group(1))
    mt = re.search(r"(-?\d+(?:\.\d+)?)\s*%", str(market.get("title") or ""))
    return float(mt.group(1)) if mt else None


def _kalshi_yes_prob(spec: Optional[dict]) -> Optional[float]:
    """Kalshi trade-api v2: 단일 시장 또는 시리즈 자동선택 → Yes 확률(0~100)."""
    if not spec:
        return None
    try:
        if "market" in spec:
            r = httpx.get(f"{KALSHI_BASE}/markets/{spec['market']}", timeout=_TIMEOUT)
            r.raise_for_status()
            return _kalshi_mid(r.json().get("market", {}))

        if "series" in spec:
            r = httpx.get(f"{KALSHI_BASE}/markets",
                          params={"series_ticker": spec["series"], "status": "open", "limit": 100},
                          timeout=_TIMEOUT)
            r.raise_for_status()
            markets = r.json().get("markets", [])
            cand = []
            for m in markets:
                p = _kalshi_mid(m)
                if p is None:
                    continue
                cand.append((m, p))
            if not cand:
                return None
            pick = spec.get("pick", "nearest_half")
            if isinstance(pick, dict) and "threshold" in pick:
                tgt = float(pick["threshold"])
                cand2 = [(m, p, _parse_threshold(m)) for m, p in cand]
                cand2 = [c for c in cand2 if c[2] is not None]
                if cand2:
                    m, p, _ = min(cand2, key=lambda c: abs(c[2] - tgt))
                    return p
                # 임계치 파싱 실패 → nearest_half 폴백
            # nearest_half: Yes 확률이 50에 가장 가까운 시장(시장 내재 중심값)
            m, p = min(cand, key=lambda c: abs(c[1] - 50.0))
            return p
    except Exception:
        return None
    return None


def _metaculus_q2(qid: Optional[int]) -> Optional[float]:
    """Metaculus api2: community_prediction.full.q2(중앙값, 0~1) → 0~100. 실패 시 None."""
    if not qid:
        return None
    try:
        r = httpx.get(f"{METACULUS_BASE}/questions/{qid}/", headers=_UA, timeout=_TIMEOUT)
        r.raise_for_status()
        d = r.json()
        # 신/구 스키마 모두 시도
        cp = (d.get("community_prediction") or {}).get("full") or {}
        q2 = cp.get("q2")
        if q2 is None:
            agg = (((d.get("question") or {}).get("aggregations") or {})
                   .get("recency_weighted") or {}).get("latest") or {}
            centers = agg.get("centers")
            if centers:
                q2 = centers[0]
        return round(float(q2) * 100, 1) if q2 is not None else None
    except Exception:
        return None


def fetch_prediction_consensus(today: Optional[date] = None) -> dict[str, dict]:
    """추적 이벤트 6개의 3소스 확률 + 재정규화 consensus.

    반환: {key: {polymarket, kalshi, metaculus, consensus, n_sources, weight_mode, feeds_into, label}}.
    3소스 모두 결측 → consensus=None, n_sources=0 (점수엔진이 중립 50 폴백 + evidence 'pred:N/A').

    weight_mode="policy_window" 인 정치·Fed 타깃은 시한부 윈도우 동안 Polymarket 0.6/Kalshi 0.4
    (Metaculus 제외)로 가중되고, 그 외/윈도우 밖은 "default"(0.4/0.4/0.2). today 는 테스트용 주입.
    가중에 포함되지 않는 소스(정책 윈도우의 Metaculus)는 consensus 산출에서 제외하되 원천값은 그대로 노출.
    """
    out: dict[str, dict] = {}
    for tgt in PREDICTION_TARGETS:
        poly = _poly_yes_prob(tgt.get("polymarket_slug"))
        kal = _kalshi_yes_prob(tgt.get("kalshi"))
        meta = _metaculus_q2(tgt.get("metaculus_id"))

        weights, weight_mode = _weights_for(tgt["key"], today)
        parts = {"polymarket": poly, "kalshi": kal, "metaculus": meta}
        # 가중 맵에 든 소스 중 가용분만 사용 → 결측분 재정규화(기존 규칙 동일, 어떤 조합에서도 작동)
        avail = {k: v for k, v in parts.items() if v is not None and k in weights}
        consensus = None
        if avail:
            wsum = sum(weights[k] for k in avail)
            consensus = round(sum(v * weights[k] for k, v in avail.items()) / wsum, 1)
        out[tgt["key"]] = {
            "polymarket": poly, "kalshi": kal, "metaculus": meta,
            "consensus": consensus, "n_sources": len(avail),
            "weight_mode": weight_mode,
            "feeds_into": tgt["feeds_into"], "label": tgt["label"],
        }
    return out


# ---------------------------------------------------------------------------
# 1.2 글로벌 시장 데이터 (yfinance)
# ---------------------------------------------------------------------------
def _pct(series, lookback: int) -> Optional[float]:
    try:
        s = series.dropna()
        if len(s) <= lookback:
            return None
        cur = float(s.iloc[-1])
        prev = float(s.iloc[-1 - lookback])
        if prev == 0:
            return None
        return round((cur - prev) / prev * 100, 2)
    except Exception:
        return None


def fetch_market_internals() -> dict:
    """15심볼의 last/chg5d_pct/chg20d_pct + US10Y-US2Y 스프레드.

    각 심볼은 개별적으로 None 폴백. yfinance 미설치 시 전체 None.
    """
    out: dict[str, Optional[dict]] = {k: None for k in MARKET_SYMBOLS}
    out["spread_10y_2y"] = None
    out["yield_inverted"] = None
    try:
        import yfinance as yf
    except Exception:
        out["_note"] = "yfinance not installed — market internals N/A"
        return out

    try:
        data = yf.download(list(MARKET_SYMBOLS.values()), period="3mo",
                           progress=False, threads=True)
        close = data["Close"]
    except Exception as exc:  # noqa: BLE001
        out["_note"] = f"yfinance download failed: {type(exc).__name__}"
        return out

    last_vals: dict[str, Optional[float]] = {}
    for name, sym in MARKET_SYMBOLS.items():
        try:
            ser = close[sym]
            sclean = ser.dropna()
            if sclean.empty:
                out[name] = None
                last_vals[name] = None
                continue
            last = round(float(sclean.iloc[-1]), 2)
            last_vals[name] = last
            out[name] = {
                "last": last,
                "chg5d_pct": _pct(ser, 5),
                "chg20d_pct": _pct(ser, 20),
            }
        except Exception:
            out[name] = None
            last_vals[name] = None

    # 장단기 금리 스프레드 (^TNX=10Y, ^IRX=13주 T-bill 대용 — 둘 다 %로 직접 표기)
    t10, t2 = last_vals.get("US10Y"), last_vals.get("US2Y")
    if t10 is not None and t2 is not None:
        spread = round(t10 - t2, 3)
        out["spread_10y_2y"] = spread
        out["yield_inverted"] = spread < 0
    return out


# ---------------------------------------------------------------------------
# 1.3 경제지표 surprise
# ---------------------------------------------------------------------------
def _load_consensus() -> dict:
    try:
        if _CONSENSUS_PATH.exists():
            return json.loads(_CONSENSUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _fred_observations(series_id: str, api_key: str, limit: int = 16) -> Optional[list]:
    try:
        r = httpx.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={"series_id": series_id, "api_key": api_key, "file_type": "json",
                    "sort_order": "desc", "limit": limit},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        obs = r.json().get("observations", [])
        vals = []
        for o in obs:
            v = o.get("value")
            if v not in (None, "", "."):
                try:
                    vals.append(float(v))
                except Exception:
                    continue
        return vals or None
    except Exception:
        return None


def _compute_actual(kind: str, vals: list) -> Optional[float]:
    """FRED 관측치(desc 정렬) → actual 값. yoy=12개월 전 대비, qoq_annual=직전 분기 연율."""
    try:
        if kind == "level":
            return round(vals[0], 2)
        if kind == "yoy":
            if len(vals) > 12 and vals[12] != 0:
                return round((vals[0] - vals[12]) / vals[12] * 100, 2)
            return None
        if kind == "qoq_annual":
            if len(vals) > 1 and vals[1] != 0:
                return round(((vals[0] / vals[1]) ** 4 - 1) * 100, 2)
            return None
    except Exception:
        return None
    return None


def fetch_econ_surprises() -> dict[str, dict]:
    """경제지표 actual/consensus/surprise. surprise = sign(actual - consensus) ∈ {+1,0,-1}.

    FRED_API_KEY 없으면 actual=None. consensus 없으면 surprise=0(부합) + note(추정 금지).
    """
    from settings import settings

    api_key = getattr(settings, "fred_api_key", "") or ""
    consensus_map = _load_consensus()
    out: dict[str, dict] = {}

    for key, meta in FRED_SERIES.items():
        actual = None
        note = None
        if api_key:
            vals = _fred_observations(meta["id"], api_key)
            if vals:
                actual = _compute_actual(meta["kind"], vals)
            if actual is None:
                note = f"FRED {meta['id']} unavailable"
        else:
            note = "no FRED_API_KEY"

        consensus = consensus_map.get(key)
        if isinstance(consensus, dict):
            consensus = consensus.get("consensus")

        if actual is None or consensus is None:
            surprise = 0
            if consensus is None and note is None:
                note = "no consensus"
        else:
            diff = actual - float(consensus)
            surprise = 1 if diff > 0 else (-1 if diff < 0 else 0)

        out[key] = {
            "label": meta["label"], "actual": actual,
            "consensus": consensus, "surprise": surprise, "note": note,
        }
    return out


# ---------------------------------------------------------------------------
# 1.4 뉴스 감성 (news_collector 재사용 — 키워드 분류, LLM 미사용)
# ---------------------------------------------------------------------------
_SENT_KW = {
    2:  ["사상 최고", "신고가", "급등", "어닝 서프라이즈", "수주 대박", "역대 최대", "강세 지속"],
    1:  ["상승", "개선", "호조", "기대", "수주", "흑자", "반등", "완화", "타결", "인하"],
    -1: ["하락", "둔화", "부진", "우려", "감소", "약세", "적자", "경고", "조정", "리스크"],
    -2: ["급락", "폭락", "쇼크", "위기", "디폴트", "패닉", "전쟁", "확전", "셧다운", "파산"],
}
_TOPIC_KW = {
    "경기": ["경기", "성장", "gdp", "고용", "실업", "소비", "제조업", "침체"],
    "인플레": ["물가", "인플레", "cpi", "금리", "연준", "fed", "유가"],
    "지정학": ["전쟁", "분쟁", "이란", "중동", "지정학", "관세", "제재", "셧다운"],
    "ai": ["ai", "반도체", "엔비디아", "nvidia", "capex", "데이터센터", "hbm", "gpu"],
}


def _classify(title: str) -> tuple[int, list[str]]:
    t = (title or "").lower()
    score = 0
    for val in (2, -2, 1, -1):       # 강한 신호 우선
        for kw in _SENT_KW[val]:
            if kw.lower() in t:
                score = val
                break
        if score != 0:
            break
    topics = [tp for tp, kws in _TOPIC_KW.items() if any(k in t for k in kws)]
    return score, topics


def fetch_news_sentiment() -> dict:
    """뉴스 헤드라인 감성 5점 척도(+2~-2) 평균 + 토픽별 집계. 실패 시 N/A."""
    out = {"score_avg": None, "n": 0, "by_topic": {}, "note": None}
    try:
        import news_collector
        ctx = news_collector.get_news_context(max_headlines_per_sector=10)
    except Exception as exc:  # noqa: BLE001
        out["note"] = f"news_collector unavailable: {type(exc).__name__}"
        return out

    scores: list[int] = []
    by_topic: dict[str, list[int]] = {}
    for sec in (ctx.get("sectors") or {}).values():
        for h in sec.get("headlines", []):
            s, topics = _classify(h.get("title", ""))
            scores.append(s)
            for tp in topics:
                by_topic.setdefault(tp, []).append(s)

    if not scores:
        out["note"] = "no headlines"
        return out
    out["score_avg"] = round(sum(scores) / len(scores), 3)
    out["n"] = len(scores)
    out["by_topic"] = {
        tp: {"score_avg": round(sum(v) / len(v), 3), "n": len(v)}
        for tp, v in by_topic.items()
    }
    return out


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    print("=== prediction consensus ===")
    print(json.dumps(fetch_prediction_consensus(), ensure_ascii=False, indent=2))
    print("=== market internals ===")
    print(json.dumps(fetch_market_internals(), ensure_ascii=False, indent=2))
    print("=== econ surprises ===")
    print(json.dumps(fetch_econ_surprises(), ensure_ascii=False, indent=2))
    print("=== news sentiment ===")
    print(json.dumps(fetch_news_sentiment(), ensure_ascii=False, indent=2))
