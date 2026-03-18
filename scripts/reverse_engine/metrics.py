from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


def to_numeric_series(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


@dataclass(frozen=True)
class CompareStats:
    n: int
    mae: float
    rmse: float
    max_abs: float
    corr: float | None


def compare_series(provided: pd.Series, computed: pd.Series) -> CompareStats:
    a = to_numeric_series(provided)
    b = to_numeric_series(computed)
    mask = a.notna() & b.notna() & np.isfinite(a) & np.isfinite(b)
    n = int(mask.sum())
    if n == 0:
        return CompareStats(n=0, mae=float("nan"), rmse=float("nan"), max_abs=float("nan"), corr=None)

    diff = (a[mask] - b[mask]).astype(float)
    mae = float(diff.abs().mean())
    rmse = float(math.sqrt(float((diff * diff).mean())))
    max_abs = float(diff.abs().max())

    if n >= 3:
        corr = float(np.corrcoef(a[mask].to_numpy(), b[mask].to_numpy())[0, 1])
    else:
        corr = None

    return CompareStats(n=n, mae=mae, rmse=rmse, max_abs=max_abs, corr=corr)
