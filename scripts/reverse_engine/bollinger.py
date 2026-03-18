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
    sd_method: Literal["rolling", "ewm"],
    ddof: int | None,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = compute_ma(mid_source, kind=mid_kind, length=length)

    if sd_method == "rolling":
        if ddof is None:
            ddof = 0
        sd = rolling_std(sd_source, length=length, ddof=ddof)
    elif sd_method == "ewm":
        sd = ewm_std_from_mid(sd_source, mid=mid, length=length)
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

    mid_kinds: list[Literal["identity", "sma", "ema", "rma"]] = ["identity", "sma", "ema", "rma"]
    sd_methods: list[Literal["rolling", "ewm"]] = ["rolling", "ewm"]
    ddofs: list[int | None] = [0, 1]

    k_start, k_end, k_step = k_range
    ks = [round(float(x), 6) for x in np.arange(k_start, k_end + 1e-12, k_step)]

    scored: list[CandidateScore] = []

    for mid_name, mid_source in sources.items():
        for sd_name, sd_source in sources.items():
            for mid_kind in mid_kinds:
                for sd_method in sd_methods:
                    for L in lengths:
                        for k in ks:
                            if sd_method == "rolling":
                                for ddof in ddofs:
                                    _mid, up, lo = _compute_bands(
                                        mid_source=mid_source,
                                        sd_source=sd_source,
                                        length=L,
                                        k=k,
                                        mid_kind=mid_kind,
                                        sd_method=sd_method,
                                        ddof=ddof,
                                    )
                                    tag = f"mid={mid_name}:{mid_kind}{L},sd={sd_name},{sd_method}(ddof={ddof}),k={k:g}"
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
                                    sd_method=sd_method,
                                    ddof=None,
                                )
                                tag = f"mid={mid_name}:{mid_kind}{L},sd={sd_name},{sd_method},k={k:g}"
                                cs = _score_upper_lower(tag, up, lo, target_upper, target_lower)
                                if cs is not None:
                                    scored.append(cs)

    if not scored:
        return BollingerInferenceResult(best_tag="(no match)", upper_stats=None, lower_stats=None, top=[])

    scored.sort(key=lambda x: x.score)
    coarse_top = scored[:coarse_top_n]

    # Fine search around top candidates.
    fine_scored: list[CandidateScore] = []

    def _parse(tag: str) -> tuple[str, str, int, str, str, int | None, float]:
        left, k_part = tag.split(",k=")
        k_val = float(k_part)

        mid_part, sd_part = left.split(",sd=")
        mid_name_kind = mid_part.replace("mid=", "")
        mid_name, kind_len = mid_name_kind.split(":")

        mid_kind = "sma"
        length = 20
        for kind in ("identity", "sma", "ema", "rma"):
            if kind_len.startswith(kind):
                mid_kind = kind
                length = int(kind_len[len(kind) :])
                break

        if ",rolling(" in sd_part:
            sd_name, rest = sd_part.split(",rolling(")
            sd_method = "rolling"
            ddof_str = rest.split("ddof=")[1].split(")")[0]
            ddof = int(ddof_str)
        else:
            sd_name, _rest = sd_part.split(",ewm")
            sd_method = "ewm"
            ddof = None

        return mid_name, mid_kind, length, sd_name, sd_method, ddof, k_val

    for cand in coarse_top[:5]:
        mid_name, mid_kind, length, sd_name, sd_method, ddof, k_val = _parse(cand.tag)
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
                            sd_method=sd_method,  # type: ignore[arg-type]
                            ddof=dd,
                        )
                        tag = f"mid={mid_name}:{mid_kind}{L},sd={sd_name},{sd_method}(ddof={dd}),k={k:g}"
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
                        sd_method=sd_method,  # type: ignore[arg-type]
                        ddof=None,
                    )
                    tag = f"mid={mid_name}:{mid_kind}{L},sd={sd_name},{sd_method},k={k:g}"
                    cs = _score_upper_lower(tag, up, lo, target_upper, target_lower)
                    if cs is not None:
                        fine_scored.append(cs)

    if fine_scored:
        fine_scored.sort(key=lambda x: x.score)
        best = fine_scored[0]
        return BollingerInferenceResult(best_tag=best.tag, upper_stats=best.upper, lower_stats=best.lower, top=fine_scored[:fine_top_n])

    best = coarse_top[0]
    return BollingerInferenceResult(best_tag=best.tag, upper_stats=best.upper, lower_stats=best.lower, top=coarse_top)
