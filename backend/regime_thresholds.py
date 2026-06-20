"""regime_thresholds.py — 장세 조건부 시그널 임계값 (단일 소스).

문제(2026-06-20 진단): 고정 컷(80/70/55/40)은 장세를 못 가린다. 하락장 표본에선
score 55-70(HOLD)와 40-55(SELL)가 통계적으로 동일했다. 같은 점수라도 **장세에 따라**
다른 시그널이어야 한다 — 상승장의 60점과 하락장의 60점은 의미가 다르다.

이 모듈은 market_compass 1단계 regime(유동성/실적/정책/테마/위기 장세)별 컷을
**단일 소스**로 보관한다. threshold_simulator --by-regime 이 장세 다양성 확보 후
holdout 기준으로 산출한 컷을 여기에 plug-in 한다.

⚠️ 현재 모든 장세 = DEFAULT_CUTS (현행과 동일). 즉 **지금은 동작 불변**이다.
   regime 별 컷은 상승장 표본이 충분히 쌓여 검증되기 전에는 갱신하지 않는다
   (data-accuracy: 단일 장세 과적합 컷을 라이브에 넣지 않는다).

컷 정의: (STRONG_BUY하한, BUY하한, HOLD하한, SELL하한) 내림차순.
  score≥c0→STRONG_BUY / ≥c1→BUY / ≥c2→HOLD / ≥c3→SELL / 미만→STRONG_SELL
"""

from __future__ import annotations

from typing import Optional

REGIMES = ["유동성 장세", "실적 장세", "정책 장세", "테마 장세", "위기 장세"]

DEFAULT_CUTS: tuple[float, float, float, float] = (80.0, 70.0, 55.0, 40.0)

# 장세별 컷 — 현재 전부 DEFAULT(튜닝 전 동작 불변). 검증된 컷만 여기서 덮어쓴다.
# 예(미래, 검증 후): "위기 장세": (82, 72, 62, 50)  # 하락장엔 매수 문턱↑·HOLD 폭↓
REGIME_CUTS: dict[str, tuple[float, float, float, float]] = {
    r: DEFAULT_CUTS for r in REGIMES
}


def get_cuts(regime: Optional[str] = None) -> tuple[float, float, float, float]:
    """장세 라벨에 해당하는 컷. 미상·미설정이면 DEFAULT."""
    if not regime:
        return DEFAULT_CUTS
    return REGIME_CUTS.get(regime, DEFAULT_CUTS)


def signal_from_score(score: float, regime: Optional[str] = None) -> str:
    """점수→시그널 (장세 조건부). regime=None 이면 현행과 동일."""
    c0, c1, c2, c3 = get_cuts(regime)
    if score >= c0:
        return "STRONG_BUY"
    if score >= c1:
        return "BUY"
    if score >= c2:
        return "HOLD"
    if score >= c3:
        return "SELL"
    return "STRONG_SELL"
