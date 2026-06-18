"""accuracy_report.py

AI 시그널 적중치 — 수치 대시보드 (CLI).

signal_outcomes 채점 완료분(scored_at NOT NULL)의 **예측 vs 실재** 적중률을
인증·서버 없이 즉시 숫자로 본다. /api/admin/signal-accuracy 와 동일 집계
(시그널별 · 확신도구간 0-50/50-70/70+ · 섹터별), 표본 30 미만은 "신뢰 낮음".

적중률 = hit_1d 평균 (alpha 우선·없으면 raw, score_signals 기준).
미채점(대기) 건수도 함께 표시 — 루프가 흐르고 있음을 보이게.

사용법:
  python scripts/accuracy_report.py
  python scripts/accuracy_report.py --json out.json
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

from sqlalchemy import func, select  # noqa: E402

import db as apollo_db  # noqa: E402
import models  # noqa: E402

MIN_SAMPLE = 30


def _conf_bucket(c):
    if c is None:
        return "unknown"
    return "0-50" if c < 50 else "50-70" if c < 70 else "70+"


def _new():
    return {"n": 0, "hits": 0, "retSum": 0.0, "retN": 0, "alphaSum": 0.0, "alphaN": 0}


def _acc(bucket, key, hit, ret, alpha):
    g = bucket.setdefault(key, _new())
    g["n"] += 1
    if hit:
        g["hits"] += 1
    if ret is not None:
        g["retSum"] += float(ret); g["retN"] += 1
    if alpha is not None:
        g["alphaSum"] += float(alpha); g["alphaN"] += 1


def _finalize(bucket):
    out = []
    for key, g in bucket.items():
        n = g["n"]
        out.append({
            "key": key, "samples": n, "hits": g["hits"],
            "hitRate": round(g["hits"] / n, 4) if n else None,
            "avgRet1d": round(g["retSum"] / g["retN"], 5) if g["retN"] else None,
            "avgAlpha1d": round(g["alphaSum"] / g["alphaN"], 5) if g["alphaN"] else None,
            "lowConfidence": n < MIN_SAMPLE,
        })
    out.sort(key=lambda x: -x["samples"])
    return out


def build(session):
    rows = session.execute(
        select(models.SignalOutcome.signal, models.SignalOutcome.confidence,
               models.SignalOutcome.sector, models.SignalOutcome.hit_1d,
               models.SignalOutcome.ret_1d, models.SignalOutcome.alpha_1d)
        .where(models.SignalOutcome.scored_at.is_not(None))
    ).all()
    pending = session.execute(
        select(func.count(models.SignalOutcome.id))
        .where(models.SignalOutcome.scored_at.is_(None))
    ).scalar_one_or_none() or 0

    by_signal, by_conf, by_sector = {}, {}, {}
    overall = {}
    for sig, conf, sector, hit, ret, alpha in rows:
        _acc(by_signal, sig or "UNKNOWN", hit, ret, alpha)
        _acc(by_conf, _conf_bucket(conf), hit, ret, alpha)
        _acc(by_sector, sector or "(미분류)", hit, ret, alpha)
        _acc(overall, "ALL", hit, ret, alpha)
    return {
        "totalScored": len(rows), "pending": int(pending), "minSample": MIN_SAMPLE,
        "overall": _finalize(overall)[0] if rows else None,
        "bySignal": _finalize(by_signal), "byConfidence": _finalize(by_conf),
        "bySector": _finalize(by_sector),
    }


def _pct(x):
    return "   N/A" if x is None else f"{x * 100:5.1f}%"


def _table(title, items, order=None):
    print(f"\n[{title}]")
    print("  키              표본   적중률   평균ret  평균alpha  신뢰")
    if order:
        items = sorted(items, key=lambda x: order.index(x["key"]) if x["key"] in order else 99)
    for it in items:
        if it["samples"] == 0:
            continue
        low = "낮음" if it["lowConfidence"] else " ok "
        print(f"  {it['key']:<14} {it['samples']:>4}  {_pct(it['hitRate'])}  "
              f"{_pct(it['avgRet1d'])}  {_pct(it['avgAlpha1d'])}   {low}")


def render(r):
    print("=" * 66)
    print("  AI 시그널 적중치 — 예측 vs 실재")
    print("=" * 66)
    print(f"채점 완료: {r['totalScored']}   채점 대기: {r['pending']}   "
          f"(표본 {r['minSample']} 미만 = 신뢰 낮음)")
    if not r["totalScored"]:
        print("\n아직 채점된 예측이 없다 — 다음 거래일 종가 적재 후 score_signals 채점 시 표시.")
        print("=" * 66)
        return
    ov = r["overall"]
    print(f"\n[전체]  적중률 {_pct(ov['hitRate'])}  "
          f"(표본 {ov['samples']}, 적중 {ov['hits']})  "
          f"평균 alpha {_pct(ov['avgAlpha1d'])}")
    _table("시그널별", r["bySignal"],
           order=["STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL"])
    _table("확신도 구간별", r["byConfidence"], order=["70+", "50-70", "0-50"])
    _table("섹터별", r["bySector"])
    print("=" * 66)


def main():
    ap = argparse.ArgumentParser(description="AI 시그널 적중치 수치 대시보드")
    ap.add_argument("--json", type=str, default=None)
    args = ap.parse_args()
    session = apollo_db.get_session_factory()()
    try:
        r = build(session)
    finally:
        session.close()
    render(r)
    if args.json:
        Path(args.json).write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON 덤프: {args.json}")


if __name__ == "__main__":
    main()
