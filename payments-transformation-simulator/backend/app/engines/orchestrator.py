"""Payment orchestration.

The orchestrator drives the lifecycle and is the only component allowed to
change the payment's status. It is deliberately explicit: each stage starts,
does its work through a dedicated engine, and ends in a recorded state.

Two processing modes
--------------------
IMMEDIATE  everything runs inside the caller's transaction with no artificial
           delay. Used by tests, the QA Lab and scenario execution.
SIMULATED  clearing responses and timeouts are handed to the durable scheduler
           so the UI can watch the lifecycle progress in real time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.identifiers import utcnow
from app.core.logging import get_logger
from app.db.models import (
    ClearingTransaction,
    Payment,
    PaymentMessage,
    PaymentStage,
    ScheduledJob,
)
from app.domain.enums import (
    STAGE_ORDER,
    AccountingStatus,
    ClearingDecision,
    ClearingStatus,
    EntrySide,
    EventType,
    InvestigationReason,
    MessageType,
    PaymentStatus,
    ProcessingMode,
    SettlementStatus,
    Severity,
    SourceSystem,
    StageKey,
    StageState,
)
from app.engines.accounting import AccountingEngine
from app.engines.clearing import ClearingAdapter
from app.engines.compliance import ComplianceEngine
from app.engines.events import EventRecorder
from app.engines.failure_injection import FailureInjectionEngine
from app.engines.investigation import InvestigationDesk
from app.engines.messaging.engine import MessageEngine
from app.engines.reconciliation import ReconciliationEngine, StatementFeedSimulator
from app.engines.settlement import SettlementEngine
from app.engines.state_machine import IllegalTransitionError, assert_transition
from app.engines.validation.engine import ValidationEngine
from app.schemes.registry import clearing_timeout_seconds, get_scheme

logger = get_logger(__name__)

JOB_CLEARING_RESPONSE = "CLEARING_RESPONSE"
JOB_CLEARING_TIMEOUT = "CLEARING_TIMEOUT_CHECK"
JOB_POST_COMPLETION = "POST_COMPLETION_EVENT"


@dataclass(slots=True)
class ExecutionResult:
    payment: Payment
    status: PaymentStatus
    stages_completed: list[str] = field(default_factory=list)
    failure_stage: StageKey | None = None
    failure_reason: str | None = None
    awaiting_async: bool = False
    notes: list[str] = field(default_factory=list)


class PaymentOrchestrator:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.events = EventRecorder(session)
        self.validator = ValidationEngine(session)
        self.compliance = ComplianceEngine(session)
        self.messages = MessageEngine(session)
        self.clearing = ClearingAdapter(session)
        self.settlement = SettlementEngine(session)
        self.accounting = AccountingEngine(session)
        self.statements = StatementFeedSimulator(session)
        self.reconciliation = ReconciliationEngine(session)
        self.investigations = InvestigationDesk(session)
        self.injections = FailureInjectionEngine(session)

    # ------------------------------------------------------------------
    # stage plumbing
    # ------------------------------------------------------------------
    def ensure_stages(self, payment: Payment) -> list[PaymentStage]:
        existing = {s.stage_key: s for s in payment.stages}
        created: list[PaymentStage] = []
        for index, key in enumerate(STAGE_ORDER):
            if key.value in existing:
                continue
            stage = PaymentStage(
                payment_id=payment.id,
                stage_key=key.value,
                sequence=index,
                state=StageState.PENDING.value,
                owner_system=_stage_owner(key).value,
            )
            self.session.add(stage)
            created.append(stage)
        if created:
            self.session.flush()
            self.session.refresh(payment)
        return sorted(payment.stages, key=lambda s: s.sequence)

    def _stage(self, payment: Payment, key: StageKey) -> PaymentStage:
        for stage in payment.stages:
            if stage.stage_key == key.value:
                return stage
        self.ensure_stages(payment)
        for stage in payment.stages:
            if stage.stage_key == key.value:
                return stage
        raise LookupError(key.value)  # pragma: no cover

    def _start(self, payment: Payment, key: StageKey, summary: str = "") -> PaymentStage:
        stage = self._stage(payment, key)
        stage.state = StageState.IN_PROGRESS.value
        stage.started_at = utcnow()
        stage.summary = summary or stage.summary
        self.session.flush()
        self.events.record(
            payment,
            EventType.STAGE_STARTED,
            _stage_owner(key),
            summary or f"{key.value} started",
            stage=key,
        )
        return stage

    def _complete(
        self,
        payment: Payment,
        key: StageKey,
        summary: str,
        detail: dict | None = None,
        state: StageState = StageState.COMPLETED,
    ) -> PaymentStage:
        stage = self._stage(payment, key)
        stage.state = state.value
        stage.completed_at = utcnow()
        if stage.started_at:
            stage.duration_ms = int((stage.completed_at - stage.started_at).total_seconds() * 1000)
        stage.summary = summary
        if detail is not None:
            stage.detail = detail
        self.session.flush()
        self.events.record(
            payment,
            EventType.STAGE_COMPLETED,
            _stage_owner(key),
            summary,
            stage=key,
            detail=detail or {},
            duration_ms=stage.duration_ms,
        )
        return stage

    def _fail(
        self,
        payment: Payment,
        key: StageKey,
        state: StageState,
        summary: str,
        reason: str,
        detail: dict | None = None,
        iso_reason_code: str | None = None,
    ) -> PaymentStage:
        stage = self._stage(payment, key)
        stage.state = state.value
        stage.completed_at = utcnow()
        if stage.started_at:
            stage.duration_ms = int((stage.completed_at - stage.started_at).total_seconds() * 1000)
        stage.summary = summary
        stage.failure_reason = reason
        stage.iso_reason_code = iso_reason_code
        if detail is not None:
            stage.detail = detail
        self.session.flush()
        self.events.record(
            payment,
            EventType.STAGE_FAILED,
            _stage_owner(key),
            summary,
            severity=Severity.ERROR,
            stage=key,
            detail={"reason": reason, **(detail or {})},
        )
        return stage

    def _skip_remaining(self, payment: Payment, from_key: StageKey, note: str) -> None:
        reached = False
        for key in STAGE_ORDER:
            if key == from_key:
                reached = True
                continue
            if not reached:
                continue
            stage = self._stage(payment, key)
            if stage.state == StageState.PENDING.value:
                stage.state = StageState.SKIPPED.value
                stage.summary = note
        self.session.flush()

    # ------------------------------------------------------------------
    # status
    # ------------------------------------------------------------------
    def set_status(
        self,
        payment: Payment,
        target: PaymentStatus,
        *,
        reason: str = "",
        force: bool = False,
    ) -> None:
        current = PaymentStatus(payment.status)
        if current == target:
            return
        if not force:
            assert_transition(current, target)
        payment.previous_status = current.value
        payment.status = target.value
        payment.updated_at = utcnow()
        if target in (
            PaymentStatus.COMPLETED,
            PaymentStatus.REJECTED,
            PaymentStatus.BLOCKED,
            PaymentStatus.CLEARING_REJECTED,
            PaymentStatus.CANCELLED,
            PaymentStatus.RETURNED,
            PaymentStatus.REVERSED,
        ):
            payment.completed_at = utcnow()
        self.session.flush()
        self.events.record(
            payment,
            EventType.STATUS_CHANGED,
            SourceSystem.ORCHESTRATOR,
            f"Status {current.value} -> {target.value}" + (f": {reason}" if reason else ""),
            severity=Severity.ERROR if target.is_failure else Severity.INFO,
            detail={"from": current.value, "to": target.value, "reason": reason},
        )

    # ------------------------------------------------------------------
    # main execution
    # ------------------------------------------------------------------
    def execute(self, payment: Payment, *, mode: ProcessingMode | None = None) -> ExecutionResult:
        scheme = get_scheme(payment.scheme)
        processing_mode = mode or ProcessingMode(payment.processing_mode)
        payment.processing_mode = processing_mode.value
        self.events.bind_context(payment)
        self.ensure_stages(payment)
        result = ExecutionResult(payment=payment, status=PaymentStatus(payment.status))

        if payment.status == PaymentStatus.DRAFT.value:
            self.set_status(payment, PaymentStatus.INITIATED, reason="Execution requested")
        payment.executed_at = payment.executed_at or utcnow()

        # --- initiation & intake ---
        self._start(payment, StageKey.INITIATION, "Customer instruction accepted")
        self._complete(
            payment,
            StageKey.INITIATION,
            f"Instruction {payment.reference} created on the {scheme.short_name} rail",
            {
                "reference": payment.reference,
                "correlationId": payment.correlation_id,
                "scheme": scheme.name,
                "amount": str(payment.amount),
                "currency": payment.currency,
                "createdBy": payment.created_by,
                "source": payment.source,
            },
        )
        result.stages_completed.append(StageKey.INITIATION.value)

        self._start(payment, StageKey.CHANNEL_INTAKE, "Channel intake")
        changes = self.injections.apply_pre_execution(payment)
        if changes:
            for change in changes:
                self.events.record(
                    payment,
                    EventType.FAILURE_INJECTED,
                    SourceSystem.QA_LAB,
                    change["summary"],
                    severity=Severity.WARNING,
                    stage=StageKey.CHANNEL_INTAKE,
                    detail=change,
                )
                self.events.audit(
                    actor="qa.lab",
                    action=f"INJECT:{change['code']}",
                    entity_type="Payment",
                    entity_id=payment.reference,
                    reason=change["summary"],
                    before={change["field"]: change["before"]},
                    after={change["field"]: change["after"]},
                    correlation_id=payment.correlation_id,
                )
        self._complete(
            payment,
            StageKey.CHANNEL_INTAKE,
            "Instruction accepted by the channel and queued for validation",
            {
                "correlationId": payment.correlation_id,
                "instructionId": payment.instruction_id,
                "endToEndId": payment.end_to_end_id,
                "uetr": payment.uetr,
                "injectedChanges": changes,
            },
        )
        result.stages_completed.append(StageKey.CHANNEL_INTAKE.value)

        # --- validation ---
        self.set_status(payment, PaymentStatus.VALIDATING, reason="Validation started")
        for stage_key in (StageKey.PRE_VALIDATION, StageKey.BUSINESS_VALIDATION):
            self._start(payment, stage_key, f"{stage_key.value} rules executing")
            run = self.validator.run(payment, scheme, stage_key)
            counts = run.counts()
            detail = {
                "counts": counts,
                "results": [_validation_dict(r) for r in run.results],
            }
            self.events.record(
                payment,
                EventType.VALIDATION_EXECUTED,
                SourceSystem.VALIDATION_ENGINE,
                f"{counts['executed']} rules executed, {counts['failed']} failed",
                stage=stage_key,
                detail={"counts": counts},
            )
            if not run.passed:
                failure = run.first_failure
                assert failure is not None
                self._fail(
                    payment,
                    stage_key,
                    StageState.REJECTED,
                    f"Rejected by {failure.rule_id}: {failure.message}",
                    failure.message,
                    detail,
                    failure.iso_reason_code,
                )
                self.events.record(
                    payment,
                    EventType.VALIDATION_FAILED,
                    SourceSystem.VALIDATION_ENGINE,
                    f"{failure.rule_id} failed: {failure.message}",
                    severity=Severity.ERROR,
                    stage=stage_key,
                    detail=_validation_dict(failure),
                )
                self.set_status(
                    payment, PaymentStatus.REJECTED, reason=f"{failure.rule_id}: {failure.message}"
                )
                payment.failure_summary = (
                    f"{stage_key.value}: {failure.rule_id} - {failure.message}"
                )
                self._skip_remaining(payment, stage_key, "Not reached: payment rejected in validation")
                result.status = PaymentStatus.REJECTED
                result.failure_stage = stage_key
                result.failure_reason = failure.message
                return result
            self._complete(
                payment,
                stage_key,
                f"{counts['passed']} of {counts['executed']} rules passed, {counts['skipped']} skipped",
                detail,
            )
            result.stages_completed.append(stage_key.value)
        self.set_status(payment, PaymentStatus.VALIDATED, reason="All validation rules passed")

        # --- compliance ---
        self.set_status(payment, PaymentStatus.COMPLIANCE_CHECK, reason="Screening started")
        self._start(payment, StageKey.COMPLIANCE, "Sanctions and embargo screening")
        overrides = self.injections.compliance_overrides(payment)
        screening = self.compliance.screen(payment, forced=overrides)
        screening_detail = {
            "hits": [
                {
                    "ruleId": h.rule_id,
                    "matchValue": h.match_value,
                    "listReference": h.list_reference,
                    "detail": h.detail,
                    "blocking": h.blocking,
                }
                for h in screening.hits
            ],
            "screenedValues": screening.screened_values,
            "results": [_validation_dict(r) for r in screening.results],
            "simulationNote": (
                "Screening runs against a small fictional list. Real screening uses licensed "
                "watch-list data and fuzzy matching."
            ),
        }
        self.events.record(
            payment,
            EventType.COMPLIANCE_SCREENED,
            SourceSystem.COMPLIANCE_ENGINE,
            f"Screening complete: {len(screening.hits)} hit(s)",
            severity=Severity.ERROR if screening.blocked else Severity.INFO,
            stage=StageKey.COMPLIANCE,
            detail={"hitCount": len(screening.hits), "blocked": screening.blocked},
        )
        if screening.blocked:
            hit = screening.blocking_hit
            assert hit is not None
            self._fail(
                payment,
                StageKey.COMPLIANCE,
                StageState.FAILED,
                f"Blocked by {hit.rule_id}: {hit.detail}",
                hit.detail,
                screening_detail,
                "RR04",
            )
            self.set_status(payment, PaymentStatus.BLOCKED, reason=hit.detail)
            payment.failure_summary = f"COMPLIANCE: {hit.rule_id} - {hit.detail}"
            self.investigations.open(
                payment,
                InvestigationReason.COMPLIANCE_BLOCK,
                actual=hit.detail,
                probable_cause=(
                    f"Screening matched '{hit.match_value}' against {hit.list_reference}. The "
                    "payment has been stopped before any message was sent to the clearing system."
                ),
                recommended_action=(
                    "Financial-crime analyst to review the alert, record the disposition and "
                    "either release the payment or reject it and inform the originating channel."
                ),
                summary=f"{hit.rule_id} hit on {hit.match_value}",
                detail={
                    "hit": {
                        "ruleId": hit.rule_id,
                        "matchValue": hit.match_value,
                        "listReference": hit.list_reference,
                        "detail": hit.detail,
                        "blocking": hit.blocking,
                    }
                },
            )
            self.set_status(
                payment, PaymentStatus.INVESTIGATION_REQUIRED, reason="Compliance alert raised"
            )
            self._skip_remaining(payment, StageKey.COMPLIANCE, "Not reached: payment blocked by compliance")
            result.status = PaymentStatus.INVESTIGATION_REQUIRED
            result.failure_stage = StageKey.COMPLIANCE
            result.failure_reason = hit.detail
            return result
        warnings = [h for h in screening.hits if not h.blocking]
        self._complete(
            payment,
            StageKey.COMPLIANCE,
            (
                f"Screening passed with {len(warnings)} non-blocking alert(s)"
                if warnings
                else "No screening matches"
            ),
            screening_detail,
        )
        result.stages_completed.append(StageKey.COMPLIANCE.value)

        # --- orchestration / routing ---
        self._start(payment, StageKey.ORCHESTRATION, "Routing the payment")
        self._complete(
            payment,
            StageKey.ORCHESTRATION,
            f"Routed to {scheme.clearing.clearing_system_name}",
            {
                "scheme": scheme.name,
                "clearingSystem": scheme.clearing.clearing_system_name,
                "settlementMethod": scheme.settlement.settlement_method,
                "settlementAccountType": scheme.settlement.settlement_account_type,
                "valueDate": scheme.value_date().isoformat(),
                "timeoutSeconds": clearing_timeout_seconds(scheme),
                "realisticTimeoutSeconds": scheme.clearing.realistic_timeout_seconds,
                "operatingHours": scheme.clearing.operating_hours,
            },
        )
        result.stages_completed.append(StageKey.ORCHESTRATION.value)

        # --- message generation ---
        self._start(payment, StageKey.MESSAGE_GENERATION, "Generating the ISO 20022 instruction")
        message, summary = self.messages.generate_pacs008(
            payment, scheme, validation_engine=self.validator
        )
        failed_message_checks = [
            s
            for s in summary
            if s.get("status") == "FAILED" and s.get("severity") in ("ERROR", "FATAL")
        ]
        self.events.record(
            payment,
            EventType.MESSAGE_GENERATED,
            SourceSystem.MESSAGE_ENGINE,
            f"{MessageType.PACS_008.value} {message.message_id} generated",
            stage=StageKey.MESSAGE_GENERATION,
            detail={"messageId": message.message_id, "messageType": message.message_type},
        )
        if failed_message_checks:
            reason = failed_message_checks[0]["message"]
            self._fail(
                payment,
                StageKey.MESSAGE_GENERATION,
                StageState.FAILED,
                f"Message validation failed: {reason}",
                reason,
                {"messageId": message.message_id, "checks": summary},
                "FF01",
            )
            self.set_status(payment, PaymentStatus.REJECTED, reason=reason, force=True)
            payment.failure_summary = f"MESSAGE_GENERATION: {reason}"
            self._skip_remaining(
                payment, StageKey.MESSAGE_GENERATION, "Not reached: message could not be generated"
            )
            result.status = PaymentStatus.REJECTED
            result.failure_stage = StageKey.MESSAGE_GENERATION
            result.failure_reason = reason
            return result
        if scheme.messages.legacy_message is MessageType.MT_103:
            self.messages.generate_mt103(payment, scheme)
        self._complete(
            payment,
            StageKey.MESSAGE_GENERATION,
            f"{MessageType.PACS_008.value} {message.message_id} generated and validated",
            {
                "messageId": message.message_id,
                "messageType": message.message_type,
                "isoIdentifier": message.iso_identifier,
                "checks": summary,
                "legacyEquivalentGenerated": scheme.messages.legacy_message is MessageType.MT_103,
            },
        )
        result.stages_completed.append(StageKey.MESSAGE_GENERATION.value)
        self.set_status(payment, PaymentStatus.MESSAGE_GENERATED, reason="pacs.008 ready")

        # --- clearing dispatch ---
        self._start(payment, StageKey.CLEARING, f"Dispatching to {scheme.clearing.clearing_system_name}")
        dispatch = self.clearing.dispatch(
            payment,
            scheme,
            request_message_id=message.message_id,
            accelerated=processing_mode is ProcessingMode.SIMULATED,
            attempt=payment.retry_count + 1,
        )
        self.messages.mark_sent(message)
        self.events.record(
            payment,
            EventType.CLEARING_DISPATCHED,
            SourceSystem.CLEARING_ADAPTER,
            f"pacs.008 sent to {scheme.clearing.clearing_system_name}, reference "
            f"{dispatch.transaction.clearing_reference}",
            stage=StageKey.CLEARING,
            detail={
                "clearingReference": dispatch.transaction.clearing_reference,
                "decision": dispatch.decision.value,
                "timeoutSeconds": round(dispatch.timeout_seconds, 2),
            },
        )

        if dispatch.decision is ClearingDecision.UNAVAILABLE:
            reason = dispatch.transaction.status_reason or "Clearing system unavailable."
            self._fail(
                payment,
                StageKey.CLEARING,
                StageState.FAILED,
                "Clearing system unavailable; instruction not accepted for processing",
                reason,
                {
                    "clearingReference": dispatch.transaction.clearing_reference,
                    "clearingSystem": scheme.clearing.clearing_system_name,
                    "operatingHours": scheme.clearing.operating_hours,
                },
                "TECH",
            )
            payment.failure_summary = f"CLEARING: {reason}"
            self.set_status(payment, PaymentStatus.SENT_TO_CLEARING, reason="Dispatch attempted")
            self.investigations.open(
                payment,
                InvestigationReason.CLEARING_TIMEOUT,
                actual=reason,
                probable_cause=(
                    "The clearing adapter could not hand the instruction to the clearing system. "
                    "No pacs.008 was accepted, so no funds have moved."
                ),
                recommended_action=(
                    "Confirm the clearing system's availability window, then retry the payment. "
                    "Because nothing was accepted, a retry is safe and will not duplicate value."
                ),
                title="Clearing system unavailable",
                detail={"clearingReference": dispatch.transaction.clearing_reference},
            )
            self.set_status(
                payment, PaymentStatus.INVESTIGATION_REQUIRED, reason="Clearing unavailable"
            )
            self._skip_remaining(payment, StageKey.CLEARING, "Not reached: clearing system unavailable")
            result.status = PaymentStatus.INVESTIGATION_REQUIRED
            result.failure_stage = StageKey.CLEARING
            result.failure_reason = reason
            return result

        self._complete(
            payment,
            StageKey.CLEARING,
            f"Accepted for processing by {scheme.clearing.clearing_system_name}",
            {
                "clearingReference": dispatch.transaction.clearing_reference,
                "clearingSystem": scheme.clearing.clearing_system_name,
                "requestMessageId": message.message_id,
                "expectedResponseInSeconds": round(dispatch.response_delay_seconds, 2),
                "timeoutSeconds": round(dispatch.timeout_seconds, 2),
                "realisticTimeoutSeconds": scheme.clearing.realistic_timeout_seconds,
                "accelerated": processing_mode is ProcessingMode.SIMULATED,
            },
        )
        result.stages_completed.append(StageKey.CLEARING.value)
        self.set_status(payment, PaymentStatus.SENT_TO_CLEARING, reason="pacs.008 dispatched")

        self._start(
            payment,
            StageKey.CLEARING_RESPONSE,
            f"Awaiting pacs.002 (threshold {dispatch.timeout_seconds:.0f}s)",
        )

        if processing_mode is ProcessingMode.IMMEDIATE:
            if dispatch.will_respond:
                self.deliver_clearing_response(payment, dispatch.transaction)
            else:
                self.handle_clearing_timeout(payment, dispatch.transaction)
            self.session.refresh(payment)
            result.status = PaymentStatus(payment.status)
            return result

        # Asynchronous: hand the work to the durable scheduler.
        now = utcnow()
        if dispatch.will_respond:
            self._schedule(
                JOB_CLEARING_RESPONSE,
                payment,
                due_at=now + timedelta(seconds=dispatch.response_delay_seconds),
                payload={"clearingTransactionId": dispatch.transaction.id},
            )
        self._schedule(
            JOB_CLEARING_TIMEOUT,
            payment,
            due_at=now + timedelta(seconds=dispatch.timeout_seconds + 0.25),
            payload={"clearingTransactionId": dispatch.transaction.id},
        )
        result.awaiting_async = True
        result.status = PaymentStatus(payment.status)
        result.notes.append(
            f"Awaiting pacs.002; timeout in {dispatch.timeout_seconds:.1f}s "
            f"(scheme threshold {scheme.clearing.realistic_timeout_seconds}s)."
        )
        return result

    # ------------------------------------------------------------------
    # clearing response handling
    # ------------------------------------------------------------------
    def deliver_clearing_response(
        self, payment: Payment, transaction: ClearingTransaction
    ) -> None:
        scheme = get_scheme(payment.scheme)
        self.events.bind_context(payment)
        if transaction.status in (ClearingStatus.ACCEPTED.value, ClearingStatus.REJECTED.value) and (
            transaction.response_count >= 1
        ):
            duplicate_wanted = transaction.requested_decision == ClearingDecision.DUPLICATE_RESPONSE.value
            if not duplicate_wanted:
                return
        response = self.clearing.build_response(transaction, scheme)
        request_message_id = transaction.request_message_id or ""
        pacs002 = self.messages.receive_pacs002(
            payment,
            scheme,
            request_message_id,
            accepted=response.accepted,
            reason_code=response.reason_code,
            reason_text=response.reason_text,
            status_code=response.status_code,
            malform=response.malformed,
            clearing_reference=transaction.clearing_reference,
        )
        self.clearing.record_response(
            transaction, response, response_message_id=pacs002.message_id
        )
        self.events.record(
            payment,
            EventType.CLEARING_RESPONSE,
            SourceSystem.CLEARING_SYSTEM,
            (
                f"pacs.002 received: {response.status_code}"
                + (f" ({response.reason_code})" if response.reason_code else "")
            ),
            severity=Severity.ERROR if not response.accepted else Severity.INFO,
            stage=StageKey.CLEARING_RESPONSE,
            detail={
                "messageId": pacs002.message_id,
                "status": response.status_code,
                "reasonCode": response.reason_code,
                "latencyMs": transaction.response_latency_ms,
                "malformed": response.malformed,
            },
        )

        if response.malformed:
            reason = (
                "A pacs.002 arrived but it does not carry the original end-to-end identification, "
                "so it cannot be matched to the instruction automatically."
            )
            self._fail(
                payment,
                StageKey.CLEARING_RESPONSE,
                StageState.INVESTIGATION_REQUIRED,
                "Unmatched status report received",
                reason,
                {
                    "messageId": pacs002.message_id,
                    "clearingReference": transaction.clearing_reference,
                    "expected": "OrgnlEndToEndId present and equal to the instruction's EndToEndId",
                    "actual": "OrgnlEndToEndId absent",
                },
                "FF01",
            )
            payment.failure_summary = f"CLEARING_RESPONSE: {reason}"
            self.investigations.open(
                payment,
                InvestigationReason.CLEARING_TIMEOUT,
                actual=reason,
                probable_cause=(
                    "The counterparty or clearing system produced a status report that omits the "
                    "mandatory original references. Automatic matching therefore failed and the "
                    "payment is still, from our side, awaiting a usable response."
                ),
                recommended_action=(
                    "Match the status report manually using the clearing system reference, then "
                    "ask the sender to correct their message construction. Do not retry the "
                    "payment until the real status is known: the instruction may already have been "
                    "accepted."
                ),
                title="Malformed pacs.002 could not be matched",
                detail={
                    "messageId": pacs002.message_id,
                    "clearingReference": transaction.clearing_reference,
                },
            )
            self.set_status(
                payment, PaymentStatus.INVESTIGATION_REQUIRED, reason="Unmatched status report"
            )
            self._skip_remaining(
                payment, StageKey.CLEARING_RESPONSE, "Not reached: status report unusable"
            )
            return

        if response.duplicate and transaction.response_count > 1:
            self.events.record(
                payment,
                EventType.CLEARING_RESPONSE,
                SourceSystem.CLEARING_SYSTEM,
                "Duplicate pacs.002 received and ignored for processing",
                severity=Severity.WARNING,
                stage=StageKey.CLEARING_RESPONSE,
                detail={"messageId": pacs002.message_id, "responseCount": transaction.response_count},
            )
            pacs002.notes = (
                "Duplicate status report. The lifecycle had already progressed on the first "
                "response, so this message was recorded but not processed again."
            )
            self.session.flush()
            return

        if not response.accepted:
            reason = response.reason_text or "Rejected by the clearing system."
            self._fail(
                payment,
                StageKey.CLEARING_RESPONSE,
                StageState.REJECTED,
                f"pacs.002 RJCT / {response.reason_code}",
                reason,
                {
                    "messageId": pacs002.message_id,
                    "reasonCode": response.reason_code,
                    "clearingReference": transaction.clearing_reference,
                    "latencyMs": transaction.response_latency_ms,
                },
                response.reason_code,
            )
            payment.failure_summary = f"CLEARING_RESPONSE: RJCT {response.reason_code} - {reason}"
            self.set_status(
                payment,
                PaymentStatus.CLEARING_REJECTED,
                reason=f"{response.reason_code}: {reason}",
            )
            self._reverse_customer_debit_if_any(payment, f"Clearing rejection {response.reason_code}")
            self._skip_remaining(
                payment, StageKey.CLEARING_RESPONSE, "Not reached: rejected by the clearing system"
            )
            return

        self._complete(
            payment,
            StageKey.CLEARING_RESPONSE,
            f"pacs.002 {response.status_code} received in {transaction.response_latency_ms or 0} ms",
            {
                "messageId": pacs002.message_id,
                "status": response.status_code,
                "clearingReference": transaction.clearing_reference,
                "latencyMs": transaction.response_latency_ms,
                "delayed": transaction.requested_decision == ClearingDecision.DELAY.value,
            },
        )
        self.set_status(payment, PaymentStatus.CLEARING_ACCEPTED, reason="Accepted by clearing")
        if transaction.requested_decision == ClearingDecision.DUPLICATE_RESPONSE.value:
            self._schedule(
                JOB_CLEARING_RESPONSE,
                payment,
                due_at=utcnow() + timedelta(seconds=0.5),
                payload={"clearingTransactionId": transaction.id, "duplicate": True},
            )
        self.continue_after_clearing(payment)

    def handle_clearing_timeout(self, payment: Payment, transaction: ClearingTransaction) -> None:
        scheme = get_scheme(payment.scheme)
        self.events.bind_context(payment)
        if transaction.status in (
            ClearingStatus.ACCEPTED.value,
            ClearingStatus.REJECTED.value,
            ClearingStatus.TIMED_OUT.value,
        ):
            return
        now = utcnow()
        elapsed = (now - transaction.sent_at).total_seconds() if transaction.sent_at else 0.0
        threshold = float((transaction.detail or {}).get("timeoutSeconds") or clearing_timeout_seconds(scheme))
        immediate = payment.processing_mode == ProcessingMode.IMMEDIATE.value
        # In IMMEDIATE mode no wall-clock time passes, so quoting the elapsed
        # seconds would be technically true and completely unhelpful. Say what
        # actually determined the outcome instead.
        waited = (
            "the clearing system was configured not to respond"
            if immediate
            else f"waited {elapsed:.1f}s"
        )
        actual = (
            "no response: the clearing system did not answer at all"
            if immediate
            else f"no response after {elapsed:.1f}s"
        )
        self.clearing.record_timeout(transaction, elapsed)
        self.events.record(
            payment,
            EventType.CLEARING_TIMEOUT,
            SourceSystem.CLEARING_ADAPTER,
            f"No pacs.002 within {threshold:.0f}s ({waited})",
            severity=Severity.ERROR,
            stage=StageKey.CLEARING_RESPONSE,
            detail={
                "clearingReference": transaction.clearing_reference,
                "elapsedSeconds": round(elapsed, 2),
                "thresholdSeconds": round(threshold, 2),
                "realisticThresholdSeconds": scheme.clearing.investigation_threshold_seconds,
                "processingMode": payment.processing_mode,
            },
        )
        self.set_status(payment, PaymentStatus.TIMED_OUT, reason="Clearing response timeout")
        self._fail(
            payment,
            StageKey.CLEARING_RESPONSE,
            StageState.TIMED_OUT,
            f"Timed out waiting for pacs.002 ({waited})",
            (
                f"Expected a pacs.002 status report within {threshold:.0f}s "
                f"(scheme threshold {scheme.clearing.investigation_threshold_seconds}s). "
                "No response was received."
            ),
            {
                "clearingReference": transaction.clearing_reference,
                "expected": f"pacs.002 within {threshold:.0f}s",
                "actual": actual,
                "schemeThresholdSeconds": scheme.clearing.investigation_threshold_seconds,
                "accelerated": payment.processing_mode == ProcessingMode.SIMULATED.value,
                "processingMode": payment.processing_mode,
            },
            "TECH",
        )
        payment.failure_summary = (
            f"CLEARING_RESPONSE: no pacs.002 within {threshold:.0f}s; investigation initiated"
        )
        status_request = self.messages.send_pacs028(
            payment,
            scheme,
            transaction.request_message_id or "",
            elapsed_seconds=elapsed,
            threshold_seconds=threshold,
        )
        self.events.record(
            payment,
            EventType.MESSAGE_SENT,
            SourceSystem.INVESTIGATION_DESK,
            f"pacs.028 status request {status_request.message_id} sent",
            stage=StageKey.CLEARING_RESPONSE,
            detail={"messageId": status_request.message_id},
        )
        investigation = self.investigations.open(
            payment,
            InvestigationReason.CLEARING_TIMEOUT,
            actual=(
                "No status report was received: the clearing system did not answer at all."
                if immediate
                else f"No status report received after {elapsed:.1f}s."
            ),
            probable_cause=(
                "Either the clearing system never received the instruction, or it processed the "
                "instruction and the status report was lost. Until the real status is known the "
                "payment must be treated as possibly in-flight."
            ),
            recommended_action=(
                "A pacs.028 status request has been sent. When the response arrives, reprocess the "
                "payment from the clearing response stage. Do not re-send the pacs.008: that risks "
                "a duplicate credit to the beneficiary."
            ),
            summary=f"pacs.002 not received within {threshold:.0f}s",
            detail={
                "clearingReference": transaction.clearing_reference,
                "statusRequestMessageId": status_request.message_id,
                "elapsedSeconds": round(elapsed, 2),
                "thresholdSeconds": round(threshold, 2),
            },
        )
        self.investigations.add_action(
            investigation,
            actor="system",
            action="STATUS_REQUEST_SENT",
            note=f"pacs.028 {status_request.message_id} sent to the clearing system.",
        )
        self.set_status(
            payment, PaymentStatus.INVESTIGATION_REQUIRED, reason="Clearing timeout investigation"
        )
        self._skip_remaining(
            payment, StageKey.CLEARING_RESPONSE, "Not reached: awaiting the clearing system's answer"
        )

    # ------------------------------------------------------------------
    # post-clearing lifecycle
    # ------------------------------------------------------------------
    def continue_after_clearing(self, payment: Payment) -> None:
        scheme = get_scheme(payment.scheme)

        # --- settlement ---
        self._start(payment, StageKey.SETTLEMENT, "Settling across the settlement account")
        self.set_status(payment, PaymentStatus.SETTLEMENT_PENDING, reason="Settlement submitted")
        settlement = self.settlement.settle(payment, scheme)
        settlement_detail = {
            "settlementReference": settlement.transaction.settlement_reference,
            "status": settlement.status.value,
            "paymentAmount": str(settlement.transaction.payment_amount),
            "paymentCurrency": settlement.transaction.payment_currency,
            "settlementAmount": str(settlement.transaction.settlement_amount),
            "settlementCurrency": settlement.transaction.settlement_currency,
            "settlementMethod": settlement.transaction.settlement_method,
            "valueDate": settlement.transaction.value_date.isoformat()
            if settlement.transaction.value_date
            else None,
            "account": settlement.account.account_number if settlement.account else None,
            "accountType": scheme.settlement.settlement_account_type,
            "finality": scheme.clearing.settlement_finality,
            "anomaly": settlement.anomaly,
        }
        if settlement.status is SettlementStatus.FAILED:
            reason = settlement.failure_reason or "Settlement failed."
            self._fail(
                payment,
                StageKey.SETTLEMENT,
                StageState.FAILED,
                "Settlement rejected",
                reason,
                settlement_detail,
                settlement.transaction.iso_reason_code,
            )
            self.events.record(
                payment,
                EventType.SETTLEMENT_FAILED,
                SourceSystem.SETTLEMENT_ENGINE,
                f"Settlement {settlement.transaction.settlement_reference} failed: {reason}",
                severity=Severity.ERROR,
                stage=StageKey.SETTLEMENT,
                detail=settlement_detail,
            )
            payment.failure_summary = f"SETTLEMENT: {reason}"
            self.set_status(payment, PaymentStatus.SETTLEMENT_FAILED, reason=reason)
            self.investigations.open(
                payment,
                InvestigationReason.SETTLEMENT_FAILURE,
                actual=reason,
                probable_cause=(
                    "The clearing system accepted the instruction but settlement across the "
                    "settlement account did not complete. The beneficiary bank may already be "
                    "relying on the acceptance."
                ),
                recommended_action=(
                    "Check the settlement account position for the value date, resolve the "
                    "liquidity shortfall and resubmit settlement. If settlement cannot be "
                    "effected, send a camt.056 cancellation request."
                ),
                detail=settlement_detail,
            )
            self.set_status(
                payment, PaymentStatus.INVESTIGATION_REQUIRED, reason="Settlement failure"
            )
            self._skip_remaining(payment, StageKey.SETTLEMENT, "Not reached: settlement failed")
            return

        self.events.record(
            payment,
            EventType.SETTLEMENT_POSTED,
            SourceSystem.SETTLEMENT_ENGINE,
            (
                f"Settlement {settlement.transaction.settlement_reference} "
                f"{settlement.status.value} for {settlement.transaction.settlement_amount} "
                f"{settlement.transaction.settlement_currency}"
            ),
            severity=Severity.WARNING if settlement.anomaly else Severity.INFO,
            stage=StageKey.SETTLEMENT,
            detail=settlement_detail,
        )
        self._complete(
            payment,
            StageKey.SETTLEMENT,
            (
                f"{settlement.status.value}: {settlement.transaction.settlement_amount} "
                f"{settlement.transaction.settlement_currency} via "
                f"{settlement.transaction.settlement_method}"
            ),
            settlement_detail,
            state=StageState.COMPLETED
            if settlement.status is SettlementStatus.SETTLED
            else StageState.FAILED,
        )
        if settlement.status_update_suppressed:
            reason = (
                "The settlement engine recorded a completed settlement, but the status update "
                "never reached the payment engine, so the payment is still shown as pending."
            )
            self.events.record(
                payment,
                EventType.SETTLEMENT_POSTED,
                SourceSystem.SETTLEMENT_ENGINE,
                "Settlement completed but the internal status update was lost",
                severity=Severity.ERROR,
                stage=StageKey.SETTLEMENT,
                detail=settlement_detail,
            )
            payment.failure_summary = f"SETTLEMENT: {reason}"
            self.investigations.open(
                payment,
                InvestigationReason.SETTLEMENT_FAILURE,
                actual=reason,
                probable_cause=(
                    "A lost or unprocessed status callback between the settlement platform and "
                    "the payment engine. Value has moved but the payment engine does not know it."
                ),
                recommended_action=(
                    "Reconcile the settlement reference against the payment, then replay the "
                    "status update. Never re-settle: the money has already moved."
                ),
                title="Settled but internal status still pending",
                detail=settlement_detail,
            )
            self.set_status(
                payment,
                PaymentStatus.INVESTIGATION_REQUIRED,
                reason="Settlement status update lost",
            )
            self._skip_remaining(
                payment, StageKey.SETTLEMENT, "Not reached: internal status not updated"
            )
            return

        self.set_status(payment, PaymentStatus.SETTLED, reason="Settlement complete")

        # --- accounting ---
        self._start(payment, StageKey.ACCOUNTING, "Posting the double-entry journal")
        journal = self.accounting.post_payment_journal(
            payment, settlement_account=settlement.account
        )
        accounting_detail = {
            "accountingReference": journal.reference,
            "balanced": journal.balanced,
            "totalDebits": str(journal.total_debits),
            "totalCredits": str(journal.total_credits),
            "anomalies": journal.anomalies,
            "breakReason": journal.break_reason,
            "breakDetail": journal.break_detail,
            "entries": [
                {
                    "entryId": e.entry_id,
                    "side": e.side,
                    "accountNumber": e.account_number,
                    "accountName": e.account_name,
                    "accountType": e.account_type,
                    "amount": str(e.amount),
                    "currency": e.currency,
                    "status": e.status,
                    "postingDate": e.posting_date.isoformat() if e.posting_date else None,
                    "narrative": e.narrative,
                    "balanceAfter": str(e.balance_after) if e.balance_after is not None else None,
                }
                for e in journal.entries
            ],
        }
        self.events.record(
            payment,
            EventType.ACCOUNTING_POSTED,
            SourceSystem.ACCOUNTING_ENGINE,
            f"Journal {journal.reference} posted with {len(journal.entries)} entries",
            severity=Severity.ERROR if not journal.balanced else Severity.INFO,
            stage=StageKey.ACCOUNTING,
            detail={"accountingReference": journal.reference, "balanced": journal.balanced},
        )
        accounting_break = not journal.balanced
        if accounting_break:
            reason = journal.break_reason or "The accounting journal does not balance."
            self._fail(
                payment,
                StageKey.ACCOUNTING,
                StageState.FAILED,
                "Accounting break",
                reason,
                accounting_detail,
                "AM09",
            )
            self.events.record(
                payment,
                EventType.ACCOUNTING_BREAK,
                SourceSystem.ACCOUNTING_ENGINE,
                reason,
                severity=Severity.ERROR,
                stage=StageKey.ACCOUNTING,
                detail=accounting_detail,
            )
            payment.failure_summary = f"ACCOUNTING: {reason}"
            self.set_status(payment, PaymentStatus.ACCOUNTING_BREAK, reason=reason)
        else:
            self._complete(
                payment,
                StageKey.ACCOUNTING,
                f"Journal {journal.reference}: {journal.total_debits} debited, {journal.total_credits} credited",
                accounting_detail,
            )
            self.set_status(payment, PaymentStatus.ACCOUNTED, reason="Journal posted")

        # --- statement notification (camt.054) ---
        # An account servicer only notifies a movement it has actually booked.
        # If the customer debit was left pending, there is nothing to notify, and
        # reconciliation will correctly report a missing statement entry.
        debit_account = payment.debtor_account
        debit_posted = any(
            e.side == EntrySide.DEBIT.value and e.status == AccountingStatus.POSTED.value
            for e in journal.entries
        )
        if debit_account is not None and not debit_posted:
            self.events.record(
                payment,
                EventType.ACCOUNTING_BREAK,
                SourceSystem.ACCOUNTING_ENGINE,
                (
                    "No camt.054 notification: the customer debit was never booked, so the "
                    "account servicer has no movement to report."
                ),
                severity=Severity.ERROR,
                stage=StageKey.ACCOUNTING,
                detail={"accountNumber": debit_account.account_number},
            )
        if debit_account is not None and debit_posted:
            statement_entries, recon_injections = self.statements.publish(
                payment,
                debit_account,
                amount=payment.amount,
                currency=payment.currency,
                side=EntrySide.DEBIT,
                narrative=(
                    f"Payment {payment.reference} to "
                    f"{payment.creditor.name if payment.creditor else 'beneficiary'}"
                ),
            )
            for entry in statement_entries:
                if entry.is_orphan:
                    continue
                notification = self.messages.receive_camt054(
                    payment,
                    scheme,
                    debit_account,
                    side=entry.side,
                    entry_amount=entry.amount,
                    entry_currency=entry.currency,
                    booking_date=entry.booking_date or utcnow().date(),
                    value_date=entry.value_date or utcnow().date(),
                    statement_reference=entry.statement_reference,
                    narrative=entry.narrative,
                )
                entry.source_message_id = notification.message_id
                self.events.record(
                    payment,
                    EventType.MESSAGE_RECEIVED,
                    SourceSystem.ACCOUNTING_ENGINE,
                    f"camt.054 {notification.message_id} notifies entry {entry.statement_reference}",
                    stage=StageKey.ACCOUNTING,
                    detail={
                        "messageId": notification.message_id,
                        "statementReference": entry.statement_reference,
                        "amount": str(entry.amount),
                        "currency": entry.currency,
                    },
                )
            if "RECON_MISSING_CAMT054" in recon_injections:
                self.events.record(
                    payment,
                    EventType.FAILURE_INJECTED,
                    SourceSystem.QA_LAB,
                    "camt.054 notification suppressed: no statement entry will exist for this payment",
                    severity=Severity.WARNING,
                    stage=StageKey.ACCOUNTING,
                    detail={"injection": "RECON_MISSING_CAMT054"},
                )
            self.session.flush()

        # --- reconciliation ---
        self._start(payment, StageKey.RECONCILIATION, "Reconciling internal, clearing and statement records")
        outcome = self.reconciliation.reconcile_payment(payment)
        recon_detail = {
            "reference": outcome.record.reference,
            "status": outcome.status.value,
            "legs": outcome.record.legs,
            "differenceAmount": str(outcome.record.difference_amount)
            if outcome.record.difference_amount is not None
            else None,
            "probableCause": outcome.record.probable_cause,
            "recommendedAction": outcome.record.recommended_action,
            **(outcome.record.detail or {}),
        }
        self.events.record(
            payment,
            EventType.RECONCILIATION_RUN,
            SourceSystem.RECONCILIATION_ENGINE,
            f"Reconciliation {outcome.record.reference}: {outcome.status.value}",
            severity=Severity.ERROR if outcome.is_break else Severity.INFO,
            stage=StageKey.RECONCILIATION,
            detail={"reference": outcome.record.reference, "status": outcome.status.value},
        )
        if outcome.is_break:
            self._fail(
                payment,
                StageKey.RECONCILIATION,
                StageState.FAILED,
                f"Reconciliation break: {outcome.status.value}",
                outcome.record.probable_cause,
                recon_detail,
            )
            self.events.record(
                payment,
                EventType.RECONCILIATION_BREAK,
                SourceSystem.RECONCILIATION_ENGINE,
                f"{outcome.status.value}: {outcome.record.probable_cause}",
                severity=Severity.ERROR,
                stage=StageKey.RECONCILIATION,
                detail=recon_detail,
            )
            payment.failure_summary = (
                f"RECONCILIATION: {outcome.status.value} - {outcome.record.probable_cause}"
            )
            target = (
                PaymentStatus.RECONCILIATION_BREAK
                if payment.status != PaymentStatus.ACCOUNTING_BREAK.value
                else PaymentStatus.RECONCILIATION_BREAK
            )
            self.set_status(payment, target, reason=outcome.status.value, force=True)
            self.investigations.open(
                payment,
                InvestigationReason.ACCOUNTING_BREAK
                if accounting_break
                else InvestigationReason.RECONCILIATION_BREAK,
                actual=(
                    f"Reconciliation classified the payment as {outcome.status.value}."
                    + (
                        f" Difference {outcome.record.difference_amount} {payment.currency}."
                        if outcome.record.difference_amount
                        else ""
                    )
                ),
                probable_cause=outcome.record.probable_cause,
                recommended_action=outcome.record.recommended_action,
                summary=f"{outcome.status.value} on {payment.reference}",
                reconciliation_record=outcome.record,
                detail=recon_detail,
            )
            self.set_status(
                payment,
                PaymentStatus.INVESTIGATION_REQUIRED,
                reason="Reconciliation break investigation",
                force=True,
            )
            self._stage(payment, StageKey.COMPLETION).state = StageState.INVESTIGATION_REQUIRED.value
            self._stage(payment, StageKey.COMPLETION).summary = (
                "Payment cannot be closed while the reconciliation break is open"
            )
            self.session.flush()
            self._post_completion_hooks(payment)
            return

        self._complete(
            payment,
            StageKey.RECONCILIATION,
            "MATCHED across internal, accounting, clearing and statement records",
            recon_detail,
        )

        if accounting_break:
            # Reconciliation agreed, but the ledger did not. The payment cannot be
            # closed on the strength of a match that the journal contradicts.
            self.investigations.open(
                payment,
                InvestigationReason.ACCOUNTING_BREAK,
                actual=journal.break_reason or "The accounting journal does not balance.",
                probable_cause=(
                    "Reconciliation matched the external records, but the internal journal is "
                    "inconsistent. The difference is inside the bank, not with the counterparty."
                ),
                recommended_action=(
                    "Correct the journal before closing the payment. Do not rely on the "
                    "reconciliation match: it compares the statement, not the ledger's internal "
                    "integrity."
                ),
                detail=accounting_detail,
            )
            self.set_status(
                payment,
                PaymentStatus.INVESTIGATION_REQUIRED,
                reason="Accounting break outstanding despite a reconciliation match",
                force=True,
            )
            completion = self._stage(payment, StageKey.COMPLETION)
            completion.state = StageState.INVESTIGATION_REQUIRED.value
            completion.summary = "Payment cannot be closed while the accounting break is open"
            self.session.flush()
            self._post_completion_hooks(payment)
            return

        self.set_status(payment, PaymentStatus.RECONCILED, reason="Reconciliation matched")

        # --- completion ---
        self._start(payment, StageKey.COMPLETION, "Closing the payment")
        self._complete(
            payment,
            StageKey.COMPLETION,
            "Payment completed end to end",
            {
                "completedAt": utcnow().isoformat(),
                "clearingReference": (self.clearing.latest(payment.id).clearing_reference
                                      if self.clearing.latest(payment.id) else None),
                "settlementReference": settlement.transaction.settlement_reference,
                "accountingReference": journal.reference,
                "reconciliationReference": outcome.record.reference,
            },
        )
        self.set_status(payment, PaymentStatus.COMPLETED, reason="Lifecycle complete")
        self._post_completion_hooks(payment)

    def _post_completion_hooks(self, payment: Payment) -> None:
        """Injections that only make sense once the payment has finished."""
        if self.injections.has_active(payment.id, "BENEFICIARY_RETURN"):
            injection = next(
                i for i in self.injections.active_for(payment.id) if i.code == "BENEFICIARY_RETURN"
            )
            if not injection.consumed:
                injection.consumed = True
                injection.effect_summary = "Beneficiary bank returned the payment."
                self.session.flush()
                self.apply_return(
                    payment,
                    reason_code=str((injection.parameters or {}).get("reasonCode", "AC04")),
                    narrative="Beneficiary account closed; funds returned by the beneficiary bank.",
                )
        if self.injections.has_active(payment.id, "BENEFICIARY_NOT_CREDITED"):
            injection = next(
                i
                for i in self.injections.active_for(payment.id)
                if i.code == "BENEFICIARY_NOT_CREDITED"
            )
            if not injection.consumed:
                injection.consumed = True
                injection.effect_summary = (
                    "Customer claim raised: beneficiary never received the funds."
                )
                self.session.flush()
                self.raise_beneficiary_claim(payment)

    # ------------------------------------------------------------------
    # operator actions
    # ------------------------------------------------------------------
    def retry(
        self,
        payment: Payment,
        *,
        reason: str,
        actor: str = "payments.operations",
        mode: ProcessingMode | None = None,
    ) -> ExecutionResult:
        """Controlled reprocessing.

        A failed payment never becomes successful by itself. Reprocessing is
        only allowed from states the state machine permits, the attempt is
        recorded, and the lifecycle re-runs for real.
        """
        current = PaymentStatus(payment.status)
        before = {"status": current.value, "retryCount": payment.retry_count}
        assert_transition(current, PaymentStatus.REPROCESSING)
        self.set_status(payment, PaymentStatus.REPROCESSING, reason=reason)
        payment.retry_count += 1
        payment.failure_summary = None
        self.events.record(
            payment,
            EventType.RETRY_REQUESTED,
            SourceSystem.INVESTIGATION_DESK,
            f"Reprocessing attempt {payment.retry_count}: {reason}",
            severity=Severity.WARNING,
            detail={"previousStatus": current.value, "attempt": payment.retry_count},
        )
        self.events.audit(
            actor=actor,
            action="RETRY",
            entity_type="Payment",
            entity_id=payment.reference,
            reason=reason,
            before=before,
            after={"status": PaymentStatus.REPROCESSING.value, "retryCount": payment.retry_count},
            correlation_id=payment.correlation_id,
        )
        for investigation in self.investigations.open_for_payment(payment.id):
            if investigation.status in ("OPEN", "IN_PROGRESS", "AWAITING_RESPONSE"):
                self.investigations.add_action(
                    investigation,
                    actor=actor,
                    action="REPROCESS_TRIGGERED",
                    note=f"Reprocessing attempt {payment.retry_count}: {reason}",
                )

        # Reset the stages that will run again. Reprocessing always restarts at
        # validation: the data may have been corrected since, and re-running the
        # checks is the point.
        restart_from = StageKey.PRE_VALIDATION
        reached = False
        for key in STAGE_ORDER:
            if key == restart_from:
                reached = True
            if reached:
                stage = self._stage(payment, key)
                stage.state = StageState.PENDING.value
                stage.started_at = None
                stage.completed_at = None
                stage.duration_ms = None
                stage.failure_reason = None
                stage.summary = ""
                stage.detail = {}
        self.session.flush()
        self.set_status(payment, PaymentStatus.VALIDATING, reason="Reprocessing: validation restart")
        payment.status = PaymentStatus.INITIATED.value  # execute() will drive it forward again
        self.session.flush()
        return self.execute(payment, mode=mode)

    def resolve_timeout_with_response(
        self,
        payment: Payment,
        *,
        accepted: bool,
        reason_code: str | None = None,
        actor: str = "payments.operations",
    ) -> None:
        """The clearing system finally answers the pacs.028 status request."""
        scheme = get_scheme(payment.scheme)
        transaction = self.clearing.latest(payment.id)
        if transaction is None:
            raise LookupError("No clearing transaction to resolve")
        pacs002 = self.messages.receive_pacs002(
            payment,
            scheme,
            transaction.request_message_id or "",
            accepted=accepted,
            reason_code=reason_code,
            status_code="ACSC" if accepted else "RJCT",
            clearing_reference=transaction.clearing_reference,
        )
        transaction.status = (
            ClearingStatus.ACCEPTED.value if accepted else ClearingStatus.REJECTED.value
        )
        transaction.decision = (
            ClearingDecision.ACCEPT.value if accepted else ClearingDecision.REJECT.value
        )
        transaction.responded_at = utcnow()
        transaction.response_count += 1
        transaction.response_message_id = pacs002.message_id
        transaction.status_reason_code = None if accepted else reason_code
        self.session.flush()
        self.events.record(
            payment,
            EventType.CLEARING_RESPONSE,
            SourceSystem.CLEARING_SYSTEM,
            f"Investigation response received: {'ACSC' if accepted else 'RJCT'}",
            severity=Severity.INFO if accepted else Severity.ERROR,
            stage=StageKey.CLEARING_RESPONSE,
            detail={"messageId": pacs002.message_id, "accepted": accepted, "reasonCode": reason_code},
        )
        # The status request has been answered, so the question the investigation
        # was opened to ask is now settled. Close it with the outcome rather than
        # leaving an open case on a payment that has moved on.
        open_states = ("OPEN", "IN_PROGRESS", "AWAITING_RESPONSE")
        for investigation in self.investigations.open_for_payment(payment.id):
            if (
                investigation.reason == InvestigationReason.CLEARING_TIMEOUT.value
                and investigation.status in open_states
            ):
                self.investigations.add_action(
                    investigation,
                    actor=actor,
                    action="RESPONSE_RECEIVED",
                    note=(
                        f"Clearing system confirmed {'acceptance' if accepted else 'rejection'} "
                        f"via {pacs002.message_id}."
                    ),
                )
                self.investigations.resolve(
                    investigation,
                    resolution=(
                        "The clearing system confirmed the payment was accepted; the lifecycle "
                        "continued from settlement."
                        if accepted
                        else (
                            f"The clearing system confirmed the payment was rejected with "
                            f"{reason_code}; any customer debit has been reversed."
                        )
                    ),
                    actor=actor,
                )

        if accepted:
            self._complete(
                payment,
                StageKey.CLEARING_RESPONSE,
                "pacs.002 ACSC received following the status request",
                {
                    "messageId": pacs002.message_id,
                    "clearingReference": transaction.clearing_reference,
                    "resolvedByInvestigation": True,
                },
            )
            # The timeout is no longer this payment's state: it recovered.
            payment.failure_summary = None
            self.set_status(
                payment, PaymentStatus.CLEARING_ACCEPTED, reason="Status request resolved", force=True
            )
            self.continue_after_clearing(payment)
        else:
            self._fail(
                payment,
                StageKey.CLEARING_RESPONSE,
                StageState.REJECTED,
                f"pacs.002 RJCT / {reason_code} received following the status request",
                f"Rejected by the clearing system with {reason_code}.",
                {"messageId": pacs002.message_id},
                reason_code,
            )
            # The payment did fail, but for a different reason than the timeout:
            # it was rejected, and we now know it.
            payment.failure_summary = (
                f"CLEARING_RESPONSE: RJCT {reason_code} confirmed following the status request"
            )
            self.set_status(
                payment,
                PaymentStatus.CLEARING_REJECTED,
                reason=f"Status request resolved: RJCT {reason_code}",
                force=True,
            )
            self._reverse_customer_debit_if_any(payment, f"Clearing rejection {reason_code}")

    def request_cancellation(
        self,
        payment: Payment,
        *,
        reason_code: str = "CUST",
        narrative: str = "",
        actor: str = "payments.operations",
        auto_resolve: bool = True,
    ) -> tuple[PaymentMessage, PaymentMessage | None]:
        scheme = get_scheme(payment.scheme)
        if not scheme.rules.supports_cancellation:
            raise ValueError(f"{scheme.short_name} does not support cancellation requests")
        original = self.messages.latest(payment.id, MessageType.PACS_008)
        camt056 = self.messages.send_camt056(
            payment,
            scheme,
            original.message_id if original else "",
            cancellation_reason_code=reason_code,
            additional_information=narrative or None,
        )
        self.events.record(
            payment,
            EventType.CANCELLATION_REQUESTED,
            SourceSystem.INVESTIGATION_DESK,
            f"camt.056 {camt056.message_id} sent with reason {reason_code}",
            severity=Severity.WARNING,
            detail={"messageId": camt056.message_id, "reasonCode": reason_code},
        )
        self.events.audit(
            actor=actor,
            action="CANCELLATION_REQUESTED",
            entity_type="Payment",
            entity_id=payment.reference,
            reason=narrative or reason_code,
            before={"status": payment.status},
            after={"cancellationMessageId": camt056.message_id},
            correlation_id=payment.correlation_id,
        )
        investigation = self.investigations.open(
            payment,
            InvestigationReason.CANCELLATION_REQUEST,
            actual=f"camt.056 sent with reason {reason_code}.",
            probable_cause=narrative or "Cancellation requested by the operator.",
            recommended_action=(
                "Await the camt.029 resolution. A cancellation request is not a guarantee: the "
                "beneficiary bank decides whether the funds can be recalled."
            ),
            detail={"cancellationMessageId": camt056.message_id, "reasonCode": reason_code},
        )
        self.investigations.add_action(
            investigation,
            actor=actor,
            action="CANCELLATION_SENT",
            note=f"camt.056 {camt056.message_id} dispatched.",
        )
        camt029: PaymentMessage | None = None
        if auto_resolve:
            # Whether a recall can succeed depends on whether value has already
            # moved, not on our own status label: once the payment has settled
            # the beneficiary bank is entitled to refuse the recall.
            settled = self.settlement.latest(payment.id)
            value_has_moved = settled is not None and settled.status in (
                SettlementStatus.SETTLED.value,
                SettlementStatus.PARTIALLY_SETTLED.value,
            )
            resolution = "RJCR" if value_has_moved else "CNCL"
            camt029 = self.messages.receive_camt029(
                payment,
                scheme,
                camt056.message_id,
                resolution_status=resolution,
                reason_code=reason_code if resolution == "CNCL" else "NARR",
                narrative=(
                    "Payment stopped before the beneficiary was credited."
                    if resolution == "CNCL"
                    else "Funds already made available to the beneficiary; recall refused."
                ),
            )
            self.events.record(
                payment,
                EventType.MESSAGE_RECEIVED,
                SourceSystem.CLEARING_SYSTEM,
                f"camt.029 {camt029.message_id} resolution {resolution}",
                stage=StageKey.CLEARING_RESPONSE,
                detail={"messageId": camt029.message_id, "resolution": resolution},
            )
            if resolution == "CNCL":
                self.set_status(
                    payment, PaymentStatus.CANCELLED, reason="Cancellation accepted", force=True
                )
                self._reverse_customer_debit_if_any(payment, "Payment cancelled on request")
                self.investigations.resolve(
                    investigation,
                    resolution="Cancellation accepted; payment cancelled and entries reversed.",
                    actor=actor,
                )
            else:
                self.investigations.add_action(
                    investigation,
                    actor="system",
                    action="CANCELLATION_REFUSED",
                    note="camt.029 RJCR: the beneficiary bank refused the recall.",
                )
        return camt056, camt029

    def apply_return(
        self,
        payment: Payment,
        *,
        reason_code: str = "AC04",
        narrative: str = "",
        returned_amount: Decimal | None = None,
        charges: Decimal | None = None,
        actor: str = "clearing.system",
    ) -> PaymentMessage:
        scheme = get_scheme(payment.scheme)
        original = self.messages.latest(payment.id, MessageType.PACS_008)
        pacs004 = self.messages.receive_pacs004(
            payment,
            scheme,
            original.message_id if original else "",
            return_reason_code=reason_code,
            return_reason_text=narrative or None,
            returned_amount=returned_amount,
            charges=charges,
        )
        self.events.record(
            payment,
            EventType.PAYMENT_RETURNED,
            SourceSystem.CLEARING_SYSTEM,
            f"pacs.004 {pacs004.message_id} received with reason {reason_code}",
            severity=Severity.WARNING,
            detail={"messageId": pacs004.message_id, "reasonCode": reason_code},
        )
        reversal = self.accounting.reverse_journal(payment, f"Return {reason_code}")
        self.settlement.reverse(payment, f"Return {reason_code}")
        self.events.record(
            payment,
            EventType.ACCOUNTING_POSTED,
            SourceSystem.ACCOUNTING_ENGINE,
            f"Journal {reversal.reference} reverses the original postings",
            detail={"accountingReference": reversal.reference, "entries": len(reversal.entries)},
        )
        self.set_status(payment, PaymentStatus.RETURNED, reason=f"Returned: {reason_code}", force=True)
        payment.failure_summary = (
            f"RETURN: pacs.004 {reason_code} - {narrative or 'returned by the beneficiary bank'}"
        )
        stage = self._stage(payment, StageKey.COMPLETION)
        stage.state = StageState.REVERSED.value
        stage.summary = f"Returned by the beneficiary bank ({reason_code})"
        stage.detail = {
            "returnMessageId": pacs004.message_id,
            "reasonCode": reason_code,
            "reversalReference": reversal.reference,
        }
        self.session.flush()
        self.events.audit(
            actor=actor,
            action="RETURN_APPLIED",
            entity_type="Payment",
            entity_id=payment.reference,
            reason=narrative or reason_code,
            before={"status": payment.previous_status},
            after={"status": payment.status, "returnMessageId": pacs004.message_id},
            correlation_id=payment.correlation_id,
        )
        return pacs004

    def raise_beneficiary_claim(self, payment: Payment) -> None:
        investigation = self.investigations.open(
            payment,
            InvestigationReason.BENEFICIARY_NOT_CREDITED,
            actual=(
                "The customer reports the beneficiary has not received the funds, although the "
                "clearing system accepted the payment and our side settled."
            ),
            probable_cause=(
                "The funds may be sitting in the beneficiary bank's suspense account because of a "
                "name/account mismatch, or have been applied to the wrong account. Our records "
                "show the payment as complete, so the problem is beyond our leg of the chain."
            ),
            recommended_action=(
                "Send a camt.056 cancellation request, or an operational enquiry, to the "
                "beneficiary bank quoting the clearing reference and the end-to-end id. Do not "
                "reverse the customer debit until the beneficiary bank confirms the funds are "
                "recoverable."
            ),
        )
        self.set_status(
            payment,
            PaymentStatus.INVESTIGATION_REQUIRED,
            reason="Beneficiary not credited",
            force=True,
        )
        camt056, camt029 = self.request_cancellation(
            payment,
            reason_code="CUTA",
            narrative="Customer claim: beneficiary not credited.",
            auto_resolve=True,
        )
        self.investigations.add_action(
            investigation,
            actor="payments.operations",
            action="ENQUIRY_SENT",
            note=f"camt.056 {camt056.message_id} sent to the beneficiary bank.",
        )
        if camt029 is not None:
            self.investigations.add_action(
                investigation,
                actor="system",
                action="RESPONSE_RECEIVED",
                note=f"camt.029 {camt029.message_id} received from the beneficiary bank.",
            )

    def _reverse_customer_debit_if_any(self, payment: Payment, reason: str) -> None:
        entries = self.accounting.entries_for_payment(payment.id)
        posted = [e for e in entries if e.status == AccountingStatus.POSTED.value]
        if not posted:
            return
        reversal = self.accounting.reverse_journal(payment, reason)
        self.events.record(
            payment,
            EventType.ACCOUNTING_POSTED,
            SourceSystem.ACCOUNTING_ENGINE,
            f"Journal {reversal.reference} reverses the customer debit: {reason}",
            severity=Severity.WARNING,
            stage=StageKey.ACCOUNTING,
            detail={"accountingReference": reversal.reference, "reason": reason},
        )

    # ------------------------------------------------------------------
    # scheduling
    # ------------------------------------------------------------------
    def _schedule(self, job_type: str, payment: Payment, *, due_at, payload: dict) -> ScheduledJob:  # noqa: ANN001
        job = ScheduledJob(
            job_type=job_type,
            payment_id=payment.id,
            correlation_id=payment.correlation_id,
            due_at=due_at,
            payload=payload,
        )
        self.session.add(job)
        self.session.flush()
        return job

    def run_job(self, job: ScheduledJob) -> None:
        payment = self.session.get(Payment, job.payment_id) if job.payment_id else None
        if payment is None:
            return
        transaction_id = (job.payload or {}).get("clearingTransactionId")
        transaction = (
            self.session.get(ClearingTransaction, transaction_id) if transaction_id else None
        )
        if transaction is None:
            transaction = self.clearing.latest(payment.id)
        if transaction is None:
            return
        if job.job_type == JOB_CLEARING_RESPONSE:
            self.deliver_clearing_response(payment, transaction)
        elif job.job_type == JOB_CLEARING_TIMEOUT:
            self.handle_clearing_timeout(payment, transaction)

    def pending_jobs(self, payment_id: int) -> list[ScheduledJob]:
        return list(
            self.session.execute(
                select(ScheduledJob)
                .where(ScheduledJob.payment_id == payment_id, ScheduledJob.status == "PENDING")
                .order_by(ScheduledJob.due_at.asc())
            ).scalars()
        )


def _stage_owner(key: StageKey) -> SourceSystem:
    return {
        StageKey.INITIATION: SourceSystem.CHANNEL,
        StageKey.CHANNEL_INTAKE: SourceSystem.CHANNEL,
        StageKey.PRE_VALIDATION: SourceSystem.VALIDATION_ENGINE,
        StageKey.BUSINESS_VALIDATION: SourceSystem.VALIDATION_ENGINE,
        StageKey.COMPLIANCE: SourceSystem.COMPLIANCE_ENGINE,
        StageKey.ORCHESTRATION: SourceSystem.ORCHESTRATOR,
        StageKey.MESSAGE_GENERATION: SourceSystem.MESSAGE_ENGINE,
        StageKey.CLEARING: SourceSystem.CLEARING_ADAPTER,
        StageKey.CLEARING_RESPONSE: SourceSystem.CLEARING_SYSTEM,
        StageKey.SETTLEMENT: SourceSystem.SETTLEMENT_ENGINE,
        StageKey.ACCOUNTING: SourceSystem.ACCOUNTING_ENGINE,
        StageKey.RECONCILIATION: SourceSystem.RECONCILIATION_ENGINE,
        StageKey.COMPLETION: SourceSystem.ORCHESTRATOR,
    }[key]


def _validation_dict(result) -> dict:  # noqa: ANN001
    return {
        "ruleId": result.rule_id,
        "ruleName": result.rule_name,
        "category": result.category,
        "severity": result.severity,
        "status": result.status,
        "stage": result.stage,
        "message": result.message,
        "field": result.field,
        "actualValue": result.actual_value,
        "expectedValue": result.expected_value,
        "isoReasonCode": result.iso_reason_code,
        "remediation": result.remediation,
        "durationMs": result.duration_ms,
    }


__all__ = [
    "ExecutionResult",
    "IllegalTransitionError",
    "JOB_CLEARING_RESPONSE",
    "JOB_CLEARING_TIMEOUT",
    "JOB_POST_COMPLETION",
    "PaymentOrchestrator",
]
