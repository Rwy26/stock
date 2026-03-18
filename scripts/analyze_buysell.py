from __future__ import annotations

import argparse

import numpy as np
import pandas as pd


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--signal", default="Buy/Sell Signal")
    args = ap.parse_args()

    df = pd.read_csv(args.csv)
    df.columns = [c.strip() for c in df.columns]

    if args.signal not in df.columns:
        raise SystemExit(f"Missing signal column: {args.signal}")

    sig = pd.to_numeric(df[args.signal], errors="coerce")

    features = [
        "RSI",
        "RSI-based MA",
        "Upper Bollinger Band",
        "Lower Bollinger Band",
        "Tenkan Sen",
        "Kijun Sen",
        "Chikou Span",
        "Senkou Span A",
        "Senkou Span B",
        "Volume",
        "open",
        "high",
        "low",
        "close",
        "BuySell Upper Band",
        "BuySell Lower Band",
    ]
    features = [f for f in features if f in df.columns]

    X: dict[str, pd.Series] = {}
    for f in features:
        X[f] = pd.to_numeric(df[f], errors="coerce")

    if "RSI" in X and "RSI-based MA" in X:
        X["RSI_minus_MA"] = X["RSI"] - X["RSI-based MA"]
        X["RSI_minus_MA_half"] = 0.5 * (X["RSI"] - X["RSI-based MA"])

    if "Upper Bollinger Band" in X and "Lower Bollinger Band" in X and "RSI" in X:
        X["BB_mid"] = 0.5 * (X["Upper Bollinger Band"] + X["Lower Bollinger Band"])
        X["BB_width"] = X["Upper Bollinger Band"] - X["Lower Bollinger Band"]
        X["RSI_z"] = (X["RSI"] - X["BB_mid"]) / X["BB_width"]

    print("rows", len(df))
    print("signal non-null", int(sig.notna().sum()))
    print("")

    rows = []
    for k, v in X.items():
        m = np.isfinite(sig) & np.isfinite(v)
        n = int(m.sum())
        if n < 30:
            continue
        corr = float(np.corrcoef(sig[m], v[m])[0, 1])
        mae = float(np.mean(np.abs(sig[m] - v[m])))
        rows.append((k, corr, mae, n))

    rows.sort(key=lambda t: (-abs(t[1]), t[2]))
    for k, corr, mae, n in rows:
        print(f"{k:20s} corr={corr: .4f} mae(sig-v)={mae: .4f} n={n}")

    if "RSI_minus_MA" in X:
        v = X["RSI_minus_MA"]
        m = np.isfinite(sig) & np.isfinite(v)
        A = np.vstack([v[m].to_numpy(), np.ones(int(m.sum()))]).T
        a, b = np.linalg.lstsq(A, sig[m].to_numpy(), rcond=None)[0]
        pred = a * v[m] + b
        mae = float(np.mean(np.abs(sig[m] - pred)))
        rmse = float(np.sqrt(np.mean((sig[m] - pred) ** 2)))
        print("\nfit: sig = a*(RSI-RSI_MA)+b")
        print("a=", float(a), "b=", float(b), "mae=", mae, "rmse=", rmse)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
