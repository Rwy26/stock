"""닷컴 데이터셋 앵커 검증 — 외부 기록값과 '당시 명목 가격(*_nominal)' 대조.

야후 시세는 분할 소급 조정 → add_us_dotcom_nominal_prices.py 가 복원한
명목 컬럼을 당시 언론·SEC 공시 기록과 비교한다. 재실행 시 기존 앵커 항목은
이름으로 대체(중복 누적 방지).

앵커 출처 (2026-06-11 검증):
  CSCO 2000-03-27 종가 $80.06       — CNBC 2025-12-10 (사상 최고 종가)
  INTC 2000-08-31 종가 $74.88       — TheStreet 회고
  ORCL 2000-09 고점   $46.47        — Benzinga/EWM
  AMZN 1999-12 장중고 $113.00       — NewTraderU 등
  AMZN 1997-05-15 IPO 종가 $23.50   — 공모가 $18, 첫날 종가 공지 기록
  MSFT 1999-10~12 분기 최고 $119.94 — MSFT FY2000 10-K Item 5 (SEC 공시 원본,
                                      edgar/MSFT/2000-09-28_10-K_...txt L6064)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(r"D:\STOCK DATA-US\dotcom_1995_2002")

ANCHORS = [
    ("CSCO", "close_nominal", "2000-03-27", 80.06, 0.5,
     "사상 최고 종가 (MS 시총 추월일)", "cnbc.com 2025-12-10"),
    ("INTC", "close_nominal", "2000-08-31", 74.88, 0.5,
     "사상 최고 종가", "thestreet.com 회고"),
    # 문헌의 $46.47 은 현재 분할 기준(2000-10-13 2:1 반영) — 조정 high 로 대조.
    # 당시 명목 가격은 92.94 (high_nominal, 2000-09-01).
    ("ORCL", "high", ("2000-08-01", "2000-10-31"), 46.47, 0.5,
     "2000-09-01 사상 최고 (현재 분할 기준 장중가)",
     "benzinga.com / ewminteractive.com"),
    ("AMZN", "high_nominal", ("1999-12-01", "1999-12-31"), 113.00, 1.0,
     "1999-12 장중 최고", "newtraderu.com"),
    ("AMZN", "close_nominal", "1997-05-15", 23.50, 0.5,
     "IPO 첫날 종가 (공모가 $18)", "당시 보도 다수"),
    ("MSFT", "high_nominal", ("1999-10-01", "1999-12-31"), 119.94, 0.5,
     "FY2000 Q2 분기 최고가 — 발행사 SEC 공시 직접 대조",
     "MSFT FY2000 10-K Item 5 (edgar/MSFT/2000-09-28 L6064)"),
]


def main() -> None:
    rp = ROOT / "verification_report.json"
    report = json.loads(rp.read_text(encoding="utf-8"))
    # 기존 앵커 항목 제거 후 재작성 (재실행 누적 방지)
    report["checks"] = [c for c in report["checks"] if "앵커 대조" not in c["name"]]

    for sym, col, when, expect, tol_pct, desc, src in ANCHORS:
        df = pd.read_csv(ROOT / "ohlcv" / f"{sym}.csv", index_col="date", parse_dates=True)
        if isinstance(when, tuple):
            got = float(df.loc[when[0]:when[1], col].max())
            label = f"{when[0]}~{when[1]} 최대 {col}"
        else:
            got = float(df.loc[when, col])
            label = f"{when} {col}"
        diff = abs(got / expect - 1) * 100
        ok = diff <= tol_pct
        report["checks"].append({
            "name": f"{sym} 앵커 대조 — {desc}",
            "passed": bool(ok),
            "detail": f"{label} = {got:.2f} vs 기록 {expect} (편차 {diff:.3f}%) | 출처: {src}",
        })
        print(("  [PASS] " if ok else "  [FAIL] ") + f"{sym}: {got:.2f} vs {expect} ({diff:.3f}%)")

    report["nasdaqPeContext"] = {
        "note": ("나스닥 P/E 시계열은 신뢰 가능한 무료 소스 부재로 미수록. "
                 "문헌값: 2000-03 고점 트레일링 P/E 추정 100~200배(방법론별 상이), "
                 "NDX 포워드 P/E ~60배. 절반 이상 종목이 적자라 집계 P/E 자체가 불안정. "
                 "개별주 P/E 는 edgar/ 의 10-K 분기 EPS × 명목 가격으로 산출 가능(후속 단계)."),
        "sources": ["en.wikipedia.org/wiki/Dot-com_bubble",
                    "blogs.cfainstitute.org 2020-11-03", "marcus.com (Goldman Sachs)"],
    }
    report["priceAdjustmentNote"] = (
        "ohlcv 의 open/high/low/close 는 야후 특성상 분할 소급 조정값(현재 기준), "
        "adj_close 는 분할+배당 조정값. *_nominal 4컬럼이 당시 명목 가격 "
        "(splits_full_history.csv 누적곱으로 복원)이며 10-K 명목 EPS 와의 P/E 계산에 사용할 것.")
    rp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    n_fail = sum(1 for c in report["checks"] if c["passed"] is False)
    print(f"앵커 검증 반영 완료 — 전체 체크 {len(report['checks'])}건 중 실패 {n_fail}건")


if __name__ == "__main__":
    main()
