"""research_consensus.py — 증권사 리포트 목표가·투자의견 컨센서스 (us_lead 패턴의 얇은 허브).

kr_research_reports(scripts/research_reports_sync.py 적재)를 종목별로 집계해
**목표가 컨센서스(평균/중앙값)·투자의견 분포·최근 상향/하향**을 결정론적으로 산출한다.
모든 수치는 저장된 리포트에서만 나오고(날조 없음), 무데이터는 N/A(None)로 명시한다
([[data-accuracy-over-availability]]).

이 모듈은 **공통 인터페이스만 노출**한다 — AI 예측 엔진 통합(목표가 상향/하향을 익일 신호
피처로)은 'AI 예측 엔진' 전담 세션 몫이다(파일 하단 TODO).

핵심 진입점:
  get_consensus(code) -> {avg_tp, median_tp, opinion_dist, tp_revision_7d, asof, n_reports, ...}
"""

from __future__ import annotations

import statistics
from datetime import date, timedelta
from typing import Optional

# 투자의견 원문 → 정규 라벨. 영문/국문 혼용을 흡수한다. 매칭 안 되면 '기타'.
_OPINION_MAP: list[tuple[tuple[str, ...], str]] = [
    (("strongbuy", "strong buy"), "적극매수"),
    (("buy", "매수", "overweight", "outperform", "trading buy", "add", "accumulate"), "매수"),
    (("hold", "중립", "neutral", "marketperform", "market perform", "marketperform"), "중립"),
    (("sell", "매도", "underweight", "underperform", "reduce"), "매도"),
]

# 컨센서스 기본 룩백(거래일 아닌 달력일). 너무 오래된 목표가는 컨센서스에서 제외.
DEFAULT_LOOKBACK_DAYS = 90
REVISION_EPS = 0.005  # 상향/하향 판정 임계(±0.5% 이내는 flat)


def normalize_opinion(raw: Optional[str]) -> Optional[str]:
    """투자의견 원문 → 정규 라벨(적극매수/매수/중립/매도/기타). None 은 None 유지."""
    if not raw:
        return None
    s = raw.strip().lower().replace(".", "")
    for keys, label in _OPINION_MAP:
        if any(k in s for k in keys):
            return label
    return "기타"


def _load_reports(code: str, lookback_days: int) -> list[dict]:
    """종목 리포트(룩백 내) → [{firm, date, tp, opinion_raw}] 날짜 오름차순. DB 미가용 시 []."""
    try:
        import db
        import models
        from sqlalchemy import select
    except Exception:
        return []
    since = date.today() - timedelta(days=lookback_days)
    try:
        s = db.get_session_factory()()
        try:
            rows = s.execute(
                select(models.KrResearchReport.firm,
                       models.KrResearchReport.report_date,
                       models.KrResearchReport.target_price,
                       models.KrResearchReport.recommendation)
                .where(models.KrResearchReport.stock_code == code,
                       models.KrResearchReport.report_date >= since)
                .order_by(models.KrResearchReport.report_date.asc())
            ).all()
        finally:
            s.close()
    except Exception:
        return []
    return [{"firm": f, "date": d, "tp": tp, "opinion_raw": rc} for f, d, tp, rc in rows]


def _tp_revision_7d(reports: list[dict]) -> Optional[str]:
    """최근 7일 목표가 중앙값 vs 직전(7~30일) 중앙값 → 'up'|'down'|'flat'|None.

    양쪽 구간 모두 목표가 표본이 있어야 판정(없으면 None — 날조 금지).
    """
    if not reports:
        return None
    asof = reports[-1]["date"]
    recent = [r["tp"] for r in reports if r["tp"] and (asof - r["date"]).days <= 7]
    prior = [r["tp"] for r in reports
             if r["tp"] and 7 < (asof - r["date"]).days <= 30]
    if not recent or not prior:
        return None
    rm, pm = statistics.median(recent), statistics.median(prior)
    if pm <= 0:
        return None
    chg = (rm - pm) / pm
    if chg > REVISION_EPS:
        return "up"
    if chg < -REVISION_EPS:
        return "down"
    return "flat"


def get_consensus(code: str, lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> dict:
    """종목 리포트 컨센서스. 무데이터면 모든 수치 None + note(N/A).

    반환:
      {
        "code": str,
        "avg_tp": float|None,            # 목표가 평균 (KRW)
        "median_tp": int|None,           # 목표가 중앙값 (KRW)
        "opinion_dist": {label: count},  # 정규 투자의견 분포 (기간 내 전 리포트)
        "tp_revision_7d": "up"|"down"|"flat"|None,  # 최근 7d vs 7~30d 목표가 중앙값 변화
        "n_reports": int,                # 기간 내 리포트 수
        "n_targets": int,                # 목표가가 있는 리포트 수
        "latest_by_firm": {firm: {tp, opinion, date}},  # 증권사별 최신
        "asof": ISO|None,                # 가장 최근 리포트 작성일
        "lookback_days": int,
        "note": str|None,                # 무데이터 안내
      }
    """
    reports = _load_reports(code, lookback_days)
    if not reports:
        return {
            "code": code, "avg_tp": None, "median_tp": None, "opinion_dist": {},
            "tp_revision_7d": None, "n_reports": 0, "n_targets": 0,
            "latest_by_firm": {}, "asof": None, "lookback_days": lookback_days,
            "note": f"kr_research_reports 무데이터(최근 {lookback_days}일) — research_reports_sync 미실행/리포트 없음",
        }

    tps = [r["tp"] for r in reports if r["tp"]]
    opinion_dist: dict[str, int] = {}
    for r in reports:
        lab = normalize_opinion(r["opinion_raw"])
        if lab:
            opinion_dist[lab] = opinion_dist.get(lab, 0) + 1

    # 증권사별 최신(같은 firm 은 가장 최근 리포트만 — 컨센서스 중복 가중 방지 참고용)
    latest_by_firm: dict[str, dict] = {}
    for r in reports:  # 오름차순이라 뒤가 최신
        latest_by_firm[r["firm"]] = {
            "tp": r["tp"],
            "opinion": normalize_opinion(r["opinion_raw"]),
            "date": r["date"].isoformat(),
        }

    asof = reports[-1]["date"].isoformat()
    return {
        "code": code,
        "avg_tp": round(sum(tps) / len(tps), 1) if tps else None,
        "median_tp": int(statistics.median(tps)) if tps else None,
        "opinion_dist": opinion_dist,
        "tp_revision_7d": _tp_revision_7d(reports),
        "n_reports": len(reports),
        "n_targets": len(tps),
        "latest_by_firm": latest_by_firm,
        "asof": asof,
        "lookback_days": lookback_days,
        "note": None if tps else "기간 내 목표가 표본 없음(투자의견만 존재) — avg/median N/A",
    }


# ---------------------------------------------------------------------------
# 후속 통합 작업 (배선은 후속 세션 몫 — 여기선 인터페이스만 노출).
# ---------------------------------------------------------------------------
# TODO(ai_prediction_engine): get_consensus(code).tp_revision_7d / opinion_dist 를
#       익일 신호 피처로 SignalOutcome.features 에 합류(목표가 상향=상방 보조신호).
#       us_lead 의 get_lead_scores() 가 sector_rotation/market_compass 에 배선된 패턴과 동일하게,
#       target_engine/stock_compass 출력 스키마는 건드리지 않고 신규 필드로만 노출할 것.
#       ([[ai-prediction-engine-session]] [[ai-signal-feedback-loop]])


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    code = sys.argv[1] if len(sys.argv) > 1 else "005930"
    print(json.dumps(get_consensus(code), ensure_ascii=False, indent=2))
