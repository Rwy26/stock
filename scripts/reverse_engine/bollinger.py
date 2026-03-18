from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from .metrics import CompareStats, compare_series
from .series_ops import compute_ma, ewm_std_from_mid, rolling_std


@dataclass(frozen=True)
class CandidateScore:
    tag: str
    score: float
    upper: CompareStats | None
    lower: CompareStats | None


@dataclass(frozen=True)
class BollingerInferenceResult:
    best_tag: str
    upper_stats: CompareStats | None
    lower_stats: CompareStats | None
    top: list[CandidateScore]


def _score_upper_lower(
    tag: str,
    up: pd.Series,
    lo: pd.Series,
    target_upper: pd.Series | None,
    target_lower: pd.Series | None,
) -> CandidateScore | None:
    up_stats = None
    lo_stats = None
    parts: list[float] = []

    if target_upper is not None:
        up_stats = compare_series(target_upper, up)
        if up_stats.n > 0 and np.isfinite(up_stats.mae):
            parts.append(up_stats.mae)

    if target_lower is not None:
        lo_stats = compare_series(target_lower, lo)
        if lo_stats.n > 0 and np.isfinite(lo_stats.mae):
            parts.append(lo_stats.mae)

    if not parts:
        return None

    return CandidateScore(tag=tag, score=float(np.mean(parts)), upper=up_stats, lower=lo_stats)


def _compute_bands(
    mid_source: pd.Series,
    sd_source: pd.Series,
    length: int,
    k: float,
    mid_kind: Literal["identity", "sma", "ema", "rma"],
    mid_adjust: bool,
    mid_init: Literal["default", "fit"],
    mid_target: pd.Series | None,
    sd_method: Literal["rolling", "rolling_dev", "ewm"],
    sd_adjust: bool,
    ddof: int | None,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid_source_num = pd.to_numeric(mid_source, errors="coerce")

    if mid_init == "fit" and (not mid_adjust) and mid_kind in ("ema", "rma") and mid_target is not None:
        # Fit the previous EMA state so that EMA at the first finite index matches the
        # mid implied by target bands. This enables exact matching when the CSV is only
        # a slice and the platform's EMA state continues from earlier bars.
        mt = pd.to_numeric(mid_target, errors="coerce")
        finite = np.isfinite(mt) & np.isfinite(mid_source_num)
        if not bool(finite.any()):
            mid = compute_ma(mid_source_num, kind=mid_kind, length=length, adjust=mid_adjust)
        else:
            t0 = int(np.flatnonzero(finite.to_numpy())[0])
            alpha = (2.0 / (length + 1.0)) if mid_kind == "ema" else (1.0 / length)
            decay = 1.0 - alpha

            x0 = float(mid_source_num.iloc[t0])
            ema0 = float(mt.iloc[t0])
            if decay == 0:
                e_prev = ema0
            else:
                e_prev = (ema0 - alpha * x0) / decay

            out = np.full(len(mid_source_num), np.nan, dtype=float)
            ema = float(e_prev)
            arr = mid_source_num.to_numpy(dtype=float)
            for t in range(t0, len(arr)):
                ema = alpha * float(arr[t]) + decay * ema
                out[t] = ema
            mid = pd.Series(out, index=mid_source_num.index)
    else:
        mid = compute_ma(mid_source_num, kind=mid_kind, length=length, adjust=mid_adjust)

    if sd_method == "rolling":
        if ddof is None:
            ddof = 0
        sd = rolling_std(sd_source, length=length, ddof=ddof)
    elif sd_method == "rolling_dev":
        if ddof is None:
            ddof = 0
        sd = rolling_std(sd_source - mid, length=length, ddof=ddof)
    elif sd_method == "ewm":
        sd = ewm_std_from_mid(sd_source, mid=mid, length=length, adjust=sd_adjust)
    else:
        raise ValueError(f"Unknown sd_method: {sd_method}")

    upper = mid + k * sd
    lower = mid - k * sd
    return mid, upper, lower


def infer_bollinger(
    target_upper: pd.Series | None,
    target_lower: pd.Series | None,
    sources: dict[str, pd.Series],
    lengths: range = range(5, 61),
    k_range: tuple[float, float, float] = (0.5, 3.5, 0.1),
    coarse_top_n: int = 10,
    fine_top_n: int = 10,
) -> BollingerInferenceResult:
    """Infer Bollinger Band definition given named source series.

    Returns best tag + stats, and Top-N candidates for inspection.
    """

    if target_upper is None and target_lower is None:
        return BollingerInferenceResult(best_tag="(no match)", upper_stats=None, lower_stats=None, top=[])

    mid_target = None
    if target_upper is not None and target_lower is not None:
        mid_target = 0.5 * (pd.to_numeric(target_upper, errors="coerce") + pd.to_numeric(target_lower, errors="coerce"))

    mid_kinds: list[Literal["identity", "sma", "ema", "rma"]] = ["identity", "sma", "ema", "rma"]
    sd_methods: list[Literal["rolling", "rolling_dev", "ewm"]] = ["rolling", "rolling_dev", "ewm"]
    ddofs: list[int | None] = [0, 1]

    k_start, k_end, k_step = k_range
    ks = [round(float(x), 6) for x in np.arange(k_start, k_end + 1e-12, k_step)]

    scored: list[CandidateScore] = []

    for mid_name, mid_source in sources.items():
        for sd_name, sd_source in sources.items():
            for mid_kind in mid_kinds:
                mid_adjusts = [False, True] if mid_kind in ("ema", "rma") else [False]
                for sd_method in sd_methods:
                    for L in lengths:
                        for k in ks:
                            for mid_adjust in mid_adjusts:
                                adj_tag = "T" if mid_adjust else "F"
                                sd_adjusts = [False, True] if sd_method == "ewm" else [False]
                                for sd_adjust in sd_adjusts:
                                    sd_adj_tag = "T" if sd_adjust else "F"
                                    mid_inits: list[Literal["default", "fit"]] = ["default"]
                                    if (mid_target is not None) and (not mid_adjust) and (mid_kind in ("ema", "rma")):
                                        mid_inits.append("fit")

                                    for mid_init in mid_inits:
                                        init_tag = "fit" if mid_init == "fit" else "default"
                                        if sd_method in ("rolling", "rolling_dev"):
                                            for ddof in ddofs:
                                                _mid, up, lo = _compute_bands(
                                                    mid_source=mid_source,
                                                    sd_source=sd_source,
                                                    length=L,
                                                    k=k,
                                                    mid_kind=mid_kind,
                                                    mid_adjust=mid_adjust,
                                                    mid_init=mid_init,
                                                    mid_target=mid_target,
                                                    sd_method=sd_method,
                                                    sd_adjust=sd_adjust,
                                                    ddof=ddof,
                                                )
                                                tag = (
                                                    f"mid={mid_name}:{mid_kind}{L}(adj={adj_tag},init={init_tag}),"
                                                    f"sd={sd_name},{sd_method}(ddof={ddof}),k={k:g}"
                                                )
                                                cs = _score_upper_lower(tag, up, lo, target_upper, target_lower)
                                                if cs is not None:
                                                    scored.append(cs)
                                        else:
                                            _mid, up, lo = _compute_bands(
                                                mid_source=mid_source,
                                                sd_source=sd_source,
                                                length=L,
                                                k=k,
                                                mid_kind=mid_kind,
                                                mid_adjust=mid_adjust,
                                                mid_init=mid_init,
                                                mid_target=mid_target,
                                                sd_method=sd_method,
                                                sd_adjust=sd_adjust,
                                                ddof=None,
                                            )
                                            tag = (
                                                f"mid={mid_name}:{mid_kind}{L}(adj={adj_tag},init={init_tag}),"
                                                f"sd={sd_name},{sd_method}(adj={sd_adj_tag}),k={k:g}"
                                            )
                                            cs = _score_upper_lower(tag, up, lo, target_upper, target_lower)
                                            if cs is not None:
                                                scored.append(cs)

    if not scored:
        return BollingerInferenceResult(best_tag="(no match)", upper_stats=None, lower_stats=None, top=[])

    scored.sort(key=lambda x: x.score)
    coarse_top = scored[:coarse_top_n]

    # Fine search around top candidates.
    fine_scored: list[CandidateScore] = []

    def _parse(tag: str) -> tuple[str, str, int, bool, Literal["default", "fit"], str, str, bool, int | None, float]:
        left, k_part = tag.split(",k=")
        k_val = float(k_part)

        mid_part, sd_part = left.split(",sd=")
        mid_name_kind = mid_part.replace("mid=", "")
        mid_name, kind_len_adj = mid_name_kind.split(":")

        mid_init: Literal["default", "fit"] = "default"
        kind_len = kind_len_adj
        mid_adjust = False
        if "(" in kind_len_adj and ")" in kind_len_adj:
            kind_len, meta = kind_len_adj.split("(", 1)
            meta = meta.split(")", 1)[0]
            parts = [p.strip() for p in meta.split(",") if p.strip()]
            for p in parts:
                if p.startswith("adj="):
                    mid_adjust = p.split("=", 1)[1].strip().upper().startswith("T")
                elif p.startswith("init="):
                    mid_init = "fit" if p.split("=", 1)[1].strip().lower() == "fit" else "default"

        mid_kind = "sma"
        length = 20
        for kind in ("identity", "sma", "ema", "rma"):
            if kind_len.startswith(kind):
                mid_kind = kind
                length = int(kind_len[len(kind) :])
                break

        sd_adjust = False
        if ",rolling_dev(" in sd_part:
            sd_name, rest = sd_part.split(",rolling_dev(")
            sd_method = "rolling_dev"
            ddof_str = rest.split("ddof=")[1].split(")")[0]
            ddof = int(ddof_str)
        elif ",rolling(" in sd_part:
            sd_name, rest = sd_part.split(",rolling(")
            sd_method = "rolling"
            ddof_str = rest.split("ddof=")[1].split(")")[0]
            ddof = int(ddof_str)
        else:
            # ewm(adj=T|F)
            sd_name, rest = sd_part.split(",ewm", 1)
            sd_method = "ewm"
            ddof = None
            if "(adj=" in rest:
                adj_str = rest.split("(adj=")[1].split(")")[0]
                sd_adjust = adj_str.strip().upper().startswith("T")

        return mid_name, mid_kind, length, mid_adjust, mid_init, sd_name, sd_method, sd_adjust, ddof, k_val

    for cand in coarse_top[:5]:
        mid_name, mid_kind, length, mid_adjust, mid_init, sd_name, sd_method, sd_adjust, ddof, k_val = _parse(cand.tag)
        if mid_name not in sources or sd_name not in sources:
            continue

        mid_source = sources[mid_name]
        sd_source = sources[sd_name]

        length_range = range(max(2, length - 3), length + 4)
        k_fine = [round(float(x), 6) for x in np.arange(max(0.05, k_val - 0.25), k_val + 0.251, 0.01)]

        for L in length_range:
            for k in k_fine:
                if sd_method == "rolling":
                    for dd in ([ddof] if ddof is not None else [0, 1]):
                        _mid, up, lo = _compute_bands(
                            mid_source=mid_source,
                            sd_source=sd_source,
                            length=L,
                            k=k,
                            mid_kind=mid_kind,  # type: ignore[arg-type]
                            mid_adjust=mid_adjust,
                            mid_init=mid_init,
                            mid_target=mid_target,
                            sd_method=sd_method,  # type: ignore[arg-type]
                            sd_adjust=sd_adjust,
                            ddof=dd,
                        )
                        adj_tag = "T" if mid_adjust else "F"
                        init_tag = "fit" if mid_init == "fit" else "default"
                        tag = f"mid={mid_name}:{mid_kind}{L}(adj={adj_tag},init={init_tag}),sd={sd_name},{sd_method}(ddof={dd}),k={k:g}"
                        cs = _score_upper_lower(tag, up, lo, target_upper, target_lower)
                        if cs is not None:
                            fine_scored.append(cs)
                elif sd_method == "rolling_dev":
                    for dd in ([ddof] if ddof is not None else [0, 1]):
                        _mid, up, lo = _compute_bands(
                            mid_source=mid_source,
                            sd_source=sd_source,
                            length=L,
                            k=k,
                            mid_kind=mid_kind,  # type: ignore[arg-type]
                            mid_adjust=mid_adjust,
                            mid_init=mid_init,
                            mid_target=mid_target,
                            sd_method=sd_method,  # type: ignore[arg-type]
                            sd_adjust=sd_adjust,
                            ddof=dd,
                        )
                        adj_tag = "T" if mid_adjust else "F"
                        init_tag = "fit" if mid_init == "fit" else "default"
                        tag = f"mid={mid_name}:{mid_kind}{L}(adj={adj_tag},init={init_tag}),sd={sd_name},{sd_method}(ddof={dd}),k={k:g}"
                        cs = _score_upper_lower(tag, up, lo, target_upper, target_lower)
                        if cs is not None:
                            fine_scored.append(cs)
                else:
                    _mid, up, lo = _compute_bands(
                        mid_source=mid_source,
                        sd_source=sd_source,
                        length=L,
                        k=k,
                        mid_kind=mid_kind,  # type: ignore[arg-type]
                        mid_adjust=mid_adjust,
                        mid_init=mid_init,
                        mid_target=mid_target,
                        sd_method=sd_method,  # type: ignore[arg-type]
                        sd_adjust=sd_adjust,
                        ddof=None,
                    )
                    adj_tag = "T" if mid_adjust else "F"
                    sd_adj_tag = "T" if sd_adjust else "F"
                    init_tag = "fit" if mid_init == "fit" else "default"
                    tag = f"mid={mid_name}:{mid_kind}{L}(adj={adj_tag},init={init_tag}),sd={sd_name},{sd_method}(adj={sd_adj_tag}),k={k:g}"
                    cs = _score_upper_lower(tag, up, lo, target_upper, target_lower)
                    if cs is not None:
                        fine_scored.append(cs)

    if fine_scored:
        fine_scored.sort(key=lambda x: x.score)
        best = fine_scored[0]
        return BollingerInferenceResult(best_tag=best.tag, upper_stats=best.upper, lower_stats=best.lower, top=fine_scored[:fine_top_n])

    best = coarse_top[0]
    return BollingerInferenceResult(best_tag=best.tag, upper_stats=best.upper, lower_stats=best.lower, top=coarse_top)
