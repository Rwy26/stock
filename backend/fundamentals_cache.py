"""fundamentals_cache.py

기업 기본적 분석(발행주식수 등) 디스크 캐시.

KIS 재호출 최소화를 위해 종목별 JSON을 D드라이브
(PIPELINE_ROOT/data/external/fundamentals/<code>.json)에 저장한다.
스케줄 동기화(fundamentals_sync.py)가 채우고, 시세 응답에서 시가총액 계산에 사용.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pipeline_paths import get_pipeline_paths


def _path_for(code: str) -> Path:
    d = get_pipeline_paths().data_fundamentals
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{code.strip()}.json"


def load(code: str) -> dict[str, Any]:
    p = _path_for(code)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save(code: str, data: dict[str, Any]) -> None:
    try:
        _path_for(code).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        # Cache write must never break the caller.
        pass


def get_shares(code: str) -> int:
    """캐시된 발행주식수(상장주식수). 없으면 0."""
    try:
        return int(load(code).get("shares") or 0)
    except Exception:
        return 0
