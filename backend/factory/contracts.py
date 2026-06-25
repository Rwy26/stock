"""예측 팩토리 — 에이전트 공통 계약.

모든 에이전트(기존 엔진 래퍼든 신규 ML 모델이든)는 동일한 `Prediction`을 emit한다.
이 단일 계약이 두 가지를 보장한다:
  1) 경쟁  — 모든 에이전트를 같은 잣대로 비교/채점할 수 있다.
  2) 탈착  — 신규 모듈은 이 계약만 지키면 코어 수정 없이 합류한다.

수치 계산은 결정론. LLM은 상위 계층(Orchestrator/Explorer)에서만 사용한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class Direction(str, Enum):
    UP = "UP"
    DOWN = "DOWN"
    FLAT = "FLAT"


class AgentKind(str, Enum):
    """에이전트 출신 분류 — 진화 루프의 자손 추적에 사용."""

    EXISTING = "existing"   # 기존 MOON STOCK 엔진 래퍼
    VARIANT = "variant"     # 기존 에이전트의 파라미터 변형(자손)
    MODEL = "model"         # 신규 ML 모델 (LSTM/Transformer/XGBoost/Diffusion ...)
    ENSEMBLE = "ensemble"   # 다른 에이전트들을 합성


@dataclass(slots=True)
class PredictionContext:
    """한 사이클에서 에이전트에게 주어지는 입력.

    as_of 시점까지의 정보만 담아 point-in-time(누설 방지)을 강제한다.
    universe 비우면 에이전트가 자체 유니버스를 고른다.
    """

    as_of: date
    horizon_days: int = 5
    universe: list[str] = field(default_factory=list)  # 종목코드. 비면 에이전트 재량
    params: dict[str, Any] = field(default_factory=dict)  # 변형/실험용 파라미터


@dataclass(slots=True)
class Prediction:
    """모든 에이전트가 emit하는 단위 예측. factory_predictions 한 행에 대응."""

    agent_name: str
    agent_version: str
    stock_code: str
    as_of: date
    horizon_days: int
    direction: Direction
    confidence: float                       # 0.0 ~ 1.0
    expected_return: float | None = None    # 기대 수익률(%) — 없으면 방향만
    rationale: str | None = None            # 사람이 읽는 근거 요약
    features: dict[str, Any] = field(default_factory=dict)  # 재현·진화용 입력 스냅샷

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0,1], got {self.confidence}")
        if isinstance(self.direction, str):
            self.direction = Direction(self.direction)


@runtime_checkable
class Agent(Protocol):
    """팩토리 에이전트 인터페이스. 기존 엔진을 이 모양으로 감싸 합류시킨다.

    name+version 은 (factory_agents PK + 예측 출처)로 쓰이므로 안정적이어야 한다.
    predict 는 부작용 없이(라이브 테이블 무수정) Prediction 리스트만 돌려준다.
    """

    name: str
    version: str
    kind: AgentKind

    def predict(self, ctx: PredictionContext) -> list[Prediction]:
        ...


def stamp(agent: Agent, ctx: PredictionContext, *, stock_code: str,
          direction: Direction | str, confidence: float,
          expected_return: float | None = None, rationale: str | None = None,
          features: dict[str, Any] | None = None) -> Prediction:
    """에이전트 안에서 Prediction을 만들 때 출처/시점을 자동 각인하는 헬퍼."""

    return Prediction(
        agent_name=agent.name,
        agent_version=agent.version,
        stock_code=stock_code,
        as_of=ctx.as_of,
        horizon_days=ctx.horizon_days,
        direction=Direction(direction) if isinstance(direction, str) else direction,
        confidence=confidence,
        expected_return=expected_return,
        rationale=rationale,
        features=features or {},
    )
