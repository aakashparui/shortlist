"""Scenario execution and expected-vs-actual comparison."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import FailureInjectionInput, PaymentCreate
from app.core.identifiers import scenario_execution_reference, utcnow
from app.core.logging import get_logger
from app.db.models import (
    AccountingEntry,
    Payment,
    PaymentMessage,
    ReconciliationRecord,
    Scenario,
    ScenarioExecution,
)
from app.domain.enums import (
    AccountingStatus,
    EntrySide,
    EventType,
    ProcessingMode,
    SourceSystem,
)
from app.services.payment_service import PaymentService

logger = get_logger(__name__)


@dataclass(slots=True)
class Assertion:
    name: str
    expected: str
    actual: str
    passed: bool
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "expected": self.expected,
            "actual": self.actual,
            "passed": self.passed,
            "note": self.note,
        }


@dataclass(slots=True)
class ScenarioResult:
    execution: ScenarioExecution
    payment: Payment
    assertions: list[Assertion] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(a.passed for a in self.assertions)


class ScenarioService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.payments = PaymentService(session)

    def list_scenarios(self) -> list[Scenario]:
        return list(
            self.session.execute(select(Scenario).order_by(Scenario.sort_order.asc())).scalars()
        )

    def get(self, code: str) -> Scenario | None:
        return self.session.execute(
            select(Scenario).where(Scenario.code == code.upper()).limit(1)
        ).scalar_one_or_none()

    def require(self, code: str) -> Scenario:
        scenario = self.get(code)
        if scenario is None:
            raise LookupError(f"Scenario '{code}' not found")
        return scenario

    # ------------------------------------------------------------------
    def build_payload(self, scenario: Scenario, *, mode: ProcessingMode) -> PaymentCreate:
        data = dict(scenario.input_data or {})
        data["processingMode"] = mode.value
        data["failureInjections"] = [
            FailureInjectionInput(code=code).model_dump() for code in (scenario.failure_codes or [])
        ]
        data.setdefault("createdBy", "qa.lab")
        data["source"] = "SCENARIO"
        data["tags"] = sorted({*(data.get("tags") or []), scenario.code, scenario.category})
        return PaymentCreate.model_validate(data)

    def _prepare_preconditions(
        self, scenario: Scenario, *, mode: ProcessingMode, is_demo_data: bool
    ) -> list[str]:
        """Create the state a scenario's preconditions require.

        A scenario must be runnable on an empty database, so a scenario that
        depends on an earlier instruction (the duplicate check) creates that
        instruction for real rather than assuming one happens to be there.
        """
        notes: list[str] = []
        if "DUPLICATE_END_TO_END_ID" not in (scenario.failure_codes or []):
            return notes
        data = dict(scenario.input_data or {})
        data["processingMode"] = ProcessingMode.IMMEDIATE.value
        data["failureInjections"] = []
        data["createdBy"] = "qa.lab"
        data["source"] = "SCENARIO_PRECONDITION"
        data["tags"] = [scenario.code, "PRECONDITION"]
        baseline = self.payments.create(
            PaymentCreate.model_validate(data),
            is_demo_data=is_demo_data,
            scenario_code=scenario.code,
        )
        self.payments.execute(baseline, mode=ProcessingMode.IMMEDIATE)
        self.session.refresh(baseline)
        notes.append(
            f"Precondition: baseline payment {baseline.reference} executed so that a prior "
            f"EndToEndId exists on the {scenario.scheme} rail."
        )
        return notes

    def run(
        self,
        scenario: Scenario,
        *,
        mode: ProcessingMode = ProcessingMode.IMMEDIATE,
        is_demo_data: bool = False,
    ) -> ScenarioResult:
        precondition_notes = self._prepare_preconditions(
            scenario, mode=mode, is_demo_data=is_demo_data
        )
        payload = self.build_payload(scenario, mode=mode)
        payment = self.payments.create(
            payload, is_demo_data=is_demo_data, scenario_code=scenario.code
        )
        execution = ScenarioExecution(
            reference=scenario_execution_reference(),
            scenario_id=scenario.id,
            scenario_code=scenario.code,
            payment_id=payment.id,
            started_at=utcnow(),
            outcome="RUNNING",
            expected_status=scenario.expected_status,
        )
        self.session.add(execution)
        self.session.flush()

        self.payments.execute(payment, mode=mode)
        self.session.refresh(payment)

        assertions = self.assert_scenario(scenario, payment)
        execution.finished_at = utcnow()
        execution.actual_status = payment.status
        execution.assertions = [a.as_dict() for a in assertions]
        execution.outcome = "PASSED" if all(a.passed for a in assertions) else "FAILED"
        outcome_note = (
            "All expectations met."
            if execution.outcome == "PASSED"
            else "; ".join(
                f"{a.name}: expected {a.expected}, got {a.actual}"
                for a in assertions
                if not a.passed
            )
        )
        execution.notes = " ".join([*precondition_notes, outcome_note]).strip()
        self.session.flush()

        self.payments.events.record(
            payment,
            EventType.SCENARIO_EXECUTED,
            SourceSystem.QA_LAB,
            f"Scenario {scenario.code} executed: {execution.outcome}",
            detail={
                "scenarioCode": scenario.code,
                "outcome": execution.outcome,
                "executionReference": execution.reference,
            },
        )
        return ScenarioResult(execution=execution, payment=payment, assertions=assertions)

    # ------------------------------------------------------------------
    def assert_scenario(self, scenario: Scenario, payment: Payment) -> list[Assertion]:
        assertions: list[Assertion] = [
            Assertion(
                name="Payment status",
                expected=scenario.expected_status,
                actual=payment.status,
                passed=payment.status == scenario.expected_status,
                note="The lifecycle must end in the state the scenario describes.",
            )
        ]

        expected_messages = list(scenario.expected_messages or [])
        if expected_messages:
            present = {
                row.message_type
                for row in self.session.execute(
                    select(PaymentMessage).where(PaymentMessage.payment_id == payment.id)
                ).scalars()
            }
            missing = [m for m in expected_messages if m not in present]
            assertions.append(
                Assertion(
                    name="Expected messages generated",
                    expected=", ".join(expected_messages),
                    actual=", ".join(sorted(present)) or "none",
                    passed=not missing,
                    note=f"Missing: {', '.join(missing)}" if missing else "",
                )
            )
        else:
            message_count = self.session.execute(
                select(PaymentMessage).where(PaymentMessage.payment_id == payment.id)
            ).scalars()
            count = len(list(message_count))
            assertions.append(
                Assertion(
                    name="No messages generated",
                    expected="0 messages",
                    actual=f"{count} messages",
                    passed=count == 0,
                    note="A payment rejected before message generation must not produce a pacs.008.",
                )
            )

        expected_recon = scenario.expected_reconciliation or "NOT_RUN"
        record = self.session.execute(
            select(ReconciliationRecord)
            .where(ReconciliationRecord.payment_id == payment.id)
            .order_by(ReconciliationRecord.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        actual_recon = record.status if record else "NOT_RUN"
        assertions.append(
            Assertion(
                name="Reconciliation outcome",
                expected=expected_recon,
                actual=actual_recon,
                passed=actual_recon == expected_recon,
            )
        )

        entries = list(
            self.session.execute(
                select(AccountingEntry).where(AccountingEntry.payment_id == payment.id)
            ).scalars()
        )
        active = [e for e in entries if e.status != AccountingStatus.REVERSED.value]
        debits = sum(
            (e.amount for e in active if e.side == EntrySide.DEBIT.value), Decimal("0")
        )
        credits = sum(
            (e.amount for e in active if e.side == EntrySide.CREDIT.value), Decimal("0")
        )
        expects_break = scenario.category == "ACCOUNTING" or any(
            code.startswith("ACCOUNTING_") for code in (scenario.failure_codes or [])
        )
        balanced = debits == credits
        assertions.append(
            Assertion(
                name="Accounting journal balance",
                expected="unbalanced journal" if expects_break else "debits equal credits",
                actual=f"debits {debits}, credits {credits}",
                passed=(not balanced) if expects_break else balanced,
                note="Only accounting-break scenarios may leave the journal unbalanced.",
            )
        )
        return assertions

    def executions(self, limit: int = 50) -> list[ScenarioExecution]:
        return list(
            self.session.execute(
                select(ScenarioExecution).order_by(ScenarioExecution.id.desc()).limit(limit)
            ).scalars()
        )
