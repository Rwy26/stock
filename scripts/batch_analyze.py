"""전 관심종목 AI 분석 배치 — 결과는 AI 분석 이력(ai_analysis_cache)에 자동 저장.

순서: ① ETF 9종 (KODEX 200 → 섹터 ETF) ② 주도 섹터 순위순 → 섹터 내 시가총액순.

과부하 방지:
  - 종목당 INTERVAL(90초) 간격 — Gemini/Groq 분당 한도, KIS 쿼터 보호
  - 당일 이미 분석된 종목은 스킵 (재실행 안전 — 중단돼도 이어서 실행 가능)
  - market_compass(시장 차원)는 30분 캐시 재사용 — 종목마다 재계산하지 않음
  - LLM 실패(레이트리밋) 시에도 결정론 데이터는 저장하고 다음 종목 진행

스케줄: MOON-STOCK-Batch-Analyze (매일 21:00 — 장 마감·저녁 동기화 이후)
로그: logs/batch-analyze.log
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))

import httpx  # noqa: E402

INTERVAL = 90  # 종목 간 간격(초)
LOG = REPO / "logs" / "batch-analyze.log"
BASE = "http://127.0.0.1:8000"

# ETF (이름 포함 — stocks 테이블에 없으면 등록해 이력에 이름이 표시되도록)
ETFS = [
    ("069500", "KODEX 200"),
    ("471990", "KODEX AI반도체핵심장비"),
    ("487240", "KODEX AI전력핵심설비"),
    ("0080G0", "KODEX 방산TOP10"),
    ("305720", "KODEX 2차전지산업"),
    ("445290", "KODEX 로봇액티브"),
    ("0098F0", "KODEX 원자력SMR"),
    ("0167Z0", "KODEX 미국우주항공"),
    ("117700", "KODEX 건설"),
]


def log(msg: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def ensure_etf_stock_rows() -> None:
    """ETF 이름이 이력에 표시되도록 stocks 테이블에 등록."""
    import db
    import models

    s = db.get_session_factory()()
    try:
        for code, name in ETFS:
            row = s.get(models.Stock, code)
            if row is None:
                s.add(models.Stock(code=code, name=name, market="ETF"))
            elif not row.name:
                row.name = name
        s.commit()
    finally:
        s.close()


def build_queue() -> list[tuple[str, str]]:
    """분석 순서: ETF → 주도 섹터 순위순 × 섹터 내 시총순."""
    wl = httpx.get(BASE + "/api/public/watchlist", timeout=120).json().get("items", [])
    try:
        rot = httpx.get(BASE + "/api/public/sector-rotation", timeout=600).json()
        rank = {s["sector"]: i for i, s in enumerate(rot.get("sectors", []))}
    except Exception:
        rank = {}

    stocks = sorted(
        wl,
        key=lambda it: (rank.get(it.get("sector"), 99), -(it.get("marketCap") or 0)),
    )
    queue = [(c, n) for c, n in ETFS]
    queue += [(it["code"], it["name"]) for it in stocks]
    return queue


def done_today(code: str) -> bool:
    import db
    import models
    from sqlalchemy import select

    s = db.get_session_factory()()
    try:
        row = s.execute(
            select(models.AiAnalysisCache.analyzed_at).where(
                models.AiAnalysisCache.stock_code == code
            )
        ).scalar_one_or_none()
    finally:
        s.close()
    return row is not None and row.date() == date.today()


def main() -> int:
    import stock_compass

    log("=== 배치 분석 시작 ===")
    ensure_etf_stock_rows()
    queue = build_queue()
    log(f"대기열: {len(queue)}건 (ETF {len(ETFS)} + 종목 {len(queue) - len(ETFS)})")

    ok = fail = skip = 0
    for i, (code, name) in enumerate(queue, start=1):
        if done_today(code):
            skip += 1
            continue
        try:
            r = stock_compass.analyze_stock(code, with_ai=True)
            comp = r.get("composite", {})
            log(f"[{i}/{len(queue)}] {name}({code}) → {comp.get('score')}점 "
                f"{comp.get('grade')} | LLM {r.get('aiProvider')}")
            ok += 1
        except Exception as exc:  # noqa: BLE001
            log(f"[{i}/{len(queue)}] {name}({code}) FAIL: {type(exc).__name__} {str(exc)[:120]}")
            fail += 1
        time.sleep(INTERVAL)

    log(f"=== 배치 완료: 성공 {ok} / 실패 {fail} / 스킵(당일 기분석) {skip} ===")
    return 0


if __name__ == "__main__":
    time.sleep(65)  # KIS 토큰 발급 1분 제한
    raise SystemExit(main())
