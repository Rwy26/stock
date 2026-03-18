r"""Verify technical-indicator columns in an OHLCV CSV by re-computing them.

This script is intentionally self-contained and read-only for the input CSV.
It recomputes common indicators (Ichimoku, RSI, RSI MA, Bollinger Bands on RSI)
using standard definitions, then compares against existing columns.

Usage (PowerShell):
    c:/stock/.venv-ai/Scripts/python.exe scripts/verify_indicators.py --csv "C:\Users\MOON\Downloads\BITMEX_BTCUSD.P, 1.csv" --out logs

Notes:
- Many exports are slices of a larger dataset; leading rows can legitimately differ
  because rolling indicators need historical lookback. This script scores matches
  only where both computed and provided values are non-null.
"""

from __future__ import annotations

import argparse
import math
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Literal

import numpy as np
import pandas as pd


REQUIRED_OHLC = ["open", "high", "low", "close"]


def _to_numeric_series(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _rolling_midpoint(high: pd.Series, low: pd.Series, period: int) -> pd.Series:
    hh = high.rolling(period, min_periods=period).max()
    ll = low.rolling(period, min_periods=period).min()
    return (hh + ll) / 2.0


def compute_ichimoku(
    df: pd.DataFrame,
    tenkan_period: int = 9,
    kijun_period: int = 26,
    senkou_b_period: int = 52,
    displacement: int = 26,
) -> dict[str, pd.Series]:
    high = df["high"]
    low = df["low"]
    close = df["close"]

    tenkan = _rolling_midpoint(high, low, tenkan_period)
    kijun = _rolling_midpoint(high, low, kijun_period)

    # Plotted forward in charting; stored as forward-shifted in many exports.
    senkou_a = ((tenkan + kijun) / 2.0).shift(displacement)
    senkou_b = _rolling_midpoint(high, low, senkou_b_period).shift(displacement)

    # Chikou is close shifted backward on the chart (i.e., current close plotted -displacement).
    # Many CSV exports store it as a forward shift so that each row contains the value plotted
    # on that bar. We compute both conventions so we can score which matches.
    chikou_back = close.shift(-displacement)
    chikou_forward = close.shift(displacement)

    return {
        "Tenkan Sen": tenkan,
        "Kijun Sen": kijun,
        "Senkou Span A": senkou_a,
        "Senkou Span B": senkou_b,
        "Chikou Span(back)": chikou_back,
        "Chikou Span(fwd)": chikou_forward,
    }


def compute_rsi_wilder(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    # Wilder's smoothing (RMA): EMA with alpha=1/length, adjust=False
    avg_gain = gain.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def compute_ma(series: pd.Series, kind: Literal["sma", "ema", "rma"], length: int) -> pd.Series:
    if kind == "sma":
        return series.rolling(length, min_periods=length).mean()
    if kind == "ema":
        return series.ewm(span=length, adjust=False, min_periods=length).mean()
    if kind == "rma":
        # Wilder's moving average (RMA): EMA with alpha=1/length
        return series.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    raise ValueError(f"Unknown MA kind: {kind}")


def compute_bollinger(series: pd.Series, length: int = 20, stdev_mult: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = series.rolling(length, min_periods=length).mean()
    sd = series.rolling(length, min_periods=length).std(ddof=0)
    upper = mid + stdev_mult * sd
    lower = mid - stdev_mult * sd
    return mid, upper, lower


def compute_bollinger_general(
    mid_source: pd.Series,
    sd_source: pd.Series,
    length: int,
    stdev_mult: float,
    mid_kind: Literal["identity", "sma", "ema", "rma"],
    sd_method: Literal["rolling", "ewm"],
    ddof: int | None,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    if mid_kind == "identity":
        mid = mid_source
    else:
        mid = compute_ma(mid_source, kind=mid_kind, length=length)

    if sd_method == "rolling":
        if ddof is None:
            ddof = 0
        sd = sd_source.rolling(length, min_periods=length).std(ddof=ddof)
    elif sd_method == "ewm":
        # EMA-based standard deviation: sqrt(EWM(mean((x-mid)^2)))
        dev = (sd_source - mid).astype(float)
        var = (dev * dev).ewm(span=length, adjust=False, min_periods=length).mean()
        sd = np.sqrt(var)
    else:
        raise ValueError(f"Unknown sd_method: {sd_method}")
    upper = mid + stdev_mult * sd
    lower = mid - stdev_mult * sd
    return mid, upper, lower


@dataclass(frozen=True)
class CandidateScore:
    tag: str
    score: float
    upper: CompareStats | None
    lower: CompareStats | None


@dataclass(frozen=True)
class CompareStats:
    n: int
    mae: float
    rmse: float
    max_abs: float
    corr: float | None


def compare_series(provided: pd.Series, computed: pd.Series) -> CompareStats:
    a = _to_numeric_series(provided)
    b = _to_numeric_series(computed)
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


def find_best_match(
    target: pd.Series,
    candidates: Iterable[tuple[str, pd.Series]],
) -> tuple[str, CompareStats]:
    best_name: str | None = None
    best_stats: CompareStats | None = None

    for name, series in candidates:
        stats = compare_series(target, series)
        if stats.n == 0:
            continue
        if best_stats is None or stats.mae < best_stats.mae:
            best_name = name
            best_stats = stats

    if best_name is None or best_stats is None:
        return "(no match)", CompareStats(n=0, mae=float("nan"), rmse=float("nan"), max_abs=float("nan"), corr=None)
    return best_name, best_stats


def find_best_combo(
    items: list[tuple[str, pd.Series, pd.Series]],
    target_upper: pd.Series | None,
    target_lower: pd.Series | None,
) -> tuple[str, CompareStats | None, CompareStats | None]:
    best_tag = "(no match)"
    best_score = float("inf")
    best_upper: CompareStats | None = None
    best_lower: CompareStats | None = None

    for tag, up, lo in items:
        up_stats = None
        lo_stats = None
        score_parts: list[float] = []
        n_parts = 0

        if target_upper is not None:
            up_stats = compare_series(target_upper, up)
            if up_stats.n > 0 and np.isfinite(up_stats.mae):
                score_parts.append(up_stats.mae)
                n_parts += 1

        if target_lower is not None:
            lo_stats = compare_series(target_lower, lo)
            if lo_stats.n > 0 and np.isfinite(lo_stats.mae):
                score_parts.append(lo_stats.mae)
                n_parts += 1

        if n_parts == 0:
            continue
        score = float(np.mean(score_parts))
        if score < best_score:
            best_score = score
            best_tag = tag
            best_upper = up_stats
            best_lower = lo_stats

    return best_tag, best_upper, best_lower


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


def infer_bollinger(
    target_upper: pd.Series | None,
    target_lower: pd.Series | None,
    sources: dict[str, pd.Series],
) -> tuple[str, CompareStats | None, CompareStats | None, list[CandidateScore]]:
    """Infer Bollinger definition via coarse-to-fine search.

    sources: named series like RSI_provided, RSI_MA_provided, etc.
    """

    if target_upper is None and target_lower is None:
        return "(no match)", None, None, []

    lengths = list(range(5, 61))
    ks = [round(float(x), 4) for x in np.arange(0.5, 3.51, 0.1)]
    mid_kinds: list[Literal["identity", "sma", "ema", "rma"]] = ["identity", "sma", "ema", "rma"]
    sd_methods: list[Literal["rolling", "ewm"]] = ["rolling", "ewm"]
    ddofs: list[int | None] = [0, 1]

    mid_names = list(sources.keys())
    sd_names = list(sources.keys())

    scored: list[CandidateScore] = []
    for mid_name in mid_names:
        for sd_name in sd_names:
            mid_source = sources[mid_name]
            sd_source = sources[sd_name]

            for mid_kind in mid_kinds:
                for sd_method in sd_methods:
                    for length in lengths:
                        for k in ks:
                            if sd_method == "rolling":
                                for ddof in ddofs:
                                    _, up, lo = compute_bollinger_general(
                                        mid_source=mid_source,
                                        sd_source=sd_source,
                                        length=length,
                                        stdev_mult=k,
                                        mid_kind=mid_kind,
                                        sd_method=sd_method,
                                        ddof=ddof,
                                    )
                                    tag = f"mid={mid_name}:{mid_kind}{length},sd={sd_name},{sd_method}(ddof={ddof}),k={k:g}"
                                    cs = _score_upper_lower(tag, up, lo, target_upper, target_lower)
                                    if cs is not None:
                                        scored.append(cs)
                            else:
                                _, up, lo = compute_bollinger_general(
                                    mid_source=mid_source,
                                    sd_source=sd_source,
                                    length=length,
                                    stdev_mult=k,
                                    mid_kind=mid_kind,
                                    sd_method=sd_method,
                                    ddof=None,
                                )
                                tag = f"mid={mid_name}:{mid_kind}{length},sd={sd_name},{sd_method},k={k:g}"
                                cs = _score_upper_lower(tag, up, lo, target_upper, target_lower)
                                if cs is not None:
                                    scored.append(cs)

    if not scored:
        return "(no match)", None, None, []

    scored.sort(key=lambda x: x.score)
    coarse_top = scored[:10]

    def _parse_tag(tag: str) -> tuple[str, str, int, str, str, int | None, float]:
        # mid=NAME:KINDLEN,sd=NAME,rolling(ddof=D),k=K
        # mid=NAME:KINDLEN,sd=NAME,ewm,k=K
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

    fine_scored: list[CandidateScore] = []
    for cand in coarse_top[:5]:
        mid_name, mid_kind, length, sd_name, sd_method, ddof, k_val = _parse_tag(cand.tag)
        mid_source = sources[mid_name]
        sd_source = sources[sd_name]

        length_range = range(max(2, length - 3), length + 4)
        k_range = [round(float(x), 4) for x in np.arange(max(0.1, k_val - 0.25), k_val + 0.251, 0.01)]

        for L in length_range:
            for k in k_range:
                if sd_method == "rolling":
                    for dd in ([ddof] if ddof is not None else [0, 1]):
                        _, up, lo = compute_bollinger_general(
                            mid_source=mid_source,
                            sd_source=sd_source,
                            length=L,
                            stdev_mult=k,
                            mid_kind=mid_kind,  # type: ignore[arg-type]
                            sd_method=sd_method,  # type: ignore[arg-type]
                            ddof=dd,
                        )
                        tag = f"mid={mid_name}:{mid_kind}{L},sd={sd_name},{sd_method}(ddof={dd}),k={k:g}"
                        cs = _score_upper_lower(tag, up, lo, target_upper, target_lower)
                        if cs is not None:
                            fine_scored.append(cs)
                else:
                    _, up, lo = compute_bollinger_general(
                        mid_source=mid_source,
                        sd_source=sd_source,
                        length=L,
                        stdev_mult=k,
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
        return best.tag, best.upper, best.lower, fine_scored[:10]

    best = coarse_top[0]
    return best.tag, best.upper, best.lower, coarse_top


def read_csv(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df.columns = [c.strip() for c in df.columns]

    for col in REQUIRED_OHLC:
        if col not in df.columns:
            raise SystemExit(f"Missing required column: {col}")
        df[col] = _to_numeric_series(df[col])

    if "time" in df.columns:
        df["time"] = _to_numeric_series(df["time"])
        # Try epoch seconds to datetime for nicer charts/reports.
        with np.errstate(all="ignore"):
            ts = pd.to_datetime(df["time"], unit="s", errors="coerce", utc=True)
        if ts.notna().any():
            df["time_dt"] = ts.dt.tz_convert(None)

    return df


def render_report(
    df: pd.DataFrame,
    ichimoku: dict[str, pd.Series],
    rsi: dict[str, pd.Series],
    bands: dict[str, pd.Series],
    best_choices: dict[str, str],
    stats: dict[str, CompareStats],
    extra: dict[str, object] | None,
    csv_path: str,
) -> str:
    lines: list[str] = []
    lines.append(f"# Indicator Verification Report")
    lines.append("")
    lines.append(f"- CSV: `{csv_path}`")
    lines.append(f"- Rows: {len(df):,}")
    if "time_dt" in df.columns:
        t0 = df["time_dt"].dropna().iloc[0]
        t1 = df["time_dt"].dropna().iloc[-1]
        lines.append(f"- Time range (UTC naive): {t0} → {t1}")
    lines.append("")

    def add_block(title: str, keys: list[str]) -> None:
        lines.append(f"## {title}")
        lines.append("")
        lines.append("| Column | Best match | N | MAE | RMSE | MaxAbs | Corr |")
        lines.append("|---|---|---:|---:|---:|---:|---:|")
        for k in keys:
            st = stats.get(k)
            choice = best_choices.get(k, "")
            if st is None:
                lines.append(f"| {k} |  | 0 |  |  |  |  |")
                continue
            corr = "" if st.corr is None else f"{st.corr:.6f}"
            mae = "" if not np.isfinite(st.mae) else f"{st.mae:.6g}"
            rmse = "" if not np.isfinite(st.rmse) else f"{st.rmse:.6g}"
            mx = "" if not np.isfinite(st.max_abs) else f"{st.max_abs:.6g}"
            lines.append(f"| {k} | {choice} | {st.n:,} | {mae} | {rmse} | {mx} | {corr} |")
        lines.append("")

    ich_keys = ["Tenkan Sen", "Kijun Sen", "Senkou Span A", "Senkou Span B", "Chikou Span"]
    rsi_keys = ["RSI", "RSI-based MA"]
    band_keys = ["Upper Bollinger Band", "Lower Bollinger Band"]

    add_block("Ichimoku", ich_keys)
    add_block("RSI", rsi_keys)
    add_block("Bollinger (on RSI)", band_keys)

    if extra is not None and "bollinger_top" in extra:
        top = extra["bollinger_top"]
        if isinstance(top, list) and top:
            lines.append("## Bollinger Top Candidates")
            lines.append("")
            lines.append("| Rank | Score(MAE avg) | Tag | Upper MAE | Lower MAE |")
            lines.append("|---:|---:|---|---:|---:|")
            for idx, item in enumerate(top[:10], start=1):
                if not isinstance(item, CandidateScore):
                    continue
                up_mae = "" if item.upper is None or not np.isfinite(item.upper.mae) else f"{item.upper.mae:.6g}"
                lo_mae = "" if item.lower is None or not np.isfinite(item.lower.mae) else f"{item.lower.mae:.6g}"
                lines.append(f"| {idx} | {item.score:.6g} | {item.tag} | {up_mae} | {lo_mae} |")
            lines.append("")

    lines.append("## Notes")
    lines.append("")
    lines.append("- Rolling indicators often disagree at the beginning of a sliced export because prior history is missing; the report only scores rows where both sides are non-null.")
    lines.append("- If MAE is near 0 and Corr is near 1, the column is consistent with the matched definition.")
    lines.append("- Columns not covered here (e.g., divergence labels, custom Buy/Sell score) need the original formula to validate.")

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="Path to CSV with OHLCV + indicator columns")
    ap.add_argument("--out", default="logs", help="Output directory for markdown/plots")
    ap.add_argument("--no-plot", action="store_true", help="Skip generating PNG plots")
    args = ap.parse_args()

    csv_path = args.csv
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = read_csv(csv_path)

    # Compute core indicators (standard) and later do a small grid-search for best fit.
    ich = compute_ichimoku(df)

    # RSI candidates (try common lengths).
    rsi_candidates: list[tuple[str, pd.Series]] = []
    for length in (7, 9, 10, 14, 21):
        rsi_candidates.append((f"RSI_Wilder_{length}", compute_rsi_wilder(df["close"], length=length)))

    # Choose best RSI match if provided.
    stats: dict[str, CompareStats] = {}
    best: dict[str, str] = {}

    if "RSI" in df.columns:
        name, st = find_best_match(df["RSI"], rsi_candidates)
        best["RSI"] = name
        stats["RSI"] = st
        chosen_rsi = dict(rsi_candidates).get(name)
    else:
        chosen_rsi = None

    # Ichimoku: Tenkan often anchors the exactness; search Kijun/Senkou params lightly.
    if "Tenkan Sen" in df.columns:
        stats["Tenkan Sen"] = compare_series(df["Tenkan Sen"], ich["Tenkan Sen"])
        best["Tenkan Sen"] = "standard(9)"

    kijun_target = df["Kijun Sen"] if "Kijun Sen" in df.columns else None
    span_a_target = df["Senkou Span A"] if "Senkou Span A" in df.columns else None
    span_b_target = df["Senkou Span B"] if "Senkou Span B" in df.columns else None

    if kijun_target is not None or span_a_target is not None or span_b_target is not None:
        best_tag = "standard(9/26/52, disp=26)"
        best_score = float("inf")
        best_series: dict[str, pd.Series] | None = None

        for kijun_period in (24, 25, 26, 27, 28):
            for senkou_b_period in (48, 52, 56):
                for disp in (24, 25, 26, 27):
                    cand = compute_ichimoku(
                        df,
                        tenkan_period=9,
                        kijun_period=kijun_period,
                        senkou_b_period=senkou_b_period,
                        displacement=disp,
                    )

                    maes: list[float] = []
                    if kijun_target is not None:
                        st = compare_series(kijun_target, cand["Kijun Sen"])
                        if st.n > 0 and np.isfinite(st.mae):
                            maes.append(st.mae)
                    if span_a_target is not None:
                        st = compare_series(span_a_target, cand["Senkou Span A"])
                        if st.n > 0 and np.isfinite(st.mae):
                            maes.append(st.mae)
                    if span_b_target is not None:
                        st = compare_series(span_b_target, cand["Senkou Span B"])
                        if st.n > 0 and np.isfinite(st.mae):
                            maes.append(st.mae)

                    if not maes:
                        continue
                    score = float(np.mean(maes))
                    if score < best_score:
                        best_score = score
                        best_tag = f"tenkan=9,kijun={kijun_period},spanB={senkou_b_period},disp={disp}"
                        best_series = cand

        if best_series is None:
            best_series = ich

        if kijun_target is not None:
            stats["Kijun Sen"] = compare_series(kijun_target, best_series["Kijun Sen"])
            best["Kijun Sen"] = best_tag
        if span_a_target is not None:
            stats["Senkou Span A"] = compare_series(span_a_target, best_series["Senkou Span A"])
            best["Senkou Span A"] = best_tag
        if span_b_target is not None:
            stats["Senkou Span B"] = compare_series(span_b_target, best_series["Senkou Span B"])
            best["Senkou Span B"] = best_tag

    # Chikou: try shifts and direction.
    if "Chikou Span" in df.columns:
        chikou_candidates: list[tuple[str, pd.Series]] = []
        for disp in range(20, 31):
            chikou_candidates.append((f"back(close shift -{disp})", df["close"].shift(-disp)))
            chikou_candidates.append((f"fwd(close shift +{disp})", df["close"].shift(disp)))
        name, st = find_best_match(df["Chikou Span"], chikou_candidates)
        best["Chikou Span"] = name
        stats["Chikou Span"] = st

    # RSI-based MA: grid search MA kinds/lengths.
    rsi_for_ma = chosen_rsi if chosen_rsi is not None else compute_rsi_wilder(df["close"], length=14)
    ma_candidates: list[tuple[str, pd.Series]] = []
    for kind in ("sma", "ema", "rma"):
        for length in range(5, 31):
            ma_candidates.append((f"{kind.upper()}_{length}", compute_ma(rsi_for_ma, kind=kind, length=length)))

    chosen_ma = None
    if "RSI-based MA" in df.columns:
        name, st = find_best_match(df["RSI-based MA"], ma_candidates)
        best["RSI-based MA"] = name
        stats["RSI-based MA"] = st
        chosen_ma = dict(ma_candidates).get(name)

    # Bollinger Bands: infer parameters more carefully (common ambiguity: ddof, EMA midline,
    # bands computed on RSI vs RSI-MA, and sd computed on RSI vs mid-source).
    upper_target = df["Upper Bollinger Band"] if "Upper Bollinger Band" in df.columns else None
    lower_target = df["Lower Bollinger Band"] if "Lower Bollinger Band" in df.columns else None

    extra: dict[str, object] = {}
    if upper_target is not None or lower_target is not None:
        sources: dict[str, pd.Series] = {}
        if "RSI" in df.columns:
            sources["RSI_provided"] = _to_numeric_series(df["RSI"])
        sources["RSI_computed"] = rsi_for_ma

        if "RSI-based MA" in df.columns:
            sources["RSI_MA_provided"] = _to_numeric_series(df["RSI-based MA"])
        if chosen_ma is not None:
            sources["RSI_MA_computed"] = chosen_ma

        best_tag, up_stats, lo_stats, top = infer_bollinger(upper_target, lower_target, sources)
        extra["bollinger_top"] = top

        if upper_target is not None and up_stats is not None:
            best["Upper Bollinger Band"] = best_tag
            stats["Upper Bollinger Band"] = up_stats
        if lower_target is not None and lo_stats is not None:
            best["Lower Bollinger Band"] = best_tag
            stats["Lower Bollinger Band"] = lo_stats

    # Plot (optional): RSI & bands overlay for a small window, to visually confirm.
    plot_path = None
    if not args.no_plot and "RSI" in df.columns:
        try:
            import matplotlib.pyplot as plt

            x = df["time_dt"] if "time_dt" in df.columns else df.index
            fig, ax = plt.subplots(figsize=(12, 5))
            ax.plot(x, _to_numeric_series(df["RSI"]), label="RSI (provided)", linewidth=1.0)
            ax.plot(x, rsi_for_ma, label="RSI (computed best)", linewidth=1.0, alpha=0.8)

            if "RSI-based MA" in df.columns:
                ax.plot(x, _to_numeric_series(df["RSI-based MA"]), label="RSI MA (provided)", linewidth=1.0)
            if chosen_ma is not None:
                ax.plot(x, chosen_ma, label="RSI MA (computed best)", linewidth=1.0, alpha=0.8)

            if "Upper Bollinger Band" in df.columns:
                ax.plot(x, _to_numeric_series(df["Upper Bollinger Band"]), label="Upper BB (provided)", linewidth=1.0)
            if "Lower Bollinger Band" in df.columns:
                ax.plot(x, _to_numeric_series(df["Lower Bollinger Band"]), label="Lower BB (provided)", linewidth=1.0)

            ax.set_title("RSI / RSI-MA / Bollinger Bands (provided vs computed)")
            ax.set_ylabel("Value")
            ax.legend(loc="best")
            ax.grid(True, alpha=0.3)

            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            plot_path = out_dir / f"indicator-verify-{ts}.png"
            fig.tight_layout()
            fig.savefig(plot_path, dpi=150)
            plt.close(fig)
        except Exception:
            plot_path = None

    # Write report.
    report = render_report(
        df=df,
        ichimoku=ich,
        rsi={},
        bands={},
        best_choices=best,
        stats=stats,
        extra=extra,
        csv_path=csv_path,
    )

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_path = out_dir / f"indicator-verify-{ts}.md"
    report_path.write_text(report, encoding="utf-8")

    print(str(report_path))
    if plot_path is not None:
        print(str(plot_path))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
