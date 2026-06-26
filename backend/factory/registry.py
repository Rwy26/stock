"""에이전트 레지스트리 — 핫플러그 + 진화 상태.

모듈이 "붙었다 떨어졌다" 하는 지점. 신규 에이전트는 @register 한 줄로 합류하고,
진화 루프는 status/weight 를 갱신해 적자생존을 집행한다.

레지스트리는 in-process 카탈로그(코드가 무엇을 제공하는가)이고,
factory_agents 테이블은 영속 상태(가중치/지위가 시간에 따라 어떻게 변했나)다.
둘은 sync() 로 맞춘다.
"""
from __future__ import annotations

from typing import Iterator

from factory.contracts import Agent


class AgentStatus:
    ACTIVE = "active"        # 정상 경쟁 참여
    PROBATION = "probation"  # 성과 미달 — 관찰 중(가중치 강등)
    RETIRED = "retired"      # 은퇴 — 예측 미수집(자손에 자리 양보)


class _Registry:
    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    def register(self, agent: Agent, *, replace: bool = False) -> Agent:
        key = agent.name
        if key in self._agents and not replace:
            raise ValueError(f"agent '{key}' already registered (use replace=True)")
        self._agents[key] = agent
        return agent

    def unregister(self, name: str) -> None:
        self._agents.pop(name, None)

    def get(self, name: str) -> Agent:
        return self._agents[name]

    def all(self) -> list[Agent]:
        return list(self._agents.values())

    def names(self) -> list[str]:
        return list(self._agents)

    def __contains__(self, name: str) -> bool:
        return name in self._agents

    def __iter__(self) -> Iterator[Agent]:
        return iter(self._agents.values())

    def __len__(self) -> int:
        return len(self._agents)


REGISTRY = _Registry()


def register(agent: Agent | None = None, *, replace: bool = False):
    """데코레이터/함수 양용 등록.

    인스턴스 등록:   register(MyAgent())
    클래스 데코레이터: @register  →  무인자 생성 가능한 에이전트 클래스에
    """

    def _apply(obj):
        # 클래스면 인스턴스화해 등록(무인자 생성 가능해야 함), 인스턴스면 그대로.
        inst = obj() if isinstance(obj, type) else obj
        REGISTRY.register(inst, replace=replace)
        return obj

    return _apply if agent is None else _apply(agent)


def active_agents(session=None) -> list[Agent]:
    """경쟁에 참여시킬 에이전트만 — 등록됨 ∩ (DB에서 retired 아님).

    session 미지정 시 DB 조회 없이 등록된 전체를 반환(Phase 0 기본).
    """

    agents = REGISTRY.all()
    if session is None:
        return agents

    from factory.models import FactoryAgent  # 지연 import (순환 방지)

    retired = {
        r.name
        for r in session.query(FactoryAgent.name)
        .filter(FactoryAgent.status == AgentStatus.RETIRED)
        .all()
    }
    return [a for a in agents if a.name not in retired]


def sync_to_db(session) -> int:
    """등록된 에이전트들을 factory_agents 에 upsert(없으면 active로 생성).

    기존 행의 weight/status 는 보존한다(진화 루프가 소유). 신규만 삽입.
    반환: 새로 생성된 행 수.
    """

    from factory.models import FactoryAgent

    existing = {r.name for r in session.query(FactoryAgent.name).all()}
    created = 0
    for a in REGISTRY.all():
        if a.name in existing:
            continue
        session.add(
            FactoryAgent(
                name=a.name,
                version=a.version,
                kind=getattr(a, "kind", "existing"),
                status=AgentStatus.ACTIVE,
                weight=1.0,
                config={},
            )
        )
        created += 1
    return created
