from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from .metrics import CompareStats, compare_series, to_numeric_series
from .series_ops import compute_ma, rolling_std


@dataclass(frozen=True)
class LinearFit:
    a: float
    b: float


@dataclass(frozen=True)
class LinearFit2:
    a1: float
    a2: float
    b: float


@dataclass(frozen=True)
class Candidate:
    tag: str
    fit: LinearFit
    stats: CompareStats


@dataclass(frozen=True)
class Candidate2:
    tag: str
    fit: LinearFit2
    stats: CompareStats


@dataclass(frozen=True)
class BuySellInferenceResult:
    best: Candidate | None
    top: list[Candidate]

    best2: Candidate2 | None
    top2: list[Candidate2]


def _fit_affine(x: pd.Series, y: pd.Series) -> LinearFit | None:
    x = to_numeric_series(x)
    y = to_numeric_series(y)
    m = np.isfinite(x) & np.isfinite(y)
    n = int(m.sum())
    if n < 30:
        return None

    A = np.vstack([x[m].to_numpy(dtype=float), np.ones(n)]).T
    a, b = np.linalg.lstsq(A, y[m].to_numpy(dtype=float), rcond=None)[0]
    return LinearFit(a=float(a), b=float(b))


def _fit_affine2(x1: pd.Series, x2: pd.Series, y: pd.Series) -> LinearFit2 | None:
    x1 = to_numeric_series(x1)
    x2 = to_numeric_series(x2)
    y = to_numeric_series(y)
    m = np.isfinite(x1) & np.isfinite(x2) & np.isfinite(y)
    n = int(m.sum())
    if n < 30:
        return None

    A = np.vstack(
        [
            x1[m].to_numpy(dtype=float),
            x2[m].to_numpy(dtype=float),
            np.ones(n),
        ]
    ).T
    a1, a2, b = np.linalg.lstsq(A, y[m].to_numpy(dtype=float), rcond=None)[0]
    return LinearFit2(a1=float(a1), a2=float(a2), b=float(b))


def _apply_affine(x: pd.Series, fit: LinearFit) -> pd.Series:
    return fit.a * to_numeric_series(x) + fit.b


def _apply_affine2(x1: pd.Series, x2: pd.Series, fit: LinearFit2) -> pd.Series:
    x1 = to_numeric_series(x1)
    x2 = to_numeric_series(x2)
    return fit.a1 * x1 + fit.a2 * x2 + fit.b


def _zscore(x: pd.Series, mid: pd.Series, sd: pd.Series) -> pd.Series:
    x = to_numeric_series(x)
    mid = to_numeric_series(mid)
    sd = to_numeric_series(sd)
    with np.errstate(divide="ignore", invalid="ignore"):
        z = (x - mid) / sd
    return z


def infer_buysell_signal(
    target: pd.Series,
    sources: dict[str, pd.Series],
    ma_kinds: tuple[Literal["identity", "sma", "ema", "rma"], ...] = ("identity", "sma", "ema", "rma"),
    ma_lengths: range = range(3, 61),
    zscore_ma_kinds: tuple[Literal["sma", "ema", "rma"], ...] = ("sma", "ema", "rma"),
    zscore_lengths: range = range(5, 61),
    ddof: int = 0,
    top_n: int = 15,
    top2_n: int = 15,
    combine_top_k: int = 12,
) -> BuySellInferenceResult:
    """Infer Buy/Sell Signal as a low-complexity function of input features.

    Candidate families:
      1) y ≈ a * MA(kind,length)(base_feature) + b
      2) y ≈ a * Z(base_feature; mid=MA(kind,L), sd=STD(rolling,L,ddof)) + b
      3) y ≈ a1 * x1 + a2 * x2 + b, combining top single-feature transforms

    where base_feature is drawn from sources plus simple differences.
    """

    y = to_numeric_series(target)

    # Build base features (raw + simple diffs) from available sources.
    base_features: list[tuple[str, pd.Series]] = []
    for name, s in sources.items():
        base_features.append((name, to_numeric_series(s)))

    # Common derived features if present.
    if "RSI" in sources and "RSI-based MA" in sources:
        rsi = to_numeric_series(sources["RSI"])
        rsi_ma = to_numeric_series(sources["RSI-based MA"])
        base_features.append(("RSI_minus_MA", rsi - rsi_ma))
        base_features.append(("0.5*(RSI_minus_MA)", 0.5 * (rsi - rsi_ma)))

    if "RSI" in sources:
        rsi = to_numeric_series(sources["RSI"])
        base_features.append(("RSI_minus_50", rsi - 50.0))

    # Build a pool of transformed 1D regressors.
    regressors: list[tuple[str, pd.Series]] = []

    for base_name, base in base_features:
        for kind in ma_kinds:
            adjusts = (False, True) if kind in ("ema", "rma") else (False,)
            for adjust in adjusts:
                adj_tag = "T" if adjust else "F"
                for L in ma_lengths:
                    sm = compute_ma(base, kind=kind, length=L, adjust=adjust)
                    regressors.append((f"MA({base_name},{kind}{L}(adj={adj_tag}))", sm))

        for kind in zscore_ma_kinds:
            adjusts = (False, True) if kind in ("ema", "rma") else (False,)
            for adjust in adjusts:
                adj_tag = "T" if adjust else "F"
                for L in zscore_lengths:
                    mid = compute_ma(base, kind=kind, length=L, adjust=adjust)
                    sd = rolling_std(base, length=L, ddof=ddof)
                    regressors.append(
                        (
                            f"Z({base_name};mid={kind}{L}(adj={adj_tag}),sd=roll{L},ddof={ddof})",
                            _zscore(base, mid, sd),
                        )
                    )
                    regressors.append((f"S({base_name};sd=roll{L},ddof={ddof})", base / sd))

    candidates: list[Candidate] = []
    for reg_name, x in regressors:
        fit = _fit_affine(x, y)
        if fit is None:
            continue
        pred = _apply_affine(x, fit)
        st = compare_series(y, pred)
        if st.n < 30 or not np.isfinite(st.mae):
            continue
        tag = f"y = {fit.a:.6g}*{reg_name} + {fit.b:.6g}"
        candidates.append(Candidate(tag=tag, fit=fit, stats=st))
    if candidates:
        candidates.sort(key=lambda c: (c.stats.mae, c.stats.rmse))
        top = candidates[:top_n]
        best = top[0]
    else:
        top = []
        best = None

    # Limited 2-feature combinations from the best single-feature candidates.
    top_regs: list[tuple[str, pd.Series]] = []
    if candidates:
        # Rebuild by mapping tag -> reg name is annoying; instead select by evaluating
        # the regressor pool with the same scoring criterion as candidates.
        # We'll do a lightweight pass: pick regressors that match the best candidates' MAE.
        scored_regs: list[tuple[float, float, str, pd.Series]] = []
        for reg_name, x in regressors:
            fit = _fit_affine(x, y)
            if fit is None:
                continue
            pred = _apply_affine(x, fit)
            st = compare_series(y, pred)
            if st.n < 30 or not np.isfinite(st.mae):
                continue
            scored_regs.append((st.mae, st.rmse, reg_name, x))
        scored_regs.sort(key=lambda t: (t[0], t[1]))
        for _, _, reg_name, x in scored_regs[: max(2, combine_top_k)]:
            top_regs.append((reg_name, x))

    candidates2: list[Candidate2] = []
    for i in range(len(top_regs)):
        name1, x1 = top_regs[i]
        for j in range(i + 1, len(top_regs)):
            name2, x2 = top_regs[j]
            fit2 = _fit_affine2(x1, x2, y)
            if fit2 is None:
                continue
            pred = _apply_affine2(x1, x2, fit2)
            st = compare_series(y, pred)
            if st.n < 30 or not np.isfinite(st.mae):
                continue
            tag = f"y = {fit2.a1:.6g}*{name1} + {fit2.a2:.6g}*{name2} + {fit2.b:.6g}"
            candidates2.append(Candidate2(tag=tag, fit=fit2, stats=st))

    if candidates2:
        candidates2.sort(key=lambda c: (c.stats.mae, c.stats.rmse))
        top2 = candidates2[:top2_n]
        best2 = top2[0]
    else:
        top2 = []
        best2 = None

    return BuySellInferenceResult(best=best, top=top, best2=best2, top2=top2)
