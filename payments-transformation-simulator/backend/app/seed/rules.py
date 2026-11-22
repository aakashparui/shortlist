"""Synchronise the code rule book into the `business_rule` table.

The rule *logic* lives in code; the table carries the inspectable metadata plus
the enabled flag the Business Rule Explorer toggles. Re-running the sync updates
metadata without resetting an operator's enable/disable choices.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import BusinessRule
from app.engines.compliance import RULE_METADATA as COMPLIANCE_RULES
from app.engines.validation.rules import RULES
from app.schemes.definitions import ALL_SCHEMES

logger = get_logger(__name__)


def _schemes_for(rule_id: str, declared: list[str]) -> list[str]:
    if declared:
        return declared
    return [s.code.value for s in ALL_SCHEMES if rule_id in s.validation_rule_ids]


def sync_business_rules(session: Session) -> dict[str, int]:
    stats = {"created": 0, "updated": 0}
    existing = {r.rule_id: r for r in session.execute(select(BusinessRule)).scalars()}

    for rule in RULES:
        row_data = rule.to_row()
        row_data["schemes"] = _schemes_for(rule.rule_id, row_data["schemes"])
        current = existing.get(rule.rule_id)
        if current is None:
            session.add(BusinessRule(**row_data, enabled=True))
            stats["created"] += 1
        else:
            for key, value in row_data.items():
                setattr(current, key, value)
            stats["updated"] += 1

    for rule_id, meta in COMPLIANCE_RULES.items():
        current = existing.get(rule_id)
        data = {
            "rule_id": rule_id,
            "name": meta["name"],
            "description": meta["description"],
            "category": "COMPLIANCE",
            "severity": meta["severity"],
            "stage": "COMPLIANCE",
            "schemes": [s.code.value for s in ALL_SCHEMES],
            "applies_to": ["pacs.008"],
            "field": "party",
            "failure_behaviour": (
                "Block the payment and raise an alert"
                if meta["severity"] in ("ERROR", "FATAL")
                else "Flag for enhanced due diligence"
            ),
            "iso_reason_code": "RR04" if meta["severity"] in ("ERROR", "FATAL") else None,
            "rationale": (
                "Sanctions and embargo obligations apply before a payment may be released."
            ),
            "standard_basis": (
                "SIMULATED: screening runs against a small fictional list, not licensed "
                "watch-list data."
            ),
            "parameters": {},
        }
        if current is None:
            session.add(BusinessRule(**data, enabled=True))
            stats["created"] += 1
        else:
            for key, value in data.items():
                setattr(current, key, value)
            stats["updated"] += 1

    session.flush()
    logger.info("business rules synchronised", extra=stats)
    return stats
