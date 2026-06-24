"""idle_narrative_filler.ps1 전용 단일 종목 narrative 헬퍼.

PowerShell 스케줄러가 유휴 윈도우 동안 한 종목씩 호출하며, 매 호출 사이에 사용자 입력을
다시 점검해 즉시 중단할 수 있도록 '한 번에 한 종목'만 처리한다(renarrate_llm_none.py 는
한 번에 전량을 INTERVAL 간격으로 돌리므로 입력 감지 시 즉시 멈추기 어렵다).

모드:
  --list [N]       claude 승급 대상 코드를 '미리 정해진 호출 순서'로 정렬해 줄단위 출력.
                   호출 순서(결정론 티어):
                     T0 섹터나침반 : market_leaders(주도 섹터의 주도주) — 섹터순×섹터내순
                     T1 관심종목   : Watchlist
                     T2 추천종목   : Recommendation(최근 발행순)
                     T3 나머지     : 그 외 분석된 종목(analyzed_at 최신순)
                   대상 = 아직 claude:max narrative 가 없는 종목(정규 배치가 gemini/groq 로
                   깔아 둔 서술을 주도주 우선으로 claude 품질로 승급). 이미 claude:max 면 제외.
                   N 지정 시 상위 N개만. (stale 되지 않는 동적 DB 조회)
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


# ---------------------------------------------------------------------------
# claude narrative 우선순위 — '호출 순서를 미리 정해 두는' 결정론 티어.
#   T0 섹터나침반 : market_leaders(주도 섹터의 주도주) — 섹터순(sector_rank)×섹터내순(stock_rank)
#   T1 관심종목   : Watchlist
#   T2 추천종목   : Recommendation(최근 발행순)
#   T3 나머지     : 그 외 분석된 종목(ai_analysis_cache, analyzed_at 최신순)
# idle 필러는 이 순서대로, '아직 claude:max 가 아닌' 종목을 예산 내에서 claude 로 승급한다.
# 정규 배치(idle_only)가 gemini/groq 로 깔아 둔 narrative 를 주도주부터 claude 품질로 끌어올린다.
# 명시 티어(T0~T2)는 미분석 종목도 대상에 포함(claude 가 새로 채움). T3 는 이미 분석된 것만.
# ---------------------------------------------------------------------------


def _session():
    import db

    return db.get_session_factory()()


def _leader_codes() -> list[str]:
    """T0 섹터나침반 — market_leaders, 주도섹터순×섹터내순(NULL 은 뒤로). 실패 시 []."""
    try:
        import models
        from sqlalchemy import func, select

        s = _session()
        try:
            rows = s.execute(
                select(models.MarketLeader.code).order_by(
                    func.coalesce(models.MarketLeader.sector_rank, 9999),
                    func.coalesce(models.MarketLeader.stock_rank, 9999),
                )
            ).all()
        finally:
            s.close()
        return [c for (c,) in rows if c]
    except Exception:  # noqa: BLE001
        return []


def _watchlist_codes() -> list[str]:
    """T1 관심종목 — Watchlist. 실패 시 []."""
    try:
        import models
        from sqlalchemy import select

        s = _session()
        try:
            rows = s.execute(select(models.Watchlist.stock_code)).all()
        finally:
            s.close()
        return [c for (c,) in rows if c]
    except Exception:  # noqa: BLE001
        return []


def _recommendation_codes() -> list[str]:
    """T2 추천종목 — Recommendation(최근 발행순). 실패 시 []."""
    try:
        import models
        from sqlalchemy import select

        s = _session()
        try:
            rows = s.execute(
                select(models.Recommendation.stock_code)
                .order_by(models.Recommendation.rec_date.desc())
                .limit(200)
            ).all()
        finally:
            s.close()
        return [c for (c,) in rows if c]
    except Exception:  # noqa: BLE001
        return []


def _claude_done_and_universe() -> tuple[set[str], list[str]]:
    """(이미 claude:max narrative 보유 코드 집합, 분석된 전체 코드[최신순]).

    aiProvider 가 'claude' 로 시작하고 aiReport 가 비어있지 않으면 '승급 완료'(제외 대상).
    두 번째 값은 T3(나머지) 티어 구성용 — ai_analysis_cache 에 실제 존재하는 코드 순서.
    """
    done: set[str] = set()
    universe: list[str] = []
    try:
        import models
        from sqlalchemy import select

        s = _session()
        try:
            rows = s.execute(
                select(models.AiAnalysisCache.stock_code, models.AiAnalysisCache.result_json)
                .order_by(models.AiAnalysisCache.analyzed_at.desc())
            ).all()
        finally:
            s.close()
    except Exception:  # noqa: BLE001
        return done, universe
    for code, rj in rows:
        if not code:
            continue
        universe.append(code)
        rj = rj or {}
        prov = str(rj.get("aiProvider") or "")
        if prov.startswith("claude") and rj.get("aiReport"):
            done.add(code)
    return done, universe


def _prioritized_targets(limit: int | None) -> list[str]:
    """T0→T3 순서로 'claude 승급이 필요한' 종목을 중복제거·정렬해 반환(이미 claude 는 제외)."""
    done, universe = _claude_done_and_universe()
    in_cache = set(universe)
    ordered: list[str] = []
    seen: set[str] = set()
    tiers = (
        ("leaders", _leader_codes()),         # T0 섹터나침반
        ("watchlist", _watchlist_codes()),    # T1 관심종목
        ("recs", _recommendation_codes()),    # T2 추천종목
        ("rest", universe),                   # T3 나머지(분석된 것만)
    )
    for label, codes in tiers:
        for c in codes:
            if c in seen or c in done:
                continue
            # 나머지 티어는 신규 분석 생성을 피하려 이미 분석된 코드만 — 명시 티어는 미분석도 허용.
            if label == "rest" and c not in in_cache:
                continue
            seen.add(c)
            ordered.append(c)
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
    for code in _prioritized_targets(limit):
        print(code)
    return 0


def _run_code(code: str) -> int:
    import stock_compass
    import market_compass as mc
    from exclusion_engine import ExcludedStockError

    # 이 프로세스를 'idle 필러 경로'로 표시 — CLAUDE_NARRATIVE_PATH=idle_only 정책에서
    # claude 1순위를 허용하는 유일한 경로다(정규 배치/서버는 opt-in 하지 않아 gemini/groq).
    mc.set_claude_idle_optin(True)

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
