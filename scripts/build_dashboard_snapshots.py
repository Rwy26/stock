"""대시보드 읽기 계층 정적 스냅샷 빌더 (Phase 1: 매크로 차트).

목표: 매 요청마다 yfinance를 때리던 매크로 차트(us-bonds, dxy)를
배치가 1회 생성한 정적 JSON 스냅샷으로 대체한다.
  - 실행 중 백엔드(포트 8000)의 기존 엔드포인트를 호출해 정확히 같은 계산 로직 재사용
  - 결과를 backend/static/snapshots/*.json 으로 원자적 기록 (main.py 가 /static/snapshots 로 서빙)
  - 파일마다 메타(updated_at·count·source·stale), version.json 으로 신선도/배포 게이트

데이터 정확성 원칙(돈 다루는 시스템): 조회 실패·빈 데이터면 새 파일을 쓰지 않고
직전 정상본을 유지한다. 깨진 값을 절대 발행하지 않는다(stale 로깅만).

스케줄: scripts/install-dashboard-snapshots-task.ps1 (30분 간격) + morning_prep 끝에 1회.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx

# Windows 콘솔(cp949)에서 em-dash 등 비-Hangul 유니코드 출력 시 인코딩 깨짐 방지.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass

REPO = Path(__file__).resolve().parents[1]
SNAP_DIR = REPO / "backend" / "static" / "snapshots"
LOG = REPO / "logs" / "dashboard-snapshots.log"
BASE = os.environ.get("MOONSTOCK_BASE", "http://127.0.0.1:8000")
KST = timezone(timedelta(hours=9))


def log(msg: str) -> None:
    line = f"[{datetime.now(KST).isoformat(timespec='seconds')}] {msg}"
    print(line)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _count_rows(data: dict) -> int:
    """대표 시계열 행수(신선도 1차 게이트용)."""
    for key in ("tnx", "ohlcv", "items"):
        v = data.get(key)
        if isinstance(v, list):
            return len(v)
    return 0


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)  # 원자적 교체


def build_one(filename: str, api_path: str, source: str, min_rows: int = 1) -> bool:
    """엔드포인트 1개를 스냅샷 파일 1개로. 성공 시 True.

    실패/빈 데이터면 새 파일을 쓰지 않고(직전본 유지) 직전본을 stale 로 표시만 한다.
    """
    out = SNAP_DIR / filename
    try:
        r = httpx.get(BASE + api_path, timeout=30.0)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        _mark_stale(out, reason=f"fetch failed: {type(exc).__name__}")
        log(f"{filename} FAIL — {type(exc).__name__} {exc} (직전본 유지)")
        return False

    rows = _count_rows(data)
    if rows < min_rows:
        _mark_stale(out, reason=f"empty data (rows={rows})")
        log(f"{filename} FAIL — 빈 데이터 rows={rows} (직전본 유지, 미발행)")
        return False

    payload = {
        "updated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "count": rows,
        "source": source,
        "stale": False,
        "data": data,
    }
    _atomic_write_json(out, payload)
    log(f"{filename} OK — rows={rows}, asOf={data.get('asOf')}")
    return True


def _mark_stale(path: Path, reason: str) -> None:
    """직전 정상본이 있으면 stale=true 로만 표시(데이터는 보존). 없으면 아무것도 안 함."""
    if not path.exists():
        return
    try:
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        payload["stale"] = True
        payload["stale_reason"] = reason
        payload["stale_at"] = datetime.now(KST).isoformat(timespec="seconds")
        _atomic_write_json(path, payload)
    except Exception:
        pass


def main() -> int:
    log("=== 대시보드 스냅샷 빌드 시작 ===")
    SNAP_DIR.mkdir(parents=True, exist_ok=True)

    results = [
        build_one("dashboard-macro-us-bonds.json", "/api/macro/us-bonds",
                  source="yfinance:^TNX,^TYX", min_rows=2),
        build_one("dashboard-macro-dxy.json", "/api/macro/dxy",
                  source="yfinance:DX-Y.NYB", min_rows=2),
        # Top 추천 — 공개 추천 엔드포인트(무인증·DB·네이버 검증명·실시간가 없음).
        # 추천이 비어도(장전·배치 전) 오늘 날짜와 함께 정직하게 발행(min_rows=0).
        build_one("dashboard-top-recommendations.json", "/api/public/recommendations",
                  source="recommendations_db", min_rows=0),
    ]

    # version.json — 프론트가 가장 싸게 폴링해 신선도/배포를 감지
    try:
        version = {
            "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
            "files": [
                "dashboard-macro-us-bonds.json",
                "dashboard-macro-dxy.json",
                "dashboard-top-recommendations.json",
            ],
            "ok_count": sum(1 for x in results if x),
        }
        _atomic_write_json(SNAP_DIR / "version.json", version)
    except Exception as exc:  # noqa: BLE001
        log(f"version.json FAIL — {type(exc).__name__} {exc}")

    ok = all(results)
    log(f"=== 빌드 {'완료' if ok else '일부 실패 — 직전본 유지'} ({sum(results)}/{len(results)}) ===")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
