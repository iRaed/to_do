"""Database engine / session factory."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import get_settings
from .models import Base


_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None


def _resolve_db_path(db_path: str) -> str:
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        settings = get_settings()
        path = _resolve_db_path(settings.DB_PATH)
        _engine = create_engine(
            f"sqlite:///{path}",
            future=True,
            echo=False,
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(_engine)
    return _engine


def get_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _SessionLocal


def session_scope() -> Session:
    return get_session_factory()()


def init_db() -> None:
    Base.metadata.create_all(get_engine())
