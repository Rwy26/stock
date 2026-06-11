"""
daily_prices 수집 스크립트 (2026-06-12 검증 강화판)

원칙: 잘못된 데이터는 저장하지 않는다 (exclusion_engine 유동성 판정이 이 테이블에 의존).

소스 구성:
  - 네이버 siseJson(원시 일봉) = 최근 구간(NAVER_DAYS)의 기준 소스.
    네이버 조회 실패 시 해당 종목은 아무것도 저장하지 않는다 (정확성 > 가용성).
  - yfinance = 과거 백필 전용. DB 보유 행이 BACKFILL_MIN 미만인 종목에만 사용하고,
    네이버와 겹치는 날짜의 종가가 0.5% 이내로 90% 이상 일치할 때만
    네이버 구간보다 오래된 행을 저장한다. (yfinance는 NaN 종가·비정상 거래량·
    거래정지일 플랫 패딩이 관측됨 — 2026-06-12 진단)

행 단위 검증 (두 소스 공통):
  - OHLC 모두 양수, NaN 없음
  - high >= max(open, close), low <= min(open, close)
  - volume=0 & OHLC 동일(거래정지일 패딩) 행 제외

사용법:
  .\\backend\\.venv\\Scripts\\python.exe scripts\\fetch_daily_prices.py [--backfill]
    --backfill: DB 보유량과 무관하게 전 종목 yfinance 백필 시도
"""
from __future__ import annotations

import argparse
import ast
import math
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

import httpx
from sqlalchemy import text
from db import get_session_factory

LOG_FILE = REPO_ROOT / "logs" / "fetch_daily_prices.log"

NAVER_DAYS = 45          # 네이버 기준 소스로 덮는 최근 달력일 수
BACKFILL_MIN = 400       # DB 보유 행이 이 미만이면 yfinance 백필 시도
BACKFILL_CAL_DAYS = 730  # 백필 범위(달력일) ≈ 500거래일
YF_AGREE_TOL = 0.005     # 네이버 대비 종가 허용 오차 0.5%
YF_AGREE_RATIO = 0.90    # 겹치는 날짜 중 일치해야 하는 비율

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

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

Row = dict  # {date, open, high, low, close, volume}


def valid_row(r: Row) -> bool:
    vals = (r["open"], r["high"], r["low"], r["close"])
    if any(v is None or (isinstance(v, float) and math.isnan(v)) or v <= 0 for v in vals):
        return False
    if r["volume"] is None or r["volume"] < 0:
        return False
    if r["high"] < max(r["open"], r["close"]) or r["low"] > min(r["open"], r["close"]):
        return False
    # 거래정지일 패딩: 거래량 0 + OHLC 동일 → 정보가 없는 행이므로 저장하지 않는다
    if r["volume"] == 0 and r["open"] == r["high"] == r["low"] == r["close"]:
        return False
    return True


def fetch_naver_daily(code: str, start: date, end: date) -> list[Row] | None:
    """네이버 siseJson 원시 일봉. 실패 시 None (호출측에서 저장 중단)."""
    try:
        resp = httpx.get(
            "https://api.finance.naver.com/siseJson.naver",
            params={
                "symbol": code, "requestType": 1,
                "startTime": start.strftime("%Y%m%d"),
                "endTime": end.strftime("%Y%m%d"),
                "timeframe": "day",
            },
            headers=HEADERS, timeout=15,
        )
        resp.raise_for_status()
        raw = ast.literal_eval(resp.text.strip())
    except Exception:
        return None
    rows: list[Row] = []
    for item in raw[1:]:  # [0]은 헤더
        try:
            rows.append({
                "date": datetime.strptime(str(item[0]), "%Y%m%d").date(),
                "open": int(item[1]), "high": int(item[2]),
                "low": int(item[3]), "close": int(item[4]),
                "volume": int(item[5]),
            })
        except (ValueError, IndexError, TypeError):
            continue
    return rows


def fetch_yf_history(code: str, market: str, start: date, end: date) -> list[Row]:
    """yfinance 백필. .KS/.KQ 교차 시도, 실패·불량은 빈 리스트."""
    import yfinance as yf
    import pandas as pd

    if "KOSDAQ" in (market or "").upper() or "KQ" in (market or "").upper():
        suffixes = [".KQ", ".KS"]
    else:
        suffixes = [".KS", ".KQ"]

    df = None
    for sfx in suffixes:
        try:
            cand = yf.download(f"{code}{sfx}", start=start.isoformat(),
                               end=(end + timedelta(days=1)).isoformat(),  # yf end는 exclusive
                               progress=False, auto_adjust=True)
        except Exception:
            cand = None
        if cand is not None and len(cand) >= 3:
            df = cand
            break
    if df is None:
        return []

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns={"Open": "open", "High": "high", "Low": "low",
                            "Close": "close", "Volume": "volume"})
    df = df[["open", "high", "low", "close", "volume"]].dropna()

    rows: list[Row] = []
    for dt, r in df.iterrows():
        rows.append({
            "date": dt.date() if hasattr(dt, "date") else dt,
            "open": int(round(float(r["open"]))), "high": int(round(float(r["high"]))),
            "low": int(round(float(r["low"]))), "close": int(round(float(r["close"]))),
            "volume": int(r["volume"]),
        })
    return rows


def yf_agrees_with_naver(yf_rows: list[Row], naver_rows: list[Row]) -> bool:
    """겹치는 날짜의 종가 일치율 검사. 겹침이 없으면 불합격."""
    naver_close = {r["date"]: r["close"] for r in naver_rows}
    overlap = [r for r in yf_rows if r["date"] in naver_close]
    if not overlap:
        return False
    agree = sum(
        1 for r in overlap
        if abs(r["close"] - naver_close[r["date"]]) / naver_close[r["date"]] <= YF_AGREE_TOL
    )
    return agree / len(overlap) >= YF_AGREE_RATIO


def upsert(batch: list[Row], code: str) -> None:
    if not batch:
        return
    db = get_session_factory()()
    try:
        db.execute(UPSERT_SQL, [
            {"code": code, "date": r["date"], "open": r["open"], "high": r["high"],
             "low": r["low"], "close": r["close"], "volume": r["volume"]}
            for r in batch
        ])
        db.commit()
    finally:
        db.close()


def log_summary(line: str) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {line}\n")
    except Exception:
        pass


def run(force_backfill: bool) -> int:
    today = date.today()
    naver_start = today - timedelta(days=NAVER_DAYS)
    backfill_start = today - timedelta(days=BACKFILL_CAL_DAYS)

    db = get_session_factory()()
    stocks = db.execute(
        text("SELECT code, name, market FROM stocks ORDER BY code")).all()
    counts = dict(db.execute(
        text("SELECT stock_code, COUNT(*) FROM daily_prices GROUP BY stock_code")).all())
    try:
        import exclusion_engine
        excluded = set(exclusion_engine.get_exclusions(db))
    except Exception:
        excluded = set()
    db.close()

    if excluded:
        before = len(stocks)
        stocks = [s for s in stocks if s[0] not in excluded]
        print(f"[exclusion] 거래 제외 종목 {before - len(stocks)}건 수집 제외")

    total = len(stocks)
    ok = fail = 0
    fail_names: list[str] = []
    print(f"\n[fetch_daily_prices] {total}종목 / 네이버 {naver_start}~{today}"
          f"{' / 전종목 백필' if force_backfill else ''}\n")
    print(f"{'#':>4}  {'코드':<8} {'종목명':<22} {'네이버':>5} {'백필':>5}  {'비고'}")
    print("─" * 64)

    # 장 마감(15:30) 전 실행이면 당일 봉은 미완성이므로 저장하지 않는다
    skip_today = datetime.now().time() < datetime.strptime("15:40", "%H:%M").time()
    if skip_today:
        print("[guard] 장 마감 전 실행 — 당일 봉 제외")

    for idx, (code, name, market) in enumerate(stocks, 1):
        naver_rows = fetch_naver_daily(code, naver_start, today)
        if naver_rows is None:
            fail += 1
            fail_names.append(f"{code} {name}")
            print(f"{idx:>4}  {code:<8} {name:<22} {'—':>5} {'—':>5}  FAIL 네이버 조회 실패 — 저장 안 함")
            time.sleep(0.3)
            continue
        naver_rows = [r for r in naver_rows if valid_row(r)
                      and not (skip_today and r["date"] == today)]

        backfill_rows: list[Row] = []
        note = ""
        if force_backfill or counts.get(code, 0) < BACKFILL_MIN:
            yf_rows = [r for r in fetch_yf_history(code, market, backfill_start, today)
                       if valid_row(r)]
            if yf_rows and naver_rows:
                if yf_agrees_with_naver(yf_rows, naver_rows):
                    oldest_naver = min(r["date"] for r in naver_rows)
                    backfill_rows = [r for r in yf_rows if r["date"] < oldest_naver]
                else:
                    note = "yf-네이버 불일치 → 백필 폐기"
            elif not yf_rows:
                note = "yf 백필 없음"
            time.sleep(0.25)

        upsert(naver_rows + backfill_rows, code)
        ok += 1
        print(f"{idx:>4}  {code:<8} {name:<22} {len(naver_rows):>5} {len(backfill_rows):>5}  {note or 'OK'}")
        time.sleep(0.2)

    print("\n" + "═" * 64)
    print(f"완료: {ok}종목 성공 / {fail}종목 실패")
    if fail_names:
        print("실패(저장 안 함):")
        for n in fail_names:
            print(f"  {n}")
    log_summary(f"ok={ok} fail={fail} total={total}"
                + (f" failed=[{', '.join(fail_names)}]" if fail_names else ""))
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill", action="store_true",
                        help="전 종목 yfinance 과거 백필 강제")
    args = parser.parse_args()
    sys.exit(run(args.backfill))
