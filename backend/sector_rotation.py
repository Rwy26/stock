"""KOSPI Sector Rotation Engine v1

7-Layer Scoring:
  L1 Macro        15%  미국금리·달러·VIX 방향
  L2 Foreign      25%  외국인 순매수 (pykrx)
  L3 Institutional 20% 기관 순매수 (pykrx)
  L4 Momentum     20%  20일 주가 모멘텀
  L5 News          5%  (placeholder 50점)
  L6 Volume       10%  거래대금 급증
  L7 Smart         5%  스마트머니 (모멘텀+거래대금 복합)
"""
from __future__ import annotations

import math
import threading
import time
import warnings
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Sector definitions: 섹터명 → 대표 종목 코드 (KOSPI)
# ---------------------------------------------------------------------------
SECTORS: Dict[str, List[str]] = {
    "AI·반도체":  ["000660", "005930", "042700", "288490"],  # SK하이닉스, 삼성전자, 한미반도체, 레이크머티
    "전력기기":   ["267260", "001440", "103590"],             # LS ELECTRIC, 국일신동, 한국전선
    "방산":       ["012450", "047810", "079550"],             # 한화에어로, KAI, LIG넥스원
    "조선":       ["009540", "010140", "042660"],             # HD한국조선해양, 삼성중공업, HD현대중공업
    "금융":       ["105560", "055550", "086790", "316140"],   # KB금융, 신한지주, 하나금융, 우리금융
    "2차전지":    ["373220", "051910", "096770"],             # LG에너지솔루션, LG화학, SK이노베이션
    "자동차":     ["005380", "000270"],                       # 현대차, 기아
    "바이오":     ["207940", "068270", "326030"],             # 삼성바이오, 셀트리온, SK바이오팜
}

WEIGHTS = {
    "macro": 0.15,
    "foreign": 0.25,
    "institutional": 0.20,
    "momentum": 0.20,
    "news": 0.05,
    "volume": 0.10,
    "smart": 0.05,
}

# 성장주 우호 섹터 (금리하락 시 +) vs 가치주 우호 섹터 (금리상승 시 +)
GROWTH_SECTORS = {"AI·반도체", "2차전지", "바이오"}
VALUE_SECTORS = {"금융", "방산"}

# ---------------------------------------------------------------------------
# Cache (1시간 TTL, thread-safe)
# ---------------------------------------------------------------------------
_cache_lock = threading.Lock()
_cache: Optional[dict] = None
_cache_ts: float = 0.0
CACHE_TTL = 3600  # seconds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _safe(v: Any) -> float:
    try:
        f = float(v)
        return 0.0 if math.isnan(f) or math.isinf(f) else f
    except Exception:
        return 0.0


def _date_str(d: date | datetime) -> str:
    return d.strftime("%Y%m%d")


def _normalize(mapping: Dict[str, float]) -> Dict[str, float]:
    """최소-최대 정규화 → 0~100"""
    vals = list(mapping.values())
    mn, mx = min(vals), max(vals)
    if mx == mn:
        return {k: 50.0 for k in mapping}
    return {k: round((v - mn) / (mx - mn) * 100, 1) for k, v in mapping.items()}


# ---------------------------------------------------------------------------
# Layer 1: Macro Score
# ---------------------------------------------------------------------------
def _macro_score() -> Tuple[float, dict]:
    """
    금리·달러·VIX 방향으로 성장주 우호도 0~100 계산.
    금리↓ + 달러↓ + VIX↓ = 성장주 우호 (점수↑)
    """
    try:
        import yfinance as yf

        raw = yf.download("^TNX DX-Y.NYB ^VIX", period="60d", interval="1d", progress=False)
        closes = raw["Close"]

        tnx = closes["^TNX"].dropna()
        dxy = closes["DX-Y.NYB"].dropna()
        vix = closes["^VIX"].dropna()

        def _dir(series, n: int = 20) -> float:
            if len(series) < n + 1:
                return 0.0
            now_ = _safe(series.iloc[-1])
            past = _safe(series.iloc[-n])
            return (now_ - past) / (abs(past) + 1e-9)

        tnx_dir = _dir(tnx)
        dxy_dir = _dir(dxy)
        vix_val = _safe(vix.iloc[-1]) if len(vix) > 0 else 20.0

        growth_score = 50.0
        growth_score -= tnx_dir * 200   # 금리 상승 → 성장주 불리
        growth_score -= dxy_dir * 100   # 달러 강세 → 외국인 이탈
        growth_score -= max(0.0, (vix_val - 20.0) * 0.5)  # VIX 20 초과 → 위험
        growth_score = round(max(0.0, min(100.0, growth_score)), 1)

        detail = {
            "tnx":       round(_safe(tnx.iloc[-1]), 3) if len(tnx) > 0 else None,
            "dxy":       round(_safe(dxy.iloc[-1]), 3) if len(dxy) > 0 else None,
            "vix":       round(vix_val, 2),
            "tnx20dChg": round(tnx_dir * 100, 2),
            "dxy20dChg": round(dxy_dir * 100, 2),
            "growthScore": growth_score,
        }
        return growth_score, detail

    except Exception as exc:  # noqa: BLE001
        return 50.0, {"error": str(exc)}


# ---------------------------------------------------------------------------
# Layer 2 & 3: Foreign + Institutional Flow (pykrx)
# ---------------------------------------------------------------------------
def _get_flow_scores() -> Dict[str, Dict[str, float]]:
    fallback = {
        s: {"foreign": 50.0, "institutional": 50.0,
            "foreign_raw": 0.0, "institutional_raw": 0.0}
        for s in SECTORS
    }
    try:
        from pykrx import stock as pstock  # type: ignore

        today = date.today()
        start = today - timedelta(days=20)
        start_str = _date_str(start)
        end_str = _date_str(today)

        def _get_net(investor: str):
            try:
                return pstock.get_market_net_purchases_of_equities(
                    start_str, end_str, "KOSPI", investor
                )
            except Exception:
                return None

        df_f = _get_net("외국인")
        df_i = _get_net("기관합계")

        def _extract(df, code: str) -> float:
            if df is None or df.empty:
                return 0.0
            try:
                if code not in df.index:
                    return 0.0
                row = df.loc[code]
                for col in ["순매수거래대금", "순매수금액", "순매수"]:
                    if col in (row.index if hasattr(row, "index") else []):
                        return _safe(row[col])
                # 컬럼명이 다를 경우 마지막 수치 컬럼 사용
                vals = [_safe(v) for v in row.values if isinstance(v, (int, float))]
                return vals[-1] if vals else 0.0
            except Exception:
                return 0.0

        sector_f: Dict[str, float] = {}
        sector_i: Dict[str, float] = {}

        for sector, codes in SECTORS.items():
            sector_f[sector] = sum(_extract(df_f, c) for c in codes)
            sector_i[sector] = sum(_extract(df_i, c) for c in codes)

        f_norm = _normalize(sector_f)
        i_norm = _normalize(sector_i)

        return {
            sector: {
                "foreign":           f_norm.get(sector, 50.0),
                "institutional":     i_norm.get(sector, 50.0),
                "foreign_raw":       round(sector_f.get(sector, 0.0) / 1e8, 1),
                "institutional_raw": round(sector_i.get(sector, 0.0) / 1e8, 1),
            }
            for sector in SECTORS
        }

    except Exception:  # noqa: BLE001
        return fallback


# ---------------------------------------------------------------------------
# Layer 4 & 6: Price Momentum + Volume Surge (pykrx)
# ---------------------------------------------------------------------------
def _get_pv_scores() -> Dict[str, Dict[str, float]]:
    fallback = {
        s: {"momentum": 50.0, "volume": 50.0,
            "momentum_pct": 0.0, "volume_surge_pct": 0.0}
        for s in SECTORS
    }
    try:
        from pykrx import stock as pstock  # type: ignore

        today = date.today()
        start = today - timedelta(days=50)
        start_str = _date_str(start)
        end_str = _date_str(today)

        raw_mom: Dict[str, float] = {}
        raw_vol: Dict[str, float] = {}

        for sector, codes in SECTORS.items():
            moms, vols = [], []
            for code in codes:
                try:
                    df = pstock.get_market_ohlcv_by_date(start_str, end_str, code)
                    if df is None or df.empty or len(df) < 5:
                        continue
                    close = df["종가"]
                    volume = df["거래량"] * df["종가"]

                    n = min(20, len(close) - 1)
                    mom = (close.iloc[-1] - close.iloc[-n - 1]) / (close.iloc[-n - 1] + 1e-9) * 100
                    moms.append(_safe(mom))

                    if len(volume) >= 20:
                        surge = (
                            volume.iloc[-5:].mean()
                            / (volume.iloc[-20:].mean() + 1e-9)
                            - 1
                        ) * 100
                    else:
                        surge = 0.0
                    vols.append(_safe(surge))
                except Exception:
                    continue

            raw_mom[sector] = sum(moms) / max(len(moms), 1) if moms else 0.0
            raw_vol[sector] = sum(vols) / max(len(vols), 1) if vols else 0.0

        mom_norm = _normalize(raw_mom)
        vol_norm = _normalize(raw_vol)

        return {
            sector: {
                "momentum":          mom_norm.get(sector, 50.0),
                "volume":            vol_norm.get(sector, 50.0),
                "momentum_pct":      round(raw_mom.get(sector, 0.0), 2),
                "volume_surge_pct":  round(raw_vol.get(sector, 0.0), 2),
            }
            for sector in SECTORS
        }

    except Exception:  # noqa: BLE001
        return fallback


# ---------------------------------------------------------------------------
# Lifecycle detection
# ---------------------------------------------------------------------------
def _lifecycle(score: float, foreign: float, institutional: float) -> Tuple[str, int]:
    if score < 30:
        return "붕괴", 0
    if score < 42:
        return "관망", 1
    if institutional >= 62 and foreign < 55:
        return "기관매집", 2
    if foreign >= 62 and score < 70:
        return "외국인유입", 3
    if score >= 80 and score < 90:
        return "개인추격·과열", 5
    if score >= 90:
        return "분배주의", 6
    if score >= 70:
        return "뉴스확산", 4
    # 42~70 중간 구간
    if institutional >= 55:
        return "기관매집", 2
    return "외국인유입", 3


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------
def compute_sector_rotation(force: bool = False) -> dict:
    """전체 계산 후 JSON 직렬화 가능한 dict 반환. 1시간 캐시."""
    global _cache, _cache_ts

    with _cache_lock:
        now = time.time()
        if not force and _cache is not None and (now - _cache_ts) < CACHE_TTL:
            return _cache

    import concurrent.futures

    macro_score, macro_detail = _macro_score()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        flow_future = ex.submit(_get_flow_scores)
        pv_future = ex.submit(_get_pv_scores)
        flow_scores = flow_future.result()
        pv_scores = pv_future.result()

    sectors_out = []

    for sector in SECTORS:
        flow = flow_scores.get(sector, {})
        pv = pv_scores.get(sector, {})

        f_score = flow.get("foreign", 50.0)
        i_score = flow.get("institutional", 50.0)
        mom_score = pv.get("momentum", 50.0)
        vol_score = pv.get("volume", 50.0)
        smart = round(mom_score * 0.6 + vol_score * 0.4, 1)
        news_score = 50.0  # placeholder

        # 매크로 편향
        if sector in GROWTH_SECTORS:
            s_macro = macro_score
        elif sector in VALUE_SECTORS:
            s_macro = round(100.0 - macro_score, 1)
        else:
            s_macro = 50.0

        total = (
            WEIGHTS["macro"] * s_macro
            + WEIGHTS["foreign"] * f_score
            + WEIGHTS["institutional"] * i_score
            + WEIGHTS["momentum"] * mom_score
            + WEIGHTS["news"] * news_score
            + WEIGHTS["volume"] * vol_score
            + WEIGHTS["smart"] * smart
        )
        total = round(max(0.0, min(100.0, total)), 1)

        lifecycle_label, lifecycle_stage = _lifecycle(total, f_score, i_score)

        sectors_out.append({
            "sector":         sector,
            "score":          total,
            "lifecycle":      lifecycle_label,
            "lifecycleStage": lifecycle_stage,
            "stars":          min(5, max(1, round(total / 20))),
            "breakdown": {
                "macro":         round(s_macro, 1),
                "foreign":       f_score,
                "institutional": i_score,
                "momentum":      mom_score,
                "news":          news_score,
                "volume":        vol_score,
                "smart":         smart,
            },
            "detail": {
                "foreignBil":      flow.get("foreign_raw", 0.0),
                "institutionalBil": flow.get("institutional_raw", 0.0),
                "momentumPct":     pv.get("momentum_pct", 0.0),
                "volumeSurgePct":  pv.get("volume_surge_pct", 0.0),
            },
            "codes": SECTORS[sector],
        })

    sectors_out.sort(key=lambda x: x["score"], reverse=True)

    result: dict = {
        "asOf":           datetime.now().strftime("%Y-%m-%d %H:%M"),
        "macroDetail":    macro_detail,
        "sectors":        sectors_out,
        "topSectors":     [s["sector"] for s in sectors_out[:3]],
        "warningSectors": [s["sector"] for s in sectors_out if s["score"] < 40],
        "cached":         False,
    }

    with _cache_lock:
        _cache = {**result, "cached": True}
        _cache_ts = time.time()

    return result
