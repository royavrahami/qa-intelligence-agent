"""
Database engine and session factory.
Uses SQLAlchemy 2.x with a context-manager session pattern.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from src.config.settings import settings
from src.storage.models import Base

logger = logging.getLogger(__name__)

# Create engine – echo=False keeps logs clean in production
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
    echo=False,
    pool_pre_ping=True,
)

# Enable WAL mode for SQLite to support concurrent reads during writes
if "sqlite" in settings.database_url:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    """Create all tables if they don't exist yet (idempotent)."""
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialised at: %s", settings.database_url)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """
    Provide a transactional database session.
    Commits on clean exit, rolls back on exception.

    Usage:
        with get_session() as session:
            session.add(obj)
    """
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
