"""scoring_engine.py

3-Tier 종목 추천 스코어링 엔진.

────────────────────────────────────────────────────────────────────────────
Tier 1. 주도 섹터 선정  (Sector Leadership Filter)
  → 섹터 전체가 주도 섹터 조건 5/6 이상 충족 시 +보너스
  → 섹터 peak-out 감지 시 Tier-3에서 감점

Tier 2. 바닥 탈출 / 기본 관심 종목  (Breakout Conditions)
  → 5가지 조건, 하나당 2점 (최대 10점)
  → 4가지 이상 충족 시 추천 대상

Tier 3. 급락 위험 제외  (Negative Filter)
  → 7가지 조건, 하나라도 해당 시 강한 감점 / 제외

────────────────────────────────────────────────────────────────────────────
데이터 소스
  - OHLCV + 거래량: yfinance (무료)
  - KOSPI 지수: ^KS11,  KOSDAQ: ^KQ11
  - 기관/외국인 수급: KIS API (not available → score = 0, details에 N/A 표시)
  - 영업이익 컨센서스: 외부 데이터 (not available → score = 0)
  - NLP 감성: 외부 데이터 (not available → score = 0)

score 컬럼 매핑 (IndicatorScore):
  score_tech   = Tier 2 기술적 탈출 점수  (0~10)
  score_flow   = 수급 점수                (0~10, KIS 없으면 0)
  score_value  = 섹터/시장 알파 점수      (0~10)
  score_profit = 실적/펀더멘털 점수       (0~10, 데이터 없으면 0)
  score_growth = Negative Filter 역점수   (10=위험 없음, 0=위험 다수)
  score_total  = 가중합산 (최대 100)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ─── 가중치 ───────────────────────────────────────────────────────────────────
# 우선순위: 섹터 > 수급 > 성장/도미넌스 > 수익 > 기술 > 가치 > NLP
# score_total = value(sector)*3 + flow*3 + growth*2 + profit*1 + tech*1  (max=100)
W_SECTOR = 3   # a. 섹터 주도성
               #    (구 score_value 컨럼 재활용, DB 스키마 변경 없음)
W_FLOW   = 3   # b. 수급 (외국인+기관)
W_GROWTH = 2   # c. 성장/도미넌스 (Negative Filter 역점수)
W_PROFIT = 1   # d. 수익 (EPS Growth)
W_TECH   = 1   # e. 기술적 탈출
# f. 가치 = Tier 1 알파 (score_value 안에 포함)
# g. NLP 감성 = N/A 시 0점, 연동 시 설정 예정

# ─── 시장 지수 티커 ────────────────────────────────────────────────────────────
KOSPI_TICKER  = "^KS11"
KOSDAQ_TICKER = "^KQ11"


# ─── 섹터 ETF 매핑 (Tier 1 모니터링용) ───────────────────────────────────────
SECTOR_ETFS: dict[str, str] = {
    "반도체":   "091160.KS",   # KODEX 반도체
    "2차전지":  "305720.KS",   # KODEX 2차전지산업
    "바이오":   "244580.KS",   # KODEX K-바이오
    "방산":     "459580.KS",   # KODEX K-방산
    "AI/로봇":  "445290.KS",   # KODEX 로봇액티브 (구 476600 KODEX 인공지능은 폐지/코드 재배정 → 네이버·yfinance 무데이터)
    "엔터":     "140570.KS",   # KODEX 미디어&엔터
}


# ─── 결과 데이터클래스 ────────────────────────────────────────────────────────

@dataclass
class ConditionResult:
    name: str
    met: bool
    value: float | str | None = None
    note: str = ""


@dataclass
class StockScoreResult:
    stock_code: str
    scoring_date: date
    score_tech:   int = 0   # Tier 2 기술적 (0~10)
    score_flow:   int = 0   # 수급 (0~10)
    score_value:  int = 0   # 섹터/알파 (0~10)
    score_profit: int = 0   # 실적 (0~10)
    score_growth: int = 0   # Negative역점수 (0~10)
    score_total:  int = 0   # 가중합 (0~100)
    details: dict[str, Any] = field(default_factory=dict)

    def compute_total(self) -> None:
        self.score_total = (
            self.score_value  * W_SECTOR +   # score_value 컨럼 = 섹터 주도성
            self.score_flow   * W_FLOW +
            self.score_growth * W_GROWTH +
            self.score_profit * W_PROFIT +
            self.score_tech   * W_TECH
        )


def _json_safe(obj: Any) -> Any:
    """details 를 MySQL JSON 컬럼/표준 JSON 에 안전하게 — NaN·±Infinity 제거.

    pandas/yfinance 계산값이 NaN(±inf)이면 json.dumps 가 비표준 리터럴 `NaN`/`Infinity`
    를 내보내고, MySQL JSON 컬럼이 이를 거부한다(pymysql err 3140 'Invalid JSON text').
    dict/list 를 재귀 순회해 비유한(非有限) float 을 None 으로 치환한다. numpy float 는
    파이썬 float 의 서브클래스라 math.isfinite 로 동일 처리된다.
    """
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


# ─── OHLCV 로딩 ───────────────────────────────────────────────────────────────

def _load_ohlcv(ticker: str, period: str = "1y") -> pd.DataFrame:
    """yfinance에서 OHLCV 로드. 실패 시 빈 DataFrame."""
    try:
        import yfinance as yf
        df = yf.download(ticker, period=period, interval="1d",
                         progress=False, auto_adjust=True)
        if df.empty:
            return pd.DataFrame()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0].lower() for c in df.columns]
        else:
            df = df.rename(columns=str.lower)
        df.index.name = "date"
        df = df.reset_index()
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        return df.dropna(subset=["close"])
    except Exception as exc:
        logger.warning("yfinance load failed for %s: %s", ticker, exc)
        return pd.DataFrame()


def _load_ohlcv_60m(ticker: str, period: str = "60d") -> pd.DataFrame:
    """yfinance 60분봉 OHLCV (최대 60일). RSI 다이버전스 등 단기 신호용."""
    try:
        import yfinance as yf
        df = yf.download(ticker, period=period, interval="60m",
                         progress=False, auto_adjust=True)
        if df.empty:
            return pd.DataFrame()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0].lower() for c in df.columns]
        else:
            df = df.rename(columns=str.lower)
        df.index.name = "datetime"
        df = df.reset_index()
        df["datetime"] = pd.to_datetime(df["datetime"]).dt.tz_localize(None)
        return df.dropna(subset=["close"])
    except Exception as exc:
        logger.warning("yfinance 60m load failed for %s: %s", ticker, exc)
        return pd.DataFrame()


def _yf_ticker(code: str) -> str:
    """6자리 한국 종목코드 → yfinance 티커 (KS 먼저 시도)."""
    if code.isdigit() and len(code) == 6:
        return f"{code}.KS"
    return code


def _to_series(df: pd.DataFrame, col: str) -> pd.Series:
    """yfinance OHLCV DataFrame에서 단일 가격 컬럼을 1차원 Series로 추출.

    yfinance는 단일 티커라도 버전/옵션에 따라 MultiIndex 컬럼
    ``(col, ticker)`` 또는 평면 컬럼 ``col`` 을 반환한다. 두 경우 모두
    Series로 정규화하고, 컬럼이 없으면 빈 Series를 돌려준다.
    (예전엔 미정의여서 _etf_alpha_vs_kospi가 항상 None을 반환했음.)
    """
    if df is None or len(df) == 0:
        return pd.Series(dtype="float64")
    try:
        if isinstance(df.columns, pd.MultiIndex):
            sub = df.xs(col, axis=1, level=0)
            return sub.iloc[:, 0] if getattr(sub, "ndim", 1) == 2 else sub
        return df[col]
    except (KeyError, IndexError):
        return pd.Series(dtype="float64")


# ─── 기술적 지표 헬퍼 ────────────────────────────────────────────────────────

def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    gain = d.clip(lower=0).rolling(n).mean()
    loss = (-d.clip(upper=0)).rolling(n).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _macd_hist(s: pd.Series) -> pd.Series:
    ema12 = _ema(s, 12)
    ema26 = _ema(s, 26)
    macd  = ema12 - ema26
    sig   = _ema(macd, 9)
    return macd - sig


def _bollinger(s: pd.Series, n: int = 20, k: float = 2.0):
    mid   = _sma(s, n)
    std   = s.rolling(n).std(ddof=0)
    upper = mid + k * std
    lower = mid - k * std
    return upper, mid, lower


def _pct_return(s: pd.Series, days: int) -> float:
    """days 전 대비 수익률 (%)."""
    if len(s) <= days:
        return 0.0
    base = float(s.iloc[-(days + 1)])
    if base == 0:
        return 0.0
    return round((float(s.iloc[-1]) - base) / base * 100, 2)


def _sharpe(s: pd.Series, n: int = 21) -> float:
    """최근 n일 수익률의 Sharpe (일간 기준)."""
    ret = s.pct_change().dropna().tail(n)
    if len(ret) < 5 or ret.std() == 0:
        return 0.0
    return round(float(ret.mean() / ret.std() * (252 ** 0.5)), 3)


# ─── Tier 1: 섹터 주도성 점수 ────────────────────────────────────────────────

def score_sector_leadership(
    df: pd.DataFrame,
    market_df: pd.DataFrame,
    *,
    supply_demand: dict | None = None,
) -> tuple[int, list[ConditionResult]]:
    """
    종목 df와 시장 지수 df를 받아 섹터 주도성 점수 반환.
    충족 조건 수 / 6 → 0~10점으로 환산.

    supply_demand: {
        "foreign_net_buy_days": int,   # 외국인 연속 순매수 일수
        "inst_net_buy_days":    int,   # 기관 연속 순매수 일수
        "program_buy_days":     int,   # 프로그램 매수 연속 일수
        "consensus_revised_up": bool,  # 분기 컨센서스 상향 조정 여부
        "nlp_trend_up":         bool,  # NLP 감성/노출 증가 여부
    }
    """
    conditions: list[ConditionResult] = []
    sd = supply_demand or {}

    if df.empty or market_df.empty:
        return 0, conditions

    close  = df["close"]
    mclose = market_df["close"]

    # ── a. Alpha (초과 수익률) ────────────────────────────────────────────────
    alpha_1m = _pct_return(close, 21) - _pct_return(mclose, 21)
    alpha_3m = _pct_return(close, 63) - _pct_return(mclose, 63)
    alpha_met = alpha_1m > 0 and alpha_3m > 0
    conditions.append(ConditionResult(
        "alpha_outperform",
        alpha_met,
        value=round(alpha_1m, 2),
        note=f"1M alpha={alpha_1m:.1f}%, 3M alpha={alpha_3m:.1f}%",
    ))

    # ── b. Sharpe Ratio ──────────────────────────────────────────────────────
    sharpe = _sharpe(close, 21)
    conditions.append(ConditionResult(
        "sharpe_ratio",
        sharpe >= 0.8,
        value=sharpe,
        note=f"21일 Sharpe={sharpe:.2f}",
    ))

    # ── c. 외국인+기관 7일+ 연속 순매수 ─────────────────────────────────────
    foreign_days = sd.get("foreign_net_buy_days", None)
    inst_days    = sd.get("inst_net_buy_days", None)
    if foreign_days is not None and inst_days is not None:
        combined_ok = (foreign_days >= 7) or (inst_days >= 7)
        conditions.append(ConditionResult(
            "foreign_inst_netbuy",
            combined_ok,
            note=f"외국인 {foreign_days}일, 기관 {inst_days}일 연속 순매수",
        ))
    else:
        conditions.append(ConditionResult(
            "foreign_inst_netbuy",
            False,
            note="N/A – KIS 수급 데이터 필요",
        ))

    # ── d. 프로그램 매수 3일+ ────────────────────────────────────────────────
    prog_days = sd.get("program_buy_days", None)
    if prog_days is not None:
        conditions.append(ConditionResult(
            "program_buy",
            prog_days >= 3,
            value=prog_days,
            note=f"프로그램 매수 {prog_days}일 연속",
        ))
    else:
        conditions.append(ConditionResult(
            "program_buy",
            False,
            note="N/A – KRX 프로그램 매수 데이터 필요",
        ))

    # ── e. 컨센서스 상향 ────────────────────────────────────────────────────
    consensus_up = sd.get("consensus_revised_up", None)
    if consensus_up is not None:
        conditions.append(ConditionResult(
            "consensus_revised_up",
            bool(consensus_up),
            note="분기 영업이익 컨센서스 상향 조정",
        ))
    else:
        conditions.append(ConditionResult(
            "consensus_revised_up",
            False,
            note="N/A – 증권사 컨센서스 데이터 필요",
        ))

    # ── f. NLP 감성/관심도 증가 ─────────────────────────────────────────────
    nlp_up = sd.get("nlp_trend_up", None)
    if nlp_up is not None:
        conditions.append(ConditionResult(
            "nlp_trend_up",
            bool(nlp_up),
            note="뉴스 감성 / 검색량 지속 증가",
        ))
    else:
        conditions.append(ConditionResult(
            "nlp_trend_up",
            False,
            note="N/A – 뉴스 NLP 데이터 필요",
        ))

    # ── g. 섹터 ETF 대비 알파 (supply_demand에 sector_etf_ticker 있을 때) ─────
    sector_etf_ticker = sd.get("sector_etf_ticker", None)
    if sector_etf_ticker:
        sector_df = _load_ohlcv(sector_etf_ticker, period="6mo")
        if not sector_df.empty:
            etf_alpha_1m = _pct_return(close, 21) - _pct_return(sector_df["close"], 21)
            etf_alpha_3m = _pct_return(close, 63) - _pct_return(sector_df["close"], 63)
            etf_alpha_ok = etf_alpha_1m > 0 and etf_alpha_3m > 0
            conditions.append(ConditionResult(
                "sector_etf_alpha",
                etf_alpha_ok,
                value=round(etf_alpha_1m, 2),
                note=f"섹터ETF({sector_etf_ticker}) 대비 1M={etf_alpha_1m:.1f}%, 3M={etf_alpha_3m:.1f}%",
            ))
        else:
            conditions.append(ConditionResult(
                "sector_etf_alpha", False,
                note=f"섹터ETF 데이터 로드 실패: {sector_etf_ticker}",
            ))
    else:
        conditions.append(ConditionResult(
            "sector_etf_alpha", False,
            note="N/A – supply_demand에 sector_etf_ticker 미지정",
        ))

    # N/A 조건을 분모에서 제외한 공정 스코어링
    # (데이터 없음 = 미평가, 충족 가능 조건 수로만 나눔)
    available = [c for c in conditions if "N/A" not in c.note]
    na_only   = [c for c in conditions if "N/A" in c.note]
    met_available = sum(1 for c in available if c.met)
    denom = max(len(available), 1)  # 0 나누기 방지
    score = round(met_available / denom * 10)
    return score, conditions


# ─── Tier 2: 바닥 탈출 패턴 점수 ─────────────────────────────────────────────

def score_breakout(
    df: pd.DataFrame,
    *,
    supply_demand: dict | None = None,
    df_60m: pd.DataFrame | None = None,
) -> tuple[int, list[ConditionResult]]:
    """
    기술적 탈출 패턴 + 수급/실적 조건 점수.
    각 조건 충족 → +2점 (최대 10점).
    3개 이상 충족이 추천 기준 (주도주 친화 완화).
    RSI 다이버전스: 60분봉 기준 (df_60m 제공 시), 없으면 일봉 fallback.
    """
    conditions: list[ConditionResult] = []
    sd = supply_demand or {}

    if len(df) < 110:
        return 0, [ConditionResult("data_insufficient", False, note="데이터 110봉 미만")]

    close  = df["close"]
    volume = df["volume"]

    # ── 조건 1: 5MA 골든크로스 OR 5MA 우상향 유지 ──────────────────────────────
    # 바닥 탈출: 최근 5봉 내 5MA가 100MA 아래→위 교차
    # 주도주 유지: 5MA가 100MA 위에 있고 5MA 기울기 양수 (상승 추세 지속)
    ma5   = _sma(close, 5)
    ma100 = _sma(close, 100)

    golden_cross = False
    trend_hold   = False
    if len(ma5.dropna()) >= 6 and len(ma100.dropna()) >= 5:
        # 골든크로스: 최근 5봉 내 5MA가 100MA 아래→위 돌파
        for i in range(-5, -1):
            try:
                if ma5.iloc[i - 1] < ma100.iloc[i - 1] and ma5.iloc[i] >= ma100.iloc[i]:
                    golden_cross = True
                    break
            except IndexError:
                pass
        # 주도주 추세 유지: 5MA > 100MA 이고 5MA 기울기 양수
        ma5_above  = float(ma5.iloc[-1]) > float(ma100.iloc[-1])
        ma5_rising = float(ma5.iloc[-1]) > float(ma5.iloc[-6])  # 5봉 전 대비 상승
        trend_hold = ma5_above and ma5_rising

    trend_ok = golden_cross or trend_hold
    trend_note = (
        f"골든크로스=True" if golden_cross
        else ("5MA우상향유지=True" if trend_hold else "5MA기울기하락 또는 100MA하방")
    )
    conditions.append(ConditionResult(
        "ma5_trend_ok",
        trend_ok,
        value=round(float(ma5.iloc[-1]), 2) if not ma5.dropna().empty else None,
        note=f"{trend_note} | 5MA={ma5.iloc[-1]:.0f}, 100MA={ma100.iloc[-1]:.0f}" if not ma5.dropna().empty else "",
    ))

    # ── 조건 2: 볼린저 케널 3회+ 반복 후 탈출 ───────────────────────────
    # ✔ 주도주에도 적용: BB% 현재 위치(0.5 기준) + 상승 모멘텀 확인
    bb_upper, bb_mid, bb_lower = _bollinger(close, 20)
    bb_pct = (close - bb_lower) / (bb_upper - bb_lower).replace(0, np.nan)
    current_bb_pct = float(bb_pct.iloc[-1]) if not bb_pct.dropna().empty else 0.0
    # 과매도 반등 제거 → 중단에서 상단(강세) or 반등 확인
    # 바닥 탈출형: 60봉 내 하단터치 3회이상 + 현재 BB% ≥ 0.4
    # 주도주형: BB% ≥ 0.6 (상단권 유지)
    bb_touch_count = int((bb_pct.tail(60) < 0.1).sum())
    bb_breakout = bb_touch_count >= 3 and current_bb_pct >= 0.4
    bb_leader   = current_bb_pct >= 0.6   # 주도주 강세
    bb_ok = bb_breakout or bb_leader
    if bb_leader:
        bb_note = f"BB%={current_bb_pct:.2f} (주도주 상단)"
    elif bb_breakout:
        bb_note = f"BB%={current_bb_pct:.2f} (바닥터치{bb_touch_count}회 후 탈출)"
    else:
        bb_note = f"BB%={current_bb_pct:.2f} (기준 미충족)"
    conditions.append(ConditionResult(
        "bollinger_position",
        bb_ok,
        value=round(current_bb_pct, 3),
        note=bb_note,
    ))

    # ── 조건 3: 거래량 300%+ & 주가 8%+ 급등 ────────────────────────────────
    vol_ma20 = volume.rolling(20).mean()
    vol_ratio = (volume.iloc[-1] / vol_ma20.iloc[-1]) if float(vol_ma20.iloc[-1]) > 0 else 0.0
    price_chg = _pct_return(close, 1)
    volume_surge = vol_ratio >= 3.0 and price_chg >= 8.0
    conditions.append(ConditionResult(
        "volume_surge",
        volume_surge,
        value=round(float(vol_ratio), 2),
        note=f"거래량 비율={vol_ratio:.1f}x, 주가변동={price_chg:.1f}%",
    ))

    # ── 조건 4: Bullish Divergence (RSI 60분봉 + MACD 일봉) ──────────────────
    mhist = _macd_hist(close)

    # RSI: 60분봉 우선, 없으면 일봉 fallback
    if df_60m is not None and len(df_60m) >= 30:
        rsi_src       = _rsi(df_60m["close"], 14)
        rsi_price_src = df_60m["close"]
        rsi_n         = min(120, len(df_60m))   # 60m: 120봉 ≈ 3거래일
        rsi_tf_note   = "60분봉"
    else:
        rsi_src       = _rsi(close, 14)
        rsi_price_src = close
        rsi_n         = 30
        rsi_tf_note   = "일봉(fallback)"

    def _bullish_divergence(price_series: pd.Series, indicator: pd.Series, n: int = 30) -> bool:
        """최근 n봉에서 가격 저점↓ + 지표 저점↑ = Bullish Divergence."""
        price_window = price_series.tail(n).reset_index(drop=True)
        ind_window   = indicator.tail(n).reset_index(drop=True)
        if ind_window.dropna().empty:
            return False
        valleys = []
        for i in range(2, len(price_window) - 2):
            if (price_window.iloc[i] <= price_window.iloc[i - 1] and
                    price_window.iloc[i] <= price_window.iloc[i - 2] and
                    price_window.iloc[i] <= price_window.iloc[i + 1] and
                    price_window.iloc[i] <= price_window.iloc[i + 2]):
                valleys.append(i)
        if len(valleys) < 2:
            return False
        v1, v2 = valleys[-2], valleys[-1]
        price_diverge = price_window.iloc[v2] < price_window.iloc[v1]
        ind_diverge   = ind_window.iloc[v2]  > ind_window.iloc[v1]
        return bool(price_diverge and ind_diverge)

    rsi_div  = _bullish_divergence(rsi_price_src, rsi_src, n=rsi_n)
    macd_div = _bullish_divergence(close, mhist)      # MACD는 일봉 유지
    bullish_div = rsi_div or macd_div
    conditions.append(ConditionResult(
        "bullish_divergence",
        bullish_div,
        note=f"RSI({rsi_tf_note}) 다이버전스={rsi_div}, MACD(일봉) 다이버전스={macd_div}",
    ))

    # ── 조건 5: 실적 턴어라운드 + 수급 매집 (수급 데이터 필요) ───────────────
    foreign_days = sd.get("foreign_net_buy_days", None)
    inst_days    = sd.get("inst_net_buy_days", None)
    turnaround   = sd.get("earnings_turnaround", None)

    if turnaround is not None and (foreign_days is not None or inst_days is not None):
        f_ok = (foreign_days or 0) >= 3
        i_ok = (inst_days or 0) >= 3
        fund_met = bool(turnaround) and (f_ok or i_ok)
        conditions.append(ConditionResult(
            "earnings_turnaround_supply",
            fund_met,
            note=f"실적턴어라운드={turnaround}, 외국인{foreign_days}일, 기관{inst_days}일",
        ))
    else:
        conditions.append(ConditionResult(
            "earnings_turnaround_supply",
            False,
            note="N/A – KIS 수급 + 실적 데이터 필요",
        ))

    # ── 조건 6: 52주 신고가 돌파 + 거래량 증가 ─────────────────────────────────
    # 신고가 돌파 = 현재가가 최근 252봉(약 1년) 최고가를 경신
    # 거래량 조건 = 20일 평균 대비 150%+ (강한 매수세 수반)
    high_252 = float(df["high"].tail(252).max())
    current_close = float(close.iloc[-1])
    is_52w_high = current_close >= high_252 * 0.998  # 0.2% 오차 허용
    vol_ma20 = volume.rolling(20).mean()
    vol_ratio_now = float(volume.iloc[-1] / vol_ma20.iloc[-1]) if float(vol_ma20.iloc[-1]) > 0 else 0.0
    new_high_vol = is_52w_high and vol_ratio_now >= 1.5
    conditions.append(ConditionResult(
        "new_52w_high_with_volume",
        new_high_vol,
        value=round(current_close / high_252 * 100, 1),
        note=f"52주고가대비={current_close / high_252 * 100:.1f}%, 거래량{vol_ratio_now:.1f}x",
    ))

    # 조건당 2점 (6개 조건, 최대 10점으로 클램프)
    met_count = sum(1 for c in conditions if c.met)
    score = met_count * 2
    return min(score, 10), conditions


# ─── Tier 3: 급락 위험 필터 (역점수) ─────────────────────────────────────────

def score_negative_filter(
    df: pd.DataFrame,
    *,
    supply_demand: dict | None = None,
    df_60m: pd.DataFrame | None = None,
) -> tuple[int, list[ConditionResult]]:
    """
    급락 위험 조건 탐지.
    하나라도 해당 → 강한 감점.
    반환: (risk_score 0~10, conditions)
      risk_score가 높을수록 위험 많음.
    score_growth = 10 - risk_score (10=안전, 0=매우 위험).
    """
    conditions: list[ConditionResult] = []
    sd = supply_demand or {}

    if len(df) < 35:
        return 0, [ConditionResult("data_insufficient", False, note="데이터 35봉 미만")]

    close  = df["close"]
    volume = df["volume"]
    high   = df["high"]

    # ── 위험 1: 거래량 고갈 + 3일 고점 경신 ─────────────────────────────────
    vol_ma29  = volume.rolling(29).mean()
    vol_ratio = float(volume.iloc[-1]) / float(vol_ma29.iloc[-1]) if float(vol_ma29.iloc[-1]) > 0 else 1.0
    high_breakout_3d = all(high.iloc[-i] > high.iloc[-(i + 1)] for i in range(1, 4))
    vol_dry_at_high  = vol_ratio <= 0.30 and high_breakout_3d
    conditions.append(ConditionResult(
        "volume_dry_at_new_high",
        vol_dry_at_high,
        value=round(vol_ratio, 3),
        note=f"거래량비율={vol_ratio:.2f} (29일 평균 대비), 3일 고점갱신={high_breakout_3d}",
    ))

    # ── 위험 2: 공매도/대차 급증 ────────────────────────────────────────────
    short_surge = sd.get("short_sell_surge_3d", None)
    if short_surge is not None:
        conditions.append(ConditionResult(
            "short_sell_surge",
            bool(short_surge),
            note=f"공매도+대차잔고 3일 연속 급증={short_surge}",
        ))
    else:
        conditions.append(ConditionResult(
            "short_sell_surge",
            False,
            note="N/A – KRX 공매도 데이터 필요",
        ))

    # ── 위험 3: Bearish Divergence (RSI 60분봉 + MACD 일봉) ──────────────────
    mhist = _macd_hist(close)

    # RSI: 60분봉 우선, 없으면 일봉 fallback
    if df_60m is not None and len(df_60m) >= 30:
        rsi_src_neg   = _rsi(df_60m["close"], 14)
        rsi_price_neg = df_60m["close"]
        rsi_n_neg     = min(120, len(df_60m))
        rsi_tf_neg    = "60분봉"
    else:
        rsi_src_neg   = _rsi(close, 14)
        rsi_price_neg = close
        rsi_n_neg     = 20
        rsi_tf_neg    = "일봉(fallback)"

    def _bearish_divergence(price_series: pd.Series, indicator: pd.Series, n: int = 20) -> bool:
        """최근 n봉에서 가격 고점↑ + 지표 고점↓ = Bearish Divergence."""
        price_window = price_series.tail(n).reset_index(drop=True)
        ind_window   = indicator.tail(n).reset_index(drop=True)
        if ind_window.dropna().empty:
            return False
        peaks = []
        for i in range(2, len(price_window) - 2):
            if (price_window.iloc[i] >= price_window.iloc[i - 1] and
                    price_window.iloc[i] >= price_window.iloc[i - 2] and
                    price_window.iloc[i] >= price_window.iloc[i + 1] and
                    price_window.iloc[i] >= price_window.iloc[i + 2]):
                peaks.append(i)
        if len(peaks) < 2:
            return False
        p1, p2 = peaks[-2], peaks[-1]
        price_higher = price_window.iloc[p2] > price_window.iloc[p1]
        ind_lower    = ind_window.iloc[p2]  < ind_window.iloc[p1]
        return bool(price_higher and ind_lower)

    rsi_bear  = _bearish_divergence(rsi_price_neg, rsi_src_neg, n=rsi_n_neg)
    macd_bear = _bearish_divergence(close, mhist)     # MACD는 일봉 유지
    bearish_div = rsi_bear or macd_bear
    conditions.append(ConditionResult(
        "bearish_divergence_at_high",
        bearish_div,
        note=f"RSI({rsi_tf_neg}) {rsi_bear}, MACD(일봉) {macd_bear} Bearish Divergence",
    ))

    # ── 위험 4: 긴 윗꼬리 + 장대 음봉 ───────────────────────────────────────
    # 최근 3봉 중 하나라도 긴 윗꼬리 + 장대 음봉 (고점 대비)
    open_  = df["open"]
    big_wick_bearish = False
    for i in range(-3, 0):
        body   = abs(float(close.iloc[i]) - float(open_.iloc[i]))
        h      = float(high.iloc[i])
        o      = float(open_.iloc[i])
        c_val  = float(close.iloc[i])
        upper_wick = h - max(o, c_val)
        is_bearish = c_val < o
        if body > 0 and upper_wick >= body * 1.5 and is_bearish:
            big_wick_bearish = True
    conditions.append(ConditionResult(
        "big_wick_bearish_candle",
        big_wick_bearish,
        note="최근 3봉 내 긴 윗꼬리+장대음봉 감지",
    ))

    # ── 위험 5: 영업이익률 4분기 연속 하락 ──────────────────────────────────
    op_margin_decline = sd.get("op_margin_4q_decline", None)
    if op_margin_decline is not None:
        conditions.append(ConditionResult(
            "op_margin_4q_decline",
            bool(op_margin_decline),
            note="영업이익률 4분기 연속 하락 (자산매각으로 당기순이익만 양호)",
        ))
    else:
        conditions.append(ConditionResult(
            "op_margin_4q_decline",
            False,
            note="N/A – 실적 데이터 필요",
        ))

    # ── 위험 6: 100일 이평 대비 162%+ 상승 (차익실현 위험) ──────────────────
    ma100 = _sma(close, 100)
    if not ma100.dropna().empty:
        ma100_val = float(ma100.iloc[-1])
        current   = float(close.iloc[-1])
        above_pct = (current / ma100_val - 1) * 100 if ma100_val > 0 else 0.0
    else:
        above_pct = 0.0
    overextended = above_pct >= 162.0
    conditions.append(ConditionResult(
        "overextended_162pct",
        overextended,
        value=round(above_pct, 1),
        note=f"100일 이평 대비 {above_pct:.1f}% 상승",
    ))

    # ── 위험 7: 섹터 Peak-out (외부 데이터) ─────────────────────────────────
    sector_peakout = sd.get("sector_peakout", None)
    if sector_peakout is not None:
        conditions.append(ConditionResult(
            "sector_peakout",
            bool(sector_peakout),
            note="섹터 성장 정점 + 하락 전환 신호",
        ))
    else:
        conditions.append(ConditionResult(
            "sector_peakout",
            False,
            note="N/A – 섹터 데이터 필요",
        ))

    risk_count = sum(1 for c in conditions if c.met)
    # 7개 중 몇 개 해당 → risk_score (0~10)
    risk_score = min(round(risk_count / 7 * 10), 10)
    # score_growth = 10 - risk_score (높을수록 안전)
    safety_score = 10 - risk_score
    return safety_score, conditions


# ─── 종목 스코어 통합 계산 ────────────────────────────────────────────────────

def compute_stock_score(
    stock_code: str,
    *,
    yf_ticker: str | None = None,
    scoring_date: date | None = None,
    supply_demand: dict | None = None,
) -> StockScoreResult:
    """
    단일 종목 스코어 계산.

    supply_demand 예시:
    {
        "foreign_net_buy_days": 8,
        "inst_net_buy_days": 5,
        "program_buy_days": 4,
        "consensus_revised_up": True,
        "nlp_trend_up": None,           # None = 데이터 없음
        "earnings_turnaround": True,
        "short_sell_surge_3d": False,
        "op_margin_4q_decline": False,
        "sector_peakout": False,
    }
    """
    sd_date = scoring_date or date.today()
    ticker  = yf_ticker or _yf_ticker(stock_code)

    result = StockScoreResult(stock_code=stock_code, scoring_date=sd_date)

    # ── supply_demand 복사 + 섹터 ETF 자동 주입 ───────────────────────────
    # caller의 dict를 수정하지 않도록 복사
    sd_effective: dict = dict(supply_demand) if supply_demand else {}

    # sector_etf_ticker 미지정 시 supply_demand["sector"] 문자열로 자동 매핑
    if "sector_etf_ticker" not in sd_effective:
        sector_name = sd_effective.get("sector", "")
        auto_etf = SECTOR_ETFS.get(sector_name)
        if auto_etf:
            sd_effective["sector_etf_ticker"] = auto_etf
            logger.debug("섹터 ETF 자동 주입: %s → %s", sector_name, auto_etf)

    # OHLCV 로드 (일봉)
    df = _load_ohlcv(ticker, period="2y")
    if df.empty:
        # KS 실패 시 KQ 재시도
        if ticker.endswith(".KS"):
            alt = ticker.replace(".KS", ".KQ")
            df = _load_ohlcv(alt, period="2y")

    if df.empty:
        result.details = {"error": f"yfinance 데이터 없음: {ticker}"}
        result.compute_total()
        return result

    # 시장 지수 로드 (KOSPI 기본)
    market_df = _load_ohlcv(KOSPI_TICKER, period="2y")
    if market_df.empty:
        market_df = _load_ohlcv(KOSDAQ_TICKER, period="2y")

    # ── 60분봉 로드 (RSI 다이버전스용) ─────────────────────────────────────
    df_60m = _load_ohlcv_60m(ticker)
    if df_60m.empty and ticker.endswith(".KS"):
        df_60m = _load_ohlcv_60m(ticker.replace(".KS", ".KQ"))

    # ── Tier 1: 섹터 알파 점수 ───────────────────────────────────────────
    sector_score, sector_conds = score_sector_leadership(df, market_df, supply_demand=sd_effective)
    result.score_value = sector_score

    # ── Tier 2: 기술적 탈출 점수 ─────────────────────────────────────────
    tech_score, tech_conds = score_breakout(df, supply_demand=sd_effective, df_60m=df_60m)
    result.score_tech = tech_score

    # ── 수급 점수: 연속 순매수 + 순매수량 + 프로그램 매수 반영 ──────────────
    # 우선순위: sd_effective의 KIS 수급 데이터 → earnings_turnaround_supply 조건
    fnd = int(sd_effective.get("foreign_net_buy_days") or 0)
    ind = int(sd_effective.get("inst_net_buy_days") or 0)
    fnq = int(sd_effective.get("foreign_net_qty") or 0)
    inq = int(sd_effective.get("inst_net_qty") or 0)
    pgd = int(sd_effective.get("program_buy_days") or 0)
    if fnd > 0 or ind > 0 or fnq > 0 or inq > 0 or pgd > 0:
        flow_score = 0

        combined_best = max(fnd, ind)
        if combined_best >= 7:
            flow_score += 5
        elif combined_best >= 5:
            flow_score += 4
        elif combined_best >= 3:
            flow_score += 3
        elif combined_best >= 1:
            flow_score += 2

        net_buy_qty = max(fnq, 0) + max(inq, 0)
        if net_buy_qty >= 1_500_000:
            flow_score += 4
        elif net_buy_qty >= 700_000:
            flow_score += 3
        elif net_buy_qty >= 250_000:
            flow_score += 2
        elif net_buy_qty >= 80_000:
            flow_score += 1

        if pgd >= 5:
            flow_score += 2
        elif pgd >= 3:
            flow_score += 1

        result.score_flow = min(flow_score, 10)
    else:
        # fallback: earnings_turnaround_supply 조건
        flow_cond = next((c for c in tech_conds if c.name == "earnings_turnaround_supply"), None)
        result.score_flow = 10 if (flow_cond and flow_cond.met) else 0

    # ── Tier 3: 급낙 위험 역점수 ───────────────────────────────────────
    safety_score, neg_conds = score_negative_filter(df, supply_demand=sd_effective, df_60m=df_60m)
    result.score_growth = safety_score

    # ── 실적/EPS성장 점수 ────────────────────────────────────────────────────────
    # 우선 1: sd_effective에 eps_growth 미리 주입 (배치에서 prefetch_fundamentals 활용)
    # 우선 2: yfinance info 자동 취득 (earningsGrowth)
    eps_growth: float | None = sd_effective.get("eps_growth", None)
    profit_margin: float | None = sd_effective.get("profit_margin", None)
    if eps_growth is None:
        try:
            import yfinance as yf
            info_full = yf.Ticker(ticker).info
            eg_raw = info_full.get("earningsGrowth") or info_full.get("earningsQuarterlyGrowth")
            if eg_raw is not None:
                eps_growth = float(eg_raw)
            pm_raw = info_full.get("profitMargins")
            if pm_raw is not None:
                profit_margin = float(pm_raw)
        except Exception:
            eps_growth = None

    profit_score = 0
    eps_growth_note = "N/A – eps_growth 데이터 필요"
    if eps_growth is not None:
        try:
            eg = float(eps_growth)
            if eg >= 0.50:
                profit_score = 10
                eps_growth_note = f"EPS성장 {eg*100:.0f}% (KING급)"
            elif eg >= 0.20:
                profit_score = 7
                eps_growth_note = f"EPS성장 {eg*100:.0f}% (강세)"
            elif eg >= 0.10:
                profit_score = 5
                eps_growth_note = f"EPS성장 {eg*100:.0f}% (양호)"
            elif eg >= 0.0:
                profit_score = 3
                eps_growth_note = f"EPS성장 {eg*100:.0f}% (성장 충)"
            else:
                profit_score = 0
                eps_growth_note = f"EPS성장 {eg*100:.0f}% (침체 주의)"
        except (TypeError, ValueError):
            pass
    result.score_profit = profit_score

    # ── 총점 계산 ─────────────────────────────────────────────────────────────
    result.compute_total()

    # ── 세부 내역 저장 ────────────────────────────────────────────────────────
    def _cond_dict(c: ConditionResult) -> dict:
        v = c.value
        if hasattr(v, "item"):   # numpy scalar → Python native
            v = v.item()
        return {
            "met": bool(c.met),
            "value": v,
            "note": c.note,
        }

    result.details = {
        "ticker": ticker,
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "data_rows": len(df),
        "tier1_sector": {c.name: _cond_dict(c) for c in sector_conds},
        "tier2_breakout": {c.name: _cond_dict(c) for c in tech_conds},
        "tier3_negative": {c.name: _cond_dict(c) for c in neg_conds},
        "tier2_met_count": sum(1 for c in tech_conds if c.met),
        "tier3_risk_count": sum(1 for c in neg_conds if c.met),
        "recommendation_eligible": (
            sum(1 for c in tech_conds if c.met) >= 3 and
            sum(1 for c in neg_conds if c.met) <= 1
        ),
        "eps_growth_note": eps_growth_note,
        "eps_growth_value": eps_growth,
        "profit_margin": profit_margin,
        "60m_rows": len(df_60m) if df_60m is not None else 0,
        "sector_etf_auto": sd_effective.get("sector_etf_ticker"),
        "supply_demand_used": {
            "foreign_net_buy_days": sd_effective.get("foreign_net_buy_days"),
            "inst_net_buy_days":    sd_effective.get("inst_net_buy_days"),
            "foreign_net_qty":       sd_effective.get("foreign_net_qty"),
            "inst_net_qty":          sd_effective.get("inst_net_qty"),
            "program_buy_days":     sd_effective.get("program_buy_days"),
        },
    }

    # NaN/Infinity 가 섞이면 MySQL JSON 저장이 거부되므로(err 3140) 저장 전 정규화.
    result.details = _json_safe(result.details)
    return result


# ─── 펜더멘털 일괄 조회 ──────────────────────────────────────────────────────────────────────

def fetch_fundamentals_batch(
    stock_codes: list[str],
    *,
    max_workers: int = 6,
) -> dict[str, dict]:
    """
    yfinance .info에서 EPS 성장률 · 순이익률 · PER · PBR 일괄 추출.

    run_batch() 실행 전 항상 선행 호출하는 것이 권장.
    반환 형식::

        {
          "005930": {
            "eps_growth":    0.42,   # earningsGrowth (YoY)
            "profit_margin": 0.18,   # profitMargins (순이익률)
            "trailing_per":  12.3,   # trailingPE
            "pbr":            1.4,   # priceToBook
          },
          ...
        }

    Google Finance 연동 검토:
        yfinance는 한국 종목 earningsGrowth가 None인 경우가 많으므로
        추후 requests-html 또는 google-finance-api 툱 사용 예정.
        현재는 yfinance 시도 후 None 유지 (배치에서 sd_map으로 직접 주입 가능).
    """
    from concurrent.futures import ThreadPoolExecutor

    def _fetch_one(code: str) -> tuple[str, dict]:
        t = _yf_ticker(code)
        out: dict = {}
        try:
            import yfinance as yf
            info = yf.Ticker(t).info
            eg = info.get("earningsGrowth") or info.get("earningsQuarterlyGrowth")
            if eg is not None:
                out["eps_growth"] = float(eg)
            pm = info.get("profitMargins")
            if pm is not None:
                out["profit_margin"] = float(pm)
            per = info.get("trailingPE")
            if per is not None:
                out["trailing_per"] = float(per)
            pbr = info.get("priceToBook")
            if pbr is not None:
                out["pbr"] = float(pbr)
        except Exception as exc:
            logger.debug("fundamentals fetch failed for %s: %s", code, exc)
        return code, out

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        results = dict(pool.map(_fetch_one, stock_codes))
    logger.info("fetch_fundamentals_batch: %d종목 완료, 유효 %d건",
                len(results), sum(1 for v in results.values() if v))
    return results


# ─── 배치 실행 ──────────────────────────────────────────────────────────────────────────

def run_batch(
    stock_codes: list[str],
    *,
    scoring_date: date | None = None,
    supply_demand_map: dict[str, dict] | None = None,
    max_workers: int = 4,
    prefetch_fundamentals: bool = True,
) -> list[StockScoreResult]:
    """
    여러 종목 병렬 스코어링.

    stock_codes: 6자리 한국 종목코드 리스트
    supply_demand_map: {stock_code: supply_demand_dict} (없으면 기술적 조건만 계산)
    prefetch_fundamentals: True이면 실행 전 yfinance info로 EPS/순이익률 추출
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # 호출자 dict 불변을 위해 미리 deep copy
    sd_map: dict[str, dict] = {k: dict(v) for k, v in (supply_demand_map or {}).items()}
    sd_date = scoring_date or date.today()
    results: list[StockScoreResult] = []

    # ── EPS/순이익률 선행 배치 조회 ────────────────────────────────────────
    if prefetch_fundamentals:
        logger.info("펜더멘털 일괄 조회 중 (%d 종목)...", len(stock_codes))
        try:
            fundamentals = fetch_fundamentals_batch(stock_codes, max_workers=max_workers)
            for code, fund in fundamentals.items():
                if code not in sd_map:
                    sd_map[code] = {}
                for k, v in fund.items():
                    if k not in sd_map[code]:   # 기존 수동 주입값 우선
                        sd_map[code][k] = v
        except Exception as exc:
            logger.warning("펜더멘털 일괄 조회 실패 (데이터 없이 계속): %s", exc)

    def _score_one(code: str) -> StockScoreResult:
        try:
            return compute_stock_score(
                code,
                scoring_date=sd_date,
                supply_demand=sd_map.get(code),
            )
        except Exception as exc:
            logger.error("scoring failed for %s: %s", code, exc)
            r = StockScoreResult(stock_code=code, scoring_date=sd_date)
            r.details = {"error": str(exc)}
            return r

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_score_one, code): code for code in stock_codes}
        for fut in as_completed(futures):
            results.append(fut.result())

    results.sort(key=lambda r: r.score_total, reverse=True)
    return results


# ─── KING 섹터 순환 분석 ──────────────────────────────────────────────────────

#: 섹터 ETF 매핑 (scoring_engine 내 독립 사용 가능)
SECTOR_ETF_MAP: dict[str, str] = {
    "반도체":    "091160.KS",
    "2차전지":   "305720.KS",
    "바이오":    "244580.KS",
    "방산":      "459580.KS",
    "AI/로봇":   "445290.KS",   # KODEX 로봇액티브 (구 476600 KODEX 인공지능 폐지/재배정 교체)
    "엔터":      "140570.KS",
}


def _kr_close_series(ticker: str, period_days: int) -> pd.Series:
    """KR 일별 종가 Series. FinanceDataReader 우선(무인증·KRX/네이버 기반), 실패 시 yfinance 폴백.

    yfinance 의 KOSPI 지수(^KS11)가 Yahoo 차단/결측으로 last=NaN 을 반환해 '기준선'이 깨지면
    모든 섹터 알파가 None 이 되는 문제를 회피한다. FDR Close 는 yfinance ETF 종가와 실측 일치
    (교차검증 완료: 091160=171440, KS11=8471.02). ticker 예 '091160.KS'|'^KS11' →
    FDR 심볼('091160'|'KS11')로 정규화.
    """
    need = max(int(period_days), 21) + 10  # 필요한 거래일 + 여유
    # 1) FinanceDataReader (KRX/네이버 기반, 무인증)
    try:
        import datetime as _dt

        import FinanceDataReader as fdr

        fdr_sym = ticker.replace(".KS", "").replace(".KQ", "").lstrip("^")
        start = (_dt.date.today() - _dt.timedelta(days=int(need * 1.7) + 20)).strftime("%Y-%m-%d")
        df = fdr.DataReader(fdr_sym, start)
        if df is not None and not df.empty and "Close" in df.columns:
            s = df["Close"].dropna()
            if len(s) >= 5:
                return s
    except Exception:  # noqa: BLE001
        pass
    # 2) yfinance 폴백 (Yahoo 가 회복됐을 때만 의미)
    try:
        import yfinance as yf

        yf_period = "3mo" if period_days <= 63 else "6mo"
        df = yf.download(ticker, period=yf_period, interval="1d", progress=False, auto_adjust=True)
        return _to_series(df, "Close").dropna()
    except Exception:  # noqa: BLE001
        return pd.Series(dtype="float64")


def _etf_alpha_vs_kospi(etf_ticker: str, period_days: int = 21) -> float | None:
    """ETF의 KOSPI 대비 초과수익률 계산 (기간: period_days 거래일).

    데이터는 _kr_close_series(FinanceDataReader 우선·yfinance 폴백)로 가져온다 —
    Yahoo 차단/^KS11 NaN 회피. (구버전은 yfinance 직접 호출로 차단 시 전부 None)
    """
    try:
        etf_close = _kr_close_series(etf_ticker, period_days)
        mkt_close = _kr_close_series(KOSPI_TICKER, period_days)
        if len(etf_close) < 5 or len(mkt_close) < 5:
            return None
        n = min(period_days, len(etf_close), len(mkt_close))
        etf_ret = float(etf_close.iloc[-1] / etf_close.iloc[-n] - 1)
        mkt_ret = float(mkt_close.iloc[-1] / mkt_close.iloc[-n] - 1)
        return round(etf_ret - mkt_ret, 4)
    except Exception:  # noqa: BLE001
        return None


def compute_king_sectors(top_n: int = 2) -> list[dict]:
    """섹터 ETF별 KOSPI 초과수익률 계산 → 상위 top_n 섹터 반환.

    반환값 예시::

        [
          {
            "sector": "반도체",
            "etf_ticker": "091160.KS",
            "alpha_1m": 0.082,
            "alpha_3m": 0.031,
            "rank": 1,
          },
          ...
        ]
    """
    from concurrent.futures import ThreadPoolExecutor

    def _fetch(item: tuple[str, str]) -> dict:
        name, ticker = item
        a1m = _etf_alpha_vs_kospi(ticker, period_days=21)
        a3m = _etf_alpha_vs_kospi(ticker, period_days=63)
        return {
            "sector": name,
            "etf_ticker": ticker,
            "alpha_1m": a1m,
            "alpha_3m": a3m,
        }

    with ThreadPoolExecutor(max_workers=len(SECTOR_ETF_MAP)) as pool:
        rows = list(pool.map(_fetch, SECTOR_ETF_MAP.items()))

    # 1M 알파 기준 정렬 (N/A는 최하위)
    rows.sort(key=lambda r: r["alpha_1m"] if r["alpha_1m"] is not None else -99)
    rows.reverse()

    for i, row in enumerate(rows):
        row["rank"] = i + 1

    return rows[:top_n] if top_n > 0 else rows
