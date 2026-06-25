"""증권사식 약세·과열 탐지(적출형) 일일 스크리너 엔진.

모든 수치는 daily_prices OHLCV로 **결정론 계산**한다 (LLM 미사용).
지표는 순수 함수로 구현되어 단위 테스트가 용이하다.

분류 표준 (사용자 제공, 그대로 구현):
  1. lowBreak3m      저점하회(3개월): 종가 < 직전 60거래일 최저 (단, 252일 최저는 아님)
  2. lowBreak1y      저점하회(1년): 종가 < 직전 252거래일 최저
  3. firstLimitDown  첫 하한가(3개월): 3개월 내 당일 최초 하한가
  4. consecLimitDown 연속 하한가: 2거래일 이상 연속 하한가
  5. surge10d        단기 상승폭 과대(10일): 상위 분위
  6. indicators      보조지표 9종 (모두 '하향' 약세 신호, 전일 위/당일 아래 교차 봉만 적출)

'하향돌파'(dead-cross-down)는 전일 값이 기준선 위(또는 같음)이고 당일 값이 아래로
내려간 봉만 True. 단순 현재값 비교가 아니다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Sequence

import numpy as np
import pandas as pd

# ── 상수 ────────────────────────────────────────────────────────────────
# 한국 가격제한폭은 ±30%. 하한가 종가는 tick 라운딩으로 통상 -29.x% ~ -30%.
LIMIT_DOWN_THRESHOLD = -0.29  # 전일 종가 대비 등락률이 이 값 이하이면 하한가로 판정
MIN_BARS = 180  # 적출에 필요한 최소 일봉 수 (이하이면 보류·N/A)

LOOKBACK_3M = 60   # 3개월 ≈ 60 거래일
LOOKBACK_1Y = 252  # 1년 ≈ 252 거래일

INDICATOR_KEYS = [
    "maDead_5_20",
    "maDead_20_60",
    "maDead_60_180",
    "ichimokuTkDown",
    "macdOscDown",
    "stochSlowDown",
    "sonarDown",
    "cciZeroDown",
    "rsiSignalDown",
]


# ── 교차 판정 헬퍼 ──────────────────────────────────────────────────────
def _cross_down(a: pd.Series, b: pd.Series) -> bool:
    """a가 b를 마지막 봉에서 하향돌파했는가 (전일 a>=b, 당일 a<b)."""
    a = a.dropna()
    b = b.dropna()
    idx = a.index.intersection(b.index)
    if len(idx) < 2:
        return False
    a = a.loc[idx]
    b = b.loc[idx]
    prev_a, prev_b = a.iloc[-2], b.iloc[-2]
    cur_a, cur_b = a.iloc[-1], b.iloc[-1]
    if any(pd.isna(v) for v in (prev_a, prev_b, cur_a, cur_b)):
        return False
    return bool(prev_a >= prev_b and cur_a < cur_b)


def _cross_below_zero(s: pd.Series) -> bool:
    """s가 마지막 봉에서 0선을 하향돌파했는가 (전일 >=0, 당일 <0)."""
    s = s.dropna()
    if len(s) < 2:
        return False
    return bool(s.iloc[-2] >= 0 and s.iloc[-1] < 0)


# ── 보조지표 순수 함수 (각각 마지막 봉의 하향돌파 여부 bool 반환) ─────────
def ma_dead_cross(close: pd.Series, fast: int, slow: int) -> bool:
    """MA(fast)가 MA(slow)를 하향돌파(데드크로스)."""
    if len(close) < slow + 1:
        return False
    ma_f = close.rolling(fast).mean()
    ma_s = close.rolling(slow).mean()
    return _cross_down(ma_f, ma_s)


def ichimoku_tk_down(high: pd.Series, low: pd.Series, conv: int = 9, base: int = 26) -> bool:
    """일목균형표 전환선이 기준선을 하향돌파."""
    if len(high) < base + 1:
        return False
    tenkan = (high.rolling(conv).max() + low.rolling(conv).min()) / 2
    kijun = (high.rolling(base).max() + low.rolling(base).min()) / 2
    return _cross_down(tenkan, kijun)


def macd_osc_down(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> bool:
    """MACD 오실레이터(히스토그램)가 0선을 하향돌파."""
    if len(close) < slow + signal + 1:
        return False
    ema_f = close.ewm(span=fast, adjust=False).mean()
    ema_s = close.ewm(span=slow, adjust=False).mean()
    macd = ema_f - ema_s
    sig = macd.ewm(span=signal, adjust=False).mean()
    osc = macd - sig
    return _cross_below_zero(osc)


def stochastic_slow_down(
    high: pd.Series, low: pd.Series, close: pd.Series, n: int = 10, k: int = 5, d: int = 5
) -> bool:
    """Stochastic slow: %K가 %D를 하향돌파."""
    if len(close) < n + k + d + 1:
        return False
    ll = low.rolling(n).min()
    hh = high.rolling(n).max()
    rng = (hh - ll).replace(0, np.nan)
    fast_k = (close - ll) / rng * 100
    slow_k = fast_k.rolling(k).mean()  # slow %K
    slow_d = slow_k.rolling(d).mean()  # %D
    return _cross_down(slow_k, slow_d)


def sonar_down(close: pd.Series, mom: int = 10, sig: int = 5) -> bool:
    """Sonar(현재가 - N봉전 모멘텀)가 Signal선(모멘텀의 이평)을 하향돌파."""
    if len(close) < mom + sig + 1:
        return False
    sonar = close - close.shift(mom)
    signal = sonar.rolling(sig).mean()
    return _cross_down(sonar, signal)


def cci_zero_down(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 9) -> bool:
    """CCI(9)가 0선을 하향돌파."""
    if len(close) < n + 1:
        return False
    tp = (high + low + close) / 3
    sma = tp.rolling(n).mean()
    mad = tp.rolling(n).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    cci = (tp - sma) / (0.015 * mad.replace(0, np.nan))
    return _cross_below_zero(cci)


def rsi_signal_down(close: pd.Series, period: int = 14, sig: int = 9) -> bool:
    """RSI(14)가 Signal선(RSI의 9 이평)을 하향돌파."""
    if len(close) < period + sig + 1:
        return False
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()  # Wilder
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    signal = rsi.rolling(sig).mean()
    return _cross_down(rsi, signal)


# ── 하한가 / 저점 ──────────────────────────────────────────────────────
def daily_return(close: pd.Series) -> pd.Series:
    """전일 종가 대비 등락률."""
    return close.pct_change()


def is_limit_down(close: pd.Series, idx: int = -1) -> bool:
    """idx 봉이 하한가인가 (전일 대비 등락률 <= LIMIT_DOWN_THRESHOLD)."""
    rets = daily_return(close)
    if len(rets) < abs(idx) + 0 or pd.isna(rets.iloc[idx]):
        return False
    return bool(rets.iloc[idx] <= LIMIT_DOWN_THRESHOLD)


# ── 종목 단위 분류 ─────────────────────────────────────────────────────
@dataclass
class StockResult:
    code: str
    name: str = ""
    flags: list[str] = field(default_factory=list)        # 적출된 분류 키 목록
    indicators: list[str] = field(default_factory=list)   # 적출된 9지표 키 목록
    surge_score: float | None = None                       # 10일 상승폭 (분위 산정용)
    detail: dict = field(default_factory=dict)
    insufficient: bool = False  # 이력 부족(보류·N/A)


def classify_stock(df: pd.DataFrame, code: str, name: str = "") -> StockResult:
    """단일 종목의 OHLCV(trading_date 오름차순)로 분류를 산출.

    df columns: open, high, low, close, volume (index/컬럼 trading_date 무관, 정렬만 보장)
    """
    res = StockResult(code=code, name=name)
    if df is None or len(df) < MIN_BARS:
        res.insufficient = True
        res.detail["bars"] = 0 if df is None else len(df)
        return res

    df = df.sort_index()
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)

    cur_close = close.iloc[-1]

    # 1·2. 저점하회
    prior_low_60 = low.iloc[-(LOOKBACK_3M + 1):-1].min()
    prior_low_252 = low.iloc[-(LOOKBACK_1Y + 1):-1].min()
    below_60 = cur_close < prior_low_60
    below_252 = len(low) >= LOOKBACK_1Y + 1 and cur_close < prior_low_252
    if below_252:
        res.flags.append("lowBreak1y")
    elif below_60:
        res.flags.append("lowBreak3m")  # 1년 저점하회는 아닌 경우만

    # 3·4. 하한가
    today_ld = is_limit_down(close, -1)
    if today_ld:
        # 연속 하한가
        if is_limit_down(close, -2):
            res.flags.append("consecLimitDown")
        # 첫 하한가(3개월): 직전 60봉(오늘 제외)에 하한가가 없었던 경우
        rets = daily_return(close)
        prior_rets = rets.iloc[-(LOOKBACK_3M + 1):-1]
        prior_ld = (prior_rets <= LIMIT_DOWN_THRESHOLD).any()
        if not prior_ld:
            res.flags.append("firstLimitDown")

    # 5. 단기 상승폭 과대(10일) — score만 산출, 분위 판정은 유니버스 단계에서
    if len(close) >= 11:
        win = close.iloc[-11:]
        up_days = int((win.diff().iloc[1:] > 0).sum())
        ret_10 = float(cur_close / close.iloc[-11] - 1)
        res.surge_score = ret_10
        res.detail["surge"] = {"upDays": up_days, "ret10d": round(ret_10, 4)}

    # 6. 보조지표 9종
    checks = {
        "maDead_5_20": ma_dead_cross(close, 5, 20),
        "maDead_20_60": ma_dead_cross(close, 20, 60),
        "maDead_60_180": ma_dead_cross(close, 60, 180),
        "ichimokuTkDown": ichimoku_tk_down(high, low, 9, 26),
        "macdOscDown": macd_osc_down(close, 12, 26, 9),
        "stochSlowDown": stochastic_slow_down(high, low, close, 10, 5, 5),
        "sonarDown": sonar_down(close, 10, 5),
        "cciZeroDown": cci_zero_down(high, low, close, 9),
        "rsiSignalDown": rsi_signal_down(close, 14, 9),
    }
    res.indicators = [k for k, v in checks.items() if v]

    res.detail["close"] = round(float(cur_close), 2)
    res.detail["ret1d"] = round(float(daily_return(close).iloc[-1] or 0), 4)
    return res


# ── 유니버스 집계 ──────────────────────────────────────────────────────
def build_report(
    results: Sequence[StockResult],
    as_of: date,
    *,
    surge_top_quantile: float = 0.8,
    surge_min_updays: int = 7,
    compress_to: int | None = None,
    rank_key=None,
) -> dict:
    """종목별 StockResult 목록 → 표준 리포트 구조.

    surge10d: 유니버스 10일 수익률 상위 분위(기본 상위 20%) AND 상승일수>=7.
    compress_to: 분류별 적출 과다 시 rank_key(code->score) 상위 N개로 압축.
    """
    valid = [r for r in results if not r.insufficient]
    insufficient = [r.code for r in results if r.insufficient]

    # surge 분위 임계값
    surge_scores = [r.surge_score for r in valid if r.surge_score is not None]
    surge_cut = None
    if surge_scores:
        surge_cut = float(np.quantile(surge_scores, surge_top_quantile))

    categories: dict[str, list] = {
        "lowBreak3m": [],
        "lowBreak1y": [],
        "firstLimitDown": [],
        "consecLimitDown": [],
        "surge10d": [],
    }
    indicators: dict[str, list] = {k: [] for k in INDICATOR_KEYS}
    frequency: dict[str, int] = {}

    for r in valid:
        hits = 0
        entry = {"code": r.code, "name": r.name, **{k: v for k, v in r.detail.items() if k in ("close", "ret1d")}}
        for f in r.flags:
            if f in categories:
                categories[f].append(entry)
                hits += 1
        # surge10d 판정
        if (
            r.surge_score is not None
            and surge_cut is not None
            and r.surge_score >= surge_cut
            and r.surge_score > 0
            and r.detail.get("surge", {}).get("upDays", 0) >= surge_min_updays
        ):
            categories["surge10d"].append({**entry, **r.detail.get("surge", {})})
            hits += 1
        for ind in r.indicators:
            indicators[ind].append(entry)
            hits += 1
        if hits:
            frequency[r.code] = hits

    compressed = False
    if compress_to is not None and rank_key is not None:
        def _compress(lst):
            nonlocal compressed
            if len(lst) > compress_to:
                compressed = True
                return sorted(lst, key=lambda e: rank_key(e["code"]), reverse=True)[:compress_to]
            return lst

        for k in categories:
            categories[k] = _compress(categories[k])
        for k in indicators:
            indicators[k] = _compress(indicators[k])

    # 적출빈도 상위 (3회 이상 집중 약세 강조)
    freq_sorted = dict(sorted(frequency.items(), key=lambda kv: kv[1], reverse=True))
    concentrated = {c: n for c, n in freq_sorted.items() if n >= 3}

    return {
        "asOf": as_of.isoformat(),
        "universe": {"total": len(results), "scored": len(valid), "insufficient": insufficient},
        "categories": categories,
        "indicators": indicators,
        "frequency": freq_sorted,
        "concentrated": concentrated,
        "compressed": compressed,
        "params": {
            "limitDownThreshold": LIMIT_DOWN_THRESHOLD,
            "minBars": MIN_BARS,
            "surgeTopQuantile": surge_top_quantile,
            "surgeMinUpDays": surge_min_updays,
        },
    }
