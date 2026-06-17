"""retrain_weights.py

AI composite 가중치 재학습 — 3단계 (signal_outcomes 집계).

현행 composite.score 는 5요소 **균등 20%** 휴리스틱이다(stock_compass._composite_score).
채점 완료된 예측의 5요소 점수(features)를 X, **익일 alpha>0**(없으면 ret_1d>0)을 y 로
로지스틱 회귀를 학습해, 데이터 기반 가중치와 시그널 임계값 재조정안을 제안한다.

  features (X): 섹터 강도 · MTF 정렬 · 상승지속확률 · 공매도 수급 · 손익비   (각 0~100)
  target (y) : alpha_1d > τ  (alpha 없으면 ret_1d > τ),  τ = --target-threshold (기본 0.0)

학습:
  · 표준화(z-score, train 통계) → numpy 경사하강 로지스틱 회귀(L2 정규화). sklearn 불요.
  · **시간순 분할**(predicted_at 오름차순 앞 train_frac, 뒤 holdout) — 룩어헤드 방지.
  · 평가: 정확도 · AUC(Mann-Whitney) · log-loss, train/holdout 양쪽.

산출:
  · 학습 가중치 — |표준화 계수| 정규화 → 요소별 기여도(%) vs 현행 균등 20%.
    계수 부호도 표기(음수 = 점수가 높을수록 익일 하락 쪽 → 요소 재검토 신호).
  · 임계값 재조정 — holdout 예측확률 분포에서 분위수 기반 BUY/HOLD/SELL 컷 제안.
    (현행: composite score 80/70/55/40 → STRONG_BUY/BUY/HOLD/SELL/STRONG_SELL)

표본 게이트:
  학습 표본(features+scored 모두 존재)이 --min-samples(기본 100) 미만이면
  "신뢰 낮음" 경고 + exit 2. 5요소 회귀는 요소당 10~20 사건 권장 → 최소 100.
  --force 로 무시. **이 단계는 표본이 충분히 쌓인 뒤 실행**한다.

⚠️ 제안만 한다 — 가중치/임계값을 코드에 자동 반영하지 않는다.
   결과를 검토 후 _composite_score / _signal_from_score 를 수동 수정하거나,
   별도 설정으로 주입하는 것은 후속 작업.

사용법:
  python scripts/retrain_weights.py
  python scripts/retrain_weights.py --target-threshold 0.003   # hit 기준과 동일 τ
  python scripts/retrain_weights.py --json out.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

import numpy as np  # noqa: E402
from sqlalchemy import select  # noqa: E402

import db as apollo_db  # noqa: E402
import models  # noqa: E402

# composite 5요소 — _composite_score(parts) 키와 순서 일치
FEATURES = ["섹터 강도", "MTF 정렬", "상승지속확률", "공매도 수급", "손익비"]
NEUTRAL = 50.0          # 결측 요소 중립 대체값 (composite 기본값과 동일)
DEFAULT_MIN_SAMPLES = 100
TRAIN_FRAC = 0.7
L2 = 1.0                # 정규화 강도
LR = 0.1                # 학습률
EPOCHS = 3000


def _fetch(session, tau: float):
    """features+scored 모두 있는 행을 predicted_at 오름차순으로 (X, y, meta)."""
    rows = session.execute(
        select(
            models.SignalOutcome.predicted_at,
            models.SignalOutcome.features,
            models.SignalOutcome.alpha_1d,
            models.SignalOutcome.ret_1d,
        )
        .where(models.SignalOutcome.scored_at.is_not(None))
        .where(models.SignalOutcome.features.is_not(None))
        .order_by(models.SignalOutcome.predicted_at.asc())
    ).all()
    X, y, used_alpha = [], [], 0
    for _pred_at, feats, alpha, ret in rows:
        if not isinstance(feats, dict):
            continue
        row = [float(feats.get(k, NEUTRAL)) for k in FEATURES]
        # target: alpha 우선, 없으면 raw ret
        base = alpha if alpha is not None else ret
        if base is None:
            continue
        if alpha is not None:
            used_alpha += 1
        X.append(row)
        y.append(1 if float(base) > tau else 0)
    return np.array(X, dtype=float), np.array(y, dtype=float), used_alpha


def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def _train_logreg(Xtr, ytr):
    """표준화 + L2 경사하강 로지스틱 회귀. (w, b, mu, sd) 반환."""
    mu = Xtr.mean(axis=0)
    sd = Xtr.std(axis=0)
    sd[sd == 0] = 1.0
    Z = (Xtr - mu) / sd
    n, d = Z.shape
    w = np.zeros(d)
    b = 0.0
    for _ in range(EPOCHS):
        p = _sigmoid(Z @ w + b)
        err = p - ytr
        gw = Z.T @ err / n + (L2 / n) * w
        gb = err.mean()
        w -= LR * gw
        b -= LR * gb
    return w, b, mu, sd


def _predict(X, w, b, mu, sd):
    return _sigmoid(((X - mu) / sd) @ w + b)


def _auc(y, p):
    """Mann-Whitney AUC. 한 클래스만 있으면 None."""
    pos = p[y == 1]
    neg = p[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return None
    order = np.argsort(p)
    ranks = np.empty(len(p), dtype=float)
    ranks[order] = np.arange(1, len(p) + 1)
    # 동점 평균 순위 보정
    _, inv, cnt = np.unique(p, return_inverse=True, return_counts=True)
    avg = np.zeros(len(cnt))
    cum = np.cumsum(cnt)
    start = np.concatenate(([0], cum[:-1]))
    for i in range(len(cnt)):
        avg[i] = (start[i] + 1 + cum[i]) / 2.0
    ranks = avg[inv]
    r_pos = ranks[y == 1].sum()
    n_pos, n_neg = len(pos), len(neg)
    return (r_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def _logloss(y, p):
    eps = 1e-12
    p = np.clip(p, eps, 1 - eps)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def _metrics(y, p):
    if len(y) == 0:
        return {"n": 0, "accuracy": None, "auc": None, "logloss": None, "base_rate": None}
    acc = float(((p >= 0.5).astype(float) == y).mean())
    return {"n": int(len(y)), "accuracy": acc, "auc": _auc(y, p),
            "logloss": _logloss(y, p), "base_rate": float(y.mean())}


def build_report(X, y, used_alpha, tau):
    n = len(y)
    out = {"n_total": n, "alpha_target_rows": used_alpha,
           "target_threshold": tau, "features": FEATURES}
    if n == 0:
        return out

    cut = max(1, int(n * TRAIN_FRAC))
    Xtr, ytr = X[:cut], y[:cut]
    Xho, yho = X[cut:], y[cut:]
    out["n_train"], out["n_holdout"] = len(ytr), len(yho)

    # 한 클래스만 있으면 학습 불가
    if len(np.unique(ytr)) < 2:
        out["error"] = "train target 단일 클래스 — 표본/τ 재검토"
        return out

    w, b, mu, sd = _train_logreg(Xtr, ytr)
    out["coef_standardized"] = {FEATURES[i]: float(w[i]) for i in range(len(FEATURES))}
    out["intercept"] = float(b)

    # 가중치 = |표준화 계수| 정규화 (현행 균등 20% 대비)
    absw = np.abs(w)
    tot = absw.sum() or 1.0
    out["learned_weights_pct"] = {
        FEATURES[i]: {"weight_pct": round(absw[i] / tot * 100, 1),
                      "direction": "정(+)" if w[i] >= 0 else "역(−)",
                      "current_pct": 20.0}
        for i in range(len(FEATURES))
    }

    out["train"] = _metrics(ytr, _predict(Xtr, w, b, mu, sd))
    out["holdout"] = _metrics(yho, _predict(Xho, w, b, mu, sd)) if len(yho) else None

    # 임계값 재조정 — holdout(없으면 train) 예측확률 분위수
    pe = _predict(Xho if len(yho) else Xtr, w, b, mu, sd)
    qs = {f"p{int(q*100)}": float(np.quantile(pe, q)) for q in (0.2, 0.4, 0.55, 0.7, 0.8)}
    out["prob_quantiles"] = qs
    out["threshold_suggestion"] = {
        "STRONG_BUY": round(qs["p80"], 3),
        "BUY": round(qs["p70"], 3),
        "HOLD": round(qs["p55"], 3),
        "SELL": round(qs["p40"], 3),
        "note": "예측 P(익일 alpha>0) 분위수 기반. 현행 score 80/70/55/40 컷의 데이터 기반 대체 후보.",
    }
    return out


def _f(x, nd=3):
    return " N/A " if x is None else f"{x:.{nd}f}"


def print_report(r, min_samples):
    print("=" * 64)
    print("  AI composite 가중치 재학습 리포트 (3단계)")
    print("=" * 64)
    n = r["n_total"]
    low = n < min_samples
    flag = "  ⚠️ 신뢰 낮음 (표본 부족)" if low else ""
    print(f"학습 표본(features+scored): {n}  (게이트 {min_samples}){flag}")
    print(f"alpha 기반 target: {r['alpha_target_rows']}/{n} "
          f"(나머지 raw ret)   τ={r['target_threshold']}")

    if n == 0:
        print("\n표본 0 — features 적재된 채점 행이 아직 없음.")
        print("=" * 64)
        return
    if "error" in r:
        print(f"\n[중단] {r['error']}")
        print("=" * 64)
        return

    print(f"분할: train {r['n_train']} / holdout {r['n_holdout']} (시간순)")

    print("\n[학습 가중치 — |표준화 계수| 정규화]")
    print("  요소            학습%   현행%   부호")
    for k in FEATURES:
        lw = r["learned_weights_pct"][k]
        print(f"  {k:<12} {lw['weight_pct']:>6.1f}  {lw['current_pct']:>6.1f}   {lw['direction']}")

    print("\n[성능]")
    for split in ("train", "holdout"):
        m = r.get(split)
        if not m:
            continue
        print(f"  {split:<8} n={m['n']:>4}  정확도 {_f(m['accuracy'])}  "
              f"AUC {_f(m['auc'])}  logloss {_f(m['logloss'])}  "
              f"기저율 {_f(m['base_rate'])}")
    print("  (AUC 0.5=무정보·0.7+ 유의미 / logloss 낮을수록·정확도>기저율이어야 학습효과)")

    ts = r["threshold_suggestion"]
    print("\n[임계값 재조정 제안 — P(익일 alpha>0) 기준]")
    for k in ("STRONG_BUY", "BUY", "HOLD", "SELL"):
        print(f"  {k:<12} P ≥ {ts[k]}")
    print(f"  ※ {ts['note']}")
    print("=" * 64)
    print("⚠️ 제안만 — _composite_score/_signal_from_score 자동 변경 안 함. 검토 후 수동 반영.")
    if low:
        print("표본 부족 — 본 결과는 참고용. 충분히 축적 후 재학습 권장.")


def main():
    ap = argparse.ArgumentParser(description="AI composite 가중치 재학습 (3단계)")
    ap.add_argument("--min-samples", type=int, default=DEFAULT_MIN_SAMPLES)
    ap.add_argument("--target-threshold", type=float, default=0.0,
                    help="target = (alpha 또는 ret) > τ (기본 0.0)")
    ap.add_argument("--json", type=str, default=None)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    session = apollo_db.get_session_factory()()
    try:
        X, y, used_alpha = _fetch(session, args.target_threshold)
    finally:
        session.close()

    report = build_report(X, y, used_alpha, args.target_threshold)
    print_report(report, args.min_samples)

    if args.json:
        Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON 덤프: {args.json}")

    if report["n_total"] < args.min_samples and not args.force:
        sys.exit(2)


if __name__ == "__main__":
    main()
