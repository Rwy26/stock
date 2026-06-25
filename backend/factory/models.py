"""예측 팩토리 — 지식공유 스키마 (apollo_db, factory_* 테이블).

기존 backend/models.py 의 Base 를 재사용해 같은 metadata 에 등록한다.
ensure_tables() 는 create_all(추가형: 없는 테이블만 생성)이라 라이브 스키마를 건드리지 않는다.

세 축:
  FactoryAgent      — 누가 경쟁하는가 + 진화 상태(weight/status). 진화 루프가 소유.
  FactoryPrediction — 각 에이전트가 무엇을 예측했나(+재현용 features 스냅샷). 경쟁의 입력.
  FactoryOutcome    — horizon 도래 후 실현 결과. 진화의 연료(per-agent 채점).
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, func,
)
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from models import Base  # 기존 DeclarativeBase 재사용 (동일 metadata)


class FactoryAgent(Base):
    """경쟁 참가자 명부 + 진화 상태. name 이 모든 예측의 출처 키."""

    __tablename__ = "factory_agents"

    name: Mapped[str] = mapped_column(String(80), primary_key=True)
    version: Mapped[str] = mapped_column(String(40), default="0.1.0")
    kind: Mapped[str] = mapped_column(String(20), default="existing")  # AgentKind
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|probation|retired

    weight: Mapped[float] = mapped_column(Float, default=1.0)  # 진화 루프가 갱신(앙상블 가중)
    parent_name: Mapped[str | None] = mapped_column(String(80), nullable=True)  # 자손 추적
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 변형 파라미터 스냅샷

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class FactoryPrediction(Base):
    """단위 예측 — contracts.Prediction 1:1 대응. (출처, 종목, 시점, horizon) 유일."""

    __tablename__ = "factory_predictions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_name: Mapped[str] = mapped_column(String(80), ForeignKey("factory_agents.name"), index=True)
    agent_version: Mapped[str] = mapped_column(String(40), default="0.1.0")

    stock_code: Mapped[str] = mapped_column(String(20), index=True)
    as_of: Mapped[date] = mapped_column(Date, index=True)
    horizon_days: Mapped[int] = mapped_column(Integer, default=5)

    direction: Mapped[str] = mapped_column(String(8))  # UP|DOWN|FLAT
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    expected_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    features: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 재현·진화용 입력 스냅샷

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("uq_factory_pred", "agent_name", "stock_code", "as_of", "horizon_days", unique=True),
    )


class FactoryOutcome(Base):
    """예측 채점 결과 — horizon 도래 후 실현 수익률/알파/적중. 진화 루프의 연료."""

    __tablename__ = "factory_outcomes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    prediction_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("factory_predictions.id"), unique=True, index=True)
    agent_name: Mapped[str] = mapped_column(String(80), index=True)  # 비정규화: per-agent 집계 가속

    resolved_at: Mapped[date] = mapped_column(Date)  # as_of + horizon 의 실현 시점
    actual_return: Mapped[float | None] = mapped_column(Float, nullable=True)  # 실현 수익률(%)
    actual_alpha: Mapped[float | None] = mapped_column(Float, nullable=True)   # 시장/지수 대비 초과
    hit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)           # 방향 적중
    brier: Mapped[float | None] = mapped_column(Float, nullable=True)          # 확률 보정 점수

    scored_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


def ensure_tables() -> list[str]:
    """factory_* 테이블을 생성(없는 것만). 라이브 스키마 무수정.

    반환: 이번 호출로 새로 만들어진(또는 이미 존재 확인된) factory 테이블 이름들.
    """

    from db import get_engine

    tables = [FactoryAgent.__table__, FactoryPrediction.__table__, FactoryOutcome.__table__]
    Base.metadata.create_all(get_engine(), tables=tables, checkfirst=True)
    return [t.name for t in tables]
