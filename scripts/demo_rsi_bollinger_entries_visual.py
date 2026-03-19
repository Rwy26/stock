r"""Visual demo: RSI Bollinger re-entry events (buy/sell).

Key idea (per user):
- Buy: RSI was below the lower Bollinger band and re-enters the band upward.
- Sell: RSI was above the upper Bollinger band and re-enters the band downward.

Outputs:
- PNG chart
- HTML report with embedded PNG (optional auto-open)

Example:
  c:/stock/.venv-ai/Scripts/python.exe scripts/demo_rsi_bollinger_entries_visual.py \
    --csv "C:\Users\MOON\Downloads\BITMEX_BTCUSD.P, 1.csv" \
    --rsi "RSI" \
    --upper "Upper Bollinger Band" \
    --lower "Lower Bollinger Band" \
    --mid "RSI-based MA" \
    --price "close" \
    --out logs --open
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


def _b64_png(fig) -> str:
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=140, bbox_inches="tight")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


def _pick_time_index(df: pd.DataFrame) -> pd.Index:
    if "time" in df.columns:
        t = pd.to_numeric(df["time"], errors="coerce")
        # Heuristic: epoch ms vs s
        if np.isfinite(t).any():
            v = float(t.dropna().iloc[0])
            unit = "ms" if v > 2e12 else "s" if v > 2e9 else None
            if unit is not None:
                return pd.to_datetime(t, unit=unit, utc=True).dt.tz_convert(None)
    return df.index


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--rsi", default="RSI")
    ap.add_argument("--upper", default="Upper Bollinger Band")
    ap.add_argument("--lower", default="Lower Bollinger Band")
    ap.add_argument("--mid", default="RSI-based MA")
    ap.add_argument("--price", default="close")
    ap.add_argument("--out", default="logs")
    ap.add_argument("--open", action="store_true")
    args = ap.parse_args()

    df = pd.read_csv(args.csv)
    df.columns = [c.strip() for c in df.columns]

    for col in (args.rsi, args.upper, args.lower):
        if col not in df.columns:
            raise SystemExit(f"Missing column: {col}")

    rsi = pd.to_numeric(df[args.rsi], errors="coerce")
    upper = pd.to_numeric(df[args.upper], errors="coerce")
    lower = pd.to_numeric(df[args.lower], errors="coerce")

    if args.mid in df.columns:
        mid = pd.to_numeric(df[args.mid], errors="coerce")
    else:
        mid = 0.5 * (upper + lower)

    price = pd.to_numeric(df[args.price], errors="coerce") if args.price in df.columns else None
    t_idx = _pick_time_index(df)

    # Define "re-entry" events (outside -> inside).
    prev_rsi = rsi.shift(1)
    prev_upper = upper.shift(1)
    prev_lower = lower.shift(1)

    inside_now = (rsi >= lower) & (rsi <= upper)

    reentry_buy = (prev_rsi < prev_lower) & inside_now
    reentry_sell = (prev_rsi > prev_upper) & inside_now

    # User rule: signal triggers only if the *next* candle is closer to mid than the re-entry candle.
    dist = (rsi - mid).abs()
    dist_next = dist.shift(-1)
    closer_next = dist_next < dist

    # Signal occurs at t+1.
    buy = reentry_buy & closer_next
    sell = reentry_sell & closer_next

    buy_idx = np.flatnonzero(buy.fillna(False).to_numpy()) + 1
    sell_idx = np.flatnonzero(sell.fillna(False).to_numpy()) + 1

    # Clip in case the last point would overflow.
    buy_idx = buy_idx[buy_idx < len(df)]
    sell_idx = sell_idx[sell_idx < len(df)]

    # Matplotlib import only when needed.
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(14.5, 8.5))
    gs = fig.add_gridspec(2, 1, height_ratios=[1.15, 1.65], hspace=0.12)

    ax0 = fig.add_subplot(gs[0])
    ax1 = fig.add_subplot(gs[1], sharex=ax0)

    # Price panel (context)
    if price is not None:
        ax0.set_title("Context: price with RSI re-entry markers")
        ax0.plot(t_idx, price, color="tab:gray", linewidth=1.1, label=args.price)
        for i in buy_idx:
            ax0.axvline(t_idx[i], color="#0a7a0a", alpha=0.22, linewidth=1.2)
        for i in sell_idx:
            ax0.axvline(t_idx[i], color="#b00020", alpha=0.22, linewidth=1.2)
        ax0.grid(True, alpha=0.22)
        ax0.legend(loc="upper left", fontsize=9)
    else:
        ax0.set_visible(False)

    # RSI + bands panel
    ax1.set_title("RSI Bollinger Bands: confirmed re-entry signals (next candle closer to mid)")

    # Band area
    ax1.fill_between(t_idx, lower.to_numpy(dtype=float), upper.to_numpy(dtype=float), color="tab:blue", alpha=0.08, label="band (lower..upper)")

    # Plot bands and RSI
    ax1.plot(t_idx, upper, color="tab:orange", linewidth=1.2, label="upper band")
    ax1.plot(t_idx, lower, color="tab:orange", linewidth=1.2, label="lower band")
    ax1.plot(t_idx, mid, color="tab:green", linewidth=1.2, alpha=0.9, label="mid")
    ax1.plot(t_idx, rsi, color="black", linewidth=1.1, label="RSI")

    # Highlight outside regions to make it obvious
    rsi_arr = rsi.to_numpy(dtype=float)
    upper_arr = upper.to_numpy(dtype=float)
    lower_arr = lower.to_numpy(dtype=float)
    ax1.fill_between(t_idx, rsi_arr, upper_arr, where=(rsi_arr > upper_arr), color="#b00020", alpha=0.10, interpolate=True, label="RSI above upper")
    ax1.fill_between(t_idx, lower_arr, rsi_arr, where=(rsi_arr < lower_arr), color="#0a7a0a", alpha=0.10, interpolate=True, label="RSI below lower")

    # Event markers
    ax1.scatter(
        t_idx[buy_idx],
        rsi.iloc[buy_idx],
        marker="^",
        s=100,
        color="#0a7a0a",
        edgecolor="white",
        linewidth=0.6,
        zorder=5,
        label=f"BUY signal ({len(buy_idx)})",
    )
    ax1.scatter(
        t_idx[sell_idx],
        rsi.iloc[sell_idx],
        marker="v",
        s=100,
        color="#b00020",
        edgecolor="white",
        linewidth=0.6,
        zorder=5,
        label=f"SELL signal ({len(sell_idx)})",
    )

    ax1.grid(True, alpha=0.22)
    ax1.set_ylim(
        float(np.nanmin([np.nanmin(rsi_arr), np.nanmin(lower_arr), 0.0])),
        float(np.nanmax([np.nanmax(rsi_arr), np.nanmax(upper_arr), 100.0])),
    )
    ax1.legend(loc="upper left", ncol=2, fontsize=9)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    png_path = out_dir / f"rsi-bollinger-reentry-demo-{ts}.png"
    html_path = out_dir / f"rsi-bollinger-reentry-demo-{ts}.html"

    fig.savefig(png_path, dpi=170, bbox_inches="tight")
    b64 = _b64_png(fig)
    plt.close(fig)

    html = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>RSI Bollinger Re-entry Demo</title>
  <style>
    body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 18px; }}
    .meta {{ color: #333; font-size: 14px; line-height: 1.5; }}
    img {{ max-width: 100%; height: auto; border: 1px solid #ddd; }}
    code {{ background: #f6f8fa; padding: 0 4px; border-radius: 4px; }}
  </style>
</head>
<body>
  <h2>RSI Bollinger Re-entry (Visual Demo)</h2>
  <div class=\"meta\">
    <div><b>CSV</b>: <code>{args.csv}</code></div>
    <div><b>Columns</b>: rsi=<code>{args.rsi}</code>, upper=<code>{args.upper}</code>, lower=<code>{args.lower}</code>, mid=<code>{args.mid if args.mid in df.columns else '(upper+lower)/2'}</code></div>
        <div><b>BUY</b>: re-entry from below, then next candle is closer to mid</div>
        <div><b>SELL</b>: re-entry from above, then next candle is closer to mid</div>
    <div><b>Counts</b>: BUY={len(buy_idx)}, SELL={len(sell_idx)}</div>
  </div>
  <p>PNG file: <code>{png_path.as_posix()}</code></p>
  <img alt=\"rsi bollinger re-entry\" src=\"data:image/png;base64,{b64}\" />
</body>
</html>"""

    html_path.write_text(html, encoding="utf-8")
    print(str(html_path))

    if args.open:
        webbrowser.open(html_path.resolve().as_uri())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
