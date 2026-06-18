"""유사 국면 엔진 point-in-time 백테스트 — 판별력·캘리브레이션 정직 측정.

설계(미래 참조 차단):
  각 과거 시점 t 에서 closes[:t+1] 만으로 엔진 예측을 만들고, t 이후 실제 경로로 채점.
  - 국면 특징·k-NN 후보·선도달 표본 전부 t 이전 데이터만 사용(_regime_features 보장).
  - 닷컴 풀(1995~2002)은 한국 어떤 날짜보다도 과거 → 누수 없음.
  - PER 백분위(7차원)는 pykrx 일별 PER as-of t (직전 사업연도 EPS 기준 → t 시점 가용).

채점 대상 (엔진의 실제 falsifiable 출력):
  A) 선도달:  예측 reachTargetPct vs 실제(목표 +8% 가 손절 -5% 보다 먼저 닿았나, 60일 한도)
  B) 방향:    예측 continueUpPct vs 실제(t+20 종가 > t 종가)
  각 예측기(1차원/6차원/7차원/닷컴)별로 AUC(순위 판별력)+캘리브레이션(10분위 실제율) 산출.

표본: DB daily_prices 보유 종목 × 시점(겹침 줄이려 stride 간격). 결과 CSV + 요약.
실행: python scripts\backtest_regime_engine.py [--with-per] [--stocks N] [--stride K]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\stock\backend")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import target_engine as te  # noqa: E402

OUT = Path(r"D:\STOCK DATA-US\backtests")
HORIZON = 60        # 선도달 검사 한도(거래일)
UP, DN = 0.08, 0.05  # 목표/손절폭 (엔진 기본 가드와 동일 스케일)
FWD = 20            # 방향 라벨 지평


def first_passage_actual(bars, t):
    """t 시점 기준 실제 선도달: +UP 먼저=1 / -DN 먼저=0 / 미결판=None."""
    c0 = bars[t]["close"]
    tgt, stp = c0 * (1 + UP), c0 * (1 - DN)
    for j in range(t + 1, min(t + HORIZON, len(bars))):
        if bars[j]["high"] >= tgt:
            return 1
        if bars[j]["low"] <= stp:
            return 0
    return None


def sample_stock(bars, per_map, stride):
    """한 종목의 여러 시점에서 (예측, 실제) 샘플 생성."""
    n = len(bars)
    out = []
    # 평가 시점: 충분한 과거(>=150) + 충분한 미래(>=HORIZON) 확보 구간
    for t in range(160, n - HORIZON - 1, stride):
        sub = bars[: t + 1]
        # 실제 라벨
        fp_actual = first_passage_actual(bars, t)
        dir_actual = 1 if bars[t + FWD]["close"] > bars[t]["close"] else 0
        # 1차원 (기존 방식)
        p1 = te._first_passage_prob(sub, UP, DN)
        pred1_reach = p1.get("reachTargetPct")
        pred1_up = p1.get("continueUpPct")
        # 6/7차원 (per_map 있으면 7차원 자동)
        p = te._similar_regime_prob(sub, UP, DN, per_map=per_map)
        if "error" in p:
            continue
        dims = len(p.get("dimensions", []))
        dc = p.get("dotcomAnalogs", {})
        out.append({
            "t_idx": t, "date": bars[t]["date"], "dims": dims,
            "fp_actual": fp_actual, "dir_actual": dir_actual,
            "pred1_reach": pred1_reach, "pred1_up": pred1_up,
            "predN_reach": p.get("reachTargetPct"), "predN_up": p.get("continueUpPct"),
            "pred_dc_up": dc.get("continueUpPct") if "error" not in dc else None,
            "valDimUsed": p.get("valuationDim", {}).get("used", False),
        })
    return out


def auc(preds, labels):
    """순위 판별력 (Mann-Whitney): 양성 예측치 > 음성 예측치 쌍 비율. 0.5=무작위."""
    pos = [p for p, l in zip(preds, labels) if l == 1 and p is not None]
    neg = [p for p, l in zip(preds, labels) if l == 0 and p is not None]
    if not pos or not neg:
        return None, 0, 0
    gt = sum(1 for a in pos for b in neg if a > b)
    eq = sum(1 for a in pos for b in neg if a == b)
    return (gt + 0.5 * eq) / (len(pos) * len(neg)), len(pos), len(neg)


def calibration(preds, labels, bins=5):
    """예측 분위별 실제 양성률 — 예측이 클수록 실제율이 오르면 캘리브레이션 양호."""
    pairs = sorted((p, l) for p, l in zip(preds, labels) if p is not None and l is not None)
    if len(pairs) < bins * 4:
        return []
    out = []
    step = len(pairs) // bins
    for b in range(bins):
        seg = pairs[b * step: (b + 1) * step] if b < bins - 1 else pairs[b * step:]
        if not seg:
            continue
        avg_pred = sum(p for p, _ in seg) / len(seg)
        act = sum(l for _, l in seg) / len(seg) * 100
        out.append((round(avg_pred, 1), round(act, 1), len(seg)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-per", action="store_true", help="7차원(PER) 포함 — pykrx 조회")
    ap.add_argument("--stocks", type=int, default=60)
    ap.add_argument("--stride", type=int, default=10)
    ap.add_argument("--min-bars", type=int, default=300)
    args = ap.parse_args()

    import db
    import models
    from sqlalchemy import select, func

    s = db.get_session_factory()()
    counts = s.execute(select(models.DailyPrice.stock_code, func.count())
                       .group_by(models.DailyPrice.stock_code)).all()
    codes = [c for c, n in counts if n >= args.min_bars][: args.stocks]
    print(f"백테스트 종목 {len(codes)}개 / stride {args.stride} / "
          f"{'7차원(PER)' if args.with_per else '6차원'} 모드")

    all_samples = []
    for k, code in enumerate(codes, 1):
        rows = s.execute(select(models.DailyPrice)
                         .where(models.DailyPrice.stock_code == code)
                         .order_by(models.DailyPrice.trading_date)).scalars().all()
        bars = [{"date": r.trading_date.strftime("%Y%m%d"), "close": float(r.close_price),
                 "high": float(r.high_price), "low": float(r.low_price),
                 "volume": float(r.volume or 0)} for r in rows]
        per_map = None
        if args.with_per:
            per_map = te._fetch_per_series(code, bars[0]["date"], bars[-1]["date"])
            time.sleep(0.25)
        try:
            all_samples.extend(sample_stock(bars, per_map, args.stride))
        except Exception as exc:  # noqa: BLE001
            print(f"  {code} 스킵: {type(exc).__name__}")
        if k % 10 == 0:
            print(f"  진행 {k}/{len(codes)} — 누적 표본 {len(all_samples)}")
    s.close()

    OUT.mkdir(parents=True, exist_ok=True)
    import csv as _csv
    with open(OUT / "regime_backtest_samples.csv", "w", encoding="utf-8", newline="") as f:
        if all_samples:
            w = _csv.DictWriter(f, fieldnames=list(all_samples[0].keys()))
            w.writeheader()
            w.writerows(all_samples)

    n = len(all_samples)
    dims_used = sorted({r["dims"] for r in all_samples})
    val_n = sum(1 for r in all_samples if r["valDimUsed"])
    print(f"\n총 표본 {n}개 (차원 {dims_used}, 7차원 적용 {val_n}개)")

    # ── A) 선도달 채점 (미결판 제외) ─────────────────────────────────────────
    fp = [r for r in all_samples if r["fp_actual"] is not None]
    base = sum(r["fp_actual"] for r in fp) / len(fp) * 100 if fp else 0
    print(f"\n[A] 선도달 (+{UP*100:.0f}% vs -{DN*100:.0f}%, {HORIZON}일) — "
          f"결판 표본 {len(fp)} / 실제 목표선도달률 {base:.1f}%")
    for name, key in [("1차원 예측", "pred1_reach"), ("N차원 예측", "predN_reach")]:
        a, np_, nn = auc([r[key] for r in fp], [r["fp_actual"] for r in fp])
        if a is not None:
            print(f"  {name}: AUC {a:.3f} (목표달성{np_}/미달{nn})")
            cal = calibration([r[key] for r in fp], [r["fp_actual"] for r in fp])
            if cal:
                print("     캘리브레이션(예측→실제%): " +
                      " | ".join(f"{p}→{a_}" for p, a_, _ in cal))

    # ── B) 방향 채점 ────────────────────────────────────────────────────────
    labels = [r["dir_actual"] for r in all_samples]
    up_base = sum(labels) / len(labels) * 100
    print(f"\n[B] 20일 방향 — 표본 {n} / 실제 상승률 {up_base:.1f}%")
    for name, key in [("1차원", "pred1_up"), ("N차원", "predN_up"), ("닷컴대조", "pred_dc_up")]:
        preds = [r[key] for r in all_samples]
        a, np_, nn = auc(preds, labels)
        cov = sum(1 for p in preds if p is not None) / n * 100
        if a is not None:
            print(f"  {name}: AUC {a:.3f} | 커버리지 {cov:.0f}%")
        else:
            print(f"  {name}: 측정불가 (커버리지 {cov:.0f}%)")

    print(f"\n결과 저장: {OUT / 'regime_backtest_samples.csv'}")
    print("주: AUC 0.5=무작위, >0.55=약한 판별력, >0.6=유의미. "
          "단일 시장 국면 한정 — 여러 해 데이터 쌓이면 재실행 권장.")


if __name__ == "__main__":
    main()
