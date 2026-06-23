"""LLM 해석 누락 종목 재서술 — 어젯밤 배치에서 'LLM none'(3중 폴백 동시 레이트리밋)
처리된 종목만 골라 재분석. LLM 쿼터 회복된 시점에 1회성으로 실행.

점수는 이미 결정론 저장돼 있으나 LLM 서술이 비어 있는 종목을 stock_compass.analyze_stock
으로 재실행해 narrative 를 채운다. KIS 보호를 위해 종목 간 INTERVAL 간격.

대상 코드(우선순위):
  1) 인자로 받은 파일(줄당 6자리 코드)
  2) ai_analysis_cache 동적 조회 — aiProvider='none*' 또는 aiReport 빈 행(서술 누락)
     (_save_history 는 LLM 실패해도 점수는 항상 저장하므로, 누락은 narrative 뿐)
  3) DB 조회 실패 시 정적 내장 목록(CODES) 폴백
로그: logs/renarrate-llm-none.log
"""

from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))

INTERVAL = 40  # 종목 간 간격(초) — KIS daily-chart 보호
LOG = REPO / "logs" / "renarrate-llm-none.log"

# 정적 폴백 목록 — DB 동적 조회가 실패할 때만 사용(평소엔 select_pending_codes() 가 우선).
CODES = """000270 000400 000660 000720 001440 003550 003670 005380 005490 005930
006400 009420 009540 009830 012330 012510 017670 018260 022100 023590
030610 032820 034730 035420 035720 039030 042700 047040 048410 051910
053800 055550 060370 064400 066570 066970 068270 078930 086790 090360
091580 093320 096770 103590 105560 108490 126340 141080 196170 204320
207940 226950 237690 240810 247540 267250 277810 290650 307950 316140
322000 326030 329180 347850 353200 373220 376300 393890 397030 448900
483650""".split()


def _llm_available() -> bool:
    """gemini/groq 중 하나라도 2xx 응답하면 True. 라이트 단일 핑(재시도 없음).

    혼잡/쿼터 소진(429·5xx·타임아웃) 시 urlopen 이 예외를 던지므로 False 가 되어
    재서술 루프를 진입하지 않는다 → KIS 일봉·국제망 헛호출 차단.
    점검 자체가 망을 무리하게 치지 않도록 timeout 12s 단일 시도만 한다.
    """
    import json
    import urllib.request

    from settings import settings

    # gemini
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{settings.gemini_model}:generateContent?key={settings.gemini_api_key}",
            data=json.dumps({"contents": [{"parts": [{"text": "hi"}]}]}).encode(),
            headers={"Content-Type": "application/json"}), timeout=12)
        return True
    except Exception:  # noqa: BLE001
        pass
    # groq
    try:
        gk = getattr(settings, "groq_api_key", "")
        urllib.request.urlopen(urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=json.dumps({
                "model": settings.groq_model,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 5}).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {gk}"}), timeout=12)
        return True
    except Exception:  # noqa: BLE001
        return False


def log(msg: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def select_pending_codes() -> list[str]:
    """ai_analysis_cache 에서 결정론 점수는 있으나 LLM 서술이 빈 행(재서술 대상) 코드 수집.

    대상: aiProvider 가 'none*' 이거나 aiReport 가 비어 있는 행. analyzed_at(UTC) 최신순.
    정적 목록과 달리 실제 누락 행을 그대로 따라가므로 stale 되지 않는다.
    조회 실패 시 빈 목록 반환 → 호출부가 정적 CODES 로 폴백.
    """
    try:
        import db
        import models
        from sqlalchemy import select

        s = db.get_session_factory()()
        try:
            rows = s.execute(
                select(models.AiAnalysisCache.stock_code, models.AiAnalysisCache.result_json)
                .order_by(models.AiAnalysisCache.analyzed_at.desc())
            ).all()
        finally:
            s.close()
        pending = []
        for code, rj in rows:
            rj = rj or {}
            prov = str(rj.get("aiProvider") or "")
            if prov.startswith("none") or not rj.get("aiReport"):
                pending.append(code)
        return pending
    except Exception as e:  # noqa: BLE001
        log(f"동적 대상 조회 실패 — 정적 CODES 폴백: {type(e).__name__} {e}")
        return []


def main() -> int:
    import stock_compass
    from exclusion_engine import ExcludedStockError

    if len(sys.argv) > 1 and Path(sys.argv[1]).exists():
        codes = [c.strip() for c in Path(sys.argv[1]).read_text().split() if c.strip()]
        src = f"파일 인자({sys.argv[1]})"
    else:
        codes = select_pending_codes()
        src = "DB 동적 조회(LLM-none/서술누락)"
        if not codes:
            codes = CODES
            src = "정적 CODES 폴백"

    if not _llm_available():
        log("=== LLM 전부 불가(혼잡/쿼터) — 재서술 중단. KIS 호출 0, 네트워크 회복 후 재실행 ===")
        return 0

    log(f"=== 재서술 시작: {len(codes)}종목 (출처={src}, INTERVAL={INTERVAL}s) ===")
    ok = fail = none = 0
    for i, code in enumerate(codes, start=1):
        try:
            r = stock_compass.analyze_stock(code, with_ai=True)
            comp = r.get("composite", {})
            prov = r.get("aiProvider")
            if prov and "none" not in str(prov):
                ok += 1
                tag = "✅서술"
            else:
                none += 1
                tag = "⚠️여전히none"
            log(f"[{i}/{len(codes)}] {code} → {comp.get('score')}점 "
                f"{comp.get('grade')} | LLM {prov} {tag}")
        except ExcludedStockError:
            log(f"[{i}/{len(codes)}] {code} → 제외종목 스킵")
        except Exception as e:
            fail += 1
            log(f"[{i}/{len(codes)}] {code} FAIL: {type(e).__name__} {e}")
        if i < len(codes):
            time.sleep(INTERVAL)

    log(f"=== 재서술 완료: 서술성공 {ok} / 여전히none {none} / 실패 {fail} ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
