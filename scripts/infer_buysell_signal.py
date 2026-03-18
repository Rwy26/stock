r"""CLI: infer Buy/Sell Signal formula from CSV columns.

Example:
  c:/stock/.venv-ai/Scripts/python.exe scripts/infer_buysell_signal.py \
    --csv "C:\Users\MOON\Downloads\BITMEX_BTCUSD.P, 1.csv" \
    --signal "Buy/Sell Signal" \
    --sources "RSI" "RSI-based MA" \
    --out logs
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from reverse_engine.buysell_signal import infer_buysell_signal


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--signal", default="Buy/Sell Signal")
    ap.add_argument(
        "--sources",
        nargs="+",
        default=[
            "RSI",
            "RSI-based MA",
            "open",
            "high",
            "low",
            "close",
            "Volume",
            "Tenkan Sen",
            "Kijun Sen",
            "Senkou Span A",
            "Senkou Span B",
            "Chikou Span",
            "Upper Bollinger Band",
            "Lower Bollinger Band",
        ],
        help="Column names to use as base sources",
    )
    ap.add_argument("--out", default="logs")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--top2", type=int, default=15)
    args = ap.parse_args()

    df = pd.read_csv(args.csv)
    df.columns = [c.strip() for c in df.columns]

    if args.signal not in df.columns:
        raise SystemExit(f"Missing signal column: {args.signal}")

    target = pd.to_numeric(df[args.signal], errors="coerce")

    sources: dict[str, pd.Series] = {}
    for col in args.sources:
        if col in df.columns:
            sources[col] = pd.to_numeric(df[col], errors="coerce")

    if not sources:
        raise SystemExit("No sources found in CSV. Pass valid --sources column names.")

    result = infer_buysell_signal(target, sources, top_n=args.top, top2_n=args.top2)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = out_dir / f"buysell-infer-{ts}.md"

    lines: list[str] = []
    lines.append("# Buy/Sell Signal Inference")
    lines.append("")
    lines.append(f"- CSV: `{args.csv}`")
    lines.append(f"- Target column: `{args.signal}`")
    lines.append(f"- Source columns: {', '.join('`'+c+'`' for c in sources.keys())}")
    lines.append("")

    if result.best is None and result.best2 is None:
        lines.append("No candidates produced (insufficient overlap / data).")
        out_path.write_text("\n".join(lines), encoding="utf-8")
        print(str(out_path))
        return 0

    if result.best is not None:
        best = result.best
        st = best.stats
        corr = "" if st.corr is None else f", corr={st.corr:.6f}"
        lines.append("## Best (Single Feature)")
        lines.append("")
        lines.append(f"- {best.tag}")
        lines.append(f"- n={st.n:,}, mae={st.mae:.6g}, rmse={st.rmse:.6g}, max_abs={st.max_abs:.6g}{corr}")
        lines.append("")

    if result.best2 is not None:
        best2 = result.best2
        st = best2.stats
        corr = "" if st.corr is None else f", corr={st.corr:.6f}"
        lines.append("## Best (Two Features)")
        lines.append("")
        lines.append(f"- {best2.tag}")
        lines.append(f"- n={st.n:,}, mae={st.mae:.6g}, rmse={st.rmse:.6g}, max_abs={st.max_abs:.6g}{corr}")
        lines.append("")

    if result.top:
        lines.append("## Top Candidates (Single Feature)")
        lines.append("")
        lines.append("| Rank | MAE | RMSE | Corr | Formula |")
        lines.append("|---:|---:|---:|---:|---|")
        for i, cand in enumerate(result.top, start=1):
            st = cand.stats
            corr_val = "" if st.corr is None else f"{st.corr:.6f}"
            mae = "" if not np.isfinite(st.mae) else f"{st.mae:.6g}"
            rmse = "" if not np.isfinite(st.rmse) else f"{st.rmse:.6g}"
            lines.append(f"| {i} | {mae} | {rmse} | {corr_val} | {cand.tag} |")

    if result.top2:
        lines.append("")
        lines.append("## Top Candidates (Two Features)")
        lines.append("")
        lines.append("| Rank | MAE | RMSE | Corr | Formula |")
        lines.append("|---:|---:|---:|---:|---|")
        for i, cand in enumerate(result.top2, start=1):
            st = cand.stats
            corr_val = "" if st.corr is None else f"{st.corr:.6f}"
            mae = "" if not np.isfinite(st.mae) else f"{st.mae:.6g}"
            rmse = "" if not np.isfinite(st.rmse) else f"{st.rmse:.6g}"
            lines.append(f"| {i} | {mae} | {rmse} | {corr_val} | {cand.tag} |")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
