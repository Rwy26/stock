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
from datetime import datetime, date, timedelta
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

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


def wait_for_backend(max_wait: int = 300) -> bool:
    """백엔드 /health 가 200 OK 될 때까지 최대 max_wait초 대기. 성공 True."""
    deadline = time.time() + max_wait
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            r = httpx.get(BASE + "/health", timeout=10)
            if r.status_code == 200 and r.json().get("ok"):
                if attempt > 1:
                    log(f"백엔드 준비됨 (시도 {attempt}회)")
                return True
        except Exception:
            pass
        log(f"백엔드 대기 중... ({attempt}회, /health 무응답)")
        time.sleep(15)
    return False


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
    # 관심종목은 큐의 필수 입력 — 백엔드(8000)가 기동 직후/과부하로 일시 응답 불가일 수
    # 있어 재시도로 대기한다. (단발 실패로 태스크 전체가 0x1 로 죽지 않도록; morning_prep 패턴)
    wl: list = []
    last_exc: Exception | None = None
    for attempt in range(1, 7):  # 최대 ~2.5분 대기 (10·20·30·40·50초 백오프)
        try:
            wl = httpx.get(BASE + "/api/public/watchlist", timeout=120).json().get("items", [])
            break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            wait = attempt * 10
            log(f"watchlist 조회 실패({attempt}/6): {type(exc).__name__} — {wait}초 후 재시도")
            time.sleep(wait)
    else:
        raise RuntimeError(
            f"백엔드(8000) watchlist 응답 없음 — {type(last_exc).__name__}: {last_exc}"
        )
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
    if row is None:
        return False
    # analyzed_at 은 _save_history 가 datetime.utcnow()(UTC)로 저장한다. 서버는 KST 가정
    # (sector_rotation: "서버는 KST 가정")이라 date.today() 는 KST 날짜 → UTC 값을 그대로
    # 비교하면 KST 09시(=UTC 자정) 경계에서 어긋난다. KST(+9h)로 환산 후 '오늘' 판정.
    return (row + timedelta(hours=9)).date() == date.today()


def main() -> int:
    import stock_compass

    log("=== 배치 분석 시작 ===")
    if not wait_for_backend(max_wait=300):
        log("=== 배치 중단: 백엔드 5분 내 미기동 — 백엔드 기동 후 재실행 필요 ===")
        return 2  # 백엔드 미기동 명시적 종료코드
    ensure_etf_stock_rows()
    queue = build_queue()
    log(f"대기열: {len(queue)}건 (ETF {len(ETFS)} + 종목 {len(queue) - len(ETFS)})")

    from exclusion_engine import ExcludedStockError

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
        except ExcludedStockError:
            log(f"[{i}/{len(queue)}] {name}({code}) SKIP: 제외종목")
            skip += 1
            continue
        except Exception as exc:  # noqa: BLE001
            log(f"[{i}/{len(queue)}] {name}({code}) FAIL: {type(exc).__name__} {str(exc)[:120]}")
            fail += 1
        time.sleep(INTERVAL)

    log(f"=== 배치 완료: 성공 {ok} / 실패 {fail} / 스킵(당일 기분석) {skip} ===")
    return 0


if __name__ == "__main__":
    time.sleep(65)  # KIS 토큰 발급 1분 제한
    try:
        rc = main()
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 — 미처리 예외도 로그에 남겨 0x1 원인 추적
        import traceback
        log(f"=== 배치 비정상 종료: {type(exc).__name__}: {exc} ===")
        log(traceback.format_exc())
        raise SystemExit(1)
    raise SystemExit(rc)
