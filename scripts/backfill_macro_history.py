"""backfill_macro_history.py — 글로벌 매크로 8점수 과거 역산 적재.

목적: MacroSentimentDaily 가 매일 1행씩만 쌓여(빈도 확률 전환에 60거래일 필요) 부족하므로,
  과거 거래일의 점수를 yfinance 일봉으로 **그 시점 데이터만(룩어헤드 없이)** 역산해 채운다.

원칙(데이터 정확성):
  - 시장지표(VIX·DXY·금리·지수·금·BTC…)는 yfinance 과거 일봉 — 실데이터.
  - 예측시장·뉴스·경제 surprise 는 과거 스냅샷이 없으므로 N/A(중립) 처리 → inputs_json.backfill=true 태그.
    따라서 역산 행은 라이브 행과 동일하지 않다(시장지표 기반 부분 재구성). 확률 공식이 쓰는
    위험선호·유동성·증시 모멘텀은 시장지표 기반이라 빈도 분석에는 충분.
  - 이미 존재하는 날짜(라이브 행)는 건드리지 않는다(덮어쓰기 금지).

라이브 스코어링과 100% 동일 룰을 쓰기 위해 global_macro 의 점수 함수를 그대로 재사용한다.

실행: python scripts/backfill_macro_history.py [--days 250]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

import global_macro as gm          # noqa: E402
import global_macro_feeds as feeds  # noqa: E402
import db as apollo_db             # noqa: E402
import models                      # noqa: E402


def _round(v, n=2):
    try:
        return round(float(v), n)
    except Exception:
        return None


def _pct(series, i: int, lookback: int):
    if i - lookback < 0:
        return None
    cur, prev = series.iloc[i], series.iloc[i - lookback]
    try:
        cur, prev = float(cur), float(prev)
        if prev == 0:
            return None
        return round((cur - prev) / prev * 100, 2)
    except Exception:
        return None


def _build_mkt(close, i: int) -> dict:
    """i번째 거래일 기준 market internals 재구성 (그 시점까지의 데이터만 사용)."""
    out: dict = {}
    last_vals: dict = {}
    for name, sym in feeds.MARKET_SYMBOLS.items():
        if sym not in close.columns:
            out[name] = None
            continue
        s = close[sym]
        last = s.iloc[i]
        try:
            last = float(last)
        except Exception:
            out[name] = None
            continue
        last_vals[name] = round(last, 2)
        out[name] = {"last": round(last, 2), "chg5d_pct": _pct(s, i, 5), "chg20d_pct": _pct(s, i, 20)}
    t10, t2 = last_vals.get("US10Y"), last_vals.get("US2Y")
    if t10 is not None and t2 is not None:
        spread = round(t10 - t2, 3)
        out["spread_10y_2y"] = spread
        out["yield_inverted"] = spread < 0
    else:
        out["spread_10y_2y"] = None
        out["yield_inverted"] = None
    return out


def _score_asof(mkt: dict) -> tuple[dict, dict]:
    """라이브 엔진과 동일 함수로 8점수 산출. pred/news/econ 은 과거 N/A(빈 dict)."""
    pred: dict = {}
    econ: dict = {}
    news: dict = {}
    s: dict = {}
    s["liquidity"], _ = gm._liquidity(pred, mkt, econ)
    s["growth"], _ = gm._growth(pred, mkt, econ)
    s["inflation"], _ = gm._inflation(pred, mkt, econ)
    s["ai_cycle"], _ = gm._ai_cycle(pred, mkt, econ, news)
    s["geopolitics"], _ = gm._geopolitics(pred, mkt, econ, news)
    s["risk_appetite"], _ = gm._risk_appetite(pred, mkt, econ)
    s["us_equity"], _ = gm._us_equity(mkt, s["risk_appetite"], s["liquidity"])
    s["kr_equity"], _ = gm._kr_equity(mkt, s["us_equity"], s["ai_cycle"])
    prob = gm._prob_deterministic(s)
    return s, prob


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=250, help="역산할 거래일 수 (기본 250)")
    args = ap.parse_args()

    try:
        import yfinance as yf
    except Exception:
        print("yfinance 미설치 — backfill 불가")
        return 1

    syms = list(feeds.MARKET_SYMBOLS.values())
    print(f"yfinance 다운로드 ({len(syms)} 심볼, 2y)…")
    data = yf.download(syms, period="2y", progress=False, threads=True)
    close = data["Close"]

    # 미국 거래일을 기준선으로 (^GSPC 유효일), 전 심볼을 그 인덱스에 맞춰 ffill
    if "^GSPC" not in close.columns:
        print("기준 지수(^GSPC) 데이터 없음 — 중단")
        return 1
    us_days = close["^GSPC"].dropna().index
    close = close.reindex(us_days).ffill()
    n = len(us_days)
    if n < 25:
        print(f"거래일 부족({n}) — 중단")
        return 1

    # 역산 구간: 마지막 days개 (단, chg20d 위해 앞쪽 20일 워밍업 필요)
    start = max(20, n - args.days)
    print(f"거래일 총 {n}, 역산 구간 {start}~{n - 1} ({n - start}일)")

    models.Base.metadata.create_all(
        apollo_db.get_engine(), tables=[models.MacroSentimentDaily.__table__]
    )

    session = apollo_db.get_session_factory()()
    inserted = skipped_exist = 0
    try:
        existing = {r[0] for r in session.execute(
            models.MacroSentimentDaily.__table__.select().with_only_columns(
                models.MacroSentimentDaily.trade_date)
        ).all()}
        for i in range(start, n):
            d = us_days[i].date()
            if d in existing:
                skipped_exist += 1
                continue
            mkt = _build_mkt(close, i)
            scores, prob = _score_asof(mkt)
            composite = gm._composite(scores)
            row = models.MacroSentimentDaily(trade_date=d)
            for k in gm.SCORE_KEYS:
                setattr(row, k, scores[k])
            row.composite = composite
            row.flow = gm._flow_label(composite)
            row.prob_json = prob
            row.inputs_json = {
                "backfill": True,
                "note": "시장지표 역산(yfinance) — 예측시장·뉴스·경제 surprise N/A",
                "market": {k: mkt.get(k) for k in ("VIX", "DXY", "US10Y", "US2Y", "spread_10y_2y", "yield_inverted")},
            }
            session.add(row)
            inserted += 1
            if inserted % 50 == 0:
                session.commit()
                print(f"  …{inserted}건 적재")
        session.commit()
    finally:
        session.close()

    print(f"완료: 신규 {inserted}건 적재, 기존(라이브) {skipped_exist}건 보존")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
