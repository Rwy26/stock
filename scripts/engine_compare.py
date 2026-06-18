"""엔진별 독립 예측 비교 — 저장된 DB만으로(네트워크 없이) 각 확률 엔진을 따로 돌려본다.

같은 종목·같은 시점(최신 봉)에서 각 엔진이 **독립적으로** 산출하는 '20일 상승 확률'을
나란히 놓고 일치도·상관·괴리를 본다. 어느 엔진도 다른 엔진 출력을 입력으로 쓰지 않음.

비교 엔진 (전부 daily_prices 만으로 동작):
  E1 1차원      : _first_passage_prob — EMA20/60 추세 상태 동일 표본의 20일후 상승빈도
  E2 6차원      : _similar_regime_prob — 6D 유사 국면 k-NN 상승빈도
  E3 7차원(PER) : 6D + P/E 백분위 (pykrx 조회 — --with-per 시에만)
  E4 닷컴       : regime_analogs 닷컴 표본 유사 국면 상승빈도
  US lead       : us_lead 섹터 선행점수(0~100) — 확률 아님(맥락 축, 참고)

산출: 엔진별 확률 테이블(CSV) + 쌍별 상관 + 방향(>50) 일치율 + 최대 괴리 종목.
실행: python scripts\engine_compare.py [--with-per] [--stocks N]
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
UP, DN = 0.08, 0.05


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-per", action="store_true")
    ap.add_argument("--stocks", type=int, default=80)
    ap.add_argument("--min-bars", type=int, default=300)
    args = ap.parse_args()

    import db
    import models
    from sqlalchemy import select, func

    s = db.get_session_factory()()
    counts = s.execute(select(models.DailyPrice.stock_code, func.count())
                       .group_by(models.DailyPrice.stock_code)).all()
    codes = [c for c, n in counts if n >= args.min_bars][: args.stocks]
    names = {c: (s.get(models.Stock, c).name if s.get(models.Stock, c) else c) for c in codes}
    print(f"엔진별 독립 예측 비교 — {len(codes)}종목 / 최신 시점 / "
          f"{'7차원 포함' if args.with_per else '6차원'}")

    rows = []
    for code in codes:
        prs = s.execute(select(models.DailyPrice)
                        .where(models.DailyPrice.stock_code == code)
                        .order_by(models.DailyPrice.trading_date)).scalars().all()
        bars = [{"date": r.trading_date.strftime("%Y%m%d"), "close": float(r.close_price),
                 "high": float(r.high_price), "low": float(r.low_price),
                 "volume": float(r.volume or 0)} for r in prs]
        # E1 1차원
        p1 = te._first_passage_prob(bars, UP, DN)
        e1 = p1.get("continueUpPct") if "error" not in p1 else None
        # E2 6차원
        p6 = te._similar_regime_prob(bars, UP, DN)
        e2 = p6.get("continueUpPct") if "error" not in p6 else None
        e4 = None
        if "error" not in p6:
            dc = p6.get("dotcomAnalogs", {})
            e4 = dc.get("continueUpPct") if "error" not in dc else None
        # E3 7차원
        e3 = None
        if args.with_per:
            per_map = te._fetch_per_series(code, bars[0]["date"], bars[-1]["date"])
            time.sleep(0.2)
            p7 = te._similar_regime_prob(bars, UP, DN, per_map=per_map)
            if "error" not in p7 and p7.get("valuationDim", {}).get("used"):
                e3 = p7.get("continueUpPct")
        # US lead (섹터)
        us_sec, lead = te._us_lead_score_for_code(code)
        rows.append({"code": code, "name": names.get(code, code),
                     "E1_1dim": e1, "E2_6dim": e2, "E3_7dim": e3,
                     "E4_dotcom": e4, "US_lead": lead, "sector": us_sec})
    s.close()

    OUT.mkdir(parents=True, exist_ok=True)
    import csv as _csv
    with open(OUT / "engine_compare.csv", "w", encoding="utf-8", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # ── 엔진별 요약 (확률 3종 + US lead) ─────────────────────────────────────
    def stats(key):
        v = [r[key] for r in rows if r[key] is not None]
        if not v:
            return None
        v.sort()
        mean = sum(v) / len(v)
        return {"n": len(v), "mean": round(mean, 1),
                "min": round(v[0], 1), "max": round(v[-1], 1),
                "p50": round(v[len(v) // 2], 1)}

    print(f"\n[엔진별 20일 상승확률 분포] (종목 {len(rows)})")
    for key, label in [("E1_1dim", "E1 1차원"), ("E2_6dim", "E2 6차원"),
                       ("E3_7dim", "E3 7차원"), ("E4_dotcom", "E4 닷컴"),
                       ("US_lead", "US lead(점수)")]:
        st = stats(key)
        if st:
            print(f"  {label}: 평균 {st['mean']} / 중앙 {st['p50']} / "
                  f"범위 {st['min']}~{st['max']} (n={st['n']})")
        else:
            print(f"  {label}: 데이터 없음")

    # ── 쌍별 상관 (확률 엔진끼리) ────────────────────────────────────────────
    def corr(ka, kb):
        pairs = [(r[ka], r[kb]) for r in rows if r[ka] is not None and r[kb] is not None]
        if len(pairs) < 10:
            return None, len(pairs)
        xs = [a for a, _ in pairs]
        ys = [b for _, b in pairs]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        cov = sum((a - mx) * (b - my) for a, b in pairs)
        dx = sum((a - mx) ** 2 for a in xs) ** 0.5
        dy = sum((b - my) ** 2 for b in ys) ** 0.5
        return (cov / (dx * dy) if dx * dy else None), len(pairs)

    print("\n[엔진 쌍별 상관] (확률이 같은 방향으로 움직이는가)")
    eng = [("E1_1dim", "E1"), ("E2_6dim", "E2"), ("E3_7dim", "E3"), ("E4_dotcom", "E4")]
    for i in range(len(eng)):
        for j in range(i + 1, len(eng)):
            c, npair = corr(eng[i][0], eng[j][0])
            if c is not None:
                print(f"  {eng[i][1]}↔{eng[j][1]}: r={c:+.3f} (n={npair})")

    # ── 방향(>50) 일치율 + 최대 괴리 ─────────────────────────────────────────
    print("\n[방향 일치] E1·E2·E4 가 모두 >50(상승우위) 또는 모두 <50(하락우위)인 종목")
    tri = [r for r in rows if all(r[k] is not None for k in ("E1_1dim", "E2_6dim", "E4_dotcom"))]
    agree = sum(1 for r in tri
                if (r["E1_1dim"] > 50) == (r["E2_6dim"] > 50) == (r["E4_dotcom"] > 50))
    print(f"  3엔진 방향 일치: {agree}/{len(tri)} ({agree/max(len(tri),1)*100:.0f}%)")
    # 최대 괴리 (E2 vs E4 차이가 큰 종목 — 한국 국면 vs 닷컴 국면 불일치)
    div = sorted((r for r in tri), key=lambda r: -abs(r["E2_6dim"] - r["E4_dotcom"]))[:5]
    print("\n[E2(6차원) vs E4(닷컴) 최대 괴리 — 한국 표본과 닷컴 표본이 다르게 보는 종목]")
    for r in div:
        print(f"  {r['name']}({r['code']}): 6차원 {r['E2_6dim']} vs 닷컴 {r['E4_dotcom']} "
              f"(차이 {abs(r['E2_6dim']-r['E4_dotcom']):.0f}p, {r['sector']} lead {r['US_lead']})")

    print(f"\n결과 저장: {OUT / 'engine_compare.csv'}")
    print("주: 각 엔진은 독립 산출(서로의 출력을 입력으로 쓰지 않음). "
          "확률은 과거 빈도 — 예측 우위는 backtest(AUC~0.5) 참조.")


if __name__ == "__main__":
    main()
