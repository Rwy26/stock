"""calibration_report.py

AI 시그널 확신도 보정 리포트 — 2단계 (signal_outcomes 집계).

채점 완료(scored_at IS NOT NULL)된 예측 행을 모아,
예측 확신도(confidence, 0~100)를 적중확률로 보고 **실현 적중률(hit_1d)** 과 비교한다.

산출:
  · 신뢰도 곡선(reliability) — confidence 구간별 [표본수 / 평균 예측확률 / 실현 적중률 / 갭]
      갭 = 평균예측확률 − 실현적중률  (양수 = 과신 over-confident)
  · Brier score — mean((conf/100 − hit)^2). 0=완벽, 0.25=무정보(p=0.5), 1=최악.
  · ECE (Expected Calibration Error) — Σ (n_b/N)·|예측−실현| 가중 평균 보정오차.
  · 시그널별·(옵션)섹터별 분해 + 과신 구간 플래그.

⚠️ 의미 주의 (semantic caveat):
  confidence 는 현재 종합 score 와 동일하다(0~100, 높을수록 매수 확신).
  SELL/STRONG_SELL 은 **score 가 낮을수록 강한 확신**이므로, confidence 를
  그대로 "적중확률"로 보면 매도측이 구조적으로 과소평가된다. 따라서 본 리포트는
  반드시 **시그널별 분해**를 함께 본다(전체 confidence 캘리브레이션은 매수측에만 직관적).
  방향성 확신(conviction) 재매핑은 3단계(가중치 재학습)에서 다룬다.

표본 게이트:
  채점 표본이 --min-samples(기본 30) 미만이면 "신뢰 낮음" 경고 후 집계는 출력하되
  exit code 2 로 끝낸다(자동화에서 미성숙 표본 차단용). --force 로 무시 가능.

확장 지점(현재 hit_1d 만 존재):
  ret_5d 컬럼은 있으나 hit_5d 판정은 아직 없음. HORIZONS 에 5d/20d 를 추가하고
  score_signals 가 hit_5d/hit_20d 를 채우면 다지평 보정으로 자연 확장된다.

사용법:
  python scripts/calibration_report.py                 # 콘솔 리포트
  python scripts/calibration_report.py --by-sector     # 섹터별 분해 추가
  python scripts/calibration_report.py --json out.json # JSON 덤프
  python scripts/calibration_report.py --bins 5        # 5구간(0-20-..) 곡선
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

# Windows cp949 콘솔에서 한글·이모지 출력 보장
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from sqlalchemy import select  # noqa: E402

import db as apollo_db  # noqa: E402
import models  # noqa: E402

# 시그널을 방향성 그룹으로. confidence-as-prob 직관이 성립하는 건 BUY 측뿐.
BUY_SIGNALS = {"BUY", "STRONG_BUY"}
SELL_SIGNALS = {"SELL", "STRONG_SELL"}

DEFAULT_MIN_SAMPLES = 30
OVERCONFIDENCE_GAP = 0.10  # 갭 > 10%p 이고 표본 충분하면 과신 플래그
MIN_BIN_SAMPLES = 5        # 구간별 신뢰 가능 최소 표본


def _fetch_scored(session):
    """채점 완료(scored_at IS NOT NULL) 행을 dict 리스트로."""
    rows = session.execute(
        select(
            models.SignalOutcome.signal,
            models.SignalOutcome.confidence,
            models.SignalOutcome.score,
            models.SignalOutcome.sector,
            models.SignalOutcome.hit_1d,
            models.SignalOutcome.ret_1d,
            models.SignalOutcome.alpha_1d,
        ).where(models.SignalOutcome.scored_at.is_not(None))
    ).all()
    out = []
    for sig, conf, score, sector, hit, ret, alpha in rows:
        if hit is None or conf is None:
            continue  # 보정에는 예측확률·실현결과 둘 다 필요
        out.append({
            "signal": (sig or "").upper(),
            "confidence": float(conf),
            "score": None if score is None else float(score),
            "sector": sector,
            "hit": 1 if hit else 0,
            "ret_1d": None if ret is None else float(ret),
            "alpha_1d": None if alpha is None else float(alpha),
        })
    return out


def _brier(samples) -> float | None:
    """Brier score = mean((conf/100 − hit)^2)."""
    if not samples:
        return None
    return sum((s["confidence"] / 100.0 - s["hit"]) ** 2 for s in samples) / len(samples)


def _reliability_bins(samples, n_bins: int):
    """confidence(0~100)를 n_bins 균등구간으로 나눠 보정 통계 산출."""
    width = 100.0 / n_bins
    bins = []
    for i in range(n_bins):
        lo, hi = i * width, (i + 1) * width
        # 마지막 구간은 상한 포함(100 포함)
        if i == n_bins - 1:
            members = [s for s in samples if lo <= s["confidence"] <= hi]
        else:
            members = [s for s in samples if lo <= s["confidence"] < hi]
        n = len(members)
        if n == 0:
            bins.append({"lo": lo, "hi": hi, "n": 0, "pred": None,
                         "observed": None, "gap": None, "overconfident": False})
            continue
        pred = sum(m["confidence"] for m in members) / n / 100.0
        observed = sum(m["hit"] for m in members) / n
        gap = pred - observed
        bins.append({
            "lo": lo, "hi": hi, "n": n,
            "pred": pred, "observed": observed, "gap": gap,
            "overconfident": bool(n >= MIN_BIN_SAMPLES and gap > OVERCONFIDENCE_GAP),
        })
    return bins


def _ece(bins, total: int) -> float | None:
    """Expected Calibration Error — 표본 가중 평균 |예측−실현|."""
    if not total:
        return None
    return sum((b["n"] / total) * abs(b["gap"]) for b in bins if b["n"] and b["gap"] is not None)


def _summarize(samples):
    """한 그룹의 표본 요약: n, 적중률, Brier, 평균 ret/alpha."""
    n = len(samples)
    if n == 0:
        return {"n": 0, "hit_rate": None, "brier": None, "mean_ret": None, "mean_alpha": None}
    hit_rate = sum(s["hit"] for s in samples) / n
    rets = [s["ret_1d"] for s in samples if s["ret_1d"] is not None]
    alphas = [s["alpha_1d"] for s in samples if s["alpha_1d"] is not None]
    return {
        "n": n,
        "hit_rate": hit_rate,
        "brier": _brier(samples),
        "mean_ret": (sum(rets) / len(rets)) if rets else None,
        "mean_alpha": (sum(alphas) / len(alphas)) if alphas else None,
    }


def build_report(samples, n_bins: int, by_sector: bool):
    total = len(samples)
    bins = _reliability_bins(samples, n_bins)
    report = {
        "total_scored": total,
        "overall": {**_summarize(samples), "ece": _ece(bins, total)},
        "reliability_bins": bins,
        "by_signal": {},
        "alpha_coverage": sum(1 for s in samples if s["alpha_1d"] is not None),
    }
    for label, group in (
        ("BUY_side", [s for s in samples if s["signal"] in BUY_SIGNALS]),
        ("SELL_side", [s for s in samples if s["signal"] in SELL_SIGNALS]),
        ("HOLD", [s for s in samples if s["signal"] == "HOLD"]),
    ):
        report["by_signal"][label] = _summarize(group)
    # 개별 시그널 5종도
    for sig in ("STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL"):
        report["by_signal"][sig] = _summarize([s for s in samples if s["signal"] == sig])
    if by_sector:
        sectors = {}
        for s in samples:
            sectors.setdefault(s["sector"] or "(미상)", []).append(s)
        report["by_sector"] = {k: _summarize(v) for k, v in sorted(sectors.items())}
    return report


def _pct(x):
    return "  N/A " if x is None else f"{x * 100:5.1f}%"


def _f3(x):
    return " N/A " if x is None else f"{x:.3f}"


def print_report(report, min_samples: int):
    total = report["total_scored"]
    print("=" * 64)
    print("  AI 시그널 확신도 보정 리포트 (2단계)")
    print("=" * 64)
    low = total < min_samples
    flag = "  ⚠️ 신뢰 낮음 (표본 부족)" if low else ""
    print(f"채점 표본: {total}  (게이트 {min_samples}){flag}")
    print(f"alpha 적용 표본: {report['alpha_coverage']}/{total} "
          f"(나머지는 raw 등락 기준 hit)")

    ov = report["overall"]
    print("\n[전체]")
    print(f"  적중률 {_pct(ov['hit_rate'])}   Brier {_f3(ov['brier'])} "
          f"(0=완벽·0.25=무정보)   ECE {_f3(ov['ece'])}")
    print(f"  평균 ret_1d {_pct(ov['mean_ret'])}   평균 alpha_1d {_pct(ov['mean_alpha'])}")

    print("\n[신뢰도 곡선 — confidence 구간별]")
    print("  구간          표본   예측확률  실현적중   갭(과신+)")
    for b in report["reliability_bins"]:
        rng = f"{int(b['lo']):>3}-{int(b['hi']):<3}"
        mark = "  ◀ 과신" if b["overconfident"] else ""
        if b["n"] == 0:
            print(f"  {rng}        {b['n']:>4}      -        -        -")
        else:
            gap_s = f"{b['gap'] * 100:+5.1f}%p"
            print(f"  {rng}        {b['n']:>4}    {_pct(b['pred'])}   "
                  f"{_pct(b['observed'])}   {gap_s}{mark}")

    print("\n[시그널별]  (confidence-as-prob 는 BUY 측만 직관적 — 상단 caveat 참고)")
    print("  그룹            표본   적중률   Brier    평균alpha")
    for label in ("BUY_side", "SELL_side", "HOLD",
                  "STRONG_BUY", "BUY", "SELL", "STRONG_SELL"):
        s = report["by_signal"].get(label)
        if not s or s["n"] == 0:
            continue
        print(f"  {label:<14} {s['n']:>4}   {_pct(s['hit_rate'])}  "
              f"{_f3(s['brier'])}   {_pct(s['mean_alpha'])}")

    if "by_sector" in report:
        print("\n[섹터별]")
        print("  섹터                  표본   적중률   평균alpha")
        for sec, s in report["by_sector"].items():
            if s["n"] == 0:
                continue
            print(f"  {sec:<20} {s['n']:>4}   {_pct(s['hit_rate'])}  {_pct(s['mean_alpha'])}")

    flags = [b for b in report["reliability_bins"] if b["overconfident"]]
    if flags:
        print("\n[과신 구간 — 재매핑 후보]")
        for b in flags:
            print(f"  confidence {int(b['lo'])}-{int(b['hi'])}: "
                  f"예측 {_pct(b['pred'])} → 실현 {_pct(b['observed'])} "
                  f"(갭 {b['gap'] * 100:+.1f}%p, n={b['n']})")
    print("=" * 64)
    if low:
        print("표본 30 미만 — 본 수치는 참고용. 표본 축적 후 재실행 권장.")


def main():
    ap = argparse.ArgumentParser(description="AI 시그널 확신도 보정 리포트 (2단계)")
    ap.add_argument("--min-samples", type=int, default=DEFAULT_MIN_SAMPLES,
                    help=f"신뢰 게이트 표본수 (기본 {DEFAULT_MIN_SAMPLES})")
    ap.add_argument("--bins", type=int, default=10, help="신뢰도 곡선 구간 수 (기본 10)")
    ap.add_argument("--by-sector", action="store_true", help="섹터별 분해 추가")
    ap.add_argument("--json", type=str, default=None, help="리포트를 JSON 파일로 덤프")
    ap.add_argument("--force", action="store_true",
                    help="표본 부족이어도 exit 0 (게이트 무시)")
    args = ap.parse_args()

    session = apollo_db.get_session_factory()()
    try:
        samples = _fetch_scored(session)
    finally:
        session.close()

    report = build_report(samples, n_bins=max(1, args.bins), by_sector=args.by_sector)
    print_report(report, args.min_samples)

    if args.json:
        Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON 덤프: {args.json}")

    low = report["total_scored"] < args.min_samples
    if low and not args.force:
        sys.exit(2)


if __name__ == "__main__":
    main()
