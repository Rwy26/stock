"""build_training_dataset.py

예측 모델 학습 데이터셋 — daily_prices 기반 point-in-time 백필.

signal_outcomes(라이브, 정확한 composite 5요소·소량·느림)를 기다리는 동안,
이미 적재된 일봉 시계열로 **과거 매 거래일의 (피처 → 익일 결과)** 쌍을 즉시 대량 생성한다.
daily_prices 152종목 × ~495봉 + short_selling_daily + macro_sentiment_daily.

⚠️ 라이브 composite 5요소와 **다른 피처셋**이다(과거 분봉·섹터점수는 미저장이라 재현 불가).
   여기 피처는 전부 **일봉 주기로 point-in-time 재구성 가능한 것**만 — 룩어헤드 0.
   모델 탐색·베이스라인용. 라이브 5요소 모델은 signal_outcomes.features 축적분으로 따로 학습.

피처(시점 t, t 이하 데이터만 사용):
  수익률   : ret_1d, ret_5d, ret_20d
  이평괴리 : ma_gap_5, ma_gap_20, ma_gap_60  (close/MA − 1)
  모멘텀   : rsi_14
  변동성   : vol_20  (일수익률 std)
  거래량   : vol_ratio  (volume / 20일평균거래량)
  위치     : high_252_dist  (close/252봉최고 − 1)
  공매도   : short_ratio, short_ratio_chg_5   (as-of, 직전값 ffill)
  지수국면 : kospi_ret_5d  (069500 과거 5일)
  거시     : macro_composite  (macro_sentiment_daily as-of)

타깃(시점 t 기준 미래 — 학습 시에만 사용):
  fwd_ret_1d   = close[t+1]/close[t] − 1
  fwd_alpha_1d = fwd_ret_1d − (069500 t→t+1)
  label_1d     = fwd_alpha_1d > 0   (없으면 fwd_ret_1d > 0)
  fwd_ret_5d   = close[t+5]/close[t] − 1  (있을 때만)

제외: exclusion_engine 대상(거래정지/스팩/우선주 등)은 종목 단위로 스킵 가능(--apply-exclusions).
      최소 이력 --min-bars(기본 80) 미만 종목 스킵. 결측 피처 행은 드롭.

출력: PIPELINE_ROOT/data/processed/training_dataset_<asof>.csv (+ 요약 콘솔).

사용법:
  python scripts/build_training_dataset.py
  python scripts/build_training_dataset.py --min-bars 120 --out C:\tmp\ds.csv
  python scripts/build_training_dataset.py --apply-exclusions
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

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sqlalchemy import text  # noqa: E402

import db as apollo_db  # noqa: E402

KOSPI_PROXY = "069500"


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _load_prices(eng) -> pd.DataFrame:
    df = pd.read_sql(
        text("SELECT stock_code,trading_date,close_price,volume FROM daily_prices "
             "ORDER BY stock_code,trading_date"), eng)
    df["trading_date"] = pd.to_datetime(df["trading_date"])
    return df


def _load_kospi(eng) -> pd.Series:
    df = pd.read_sql(
        text("SELECT trading_date,close_price FROM daily_prices "
             "WHERE stock_code=:c ORDER BY trading_date"),
        eng, params={"c": KOSPI_PROXY})
    df["trading_date"] = pd.to_datetime(df["trading_date"])
    return df.set_index("trading_date")["close_price"]


def _load_short(eng) -> pd.DataFrame:
    df = pd.read_sql(
        text("SELECT stock_code,trade_date,short_ratio FROM short_selling_daily "
             "ORDER BY stock_code,trade_date"), eng)
    if df.empty:
        return df
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df


def _load_macro(eng) -> pd.Series:
    df = pd.read_sql(text("SELECT trade_date,composite FROM macro_sentiment_daily "
                          "ORDER BY trade_date"), eng)
    if df.empty:
        return pd.Series(dtype=float)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df.set_index("trade_date")["composite"]


def _excluded_codes(session) -> set:
    try:
        import exclusion_engine  # noqa: F401
        from sqlalchemy import select
        import models
        rows = session.execute(select(models.ExcludedStock.stock_code)).all()
        return {r[0] for r in rows}
    except Exception:
        return set()


def build(min_bars: int, apply_exclusions: bool) -> pd.DataFrame:
    eng = apollo_db.get_engine()
    prices = _load_prices(eng)
    kospi = _load_kospi(eng)
    short = _load_short(eng)
    macro = _load_macro(eng)

    kospi_ret1 = kospi.pct_change()        # t-1 → t
    kospi_fwd1 = kospi.shift(-1) / kospi - 1  # t → t+1 (타깃용)
    kospi_ret5 = kospi.pct_change(5)

    excluded = set()
    if apply_exclusions:
        s = apollo_db.get_session_factory()()
        try:
            excluded = _excluded_codes(s)
        finally:
            s.close()

    short_by = {c: g.set_index("trade_date")["short_ratio"]
                for c, g in short.groupby("stock_code")} if not short.empty else {}

    frames = []
    for code, g in prices.groupby("stock_code"):
        if code == KOSPI_PROXY or code in excluded:
            continue
        g = g.sort_values("trading_date").set_index("trading_date")
        if len(g) < min_bars:
            continue
        close = g["close_price"].astype(float)
        vol = g["volume"].astype(float)

        f = pd.DataFrame(index=g.index)
        f["stock_code"] = code
        # 피처 (t 이하)
        f["ret_1d"] = close.pct_change(1)
        f["ret_5d"] = close.pct_change(5)
        f["ret_20d"] = close.pct_change(20)
        f["ma_gap_5"] = close / close.rolling(5).mean() - 1
        f["ma_gap_20"] = close / close.rolling(20).mean() - 1
        f["ma_gap_60"] = close / close.rolling(60).mean() - 1
        f["rsi_14"] = _rsi(close, 14)
        f["vol_20"] = close.pct_change().rolling(20).std()
        f["vol_ratio"] = vol / vol.rolling(20).mean()
        f["high_252_dist"] = close / close.rolling(252, min_periods=60).max() - 1
        f["kospi_ret_5d"] = kospi_ret5.reindex(g.index)
        f["macro_composite"] = macro.reindex(g.index, method="ffill") if len(macro) else np.nan
        # 공매도 (as-of ffill)
        if code in short_by:
            sr = short_by[code].reindex(g.index, method="ffill")
            f["short_ratio"] = sr
            f["short_ratio_chg_5"] = sr - sr.shift(5)
        else:
            f["short_ratio"] = np.nan
            f["short_ratio_chg_5"] = np.nan
        # 타깃 (미래)
        fwd1 = close.shift(-1) / close - 1
        f["fwd_ret_1d"] = fwd1
        kfwd = kospi_fwd1.reindex(g.index)
        f["fwd_alpha_1d"] = fwd1 - kfwd
        basis = f["fwd_alpha_1d"].where(kfwd.notna(), fwd1)
        f["label_1d"] = (basis > 0).astype("Int64")
        f.loc[basis.isna(), "label_1d"] = pd.NA
        f["fwd_ret_5d"] = close.shift(-5) / close - 1
        frames.append(f.reset_index().rename(columns={"index": "trading_date"}))

    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    # 타깃 없는(마지막 봉) 행·필수 피처 결측 드롭
    feat_cols = ["ret_1d", "ret_5d", "ret_20d", "ma_gap_5", "ma_gap_20", "ma_gap_60",
                 "rsi_14", "vol_20", "vol_ratio", "high_252_dist"]
    out = out.dropna(subset=feat_cols + ["fwd_ret_1d", "label_1d"])
    return out


def main():
    ap = argparse.ArgumentParser(description="예측 모델 학습 데이터셋 백필")
    ap.add_argument("--min-bars", type=int, default=80)
    ap.add_argument("--apply-exclusions", action="store_true")
    ap.add_argument("--out", type=str, default=None)
    args = ap.parse_args()

    df = build(args.min_bars, args.apply_exclusions)

    print("=" * 64)
    print("  예측 모델 학습 데이터셋 (point-in-time 백필)")
    print("=" * 64)
    if df.empty:
        print("샘플 0 — 이력 부족.")
        sys.exit(2)

    n = len(df)
    pos = int((df["label_1d"] == 1).sum())
    print(f"샘플: {n:,}   종목: {df['stock_code'].nunique()}   "
          f"기간: {df['trading_date'].min().date()} ~ {df['trading_date'].max().date()}")
    print(f"라벨(익일 alpha>0): 양성 {pos:,} ({pos/n*100:.1f}%) / 음성 {n-pos:,}")
    cov = df[["short_ratio", "macro_composite"]].notna().mean() * 100
    print(f"피처 커버리지 — short_ratio {cov['short_ratio']:.0f}% · "
          f"macro_composite {cov['macro_composite']:.0f}%")
    print(f"fwd_ret_5d 보유: {df['fwd_ret_5d'].notna().mean()*100:.0f}%")

    # 출력 경로
    if args.out:
        out_path = Path(args.out)
    else:
        try:
            import pipeline_paths
            base = pipeline_paths.get_pipeline_paths().data_processed
            base.mkdir(parents=True, exist_ok=True)
        except Exception:
            base = Path(".")
        asof = df["trading_date"].max().strftime("%Y%m%d")
        out_path = Path(base) / f"training_dataset_{asof}.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n저장: {out_path}  ({out_path.stat().st_size/1e6:.1f} MB)")
    print("=" * 64)


if __name__ == "__main__":
    main()
