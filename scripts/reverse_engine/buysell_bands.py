from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .series_ops import rolling_std


@dataclass(frozen=True)
class BuySellBands:
    mid: pd.Series
    sd: pd.Series
    upper: pd.Series
    lower: pd.Series
    length: int
    k: float
    ddof: int
    ema_prev: float | None
    ema_start: int | None


def fit_ema_prev_from_bands(
    signal: pd.Series,
    upper: pd.Series,
    lower: pd.Series,
    *,
    length: int = 20,
) -> tuple[float, int] | None:
    """Infer the previous EMA state from observed bands.

    For adjust=False EMA recursion:
      ema_t = a * x_t + (1-a) * ema_{t-1}

    If we know x_t and want ema_t to match the band-implied mid at the first
    finite index t0, solve:
      ema_{t0-1} = (ema_{t0} - a*x_{t0}) / (1-a)

    Returns (ema_prev, t0) where t0 is an integer positional index in the
    provided series.
    """

    s = pd.to_numeric(signal, errors="coerce")
    mid_target = 0.5 * (pd.to_numeric(upper, errors="coerce") + pd.to_numeric(lower, errors="coerce"))
    finite = np.isfinite(s) & np.isfinite(mid_target)
    if not bool(finite.any()):
        return None

    t0 = int(np.flatnonzero(finite.to_numpy())[0])
    alpha = 2.0 / (length + 1.0)
    decay = 1.0 - alpha

    x0 = float(s.iloc[t0])
    ema0 = float(mid_target.iloc[t0])
    if decay == 0:
        ema_prev = ema0
    else:
        ema_prev = (ema0 - alpha * x0) / decay
    return float(ema_prev), t0


def _ema_stateful_adjust_false(
    series: pd.Series,
    *,
    length: int,
    ema_prev: float | None,
    start: int,
) -> pd.Series:
    alpha = 2.0 / (length + 1.0)
    decay = 1.0 - alpha

    arr = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    out = np.full(len(arr), np.nan, dtype=float)

    if not (0 <= start < len(arr)):
        return pd.Series(out, index=series.index)
    if not np.isfinite(arr[start]):
        return pd.Series(out, index=series.index)

    ema = float(arr[start]) if ema_prev is None else float(ema_prev)
    for t in range(start, len(arr)):
        x = float(arr[t])
        if not np.isfinite(x):
            continue
        ema = alpha * x + decay * ema
        out[t] = ema
    return pd.Series(out, index=series.index)


def compute_buysell_bands(
    signal: pd.Series,
    *,
    length: int = 20,
    k: float = 1.0,
    ddof: int = 0,
    ema_prev: float | None = None,
    ema_start: int | None = None,
    prepend_signal: pd.Series | None = None,
) -> BuySellBands:
    """Compute BuySell bands using the fixed definition.

    Fixed definition (per inference):
      mid = EMA(signal, length, adjust=False)  [stateful]
      sd  = rolling_std(signal, length, ddof)
      upper/lower = mid ± k*sd

    Notes:
    - For exact reproduction on sliced datasets you may need BOTH:
        * EMA previous state (ema_prev) and
        * enough prepend_signal values to fill the rolling window.
      If prepend_signal is omitted, sd will be NaN for the first (length-1)
      points, even if your target has finite values there.
    - ema_start is a positional index in the *signal* series (not including
      prepend_signal). When provided, the EMA recursion starts at that index.
    """

    s = pd.to_numeric(signal, errors="coerce")

    if prepend_signal is not None and len(prepend_signal) > 0:
        pre = pd.to_numeric(prepend_signal, errors="coerce").reset_index(drop=True)
        s2 = s.reset_index(drop=True)
        combined = pd.concat([pre, s2], ignore_index=True)
        offset = len(pre)
    else:
        combined = s.reset_index(drop=True)
        offset = 0

    # Choose EMA start.
    if ema_start is not None:
        start = offset + int(ema_start)
    else:
        finite = np.isfinite(combined.to_numpy(dtype=float))
        start = int(np.flatnonzero(finite)[0]) if bool(finite.any()) else 0

    mid_c = _ema_stateful_adjust_false(combined, length=length, ema_prev=ema_prev, start=start)
    sd_c = rolling_std(combined, length=length, ddof=ddof)
    upper_c = mid_c + k * sd_c
    lower_c = mid_c - k * sd_c

    mid = mid_c.iloc[offset:].set_axis(signal.index)
    sd = sd_c.iloc[offset:].set_axis(signal.index)
    upper = upper_c.iloc[offset:].set_axis(signal.index)
    lower = lower_c.iloc[offset:].set_axis(signal.index)

    return BuySellBands(
        mid=mid,
        sd=sd,
        upper=upper,
        lower=lower,
        length=length,
        k=float(k),
        ddof=int(ddof),
        ema_prev=None if ema_prev is None else float(ema_prev),
        ema_start=None if ema_start is None else int(ema_start),
    )
