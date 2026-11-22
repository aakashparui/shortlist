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
from app.core.identifiers import prime_counters, reset_counters
from app.core.logging import get_logger
from app.db.models import (
    AccountingEntry,
    Base,
    Investigation,
    Payment,
    ReconciliationRecord,
    ScenarioExecution,
    StatementEntry,
)
from app.db.session import engine as default_engine
from app.db.session import session_scope

logger = get_logger(__name__)

# Where each counter-backed sequence is persisted. Every prefix in
# SEQUENCE_STARTS must appear here or that sequence restarts from its start
# value on the next boot and collides with references already in the database.
SEQUENCE_SOURCES: tuple[tuple[str, object], ...] = (
    ("TXN", Payment.reference),
    ("ACC", AccountingEntry.accounting_reference),
    ("GL", AccountingEntry.entry_id),
    ("STMT", StatementEntry.statement_reference),
    ("RECON", ReconciliationRecord.reference),
    ("INV", Investigation.reference),
    ("RUN", ScenarioExecution.reference),
)


def prime_sequences(session) -> dict[str, int]:  # noqa: ANN001
    """Advance the in-memory identifier sequences past what is already stored.

    The suffixes are parsed in Python rather than taken from SQL `max()`: these
    references are strings, and a lexicographic maximum picks 'TXN-9999' over
    'TXN-10001'. Correctness matters more than the scan, which runs once per
    process over a few hundred rows.
    """
    highest: dict[str, int] = {}
    for prefix, column in SEQUENCE_SOURCES:
        token = f"{prefix}-"
        best = 0
        for value in session.execute(select(column).where(column.like(f"{token}%"))).scalars():
            suffix = value[len(token) :]
            if suffix.isdigit():
                best = max(best, int(suffix))
        if best:
            highest[prefix] = best
    prime_counters(highest)
    if highest:
        logger.info("identifier sequences primed", extra={"sequences": highest})
    return highest


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
    # Before anything can allocate an identifier, and regardless of whether
    # seeding runs: a restart against an existing database must not hand out
    # references that are already taken.
    with session_scope() as session:
        primed = prime_sequences(session)
    should_seed = settings.AUTO_SEED if seed is None else seed
    if not should_seed:
        return {"seeded": False, "sequences": primed}
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
    # The stored references are gone, so the sequences must not stay advanced
    # past them.
    reset_counters()
    logger.warning("database reset")
