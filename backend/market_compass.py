"""시장 나침반 (Market Compass) — 자금 흐름 추적 프레임워크.

거시경제 → 유동성 → 정책 → 섹터 → 산업 → 종목 → 수급 → 차트 흐름을 점수화해
"지금 시장의 자금은 어디서 와서 어디로 가고 있는가?"를 자동 계산한다.

구조 (월가 리서치 하우스 방식):
  [결정론 레이어] 1~4단계 — 데이터로 직접 계산 (LLM 없음, 재현 가능)
    1. 시장 구조 판정  : 유동성/실적/정책/테마/위기 장세 — 규칙 기반 + 근거
    2. 거시경제 분석   : sector_rotation 매크로 디테일 → 섹터 유불리 매핑
    3. 섹터 순환 위치  : 현금→방어주→경기민감주→성장주→고위험테마 사다리
    4. 주도 섹터 순위  : 8레이어 점수 (기존 sector_rotation 엔진)
  [LLM 레이어] 5~12단계 — 계산된 데이터를 컨텍스트로 종합 추론
    Gemini > Groq > OpenAI 우선순위 (settings 의 키 사용)
    LLM은 제공된 데이터만 근거로 쓰도록 강제 — 환각으로 만든 수치 금지.

데이터 정확성 원칙: 모든 수치는 계산 레이어가 제공하고, LLM은 해석만 한다.
뉴스·산업 세부·종목 차트(5~11단계 일부)는 Phase 2에서 데이터 수집 후 활성화.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx

from settings import settings

# Windows 파일락(claude 전역 직렬화)용. 윈도우 전용 시스템이지만 비윈도우에서 import 실패해도
# 모듈 로드는 깨지지 않도록 가드 — msvcrt 부재 시 직렬화 없이 통과(개발 편의).
try:
    import msvcrt
except ImportError:  # pragma: no cover - 비윈도우
    msvcrt = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# 캐시 (장중 30분 / 장외 8시간 — LLM 호출 비용 절약)
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_cache: Optional[dict] = None
_cache_ts: float = 0.0


def _ttl() -> int:
    now = datetime.now()
    if now.weekday() < 5 and (9 * 60 <= now.hour * 60 + now.minute <= 15 * 60 + 30):
        return 1800
    return 28800


# ---------------------------------------------------------------------------
# 섹터 그룹 (순환 사다리용) — sector_classification 12섹터 기준
# ---------------------------------------------------------------------------
DEFENSIVE_SECTORS = {"금융", "소비재"}                                  # 방어주
CYCLICAL_SECTORS = {"조선", "화학", "전력 인프라", "방산"}              # 경기민감주
GROWTH_SECTORS_G = {"반도체", "AI 생태계", "2차전지", "바이오"}         # 성장주
THEME_SECTORS = {"로봇 AI"}                                             # 고위험 테마주


def _vkospi_context() -> dict:
    """VKOSPI 레벨 + 추세 (위기 장세 판정의 핵심 입력)."""
    out = {"value": None, "chg5d": None, "level": "unknown"}
    try:
        import db
        import models
        from sqlalchemy import select

        s = db.get_session_factory()()
        try:
            rows = s.execute(
                select(models.VkospiHistory.close)
                .order_by(models.VkospiHistory.trade_date.desc())
                .limit(6)
            ).scalars().all()
        finally:
            s.close()
        if rows:
            cur = float(rows[0])
            out["value"] = round(cur, 2)
            if len(rows) >= 6 and rows[5]:
                out["chg5d"] = round((cur - float(rows[5])) / float(rows[5]) * 100, 1)
            out["level"] = (
                "극단적 공포" if cur >= 50 else
                "공포" if cur >= 30 else
                "평시" if cur >= 20 else
                "안정"
            )
    except Exception:
        pass
    return out


def _us_lead_context(force: bool = False) -> dict:
    """US 선행 심리 (us-leaders-lead-lag) — 시장 나침반 보조 지표.

    us_lead.compute_us_lead() 의 섹터별 lead_score·composite·evidence 를 그대로 싣는다
    (결정론, LLM 미호출). 엔진 실패/무데이터면 {available:False} 또는 note 동반 — 본체는
    정상 동작(회귀 없음). composite=섹터 lead_score 평균(0~100, 50=중립).
    """
    try:
        import us_lead

        u = us_lead.compute_us_lead(force=force)
        scored = {s: v for s, v in u.get("sectors", {}).items() if v.get("n", 0) > 0}
        return {
            "available": bool(scored),
            "composite": u.get("composite"),
            "asof": u.get("asof"),
            "sectors": {
                s: {
                    "leadScore": v["lead_score"],
                    "avgOvernightPct": v.get("avg_overnight_pct"),
                    "leadLagDays": v.get("lead_lag_days"),
                    "topMovers": v.get("top_movers", []),
                }
                for s, v in scored.items()
            },
            "evidence": {s: u["evidence"].get(s) for s in scored},
            "note": u.get("note"),
        }
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": f"us_lead 실패: {type(exc).__name__}"}


def _stage0_global_sentiment(force: bool = False) -> dict:
    """[0단계] 글로벌 투자심리 (스펙 §4.2) — 국내 regime 판정에 선행.

    global_macro.compute_global_macro() 의 8점수·composite·flow·확률·한국섹터를 그대로 싣는다.
    force 면 글로벌 레이어도 재계산(시장 재분석 버튼이 글로벌까지 갱신하도록 전파).
    엔진 실패 시 {available: False} 로 fail-soft — market_compass 본체는 정상 동작(회귀 없음).
    """
    try:
        import global_macro

        g = global_macro.compute_global_macro(force=force)
        return {
            "available": True,
            "scores": g.get("scores", {}),
            "composite": g.get("composite"),
            "flow": g.get("flow"),
            "probabilities": g.get("probabilities"),
            "krSectors": g.get("kr_sectors"),
            "krSectorMatrix": g.get("kr_sector_matrix"),
            "riskSignals": g.get("risk_signals"),
            "evidence": g.get("evidence"),
            "asof": g.get("asof"),
        }
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": f"global_macro 실패: {type(exc).__name__}"}


def _stage1_market_regime(macro: dict, vkospi: dict, sectors: list[dict],
                          global_sent: Optional[dict] = None,
                          us_lead: Optional[dict] = None) -> dict:
    """[1단계] 시장 구조: 유동성/실적/정책/테마/위기 장세 판정 (규칙 기반 + 근거).

    global_sent(0단계)가 가용하면 글로벌 Risk-On/Off 를 보조 신호로 반영한다(과긍정/과부정 보정).
    us_lead(US 선행 심리)가 가용하면 composite(밤사이 반도체·AI 방향)를 보조 신호로 반영한다.
    둘 다 None 이면 기존 5개 국내 신호만으로 판정 — 회귀 없음.
    """
    evidence: list[str] = []
    scores = {"유동성 장세": 0.0, "실적 장세": 0.0, "정책 장세": 0.0, "테마 장세": 0.0, "위기 장세": 0.0}

    if us_lead and us_lead.get("available"):
        comp = us_lead.get("composite")
        if comp is not None:
            if comp >= 60:
                scores["테마 장세"] += 0.5
                evidence.append(f"US 선행 {comp}/100 — 밤사이 반도체·AI 강세(KR 성장주 우호)")
            elif comp <= 40:
                scores["위기 장세"] += 0.5
                evidence.append(f"US 선행 {comp}/100 — 밤사이 반도체·AI 약세(KR 개장 부담)")

    if global_sent and global_sent.get("available"):
        gs = global_sent.get("scores", {})
        ra = gs.get("risk_appetite")
        gliq = gs.get("liquidity")
        if ra is not None:
            if ra >= 65:
                scores["테마 장세"] += 0.5
                evidence.append(f"글로벌 위험선호 {ra}/100 — Risk-On(성장·테마 우호)")
            elif ra <= 35:
                scores["위기 장세"] += 1
                evidence.append(f"글로벌 위험선호 {ra}/100 — Risk-Off(위험회피)")
        if gliq is not None and gliq >= 60:
            scores["유동성 장세"] += 0.5
            evidence.append(f"글로벌 유동성 {gliq}/100 — 유동성 우호")

    vk = vkospi.get("value")
    if vk is not None:
        if vk >= 50:
            scores["위기 장세"] += 3
            evidence.append(f"VKOSPI {vk} — 극단적 공포 구간 (2008년 위기 ~80, 평시 20~30)")
        elif vk >= 30:
            scores["위기 장세"] += 1.5
            evidence.append(f"VKOSPI {vk} — 공포 구간(30 이상)")
        else:
            evidence.append(f"VKOSPI {vk} — 평시 수준")

    tnx_chg = float(macro.get("tnx20dChg") or 0)
    if tnx_chg < -3:
        scores["유동성 장세"] += 2
        evidence.append(f"미 10Y 금리 20일 {tnx_chg}% 하락 — 유동성 우호")
    elif tnx_chg > 3:
        scores["위기 장세"] += 0.5
        evidence.append(f"미 10Y 금리 20일 {tnx_chg}% 상승 — 유동성 압박")

    krw = float(macro.get("usKrw") or 0)
    if krw >= 1450:
        scores["위기 장세"] += 1
        evidence.append(f"원달러 {krw} — 위험회피(원화 약세) 심화")

    nas20 = float(macro.get("nasdaqChg20d") or 0)
    if nas20 > 5:
        scores["테마 장세"] += 1
        scores["유동성 장세"] += 0.5
        evidence.append(f"나스닥 20일 +{nas20}% — 글로벌 성장주 위험선호")
    elif nas20 < -5:
        scores["위기 장세"] += 1
        evidence.append(f"나스닥 20일 {nas20}% — 글로벌 위험회피")

    # 섹터 점수 분산: 특정 테마 섹터만 독주하면 테마 장세 성격
    if sectors:
        top = sectors[0]
        spread = top["score"] - sectors[-1]["score"]
        if spread >= 25:
            scores["테마 장세"] += 1
            evidence.append(f"섹터 점수 격차 {spread:.0f}p — 자금이 소수 섹터에 집중")

    regime = max(scores, key=lambda k: scores[k])
    if scores[regime] == 0:
        regime = "실적 장세"
        evidence.append("뚜렷한 극단 신호 없음 — 기본값(실적 장세)")
    return {"label": regime, "scores": scores, "evidence": evidence}


def _stage2_macro_map(macro: dict, global_scores: Optional[dict] = None) -> list[dict]:
    """[2단계] 거시 요소별 → 유리한 섹터 매핑 (현재값 기준).

    기존 5개 국내 거시 행(US10Y·원달러·WTI·나스닥·VIX) 뒤에 글로벌 매크로 4행을 덧붙인다
    (스펙 §4.1). global_scores 가 없으면(엔진 실패) 기존 5행만 반환 — 회귀 없음.
    """
    rows = []

    def add(factor, value, favors, why):
        rows.append({"factor": factor, "value": value, "favors": favors, "why": why})

    tnx = macro.get("tnx")
    if tnx is not None:
        add("미 10Y 금리", f"{tnx}% (20일 {macro.get('tnx20dChg', 0):+}%)",
            ["금융"] if float(macro.get("tnx20dChg") or 0) > 0 else ["반도체", "AI 생태계", "바이오"],
            "금리 상승=은행 마진 개선, 하락=성장주 할인율 완화")
    krw = macro.get("usKrw")
    if krw is not None:
        add("원달러", f"{krw} (5일 {macro.get('usKrwChg5d', 0):+}%)",
            ["조선", "방산", "반도체"] if float(krw) > 1380 else ["금융", "소비재"],
            "원화 약세=수출주(조선·방산·반도체) 환차익, 강세=내수 구매력")
    oil = macro.get("oil")
    if oil is not None:
        add("유가(WTI)", f"${oil} (5일 {macro.get('oilChg5d', 0):+}%)",
            ["화학"] if float(macro.get("oilChg5d") or 0) < 0 else ["조선"],
            "유가 하락=화학 원가 개선, 상승=해양플랜트·시추 발주 기대")
    nas = macro.get("nasdaq")
    if nas is not None:
        add("나스닥", f"{nas} (20일 {macro.get('nasdaqChg20d', 0):+}%)",
            ["반도체", "AI 생태계", "로봇 AI"],
            "미 기술주와 동조화 — AI 밸류체인 위험선호 지표")
    vix = macro.get("vix")
    if vix is not None:
        add("VIX(미국)", str(vix),
            ["금융", "소비재"] if float(vix) > 25 else ["반도체", "AI 생태계"],
            "VIX 상승 국면은 방어주, 안정 국면은 성장주 우위")

    # --- 글로벌 매크로 4행 (스펙 §4.1) — 점수 임계로 favors 선택, 기존 패턴 준수 ---
    g = global_scores or {}
    ra = g.get("risk_appetite")
    if ra is not None:
        add("글로벌 위험선호", f"{ra}/100",
            ["반도체", "AI 생태계", "로봇 AI"] if ra >= 50 else ["금융", "소비재"],
            "VIX·신용·BTC·S&P 종합 — 위험선호 高=성장주, 低=방어주")
    liq = g.get("liquidity")
    if liq is not None:
        add("글로벌 유동성", f"{liq}/100",
            ["반도체", "AI 생태계", "바이오"] if liq >= 50 else ["금융"],
            "Fed경로·US10Y·DXY 종합 — 유동성 우호=성장주 할인율 완화")
    ai = g.get("ai_cycle")
    if ai is not None:
        add("AI 투자사이클", f"{ai}/100", ["반도체", "AI 생태계"],
            "빅테크 Capex·SOX·나스닥 모멘텀 — AI 밸류체인 구조 주도")
    geo = g.get("geopolitics")
    if geo is not None:
        # 점수↑=리스크완화. 리스크 高(점수 低)면 방산·조선 수혜
        add("지정학 리스크", f"{geo}/100",
            ["반도체", "AI 생태계"] if geo >= 50 else ["방산", "조선"],
            "예측시장·뉴스·Gold 종합 — 점수↑=리스크완화(성장주), 低=방산·조선")
    return rows


def _stage3_rotation_ladder(sectors: list[dict]) -> dict:
    """[3단계] 현금→방어주→경기민감주→성장주→고위험테마 사다리에서 현재 위치."""
    groups = {
        "방어주": DEFENSIVE_SECTORS,
        "경기민감주": CYCLICAL_SECTORS,
        "성장주": GROWTH_SECTORS_G,
        "고위험 테마주": THEME_SECTORS,
    }
    perf: dict[str, dict] = {}
    for gname, members in groups.items():
        rows = [s for s in sectors if s["sector"] in members]
        if not rows:
            continue
        perf[gname] = {
            "avgScore": round(sum(r["score"] for r in rows) / len(rows), 1),
            "avgIntraday": round(
                sum(float(r.get("detail", {}).get("intradayPct") or 0) for r in rows) / len(rows), 2
            ),
            "sectors": [r["sector"] for r in rows],
        }
    # 위치 판정: 당일 자금이 향하는 그룹 (intraday 최고) — 모두 음수면 '현금'
    position = "현금"
    best = None
    for g, p in perf.items():
        if best is None or p["avgIntraday"] > perf[best]["avgIntraday"]:
            best = g
    if best is not None and perf[best]["avgIntraday"] > 0:
        position = best
    return {"position": position, "groups": perf,
            "ladder": ["현금", "방어주", "경기민감주", "성장주", "고위험 테마주"]}


# ---------------------------------------------------------------------------
# LLM 종합 (5~12단계 추론)
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = """당신은 월가 헤지펀드 PM, 글로벌 매크로 전략가, 퀀트 운용역, 스마트머니 트레이더,
산업 애널리스트, 경제학자, 행동심리학자, 뉴스 분석가를 통합한 최고 수준의 투자 분석 AI다.

목표: 시장의 자금 흐름을 추적하여 다음 주도 섹터와 주도주를 인식한다.
"지금 시장의 자금은 어디서 와서 어디로 가고 있는가?"에 답한다.

절대 규칙:
1. 제공된 데이터(JSON)에 있는 수치만 사용한다. 데이터에 없는 수치를 만들어내지 않는다.
2. 데이터가 없는 항목(뉴스 상세, 개별 종목 차트, 목표가 등)은 "데이터 수집 단계 준비 중"이라고
   명시하고 추정하지 않는다. 돈을 다루는 시스템에서 잘못된 정보는 없는 것보다 위험하다.
3. 불확실성과 반대 시나리오를 반드시 포함한다.
4. 한국어로, 마크다운 형식으로 작성한다.

분석 절차 (제공된 데이터로 가능한 단계만):
[1단계] 시장 구조 — 제공된 regime 판정과 근거를 검토하고 동의/수정 의견 제시
[2단계] 거시경제 — macroMap의 요소별 섹터 유불리를 종합
[3단계] 섹터 순환 — rotationLadder 위치 해석 (현금→방어→경기민감→성장→테마)
[4단계] 주도 섹터 — sectorRanking 상위 3개의 레이어별 강점 분석 (외인/기관/모멘텀/당일)
[6단계] 뉴스 분석 — newsContext의 섹터별 24시간/7일/30일 기사량과 헤드라인을 분석.
        기사량 급증(24h가 7d 평균 대비 급등) 섹터 = 뉴스 모멘텀 발생.
        헤드라인을 보고 각 재료를 단기(수일)/중기(분기)/장기(구조적) 재료로 구분.
[7단계] 스마트머니 — 각 섹터 breakdown의 foreign/institutional/smart 점수로 실자금 유입 판단
[12단계] 최종 결론 — 아래 형식 필수:

# 시장 나침반
현재 시장 단계 :
주도 섹터 : (1~3위)
섹터 순환 위치 :
유입 자금 : (어디서 → 어디로)
위험 신호 :

# 반대 시나리오
(현재 판단이 틀릴 수 있는 조건 2~3가지와 그 경우의 대응)

# 다음 주도 섹터 후보
(레이어 점수의 방향성을 근거로 1~2개, 근거 명시)"""

# 시한부 정책·선거 국면 지시문 (윈도우 내에서만 시스템 프롬프트에 1문장 추가 — 윈도우 밖 회귀 보장)
_POLICY_DIRECTIVE = (
    "정책·선거 국면: 컨텍스트의 policyRegime 신호(트럼프 정책행동·해당 예측시장 반응)를 "
    "상위 가중해 해석하되, 제공된 수치만 근거로 쓸 것(환각 금지)."
)

# 정책 뉴스 토픽 키워드 (결정론 태깅 — LLM 미사용). news_collector 헤드라인에서 트럼프 정책행동 탐지.
_POLICY_NEWS_KW = {
    "관세": ["관세", "tariff", "무역전쟁", "수입세"],
    "연준압박": ["파월", "연준", "fed", "연준의장", "금리 인하 압박", "해임"],
    "셧다운": ["셧다운", "shutdown", "부채한도", "debt ceiling"],
    "선거": ["중간선거", "midterm", "하원", "상원", "공화당", "민주당"],
}

# policyRegime 에 surface 할 정치·Fed 예측 타깃 (global_macro_feeds.POLICY_PREDICTION_TARGETS 중 실조회분)
_POLICY_REGIME_KEYS = ["fed_cut_next", "fed_path_eoy", "us_gov_shutdown"]


def _scan_policy_news(news_ctx: dict, limit: int = 12) -> list[dict]:
    """뉴스 헤드라인에서 정책 토픽(관세·연준압박·셧다운·선거)을 결정론 태깅. 중복 제목 제거."""
    out: list[dict] = []
    seen: set[str] = set()
    for sec in ((news_ctx or {}).get("sectors") or {}).values():
        for h in sec.get("headlines", []):
            title = h.get("title", "")
            t = title.lower()
            for topic, kws in _POLICY_NEWS_KW.items():
                if any(k.lower() in t for k in kws):
                    if title not in seen:
                        seen.add(title)
                        out.append({"topic": topic, "title": title})
                    break
            if len(out) >= limit:
                return out
    return out


def _policy_regime(news_ctx: dict) -> dict:
    """[시한부] policyRegime 블록 — 트럼프 정책행동(뉴스) + 정치·Fed 예측시장 반응(수치).

    윈도우 내에서만 호출된다. 예측시장 수치는 global_macro(캐시) 의 원천 consensus 만 사용(환각 금지).
    """
    import global_macro
    import global_macro_feeds as gmf

    try:
        g = global_macro.compute_global_macro()
        preds = (g.get("inputs") or {}).get("prediction") or {}
    except Exception:
        preds = {}

    markets: list[dict] = []
    for key in _POLICY_REGIME_KEYS:
        row = preds.get(key)
        if not row:
            continue
        markets.append({
            "key": key,
            "label": row.get("label"),
            "consensus": row.get("consensus"),
            "polymarket": row.get("polymarket"),
            "kalshi": row.get("kalshi"),
            "nSources": row.get("n_sources"),
            "weightMode": row.get("weight_mode"),
            "feedsInto": row.get("feeds_into"),
        })

    return {
        "active": True,
        "windowUntil": gmf.ELECTION_WINDOW_UNTIL.isoformat(),
        "note": ("미 중간선거(2026-11-03) 시한부 — 정치·Fed 예측시장 신호를 "
                 "Polymarket 0.6/Kalshi 0.4로 상위 가중. 모든 수치는 엔진 산출 원천값."),
        "predictionMarkets": markets,
        "policyNews": _scan_policy_news(news_ctx),
    }


# Groq 폴백 전용 — context 에서 우선 트림할 부피 큰/보조 섹션 (왼쪽부터 제거).
# 핵심 결정론 신호(regime·macroMap·rotationLadder·sectorRanking·vkospi / stock·mtf·targets·
# stops·composite)는 남기고, 부피 크고 보조적인 섹션부터 버린다. gemini/openai 엔 영향 없음.
_GROQ_DROP_ORDER = (
    "dotcomCasebook",     # 닷컴 사례집 (stock, 부피 큰 보조 근거)
    "series",             # 과거 시계열 (stock, 최대 부피)
    "newsContext",        # 시장 뉴스 상세 (market)
    "usLead",             # US 선행 종목 (market)
    "globalSentiment",    # 글로벌 투자심리 상세 (market)
    "signalTrackRecord",  # 시그널 과거 적중 그라운딩 (stock)
    "recentNews",         # 종목 최근 뉴스 (stock)
    "etfHoldings",        # ETF 구성종목 (stock)
    "businessProfile",    # 산업·사업 프로필 (stock)
    "policyRegime",       # 정책·선거 국면 블록
    "dataNotes",          # 안내 메모
    "probability",        # 확률 상세 (stock, 무거움 — 후순위로 양보)
    "tradePlan",          # 분할매수/매집 (stock)
)


def _slim_context_for_groq(context_json: str, budget: int) -> tuple[str, list[str]]:
    """groq 무료 TPM 한도 이하로 context 를 축약. (json문자열, 제거된섹션목록) 반환.

    1) 한도 이내면 그대로 둔다.
    2) _GROQ_DROP_ORDER 순으로 섹션을 제거하며 매번 한도 도달 여부 확인.
    3) 그래도 초과하면 mtf 타임프레임의 부피 큰 하위항목(매물대/FVG/유동성/CDV)을 비운다.
    4) 최후엔 문자열을 하드 캡한다. JSON 파싱 실패 시에도 하드 캡으로 안전 동작.
    """
    if len(context_json) <= budget:
        return context_json, []
    try:
        ctx = json.loads(context_json)
    except Exception:  # noqa: BLE001
        return context_json[:budget] + "\n…(groq 한도 초과로 절단)", ["<hard-cap>"]

    dropped: list[str] = []
    for key in _GROQ_DROP_ORDER:
        if key in ctx:
            ctx.pop(key, None)
            dropped.append(key)
            if len(json.dumps(ctx, ensure_ascii=False)) <= budget:
                return json.dumps(ctx, ensure_ascii=False), dropped

    # 중첩 트림 — mtf 타임프레임의 부피 큰 하위항목 제거 (정렬/추세/RSI/구조이벤트는 유지)
    tfs = (ctx.get("mtf") or {}).get("timeframes")
    if isinstance(tfs, list):
        for t in tfs:
            if isinstance(t, dict):
                for k in ("volumeProfile", "fvg", "liquidity", "cdv"):
                    t.pop(k, None)
        dropped.append("mtf.timeframes.detail")

    out = json.dumps(ctx, ensure_ascii=False)
    if len(out) <= budget:
        return out, dropped
    return out[:budget] + "\n…(groq 한도 초과로 절단)", dropped + ["<hard-cap>"]


# 런타임 claude on/off — settings.claude_cli_enabled(전역 기본값) 위에 얹는 프로세스 단위
# 스위치. 배치(batch_analyze.py)가 MAX 예산 소진 시 이후 종목에 대해 claude 를 끄고
# gemini/groq 로 강등시키는 데 쓴다. 기본 True(설정값 그대로). 단일 프로세스 내 직렬 호출
# 전제라 락 없이 단순 전역으로 충분하다.
_claude_runtime_enabled = True

# narrative claude 경로 게이트(settings.claude_narrative_path == "idle_only"):
# 정규 배치/온디맨드 경로는 claude 를 쓰지 않고(동시성 충돌 원천 제거), idle 필러
# (scripts/narrate_one.py, 단일 프로세스·직렬)만 이 플래그를 켜서 주도주 예산 내로 claude
# 품질 narrative 를 채운다. "all" 모드에선 무시(모든 경로가 claude 1순위 시도).
_claude_idle_optin = False


def set_claude_runtime(enabled: bool) -> None:
    """이 프로세스의 claude 1순위 사용 여부를 런타임에 토글. (배치 예산 가드용)"""
    global _claude_runtime_enabled
    _claude_runtime_enabled = bool(enabled)


def set_claude_idle_optin(enabled: bool) -> None:
    """이 프로세스를 'idle 필러 경로'로 표시 — idle_only 정책에서 claude 사용을 허용한다.

    narrate_one.py(idle 스케줄러 헬퍼)만 호출한다. 정규 배치/서버 경로는 호출하지 않으므로
    idle_only 정책에서 claude 를 시도하지 않고 곧장 gemini/groq 로 간다(조용히).
    """
    global _claude_idle_optin
    _claude_idle_optin = bool(enabled)


# claude 사용량 공유 원장(scripts/claude_usage.py) 지연 로딩. 배치/필러 경로는 sys.path 에
# scripts 가 있어 바로 import 되고, 백엔드 서버 경로는 여기서 scripts 를 path 에 얹어 import 한다.
# False = 이전에 import 실패(원장 미가용) — 예산 판정 불가 시 호출측 게이팅에 위임한다.
_claude_usage_mod = None


def _get_claude_usage():
    global _claude_usage_mod
    if _claude_usage_mod is not None:
        return _claude_usage_mod or None
    try:
        import claude_usage  # type: ignore
    except ImportError:
        scripts_dir = str(Path(__file__).resolve().parents[1] / "scripts")
        if scripts_dir not in sys.path:
            sys.path.append(scripts_dir)
        try:
            import claude_usage  # type: ignore
        except Exception:  # noqa: BLE001
            _claude_usage_mod = False
            return None
    _claude_usage_mod = claude_usage
    return claude_usage


def _claude_budget_exhausted() -> bool:
    """일/주 캡 도달 여부(공유 원장 기준). 원장 미가용/오류 시 막지 않음(False)."""
    cu = _get_claude_usage()
    if cu is None:
        return False
    try:
        return bool(cu.exhausted(settings.claude_daily_cap, settings.claude_weekly_cap))
    except Exception:  # noqa: BLE001
        return False


def _record_claude_usage() -> None:
    """claude 호출 1건을 공유 원장(logs/claude-usage.json)에 누적. 원장 미가용 시 무시.

    실제 호출 지점에서 기록하는 '단일 소스' — 어느 경로(배치/idle 필러/서버)가 claude 를
    쓰든 여기서만 카운트한다. 호출부는 더 이상 따로 증가시키지 않고 원장을 재조회만 한다.
    (호출은 전역 호출락으로 직렬화되므로 이 record 의 read-modify-write 도 경쟁하지 않는다.)
    """
    cu = _get_claude_usage()
    if cu is None:
        return
    try:
        cu.record(1)
    except Exception:  # noqa: BLE001
        pass


def _claude_active() -> bool:
    """claude 1순위 narrative 를 '시도할 가치가 있는' 상태인지. False 면 호출부가 조용히 폴백."""
    if not settings.claude_cli_enabled or not _claude_runtime_enabled:
        return False
    # 경로 게이트: idle_only 정책에선 idle 필러가 opt-in 한 프로세스에서만 claude 시도.
    if settings.claude_narrative_path == "idle_only" and not _claude_idle_optin:
        return False
    # 예산 게이트: 일/주 캡 도달 시 조용히 폴백(에러 아님).
    if _claude_budget_exhausted():
        return False
    return True


# ---------------------------------------------------------------------------
# claude 전역 호출락 — 단일 MAX 구독 세션을 동시에 1건만 점유(동시성 1).
# 여러 프로세스(수동 배치·정규 배치·idle 필러)가 동시에 claude.cmd 를 때리면 MAX rate/동시성을
# 못 견뎌 대부분 실패하므로, 전역 파일락으로 직렬화한다. 락 획득 실패(타 프로세스 사용 중)면
# 대기 없이 즉시 None 반환 → 호출부가 gemini/groq 로 강등. 프로세스가 죽어도 OS 가 파일락을
# 자동 해제하므로 stale 락이 남지 않는다.
# ---------------------------------------------------------------------------
_CLAUDE_LOCK_PATH = Path(__file__).resolve().parents[1] / "logs" / "claude-call.lock"


def _acquire_claude_lock():
    """비대기(non-blocking) 전역 락 시도. 성공 시 파일 핸들, 점유 중이면 None.

    msvcrt 부재(비윈도우) 시 직렬화 없이 통과하도록 핸들만 반환한다.
    """
    try:
        _CLAUDE_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        fh = open(_CLAUDE_LOCK_PATH, "a+b")
    except OSError:
        return None
    if msvcrt is None:  # 비윈도우 — 직렬화 미적용, 그대로 진행
        return fh
    try:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)  # 1바이트 비대기 배타락
    except OSError:
        fh.close()
        return None  # 다른 프로세스가 claude 점유 중
    return fh


def _release_claude_lock(fh) -> None:
    if fh is None:
        return
    try:
        if msvcrt is not None:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass
    finally:
        try:
            fh.close()
        except OSError:
            pass


def _call_claude_cli(prompt: str, timeout: Optional[int] = None) -> Optional[str]:
    """claude -p (Claude Code MAX 구독) 로 narrative 생성. stdin 으로 프롬프트 전달(UTF-8).

    성공 시 stdout 텍스트, 실패/타임아웃/빈 출력/비활성화 시 None → 호출부가 gemini/groq/
    openai 체인으로 자연 강등(무중단). 결정론 점수·로직과 무관하며 narrative 생성 전용이다.

    개발단계 단일 사용 전제(본인+테스터 소수, MAX 구독 1계정). 동시 다발 호출은 MAX rate 와
    인터랙티브 사용을 침범하므로 idle 스케줄러(scripts/idle_narrative_filler.ps1)가 호출 빈도
    /상한을 통제한다.

    TODO(public-service): 외부 공개 서비스로 전환하면 claude.cmd CLI 를 정식 Anthropic API
    (키 기반 과금 + rate-limit 처리)로 교체할 것. CLI 는 단일 사용자 MAX 구독 전용이다.
    """
    if not settings.claude_cli_enabled:
        return None
    path = settings.claude_cli_path
    if not path or not os.path.exists(path):
        return None
    timeout = timeout if timeout is not None else settings.claude_cli_timeout
    # .cmd/.bat 은 CreateProcess 가 직접 실행하지 못하므로 cmd.exe 경유로 기동.
    if os.name == "nt" and path.lower().endswith((".cmd", ".bat")):
        argv = ["cmd", "/c", path, "-p"]
    else:
        argv = [path, "-p"]
    try:
        proc = subprocess.run(
            argv,
            input=prompt.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None
    except Exception:  # noqa: BLE001
        return None
    if proc.returncode != 0:
        return None
    text = (proc.stdout or b"").decode("utf-8", errors="replace").strip()
    return text or None


def _call_llm(context_json: str, policy_active: bool = False) -> tuple[Optional[str], str]:
    """Claude(MAX) > Gemini > Groq > OpenAI 우선순위로 종합 리포트 생성. (리포트, 프로바이더) 반환.

    실패 시 다음 프로바이더로 폴백하고, 전부 실패하면 마지막 오류를 프로바이더 문자열에 담는다.
    """
    user_msg = (
        "다음은 실시간 계산된 시장 데이터다. 이 데이터만 근거로 분석 절차를 수행하라.\n\n"
        f"```json\n{context_json}\n```"
    )
    # 윈도우 밖(policy_active=False)에서는 시스템 프롬프트가 기존과 완전히 동일 — 회귀 없음.
    system_prompt = _SYSTEM_PROMPT + (("\n\n" + _POLICY_DIRECTIVE) if policy_active else "")
    errors: list[str] = []

    # Claude CLI (MAX 구독) — 1순위. 수치 정확·절제(없는 값 안 지어냄) 실측 우위로 머니시스템에
    # 적합. CLI 는 system/user 역할 분리가 없어 시스템 프롬프트를 프롬프트 본문에 합쳐 전달한다.
    # _claude_active() 가 False(경로/예산/비활성)면 '조용히' 폴백 — 에러로 남기지 않는다.
    # 활성이면 전역 호출락으로 동시성 1 보장: 타 프로세스가 점유 중이면 대기 없이 즉시 강등하고
    # 정보 로그만 남긴다("claude busy"). 실패/타임아웃/빈 출력도 gemini/groq/openai 로 자연 강등.
    if _claude_active():
        lock = _acquire_claude_lock()
        if lock is None:
            # 다른 프로세스가 claude 점유 중 — 대기 금지, 즉시 폴백(에러 아님, 정보 로그).
            print("[market_compass] claude busy → gemini/groq 폴백", file=sys.stderr, flush=True)
        else:
            claude_text = None
            try:
                claude_text = _call_claude_cli(f"{system_prompt}\n\n{user_msg}")
                if claude_text:
                    # 성공 시 락 보유 중 공유 예산 원장에 기록(단일 소스, 경쟁 방지).
                    _record_claude_usage()
            finally:
                _release_claude_lock(lock)
            if claude_text:
                return claude_text, "claude:max"
            # 실제 시도했으나 빈 출력/실패(타임아웃 등) — 폴백 진행. 동시성/예산 오염과 구분되는
            # 드문 케이스라 'unavailable'(혼동 유발) 대신 'no-output' 으로 표기.
            errors.append("claude no-output")

    # Gemini (2.5-flash 는 thinking 토큰을 쓰므로 출력 한도를 넉넉히)
    # 무료 티어 레이트리밋(429) 대비 1회 재시도.
    if settings.gemini_api_key:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{settings.gemini_model}:generateContent?key={settings.gemini_api_key}"
        )
        body = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_msg}]}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 16384},
        }
        for attempt in (1, 2):
            try:
                r = httpx.post(url, json=body, timeout=120.0)
                # 429(rate-limit): 20s 후 재시도, 503(일시적 불가): 15s 후 재시도
                if r.status_code in (429, 503) and attempt == 1:
                    time.sleep(20 if r.status_code == 429 else 15)
                    continue
                r.raise_for_status()
                cand = r.json().get("candidates", [{}])[0]
                parts = cand.get("content", {}).get("parts") or []
                text = "".join(p.get("text", "") for p in parts).strip()
                if text:
                    return text, f"gemini:{settings.gemini_model}"
                errors.append(f"gemini empty (finishReason={cand.get('finishReason')})")
                break
            except httpx.HTTPStatusError as exc:
                errors.append(f"gemini HTTP {exc.response.status_code}")
                break
            except Exception as exc:  # noqa: BLE001
                errors.append(f"gemini {type(exc).__name__}")
                break

    # Groq / OpenAI (OpenAI 호환) — 429 rate-limit 시 30s 후 1회 재시도
    for name, key, model, base in (
        ("groq", settings.groq_api_key, settings.groq_model, "https://api.groq.com/openai/v1"),
        ("openai", settings.openai_api_key, settings.openai_model, "https://api.openai.com/v1"),
    ):
        if not key:
            continue
        # groq 폴백만: 무료 TPM(12k) 한도 내로 context 트림 + 완성 토큰 캡 → 413 방지.
        # gemini/openai 엔 full 프롬프트 유지(품질 불변).
        provider_user_msg = user_msg
        if name == "groq":
            slim_json, dropped = _slim_context_for_groq(context_json, settings.groq_ctx_char_budget)
            if dropped:
                provider_user_msg = (
                    "다음은 실시간 계산된 시장 데이터다. 이 데이터만 근거로 분석 절차를 수행하라.\n"
                    "(폴백 모델 토큰 한도로 일부 보조 섹션이 생략됨 — 주어진 수치만 사용)\n\n"
                    f"```json\n{slim_json}\n```"
                )
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": provider_user_msg},
            ],
            "temperature": 0.3,
        }
        if name == "groq":
            payload["max_tokens"] = settings.groq_max_tokens
        for attempt in (1, 2):
            try:
                r = httpx.post(
                    f"{base}/chat/completions",
                    headers={"Authorization": f"Bearer {key}"},
                    json=payload,
                    timeout=120.0,
                )
                if r.status_code == 429 and attempt == 1:
                    time.sleep(30)
                    continue
                r.raise_for_status()
                text = (r.json()["choices"][0]["message"]["content"] or "").strip()
                if text:
                    return text, f"{name}:{model}"
                errors.append(f"{name} empty")
                break
            except httpx.HTTPStatusError as exc:
                errors.append(f"{name} HTTP {exc.response.status_code}")
                break
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{name} {type(exc).__name__}")
                break
    return None, f"none ({'; '.join(errors)})" if errors else "none"


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------
def compute_market_compass(force: bool = False, with_ai: bool = True) -> dict:
    global _cache, _cache_ts
    with _lock:
        if not force and _cache is not None and (time.time() - _cache_ts) < _ttl():
            return _cache

    import sector_rotation

    rotation = sector_rotation.compute_sector_rotation(force=False)
    sectors = rotation.get("sectors", [])
    macro = rotation.get("macroDetail", {})
    vkospi = _vkospi_context()

    global_sent = _stage0_global_sentiment(force=force)
    us_lead_ctx = _us_lead_context(force=force)
    regime = _stage1_market_regime(macro, vkospi, sectors, global_sent, us_lead_ctx)
    macro_map = _stage2_macro_map(
        macro, global_sent.get("scores") if global_sent.get("available") else None
    )
    ladder = _stage3_rotation_ladder(sectors)

    # [6단계] 뉴스 수집 (30분 TTL) + 컨텍스트
    news_ctx: dict = {}
    try:
        import news_collector
        news_collector.collect(pages=1)
        news_ctx = news_collector.get_news_context()
    except Exception:
        news_ctx = {"error": "뉴스 수집 실패 — 이번 리포트에서 6단계 제외"}
    ranking = [
        {
            "rank": i + 1,
            "sector": s["sector"],
            "score": s["score"],
            "lifecycle": s.get("lifecycle"),
            "intradayPct": s.get("detail", {}).get("intradayPct"),
            "breakdown": s.get("breakdown"),
        }
        for i, s in enumerate(sectors)
    ]

    context = {
        "asOf": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "vkospi": vkospi,
        "globalSentiment": global_sent,
        "usLead": us_lead_ctx,
        "regime": regime,
        "macroMap": macro_map,
        "rotationLadder": ladder,
        "sectorRanking": ranking,
        "newsContext": news_ctx,
        "dataNotes": [
            "산업 세부(5단계)·개별 종목 차트/목표가(8~11단계)는 Phase 3 데이터 수집 후 활성화",
            "VKOSPI는 KRX 변동성지수 선물(VKI1!) 기반",
            "뉴스는 나침반 대표종목 39개 기준 (네이버 증권 뉴스)",
        ],
    }

    # [시한부] 정책·선거 국면 블록 — 윈도우 내에서만 주입. 밖(2026-11-04+)에선 키 자체가 없음(회귀).
    import global_macro_feeds as gmf
    policy_active = gmf.election_window_active()
    if policy_active:
        context["policyRegime"] = _policy_regime(news_ctx)

    ai_report, provider = (None, "skipped")
    if with_ai:
        ai_report, provider = _call_llm(json.dumps(context, ensure_ascii=False),
                                        policy_active=policy_active)

    result = {
        **context,
        "aiReport": ai_report,
        "aiProvider": provider,
        "cached": False,
    }
    with _lock:
        _cache = {**result, "cached": True}
        _cache_ts = time.time()
    return result
