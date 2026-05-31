"""
daily_prices 500거래일 수집 스크립트
- yfinance {code}.KS (KOSPI) / {code}.KQ (KOSDAQ) 조회
- 실패 시 .KS/.KQ 교차 재시도
- DB: INSERT INTO daily_prices ON DUPLICATE KEY UPDATE
- 진행상황: 종목당 1줄 출력
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import yfinance as yf
import pandas as pd
from sqlalchemy import text
from db import get_session_factory

# 500거래일 ≈ 2년(휴일 포함 약 730일)
START = (datetime.today() - timedelta(days=730)).strftime("%Y-%m-%d")
END = datetime.today().strftime("%Y-%m-%d")

UPSERT_SQL = text("""
INSERT INTO daily_prices
    (stock_code, trading_date, open_price, high_price, low_price, close_price, volume)
VALUES
    (:code, :date, :open, :high, :low, :close, :volume)
ON DUPLICATE KEY UPDATE
    open_price  = VALUES(open_price),
    high_price  = VALUES(high_price),
    low_price   = VALUES(low_price),
    close_price = VALUES(close_price),
    volume      = VALUES(volume)
""")


class Result(NamedTuple):
    code: str
    name: str
    rows: int
    ticker_used: str
    error: str


def fetch_ticker(ticker: str) -> pd.DataFrame | None:
    try:
        df = yf.download(ticker, start=START, end=END, progress=False, auto_adjust=True)
        if df.empty or len(df) < 3:
            return None
        return df
    except Exception:
        return None


def get_all_stocks(db) -> list[tuple[str, str, str]]:
    """(code, name, market) 반환."""
    rows = db.execute(text("SELECT code, name, market FROM stocks ORDER BY code")).all()
    return [(r[0], r[1], r[2] or "KOSPI") for r in rows]


def run() -> None:
    db = get_session_factory()()
    stocks = get_all_stocks(db)
    db.close()

    total = len(stocks)
    ok_list: list[Result] = []
    fail_list: list[Result] = []

    print(f"\n[fetch_daily_prices] 수집 시작 — {total}종목 / {START} ~ {END}\n")
    print(f"{'#':>4}  {'코드':<8} {'종목명':<22} {'행수':>5}  {'티커':<12}  {'비고'}")
    print("─" * 68)

    for idx, (code, name, market) in enumerate(stocks, 1):
        # 거래소 기반 기본 서픽스 결정
        if "KOSDAQ" in (market or "").upper() or "KQ" in (market or "").upper():
            suffixes = [".KQ", ".KS"]
        else:
            suffixes = [".KS", ".KQ"]

        df = None
        ticker_used = ""
        for sfx in suffixes:
            ticker = f"{code}{sfx}"
            df = fetch_ticker(ticker)
            if df is not None:
                ticker_used = ticker
                break

        if df is None or df.empty:
            fail_list.append(Result(code, name, 0, "", "데이터 없음"))
            print(f"{idx:>4}  {code:<8} {name:<22} {'—':>5}  {'—':<12}  FAIL")
            time.sleep(0.3)
            continue

        # DataFrame 컬럼 정규화 (MultiIndex 방어)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.rename(columns={"Open": "open", "High": "high", "Low": "low",
                                 "Close": "close", "Volume": "volume"})
        df = df[["open", "high", "low", "close", "volume"]].dropna()

        # DB upsert
        batch = []
        for dt, row in df.iterrows():
            trading_date = dt.date() if hasattr(dt, "date") else dt
            batch.append({
                "code": code,
                "date": trading_date,
                "open": int(row["open"]),
                "high": int(row["high"]),
                "low": int(row["low"]),
                "close": int(row["close"]),
                "volume": int(row["volume"]),
            })

        db2 = get_session_factory()()
        try:
            db2.execute(UPSERT_SQL, batch)
            db2.commit()
        finally:
            db2.close()

        ok_list.append(Result(code, name, len(batch), ticker_used, ""))
        print(f"{idx:>4}  {code:<8} {name:<22} {len(batch):>5}  {ticker_used:<12}  OK")
        time.sleep(0.25)   # yfinance 과부하 방지

    # 결과 요약
    print("\n" + "═" * 68)
    print(f"완료: {len(ok_list)}종목 성공 / {len(fail_list)}종목 실패\n")
    if fail_list:
        print("실패 목록:")
        for r in fail_list:
            print(f"  {r.code}  {r.name}  — {r.error}")


if __name__ == "__main__":
    run()
