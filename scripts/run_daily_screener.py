"""일일 약세·과열 스크리너 실행 + 저장.

매 거래일 마감(일봉 적재 16:10) 이후 16:35 KST 실행 권장.

  관심종목(watchlist user_id=1) + 확장풀(daily_prices 이력 >=180봉, 거래대금 상위)
  → exclusion_engine 제외 → screener_engine 분류 → daily_screener_results 저장.

사용법:
  cd C:\\stock\\backend
  .\\.venv\\Scripts\\python.exe ..\\scripts\\run_daily_screener.py [--date YYYY-MM-DD]
                                                                   [--expand N] [--compress N]
                                                                   [--no-store] [--print]
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))

import pandas as pd
from sqlalchemy import text

import exclusion_engine
import models
import screener_engine as se
from db import get_engine, get_session_factory

LOG_FILE = REPO / "logs" / "daily_screener.log"
WATCHLIST_USER_ID = 1
DEFAULT_EXPAND = 150     # 확장풀 최대 종목 수 (거래대금 상위)
DEFAULT_COMPRESS = 60    # 분류별 적출 과다 시 압축 상한
MIN_BARS = se.MIN_BARS


def log(msg: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def resolve_as_of(session, requested: date | None) -> date:
    """저장된 daily_prices의 최신 거래일 (요청일 이하)을 기준일로 사용."""
    q = "SELECT MAX(trading_date) FROM daily_prices"
    params = {}
    if requested is not None:
        q += " WHERE trading_date <= :d"
        params["d"] = requested
    row = session.execute(text(q), params).scalar()
    if row is None:
        raise SystemExit("daily_prices 비어있음 — 일봉 적재 필요")
    return row if isinstance(row, date) else datetime.strptime(str(row), "%Y-%m-%d").date()


def watchlist_codes(session) -> list[str]:
    rows = session.execute(
        text("SELECT DISTINCT stock_code FROM watchlist WHERE user_id = :u"),
        {"u": WATCHLIST_USER_ID},
    ).all()
    return [r[0] for r in rows]


def expansion_codes(session, as_of: date, limit: int, exclude: set[str]) -> tuple[list[str], int]:
    """확장풀: 이력 >=MIN_BARS 종목 중 최근 20봉 평균 거래대금 상위 limit개.

    이력 부족(<MIN_BARS) 종목은 후속 적재 과제로 카운트만 반환.
    """
    # 이력 충분 + 최근 평균 거래대금
    rows = session.execute(
        text(
            """
            SELECT stock_code,
                   COUNT(*) AS bars,
                   AVG(CASE WHEN value IS NOT NULL THEN value
                            ELSE close_price * volume END) AS avg_val
            FROM daily_prices
            WHERE trading_date <= :asof
            GROUP BY stock_code
            HAVING COUNT(*) >= :minbars
            ORDER BY avg_val DESC
            """
        ),
        {"asof": as_of, "minbars": MIN_BARS},
    ).all()
    # 전체 distinct 종목 수 (이력 부족 카운트용)
    total_codes = session.execute(
        text("SELECT COUNT(DISTINCT stock_code) FROM daily_prices WHERE trading_date <= :asof"),
        {"asof": as_of},
    ).scalar() or 0

    sufficient = [r[0] for r in rows]
    insufficient_count = int(total_codes) - len(sufficient)

    picked = [c for c in sufficient if c not in exclude][:limit]
    return picked, insufficient_count


def load_ohlcv(session, code: str, as_of: date, lookback: int = 300) -> pd.DataFrame | None:
    rows = session.execute(
        text(
            """
            SELECT trading_date, open_price, high_price, low_price, close_price, volume
            FROM daily_prices
            WHERE stock_code = :c AND trading_date <= :asof
            ORDER BY trading_date DESC
            LIMIT :lim
            """
        ),
        {"c": code, "asof": as_of, "lim": lookback},
    ).all()
    if not rows:
        return None
    df = pd.DataFrame(
        rows, columns=["trading_date", "open", "high", "low", "close", "volume"]
    )
    df = df.sort_values("trading_date").set_index("trading_date")
    return df


def stock_names(session, codes: list[str]) -> dict[str, str]:
    if not codes:
        return {}
    rows = session.execute(
        text("SELECT code, name FROM stocks WHERE code IN :codes").bindparams(
            __import__("sqlalchemy").bindparam("codes", expanding=True)
        ),
        {"codes": codes},
    ).all()
    return {r[0]: r[1] for r in rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="기준일 YYYY-MM-DD (생략 시 최신 거래일)")
    ap.add_argument("--expand", type=int, default=DEFAULT_EXPAND, help="확장풀 종목 수 (0=관심종목만)")
    ap.add_argument("--compress", type=int, default=DEFAULT_COMPRESS, help="분류별 압축 상한")
    ap.add_argument("--no-store", action="store_true", help="DB 저장 생략")
    ap.add_argument("--print", action="store_true", dest="do_print", help="요약 출력")
    args = ap.parse_args()

    requested = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else None

    # 테이블 보장
    models.Base.metadata.create_all(bind=get_engine())

    session = get_session_factory()()
    try:
        as_of = resolve_as_of(session, requested)
        log(f"스크리너 시작 asOf={as_of}")

        # 제외 인덱스
        try:
            exclusions = exclusion_engine.get_exclusions(session)
        except Exception as e:  # 제외 엔진 실패 시 빈 집합(보수적으로 진행)
            log(f"WARN get_exclusions 실패: {e}")
            exclusions = {}
        excluded = set(exclusions.keys())

        wl = watchlist_codes(session)
        log(f"관심종목 {len(wl)}개")

        exp, insuff_cnt = ([], 0)
        if args.expand > 0:
            exp, insuff_cnt = expansion_codes(session, as_of, args.expand, set(wl) | excluded)
            log(f"확장풀 {len(exp)}개 (이력<{MIN_BARS}봉 보류 종목 {insuff_cnt}개 — 후속 적재 과제)")

        # 적출 대상 = 관심종목 + 확장풀, 제외종목 필터
        codes = [c for c in dict.fromkeys(wl + exp) if c not in excluded]
        skipped_excluded = [c for c in dict.fromkeys(wl + exp) if c in excluded]
        log(f"적출 대상 {len(codes)}개 (제외 {len(skipped_excluded)}개 스킵)")

        names = stock_names(session, codes)

        results: list[se.StockResult] = []
        for code in codes:
            df = load_ohlcv(session, code, as_of)
            results.append(se.classify_stock(df, code, names.get(code, "")))

        # 압축용 랭크: 최근 평균 거래대금
        rank_rows = session.execute(
            text(
                """
                SELECT stock_code, AVG(CASE WHEN value IS NOT NULL THEN value
                                            ELSE close_price*volume END) AS av
                FROM daily_prices WHERE trading_date <= :asof GROUP BY stock_code
                """
            ),
            {"asof": as_of},
        ).all()
        rank_map = {r[0]: float(r[1] or 0) for r in rank_rows}

        report = se.build_report(
            results,
            as_of,
            compress_to=args.compress,
            rank_key=lambda c: rank_map.get(c, 0.0),
        )
        report["expansionInsufficient"] = insuff_cnt
        report["excludedSkipped"] = skipped_excluded

        # 요약 로그
        cats = report["categories"]
        inds = report["indicators"]
        log(
            "분류수 | "
            + " ".join(f"{k}={len(v)}" for k, v in cats.items())
        )
        log("지표수 | " + " ".join(f"{k}={len(v)}" for k, v in inds.items()))
        log(f"집중약세(3회+) {len(report['concentrated'])}개: {list(report['concentrated'].items())[:10]}")

        if args.do_print:
            import json

            print(json.dumps(report, ensure_ascii=False, indent=2)[:4000])

        if not args.no_store:
            flagged = len(report["frequency"])
            existing = (
                session.query(models.DailyScreenerResult)
                .filter(models.DailyScreenerResult.scan_date == as_of)
                .one_or_none()
            )
            if existing:
                existing.payload = report
                existing.universe_total = report["universe"]["total"]
                existing.universe_scored = report["universe"]["scored"]
                existing.flagged_count = flagged
            else:
                session.add(
                    models.DailyScreenerResult(
                        scan_date=as_of,
                        universe_total=report["universe"]["total"],
                        universe_scored=report["universe"]["scored"],
                        flagged_count=flagged,
                        payload=report,
                    )
                )
            session.commit()
            log(f"저장 완료 daily_screener_results scan_date={as_of} flagged={flagged}")
        log("스크리너 완료")
    finally:
        session.close()


if __name__ == "__main__":
    main()
