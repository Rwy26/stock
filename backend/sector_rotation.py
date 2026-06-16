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
# 관심종목(sector_classification.json)과 동일한 섹터 체계.
# 각 섹터 대표 4종목 = 시총 상위(대장주 우선). 코드↔이름은 네이버 금융으로 전수 검증(2026-06-10).
SECTORS: Dict[str, List[str]] = {
    "반도체":      ["005930", "000660", "009150", "042700"],  # 삼성전자, SK하이닉스, 삼성전기, 한미반도체
    "AI 생태계":   ["035420", "034730", "018260", "030200"],  # NAVER, SK, 삼성에스디에스, KT
    "모빌리티":    ["005380", "000270", "003620", "012330", "066570", "011210",  # 현대차,기아,KG모빌리티,현대모비스,LG전자,현대위아
                    "454910", "307950", "204320", "373220", "006400", "319400",  # 두산로보틱스,현대오토에버,HL만도,LG엔솔,삼성SDI,현대무벡스
                    "096770", "005490", "457190", "247540", "222080", "003670"],  # SK이노,포스코홀딩스,이수스페셜티,에코프로비엠,씨아이에스,포스코퓨처엠
    "전력 인프라": ["267260", "103590", "001440", "060370"],  # HD현대일렉트릭, 일진전기, 대한전선, LS마린솔루션
    "조선":        ["329180", "009540", "042660", "010140"],  # HD현대중공업, HD한국조선해양, 한화오션, 삼성중공업
    "방산":        ["012450", "047810", "272210", "079550"],  # 한화에어로스페이스, 한국항공우주, 한화시스템, LIG디펜스
    "금융":        ["105560", "055550", "086790", "316140"],  # KB금융, 신한지주, 하나금융지주, 우리금융지주
    "바이오":      ["207940", "068270", "196170", "326030"],  # 삼성바이오로직스, 셀트리온, 알테오젠, SK바이오팜
    "화학":        ["051910", "009830", "010060"],             # LG화학, 한화솔루션, OCI홀딩스
    "경기소비재":  ["000720", "047040", "097950", "005300", "139480", "352820"],  # 현대건설,대우건설,CJ제일제당,롯데칠성,이마트,하이브
}

# 섹터 별칭 — 자동차·로봇·2차전지 등으로 입력돼도 모빌리티로 귀속 (전 시스템 공유)
SECTOR_ALIASES: Dict[str, str] = {
    "자동차": "모빌리티", "로봇 AI": "모빌리티", "로봇AI": "모빌리티", "로봇": "모빌리티",
    "2차전지": "모빌리티", "이차전지": "모빌리티", "배터리": "모빌리티", "전기차": "모빌리티",
}


def canonical_sector(name: str | None) -> str | None:
    """섹터명을 정식 분류로 정규화 (별칭 → 모빌리티 등). 없으면 원본 반환."""
    if not name:
        return name
    s = str(name).strip()
    return SECTOR_ALIASES.get(s, s)

# 종목 코드 → 한국어 이름 (네이버 금융 기준 실명)
CODE_NAMES: Dict[str, str] = {
    "005930": "삼성전자",     "000660": "SK하이닉스",   "009150": "삼성전기",     "042700": "한미반도체",
    "035420": "NAVER",        "034730": "SK",           "018260": "삼성에스디에스", "030200": "KT",
    "005380": "현대차",       "000270": "기아",         "277810": "레인보우로보틱스", "108490": "로보티즈",
    "267260": "HD현대일렉트릭", "103590": "일진전기",   "001440": "대한전선",     "060370": "LS마린솔루션",
    "329180": "HD현대중공업", "009540": "HD한국조선해양", "042660": "한화오션",   "010140": "삼성중공업",
    "012450": "한화에어로스페이스", "047810": "한국항공우주", "272210": "한화시스템", "079550": "LIG디펜스",
    "105560": "KB금융",       "055550": "신한지주",     "086790": "하나금융지주", "316140": "우리금융지주",
    "207940": "삼성바이오로직스", "068270": "셀트리온", "196170": "알테오젠",     "326030": "SK바이오팜",
    "373220": "LG에너지솔루션", "051910": "LG화학",     "247540": "에코프로비엠", "003670": "포스코퓨처엠",
    "096770": "SK이노베이션", "009830": "한화솔루션",   "010060": "OCI홀딩스",
    "000720": "현대건설",     "047040": "대우건설",     "097950": "CJ제일제당",   "005300": "롯데칠성",
    "139480": "이마트",       "352820": "하이브",
    # 모빌리티 신규
    "003620": "KG모빌리티",   "012330": "현대모비스",   "066570": "LG전자",       "011210": "현대위아",
    "454910": "두산로보틱스", "307950": "현대오토에버", "204320": "HL만도",       "006400": "삼성SDI",
    "319400": "현대무벡스",   "005490": "POSCO홀딩스",  "457190": "이수스페셜티케미컬", "222080": "씨아이에스",
}

# 섹터별 주도주(시총 대장) / 소부장·동종 구분 — 주도주 = 시총 상위 2개
SECTOR_ROLES: Dict[str, Dict[str, List[str]]] = {
    "반도체":      {"주도주": ["005930", "000660"], "소부장": ["009150", "042700"]},
    "AI 생태계":   {"주도주": ["035420", "034730"], "소부장": ["018260", "030200"]},
    "모빌리티":    {"주도주": ["005380", "000270"], "소부장": ["012330", "204320"]},
    "전력 인프라": {"주도주": ["267260", "103590"], "소부장": ["001440", "060370"]},
    "조선":        {"주도주": ["329180", "009540"], "소부장": ["042660", "010140"]},
    "방산":        {"주도주": ["012450", "047810"], "소부장": ["272210", "079550"]},
    "금융":        {"주도주": ["105560", "055550"], "소부장": ["086790", "316140"]},
    "바이오":      {"주도주": ["207940", "068270"], "소부장": ["196170", "326030"]},
    "화학":        {"주도주": ["051910", "009830"], "소부장": ["010060"]},
    "경기소비재":  {"주도주": ["000720", "097950"], "소부장": ["139480", "352820"]},
}

# 섹터별 현재 시장 트렌드 테마 (주기적 갱신 예정)
SECTOR_TRENDS: Dict[str, Dict] = {
    "반도체":      {"tags": ["HBM", "AI인프라", "엔비디아밸류체인"],       "theme": "AI 데이터센터 폭발적 수요"},
    "AI 생태계":   {"tags": ["클라우드", "AI서비스", "소버린AI"],           "theme": "클라우드·AI 플랫폼 기대감"},
    "모빌리티":    {"tags": ["SDV·자율주행", "ADAS", "전고체배터리", "휴머노이드"], "theme": "전장화·자율주행·배터리 통합 모빌리티"},
    "전력 인프라": {"tags": ["데이터센터전력", "HVDC", "원전·에너지전환"],  "theme": "전력망 현대화 수혜"},
    "조선":        {"tags": ["LNG선", "친환경선박", "수주잔고최대"],        "theme": "조선 슈퍼사이클 진입"},
    "방산":        {"tags": ["K방산수출", "NATO재무장", "폴란드계약"],      "theme": "글로벌 지정학 리스크 수혜"},
    "금융":        {"tags": ["고금리수혜", "밸류업", "배당확대"],           "theme": "정부 밸류업 프로그램"},
    "바이오":      {"tags": ["ADC항체약물", "비만치료제", "AI신약"],        "theme": "글로벌 바이오텍 확장"},
    "화학":        {"tags": ["정유스프레드", "태양광소재", "친환경전환"],   "theme": "화학 업황 턴어라운드 대기"},
    "경기소비재":  {"tags": ["건설수주", "내수회복", "K엔터·콘텐츠"],        "theme": "내수·소비 회복 + 건설 턴어라운드"},
}

WEIGHTS = {
    "macro": 0.12,
    "foreign": 0.22,
    "institutional": 0.17,
    "momentum": 0.18,
    "news": 0.04,
    "volume": 0.09,
    "smart": 0.03,
    "intraday": 0.15,  # 당일 실시간 등락 — 장중 로테이션 즉시 반영 (KIS와 동일성 검증된 네이버 실시간)
}

# 성장주 우호 섹터 (금리하락 시 +) vs 가치주 우호 섹터 (금리상승 시 +)
GROWTH_SECTORS = {"반도체", "AI 생태계", "모빌리티", "바이오"}
VALUE_SECTORS  = {"금융", "방산"}

# ---------------------------------------------------------------------------
# Cache (1시간 TTL, thread-safe)
# ---------------------------------------------------------------------------
_cache_lock = threading.Lock()
_cache: Optional[dict] = None
_cache_ts: float = 0.0
CACHE_TTL = 28800        # 장외: 8시간 (일별 데이터는 하루 1회 갱신이면 충분)
CACHE_TTL_MARKET = 900   # 장중: 15분 — 당일 실시간 레이어가 장중 로테이션을 따라가도록


def _is_market_hours() -> bool:
    """KRX 정규장 (평일 09:00~15:30 KST). 서버는 KST 가정."""
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    hm = now.hour * 60 + now.minute
    return 9 * 60 <= hm <= 15 * 60 + 30


def _current_ttl() -> int:
    return CACHE_TTL_MARKET if _is_market_hours() else CACHE_TTL


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


def _compute_bb(
    prices: List[float], period: int = 20, mult: float = 2.0
) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
    """볼린저 밴드 (상단, 중앙, 하단) 반환."""
    n = len(prices)
    upper:  List[Optional[float]] = [None] * n
    middle: List[Optional[float]] = [None] * n
    lower:  List[Optional[float]] = [None] * n
    for i in range(period - 1, n):
        win  = prices[i - period + 1: i + 1]
        mean = sum(win) / period
        std  = math.sqrt(sum((x - mean) ** 2 for x in win) / period)
        middle[i] = round(mean, 3)
        upper[i]  = round(mean + mult * std, 3)
        lower[i]  = round(mean - mult * std, 3)
    return upper, middle, lower


def _compute_rsi(prices: List[float], period: int = 14) -> List[float]:
    """Wilder's Smoothed RSI."""
    n = len(prices)
    result = [50.0] * n
    if n <= period:
        return result
    gains  = [max(0.0, prices[i] - prices[i - 1]) for i in range(1, n)]
    losses = [max(0.0, prices[i - 1] - prices[i]) for i in range(1, n)]
    avg_g  = sum(gains[:period])  / period
    avg_l  = sum(losses[:period]) / period

    def _val(g: float, l: float) -> float:
        return 100.0 if l < 1e-10 else round(100.0 - 100.0 / (1.0 + g / l), 1)

    result[period] = _val(avg_g, avg_l)
    for i in range(period, n - 1):
        avg_g = (avg_g * (period - 1) + gains[i])  / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
        result[i + 1] = _val(avg_g, avg_l)
    return result


# ---------------------------------------------------------------------------
# Layer 1: Macro Score
# ---------------------------------------------------------------------------
def _vkospi_series_db(n: int = 44) -> List[float]:
    """vkospi_history 테이블에서 최근 n개 종가 (과거→현재 순).

    이력은 scripts/vkospi_crawl.py(초기 2,064개 적재) + fundamentals_sync(매일 갱신)가 채운다.
    """
    try:
        import db as _db
        import models as _models
        from sqlalchemy import select as _select

        s = _db.get_session_factory()()
        try:
            rows = s.execute(
                _select(_models.VkospiHistory.close)
                .order_by(_models.VkospiHistory.trade_date.desc())
                .limit(n)
            ).scalars().all()
        finally:
            s.close()
        return [round(float(v), 2) for v in reversed(rows)]
    except Exception:
        return []


def _vkospi_quote() -> Tuple[Optional[float], float]:
    """V-KOSPI(한국 변동성지수) 현재값 + 등락률%.

    현물 VKOSPI는 야후/네이버/다음 모두 미제공, KRX 정보데이터시스템은 이 환경에서
    DNS 불가 — KRX 변동성지수 선물 연속물(VKI1!)을 TradingView 스캐너로 조회한다
    (20분 지연). 선물이므로 현물과 약간의 베이시스가 있고, 라벨에 '선물·지연' 명시.
    해석 기준: 20~30 평시, 30+ 공포 (2008년 위기 시 ~80).
    """
    try:
        import httpx as _httpx

        body = {
            "symbols": {"tickers": ["KRX:VKI1!"], "query": {"types": []}},
            "columns": ["close", "change"],
        }
        r = _httpx.post(
            "https://scanner.tradingview.com/global/scan",
            headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"},
            json=body, timeout=8.0,
        )
        rows = r.json().get("data", [])
        if rows and rows[0].get("d"):
            close = float(rows[0]["d"][0])
            chg = float(rows[0]["d"][1] or 0.0)
            if close > 0:
                return round(close, 2), round(chg, 2)
    except Exception:
        pass
    return None, 0.0


def _macro_score() -> Tuple[float, dict]:
    """
    금리·달러·VIX 방향으로 성장주 우호도 0~100 계산.
    금리↓ + 달러↓ + VIX↓ = 성장주 우호 (점수↑)
    """
    try:
        import yfinance as yf

        # 일봉 60일 (추세 계산용)
        raw_d = yf.download(
            "^TNX DX-Y.NYB ^VIX ^IXIC KRW=X CL=F ^KS11",
            period="60d", interval="1d", progress=False,
        )
        closes_d = raw_d["Close"]

        # 1시간봉 5일 (단기 추이용)
        raw_h = yf.download(
            "^TNX DX-Y.NYB ^VIX ^IXIC KRW=X CL=F",
            period="5d", interval="1h", progress=False,
        )
        closes_h = raw_h["Close"]

        def _last(s) -> Optional[float]:
            s2 = s.dropna()
            return float(s2.iloc[-1]) if len(s2) > 0 else None

        def _series(closes, key: str, n: int = 30) -> List[float]:
            try:
                s = closes[key].dropna()
                return [round(float(v), 4) for v in s.iloc[-n:].values]
            except Exception:
                return []

        def _chg(s, n: int) -> float:
            s2 = s.dropna()
            if len(s2) < n + 1:
                return 0.0
            v0, v1 = _safe(s2.iloc[-n - 1]), _safe(s2.iloc[-1])
            return round((v1 - v0) / (abs(v0) + 1e-9) * 100, 2)

        tnx    = closes_d["^TNX"].dropna()
        dxy    = closes_d["DX-Y.NYB"].dropna()
        vix    = closes_d["^VIX"].dropna()
        nasdaq = closes_d["^IXIC"].dropna()
        krw    = closes_d["KRW=X"].dropna()
        oil    = closes_d["CL=F"].dropna()

        # VKOSPI: 야후 ^VKOSPI는 폐지된 심볼(항상 빈 데이터) → KRX 변동성지수 선물(VKI1!) 사용
        # 실시간 값은 TradingView 스캐너, 일별 시계열은 DB(vkospi_history)에서 로드.
        vkospi_val, vkospi_chg = _vkospi_quote()
        vkospi_series = _vkospi_series_db(44)
        if vkospi_val is None and vkospi_series:
            # 실시간 조회 실패 시 DB 최신 종가로 폴백 (전일 대비 등락률도 DB에서 계산)
            vkospi_val = vkospi_series[-1]
            if len(vkospi_series) >= 2 and vkospi_series[-2]:
                vkospi_chg = round((vkospi_series[-1] - vkospi_series[-2]) / vkospi_series[-2] * 100, 2)

        tnx_dir = _chg(tnx, 20) / 100
        dxy_dir = _chg(dxy, 20) / 100
        vix_val = _safe(vix.iloc[-1]) if len(vix) > 0 else 20.0

        growth_score = 50.0
        growth_score -= tnx_dir * 200
        growth_score -= dxy_dir * 100
        growth_score -= max(0.0, (vix_val - 20.0) * 0.5)
        growth_score = round(max(0.0, min(100.0, growth_score)), 1)

        # 지표 점수 (0~100): 섹터 카드 스타일 표현용
        def _tnx_score(v: Optional[float]) -> float:
            """금리: 3% 이하=90, 5% 이상=10"""
            if v is None: return 50.0
            return round(max(10.0, min(90.0, 90 - (v - 3.0) * 40)), 1)

        def _dxy_score(v: Optional[float]) -> float:
            """달러: 95 이하=85, 110 이상=15"""
            if v is None: return 50.0
            return round(max(15.0, min(85.0, 85 - (v - 95) * (70 / 15))), 1)

        def _vix_score(v: float) -> float:
            """VIX: 12 이하=90, 30 이상=10"""
            return round(max(10.0, min(90.0, 90 - (v - 12) * (80 / 18))), 1)

        def _nasdaq_score(chg20: float) -> float:
            """나스닥 20d 수익률: -15%=10, +15%=90"""
            return round(max(10.0, min(90.0, 50 + chg20 * (40 / 15))), 1)

        def _krw_score(v: Optional[float]) -> float:
            """원달러: 1200 이하=85, 1500 이상=15"""
            if v is None: return 50.0
            return round(max(15.0, min(85.0, 85 - (v - 1200) * (70 / 300))), 1)

        def _oil_score(v: Optional[float]) -> float:
            """WTI: 60 이하=80, 100 이상=20"""
            if v is None: return 50.0
            return round(max(20.0, min(80.0, 80 - (v - 60) * (60 / 40))), 1)

        tnx_val   = _last(tnx)
        dxy_val   = _last(dxy)
        krw_val   = _last(krw)
        oil_val   = _last(oil)
        nas_val   = _last(nasdaq)
        vkos_val  = vkospi_val

        detail: dict = {
            # 현재값
            "tnx":          round(tnx_val, 3) if tnx_val else None,
            "dxy":          round(dxy_val, 3) if dxy_val else None,
            "vix":          round(vix_val, 2),
            "vkospi":       round(vkos_val, 2) if vkos_val else None,
            "nasdaq":       int(nas_val) if nas_val else None,
            "usKrw":        round(krw_val, 1) if krw_val else None,
            "oil":          round(oil_val, 2) if oil_val else None,
            # 점수 (0~100)
            "tnxScore":     _tnx_score(tnx_val),
            "dxyScore":     _dxy_score(dxy_val),
            "vixScore":     _vix_score(vix_val),
            "vkospiScore":  _vix_score(vkos_val) if vkos_val else 50.0,
            "nasScore":     _nasdaq_score(_chg(nasdaq, 20)),
            "krwScore":     _krw_score(krw_val),
            "oilScore":     _oil_score(oil_val),
            # 변화율
            "tnxChg1d":     _chg(tnx, 1),
            "tnxChg5d":     _chg(tnx, 5),
            "tnx20dChg":    _chg(tnx, 20),
            "dxyChg1d":     _chg(dxy, 1),
            "dxy20dChg":    _chg(dxy, 20),
            "vixChg1d":     _chg(vix, 1),
            "nasdaqChg1d":  _chg(nasdaq, 1),
            "nasdaqChg5d":  _chg(nasdaq, 5),
            "nasdaqChg20d": _chg(nasdaq, 20),
            "usKrwChg1d":   _chg(krw, 1),
            "usKrwChg5d":   _chg(krw, 5),
            "usKrwChg20d":  _chg(krw, 20),
            "oilChg1d":     _chg(oil, 1),
            "oilChg5d":     _chg(oil, 5),
            "oilChg20d":    _chg(oil, 20),
            "vkospiChg1d":  vkospi_chg,
            "growthScore":  growth_score,
            # 일봉 시계열 (최근 44일 — BB(20) 계산 시 표시 구간 25포인트 확보)
            "series1d": {
                "tnx":    _series(closes_d, "^TNX", 44),
                "dxy":    _series(closes_d, "DX-Y.NYB", 44),
                "vix":    _series(closes_d, "^VIX", 44),
                "nasdaq": _series(closes_d, "^IXIC", 44),
                "krw":    _series(closes_d, "KRW=X", 44),
                "oil":    _series(closes_d, "CL=F", 44),
                "vkospi": vkospi_series,
            },
            # 1시간봉 시계열 (최근 48시간)
            "series1h": {
                "tnx":    _series(closes_h, "^TNX", 48),
                "dxy":    _series(closes_h, "DX-Y.NYB", 48),
                "vix":    _series(closes_h, "^VIX", 48),
                "nasdaq": _series(closes_h, "^IXIC", 48),
                "krw":    _series(closes_h, "KRW=X", 48),
                "oil":    _series(closes_h, "CL=F", 48),
            },
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
            "momentum_pct": 0.0, "volume_surge_pct": 0.0, "top_stocks": [],
            "dominance": None}
        for s in SECTORS
    }
    try:
        from pykrx import stock as pstock  # type: ignore

        today = date.today()
        start = today - timedelta(days=90)
        start_str = _date_str(start)
        end_str = _date_str(today)

        raw_mom: Dict[str, float] = {}
        raw_vol: Dict[str, float] = {}
        sector_top3: Dict[str, list] = {}
        sector_all: Dict[str, list] = {}
        code_close_series: Dict[str, List[float]] = {}

        for sector, codes in SECTORS.items():
            moms, vols = [], []
            code_14d: Dict[str, float] = {}
            for code in codes:
                try:
                    df = pstock.get_market_ohlcv_by_date(start_str, end_str, code)
                    if df is None or df.empty or len(df) < 5:
                        continue
                    close = df["종가"]
                    code_close_series[code] = [float(x) for x in close.values]
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

            # 14일 수익률 정렬 — 상위 3(leadStocks) + 전 종목(stocks)
            ranked = sorted(code_14d.items(), key=lambda x: x[1], reverse=True)
            sector_top3[sector] = [
                {"code": c, "name": CODE_NAMES.get(c, c), "change14d": v}
                for c, v in ranked[:3]
            ]
            sector_all[sector] = [
                {"code": c, "name": CODE_NAMES.get(c, c), "change14d": v}
                for c, v in ranked
            ]

        mom_norm = _normalize(raw_mom)
        vol_norm = _normalize(raw_vol)

        # ── Dominance: BB(20) + RSI(14) 섹터 평균 정규화 가격 기준 ──────────────
        sector_dominance: Dict[str, Optional[dict]] = {}
        for sector, codes in SECTORS.items():
            series_list = [code_close_series[c] for c in codes if c in code_close_series]
            dom = None
            if series_list:
                min_len = min(len(s) for s in series_list)
                if min_len >= 22:
                    # 각 종목을 첫 가격=100 으로 정규화 후 평균
                    normed = [
                        [100.0 * v / s[0] for v in s[:min_len]]
                        for s in series_list
                    ]
                    avg_px = [
                        sum(row[i] for row in normed) / len(normed)
                        for i in range(min_len)
                    ]
                    bb_u, bb_m, bb_l = _compute_bb(avg_px)
                    rsi_v = _compute_rsi(avg_px)

                    valid_idx = [i for i in range(len(avg_px)) if bb_u[i] is not None]
                    last_n = valid_idx[-30:]
                    if len(last_n) >= 4:
                        p_out = [round(avg_px[i], 3) for i in last_n]
                        u_out: List[Optional[float]] = [bb_u[i] for i in last_n]
                        m_out: List[Optional[float]] = [bb_m[i] for i in last_n]
                        l_out: List[Optional[float]] = [bb_l[i] for i in last_n]
                        r_out = [round(rsi_v[i], 1) for i in last_n]
                        signals = []
                        for j, i in enumerate(last_n):
                            u_v, l_v = bb_u[i], bb_l[i]
                            if u_v is None or l_v is None:
                                continue
                            p, r = avg_px[i], rsi_v[i]
                            if p <= l_v * 1.01 and r <= 35:
                                signals.append({"idx": j, "type": "buy"})
                            elif p >= u_v * 0.99 and r >= 65:
                                signals.append({"idx": j, "type": "sell"})
                        dom = {
                            "prices":   p_out,
                            "bbUpper":  u_out,
                            "bbMiddle": m_out,
                            "bbLower":  l_out,
                            "rsi":      r_out,
                            "signals":  signals,
                        }
            sector_dominance[sector] = dom

        return {
            sector: {
                "momentum":          mom_norm.get(sector, 50.0),
                "volume":            vol_norm.get(sector, 50.0),
                "momentum_pct":      round(raw_mom.get(sector, 0.0), 2),
                "volume_surge_pct":  round(raw_vol.get(sector, 0.0), 2),
                "top_stocks":        sector_top3.get(sector, []),
                "all_stocks":        sector_all.get(sector, []),
                "dominance":         sector_dominance.get(sector),
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
    if foreign >= 55:
        return "외국인유입", 3
    return "관망", 1  # 외국인·기관 모두 매도 우위 → 관망


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------
def _intraday_scores() -> tuple[Dict[str, float], Dict[str, float], Dict[str, float]]:
    """당일 실시간 등락 레이어.

    네이버 실시간 polling API (KIS inquire_price와 39종목 전수 대조로 동일성 검증, 2026-06-10).
    KIS는 종목당 1콜(레이트리밋)이라 장중 15분 캐시에는 배치 1콜인 네이버를 사용한다.
    반환: (섹터별 점수 0~100, 섹터별 평균 등락%, 종목별 등락%)
    """
    import httpx as _httpx

    headers = {"User-Agent": "Mozilla/5.0"}
    all_codes = sorted({c for codes in SECTORS.values() for c in codes})
    code_chg: Dict[str, float] = {}
    for i in range(0, len(all_codes), 40):
        part = all_codes[i:i + 40]
        try:
            r = _httpx.get(
                "https://polling.finance.naver.com/api/realtime/domestic/stock/" + ",".join(part),
                headers=headers, timeout=8.0,
            )
            for d in r.json().get("datas", []):
                c = str(d.get("itemCode") or "")
                try:
                    code_chg[c] = float(str(d.get("fluctuationsRatio") or 0))
                except Exception:
                    continue
        except Exception:
            continue

    sector_pct: Dict[str, float] = {}
    sector_score: Dict[str, float] = {}
    for sector, codes in SECTORS.items():
        chgs = [code_chg[c] for c in codes if c in code_chg]
        avg = sum(chgs) / len(chgs) if chgs else 0.0
        sector_pct[sector] = round(avg, 2)
        # ±4% 등락을 0~100 점수로 사상 (50 = 보합)
        sector_score[sector] = round(max(0.0, min(100.0, 50.0 + avg * 12.5)), 1)
    return sector_score, sector_pct, code_chg


def compute_sector_rotation(force: bool = False) -> dict:
    """전체 계산 후 JSON 직렬화 가능한 dict 반환. 캐시: 장중 15분 / 장외 8시간."""
    global _cache, _cache_ts

    with _cache_lock:
        now = time.time()
        if not force and _cache is not None and (now - _cache_ts) < _current_ttl():
            return _cache

    import concurrent.futures

    macro_score, macro_detail = _macro_score()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        flow_future = ex.submit(_get_flow_scores)
        pv_future = ex.submit(_get_pv_scores)
        flow_scores = flow_future.result()
        pv_scores = pv_future.result()

    intraday_score, intraday_pct, code_intraday = _intraday_scores()

    sectors_out = []

    for sector in SECTORS:
        flow = flow_scores.get(sector, {})
        pv = pv_scores.get(sector, {})

        f_score = flow.get("foreign", 50.0)
        i_score = flow.get("institutional", 50.0)
        mom_score = pv.get("momentum", 50.0)
        vol_score = pv.get("volume", 50.0)
        smart = round(mom_score * 0.6 + vol_score * 0.4, 1)
        intr_score = intraday_score.get(sector, 50.0)
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
            + WEIGHTS["intraday"] * intr_score
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
                "intraday":      intr_score,
            },
            "detail": {
                "foreignBil":      flow.get("foreign_raw", 0.0),
                "institutionalBil": flow.get("institutional_raw", 0.0),
                "momentumPct":     pv.get("momentum_pct", 0.0),
                "volumeSurgePct":  pv.get("volume_surge_pct", 0.0),
                "intradayPct":     intraday_pct.get(sector, 0.0),
            },
            "codes": SECTORS[sector],
            "leadNames":      [CODE_NAMES.get(c, c) for c in SECTOR_ROLES.get(sector, {}).get("주도주", SECTORS[sector][:2])[:2]],
            "componentNames": [CODE_NAMES.get(c, c) for c in SECTOR_ROLES.get(sector, {}).get("소부장", SECTORS[sector][2:4])[:2]],
            "trends":         SECTOR_TRENDS.get(sector, {"tags": [], "theme": ""}),
            "leadStocks":     [
                {**ls, "changeToday": code_intraday.get(str(ls.get("code")), 0.0)}
                for ls in pv.get("top_stocks", [])
            ],
            "allStocks":      [
                {**ls, "changeToday": code_intraday.get(str(ls.get("code")), 0.0)}
                for ls in pv.get("all_stocks", [])
            ],
            # 헤더 스파크라인용 — 섹터 평균 정규화 가격(최근 ~30봉)
            "sparkline":      (pv.get("dominance") or {}).get("prices") or [],
            "dominance":      pv.get("dominance"),
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
