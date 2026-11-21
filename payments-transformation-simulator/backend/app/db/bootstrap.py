"""Schema creation and first-run seeding.

Alembic owns the schema in a deployed environment (`alembic upgrade head`). For
local development and for the test suite the metadata is created directly, which
keeps a fresh clone to a single command.
"""

from __future__ import annotations

from sqlalchemy import inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import close_all_sessions

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import Base, Payment
from app.db.session import engine as default_engine
from app.db.session import session_scope

logger = get_logger(__name__)


def create_schema(target: Engine | None = None) -> None:
    Base.metadata.create_all(bind=target or default_engine)
    logger.info("schema ensured", extra={"tables": len(Base.metadata.tables)})


def schema_exists(target: Engine | None = None) -> bool:
    inspector = inspect(target or default_engine)
    return "payment" in inspector.get_table_names()


def initialise(*, create: bool = True, seed: bool | None = None) -> dict:
    """Prepare the database for use. Safe to call repeatedly."""
    if create:
        create_schema()
    should_seed = settings.AUTO_SEED if seed is None else seed
    if not should_seed:
        return {"seeded": False}
    from app.seed import seed_everything

    with session_scope() as session:
        existing = session.execute(select(Payment.id).limit(1)).first()
        summary = seed_everything(session, with_demo_payments=settings.DEMO_MODE and not existing)
    return {"seeded": True, **summary}


def reset_database() -> None:
    """Drop and recreate everything. Used by the test suite and `scripts/reset_db`."""
    Base.metadata.drop_all(bind=default_engine)
    Base.metadata.create_all(bind=default_engine)
    close_all_sessions()
    logger.warning("database reset")
