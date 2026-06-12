"""short_selling_sync.py

매일 18:40 실행 (Windows 작업 스케줄러 — install-short-selling-sync-task.ps1).

대상: stocks 테이블 전 종목.
동작:
  1. KIS 공매도 일별추이(T+1) → short_selling_daily upsert (거래량/비중)
  2. KRX_ID/KRX_PW 설정 시 KRX 공매도 잔고(T+2) upsert + KIS↔KRX 거래량 교차검증
     (미설정이면 잔고는 건너뛰고 거래량만 — 급증 판정은 거래량 기준으로 동작)
  3. 결과를 logs/short-selling-sync.log 에 기록

KIS는 읽기 전용(시세 조회)만 사용 — 주문/거래 없음(킬스위치 무관).

사용법:
  python scripts/short_selling_sync.py            # 최근 30일 구간 동기화
  python scripts/short_selling_sync.py --days 60  # 백필 구간 지정
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select, text  # noqa: E402

import db as apollo_db  # noqa: E402
import models  # noqa: E402
import short_selling  # noqa: E402
from settings import settings  # noqa: E402


def _all_codes(s) -> list[str]:
    return [str(c) for c in s.execute(select(models.Stock.code).order_by(models.Stock.code)).scalars().all()]


def _admin_profile(s):
    return s.execute(select(models.KisProfile).where(models.KisProfile.user_id == 1)).scalar_one_or_none()


def _append_log(logf: Path, lines: list[str]) -> None:
    try:
        logf.parent.mkdir(parents=True, exist_ok=True)
        with logf.open("a", encoding="utf-8") as f:
            for line in lines:
                f.write(line + "\n")
    except Exception:
        pass


def main() -> int:
    days = 30
    if "--days" in sys.argv:
        try:
            days = max(5, int(sys.argv[sys.argv.index("--days") + 1]))
        except (IndexError, ValueError):
            pass

    now = datetime.now()
    logf = Path(__file__).resolve().parents[1] / "logs" / "short-selling-sync.log"
    _append_log(logf, [f"[{now.isoformat(timespec='seconds')}] START days={days}"])

    s = apollo_db.get_session_factory()()
    try:
        codes = _all_codes(s)
        # 거래 제외 종목은 공매도 데이터를 저장하지 않는다 (인덱스만 유지 원칙)
        try:
            import exclusion_engine  # noqa: E402

            codes = exclusion_engine.filter_codes(s, codes)
        except Exception:
            pass
        prof = _admin_profile(s)
        if not codes:
            msg = "stocks 테이블 비어 있음 — 종료"
            print(msg)
            _append_log(logf, [f"[{now.isoformat(timespec='seconds')}] ERROR {msg}"])
            return 1
        if prof is None or not prof.app_key:
            msg = "관리자 KIS 프로필 없음 — 종료"
            print(msg)
            _append_log(logf, [f"[{now.isoformat(timespec='seconds')}] ERROR {msg}"])
            return 1

        # 1. KIS 공매도 거래량/비중
        try:
            kis_ok, kis_rows, kis_failed = short_selling.sync_kis_short_sale(
                s, codes,
                app_key=str(prof.app_key),
                app_secret=str(prof.app_secret),
                is_paper=False,
                live_base_url=settings.kis_live_base_url,
                paper_base_url=settings.kis_paper_base_url,
                days=days,
            )
        except Exception as exc:
            _append_log(logf, [f"[{now.isoformat(timespec='seconds')}] CRASH sync_kis_short_sale: {exc}"])
            raise

        # 2. KRX 잔고 (자격증명 있을 때만) + 교차검증
        end = date.today()
        start = end - timedelta(days=days)
        if short_selling.krx_credentials_available():
            try:
                krx_ok, krx_rows, krx_failed, mismatches = short_selling.sync_krx_balance(
                    s, codes, start=start, end=end,
                )
                krx_note = f" krx(ok={krx_ok} rows={krx_rows} fail={len(krx_failed)} mismatch={len(mismatches)})"
            except Exception as exc:
                _append_log(logf, [f"[{now.isoformat(timespec='seconds')}] CRASH sync_krx_balance: {exc}"])
                raise
        else:
            mismatches = []
            krx_note = " krx(SKIP — KRX_ID/KRX_PW 미설정, 잔고 미수집)"

        total_rows = s.execute(text("SELECT COUNT(*) FROM short_selling_daily")).scalar()
    finally:
        s.close()

    header = (
        f"[{now.isoformat(timespec='seconds')}] kis(ok={kis_ok}/{len(codes)} rows={kis_rows} "
        f"fail={len(kis_failed)}){krx_note} table_total={total_rows}"
    )

    lines = [header] + [f"   KIS-FAIL {c}" for c in kis_failed] + [f"   {m}" for m in mismatches]
    _append_log(logf, lines)

    print(header)
    for c in kis_failed[:20]:
        print(f"  KIS-FAIL {c}")
    for m in mismatches[:20]:
        print(f"  {m}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
