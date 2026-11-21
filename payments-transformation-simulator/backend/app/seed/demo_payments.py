"""Demo payment book.

Runs the scenario library (plus a few extra instructions) in IMMEDIATE mode to
produce a realistic, deterministic demo portfolio: completed payments, rejects,
timeouts, reconciliation breaks, investigations and returns, across CHF, EUR,
GBP, USD and INR.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.schemas import PaymentCreate
from app.core.logging import get_logger
from app.db.models import Payment
from app.domain.enums import ProcessingMode
from app.seed.scenarios import (
    CH_CREDITOR,
    GB_CREDITOR,
    IN_CREDITOR,
    NL_CREDITOR,
    generic,
    sepa,
    sic,
    swift,
)
from app.services.payment_service import PaymentService
from app.services.scenario_service import ScenarioService

logger = get_logger(__name__)

# Scenario runs beyond one pass of the library, chosen so the demo book matches
# the distribution an operations team would expect to see on a quiet day.
EXTRA_SCENARIO_RUNS: tuple[str, ...] = (
    "SC-01",  # completed
    "SC-01",  # completed
    "SC-07",  # completed (delayed but fine)
    "SC-12",  # completed with an unmatched statement entry
    "SC-20",  # completed cross-border
    "SC-02",  # rejected
    "SC-06",  # timeout
    "SC-17",  # returned
)

EXTRA_PAYMENTS: tuple[dict, ...] = (
    sic("12750.00", CH_CREDITOR, remittanceInformation="Machine parts invoice 7781"),
    sepa("9340.00", NL_CREDITOR, remittanceInformation="Quarterly licence fee"),
    generic("5600.00", "GBP", GB_CREDITOR, remittanceInformation="Freight settlement week 13"),
    swift("1450000.00", "INR", IN_CREDITOR, remittanceInformation="Component order INR-2291"),
)


def seed_demo_payments(session: Session, *, minimum: int = 25) -> dict[str, int]:
    existing = session.execute(
        select(func.count(Payment.id)).where(Payment.is_demo_data.is_(True))
    ).scalar_one()
    if existing >= minimum:
        logger.info("demo payments already present", extra={"count": existing})
        return {"created": 0, "existing": existing}

    scenarios = ScenarioService(session)
    payments = PaymentService(session)
    created = 0

    for scenario in scenarios.list_scenarios():
        scenarios.run(scenario, mode=ProcessingMode.IMMEDIATE, is_demo_data=True)
        created += 1

    for code in EXTRA_SCENARIO_RUNS:
        scenario = scenarios.get(code)
        if scenario is None:  # pragma: no cover
            continue
        scenarios.run(scenario, mode=ProcessingMode.IMMEDIATE, is_demo_data=True)
        created += 1

    for spec in EXTRA_PAYMENTS:
        payload = PaymentCreate.model_validate(
            {**spec, "processingMode": "IMMEDIATE", "createdBy": "demo.seed", "source": "SEED"}
        )
        payment = payments.create(payload, is_demo_data=True)
        payments.execute(payment, mode=ProcessingMode.IMMEDIATE)
        created += 1

    total = session.execute(
        select(func.count(Payment.id)).where(Payment.is_demo_data.is_(True))
    ).scalar_one()
    logger.info("demo payments seeded", extra={"created": created, "total": total})
    return {"created": created, "existing": total}
