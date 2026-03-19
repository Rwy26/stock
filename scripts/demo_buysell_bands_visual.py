r"""Visual demo for BuySell Upper/Lower Bands matching.

Creates a small HTML report (with embedded PNG) showing:
- Exported bands vs fixed-definition recomputation (stateful EMA + rolling std)
- mid_obs/sd_obs decomposition vs computed mid/sd

Example:
  c:/stock/.venv-ai/Scripts/python.exe scripts/demo_buysell_bands_visual.py \
    --csv "C:\Users\MOON\Downloads\BITMEX_BTCUSD.P, 1.csv" \
    --signal "Buy/Sell Signal" \
    --upper "BuySell Upper Band" \
    --lower "BuySell Lower Band" \
    --span 20 --ddof 0 --out logs --open
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime
from io import BytesIO
from pathlib import Path
import webbrowser

import numpy as np
import pandas as pd

from reverse_engine.buysell_bands import compute_buysell_bands, fit_ema_prev_from_bands
from reverse_engine.metrics import compare_series


def _b64_png(fig) -> str:
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=140, bbox_inches="tight")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--signal", default="Buy/Sell Signal")
    ap.add_argument("--upper", default="BuySell Upper Band")
    ap.add_argument("--lower", default="BuySell Lower Band")
    ap.add_argument("--span", type=int, default=20)
    ap.add_argument("--ddof", type=int, default=0)
    ap.add_argument("--out", default="logs")
    ap.add_argument("--open", action="store_true")
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

    up_stats = compare_series(up, fixed.upper)
    lo_stats = compare_series(lo, fixed.lower)

    # For reference: naive mid calculations
    mid_adjT = s.ewm(span=args.span, adjust=True, min_periods=args.span).mean()
    mid_adjF = s.ewm(span=args.span, adjust=False, min_periods=args.span).mean()

    # Matplotlib import only when needed (keeps import errors localized)
    import matplotlib.pyplot as plt

    x = np.arange(len(df))

    fig = plt.figure(figsize=(13.5, 9.5))
    gs = fig.add_gridspec(3, 1, height_ratios=[2.2, 1.5, 1.4], hspace=0.22)

    ax0 = fig.add_subplot(gs[0])
    ax0.set_title("BuySell Bands: exported vs fixed-definition")
    ax0.plot(x, s, color="tab:gray", linewidth=1.0, label="signal")
    ax0.plot(x, up, color="tab:orange", linewidth=1.2, label="upper (exported)")
    ax0.plot(x, lo, color="tab:blue", linewidth=1.2, label="lower (exported)")
    ax0.plot(x, fixed.upper, color="tab:orange", linestyle="--", linewidth=1.0, label="upper (fixed)")
    ax0.plot(x, fixed.lower, color="tab:blue", linestyle="--", linewidth=1.0, label="lower (fixed)")
    ax0.grid(True, alpha=0.25)
    ax0.legend(loc="upper left", ncol=2, fontsize=9)

    ax1 = fig.add_subplot(gs[1], sharex=ax0)
    ax1.set_title("Midline comparison")
    ax1.plot(x, mid_obs, color="black", linewidth=1.2, label="mid_obs=(up+lo)/2")
    ax1.plot(x, fixed.mid, color="tab:green", linestyle="--", linewidth=1.2, label="mid_fixed (stateful EMA adj=False)")
    ax1.plot(x, mid_adjT, color="tab:purple", linewidth=1.0, alpha=0.7, label="EMA adj=True (pandas default)")
    ax1.plot(x, mid_adjF, color="tab:red", linewidth=1.0, alpha=0.7, label="EMA adj=False (pandas default)")
    ax1.grid(True, alpha=0.25)
    ax1.legend(loc="upper left", ncol=2, fontsize=9)

    ax2 = fig.add_subplot(gs[2], sharex=ax0)
    ax2.set_title("SD comparison")
    ax2.plot(x, sd_obs, color="black", linewidth=1.2, label="sd_obs=(up-lo)/2")
    ax2.plot(x, fixed.sd, color="tab:green", linestyle="--", linewidth=1.2, label="sd_fixed (rolling std)")
    ax2.grid(True, alpha=0.25)
    ax2.legend(loc="upper left", fontsize=9)

    # Small summary text
    extra = []
    if fit is None:
        extra.append("ema_prev: (fit unavailable)")
    else:
        extra.append(f"ema_prev={ema_prev:.12g}, t0={ema_t0}")
    extra.append(f"Upper MAE={up_stats.mae:.3g}, max_abs={up_stats.max_abs:.3g}")
    extra.append(f"Lower MAE={lo_stats.mae:.3g}, max_abs={lo_stats.max_abs:.3g}")
    fig.text(0.01, 0.01, " | ".join(extra), fontsize=9)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    png_path = out_dir / f"buysell-bands-demo-{ts}.png"
    html_path = out_dir / f"buysell-bands-demo-{ts}.html"

    fig.savefig(png_path, dpi=160, bbox_inches="tight")
    b64 = _b64_png(fig)
    plt.close(fig)

    html = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>BuySell Bands Demo</title>
  <style>
    body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 18px; }}
    .meta {{ color: #333; font-size: 14px; line-height: 1.5; }}
    img {{ max-width: 100%; height: auto; border: 1px solid #ddd; }}
    code {{ background: #f6f8fa; padding: 0 4px; border-radius: 4px; }}
  </style>
</head>
<body>
  <h2>BuySell Bands Visual Demo</h2>
  <div class=\"meta\">
    <div><b>CSV</b>: <code>{args.csv}</code></div>
    <div><b>Columns</b>: signal=<code>{args.signal}</code>, upper=<code>{args.upper}</code>, lower=<code>{args.lower}</code></div>
    <div><b>Fixed definition</b>: mid=EMA(span={args.span}, adjust=False, stateful), sd=rolling std(span={args.span}, ddof={args.ddof}), k=1</div>
    <div><b>EMA state</b>: <code>{'unavailable' if fit is None else f'ema_prev={ema_prev:.12g}, t0={ema_t0}'}</code></div>
    <div><b>Match</b>: upper mae={up_stats.mae:.6g}, lower mae={lo_stats.mae:.6g}</div>
  </div>
  <p>PNG file: <code>{png_path.as_posix()}</code></p>
  <img alt=\"buysell bands\" src=\"data:image/png;base64,{b64}\" />
</body>
</html>"""

    html_path.write_text(html, encoding="utf-8")
    print(str(html_path))

    if args.open:
        webbrowser.open(html_path.resolve().as_uri())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
