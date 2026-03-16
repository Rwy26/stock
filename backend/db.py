from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

import settings


_ENGINE: Engine | None = None
_SESSION_FACTORY: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _ENGINE
    if _ENGINE is None:
        url = settings.settings.database_url()
        _ENGINE = create_engine(
            url,
            pool_pre_ping=True,
            pool_recycle=3600,
            future=True,
        )
    return _ENGINE


def get_session_factory() -> sessionmaker[Session]:
    global _SESSION_FACTORY
    if _SESSION_FACTORY is None:
        _SESSION_FACTORY = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, future=True)
    return _SESSION_FACTORY


def get_db() -> Generator[Session, None, None]:
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    db = get_session_factory()()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def healthcheck() -> dict:
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"ok": True, "dialect": engine.dialect.name}
