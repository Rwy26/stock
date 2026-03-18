r"""CLI: infer Bollinger Band formula from CSV columns.

Example:
  c:/stock/.venv-ai/Scripts/python.exe scripts/infer_bollinger.py \
    --csv "C:\Users\MOON\Downloads\BITMEX_BTCUSD.P, 1.csv" \
    --upper "Upper Bollinger Band" --lower "Lower Bollinger Band" \
    --sources "RSI" "RSI-based MA" \
    --out logs
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from reverse_engine.bollinger import infer_bollinger
from reverse_engine.metrics import to_numeric_series


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--upper", default="Upper Bollinger Band")
    ap.add_argument("--lower", default="Lower Bollinger Band")
    ap.add_argument("--sources", nargs="+", default=["RSI", "RSI-based MA"], help="Column names to use as base sources")
    ap.add_argument("--out", default="logs")
    args = ap.parse_args()

    df = pd.read_csv(args.csv)
    df.columns = [c.strip() for c in df.columns]

    upper = df[args.upper] if args.upper in df.columns else None
    lower = df[args.lower] if args.lower in df.columns else None

    sources: dict[str, pd.Series] = {}
    for col in args.sources:
        if col in df.columns:
            sources[col] = to_numeric_series(df[col])

    if not sources:
        raise SystemExit("No sources found in CSV. Pass valid --sources column names.")

    result = infer_bollinger(upper, lower, sources)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = out_dir / f"bollinger-infer-{ts}.md"

    lines: list[str] = []
    lines.append("# Bollinger Inference")
    lines.append("")
    lines.append(f"- CSV: `{args.csv}`")
    lines.append(f"- Best: {result.best_tag}")
    lines.append("")

    def fmt_stats(label: str, st):
        if st is None or not np.isfinite(st.mae):
            return f"- {label}: (no stats)"
        corr = "" if st.corr is None else f", corr={st.corr:.6f}"
        return f"- {label}: n={st.n:,}, mae={st.mae:.6g}, rmse={st.rmse:.6g}, max_abs={st.max_abs:.6g}{corr}"

    lines.append(fmt_stats("Upper", result.upper_stats))
    lines.append(fmt_stats("Lower", result.lower_stats))
    lines.append("")

    if result.top:
        lines.append("## Top Candidates")
        lines.append("")
        lines.append("| Rank | Score(MAE avg) | Tag |")
        lines.append("|---:|---:|---|")
        for i, cand in enumerate(result.top, start=1):
            lines.append(f"| {i} | {cand.score:.6g} | {cand.tag} |")
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
