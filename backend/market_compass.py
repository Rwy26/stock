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
import threading
import time
from datetime import datetime
from typing import Optional

import httpx

from settings import settings

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


def _stage1_market_regime(macro: dict, vkospi: dict, sectors: list[dict]) -> dict:
    """[1단계] 시장 구조: 유동성/실적/정책/테마/위기 장세 판정 (규칙 기반 + 근거)."""
    evidence: list[str] = []
    scores = {"유동성 장세": 0.0, "실적 장세": 0.0, "정책 장세": 0.0, "테마 장세": 0.0, "위기 장세": 0.0}

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


def _stage2_macro_map(macro: dict) -> list[dict]:
    """[2단계] 거시 요소별 → 유리한 섹터 매핑 (현재값 기준)."""
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


def _call_llm(context_json: str) -> tuple[Optional[str], str]:
    """Gemini > Groq > OpenAI 우선순위로 종합 리포트 생성. (리포트, 프로바이더) 반환."""
    user_msg = (
        "다음은 실시간 계산된 시장 데이터다. 이 데이터만 근거로 분석 절차를 수행하라.\n\n"
        f"```json\n{context_json}\n```"
    )

    # Gemini
    if settings.gemini_api_key:
        try:
            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{settings.gemini_model}:generateContent?key={settings.gemini_api_key}"
            )
            body = {
                "systemInstruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
                "contents": [{"role": "user", "parts": [{"text": user_msg}]}],
                "generationConfig": {"temperature": 0.3, "maxOutputTokens": 4096},
            }
            r = httpx.post(url, json=body, timeout=90.0)
            r.raise_for_status()
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            return text, f"gemini:{settings.gemini_model}"
        except Exception:
            pass

    # Groq / OpenAI (OpenAI 호환)
    for key, model, base in (
        (settings.groq_api_key, settings.groq_model, "https://api.groq.com/openai/v1"),
        (settings.openai_api_key, settings.openai_model, "https://api.openai.com/v1"),
    ):
        if not key:
            continue
        try:
            r = httpx.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    "temperature": 0.3,
                },
                timeout=90.0,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"], f"{base.split('.')[1]}:{model}"
        except Exception:
            continue
    return None, "none"


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

    regime = _stage1_market_regime(macro, vkospi, sectors)
    macro_map = _stage2_macro_map(macro)
    ladder = _stage3_rotation_ladder(sectors)
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
        "regime": regime,
        "macroMap": macro_map,
        "rotationLadder": ladder,
        "sectorRanking": ranking,
        "dataNotes": [
            "뉴스 상세(6단계)·산업 세부(5단계)·개별 종목 차트/목표가(8~11단계)는 Phase 2 데이터 수집 후 활성화",
            "VKOSPI는 KRX 변동성지수 선물(VKI1!) 기반",
        ],
    }

    ai_report, provider = (None, "skipped")
    if with_ai:
        ai_report, provider = _call_llm(json.dumps(context, ensure_ascii=False))

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
