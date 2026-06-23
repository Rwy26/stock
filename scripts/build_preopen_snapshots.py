"""개장 전 선행 스냅샷 빌더 — US 야간 → KR 익일 선행 + 현재 장세.

실시간 운영 지원(예측 엔진 세션): 검증된 유일한 실측 선행 신호(US 야간→KR 익일,
AUC 반도체 0.635·AI 0.659)를 **KR 개장 전**에 가장 이른 시점으로 정적 스냅샷화한다.
운영자가 장 시작 시점에 KIS/yfinance 를 두드리지 않고 "오늘 반도체·AI 갭 방향"과
현재 장세를 즉시 본다.

소스: us_lead.get_opening_gap_context()/compute_us_lead() — **DB(us_daily_prices)만 읽는
결정론 함수**(KIS·LLM 미호출)라 개장 전 배치에 안정적. 현재 장세는 직전 batch_analyze 가
적재한 signal_outcomes.regime 최신값(저비용 DB 조회).

데이터 정확성 원칙: US 데이터가 비어 섹터가 0개면 새 파일을 쓰지 않고 직전 정상본을
유지(stale 표시만) — 깨진 값 미발행. main.py 가 /static/snapshots 로 서빙, version-preopen.json
으로 차등 폴링.

스케줄: install-preopen-snapshots-task.ps1 (06:10 KST — US 동기화 06:05 직후·KR 개장 전).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass

SNAP_DIR = REPO / "backend" / "static" / "snapshots"
LOG = REPO / "logs" / "preopen-snapshots.log"
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


def _current_regime() -> dict:
    """직전 batch_analyze 가 적재한 최신 장세(저비용 DB 조회). 없으면 미상."""
    try:
        import db
        import models
        from sqlalchemy import select
        s = db.get_session_factory()()
        try:
            row = s.execute(
                select(models.SignalOutcome.regime, models.SignalOutcome.predicted_at)
                .where(models.SignalOutcome.regime.is_not(None))
                .order_by(models.SignalOutcome.predicted_at.desc())
                .limit(1)
            ).first()
        finally:
            s.close()
        if row and row[0]:
            return {"label": row[0],
                    "as_of": row[1].isoformat() if row[1] else None}
    except Exception:
        pass
    return {"label": None, "as_of": None}


def build_preopen_lead() -> bool:
    out = SNAP_DIR / "preopen-lead.json"
    try:
        import us_lead
        ctx = us_lead.get_opening_gap_context(force=True)
        composite = us_lead.compute_us_lead(force=False).get("composite")
    except Exception as exc:  # noqa: BLE001
        _mark_stale(out, reason=f"compute failed: {type(exc).__name__}")
        log(f"preopen-lead FAIL — {type(exc).__name__} {exc} (직전본 유지)")
        return False

    sectors = ctx.get("sectors") or {}
    if not sectors:
        _mark_stale(out, reason=f"no US data ({ctx.get('note')})")
        log(f"preopen-lead FAIL — US 데이터 없음 (직전본 유지, 미발행)")
        return False

    payload = {
        "updated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "count": len(sectors),
        "source": "us_lead.get_opening_gap_context (us_daily_prices, KIS/LLM 미호출)",
        "stale": False,
        "data": {
            "asof": ctx.get("asof"),
            "composite": composite,
            "regime": _current_regime(),
            "sectors": sectors,
            "note": ctx.get("note"),
        },
    }
    _atomic_write_json(out, payload)
    log(f"preopen-lead OK — sectors={len(sectors)} asof={ctx.get('asof')} "
        f"composite={composite} regime={payload['data']['regime']['label']}")
    return True


def main() -> int:
    log("=== 개장 전 선행 스냅샷 빌드 시작 ===")
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    ok = build_preopen_lead()
    try:
        _atomic_write_json(SNAP_DIR / "version-preopen.json", {
            "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
            "files": ["preopen-lead.json"],
            "ok_count": 1 if ok else 0,
        })
    except Exception as exc:  # noqa: BLE001
        log(f"version-preopen.json FAIL — {type(exc).__name__} {exc}")
    log(f"=== 빌드 {'완료' if ok else '실패 — 직전본 유지'} ===")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
