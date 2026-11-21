"""Validation engine.

Executes the rule book against a payment for a given processing stage and
persists one `ValidationResult` per rule. Rules disabled in the Business Rule
Explorer are recorded as SKIPPED rather than silently dropped, so a QA engineer
can always see which checks ran.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import BusinessRule, Payment, ValidationResult
from app.domain.enums import Severity, StageKey, ValidationStatus
from app.engines.validation.context import RuleDefinition, RuleOutcome, ValidationContext
from app.engines.validation.rules import RULES_BY_ID, rules_for_scheme, utc_now
from app.schemes.base import PaymentScheme

logger = get_logger(__name__)


@dataclass(slots=True)
class ValidationRun:
    stage: StageKey
    results: list[ValidationResult] = field(default_factory=list)

    @property
    def failures(self) -> list[ValidationResult]:
        return [
            r
            for r in self.results
            if r.status == ValidationStatus.FAILED.value
            and r.severity in (Severity.ERROR.value, Severity.FATAL.value)
        ]

    @property
    def warnings(self) -> list[ValidationResult]:
        return [
            r
            for r in self.results
            if r.status == ValidationStatus.FAILED.value and r.severity == Severity.WARNING.value
        ] + [r for r in self.results if r.severity == Severity.WARNING.value and r.status == ValidationStatus.PASSED.value]

    @property
    def passed(self) -> bool:
        return not self.failures

    @property
    def first_failure(self) -> ValidationResult | None:
        return self.failures[0] if self.failures else None

    def counts(self) -> dict[str, int]:
        out = {"executed": len(self.results), "passed": 0, "failed": 0, "skipped": 0, "notApplicable": 0}
        for r in self.results:
            if r.status == ValidationStatus.PASSED.value:
                out["passed"] += 1
            elif r.status == ValidationStatus.FAILED.value:
                out["failed"] += 1
            elif r.status == ValidationStatus.SKIPPED.value:
                out["skipped"] += 1
            else:
                out["notApplicable"] += 1
        return out


class ValidationEngine:
    def __init__(self, session: Session) -> None:
        self.session = session
        self._disabled: set[str] | None = None

    # -- rule state -----------------------------------------------------
    def disabled_rule_ids(self) -> set[str]:
        if self._disabled is None:
            rows = self.session.execute(
                select(BusinessRule.rule_id).where(BusinessRule.enabled.is_(False))
            ).scalars()
            self._disabled = set(rows)
        return self._disabled

    def invalidate_rule_cache(self) -> None:
        self._disabled = None

    # -- execution ------------------------------------------------------
    def run(
        self,
        payment: Payment,
        scheme: PaymentScheme,
        stage: StageKey,
        extras: dict | None = None,
    ) -> ValidationRun:
        run = ValidationRun(stage=stage)
        run_id = self._next_run_id(payment)
        disabled = self.disabled_rule_ids()
        ctx = ValidationContext(
            payment=payment,
            scheme=scheme,
            session=self.session,
            now=utc_now(),
            stage=stage,
            extras=extras or {},
        )
        for rule in rules_for_scheme(payment.scheme, scheme.validation_rule_ids):
            if rule.stage != stage:
                continue
            result = self._execute_rule(rule, ctx, run_id, disabled)
            self.session.add(result)
            run.results.append(result)
        self.session.flush()
        logger.info(
            "validation stage executed",
            extra={
                "stage": stage.value,
                "payment_reference": payment.reference,
                "counts": run.counts(),
            },
        )
        return run

    def _execute_rule(
        self,
        rule: RuleDefinition,
        ctx: ValidationContext,
        run_id: int,
        disabled: set[str],
    ) -> ValidationResult:
        started = time.perf_counter()
        if rule.rule_id in disabled:
            outcome = RuleOutcome(
                passed=None,
                message="Rule is disabled in the rule engine configuration; check not performed.",
                field=rule.field,
            )
            status = ValidationStatus.SKIPPED
            severity = rule.severity
        else:
            try:
                outcome = rule.evaluator(ctx)
            except Exception as exc:  # defensive: a broken rule must not kill the payment
                logger.exception("rule evaluation failed", extra={"rule_id": rule.rule_id})
                outcome = RuleOutcome(
                    passed=False,
                    message=f"Rule evaluation raised {type(exc).__name__}: {exc}",
                    field=rule.field,
                    remediation="This is a simulator defect; inspect the rule implementation.",
                )
            status = outcome.status
            severity = outcome.severity_override or rule.severity
        duration_ms = int((time.perf_counter() - started) * 1000)
        return ValidationResult(
            payment_id=ctx.payment.id,
            run_id=run_id,
            rule_id=rule.rule_id,
            rule_name=rule.name,
            category=rule.category.value,
            severity=severity.value,
            status=status.value,
            stage=rule.stage.value,
            message=outcome.message,
            field=outcome.field or rule.field,
            actual_value=_truncate(outcome.actual_value),
            expected_value=_truncate(outcome.expected_value),
            iso_reason_code=outcome.iso_reason_code or rule.iso_reason_code,
            remediation=outcome.remediation,
            executed_at=ctx.now,
            duration_ms=duration_ms,
        )

    def _next_run_id(self, payment: Payment) -> int:
        current = self.session.execute(
            select(ValidationResult.run_id)
            .where(ValidationResult.payment_id == payment.id)
            .order_by(ValidationResult.run_id.desc())
            .limit(1)
        ).scalar()
        return (current or 0) + 1

    # -- single-rule evaluation (used by the test-case runner) ----------
    def evaluate_single(
        self, rule_id: str, payment: Payment, scheme: PaymentScheme, extras: dict | None = None
    ) -> RuleOutcome:
        rule = RULES_BY_ID.get(rule_id)
        if rule is None:
            raise KeyError(rule_id)
        ctx = ValidationContext(
            payment=payment,
            scheme=scheme,
            session=self.session,
            now=utc_now(),
            stage=rule.stage,
            extras=extras or {},
        )
        return rule.evaluator(ctx)


def _truncate(value: str | None, limit: int = 300) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."
