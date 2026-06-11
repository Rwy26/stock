"""닷컴 데이터셋 명목 가격 복원 — 야후 시세는 분할을 현재 기준으로 소급 조정함.

야후 특성: auto_adjust=False 여도 분할(액면병합/분할)은 항상 소급 반영.
→ 1999년 AMZN 종가가 5.65 로 보임 (당시 명목 113.00 ÷ 2022년 20:1 분할).

복원: close_nominal = close × (해당 일자 이후 ~ 현재까지 분할 비율의 누적곱)
당시 언론 기록·10-K Item 5 주가범위·명목 EPS 와 직접 비교 가능한 가격.

산출:
  actions/splits_full_history.csv   전체 분할 이력 (2026 현재까지 — 복원 계수의 근거)
  ohlcv/{SYM}.csv                   open/high/low/close 의 *_nominal 4컬럼 추가
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(r"D:\STOCK DATA-US\dotcom_1995_2002")
STOCKS = ["AMZN", "CSCO", "INTC", "ORCL", "MSFT"]


def main() -> None:
    import yfinance as yf

    rows = []
    for sym in STOCKS:
        sp = yf.Ticker(sym).splits  # 전체 이력 (상장~현재)
        for d, ratio in sp.items():
            rows.append({"symbol": sym, "date": d.strftime("%Y-%m-%d"),
                         "ratio": float(ratio)})
        time.sleep(0.4)
    full = pd.DataFrame(rows).sort_values(["symbol", "date"])
    full.to_csv(ROOT / "actions" / "splits_full_history.csv", index=False)
    print(f"전체 분할 이력 {len(full)}건 저장")

    for sym in STOCKS:
        f = ROOT / "ohlcv" / f"{sym}.csv"
        df = pd.read_csv(f, index_col="date", parse_dates=True)
        sp = full[full.symbol == sym]
        # 각 일자에 대해 '그 이후' 분할 비율 누적곱 = 명목 복원 계수
        factors = pd.Series(1.0, index=df.index)
        for _, r in sp.iterrows():
            d = pd.Timestamp(r["date"])
            factors[df.index < d] *= r["ratio"]
        df["split_factor_to_present"] = factors
        for col in ("open", "high", "low", "close"):
            df[f"{col}_nominal"] = (df[col] * factors).round(4)
        df.to_csv(f)
        c0 = df["close_nominal"].iloc[0]
        print(f"  {sym}: 계수 {factors.max():.0f}→{factors.min():.0f}, "
              f"첫 명목종가 {c0:.2f}")


if __name__ == "__main__":
    main()
