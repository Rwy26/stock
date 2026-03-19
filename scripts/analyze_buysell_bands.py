r"""Analyze whether BuySell Upper/Lower Band were computed from a higher-precision internal signal.

This script:
  1) Computes mid/sd implied by the exported bands:
       mid_obs = (upper + lower)/2
       sd_obs  = (upper - lower)/2
  2) Compares those to candidate computations from the exported signal.
  3) Reconstructs a latent signal s_hat such that EMA(span, adjust=True) exactly equals mid_obs,
     and checks whether rolling std on s_hat matches sd_obs and whether regenerated bands match.

Example:
  c:/stock/.venv-ai/Scripts/python.exe scripts/analyze_buysell_bands.py \
    --csv "C:\Users\MOON\Downloads\BITMEX_BTCUSD.P, 1.csv" \
    --signal "Buy/Sell Signal" \
    --upper "BuySell Upper Band" \
    --lower "BuySell Lower Band" \
    --span 20 \
    --out logs
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from reverse_engine.buysell_bands import compute_buysell_bands, fit_ema_prev_from_bands


@dataclass(frozen=True)
class Stats:
    n: int
    mae: float
    rmse: float
    max_abs: float
    corr: float | None


def _stats(a: pd.Series, b: pd.Series) -> Stats:
    a = pd.to_numeric(a, errors="coerce")
    b = pd.to_numeric(b, errors="coerce")
    m = np.isfinite(a) & np.isfinite(b)
    n = int(m.sum())
    if n == 0:
        return Stats(n=0, mae=float("nan"), rmse=float("nan"), max_abs=float("nan"), corr=None)
    da = (a[m] - b[m]).to_numpy(dtype=float)
    mae = float(np.mean(np.abs(da)))
    rmse = float(np.sqrt(np.mean(da * da)))
    max_abs = float(np.max(np.abs(da)))
    aa = a[m].to_numpy(dtype=float)
    bb = b[m].to_numpy(dtype=float)
    corr = None
    if n >= 3 and np.isfinite(aa).all() and np.isfinite(bb).all():
        c = np.corrcoef(aa, bb)[0, 1]
        if np.isfinite(c):
            corr = float(c)
    return Stats(n=n, mae=mae, rmse=rmse, max_abs=max_abs, corr=corr)


def _fmt(st: Stats) -> str:
    corr = "" if st.corr is None else f", corr={st.corr:.6f}"
    return f"n={st.n:,}, mae={st.mae:.6g}, rmse={st.rmse:.6g}, max_abs={st.max_abs:.6g}{corr}"


def reconstruct_signal_from_ema(mid_obs: pd.Series, seed: pd.Series, span: int) -> pd.Series:
    """Reconstruct s_hat such that EMA(span, adjust=True) == mid_obs where mid_obs is finite.

    Uses the adjust=True recursion:
      num_t   = s_t + (1-a)*num_{t-1}
      den_t   = 1   + (1-a)*den_{t-1}
      ema_t   = num_t / den_t

    If ema_t is known, solve:
      s_t = ema_t*den_t - (1-a)*num_{t-1}

    For t where mid_obs is NaN, keep seed value.
    """

    a = 2.0 / (span + 1.0)
    decay = 1.0 - a

    seed = pd.to_numeric(seed, errors="coerce")
    mid_obs = pd.to_numeric(mid_obs, errors="coerce")

    s_hat = seed.copy()

    num_prev = float("nan")
    den_prev = float("nan")

    for t in range(len(s_hat)):
        x = float(seed.iloc[t]) if np.isfinite(seed.iloc[t]) else float("nan")

        if t == 0:
            den_prev = 1.0
            num_prev = x
            continue

        den_t = 1.0 + decay * den_prev

        if np.isfinite(mid_obs.iloc[t]):
            ema_t = float(mid_obs.iloc[t])
            s_t = ema_t * den_t - decay * num_prev
            s_hat.iloc[t] = s_t
            num_t = s_t + decay * num_prev
        else:
            s_t = float(s_hat.iloc[t]) if np.isfinite(s_hat.iloc[t]) else float("nan")
            num_t = s_t + decay * num_prev

        den_prev = den_t
        num_prev = num_t

    return s_hat


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--signal", default="Buy/Sell Signal")
    ap.add_argument("--upper", default="BuySell Upper Band")
    ap.add_argument("--lower", default="BuySell Lower Band")
    ap.add_argument("--span", type=int, default=20)
    ap.add_argument("--ddof", type=int, default=0)
    ap.add_argument("--out", default="logs")
    args = ap.parse_args()

    df = pd.read_csv(args.csv)
    df.columns = [c.strip() for c in df.columns]

    for col in (args.signal, args.upper, args.lower):
        if col not in df.columns:
            raise SystemExit(f"Missing column: {col}")

    s = pd.to_numeric(df[args.signal], errors="coerce")
    up = pd.to_numeric(df[args.upper], errors="coerce")
    lo = pd.to_numeric(df[args.lower], errors="coerce")

    mid_obs = 0.5 * (up + lo)
    sd_obs = 0.5 * (up - lo)

    fit = fit_ema_prev_from_bands(s, up, lo, length=args.span)
    if fit is None:
        ema_prev, ema_t0 = None, None
    else:
        ema_prev, ema_t0 = fit
        ema_prev = float(ema_prev)
        ema_t0 = int(ema_t0)

    fixed = compute_buysell_bands(
        s,
        length=args.span,
        k=1.0,
        ddof=args.ddof,
        ema_prev=ema_prev,
        ema_start=ema_t0,
    )

    # Candidate computations from exported signal.
    mid_s_adjT = s.ewm(span=args.span, adjust=True, min_periods=args.span).mean()
    mid_s_adjF = s.ewm(span=args.span, adjust=False, min_periods=args.span).mean()
    sd_s_roll = s.rolling(args.span, min_periods=args.span).std(ddof=args.ddof)
    sd_s_roll_dev = (s - mid_s_adjT).rolling(args.span, min_periods=args.span).std(ddof=args.ddof)
    sd_s_ewm_dev_adjF = np.sqrt(((s - mid_s_adjF) ** 2).ewm(span=args.span, adjust=False, min_periods=args.span).mean())
    sd_s_ewm_dev_adjT = np.sqrt(((s - mid_s_adjT) ** 2).ewm(span=args.span, adjust=True, min_periods=args.span).mean())

    # Reconstruct latent signal that exactly matches mid_obs under EMA(adj=True).
    s_hat = reconstruct_signal_from_ema(mid_obs=mid_obs, seed=s, span=args.span)
    mid_hat = s_hat.ewm(span=args.span, adjust=True, min_periods=args.span).mean()
    sd_hat_roll = s_hat.rolling(args.span, min_periods=args.span).std(ddof=args.ddof)
    sd_hat_roll_dev = (s_hat - mid_hat).rolling(args.span, min_periods=args.span).std(ddof=args.ddof)
    sd_hat_ewm_dev_adjF = np.sqrt(((s_hat - mid_hat) ** 2).ewm(span=args.span, adjust=False, min_periods=args.span).mean())
    sd_hat_ewm_dev_adjT = np.sqrt(((s_hat - mid_hat) ** 2).ewm(span=args.span, adjust=True, min_periods=args.span).mean())

    # Regenerate bands.
    up_hat_roll = mid_hat + sd_hat_roll
    lo_hat_roll = mid_hat - sd_hat_roll
    up_hat_roll_dev = mid_hat + sd_hat_roll_dev
    lo_hat_roll_dev = mid_hat - sd_hat_roll_dev
    up_hat_ewmT = mid_hat + sd_hat_ewm_dev_adjT
    lo_hat_ewmT = mid_hat - sd_hat_ewm_dev_adjT

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = out_dir / f"buysell-bands-analyze-{ts}.md"

    lines: list[str] = []
    lines.append("# BuySell Bands: Hidden Signal Check")
    lines.append("")
    lines.append(f"- CSV: `{args.csv}`")
    lines.append(f"- Signal: `{args.signal}`")
    lines.append(f"- Upper/Lower: `{args.upper}` / `{args.lower}`")
    lines.append(f"- span={args.span}, ddof={args.ddof}")
    lines.append("")

    lines.append("## Step 1: Mid/SD implied by exported bands")
    lines.append("")
    lines.append("- mid_obs = (upper+lower)/2")
    lines.append("- sd_obs  = (upper-lower)/2")
    lines.append("")

    lines.append("## Step 2: Compare mid_obs/sd_obs to computations from exported signal")
    lines.append("")
    lines.append(f"- mid_obs vs EMA(span={args.span}, adjust=True) from signal: {_fmt(_stats(mid_obs, mid_s_adjT))}")
    lines.append(f"- mid_obs vs EMA(span={args.span}, adjust=False) from signal: {_fmt(_stats(mid_obs, mid_s_adjF))}")
    lines.append(f"- sd_obs vs rolling std(span={args.span}, ddof={args.ddof}) from signal: {_fmt(_stats(sd_obs, sd_s_roll))}")
    lines.append(f"- sd_obs vs rolling std of (signal-mid_adjT): {_fmt(_stats(sd_obs, sd_s_roll_dev))}")
    lines.append(f"- sd_obs vs ewm std of dev (adjust=False): {_fmt(_stats(sd_obs, sd_s_ewm_dev_adjF))}")
    lines.append(f"- sd_obs vs ewm std of dev (adjust=True):  {_fmt(_stats(sd_obs, sd_s_ewm_dev_adjT))}")
    lines.append("")

    lines.append("## Step 2b: Fixed BuySell definition (stateful EMA + rolling std)")
    lines.append("")
    lines.append("- mid = EMA(signal, span, adjust=False) with carried state")
    lines.append("- sd  = rolling std(signal, span, ddof)")
    lines.append("- bands = mid ± sd (k=1)")
    lines.append("")
    if fit is None:
        lines.append("- EMA state fit: (not available; insufficient finite overlap)")
    else:
        lines.append(f"- EMA state fit: ema_prev={ema_prev:.12g}, ema_start(t0)={ema_t0}")
    lines.append(f"- Upper vs fixed bands: {_fmt(_stats(up, fixed.upper))}")
    lines.append(f"- Lower vs fixed bands: {_fmt(_stats(lo, fixed.lower))}")
    lines.append("")

    lines.append("## Step 3: Reconstruct latent signal s_hat from mid_obs (EMA adjust=True inversion)")
    lines.append("")
    lines.append(f"- s_hat vs exported signal: {_fmt(_stats(s_hat, s))}")
    lines.append(f"- mid_obs vs EMA(s_hat, adjust=True): {_fmt(_stats(mid_obs, mid_hat))}")
    lines.append("")

    lines.append("## Step 4: Does sd_obs match std computed on s_hat?")
    lines.append("")
    lines.append(f"- sd_obs vs rolling std(s_hat): {_fmt(_stats(sd_obs, sd_hat_roll))}")
    lines.append(f"- sd_obs vs rolling std(s_hat-mid_hat): {_fmt(_stats(sd_obs, sd_hat_roll_dev))}")
    lines.append(f"- sd_obs vs ewm std(dev) on s_hat (adjust=False): {_fmt(_stats(sd_obs, sd_hat_ewm_dev_adjF))}")
    lines.append(f"- sd_obs vs ewm std(dev) on s_hat (adjust=True):  {_fmt(_stats(sd_obs, sd_hat_ewm_dev_adjT))}")
    lines.append("")

    lines.append("## Step 5: Regenerate bands from s_hat and compare")
    lines.append("")
    lines.append(f"- Upper vs mid_hat+rollstd(s_hat): {_fmt(_stats(up, up_hat_roll))}")
    lines.append(f"- Lower vs mid_hat-rollstd(s_hat): {_fmt(_stats(lo, lo_hat_roll))}")
    lines.append(f"- Upper vs mid_hat+rollstd(s_hat-mid_hat): {_fmt(_stats(up, up_hat_roll_dev))}")
    lines.append(f"- Lower vs mid_hat-rollstd(s_hat-mid_hat): {_fmt(_stats(lo, lo_hat_roll_dev))}")
    lines.append(f"- Upper vs mid_hat+ewmstd(dev,adj=T): {_fmt(_stats(up, up_hat_ewmT))}")
    lines.append(f"- Lower vs mid_hat-ewmstd(dev,adj=T): {_fmt(_stats(lo, lo_hat_ewmT))}")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
