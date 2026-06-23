"""공유(게스트) 읽기 계층 정적 스냅샷 빌더 — 리포트/공유 계층.

Phase A: AI 그래프(/api/public/stock-graph) — 결정론 30분 캐시 산출물을 정적화.
(후속 Phase: ai-history 인덱스, 종목별 리포트 샤딩)

대시보드 빌더(build_dashboard_snapshots.py)와 같은 패턴:
  - 실행 중 백엔드(포트 8000)의 공개 엔드포인트(무인증)를 호출해 같은 로직 재사용
  - backend/static/snapshots/public-*.json 으로 원자적 기록(main.py /static/snapshots 서빙)
  - 파일마다 메타(updated_at·count·source·stale), 조회 실패/빈데이터면 직전본 유지·미발행

스케줄: 30분 배치(install-public-snapshots-task.ps1) + morning_prep 워밍 직후 1회.
공유 계층은 매매·예측 경로와 무접촉(공개 읽기 전용).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass

REPO = Path(__file__).resolve().parents[1]
SNAP_DIR = REPO / "backend" / "static" / "snapshots"
LOG = REPO / "logs" / "public-snapshots.log"
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
    for key in ("nodes", "items", "sectors"):
        v = data.get(key)
        if isinstance(v, list):
            return len(v)
    return 1 if data else 0


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def _mark_stale(path: Path, reason: str) -> None:
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


def build_one(filename: str, api_path: str, source: str, min_rows: int = 1) -> bool:
    out = SNAP_DIR / filename
    try:
        r = httpx.get(BASE + api_path, timeout=120.0)  # 그래프 빌드는 느릴 수 있음
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
    log(f"{filename} OK — rows={rows}")
    return True


def main() -> int:
    log("=== 공유 계층 스냅샷 빌드 시작 ===")
    SNAP_DIR.mkdir(parents=True, exist_ok=True)

    results = [
        # AI 관계 그래프 — graph_engine 결정론 산출(30분 캐시), 무인증.
        build_one("public-stock-graph.json", "/api/public/stock-graph",
                  source="graph_engine", min_rows=1),
    ]

    try:
        version = {
            "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
            "files": ["public-stock-graph.json"],
            "ok_count": sum(1 for x in results if x),
        }
        _atomic_write_json(SNAP_DIR / "version-public.json", version)
    except Exception as exc:  # noqa: BLE001
        log(f"version-public.json FAIL — {type(exc).__name__} {exc}")

    ok = all(results)
    log(f"=== 빌드 {'완료' if ok else '일부 실패 — 직전본 유지'} ({sum(results)}/{len(results)}) ===")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
