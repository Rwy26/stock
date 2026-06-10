"""종목 종합 평가 (시장 나침반 12단계 최종 통합).

종목 코드 하나를 입력하면:
  1~7단계  : market_compass (시장 구조·거시·순환·주도섹터·뉴스·스마트머니)
  8단계    : mtf_analysis (월/주/일/60분/15분 멀티 타임프레임)
  9~11단계 : target_engine (목표가 5종·손절가 3종·빈도 기반 확률)
  12단계   : 결정론 점수/등급 + LLM 종합 → 최종 형식 출력
             (# 시장 나침반 / # 종목 평가 / # 투자 행동 / 반대 시나리오)

결정론 종합 점수 (0~100, LLM이 아닌 코드가 계산):
  섹터 강도 25% + MTF 정렬 25% + 상승지속확률 25% + 손익비 25%
등급: S(80+) A(70+) B(55+) C(40+) D(미만)
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional


def _stock_sector(code: str) -> Optional[str]:
    """sector_classification.json 에서 종목의 섹터."""
    try:
        p = Path(__file__).resolve().parent / "sector_classification.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get(code)
    except Exception:
        return None


def _composite_score(sector_score: Optional[float], mtf: dict, targets: dict) -> dict:
    """결정론 종합 점수 — 각 요소와 가중치를 투명하게 반환."""
    parts = {}

    parts["섹터 강도"] = round(sector_score, 1) if sector_score is not None else 50.0

    align = mtf.get("alignment", {})
    total_tf = max(align.get("total", 5), 1)
    parts["MTF 정렬"] = round(align.get("uptrendCount", 0) / total_tf * 100, 1)

    prob = targets.get("probability", {})
    parts["상승지속확률"] = float(prob.get("continueUpPct", 50.0)) if "error" not in prob else 50.0

    # 손익비: (평균목표 상승폭) / (기술적 손절 하락폭) — 2.0 이상이면 만점
    cur = targets.get("currentPrice") or 0
    avg_t = targets.get("avgTarget")
    tech = (targets.get("stops", {}).get("기술적 손절") or {}).get("price")
    rr_score = 50.0
    rr = None
    if cur and avg_t and tech and cur > tech:
        up = avg_t / cur - 1
        dn = 1 - tech / cur
        if dn > 0:
            rr = round(up / dn, 2)
            rr_score = round(min(rr / 2.0, 1.0) * 100, 1)
    parts["손익비"] = rr_score

    score = round(sum(parts.values()) / len(parts), 1)
    grade = "S" if score >= 80 else "A" if score >= 70 else "B" if score >= 55 else "C" if score >= 40 else "D"
    return {"score": score, "grade": grade, "parts": parts, "riskReward": rr}


_SYSTEM_PROMPT = """당신은 월가 헤지펀드 PM, 글로벌 매크로 전략가, 퀀트 운용역, 스마트머니 트레이더,
산업 애널리스트, 경제학자, 행동심리학자, 뉴스 분석가를 통합한 최고 수준의 투자 분석 AI다.

절대 규칙:
1. 제공된 데이터(JSON)의 수치만 사용한다. 없는 수치를 만들지 않는다.
2. 점수/등급/목표가/손절가/확률은 이미 계산되어 제공된다 — 그대로 인용하고 해석만 한다.
3. 불확실성과 반대 시나리오를 반드시 포함한다.
4. 한국어 마크다운. 아래 형식을 정확히 따른다.

출력 형식 (필수):

# 시장 나침반
현재 시장 단계 :
주도 섹터 :
섹터 순환 위치 :
유입 자금 : (어디서 → 어디로)
위험 신호 :

---

# 종목 평가
점수 : (composite.score)
등급 : (composite.grade)
목표가 : (targets.avgTarget — 5종 계산의 평균, 주요 근거 1~2개 병기)
손절가 : (stops 중 가장 타당한 것, 근거 병기)
예상 기간 : (확률 계산의 60일 한도와 MTF 구조를 근거로 추정)

---

# 투자 행동
신규 진입 : (권고/조건부/비권고 + 근거)
추가 매수 : (조건 명시)
부분 익절 : (레벨 명시)
전량 익절 : (레벨 명시)
관망 : (관망이 합리적인 조건)

---

# 불확실성·반대 시나리오
(현재 판단이 틀리는 조건 2~3가지와 각각의 대응. 표본 수가 적거나 데이터가 빠진 항목 명시)

판단 시 멀티 타임프레임 정렬(상위 TF 우선), 시장 단계(위기 장세에서는 보수적), 손익비,
빈도 기반 확률의 표본 수를 모두 고려하라."""


def analyze_stock(code: str, with_ai: bool = True) -> dict:
    """12단계 통합 종목 평가."""
    import market_compass
    import mtf_analysis
    import target_engine

    code = code.strip()

    # 1~7단계 (캐시 활용 — 시장 차원은 종목과 무관하게 재사용)
    market = market_compass.compute_market_compass(force=False, with_ai=False)
    market_ctx = {
        "regime": market.get("regime"),
        "rotationLadder": market.get("rotationLadder"),
        "sectorRanking": [
            {k: s.get(k) for k in ("rank", "sector", "score", "lifecycle", "intradayPct")}
            for s in market.get("sectorRanking", [])
        ],
        "vkospi": market.get("vkospi"),
    }

    # 8단계
    mtf = mtf_analysis.analyze_mtf(code)

    # 9~11단계
    targets = target_engine.analyze_targets(code)

    # 종목 섹터 + 섹터 점수
    sector = _stock_sector(code)
    sector_score = None
    sector_rank = None
    for s in market.get("sectorRanking", []):
        if s.get("sector") == sector:
            sector_score = s.get("score")
            sector_rank = s.get("rank")
            break

    composite = _composite_score(sector_score, mtf, targets)

    context = {
        "asOf": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "stock": {
            "code": code,
            "name": targets.get("name", code),
            "sector": sector,
            "sectorRank": sector_rank,
            "sectorScore": sector_score,
            "currentPrice": targets.get("currentPrice"),
        },
        "market": market_ctx,
        "mtf": {
            "alignment": mtf.get("alignment"),
            "timeframes": [
                {
                    "label": t.get("label"),
                    "trend": t.get("trend"),
                    "emaState": t.get("emaState"),
                    "rsi14": t.get("rsi14"),
                    "structureEvent": t.get("structureEvent"),
                    "liquidity": t.get("liquidity"),
                    "cdv": t.get("cdv"),
                    "error": t.get("error"),
                }
                for t in mtf.get("timeframes", [])
            ],
        },
        "targets": {
            "list": targets.get("targets"),
            "avgTarget": targets.get("avgTarget"),
            "avgTargetUpside": targets.get("avgTargetUpside"),
        },
        "stops": targets.get("stops"),
        "probability": targets.get("probability"),
        "composite": composite,
    }

    ai_report, provider = (None, "skipped")
    if with_ai:
        ai_report, provider = _call_stock_llm(context)

    return {
        **context,
        "aiReport": ai_report,
        "aiProvider": provider,
    }


def _call_stock_llm(context: dict) -> tuple[Optional[str], str]:
    """market_compass 의 LLM 폴백 체인을 종목용 시스템 프롬프트로 재사용."""
    import market_compass as mc

    saved = mc._SYSTEM_PROMPT
    try:
        mc._SYSTEM_PROMPT = _SYSTEM_PROMPT
        return mc._call_llm(json.dumps(context, ensure_ascii=False))
    finally:
        mc._SYSTEM_PROMPT = saved
