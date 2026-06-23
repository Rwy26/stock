"""미 정규장 마감 직후 대시보드 읽기계층 스냅샷 1회 보강 (예약작업 MOON-STOCK-PostClose-Macro).

목적: 미 정규장(16:00 ET) 마감 직후 `build_dashboard_snapshots.py` 를 1회 실행해
backend/static/snapshots/*.json (글로벌 매크로·미국채·DXY 등)을 즉시 갱신한다.
30분 배치 사이 마감직후 신선도를 메우는 보강 트리거 — 화면 asOf(스냅샷 봉투 updated_at)가
사람이 열지 않아도 마감 직후 값으로 자동 갱신된다.

마감 시각(KST) — 미 동부 서머타임에 따라 달라진다:
  - EDT(여름): 16:00 ET = 익일 05:00 KST  → KST 05시대 트리거에만 실행
  - EST(겨울): 16:00 ET = 익일 06:00 KST  → KST 06시대 트리거에만 실행
예약작업은 05:10 / 06:10 두 트리거를 모두 걸어두고, 이 스크립트가 DST를 자가 게이트해
둘 중 하나만 실효시킨다(나머지는 즉시 no-op 종료).

별도 warm 엔드포인트는 더 이상 호출하지 않는다(정적 스냅샷 표준으로 통합 — 중복 제거).
빌더는 무인증 공개 read 엔드포인트만 호출하고 깨진 값은 발행하지 않는다(직전본 유지).
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

LOG = REPO / "logs" / "post-close-macro.log"


def log(msg: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def main() -> int:
    # 미 동부 현재 DST 판정
    ny_now = datetime.now(ZoneInfo("America/New_York"))
    is_edt = bool(ny_now.dst())  # EDT면 dst() != 0
    kst_hour = datetime.now(ZoneInfo("Asia/Seoul")).hour

    # EDT → 05시대 트리거만, EST → 06시대 트리거만 실행
    want_hour = 5 if is_edt else 6
    tz_label = "EDT(여름)" if is_edt else "EST(겨울)"

    if kst_hour != want_hour:
        log(
            f"no-op: 미동부={tz_label}, 마감=KST {want_hour}시대 → 현재 KST {kst_hour}시대 트리거는 건너뜀"
        )
        return 0

    log(f"실행: 미동부={tz_label}, 마감 직후(KST {kst_hour}시대) → 대시보드 스냅샷 1회 보강")
    try:
        import build_dashboard_snapshots
        rc = build_dashboard_snapshots.main()
        log(f"스냅샷 보강 완료 rc={rc}")
        return rc
    except Exception as exc:  # noqa: BLE001
        log(f"스냅샷 보강 FAIL: {type(exc).__name__} {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
