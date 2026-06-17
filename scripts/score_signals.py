"""score_signals.py

AI 시그널 적중 추적 — 야간 채점 (1단계).

signal_outcomes 테이블에서 scored_at IS NULL 인 예측 행을 골라,
예측 시점(predicted_at, UTC naive → KST +9h) 이후의 **다음 거래일 종가**가
daily_prices 에 적재되어 있으면 채점한다.

채점:
  ret_1d  = next_close / entry_close - 1
  ret_5d  = (예측일 기준 5번째 거래일 종가가 있으면) close5 / entry_close - 1, 없으면 null
  kospi_ret_1d = 069500(KODEX200) 같은 구간 수익률 (069500 일봉 없으면 null)
  alpha_1d = ret_1d - kospi_ret_1d (kospi 없으면 null)
  hit_1d:
    BUY/STRONG_BUY  → (alpha_1d 있으면 alpha, 없으면 ret_1d) > +0.003
    SELL/STRONG_SELL→ (동상) < -0.003
    HOLD            → |동상| <= 0.003
  scored_at = utcnow()

룩어헤드 금지: entry_close 는 예측 시점 마지막 종가(분석 결과에 기록됨), next/5d 는
예측한 거래일(KST) **다음** 거래일부터의 종가만 사용한다.

사용법:
  python scripts/score_signals.py            # 채점 실행
  python scripts/score_signals.py --dry-run  # 계산만, DB 미반영
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402

import db as apollo_db  # noqa: E402
import models  # noqa: E402

KOSPI_PROXY = "069500"  # KODEX200 (KOSPI 지수 프록시)
HIT_THRESHOLD = 0.003


def _kst_date(predicted_at: datetime):
    """predicted_at(UTC naive) → KST 달력 날짜."""
    return (predicted_at + timedelta(hours=9)).date()


def _trading_rows_after(session, code: str, after_date):
    """code 의 after_date(포함 안 함) 이후 거래일 종가를 날짜 오름차순으로 반환."""
    rows = session.execute(
        select(models.DailyPrice.trading_date, models.DailyPrice.close_price)
        .where(models.DailyPrice.stock_code == code)
        .where(models.DailyPrice.trading_date > after_date)
        .order_by(models.DailyPrice.trading_date.asc())
    ).all()
    return [(d, float(c)) for d, c in rows if c is not None]


def _kospi_segment_ret(session, start_date, end_date):
    """KODEX200 의 start_date→end_date 구간 수익률. 두 종가 모두 있어야 함."""
    px = {}
    for d in (start_date, end_date):
        c = session.execute(
            select(models.DailyPrice.close_price)
            .where(models.DailyPrice.stock_code == KOSPI_PROXY)
            .where(models.DailyPrice.trading_date == d)
        ).scalar_one_or_none()
        if c is None:
            return None
        px[d] = float(c)
    if not px.get(start_date):
        return None
    return px[end_date] / px[start_date] - 1


def score_pending(dry_run: bool = False) -> dict:
    session = apollo_db.get_session_factory()()
    stats = {"candidates": 0, "scored": 0, "skipped_no_next_close": 0,
             "skipped_no_entry": 0, "with_alpha": 0, "with_ret5": 0, "hits": 0}
    try:
        pending = session.execute(
            select(models.SignalOutcome)
            .where(models.SignalOutcome.scored_at.is_(None))
            .order_by(models.SignalOutcome.predicted_at.asc())
        ).scalars().all()
        stats["candidates"] = len(pending)

        for row in pending:
            if row.entry_close is None or not row.entry_close:
                stats["skipped_no_entry"] += 1
                continue

            pred_date = _kst_date(row.predicted_at)
            future = _trading_rows_after(session, row.stock_code, pred_date)
            if not future:
                stats["skipped_no_next_close"] += 1
                continue

            next_date, next_close = future[0]
            ret_1d = next_close / row.entry_close - 1

            # KOSPI 같은 구간(pred_date → next_date) 프록시 수익률.
            kospi_ret = _kospi_segment_ret(session, pred_date, next_date)
            alpha_1d = (ret_1d - kospi_ret) if kospi_ret is not None else None

            # 5일 수익률 (예측일 기준 5번째 거래일 종가가 있을 때만)
            ret_5d = None
            if len(future) >= 5:
                ret_5d = future[4][1] / row.entry_close - 1
                stats["with_ret5"] += 1

            basis = alpha_1d if alpha_1d is not None else ret_1d
            sig = (row.signal or "").upper()
            if sig in ("BUY", "STRONG_BUY"):
                hit = basis > HIT_THRESHOLD
            elif sig in ("SELL", "STRONG_SELL"):
                hit = basis < -HIT_THRESHOLD
            else:  # HOLD (및 미지정)
                hit = abs(basis) <= HIT_THRESHOLD

            if alpha_1d is not None:
                stats["with_alpha"] += 1
            if hit:
                stats["hits"] += 1
            stats["scored"] += 1

            if dry_run:
                print(f"[dry] {row.stock_code} {row.signal} pred={pred_date} "
                      f"next={next_date} entry={row.entry_close:.2f} next={next_close:.2f} "
                      f"ret_1d={ret_1d:+.4f} alpha_1d="
                      f"{('%.4f' % alpha_1d) if alpha_1d is not None else 'NA'} hit={hit}")
                continue

            row.next_close = next_close
            row.ret_1d = ret_1d
            row.ret_5d = ret_5d
            row.kospi_ret_1d = kospi_ret
            row.alpha_1d = alpha_1d
            row.hit_1d = bool(hit)
            row.scored_at = datetime.utcnow()

        if not dry_run:
            session.commit()
    finally:
        session.close()
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="계산만, DB 미반영")
    args = ap.parse_args()

    stats = score_pending(dry_run=args.dry_run)
    mode = "DRY-RUN" if args.dry_run else "COMMIT"
    print(f"[score_signals {mode}] {datetime.utcnow().isoformat()}Z")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    if stats["scored"]:
        print(f"  hit_rate: {stats['hits'] / stats['scored']:.1%}")


if __name__ == "__main__":
    main()
