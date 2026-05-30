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
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ─── 가중치 ───────────────────────────────────────────────────────────────────
# score_total = tech*3 + flow*3 + value*2 + profit*1 + growth*1  (max=100)
W_TECH   = 3
W_FLOW   = 3
W_VALUE  = 2
W_PROFIT = 1
W_GROWTH = 1

# ─── 시장 지수 티커 ────────────────────────────────────────────────────────────
KOSPI_TICKER  = "^KS11"
KOSDAQ_TICKER = "^KQ11"


# ─── 섹터 ETF 매핑 (Tier 1 모니터링용) ───────────────────────────────────────
SECTOR_ETFS: dict[str, str] = {
    "반도체":   "091160.KS",   # KODEX 반도체
    "2차전지":  "305720.KS",   # KODEX 2차전지산업
    "바이오":   "244580.KS",   # KODEX K-바이오
    "방산":     "459580.KS",   # KODEX K-방산
    "AI/로봇":  "476600.KS",   # KODEX 인공지능
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
            self.score_tech   * W_TECH +
            self.score_flow   * W_FLOW +
            self.score_value  * W_VALUE +
            self.score_profit * W_PROFIT +
            self.score_growth * W_GROWTH
        )


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


def _yf_ticker(code: str) -> str:
    """6자리 한국 종목코드 → yfinance 티커 (KS 먼저 시도)."""
    if code.isdigit() and len(code) == 6:
        return f"{code}.KS"
    return code


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
) -> tuple[int, list[ConditionResult]]:
    """
    기술적 탈출 패턴 + 수급/실적 조건 점수.
    각 조건 충족 → +2점 (최대 10점).
    4~5개 이상 충족이 추천 기준.
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

    # ── 조건 2: 볼린저 하단 3회+ 반복 후 탈출 ────────────────────────────────
    bb_upper, bb_mid, bb_lower = _bollinger(close, 20)
    bb_pct = (close - bb_lower) / (bb_upper - bb_lower).replace(0, np.nan)

    # 최근 60봉에서 하단 터치(bb_pct < 0.1) 횟수
    bb_touch_count = int((bb_pct.tail(60) < 0.1).sum())
    # 현재 중간 이상으로 회복
    current_bb_pct = float(bb_pct.iloc[-1]) if not bb_pct.dropna().empty else 0.0
    bb_breakout = bb_touch_count >= 3 and current_bb_pct >= 0.4
    conditions.append(ConditionResult(
        "bollinger_lower_bounce",
        bb_breakout,
        value=round(current_bb_pct, 3),
        note=f"60봉내 하단터치 {bb_touch_count}회, 현재 BB%={current_bb_pct:.2f}",
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

    # ── 조건 4: Bullish Divergence (RSI 또는 MACD) ───────────────────────────
    rsi   = _rsi(close, 14)
    mhist = _macd_hist(close)

    def _bullish_divergence(indicator: pd.Series, n: int = 30) -> bool:
        """
        최근 n봉에서 가격 저점이 낮아지는데 지표 저점이 높아지면 True.
        2개의 저점(valley) 기준.
        """
        price_window = close.tail(n).reset_index(drop=True)
        ind_window   = indicator.tail(n).reset_index(drop=True)
        if ind_window.dropna().empty:
            return False
        # 로컬 최솟값 인덱스 (간단: 5봉 윈도우)
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

    rsi_div  = _bullish_divergence(rsi)
    macd_div = _bullish_divergence(mhist)
    bullish_div = rsi_div or macd_div
    conditions.append(ConditionResult(
        "bullish_divergence",
        bullish_div,
        note=f"RSI 다이버전스={rsi_div}, MACD 다이버전스={macd_div}",
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

    # ── 위험 3: Bearish Divergence (RSI/MACD) at high ────────────────────────
    rsi   = _rsi(close, 14)
    mhist = _macd_hist(close)

    def _bearish_divergence(indicator: pd.Series, n: int = 20) -> bool:
        price_window = close.tail(n).reset_index(drop=True)
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

    rsi_bear  = _bearish_divergence(rsi)
    macd_bear = _bearish_divergence(mhist)
    bearish_div = rsi_bear or macd_bear
    conditions.append(ConditionResult(
        "bearish_divergence_at_high",
        bearish_div,
        note=f"RSI={rsi_bear}, MACD={macd_bear} Bearish Divergence",
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

    # OHLCV 로드
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

    # ── Tier 1: 섹터 알파 점수 ───────────────────────────────────────────────
    sector_score, sector_conds = score_sector_leadership(df, market_df, supply_demand=supply_demand)
    result.score_value = sector_score

    # ── Tier 2: 기술적 탈출 점수 ─────────────────────────────────────────────
    tech_score, tech_conds = score_breakout(df, supply_demand=supply_demand)
    result.score_tech = tech_score
    # ── 수급 점수: tech_conds 중 수급/실적 조건만 별도 환산 ──────────────────
    flow_cond = next((c for c in tech_conds if c.name == "earnings_turnaround_supply"), None)
    result.score_flow = 10 if (flow_cond and flow_cond.met) else 0

    # ── Tier 3: 급락 위험 역점수 ─────────────────────────────────────────────
    safety_score, neg_conds = score_negative_filter(df, supply_demand=supply_demand)
    result.score_growth = safety_score

    # ── 실적/밸류에이션 점수: PER·PBR 밴드 체크 ──────────────────────────────
    # supply_demand에 per, pbr 주입 시 점수화 (없으면 0)
    sd = supply_demand or {}
    per = sd.get("per", None)   # 주가수익비율
    pbr = sd.get("pbr", None)   # 주가순자산비율
    profit_score = 0
    if per is not None:
        try:
            per_f = float(per)
            # PER 5~25: 합리적 밸류에이션 (+5점)
            if 5.0 <= per_f <= 25.0:
                profit_score += 5
        except (TypeError, ValueError):
            pass
    if pbr is not None:
        try:
            pbr_f = float(pbr)
            # PBR 0.5~3.0: 적정 자산가치 (+5점)
            if 0.5 <= pbr_f <= 3.0:
                profit_score += 5
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
            sum(1 for c in tech_conds if c.met) >= 4 and
            sum(1 for c in neg_conds if c.met) == 0
        ),
    }

    return result


# ─── 배치 실행 ────────────────────────────────────────────────────────────────

def run_batch(
    stock_codes: list[str],
    *,
    scoring_date: date | None = None,
    supply_demand_map: dict[str, dict] | None = None,
    max_workers: int = 4,
) -> list[StockScoreResult]:
    """
    여러 종목 병렬 스코어링.

    stock_codes: 6자리 한국 종목코드 리스트
    supply_demand_map: {stock_code: supply_demand_dict} (없으면 기술적 조건만 계산)
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    sd_map = supply_demand_map or {}
    sd_date = scoring_date or date.today()
    results: list[StockScoreResult] = []

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
