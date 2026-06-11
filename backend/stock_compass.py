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


def _stock_news(code: str, sector: Optional[str], limit: int = 8) -> list[dict]:
    """모멘텀 판정용 최근 7일 뉴스 — 종목 직접 기사 우선, 부족하면 섹터 기사."""
    try:
        from datetime import timedelta

        import db
        import models
        from sqlalchemy import select, or_

        s = db.get_session_factory()()
        try:
            d7 = datetime.now() - timedelta(days=7)
            cond = (models.NewsArticle.stock_code == code)
            if sector:
                cond = or_(cond, models.NewsArticle.sector == sector)
            rows = s.execute(
                select(
                    models.NewsArticle.title,
                    models.NewsArticle.press,
                    models.NewsArticle.published_at,
                    models.NewsArticle.stock_code,
                )
                .where(models.NewsArticle.published_at >= d7)
                .where(cond)
                .order_by(
                    (models.NewsArticle.stock_code != code),  # 종목 직접 기사 우선
                    models.NewsArticle.published_at.desc(),
                )
                .limit(limit)
            ).all()
        finally:
            s.close()
        return [
            {"title": t, "press": p, "at": at.strftime("%m-%d"), "direct": c == code}
            for t, p, at, c in rows
        ]
    except Exception:
        return []


def _stock_sector(code: str) -> Optional[str]:
    """sector_classification.json 에서 종목의 섹터."""
    try:
        p = Path(__file__).resolve().parent / "sector_classification.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get(code)
    except Exception:
        return None


def _composite_score(sector_score: Optional[float], mtf: dict, targets: dict) -> dict:
    """결정론 종합 점수 — 각 요소와 가중치를 투명하게 반환 (5요소 균등 20%)."""
    parts = {}

    parts["섹터 강도"] = round(sector_score, 1) if sector_score is not None else 50.0

    align = mtf.get("alignment", {})
    total_tf = max(align.get("total", 5), 1)
    parts["MTF 정렬"] = round(align.get("uptrendCount", 0) / total_tf * 100, 1)

    prob = targets.get("probability", {})
    parts["상승지속확률"] = float(prob.get("continueUpPct", 50.0)) if "error" not in prob else 50.0

    # 공매도 수급: 감소 추세=가점, 높은 비중=감점 (target_engine 계산). 데이터 없으면 중립 50.
    short = targets.get("shortSelling") or {}
    parts["공매도 수급"] = float(short.get("score", 50.0)) if "error" not in short else 50.0

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
5. probability.dotcomAnalogs 와 dotcomCasebook 이 제공되면 "닷컴 대조" 섹션을 쓴다 —
   1995~2002 미국 닷컴 버블에서 현재와 가장 비슷했던 국면의 검증 기록이다.
   매칭 국면의 실제 20일 후 분포·당시 밸류에이션·경영진 어조 지표를 그대로 인용해
   현재 판단의 보조 근거(특히 한국 ~500봉에 없는 과열·붕괴 국면 경고)로 쓰되,
   "다른 시장·다른 시대의 유사 국면 — 참고용"임을 명시한다. 없으면 섹션 생략.

문체: 간결한 트레이딩 저널체 — 베테랑 트레이더가 자기 매매일지에 쓰듯 직설적으로.
종목의 본질을 꿰뚫는 비유 1개 허용 (예: "서부 개척 시대에 청바지 파는 격",
"하드웨어가 현대차라면 이 회사는 AI 운영체제"). 비유는 제공된 섹터·뉴스 데이터에 근거할 것.

출력 형식 (필수):

# 시장 나침반
현재 시장 단계 :
주도 섹터 :
섹터 순환 위치 :
유입 자금 : (어디서 → 어디로)
위험 신호 :

---

# 닷컴 대조 (1995~2002 · 참고용 — 데이터 제공 시에만)
매칭 국면 : (dotcomAnalogs.phaseDistribution — 예: 과열기 12건 · 붕괴기 5건)
당시 기록 : (dotcomCasebook 의 해당 국면 — 나스닥 변화·대표 P/E·실제 20일 후 분포 인용)
시사점 : (현재 종목 판단에 주는 경고 또는 지지 — 1~2문장, 다른 시장·시대임을 명시)

---

# 종목 평가
한줄 테제 : (이 종목이 왜 오르는가/재평가되는가 — 한 문장, 비유 가능)
점수 : (composite.score)
등급 : (composite.grade)
예상 기간 : (확률 계산의 60일 한도와 MTF 구조를 근거로 추정)

---

# 모멘텀 (보유 이유)
핵심 모멘텀 : (이 종목을 보유하는 이유가 되는 재료 1~3개 — recentNews 헤드라인,
              섹터 순위·당일 자금 흐름, 수급(외인/기관/공매도 추세) 중 데이터가
              실제로 지지하는 것만. 뚜렷한 재료가 없으면 "뚜렷한 모멘텀 없음"이라고 쓸 것)
모멘텀 상태 : 살아있음 / 약화 / 소멸 중 하나 — 판정 근거 병기
              (예: 섹터 순위 상위 + 외인 유입 지속 = 살아있음 / 뉴스 소강 + 당일 자금 이탈 = 약화)
소멸 판정 기준 : (관측 가능한 구체 조건 2~3개 — 예: 일봉 구조 LH+LL 전환,
                섹터 순위 6위 밖 이탈 지속, 공매도 비중 증가 전환, 외인 레이어 50 미만 하락)
소멸 시 행동 : 모멘텀 소멸 = 보유 이유 소멸 = 매도 전환.
              가격 손절과 별개로 작동하는 두 번째 청산 트리거임을 명시할 것.
              (가격이 손절선 위에 있어도 모멘텀이 죽으면 정리한다)

---

# 투자 행동
진입 이유 : (위 핵심 모멘텀을 매수 근거로 연결 — 모멘텀 없는 진입은 권하지 않는다)
신규 진입 : (권고/조건부/비권고 + 근거)
분할 매수 계획 : (tradePlan.buyLevels의 1·2·3차 가격을 그대로 인용 — "하락 시 계속 담는" 구간.
                mtf 일봉 fvg.bullish(미충전 상승 갭 = 스마트머니 매수 흔적)와 겹치는 레벨이
                있으면 "ICT FVG 지지 구간과 일치 — 우선 매수 구간"으로 명시)
단계별 목표 : (tradePlan.stagedTargets의 1·2·3차 가격 + 각 산출 근거.
              경로상 fvg.bearish(미충전 하락 갭)가 있으면 통과해야 할 저항 구간으로 언급)
익절 계획 : (1차 목표 도달 시 부분 익절, 최종 목표에서 정리 등 — 제공된 레벨로만)
손절 : (stops 중 타당한 것 + "추세 진행 시 손절선을 따라 올리는" 운용 규칙 언급)
수급 읽기 : (외인/기관/스마트 레이어 점수 해석 + tradePlan.accumulationZones를
            "매집 추정 구간(거래량 집중 가격대)"으로 인용 — 반드시 '추정'임을 명시.
            shortSelling 데이터가 있으면 공매도 비중·추세를 인용할 것 —
            감소 추세(trend>0)는 "공매도 감소 = 숏커버/재평가 신호"로,
            증가 추세는 "하락 베팅 확대"로 해석. 대차잔고는 미제공이므로 언급 금지)
리스크 트리거 : ("~하면 즉시 매도" 형식 1~2개 — 데이터 근거 필수)
개미털기 주의 : (스윙 레벨·매물대 기반으로 흔들기 가능 구간 1개 — 구조적 추측임을 명시)

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
                    "volumeProfile": t.get("volumeProfile"),  # 매물대 — 핵심 차트에 밴드로 표시
                    "fvg": t.get("fvg"),  # ICT FVG (미충전 갭) — 스마트머니 매물대
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
        "series": targets.get("series"),
        "tradePlan": targets.get("tradePlan"),
        "shortSelling": targets.get("shortSelling"),
        "recentNews": _stock_news(code, sector),  # 모멘텀 판정 근거 (최근 7일)
        "composite": composite,
    }

    # 닷컴 사례집 — 유사 국면 매칭이 있을 때만 해당 국면 검증 기록 주입 (실패 무영향)
    try:
        import dotcom_casebook
        _dc = (context.get("probability") or {}).get("dotcomAnalogs") or {}
        _cb = dotcom_casebook.context_block(_dc)
        if _cb:
            context["dotcomCasebook"] = _cb
    except Exception:
        pass

    ai_report, provider = (None, "skipped")
    if with_ai:
        ai_report, provider = _call_stock_llm(context)

    result = {
        **context,
        "aiReport": ai_report,
        "aiProvider": provider,
    }

    # AI 분석 이력(ai_analysis_cache)에 자동 저장 — 실패해도 분석 결과 반환은 유지
    try:
        _save_history(result)
    except Exception:
        pass

    return result


def _save_history(result: dict) -> None:
    """분석 결과를 AI 분석 이력 테이블에 upsert (AI 분석 이력 페이지에 표시됨).

    signal 매핑(결정론 점수 기준): 80+ STRONG_BUY / 70+ BUY / 55+ HOLD / 40+ SELL / 미만 STRONG_SELL
    confidence = 종합 점수, upside_probability = 목표가 선도달 확률(빈도 기반).
    """
    from datetime import datetime as _dt

    import db
    import models
    from sqlalchemy import select

    st = result.get("stock", {})
    comp = result.get("composite", {})
    prob = result.get("probability", {}) or {}
    score = float(comp.get("score") or 0)
    signal = (
        "STRONG_BUY" if score >= 80 else
        "BUY" if score >= 70 else
        "HOLD" if score >= 55 else
        "SELL" if score >= 40 else
        "STRONG_SELL"
    )
    reach = prob.get("reachTargetPct")

    payload = {
        "source": "market-compass-12stage",
        "asOf": result.get("asOf"),
        "stock": st,
        "composite": comp,
        "market": result.get("market"),  # regime + rotationLadder + sectorRanking + vkospi
        "mtf": result.get("mtf"),
        "targets": result.get("targets"),
        "stops": result.get("stops"),
        "probability": prob,
        "series": result.get("series"),
        "shortSelling": result.get("shortSelling"),
        "tradePlan": result.get("tradePlan"),
        "aiReport": result.get("aiReport"),
        "aiProvider": result.get("aiProvider"),
    }

    session = db.get_session_factory()()
    try:
        row = session.execute(
            select(models.AiAnalysisCache).where(
                models.AiAnalysisCache.stock_code == st.get("code")
            )
        ).scalar_one_or_none()
        if row is None:
            session.add(models.AiAnalysisCache(
                stock_code=st.get("code"),
                stock_name=st.get("name"),
                analyzed_at=_dt.utcnow(),
                signal=signal,
                confidence=score,
                upside_probability=float(reach) if reach is not None else None,
                result_json=payload,
            ))
        else:
            row.stock_name = st.get("name") or row.stock_name
            row.analyzed_at = _dt.utcnow()
            row.signal = signal
            row.confidence = score
            row.upside_probability = float(reach) if reach is not None else None
            row.result_json = payload
        session.commit()
    finally:
        session.close()


def _call_stock_llm(context: dict) -> tuple[Optional[str], str]:
    """market_compass 의 LLM 폴백 체인을 종목용 시스템 프롬프트로 재사용."""
    import market_compass as mc

    saved = mc._SYSTEM_PROMPT
    try:
        mc._SYSTEM_PROMPT = _SYSTEM_PROMPT
        return mc._call_llm(json.dumps(context, ensure_ascii=False))
    finally:
        mc._SYSTEM_PROMPT = saved
