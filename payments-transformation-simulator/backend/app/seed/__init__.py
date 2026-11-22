"""Database seeding entry point."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.seed.demo_payments import seed_demo_payments
from app.seed.reference_data import seed_reference_data
from app.seed.rules import sync_business_rules
from app.seed.scenarios import seed_scenarios

logger = get_logger(__name__)

__all__ = [
    "seed_demo_payments",
    "seed_everything",
    "seed_reference_data",
    "seed_static_data",
    "sync_business_rules",
    "seed_scenarios",
]


def seed_static_data(session: Session) -> dict[str, dict]:
    """Reference data, rule book and scenario library. Idempotent."""
    return {
        "reference": seed_reference_data(session),
        "rules": sync_business_rules(session),
        "scenarios": seed_scenarios(session),
    }


def seed_everything(session: Session, *, with_demo_payments: bool | None = None) -> dict[str, dict]:
    result = seed_static_data(session)
    include_demo = settings.DEMO_MODE if with_demo_payments is None else with_demo_payments
    if include_demo:
        result["demoPayments"] = seed_demo_payments(
            session, minimum=settings.SEED_PAYMENT_COUNT
        )
    return result
