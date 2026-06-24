"""idle_narrative_filler.ps1 전용 단일 종목 narrative 헬퍼.

PowerShell 스케줄러가 유휴 윈도우 동안 한 종목씩 호출하며, 매 호출 사이에 사용자 입력을
다시 점검해 즉시 중단할 수 있도록 '한 번에 한 종목'만 처리한다(renarrate_llm_none.py 는
한 번에 전량을 INTERVAL 간격으로 돌리므로 입력 감지 시 즉시 멈추기 어렵다).

모드:
  --list [N]       재서술 대상(LLM none/서술 누락) 코드를 우선순위 정렬해 줄단위 출력.
                   우선순위: 관심종목(watchlist)·최근 발행 추천 종목 먼저, 나머지는 뒤.
                   N 지정 시 상위 N개만. 대상 선정은 renarrate_llm_none.select_pending_codes()
                   재사용(stale 되지 않는 동적 조회).
  --code XXXXXX    해당 종목 1개를 stock_compass.analyze_stock(with_ai=True)로 재분석.
                   claude(MAX) 1순위 폴백 체인을 그대로 탄다. 결과를 한 줄로 출력하고,
                   exit code 로 호출부(PS)가 claude 사용/성공 여부를 판정한다.

--code 종료 코드:
  0  narrative 생성 성공, claude(MAX)가 처리   → PS 가 MAX 사용 카운트 증가
  1  narrative 생성 성공, 폴백(gemini/groq/openai)이 처리 → MAX 카운트 증가 안 함
  2  여전히 none(전 프로바이더 실패)            → MAX 카운트 증가 안 함
  3  제외종목 스킵 또는 예외                     → MAX 카운트 증가 안 함

표준출력 1행 형식(--code): "<code>\t<provider>\t<score>\t<grade>"
"""

from __future__ import annotations

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(REPO / "scripts"))


def _priority_codes() -> list[str]:
    """관심종목 + 최근 발행 추천 종목 코드 집합(우선순위 가중용). 실패 시 빈 리스트."""
    codes: list[str] = []
    seen: set[str] = set()
    try:
        import db
        import models
        from sqlalchemy import select

        s = db.get_session_factory()()
        try:
            # 관심종목(watchlist) — 사용자가 직접 추적 중인 종목
            for (c,) in s.execute(select(models.Watchlist.stock_code)).all():
                if c and c not in seen:
                    seen.add(c)
                    codes.append(c)
            # 최근 발행 추천(recommendations) — 리포트로 노출된 종목
            for (c,) in s.execute(
                select(models.Recommendation.stock_code)
                .order_by(models.Recommendation.rec_date.desc())
                .limit(200)
            ).all():
                if c and c not in seen:
                    seen.add(c)
                    codes.append(c)
        finally:
            s.close()
    except Exception:  # noqa: BLE001
        return []
    return codes


def _prioritized_pending(limit: int | None) -> list[str]:
    from renarrate_llm_none import select_pending_codes

    pending = select_pending_codes()
    if not pending:
        return []
    pri = _priority_codes()
    pri_set = set(pri)
    # 관심종목/추천 순서를 먼저(원래 우선순위 보존), 그다음 잔여 pending(analyzed_at 최신순 유지)
    head = [c for c in pri if c in set(pending)]
    head_set = set(head)
    tail = [c for c in pending if c not in head_set]
    ordered = head + tail
    if limit is not None and limit > 0:
        ordered = ordered[:limit]
    return ordered


def _run_list(argv: list[str]) -> int:
    limit = None
    if argv:
        try:
            limit = int(argv[0])
        except ValueError:
            limit = None
    for code in _prioritized_pending(limit):
        print(code)
    return 0


def _run_code(code: str) -> int:
    import stock_compass
    from exclusion_engine import ExcludedStockError

    try:
        r = stock_compass.analyze_stock(code, with_ai=True)
    except ExcludedStockError:
        print(f"{code}\texcluded\t-\t-")
        return 3
    except Exception as e:  # noqa: BLE001
        print(f"{code}\terror:{type(e).__name__}\t-\t-")
        return 3

    comp = r.get("composite", {}) or {}
    prov = str(r.get("aiProvider") or "none")
    score = comp.get("score")
    grade = comp.get("grade")
    print(f"{code}\t{prov}\t{score}\t{grade}")

    if "none" in prov or not r.get("aiReport"):
        return 2
    if prov.startswith("claude"):
        return 0
    return 1


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("usage: narrate_one.py --list [N] | --code <code>", file=sys.stderr)
        return 64
    if args[0] == "--list":
        return _run_list(args[1:])
    if args[0] == "--code" and len(args) >= 2:
        return _run_code(args[1].strip())
    # 위치인자 단독(6자리 코드)도 --code 로 취급
    if len(args) == 1 and args[0].isdigit():
        return _run_code(args[0].strip())
    print("usage: narrate_one.py --list [N] | --code <code>", file=sys.stderr)
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
