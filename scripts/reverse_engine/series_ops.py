from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd


def compute_rsi_wilder(close: pd.Series, length: int = 14) -> pd.Series:
    close = pd.to_numeric(close, errors="coerce")
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    avg_gain = gain.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def compute_ma(
    series: pd.Series,
    kind: Literal["identity", "sma", "ema", "rma"],
    length: int,
    adjust: bool = False,
) -> pd.Series:
    series = pd.to_numeric(series, errors="coerce")
    if kind == "identity":
        return series
    if kind == "sma":
        return series.rolling(length, min_periods=length).mean()
    if kind == "ema":
        return series.ewm(span=length, adjust=adjust, min_periods=length).mean()
    if kind == "rma":
        return series.ewm(alpha=1 / length, adjust=adjust, min_periods=length).mean()
    raise ValueError(f"Unknown MA kind: {kind}")


def rolling_std(series: pd.Series, length: int, ddof: int) -> pd.Series:
    series = pd.to_numeric(series, errors="coerce")
    return series.rolling(length, min_periods=length).std(ddof=ddof)


def ewm_std_from_mid(series: pd.Series, mid: pd.Series, length: int, adjust: bool = False) -> pd.Series:
    series = pd.to_numeric(series, errors="coerce")
    mid = pd.to_numeric(mid, errors="coerce")
    dev = (series - mid).astype(float)
    var = (dev * dev).ewm(span=length, adjust=adjust, min_periods=length).mean()
    return np.sqrt(var)
