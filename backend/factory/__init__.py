"""자율 진화형 예측 팩토리 (Prediction Factory).

경쟁하며 협력하는 다중 에이전트 예측 시스템. 라이브 매매/추천 경로는 불가침 —
팩토리는 factory_* 테이블에만 쓰는 섀도(병렬)로 시작한다. 설계: FACTORY.md 참조.

Phase 0 (기반): contracts(계약) · registry(핫플러그/진화상태) · models(지식 스키마).
"""
from __future__ import annotations

from factory.contracts import (
    Agent,
    AgentKind,
    Direction,
    Prediction,
    PredictionContext,
    stamp,
)
from factory.registry import REGISTRY, AgentStatus, active_agents, register, sync_to_db

__all__ = [
    "Agent",
    "AgentKind",
    "Direction",
    "Prediction",
    "PredictionContext",
    "stamp",
    "REGISTRY",
    "AgentStatus",
    "active_agents",
    "register",
    "sync_to_db",
]
