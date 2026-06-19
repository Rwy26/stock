"""us_leaders_sync.py — KR 섹터 선행 US 종목 일별 OHLCV 수집 (us-leaders-lead-lag).

us_lead.US_UNIVERSE(단일 소스)를 us_stocks / us_kr_lead_link 로 시드한 뒤, active 종목 전체의
최근 3개월 OHLCV 를 yfinance 일괄 다운로드해 us_daily_prices 로 UPSERT 하고
overnight_return_pct(= (close-prev_close)/prev_close*100)를 계산한다.

yfinance 단일소스라 KR siseJson 교차검증 대상은 아니지만, 종가 sanity check(전일 대비 ±50%
초과 시 경고 로그)로 분할/이상치를 표시한다(data-accuracy 원칙). 재실행 안전(UPSERT).

실행:  backend/.venv/Scripts/python.exe scripts/us_leaders_sync.py
스케줄: MOON-STOCK-US-Leaders-Sync (매일 06:05 KST — 미 정규장 마감·KR 개장 전)
로그:   logs/us-leaders-sync.log
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))

LOG = REPO / "logs" / "us-leaders-sync.log"
PERIOD = "3mo"  # 일일 스케줄 기본값 — CLI --period 로 일회성 백필 가능(예: 2y)
SANITY_PCT = 50.0   # 전일 종가 대비 ±50% 초과 → 경고(분할/이상치 의심)


def log(msg: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def ensure_tables() -> None:
    """us_* 3 테이블 생성(존재하면 무시 — create_all 은 기존 테이블 미변경)."""
    import db
    import models
    models.Base.metadata.create_all(bind=db.get_engine())


def seed_universe() -> None:
    """us_lead.US_UNIVERSE / iter_lead_links() → us_stocks / us_kr_lead_link UPSERT (멱등)."""
    import db
    import models
    import us_lead
    from sqlalchemy import select

    with db.session_scope() as s:
        for u in us_lead.iter_universe():
            row = s.get(models.UsStock, u["ticker"])
            if row is None:
                s.add(models.UsStock(
                    ticker=u["ticker"], name=u.get("name"),
                    kr_sector_lead=u.get("kr_sector_lead"),
                    weight=float(u.get("weight", 1.0)), active=True,
                ))
            else:
                row.name = u.get("name")
                row.kr_sector_lead = u.get("kr_sector_lead")
                row.weight = float(u.get("weight", 1.0))
                row.active = True

        existing = {
            (lk.us_ticker, lk.kr_sector): lk
            for lk in s.execute(select(models.UsKrLeadLink)).scalars().all()
        }
        for t, sec, lag in us_lead.iter_lead_links():
            lk = existing.get((t, sec))
            if lk is None:
                s.add(models.UsKrLeadLink(us_ticker=t, kr_sector=sec, lead_lag_days=lag))
            else:
                lk.lead_lag_days = lag
    log(f"seed: us_stocks={len(us_lead.iter_universe())}종목 / us_kr_lead_link={len(us_lead.iter_lead_links())}링크 UPSERT")


def _active_tickers() -> list[str]:
    import db
    import models
    from sqlalchemy import select
    with db.session_scope() as s:
        return list(s.execute(
            select(models.UsStock.ticker).where(models.UsStock.active.is_(True))
        ).scalars().all())


def sync_prices(tickers: list[str], period: str = PERIOD) -> int:
    """yfinance OHLCV(period) → us_daily_prices UPSERT. 적재 행수 반환."""
    import db
    import models
    from sqlalchemy import select

    try:
        import yfinance as yf
    except Exception as exc:  # noqa: BLE001
        log(f"ERROR: yfinance 미설치 — {type(exc).__name__} (pip install yfinance)")
        return 0

    # yfinance 빈 응답/실패는 일시적(특히 06:05 US 애프터아워)이라 재시도 가드.
    import time
    RETRIES = 3          # 총 시도 횟수
    BACKOFF = (20, 60)   # 재시도 간 대기(초): 1차 실패→20s, 2차 실패→60s
    data = None
    for attempt in range(1, RETRIES + 1):
        try:
            data = yf.download(tickers, period=period, progress=False,
                               threads=True, auto_adjust=False, group_by="column")
        except Exception as exc:  # noqa: BLE001
            log(f"WARN: yfinance download 실패 ({attempt}/{RETRIES}) — {type(exc).__name__}: {exc}")
            data = None
        if data is not None and not getattr(data, "empty", True):
            if attempt > 1:
                log(f"yfinance 응답 회복 (시도 {attempt}/{RETRIES})")
            break
        if data is not None:  # 빈 응답
            log(f"WARN: yfinance 빈 응답 ({attempt}/{RETRIES})")
        if attempt < RETRIES:
            wait = BACKOFF[min(attempt - 1, len(BACKOFF) - 1)]
            log(f"  {wait}초 후 재시도...")
            time.sleep(wait)

    if data is None or getattr(data, "empty", True):
        log(f"ERROR: yfinance {RETRIES}회 시도 모두 빈 응답/실패 — 적재 없음 (기존 데이터 보존)")
        return 0

    multi = hasattr(data.columns, "levels") and data.columns.nlevels > 1

    def series(field: str, ticker: str):
        try:
            if multi:
                return data[field][ticker]
            return data[field]   # 단일 종목
        except Exception:
            return None

    total = 0
    for ticker in tickers:
        close = series("Close", ticker)
        if close is None:
            log(f"  {ticker}: Close 컬럼 없음 — 스킵")
            continue
        opn = series("Open", ticker)
        high = series("High", ticker)
        low = series("Low", ticker)
        vol = series("Volume", ticker)

        cclean = close.dropna()
        if cclean.empty:
            log(f"  {ticker}: 종가 데이터 없음 — 스킵")
            continue

        with db.session_scope() as s:
            existing = {
                r.trading_date: r
                for r in s.execute(
                    select(models.UsDailyPrice).where(models.UsDailyPrice.ticker == ticker)
                ).scalars().all()
            }
            prev_close: float | None = None
            n_rows = warns = 0
            for ts in close.index:
                c = close.get(ts)
                if c is None or (isinstance(c, float) and c != c):   # NaN
                    prev_close = None
                    continue
                c = float(c)
                tdate = ts.date() if hasattr(ts, "date") else ts

                ovr = None
                if prev_close not in (None, 0):
                    ovr = round((c - prev_close) / prev_close * 100, 4)
                    if abs(ovr) > SANITY_PCT:
                        warns += 1
                        log(f"  WARN {ticker} {tdate}: 전일 대비 {ovr:+.1f}% (±{SANITY_PCT}% 초과 — 분할/이상치 의심)")

                def num(srs, default=None):
                    if srs is None:
                        return default
                    v = srs.get(ts)
                    if v is None or (isinstance(v, float) and v != v):
                        return default
                    return float(v)

                v_open = num(opn)
                v_high = num(high)
                v_low = num(low)
                v_vol = num(vol)
                v_vol = int(v_vol) if v_vol is not None else None

                row = existing.get(tdate)
                if row is None:
                    s.add(models.UsDailyPrice(
                        ticker=ticker, trading_date=tdate,
                        open_price=v_open, high_price=v_high, low_price=v_low,
                        close_price=c, volume=v_vol, overnight_return_pct=ovr,
                    ))
                else:
                    row.open_price = v_open
                    row.high_price = v_high
                    row.low_price = v_low
                    row.close_price = c
                    row.volume = v_vol
                    row.overnight_return_pct = ovr
                n_rows += 1
                prev_close = c

            total += n_rows
            last = round(float(cclean.iloc[-1]), 2)
            log(f"  {ticker}: {n_rows}행 UPSERT (최근 종가 {last}{', 경고 ' + str(warns) if warns else ''})")
    return total


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", default=PERIOD,
                    help="yfinance 기간(기본 3mo). 일회성 백필 예: 2y, 5y")
    cli = ap.parse_args()
    log(f"=== us-leaders-sync 시작 (period={cli.period}) ===")
    try:
        ensure_tables()
    except Exception as exc:  # noqa: BLE001
        log(f"FATAL: 테이블 생성 실패 — {type(exc).__name__}: {exc}")
        return 1
    try:
        seed_universe()
    except Exception as exc:  # noqa: BLE001
        log(f"FATAL: 유니버스 시드 실패 — {type(exc).__name__}: {exc}")
        return 1

    tickers = _active_tickers()
    log(f"active 종목 {len(tickers)}개 수집 시작: {', '.join(tickers)}")
    total = sync_prices(tickers, period=cli.period)
    log(f"=== 완료: us_daily_prices {total}행 UPSERT ===")
    return 0 if total > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
