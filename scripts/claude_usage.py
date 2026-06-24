"""claude(MAX) 자동 호출 사용량 공유 원장 — logs/claude-usage.json.

배치(batch_analyze.py)와 idle 필러(idle_narrative_filler.ps1), 백엔드 서버가 같은 파일에
claude 호출을 누적해, '어느 경로가 쓰든' 자동 claude 사용량을 하나의 예산으로 묶어
제한한다(MAX 5시간 롤링 한도 보호). 사용자의 인터랙티브 사용은 카운트되지 않는다.

예산 모델(2026-06 공격적 전환):
  - 핵심 게이트는 **롤링 5시간 창**. 각 claude 성공 호출의 (타임스탬프, 소요초)를 events 에
    누적하고, 최근 window_sec(기본 5h) 안에 쌓인 소요초 합이 capacity_sec 의 use_ratio
    (기본 97%)에 도달하면 그 창 동안만 claude 를 끈다(gemini/groq 강등). 시간이 흐르며 오래된
    이벤트가 창 밖으로 빠지면 자동 재개된다 — 일/주 카운트 캡(레거시)을 대체한다.
  - weekCount/dayCount 는 표시·관찰용으로만 유지(게이트 아님).

스키마:
  {
    "week": "2026-W26", "weekCount": 0, "day": "2026-06-25", "dayCount": 0,
    "updatedAt": "...",
    "events": [[<epoch_sec>, <duration_sec>], ...]   # 최근 RETENTION_SEC 만 보관
  }
ISO 주/일 경계가 바뀌면 해당 카운터를 0으로 리셋한다(events 는 시간 기반이라 무관).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
USAGE_FILE = _REPO / "logs" / "claude-usage.json"

# events 보관 한도 — 롤링 창(기본 5h)에 넉넉한 여유를 둬 게이트 판정에 필요한 이벤트가
# 조기 삭제되지 않게 한다. 풀리포트 1건 ≈ 190s 라 24h 라도 파일은 수십 KB 미만으로 유지된다.
RETENTION_SEC = 24 * 3600


def _stamp() -> tuple[str, str]:
    now = datetime.now()
    iso_year, iso_week, _ = now.isocalendar()
    return f"{iso_year}-W{iso_week:02d}", now.strftime("%Y-%m-%d")


def _prune(events: list, now: float | None = None) -> list:
    """RETENTION_SEC 보다 오래된 이벤트 제거. 형식 이상치는 조용히 버린다."""
    now = time.time() if now is None else now
    out = []
    for e in events or []:
        try:
            ts = float(e[0])
            sec = float(e[1])
        except (TypeError, ValueError, IndexError):
            continue
        if now - ts <= RETENTION_SEC:
            out.append([ts, sec])
    return out


def read() -> dict:
    """현재 사용량(주/일 경계 자동 리셋 + events 프루닝 반영). 파일 없거나 손상 시 0 기준."""
    week, day = _stamp()
    u = {"week": week, "weekCount": 0, "day": day, "dayCount": 0, "updatedAt": "", "events": []}
    try:
        raw = json.loads(USAGE_FILE.read_text(encoding="utf-8"))
        if raw.get("week") == week:
            u["weekCount"] = int(raw.get("weekCount") or 0)
        if raw.get("day") == day:
            u["dayCount"] = int(raw.get("dayCount") or 0)
        u["events"] = _prune(raw.get("events") or [])
    except FileNotFoundError:
        pass
    except Exception:  # noqa: BLE001 — 손상 파일은 0 기준으로 재시작
        pass
    return u


def record(sec: float = 0.0, n: int = 1) -> dict:
    """claude 호출 1건(소요 sec초) 누적 후 원장에 저장(원자적 교체). 갱신된 사용량 반환.

    sec = 이번 호출의 벽시계 소요초(롤링 5h 게이트의 핵심 입력). 0 이면 카운트만 늘고
    예산엔 영향이 없다(소요 미측정 호출). n 은 레거시 카운트 증분(표시용).
    """
    now = time.time()
    u = read()
    u["weekCount"] += n
    u["dayCount"] += n
    if sec and sec > 0:
        u["events"].append([now, float(sec)])
    u["events"] = _prune(u["events"], now)
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


def rolling_seconds(window_sec: int, usage: dict | None = None) -> float:
    """최근 window_sec 안에 누적된 claude 소요초 합. usage 미지정 시 현재 원장 조회."""
    u = usage if usage is not None else read()
    now = time.time()
    total = 0.0
    for e in u.get("events") or []:
        try:
            ts = float(e[0])
            sec = float(e[1])
        except (TypeError, ValueError, IndexError):
            continue
        if now - ts <= window_sec:
            total += sec
    return total


def rolling_exhausted(
    capacity_sec: int, window_sec: int, use_ratio: float = 0.97, usage: dict | None = None
) -> bool:
    """롤링 창 예산 소진 여부. 최근 window_sec 소요초 합 ≥ use_ratio × capacity_sec 면 True.

    capacity_sec ≤ 0 이면 게이트 비활성(무제한, 항상 False).
    """
    if capacity_sec <= 0:
        return False
    return rolling_seconds(window_sec, usage) >= use_ratio * capacity_sec


def summary(capacity_sec: int, window_sec: int, usage: dict | None = None) -> dict:
    """표시용 요약 — 롤링 사용초/용량/소진율 + 레거시 카운트."""
    u = usage if usage is not None else read()
    used = rolling_seconds(window_sec, u)
    pct = (used / capacity_sec * 100.0) if capacity_sec > 0 else 0.0
    return {
        "rollingSec": round(used, 1),
        "capacitySec": capacity_sec,
        "pct": round(pct, 1),
        "weekCount": u.get("weekCount", 0),
        "dayCount": u.get("dayCount", 0),
    }


def exhausted(daily_cap: int, weekly_cap: int, usage: dict | None = None) -> bool:
    """[레거시] 일/주 카운트 캡 도달 여부. 롤링 게이트(rolling_exhausted)로 대체됨 — 미사용.

    하위 호환을 위해 시그니처만 유지한다. 캡 ≤ 0 이면 해당 축은 무제한.
    """
    u = usage if usage is not None else read()
    if weekly_cap > 0 and u.get("weekCount", 0) >= weekly_cap:
        return True
    if daily_cap > 0 and u.get("dayCount", 0) >= daily_cap:
        return True
    return False
