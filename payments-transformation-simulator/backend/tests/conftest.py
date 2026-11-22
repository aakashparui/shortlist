"""Test fixtures.

Each test module gets a fresh file-backed SQLite database in a temp directory,
seeded with reference data, the rule book and the scenario library but *not*
with demo payments, so counts in assertions are deterministic.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

os.environ.setdefault("AUTO_SEED", "false")
os.environ.setdefault("SCHEDULER_ENABLED", "false")
os.environ.setdefault("DEMO_MODE", "true")
os.environ.setdefault("LOG_LEVEL", "CRITICAL")
os.environ.setdefault("LOG_FORMAT", "text")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")


@pytest.fixture(scope="module")
def database(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    directory = tmp_path_factory.mktemp("simulator-db")
    path = directory / "test.db"
    url = f"sqlite+pysqlite:///{path}"
    os.environ["DATABASE_URL"] = url

    from app.db import session as session_module

    session_module.configure_engine(url)

    from app.db.models import Base

    Base.metadata.create_all(bind=session_module.engine)
    yield path


@pytest.fixture
def db_session(database: Path) -> Iterator[Session]:  # noqa: F821
    from sqlalchemy.orm import close_all_sessions

    from app.core.identifiers import reset_counters
    from app.db.models import Base
    from app.db.session import SessionFactory, engine

    close_all_sessions()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    reset_counters()

    session = SessionFactory()
    from app.seed import seed_static_data

    seed_static_data(session)
    session.commit()
    try:
        yield session
        session.commit()
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def payments(db_session):  # noqa: ANN001, ANN201
    from app.services.payment_service import PaymentService

    return PaymentService(db_session)


@pytest.fixture
def scenarios(db_session):  # noqa: ANN001, ANN201
    from app.services.scenario_service import ScenarioService

    return ScenarioService(db_session)


@pytest.fixture
def orchestrator(payments):  # noqa: ANN001, ANN201
    return payments.orchestrator


@pytest.fixture
def api_client(database: Path) -> Iterator[TestClient]:  # noqa: F821
    """A TestClient over a freshly seeded database, including demo payments."""
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import close_all_sessions

    from app.core.identifiers import reset_counters
    from app.db.models import Base
    from app.db.session import SessionFactory, engine
    from app.main import create_app
    from app.seed import seed_static_data

    close_all_sessions()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    reset_counters()
    session = SessionFactory()
    try:
        seed_static_data(session)
        session.commit()
    finally:
        session.close()

    # AUTO_SEED and SCHEDULER_ENABLED are false in the test environment, so the
    # application's own lifespan only ensures the schema: no demo seeding and no
    # background thread interfere with assertions.
    app = create_app()
    with TestClient(app) as client:
        yield client


def valid_ch_iban(bban: str) -> str:
    from app.domain.identifiers_bank import compute_iban

    return compute_iban("CH", bban)


def sic_payload(**overrides):  # noqa: ANN003, ANN201
    from app.seed.scenarios import sic

    payload = sic("1000.00")
    payload.update(overrides)
    return payload
