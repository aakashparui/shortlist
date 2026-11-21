"""Test-case generator and runner.

Given a rule from the rule book, derive the test cases a payments QA lead would
write: positive, negative, boundary, exception, integration, regression and
reconciliation. The generator reads the rule's own parameters (for example the
scheme amount ceiling) so the boundary values are the real ones rather than
hand-written guesses.

The runner then *executes* each generated case against the engine and reports
whether the rule behaved as the case expects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import FailureInjectionInput, PaymentCreate
from app.core.identifiers import utcnow
from app.core.logging import get_logger
from app.db.models import BusinessRule, TestCase, ValidationResult
from app.domain.enums import ProcessingMode, ValidationStatus
from app.engines.validation.rules import RULES_BY_ID
from app.schemes.registry import get_scheme
from app.seed.scenarios import sepa, sic, swift
from app.services.payment_service import PaymentService

logger = get_logger(__name__)

TEST_TYPES = (
    "POSITIVE",
    "NEGATIVE",
    "BOUNDARY",
    "EXCEPTION",
    "INTEGRATION",
    "REGRESSION",
    "RECONCILIATION",
)


def base_payload(scheme_code: str) -> dict:
    if scheme_code == "SEPA_INSTANT":
        return sepa("1000.00")
    if scheme_code == "SWIFT_CROSS_BORDER":
        return swift("10000.00")
    if scheme_code == "GENERIC_ISO20022":
        from app.seed.scenarios import generic

        return generic("1000.00")
    return sic("1000.00")


@dataclass(slots=True)
class GeneratedCase:
    case_id: str
    test_type: str
    title: str
    preconditions: list[str]
    steps: list[str]
    input_data: dict
    expected_result: str
    expected_status: str | None
    expected_rule_outcome: str | None
    priority: str = "MEDIUM"

    def as_row(self, *, suite: str, rule_id: str | None, scheme: str, requirement_id: str | None) -> dict:
        return {
            "case_id": self.case_id,
            "suite": suite,
            "rule_id": rule_id,
            "scheme": scheme,
            "test_type": self.test_type,
            "title": self.title,
            "preconditions": self.preconditions,
            "steps": self.steps,
            "input_data": self.input_data,
            "expected_result": self.expected_result,
            "expected_status": self.expected_status,
            "expected_rule_outcome": self.expected_rule_outcome,
            "priority": self.priority,
            "requirement_id": requirement_id,
        }


@dataclass(slots=True)
class RunOutcome:
    case: TestCase
    passed: bool
    detail: dict = field(default_factory=dict)


class TestCaseService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.payments = PaymentService(session)

    # ------------------------------------------------------------------
    # generation
    # ------------------------------------------------------------------
    def generate_for_rule(self, rule_id: str, scheme_code: str) -> list[GeneratedCase]:
        rule = RULES_BY_ID.get(rule_id)
        row = self.session.execute(
            select(BusinessRule).where(BusinessRule.rule_id == rule_id).limit(1)
        ).scalar_one_or_none()
        if rule is None and row is None:
            raise LookupError(f"Rule '{rule_id}' not found")
        scheme = get_scheme(scheme_code)
        base = base_payload(scheme_code)
        seq = 0

        def next_id() -> str:
            nonlocal seq
            seq += 1
            return f"TC{seq:03d}"

        cases: list[GeneratedCase] = []
        field_name = (rule.field if rule else row.field) or ""
        category = (rule.category.value if rule else row.category) or "BUSINESS"

        # --- amount-limit rules: real boundary analysis ------------------
        if field_name == "amount" and rule_id in (
            "VAL-AMOUNT-003",
            "SIC-AMOUNT-001",
            "SEPA-AMOUNT-001",
        ):
            limit = scheme.rules.limit_for(base["currency"])
            if limit is None:  # pragma: no cover
                raise LookupError(f"{scheme_code} has no amount limit for {base['currency']}")
            maximum = limit.maximum
            minimum = limit.minimum
            step = Decimal("0.01")
            values: list[tuple[str, Decimal, str, str | None, str | None, str]] = [
                (
                    "BOUNDARY",
                    maximum - step,
                    f"Amount one minor unit below the {maximum} {limit.currency} ceiling is accepted",
                    "PASSED",
                    "COMPLETED",
                    "HIGH",
                ),
                (
                    "BOUNDARY",
                    maximum,
                    f"Amount exactly at the {maximum} {limit.currency} ceiling is accepted",
                    "PASSED",
                    "COMPLETED",
                    "HIGH",
                ),
                (
                    "NEGATIVE",
                    maximum + step,
                    "Amount one minor unit above the ceiling is rejected",
                    "FAILED",
                    "REJECTED",
                    "HIGH",
                ),
                (
                    "BOUNDARY",
                    minimum,
                    f"Amount exactly at the {minimum} {limit.currency} minimum is accepted",
                    "PASSED",
                    "COMPLETED",
                    "MEDIUM",
                ),
                # Zero and negative amounts are caught by VAL-AMOUNT-001 during
                # pre-validation, which is an earlier stage than the scheme
                # ceiling rule, so the scheme rule never executes. The case
                # therefore asserts the payment status, not this rule's outcome.
                ("NEGATIVE", Decimal("0"), "Zero amount is rejected", None, "REJECTED", "HIGH"),
                (
                    "NEGATIVE",
                    Decimal("-100.00"),
                    "Negative amount is rejected",
                    None,
                    "REJECTED",
                    "HIGH",
                ),
                (
                    "POSITIVE",
                    (maximum / 2).quantize(Decimal("0.01")),
                    "A typical mid-range amount completes end to end",
                    "PASSED",
                    "COMPLETED",
                    "HIGH",
                ),
            ]
            for test_type, amount, title, outcome, status, priority in values:
                payload = {**base, "amount": str(amount)}
                cases.append(
                    GeneratedCase(
                        case_id=next_id(),
                        test_type=test_type,
                        title=title,
                        preconditions=[
                            f"Scheme {scheme.short_name} is selected",
                            f"Rule {rule_id} is enabled",
                            "The debtor account is funded above the test amount",
                        ],
                        steps=[
                            f"Create a payment for {amount} {base['currency']}",
                            "Execute the payment",
                            f"Inspect the {rule_id} validation result",
                        ],
                        input_data=payload,
                        expected_result=(
                            f"{rule_id} status {outcome}; payment status {status}"
                            if outcome
                            else (
                                f"Payment status {status}. VAL-AMOUNT-001 rejects the amount during "
                                f"pre-validation, so {rule_id} is never reached."
                            )
                        ),
                        expected_status=status,
                        expected_rule_outcome=outcome,
                        priority=priority,
                    )
                )
            # Combination case: boundary amount with an invalid currency
            bad_currency = next(
                (c for c in ("USD", "GBP", "SEK") if c not in scheme.rules.allowed_currencies),
                "USD",
            )
            cases.append(
                GeneratedCase(
                    case_id=next_id(),
                    test_type="EXCEPTION",
                    title=f"Maximum amount with an unsupported currency ({bad_currency}) is rejected",
                    preconditions=[f"Scheme {scheme.short_name} is selected"],
                    steps=[
                        f"Create a payment for {maximum} {bad_currency}",
                        "Execute the payment",
                        "Inspect the scheme currency rule",
                    ],
                    input_data={**base, "amount": str(maximum), "currency": bad_currency},
                    expected_result="The scheme currency rule fails; payment status REJECTED",
                    expected_status="REJECTED",
                    expected_rule_outcome=None,
                    priority="MEDIUM",
                )
            )
        else:
            # --- generic rule: positive plus the matching injection -------
            cases.append(
                GeneratedCase(
                    case_id=next_id(),
                    test_type="POSITIVE",
                    title=f"{rule_id} passes for a well-formed instruction",
                    preconditions=[f"Rule {rule_id} is enabled", "All input data is valid"],
                    steps=["Create a valid payment", "Execute it", f"Inspect {rule_id}"],
                    input_data=dict(base),
                    expected_result=f"{rule_id} status PASSED",
                    expected_status=None,
                    expected_rule_outcome="PASSED",
                    priority="MEDIUM",
                )
            )
            injection = self._injection_for_rule(rule_id)
            if injection:
                cases.append(
                    GeneratedCase(
                        case_id=next_id(),
                        test_type="NEGATIVE",
                        title=f"{rule_id} fails when '{injection}' is injected",
                        preconditions=[f"Rule {rule_id} is enabled"],
                        steps=[
                            f"Create a payment with failure injection {injection}",
                            "Execute it",
                            f"Inspect {rule_id}",
                        ],
                        input_data={
                            **base,
                            "failureInjections": [{"code": injection, "parameters": {}}],
                        },
                        expected_result=f"{rule_id} status FAILED and the payment does not complete",
                        expected_status=None,
                        expected_rule_outcome="FAILED",
                        priority="HIGH",
                    )
                )
            if field_name in ("creditor.name", "debtor.name", "endToEndId", "creditor.account"):
                cases.append(
                    GeneratedCase(
                        case_id=next_id(),
                        test_type="BOUNDARY",
                        title=f"{field_name} at the maximum permitted length is accepted",
                        preconditions=["The field is populated to exactly its maximum length"],
                        steps=["Create the payment", "Execute it", f"Inspect {rule_id}"],
                        input_data=self._max_length_payload(base, field_name),
                        expected_result=f"{rule_id} status PASSED",
                        expected_status=None,
                        expected_rule_outcome="PASSED",
                        priority="MEDIUM",
                    )
                )
                cases.append(
                    GeneratedCase(
                        case_id=next_id(),
                        test_type="NEGATIVE",
                        title=f"{field_name} left empty is rejected",
                        preconditions=["The mandatory field is cleared"],
                        steps=["Create the payment", "Execute it", f"Inspect {rule_id}"],
                        input_data={
                            **base,
                            "failureInjections": [
                                {
                                    "code": "MISSING_MANDATORY_FIELD",
                                    "parameters": {"field": field_name},
                                }
                            ],
                        },
                        expected_result="A mandatory-field rule fails; payment status REJECTED",
                        expected_status="REJECTED",
                        expected_rule_outcome=None,
                        priority="HIGH",
                    )
                )

        # --- integration, regression and reconciliation ------------------
        cases.append(
            GeneratedCase(
                case_id=next_id(),
                test_type="INTEGRATION",
                title=f"A payment that satisfies {rule_id} clears, settles and is accounted for",
                preconditions=["The clearing system is configured to accept"],
                steps=[
                    "Create a valid payment",
                    "Execute it",
                    "Verify the pacs.008 and pacs.002",
                    "Verify settlement and the accounting journal",
                ],
                input_data=dict(base),
                expected_result=(
                    "pacs.008 and pacs.002 exist, settlement status SETTLED and the journal balances"
                ),
                expected_status="COMPLETED",
                expected_rule_outcome="PASSED",
                priority="HIGH",
            )
        )
        cases.append(
            GeneratedCase(
                case_id=next_id(),
                test_type="RECONCILIATION",
                title=f"Reconciliation matches after a {rule_id}-compliant payment completes",
                preconditions=["The statement notification is received"],
                steps=[
                    "Create and execute a valid payment",
                    "Inspect the reconciliation record and its four legs",
                ],
                input_data=dict(base),
                expected_result="Reconciliation status MATCHED with no difference amount",
                expected_status="COMPLETED",
                expected_rule_outcome="PASSED",
                priority="HIGH",
            )
        )
        cases.append(
            GeneratedCase(
                case_id=next_id(),
                test_type="REGRESSION",
                title=f"Disabling {rule_id} stops the check without breaking the lifecycle",
                preconditions=[f"Rule {rule_id} is disabled in the rule engine"],
                steps=[
                    f"Disable {rule_id}",
                    "Create and execute a payment that would have failed the rule",
                    "Confirm the rule is recorded as SKIPPED",
                    f"Re-enable {rule_id}",
                ],
                input_data=dict(base),
                expected_result=f"{rule_id} status SKIPPED; the payment is not rejected by this rule",
                expected_status=None,
                expected_rule_outcome="SKIPPED",
                priority="LOW",
            )
        )
        if category == "COMPLIANCE":
            cases.append(
                GeneratedCase(
                    case_id=next_id(),
                    test_type="EXCEPTION",
                    title="A screening hit blocks the payment before dispatch",
                    preconditions=["Screening is enabled"],
                    steps=[
                        "Create a payment with a sanctions injection",
                        "Execute it",
                        "Confirm no pacs.008 is dispatched",
                    ],
                    input_data={
                        **base,
                        "failureInjections": [{"code": "SANCTIONS_MATCH", "parameters": {}}],
                    },
                    expected_result="Payment is blocked and an investigation is opened",
                    expected_status="INVESTIGATION_REQUIRED",
                    expected_rule_outcome=None,
                    priority="HIGH",
                )
            )
        return cases

    def _injection_for_rule(self, rule_id: str) -> str | None:
        from app.engines.failure_injection import CATALOGUE

        for definition in CATALOGUE:
            if rule_id in definition.affected_rule_ids:
                return definition.code
        return None

    def _max_length_payload(self, base: dict, field_name: str) -> dict:
        payload = {k: (dict(v) if isinstance(v, dict) else v) for k, v in base.items()}
        if field_name == "creditor.name":
            payload["creditor"]["name"] = "A" * 140
        elif field_name == "debtor.name":
            payload["debtor"]["name"] = "B" * 140
        elif field_name == "endToEndId":
            payload["endToEndId"] = "E" * 35
        return payload

    # ------------------------------------------------------------------
    # persistence
    # ------------------------------------------------------------------
    def persist(
        self, cases: list[GeneratedCase], *, suite: str, rule_id: str | None, scheme: str
    ) -> list[TestCase]:
        requirement_id = f"FR-{rule_id}" if rule_id else None
        self.session.execute(
            select(TestCase).where(TestCase.suite == suite)
        )  # ensure table is loaded for the delete below
        for existing in self.session.execute(
            select(TestCase).where(TestCase.suite == suite)
        ).scalars():
            self.session.delete(existing)
        self.session.flush()
        rows: list[TestCase] = []
        for case in cases:
            row = TestCase(
                **case.as_row(
                    suite=suite, rule_id=rule_id, scheme=scheme, requirement_id=requirement_id
                )
            )
            self.session.add(row)
            rows.append(row)
        self.session.flush()
        logger.info("test cases generated", extra={"suite": suite, "count": len(rows)})
        return rows

    def list_cases(self, *, suite: str | None = None, rule_id: str | None = None) -> list[TestCase]:
        stmt = select(TestCase)
        if suite:
            stmt = stmt.where(TestCase.suite == suite)
        if rule_id:
            stmt = stmt.where(TestCase.rule_id == rule_id)
        return list(self.session.execute(stmt.order_by(TestCase.id.asc())).scalars())

    def suites(self) -> list[dict]:
        rows = self.session.execute(
            select(TestCase.suite, TestCase.rule_id, TestCase.scheme).distinct()
        ).all()
        counts: dict[str, dict] = {}
        for suite, rule_id, scheme in rows:
            counts.setdefault(suite, {"suite": suite, "ruleId": rule_id, "scheme": scheme, "cases": 0})
        for suite in counts:
            counts[suite]["cases"] = len(self.list_cases(suite=suite))
        return sorted(counts.values(), key=lambda s: s["suite"])

    # ------------------------------------------------------------------
    # execution
    # ------------------------------------------------------------------
    def run_case(self, case: TestCase) -> RunOutcome:
        data = dict((case.input_data or {}).items())
        injections = data.pop("failureInjections", [])
        data["processingMode"] = ProcessingMode.IMMEDIATE.value
        data["createdBy"] = "qa.lab"
        data["source"] = "TEST_CASE"
        data["tags"] = sorted({case.suite, case.test_type, case.case_id})
        if case.test_type == "REGRESSION":
            return self._run_regression(case, data)
        payload = PaymentCreate.model_validate(
            {
                **data,
                "failureInjections": [
                    FailureInjectionInput.model_validate(i).model_dump() for i in injections
                ],
            }
        )
        payment = self.payments.create(payload)
        self.payments.execute(payment, mode=ProcessingMode.IMMEDIATE)
        self.session.refresh(payment)
        return self._assess(case, payment)

    def _run_regression(self, case: TestCase, data: dict) -> RunOutcome:
        """Disable the rule, confirm it is skipped, re-enable it."""
        rule_row = (
            self.session.execute(
                select(BusinessRule).where(BusinessRule.rule_id == case.rule_id).limit(1)
            ).scalar_one_or_none()
            if case.rule_id
            else None
        )
        if rule_row is None:
            return RunOutcome(case=case, passed=False, detail={"error": "Rule not found"})
        was_enabled = rule_row.enabled
        rule_row.enabled = False
        self.session.flush()
        # The validation engine caches the disabled-rule set per instance, so it
        # must be told the rule book changed under it.
        self.payments.orchestrator.validator.invalidate_rule_cache()
        try:
            payload = PaymentCreate.model_validate({**data, "failureInjections": []})
            payment = self.payments.create(payload)
            self.payments.execute(payment, mode=ProcessingMode.IMMEDIATE)
            self.session.refresh(payment)
            outcome = self._assess(case, payment)
        finally:
            rule_row.enabled = was_enabled
            self.session.flush()
            self.payments.orchestrator.validator.invalidate_rule_cache()
        return outcome

    def _assess(self, case: TestCase, payment) -> RunOutcome:  # noqa: ANN001
        checks: list[dict] = []
        if case.expected_status:
            checks.append(
                {
                    "name": "Payment status",
                    "expected": case.expected_status,
                    "actual": payment.status,
                    "passed": payment.status == case.expected_status,
                }
            )
        if case.expected_rule_outcome and case.rule_id:
            row = self.session.execute(
                select(ValidationResult)
                .where(
                    ValidationResult.payment_id == payment.id,
                    ValidationResult.rule_id == case.rule_id,
                )
                .order_by(ValidationResult.id.desc())
                .limit(1)
            ).scalar_one_or_none()
            actual = row.status if row else ValidationStatus.NOT_APPLICABLE.value
            checks.append(
                {
                    "name": f"{case.rule_id} outcome",
                    "expected": case.expected_rule_outcome,
                    "actual": actual,
                    "passed": actual == case.expected_rule_outcome,
                    "message": row.message if row else "The rule did not execute for this payment.",
                }
            )
        passed = all(c["passed"] for c in checks) if checks else True
        case.last_run_at = utcnow()
        case.last_run_outcome = "PASSED" if passed else "FAILED"
        case.last_run_payment_id = payment.id
        case.last_run_detail = {"paymentReference": payment.reference, "checks": checks}
        self.session.flush()
        return RunOutcome(case=case, passed=passed, detail=case.last_run_detail)

    def run_suite(self, cases: list[TestCase]) -> dict:
        results = [self.run_case(case) for case in cases]
        passed = sum(1 for r in results if r.passed)
        return {
            "total": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "results": [
                {
                    "caseId": r.case.case_id,
                    "title": r.case.title,
                    "testType": r.case.test_type,
                    "outcome": r.case.last_run_outcome,
                    "detail": r.detail,
                }
                for r in results
            ],
        }


def future_date(days: int) -> str:
    return (utcnow() + timedelta(days=days)).date().isoformat()
