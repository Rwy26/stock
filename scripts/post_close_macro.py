"""미 정규장 마감 직후 글로벌 매크로 투자심리 재계산 (예약작업 MOON-STOCK-PostClose-Macro).

목적: 미 정규장(16:00 ET) 마감 직후 운영 백엔드(포트 8000)의 인메모리 매크로 캐시를
강제로 데워서 화면 헤더 asOf 타임스탬프가 사람이 열지 않아도 자동 갱신되게 한다.

마감 시각(KST) — 미 동부 서머타임에 따라 달라진다:
  - EDT(여름): 16:00 ET = 익일 05:00 KST  → KST 05시대 트리거에만 실행
  - EST(겨울): 16:00 ET = 익일 06:00 KST  → KST 06시대 트리거에만 실행
예약작업은 05:10 / 06:10 두 트리거를 모두 걸어두고, 이 스크립트가 DST를 자가 게이트해
둘 중 하나만 실효시킨다(나머지는 즉시 no-op 종료).

with_ai=False(LLM 비용 0) read-only warm 엔드포인트만 호출한다 — 주문·autotrade 불가침.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx  # noqa: E402

LOG = REPO / "logs" / "post-close-macro.log"
BASE = "http://127.0.0.1:8000"
WARM_PATH = "/api/public/macro-warm"


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

    log(f"실행: 미동부={tz_label}, 마감 직후(KST {kst_hour}시대) → macro warm 호출")
    try:
        r = httpx.get(BASE + WARM_PATH, timeout=120)
        r.raise_for_status()
        as_of = r.json().get("asOf")
        log(f"macro warm OK — asOf={as_of}")
        return 0
    except Exception as exc:  # noqa: BLE001
        log(f"macro warm FAIL: {type(exc).__name__} {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
