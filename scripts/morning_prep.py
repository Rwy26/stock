"""아침 서비스 준비 (매일 06:30, 작업 스케줄러 MOON-STOCK-MorningPrep).

목표: 07:00 이전에 모든 공개/관리자 서비스가 직전 영업일 데이터로 완전히 준비된 상태.
(한국 증시는 정규장 전 시간외 거래가 있으므로 장전에도 화면이 살아 있어야 한다)

순서:
  1. 직전 영업일 등락률 스냅샷 갱신 (KIS 일봉 — 휴일이어도 마지막 두 영업일 종가로 계산)
     → 장전/휴장에 등락률이 0이면 이 스냅샷이 화면 색을 채운다 (quoteBasis=prevClose)
  2. 캐시 워밍: 관심종목 / 섹터 나침반 / ETF 시세 — 첫 방문자가 기다리지 않도록
  3. 검증: 응답 정상 + 등락률 표시 가능 여부 확인 → logs/morning-prep.log

06:00 fundamentals_sync(데이터 확인) 이후에 실행되도록 06:30 스케줄.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx  # noqa: E402

LOG = REPO / "logs" / "morning-prep.log"
BASE = "http://127.0.0.1:8000"


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
    ok = True
    log("=== 아침 준비 시작 ===")

    # 1) 직전 영업일 스냅샷 갱신
    try:
        import backfill_last_session
        rc = backfill_last_session.main()
        log(f"스냅샷 갱신 {'OK' if rc == 0 else 'FAIL rc=' + str(rc)}")
        ok = ok and rc == 0
    except Exception as exc:  # noqa: BLE001
        log(f"스냅샷 갱신 FAIL: {type(exc).__name__} {exc}")
        ok = False

    # 2) 캐시 워밍 + 3) 검증
    warm = [
        ("관심종목", "/api/public/watchlist", 120),
        ("ETF 시세", "/api/public/etf-quotes", 60),
        ("섹터 나침반", "/api/public/sector-rotation", 600),
    ]
    for name, path, to in warm:
        try:
            r = httpx.get(BASE + path, timeout=to)
            r.raise_for_status()
            d = r.json()
            note = ""
            if path.endswith("watchlist"):
                items = d.get("items", [])
                nz = sum(1 for it in items if abs(float(it.get("changeRate") or 0)) > 1e-9)
                note = f" — {len(items)}종목, 등락률 표시 {nz}건, 기준={d.get('quoteBasis')}"
                if nz == 0:
                    note += " ⚠ 전 종목 0% (스냅샷 폴백 실패)"
                    ok = False
            elif path.endswith("sector-rotation"):
                note = f" — {len(d.get('sectors', []))}개 섹터, asOf={d.get('asOf')}"
            log(f"{name} 워밍 OK{note}")
        except Exception as exc:  # noqa: BLE001
            log(f"{name} 워밍 FAIL: {type(exc).__name__}")
            ok = False

    log(f"=== 아침 준비 {'완료' if ok else '일부 실패 — 점검 필요'} ===")
    return 0 if ok else 1


if __name__ == "__main__":
    time.sleep(65)  # KIS 토큰 발급 1분 제한 (06:00 sync 와 토큰 충돌 방지)
    raise SystemExit(main())
