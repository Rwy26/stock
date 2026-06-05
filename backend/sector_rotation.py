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
    "AI·반도체":   ["000660", "005930", "042700", "288490"],  # SK하이닉스, 삼성전자, 한미반도체, 레이크머티
    "전력기기":    ["267260", "001440", "103590"],             # LS ELECTRIC, 국일신동, 한국전선
    "방산":        ["012450", "047810", "079550"],             # 한화에어로, KAI, LIG넥스원
    "조선":        ["009540", "010140", "042660"],             # HD한국조선해양, 삼성중공업, HD현대중공업
    "금융":        ["105560", "055550", "086790", "316140"],   # KB금융, 신한지주, 하나금융, 우리금융
    "2차전지":     ["373220", "051910", "096770"],             # LG에너지솔루션, LG화학, SK이노베이션
    "자동차·로봇": ["005380", "000270", "267250", "277810"],  # 현대차, 기아, 현대로보틱스, 레인보우로보틱스
    "바이오":      ["207940", "068270", "326030"],             # 삼성바이오, 셀트리온, SK바이오팜
}

# 종목 코드 → 한국어 이름
CODE_NAMES: Dict[str, str] = {
    "000660": "SK하이닉스",  "005930": "삼성전자",     "042700": "한미반도체",  "288490": "레이크머티",
    "267260": "LS ELECTRIC", "001440": "국일신동",     "103590": "한국전선",
    "012450": "한화에어로",  "047810": "KAI",          "079550": "LIG넥스원",
    "009540": "HD한국조선", "010140": "삼성중공업",   "042660": "HD현대중공",
    "105560": "KB금융",      "055550": "신한지주",     "086790": "하나금융",    "316140": "우리금융",
    "373220": "LG에너지솔", "051910": "LG화학",       "096770": "SK이노베이션",
    "005380": "현대차",      "000270": "기아",         "267250": "현대로보틱스", "277810": "레인보우로보",
    "207940": "삼성바이오", "068270": "셀트리온",     "326030": "SK바이오팜",
}

# 섹터별 주도주 / 소부장(소재·부품·장비) 구분
SECTOR_ROLES: Dict[str, Dict[str, List[str]]] = {
    "AI·반도체":   {"주도주": ["000660", "005930"], "소부장": ["042700", "288490"]},
    "전력기기":    {"주도주": ["267260"],            "소부장": ["001440", "103590"]},
    "방산":        {"주도주": ["012450", "047810"], "소부장": ["079550"]},
    "조선":        {"주도주": ["009540", "010140"], "소부장": ["042660"]},
    "금융":        {"주도주": ["105560", "055550"], "소부장": ["086790", "316140"]},
    "2차전지":     {"주도주": ["373220"],            "소부장": ["051910", "096770"]},
    "자동차·로봇": {"주도주": ["005380", "000270"], "소부장": ["267250", "277810"]},
    "바이오":      {"주도주": ["207940", "068270"], "소부장": ["326030"]},
}

# 섹터별 현재 시장 트렌드 테마 (주기적 갱신 예정)
SECTOR_TRENDS: Dict[str, Dict] = {
    "AI·반도체":   {"tags": ["HBM", "AI인프라", "엔비디아밸류체인"],       "theme": "AI 데이터센터 폭발적 수요"},
    "전력기기":    {"tags": ["데이터센터전력", "HVDC", "에너지전환"],       "theme": "전력망 현대화 수혜"},
    "방산":        {"tags": ["K방산수출", "NATO재무장", "폴란드계약"],      "theme": "글로벌 지정학 리스크 수혜"},
    "조선":        {"tags": ["LNG선", "친환경선박", "수주잔고최대"],        "theme": "조선 슈퍼사이클 진입"},
    "금융":        {"tags": ["고금리수혜", "밸류업", "배당확대"],           "theme": "정부 밸류업 프로그램"},
    "2차전지":     {"tags": ["ESS전환", "전기차조정", "소재다변화"],        "theme": "ESS·에너지저장 전환 모색"},
    "자동차·로봇": {"tags": ["AI로봇", "휴머노이드", "자율주행", "로봇택시"], "theme": "모빌리티·AI로봇 융합 테마"},
    "바이오":      {"tags": ["ADC항체약물", "비만치료제", "AI신약"],        "theme": "글로벌 바이오텍 확장"},
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
GROWTH_SECTORS = {"AI·반도체", "2차전지", "바이오", "자동차·로봇"}
VALUE_SECTORS  = {"금융", "방산"}

# ---------------------------------------------------------------------------
# Cache (1시간 TTL, thread-safe)
# ---------------------------------------------------------------------------
_cache_lock = threading.Lock()
_cache: Optional[dict] = None
_cache_ts: float = 0.0
CACHE_TTL = 28800  # 8시간 (매일 장마감 후 1회 갱신 권장)


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

        raw = yf.download(
            "^TNX DX-Y.NYB ^VIX ^IXIC KRW=X CL=F",
            period="60d", interval="1d", progress=False,
        )
        closes = raw["Close"]

        tnx    = closes["^TNX"].dropna()
        dxy    = closes["DX-Y.NYB"].dropna()
        vix    = closes["^VIX"].dropna()
        nasdaq = closes["^IXIC"].dropna()
        krw    = closes["KRW=X"].dropna()  # USD per 1 KRW (ex. 1380.5)
        oil    = closes["CL=F"].dropna()   # WTI 원유 선물 (USD/배럴)

        def _dir(series, n: int = 20) -> float:
            if len(series) < n + 1:
                return 0.0
            now_ = _safe(series.iloc[-1])
            past = _safe(series.iloc[-n])
            return (now_ - past) / (abs(past) + 1e-9)

        tnx_dir    = _dir(tnx)
        dxy_dir    = _dir(dxy)
        nasdaq_dir = _dir(nasdaq)
        vix_val    = _safe(vix.iloc[-1]) if len(vix) > 0 else 20.0

        growth_score = 50.0
        growth_score -= tnx_dir * 200   # 금리 상승 → 성장주 불리
        growth_score -= dxy_dir * 100   # 달러 강세 → 외국인 이탈
        growth_score -= max(0.0, (vix_val - 20.0) * 0.5)  # VIX 20 초과 → 위험
        growth_score = round(max(0.0, min(100.0, growth_score)), 1)

        nasdaq_val    = round(_safe(nasdaq.iloc[-1]), 0) if len(nasdaq) > 0 else None
        nasdaq_chg5d  = round(_dir(nasdaq, n=5)  * 100, 2)
        nasdaq_chg20d = round(_dir(nasdaq, n=20) * 100, 2)

        us_krw_val    = round(_safe(krw.iloc[-1]), 1) if len(krw) > 0 else None
        us_krw_chg5d  = round(_dir(krw, n=5)  * 100, 2) if len(krw) >= 6  else 0.0
        us_krw_chg20d = round(_dir(krw, n=20) * 100, 2) if len(krw) >= 21 else 0.0

        oil_val    = round(_safe(oil.iloc[-1]), 2) if len(oil) > 0 else None
        oil_chg5d  = round(_dir(oil, n=5)  * 100, 2) if len(oil) >= 6  else 0.0
        oil_chg20d = round(_dir(oil, n=20) * 100, 2) if len(oil) >= 21 else 0.0

        tnx_chg5d = round(_dir(tnx, n=5) * 100, 2) if len(tnx) >= 6 else 0.0

        detail = {
            "tnx":         round(_safe(tnx.iloc[-1]), 3) if len(tnx) > 0 else None,
            "dxy":         round(_safe(dxy.iloc[-1]), 3) if len(dxy) > 0 else None,
            "vix":         round(vix_val, 2),
            "tnx20dChg":   round(tnx_dir * 100, 2),
            "tnxChg5d":    tnx_chg5d,
            "dxy20dChg":   round(dxy_dir * 100, 2),
            "growthScore": growth_score,
            "nasdaq":      int(nasdaq_val) if nasdaq_val is not None else None,
            "nasdaqChg5d": nasdaq_chg5d,
            "nasdaqChg20d": nasdaq_chg20d,
            "usKrw":       us_krw_val,
            "usKrwChg5d":  us_krw_chg5d,
            "usKrwChg20d": us_krw_chg20d,
            "oil":         oil_val,
            "oilChg5d":    oil_chg5d,
            "oilChg20d":   oil_chg20d,
        }
        return growth_score, detail

    except Exception as exc:  # noqa: BLE001
        return 50.0, {"error": str(exc)}


# ---------------------------------------------------------------------------
# KIS credentials helper
# ---------------------------------------------------------------------------
def _get_kis_credentials() -> Tuple[Optional[str], Optional[str], bool]:
    """DB에서 첫 번째 KIS 자격증명 반환. 없으면 (None, None, False)."""
    try:
        import pymysql  # type: ignore
        from settings import settings as s
        conn = pymysql.connect(
            host=s.mysql_host, port=s.mysql_port,
            user=s.mysql_user, password=s.mysql_password,
            database=s.mysql_db, connect_timeout=5,
        )
        cursor = conn.cursor()
        cursor.execute(
            "SELECT app_key, app_secret, is_paper FROM kis_profiles ORDER BY id LIMIT 1"
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            return str(row[0]), str(row[1]), bool(row[2])
    except Exception:
        pass
    return None, None, False


# ---------------------------------------------------------------------------
# Layer 2 & 3: Foreign + Institutional Flow (KIS inquire_investor)
# ---------------------------------------------------------------------------
def _get_flow_scores() -> Dict[str, Dict[str, float]]:
    fallback = {
        s: {"foreign": 50.0, "institutional": 50.0,
            "foreign_raw": 0.0, "institutional_raw": 0.0}
        for s in SECTORS
    }

    app_key, app_secret, is_paper = _get_kis_credentials()
    if not app_key:
        return fallback

    try:
        from kis_client import inquire_investor  # type: ignore

        today = date.today()
        start_date = _date_str(today - timedelta(days=42))  # ~30 거래일 커버
        end_date = _date_str(today)

        # 모든 섹터 종목 중복 제거
        all_codes: List[str] = list({c for codes in SECTORS.values() for c in codes})

        def _safe_int(v: Any) -> int:
            try:
                return int(str(v or 0).replace(",", "").strip() or 0)
            except Exception:
                return 0

        def _fetch_one(code: str) -> Tuple[str, float, float]:
            try:
                result = inquire_investor(
                    app_key=app_key,        # type: ignore[arg-type]
                    app_secret=app_secret,  # type: ignore[arg-type]
                    is_paper=is_paper,
                    code=code,
                    start_date=start_date,
                    end_date=end_date,
                    timeout_seconds=15.0,
                )
                rows = result.get("output") or []

                # 값이 있는 행만 (오늘 장중 데이터 제외), 최근 20 거래일
                valid_rows = [
                    r for r in rows
                    if r.get("frgn_ntby_tr_pbmn") not in (None, "")
                ][:20]

                # frgn_ntby_tr_pbmn / orgn_ntby_tr_pbmn: 백만원 단위
                # 백만원 합계 → 억원 (/ 100)
                f_sum = sum(_safe_int(r.get("frgn_ntby_tr_pbmn")) for r in valid_rows)
                i_sum = sum(_safe_int(r.get("orgn_ntby_tr_pbmn")) for r in valid_rows)
                return code, f_sum / 100.0, i_sum / 100.0
            except Exception:
                return code, 0.0, 0.0

        import concurrent.futures as _cf
        code_flows: Dict[str, Tuple[float, float]] = {}
        with _cf.ThreadPoolExecutor(max_workers=5) as ex:
            futures = {ex.submit(_fetch_one, c): c for c in all_codes}
            for fut in _cf.as_completed(futures):
                c, f_val, i_val = fut.result()
                code_flows[c] = (f_val, i_val)

        sector_f: Dict[str, float] = {}
        sector_i: Dict[str, float] = {}
        for sector, codes in SECTORS.items():
            sector_f[sector] = sum(code_flows.get(c, (0.0, 0.0))[0] for c in codes)
            sector_i[sector] = sum(code_flows.get(c, (0.0, 0.0))[1] for c in codes)

        f_norm = _normalize(sector_f)
        i_norm = _normalize(sector_i)

        return {
            sector: {
                "foreign":           f_norm.get(sector, 50.0),
                "institutional":     i_norm.get(sector, 50.0),
                "foreign_raw":       round(sector_f.get(sector, 0.0), 0),
                "institutional_raw": round(sector_i.get(sector, 0.0), 0),
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
            "momentum_pct": 0.0, "volume_surge_pct": 0.0, "top_stocks": []}
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
        sector_top3: Dict[str, list] = {}

        for sector, codes in SECTORS.items():
            moms, vols = [], []
            code_14d: Dict[str, float] = {}
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

                    # 14거래일 수익률 (leadStocks용)
                    n14 = min(14, len(close) - 1)
                    if n14 > 0:
                        chg14 = (close.iloc[-1] - close.iloc[-n14]) / (close.iloc[-n14] + 1e-9) * 100
                        code_14d[code] = round(_safe(chg14), 2)

                except Exception:
                    continue

            raw_mom[sector] = sum(moms) / max(len(moms), 1) if moms else 0.0
            raw_vol[sector] = sum(vols) / max(len(vols), 1) if vols else 0.0

            # 14일 수익률 상위 3종목
            top3 = sorted(code_14d.items(), key=lambda x: x[1], reverse=True)[:3]
            sector_top3[sector] = [
                {"code": c, "name": CODE_NAMES.get(c, c), "change14d": v}
                for c, v in top3
            ]

        mom_norm = _normalize(raw_mom)
        vol_norm = _normalize(raw_vol)

        return {
            sector: {
                "momentum":          mom_norm.get(sector, 50.0),
                "volume":            vol_norm.get(sector, 50.0),
                "momentum_pct":      round(raw_mom.get(sector, 0.0), 2),
                "volume_surge_pct":  round(raw_vol.get(sector, 0.0), 2),
                "top_stocks":        sector_top3.get(sector, []),
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
            "leadNames":      [CODE_NAMES.get(c, c) for c in SECTOR_ROLES.get(sector, {}).get("주도주", SECTORS[sector][:2])[:2]],
            "componentNames": [CODE_NAMES.get(c, c) for c in SECTOR_ROLES.get(sector, {}).get("소부장", SECTORS[sector][2:4])[:2]],
            "trends":         SECTOR_TRENDS.get(sector, {"tags": [], "theme": ""}),
            "leadStocks":     pv.get("top_stocks", []),
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
