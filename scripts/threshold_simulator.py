"""threshold_simulator.py

시그널 임계값 시뮬레이터 — HOLD/매수/매도 컷 재정의 도구 (2단계 보조).

채점된 signal_outcomes(score, alpha_1d/ret_1d)로 **임의 컷셋을 재매핑**해
구간별 적중률·평균alpha·시그널 분포를 산출한다. 같은 점수에 다른 임계값을
적용했을 때 결과가 어떻게 달라지는지 반사실(counterfactual)로 본다.

⚠️ 핵심 한계: 임계값을 같은 데이터로 고르면 과적합이다. 그래서 **시간분할**로
   in-sample(train)과 out-of-sample(holdout)을 분리 출력한다 — holdout 에서도
   유지되는 개선만 신뢰. 또 단일 장세(예: 전량 하락) 표본에서 고른 컷은 다른
   국면에서 깨질 수 있으므로, 표본의 상승/하락 비율(regime skew)을 함께 표시한다.
   → 장세 다양성(특히 상승·보합 표본) 확보 전에는 '확정'이 아니라 '관찰'용.

컷셋 정의: [STRONG_BUY하한, BUY하한, HOLD하한, SELL하한]  (내림차순, 0~100)
  score≥c0→STRONG_BUY / ≥c1→BUY / ≥c2→HOLD / ≥c3→SELL / 그 미만→STRONG_SELL
  현행(stock_compass._signal_from_score): 80,70,55,40

적중 규칙(score_signals 와 동일): basis = alpha 우선·없으면 ret.
  BUY/STRONG_BUY → basis>+0.003 / SELL/STRONG_SELL → basis<−0.003 / HOLD → |basis|≤0.003

사용법:
  python scripts/threshold_simulator.py                      # 현행 컷 평가(+시간분할)
  python scripts/threshold_simulator.py --cuts 80,70,60,45   # 후보 컷 평가
  python scripts/threshold_simulator.py --sweep              # HOLD 경계 격자 탐색→holdout 랭킹
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from sqlalchemy import select  # noqa: E402

import db as apollo_db  # noqa: E402
import models  # noqa: E402

HIT_THRESHOLD = 0.003
CURRENT_CUTS = (80.0, 70.0, 55.0, 40.0)
SIGNAL_ORDER = ["STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL"]
MIN_BUCKET = 30


def _fetch(session):
    rows = session.execute(
        select(models.SignalOutcome.predicted_at, models.SignalOutcome.score,
               models.SignalOutcome.alpha_1d, models.SignalOutcome.ret_1d)
        .where(models.SignalOutcome.scored_at.is_not(None))
        .order_by(models.SignalOutcome.predicted_at.asc())
    ).all()
    out = []
    for _p, score, alpha, ret in rows:
        if score is None:
            continue
        basis = alpha if alpha is not None else ret
        if basis is None:
            continue
        out.append({"score": float(score), "basis": float(basis)})
    return out


def _signal_of(score, cuts):
    c0, c1, c2, c3 = cuts
    if score >= c0:
        return "STRONG_BUY"
    if score >= c1:
        return "BUY"
    if score >= c2:
        return "HOLD"
    if score >= c3:
        return "SELL"
    return "STRONG_SELL"


def _hit(signal, basis):
    if signal in ("BUY", "STRONG_BUY"):
        return basis > HIT_THRESHOLD
    if signal in ("SELL", "STRONG_SELL"):
        return basis < -HIT_THRESHOLD
    return abs(basis) <= HIT_THRESHOLD  # HOLD


def evaluate(samples, cuts):
    """컷셋 적용 결과: 전체 정확도 + 시그널별 [n, 적중률, 평균basis]."""
    buckets = {s: {"n": 0, "hits": 0, "basis_sum": 0.0} for s in SIGNAL_ORDER}
    hits = 0
    for x in samples:
        sig = _signal_of(x["score"], cuts)
        h = _hit(sig, x["basis"])
        b = buckets[sig]
        b["n"] += 1
        b["basis_sum"] += x["basis"]
        if h:
            b["hits"] += 1
            hits += 1
    n = len(samples)
    by = {}
    for s in SIGNAL_ORDER:
        bk = buckets[s]
        by[s] = {
            "n": bk["n"],
            "hit_rate": (bk["hits"] / bk["n"]) if bk["n"] else None,
            "avg_basis": (bk["basis_sum"] / bk["n"]) if bk["n"] else None,
        }
    return {"n": n, "accuracy": (hits / n) if n else None, "by_signal": by}


def _split(samples, frac):
    cut = max(1, int(len(samples) * frac))
    return samples[:cut], samples[cut:]


def _regime_skew(samples):
    up = sum(1 for x in samples if x["basis"] > HIT_THRESHOLD)
    dn = sum(1 for x in samples if x["basis"] < -HIT_THRESHOLD)
    fl = len(samples) - up - dn
    return up, fl, dn


def _pct(x):
    return "  N/A" if x is None else f"{x * 100:5.1f}%"


def _print_eval(title, ev):
    print(f"\n[{title}]  표본 {ev['n']}  전체정확도 {_pct(ev['accuracy'])}")
    print("  시그널        n    적중률   평균basis")
    for s in SIGNAL_ORDER:
        bk = ev["by_signal"][s]
        if bk["n"] == 0:
            continue
        warn = "  ⚠️<30" if bk["n"] < MIN_BUCKET else ""
        print(f"  {s:<12} {bk['n']:>3}   {_pct(bk['hit_rate'])}  "
              f"{_pct(bk['avg_basis'])}{warn}")


def run_single(samples, cuts, frac):
    up, fl, dn = _regime_skew(samples)
    print("=" * 60)
    print("  시그널 임계값 시뮬레이터")
    print("=" * 60)
    print(f"컷셋: STRONG_BUY≥{cuts[0]} BUY≥{cuts[1]} HOLD≥{cuts[2]} SELL≥{cuts[3]}")
    print(f"표본 장세: 상승 {up} / 보합 {fl} / 하락 {dn}  "
          f"(상승비율 {up/len(samples)*100:.0f}% — 편중 시 컷 신뢰 낮음)")
    _print_eval("전체", evaluate(samples, cuts))
    tr, ho = _split(samples, frac)
    _print_eval(f"in-sample (앞 {len(tr)})", evaluate(tr, cuts))
    if ho:
        _print_eval(f"out-of-sample (뒤 {len(ho)})", evaluate(ho, cuts))
    print("=" * 60)


def run_sweep(samples, frac):
    """HOLD 경계(c2=SELL/HOLD, c1=HOLD/BUY) 격자 탐색 → holdout 기준 랭킹."""
    tr, ho = _split(samples, frac)
    eval_set = ho if ho else tr
    label = "holdout" if ho else "in-sample(holdout 없음)"
    print("=" * 60)
    print(f"  HOLD 경계 스윕 — {label} 기준 랭킹")
    print("=" * 60)
    up, fl, dn = _regime_skew(samples)
    print(f"표본 장세: 상승 {up} / 보합 {fl} / 하락 {dn}")
    results = []
    for c3 in (35, 40, 45):                      # SELL/STRONG_SELL 경계
        for c2 in range(45, 71, 5):              # SELL/HOLD 경계
            for c1 in range(c2 + 5, 76, 5):      # HOLD/BUY 경계
                cuts = (80.0, float(c1), float(c2), float(c3))
                ev = evaluate(eval_set, cuts)
                hold = ev["by_signal"]["HOLD"]
                results.append({
                    "cuts": (c1, c2, c3), "acc": ev["accuracy"],
                    "hold_n": hold["n"], "hold_hit": hold["hit_rate"],
                })
    # 전체정확도 우선, HOLD 표본 충분(>=10) 가산
    results.sort(key=lambda r: (-(r["acc"] or 0)))
    print("\n  순위  BUY≥/HOLD≥/SELL≥   전체정확도  HOLD n  HOLD적중")
    for i, r in enumerate(results[:12], 1):
        c1, c2, c3 = r["cuts"]
        print(f"  {i:>2}.   {c1:>3}/{c2:>3}/{c3:<3}        {_pct(r['acc'])}   "
              f"{r['hold_n']:>4}   {_pct(r['hold_hit'])}")
    cur = evaluate(eval_set, CURRENT_CUTS)
    print(f"\n  (현행 80/70/55/40 → 전체정확도 {_pct(cur['accuracy'])} "
          f"HOLD n={cur['by_signal']['HOLD']['n']} 적중 {_pct(cur['by_signal']['HOLD']['hit_rate'])})")
    print("=" * 60)
    print("⚠️ holdout 개선이 in-sample 과 일관될 때만, 그리고 상승장 표본이 섞인 뒤에만 확정.")


def main():
    ap = argparse.ArgumentParser(description="시그널 임계값 시뮬레이터")
    ap.add_argument("--cuts", type=str, default=None, help="콤마 4개: STRONG_BUY,BUY,HOLD,SELL 하한")
    ap.add_argument("--split", type=float, default=0.7, help="시간분할 train 비율(기본 0.7)")
    ap.add_argument("--sweep", action="store_true", help="HOLD 경계 격자 탐색")
    ap.add_argument("--min-samples", type=int, default=30)
    args = ap.parse_args()

    session = apollo_db.get_session_factory()()
    try:
        samples = _fetch(session)
    finally:
        session.close()

    if len(samples) < args.min_samples:
        print(f"채점 표본 {len(samples)} < {args.min_samples} — 신뢰 낮음. (참고용 출력)")
    if not samples:
        sys.exit(2)

    if args.sweep:
        run_sweep(samples, args.split)
    else:
        cuts = CURRENT_CUTS
        if args.cuts:
            parts = [float(x) for x in args.cuts.split(",")]
            if len(parts) != 4:
                print("--cuts 는 4개 값"); sys.exit(2)
            cuts = tuple(parts)
        run_single(samples, cuts, args.split)


if __name__ == "__main__":
    main()
