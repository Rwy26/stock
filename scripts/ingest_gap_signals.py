"""시초가 갭 신호 적재 스크립트 — premarket-scanner 결과를 MOON STOCK DB로 올린다.

소스: C:\\Users\\MOON\\premarket-scanner\\kr_gap_gappers_YYYY-MM-DD.json
  (kr_gap_scanner.sh 가 생성 — 네이버 모바일 API 기반 시초가 갭 + 뉴스 촉매)
  소스는 건드리지 않는다. 이 스크립트는 읽기만 한다.

동작:
  - 기본(ingest, 09:05): 스캐너 JSON 의 gappers 를 검증·네이버 siseJson 재확인 후 적재.
  - --reconcile (16:15, daily_prices 16:10 이후): 저장된 신호를 확정 siseJson 기준 재확인.

가드레일은 backend/gap_signal_intake.py 가 적용한다(촉매 미검증 고정 · siseJson 우선 ·
exclusion_engine 경유 완전제외+인덱스만).

사용법:
  .\\backend\\.venv\\Scripts\\python.exe scripts\\ingest_gap_signals.py [--reconcile]
      [--file PATH] [--session-date YYYY-MM-DD] [--scanner-dir DIR]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from db import get_session_factory  # noqa: E402
import gap_signal_intake  # noqa: E402

DEFAULT_SCANNER_DIR = Path.home() / "premarket-scanner"
LOG_FILE = REPO_ROOT / "logs" / "ingest_gap_signals.log"
_FNAME_RE = re.compile(r"kr_gap_gappers_(\d{4}-\d{2}-\d{2})\.json$")


def _log(line: str) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {line}\n")
    except Exception:
        pass


def _find_scanner_file(scanner_dir: Path, session_date: date | None, explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if p.exists() else None
    if session_date is not None:
        cand = scanner_dir / f"kr_gap_gappers_{session_date.isoformat()}.json"
        if cand.exists():
            return cand
    files = sorted(scanner_dir.glob("kr_gap_gappers_*.json"))
    return files[-1] if files else None


def _session_date_from(path: Path, override: str | None) -> date:
    if override:
        return datetime.strptime(override.strip(), "%Y-%m-%d").date()
    m = _FNAME_RE.search(path.name)
    if m:
        return datetime.strptime(m.group(1), "%Y-%m-%d").date()
    return date.today()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reconcile", action="store_true",
                        help="적재 대신 저장된 신호를 확정 siseJson 기준으로 재확인")
    parser.add_argument("--file", help="스캐너 JSON 파일 경로 (생략 시 자동 탐색)")
    parser.add_argument("--session-date", help="세션 거래일 YYYY-MM-DD (생략 시 파일명/오늘)")
    parser.add_argument("--scanner-dir", help=f"스캐너 디렉터리 (기본 {DEFAULT_SCANNER_DIR})")
    args = parser.parse_args()

    scanner_dir = Path(args.scanner_dir) if args.scanner_dir else DEFAULT_SCANNER_DIR
    override_date = args.session_date

    # reconcile 모드: 파일 없이 session_date 만으로 동작
    if args.reconcile:
        session_date = (datetime.strptime(override_date.strip(), "%Y-%m-%d").date()
                        if override_date else date.today())
        db = get_session_factory()()
        try:
            result = gap_signal_intake.reconcile_signals(db, session_date)
        finally:
            db.close()
        print(f"[reconcile] {result}")
        _log(f"reconcile {result}")
        return 0

    # ingest 모드
    path = _find_scanner_file(scanner_dir, None, args.file)
    if path is None:
        msg = f"스캐너 JSON 없음 (dir={scanner_dir}, file={args.file})"
        print(f"[ingest] FAIL {msg}")
        _log(f"ingest FAIL {msg}")
        return 1

    session_date = _session_date_from(path, override_date)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[ingest] FAIL JSON 파싱 실패 {path}: {exc}")
        _log(f"ingest FAIL parse {path}: {exc}")
        return 1

    gappers = data.get("gappers")
    if not isinstance(gappers, list):
        print(f"[ingest] FAIL gappers 배열 없음: {path}")
        _log(f"ingest FAIL no-gappers {path}")
        return 1

    db = get_session_factory()()
    try:
        result = gap_signal_intake.ingest_gappers(db, gappers, session_date)
    finally:
        db.close()
    print(f"[ingest] {path.name} → {result}")
    _log(f"ingest {path.name} {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
