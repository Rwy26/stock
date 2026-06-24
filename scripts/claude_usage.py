"""claude(MAX) 자동 호출 사용량 공유 원장 — logs/claude-usage.json.

배치(batch_analyze.py)와 idle 필러(idle_narrative_filler.ps1)가 같은 파일·같은 캡으로
claude 호출 수를 누적해, '어느 경로가 쓰든' 자동 claude 사용량을 하나의 예산으로 묶어
제한한다(MAX 5시간/주간 한도 보호). 사용자의 인터랙티브 사용은 카운트되지 않는다.

스키마(PS 필러와 동일):
  { "week": "2026-W26", "weekCount": 0, "day": "2026-06-24", "dayCount": 0, "updatedAt": "..." }
ISO 주/일 경계가 바뀌면 해당 카운터를 0으로 리셋한다.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
USAGE_FILE = _REPO / "logs" / "claude-usage.json"


def _stamp() -> tuple[str, str]:
    now = datetime.now()
    iso_year, iso_week, _ = now.isocalendar()
    return f"{iso_year}-W{iso_week:02d}", now.strftime("%Y-%m-%d")


def read() -> dict:
    """현재 사용량(주/일 경계 자동 리셋 반영). 파일 없거나 손상 시 0 기준 반환."""
    week, day = _stamp()
    u = {"week": week, "weekCount": 0, "day": day, "dayCount": 0, "updatedAt": ""}
    try:
        raw = json.loads(USAGE_FILE.read_text(encoding="utf-8"))
        if raw.get("week") == week:
            u["weekCount"] = int(raw.get("weekCount") or 0)
        if raw.get("day") == day:
            u["dayCount"] = int(raw.get("dayCount") or 0)
    except FileNotFoundError:
        pass
    except Exception:  # noqa: BLE001 — 손상 파일은 0 기준으로 재시작
        pass
    return u


def record(n: int = 1) -> dict:
    """claude 호출 n건 누적 후 원장에 저장(원자적 교체). 갱신된 사용량 반환."""
    u = read()
    u["weekCount"] += n
    u["dayCount"] += n
    u["updatedAt"] = datetime.now().isoformat(timespec="seconds")
    try:
        USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(USAGE_FILE.parent), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(u, f, ensure_ascii=False)
        os.replace(tmp, USAGE_FILE)  # 같은 볼륨 → 원자적
    except Exception:  # noqa: BLE001
        pass
    return u


def exhausted(daily_cap: int, weekly_cap: int, usage: dict | None = None) -> bool:
    """일/주 캡 중 하나라도 도달했으면 True. usage 미지정 시 현재 원장 조회."""
    u = usage if usage is not None else read()
    if weekly_cap > 0 and u.get("weekCount", 0) >= weekly_cap:
        return True
    if daily_cap > 0 and u.get("dayCount", 0) >= daily_cap:
        return True
    return False
