"""Validation rule contract and execution context."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.domain.enums import Severity, StageKey, ValidationCategory, ValidationStatus
from app.schemes.base import PaymentScheme

if TYPE_CHECKING:  # pragma: no cover
    from app.db.models import Payment


@dataclass(slots=True)
class RuleOutcome:
    """What a rule decided. `passed=None` means the rule did not apply."""

    passed: bool | None
    message: str = ""
    actual_value: str | None = None
    expected_value: str | None = None
    field: str | None = None
    remediation: str = ""
    iso_reason_code: str | None = None
    severity_override: Severity | None = None

    @property
    def status(self) -> ValidationStatus:
        if self.passed is None:
            return ValidationStatus.NOT_APPLICABLE
        return ValidationStatus.PASSED if self.passed else ValidationStatus.FAILED


@dataclass(slots=True)
class ValidationContext:
    payment: Payment
    scheme: PaymentScheme
    session: Session
    now: datetime
    stage: StageKey
    extras: dict = dc_field(default_factory=dict)


Evaluator = Callable[[ValidationContext], RuleOutcome]


@dataclass(frozen=True, slots=True)
class RuleDefinition:
    rule_id: str
    name: str
    description: str
    category: ValidationCategory
    severity: Severity
    stage: StageKey
    evaluator: Evaluator
    schemes: tuple[str, ...] = ()  # empty == all schemes that reference the rule id
    applies_to: tuple[str, ...] = ("pacs.008",)
    field: str | None = None
    failure_behaviour: str = "Reject payment"
    iso_reason_code: str | None = None
    rationale: str = ""
    standard_basis: str = ""
    parameters: dict = dc_field(default_factory=dict)

    def to_row(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "description": self.description,
            "category": self.category.value,
            "severity": self.severity.value,
            "stage": self.stage.value,
            "schemes": list(self.schemes),
            "applies_to": list(self.applies_to),
            "field": self.field,
            "failure_behaviour": self.failure_behaviour,
            "iso_reason_code": self.iso_reason_code,
            "rationale": self.rationale,
            "standard_basis": self.standard_basis,
            "parameters": dict(self.parameters),
        }
