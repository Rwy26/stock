"""check_scoring_freshness.py — IndicatorScore 최신일 신선도 점검(재발 조기 감지).

3-Tier 스코어링(IndicatorScore)은 추천·주도주의 근거 데이터인데, 자동 스케줄
(MOON-STOCK-Scoring, run_scoring.py)이 멈추면 조용히 정체된다. morning-check 가 이
스크립트를 호출해 IndicatorScore 가 N일 이상 묵으면 WARN 으로 조기 감지한다.

출력(stdout 1줄):
  IndicatorScore latest=YYYY-MM-DD (Nd stale, rows=…)
  IndicatorScore EMPTY (no rows)

종료코드: 신선(<= max-age일)=0, 정체/비어있음=1.

사용법:
  python scripts/check_scoring_freshness.py            # 기본 3일 임계
  python scripts/check_scoring_freshness.py --max-age 2
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))


def main() -> int:
    ap = argparse.ArgumentParser(description="IndicatorScore 신선도 점검")
    ap.add_argument("--max-age", type=int, default=3, help="허용 최대 경과일(기본 3)")
    args = ap.parse_args()

    from sqlalchemy import func, select  # noqa: E402

    import db as apollo_db  # noqa: E402
    import models  # noqa: E402

    s = apollo_db.get_session_factory()()
    try:
        latest = s.execute(select(func.max(models.IndicatorScore.scoring_date))).scalar_one_or_none()
        if latest is None:
            print("IndicatorScore EMPTY (no rows)")
            return 1
        rows = s.execute(
            select(func.count()).select_from(models.IndicatorScore).where(
                models.IndicatorScore.scoring_date == latest
            )
        ).scalar_one()
    finally:
        s.close()

    stale = (date.today() - latest).days
    print(f"IndicatorScore latest={latest.isoformat()} ({stale}d stale, rows={rows})")
    return 0 if stale <= args.max_age else 1


if __name__ == "__main__":
    raise SystemExit(main())
