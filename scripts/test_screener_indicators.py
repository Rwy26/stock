"""screener_engine 지표 순수 함수 단위 점검 (알려진 시계열로 검출 확인).

실행:
  cd C:\\stock\\backend
  .\\.venv\\Scripts\\python.exe ..\\scripts\\test_screener_indicators.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

import numpy as np
import pandas as pd

import screener_engine as se

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}")


def s(vals):
    return pd.Series(vals, index=pd.RangeIndex(len(vals)), dtype=float)


# 1) _cross_down: 전일 위/당일 아래만 True
a = s([1, 2, 3, 2])
b = s([2, 2, 2, 2.5])
check("cross_down detects last-bar down cross", se._cross_down(a, b) is True)
a2 = s([3, 3, 3, 3])
check("cross_down no-cross stays False", se._cross_down(a2, b) is False)

# 2) _cross_below_zero
check("cross_below_zero true", se._cross_below_zero(s([1, 0.5, -0.2])) is True)
check("cross_below_zero false (already below)", se._cross_below_zero(s([-1, -0.5, -0.2])) is False)

# 3) MA dead cross: 상승추세 후 급락으로 5선이 20선 하향돌파
up = list(np.linspace(100, 140, 30))      # 완만 상승
drop = list(np.linspace(139, 110, 6))     # 마지막 급락
close = s(up + drop)
check("ma_dead_cross 5/20 detects drop", se.ma_dead_cross(close, 5, 20) is True)
check("ma_dead_cross pure uptrend = False", se.ma_dead_cross(s(up), 5, 20) is False)

# 4) MACD osc 0선 하향돌파: 상승 후 꺾임
seq = list(np.linspace(100, 130, 40)) + list(np.linspace(129, 118, 8))
check("macd_osc_down on reversal", se.macd_osc_down(s(seq)) is True)

# 5) RSI signal 하향돌파
check("rsi_signal_down on reversal", isinstance(se.rsi_signal_down(s(seq)), bool))

# 6) 하한가 판정
ld = s([1000, 1000, 700])  # -30%
check("is_limit_down true (-30%)", se.is_limit_down(ld, -1) is True)
nd = s([1000, 1000, 950])  # -5%
check("is_limit_down false (-5%)", se.is_limit_down(nd, -1) is False)

# 7) classify_stock: 이력 부족 → insufficient
short_df = pd.DataFrame(
    {"open": [1, 2], "high": [1, 2], "low": [1, 2], "close": [1, 2], "volume": [1, 1]}
)
r = se.classify_stock(short_df, "TEST")
check("classify_stock insufficient on short history", r.insufficient is True)

# 8) classify_stock: 저점하회(1년) — 마지막 종가가 252봉 최저
n = 260
base = list(np.linspace(200, 120, n - 1)) + [90.0]  # 마지막이 최저
df = pd.DataFrame(
    {"open": base, "high": [x * 1.01 for x in base], "low": [x * 0.99 for x in base],
     "close": base, "volume": [1] * n}
)
r = se.classify_stock(df, "LOW1Y")
check("classify_stock flags lowBreak1y", "lowBreak1y" in r.flags)
check("classify_stock not lowBreak3m when 1y", "lowBreak3m" not in r.flags)

# 9) build_report 구조
rep = se.build_report([r], se.date(2026, 6, 25))
check("build_report has categories", "categories" in rep and "lowBreak1y" in rep["categories"])
check("build_report has 9 indicators", len(rep["indicators"]) == 9)
check("build_report frequency present", isinstance(rep["frequency"], dict))

print(f"\n결과: PASS={PASS} FAIL={FAIL}")
sys.exit(1 if FAIL else 0)
