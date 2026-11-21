"""Engine and session management."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _ensure_sqlite_dir(url: str) -> None:
    marker = "sqlite+pysqlite:///"
    if url.startswith(marker):
        path = Path(url[len(marker) :])
        if path.name and str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)


def build_engine(url: str | None = None) -> Engine:
    database_url = url or settings.DATABASE_URL
    _ensure_sqlite_dir(database_url)
    kwargs: dict[str, object] = {"echo": settings.DB_ECHO, "future": True, "pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    else:
        kwargs["pool_size"] = 10
        kwargs["max_overflow"] = 20
    created = create_engine(database_url, **kwargs)
    if created.dialect.name == "sqlite":

        @event.listens_for(created, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):  # noqa: ANN001, ANN202
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    return created


engine: Engine = build_engine()
SessionFactory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def configure_engine(url: str) -> Engine:
    """Rebind the global session factory (used by the test suite)."""
    global engine
    engine = build_engine(url)
    SessionFactory.configure(bind=engine)
    return engine


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for background work and scripts."""
    session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, committed on success."""
    session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
