"""Clearing adapter and simulated clearing system.

    Payment engine -> ClearingAdapter -> SimulatedClearingSystem -> pacs.002

The adapter is the only component the orchestrator talks to. It knows nothing
about *why* the clearing system behaves the way it does; the simulated clearing
system decides, deterministically, based on the scheme profile and on any
failure injection the QA Lab has registered for the payment.

SIMULATION BEHAVIOUR: a real adapter would speak a network protocol with mutual
authentication, message signing and store-and-forward semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.identifiers import clearing_reference, utcnow
from app.core.logging import get_logger
from app.db.models import ClearingTransaction, FailureInjection, Payment
from app.domain.enums import ClearingDecision, ClearingStatus, FailureCategory
from app.schemes.base import PaymentScheme
from app.schemes.registry import clearing_response_seconds, clearing_timeout_seconds

logger = get_logger(__name__)

# Failure-injection code -> clearing behaviour
INJECTION_TO_DECISION: dict[str, ClearingDecision] = {
    "CLEARING_REJECT_BUSINESS": ClearingDecision.BUSINESS_ERROR,
    "CLEARING_REJECT_TECHNICAL": ClearingDecision.TECHNICAL_ERROR,
    "CLEARING_TIMEOUT": ClearingDecision.TIMEOUT,
    "CLEARING_DELAY": ClearingDecision.DELAY,
    "CLEARING_UNAVAILABLE": ClearingDecision.UNAVAILABLE,
    "CLEARING_DUPLICATE_RESPONSE": ClearingDecision.DUPLICATE_RESPONSE,
    "CLEARING_MALFORMED_RESPONSE": ClearingDecision.MALFORMED_RESPONSE,
}

DECISION_REASONS: dict[ClearingDecision, tuple[str, str]] = {
    ClearingDecision.BUSINESS_ERROR: (
        "AC01",
        "Creditor account identification is unknown at the beneficiary institution.",
    ),
    ClearingDecision.TECHNICAL_ERROR: (
        "FF01",
        "The instruction failed technical validation at the clearing system.",
    ),
    ClearingDecision.REJECT: ("NARR", "Rejected by the clearing system."),
    ClearingDecision.UNAVAILABLE: (
        "TECH",
        "The clearing system is not available; the instruction was not accepted for processing.",
    ),
}


@dataclass(slots=True)
class ClearingDispatch:
    transaction: ClearingTransaction
    decision: ClearingDecision
    response_delay_seconds: float
    timeout_seconds: float
    will_respond: bool


@dataclass(slots=True)
class ClearingResponse:
    accepted: bool
    decision: ClearingDecision
    reason_code: str | None
    reason_text: str | None
    status_code: str
    malformed: bool
    duplicate: bool


class SimulatedClearingSystem:
    """Deterministic decision engine for the simulated rail."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def active_injection(self, payment: Payment) -> FailureInjection | None:
        rows = self.session.execute(
            select(FailureInjection)
            .where(
                FailureInjection.payment_id == payment.id,
                FailureInjection.active.is_(True),
                FailureInjection.consumed.is_(False),
                FailureInjection.category.in_(
                    (FailureCategory.CLEARING.value, FailureCategory.TIMEOUT.value)
                ),
            )
            .order_by(FailureInjection.created_at.asc())
        ).scalars()
        for row in rows:
            if row.code in INJECTION_TO_DECISION:
                return row
        return None

    def decide(self, payment: Payment, scheme: PaymentScheme) -> tuple[ClearingDecision, dict]:
        injection = self.active_injection(payment)
        if injection is not None:
            decision = INJECTION_TO_DECISION[injection.code]
            params = dict(injection.parameters or {})
            injection.consumed = True
            injection.effect_summary = (
                f"Clearing system instructed to respond {decision.value} for {payment.reference}."
            )
            self.session.flush()
            return decision, params
        return ClearingDecision.ACCEPT, {}

    def response_for(
        self, decision: ClearingDecision, scheme: PaymentScheme, params: dict
    ) -> ClearingResponse:
        if decision in (ClearingDecision.ACCEPT, ClearingDecision.DELAY):
            return ClearingResponse(
                accepted=True,
                decision=decision,
                reason_code=None,
                reason_text=None,
                status_code="ACSC",
                malformed=False,
                duplicate=False,
            )
        if decision is ClearingDecision.DUPLICATE_RESPONSE:
            return ClearingResponse(
                accepted=True,
                decision=decision,
                reason_code=None,
                reason_text=None,
                status_code="ACSC",
                malformed=False,
                duplicate=True,
            )
        if decision is ClearingDecision.MALFORMED_RESPONSE:
            return ClearingResponse(
                accepted=True,
                decision=decision,
                reason_code=None,
                reason_text=None,
                status_code="ACSC",
                malformed=True,
                duplicate=False,
            )
        default_code, default_text = DECISION_REASONS.get(
            decision, ("NARR", "Rejected by the clearing system.")
        )
        code = str(params.get("reasonCode") or default_code)
        if code not in scheme.clearing.rejection_reason_codes and code != default_code:
            logger.info(
                "reason code not in scheme list; using it anyway",
                extra={"reason_code": code, "scheme": scheme.code.value},
            )
        return ClearingResponse(
            accepted=False,
            decision=decision,
            reason_code=code,
            reason_text=str(params.get("reasonText") or default_text),
            status_code="RJCT",
            malformed=False,
            duplicate=False,
        )


class ClearingAdapter:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.system = SimulatedClearingSystem(session)

    def dispatch(
        self,
        payment: Payment,
        scheme: PaymentScheme,
        *,
        request_message_id: str,
        accelerated: bool = True,
        attempt: int = 1,
    ) -> ClearingDispatch:
        decision, params = self.system.decide(payment, scheme)
        now = utcnow()
        response_delay = float(
            params.get("responseDelaySeconds", clearing_response_seconds(scheme, accelerated))
        )
        timeout = float(params.get("timeoutSeconds", clearing_timeout_seconds(scheme, accelerated)))

        if decision is ClearingDecision.DELAY:
            # A delayed but valid response: arrives late, still inside the window
            # unless the caller overrides the multiplier.
            response_delay = float(params.get("responseDelaySeconds", timeout * 0.8))
        if decision is ClearingDecision.TIMEOUT:
            response_delay = timeout + 1.0

        will_respond = decision not in (ClearingDecision.TIMEOUT, ClearingDecision.UNAVAILABLE)

        reference = clearing_reference(payment.scheme)
        txn = ClearingTransaction(
            payment_id=payment.id,
            clearing_reference=reference,
            clearing_system=scheme.clearing.clearing_system_name,
            scheme=payment.scheme,
            status=(
                ClearingStatus.UNAVAILABLE.value
                if decision is ClearingDecision.UNAVAILABLE
                else ClearingStatus.AWAITING_RESPONSE.value
            ),
            requested_decision=decision.value,
            amount=payment.amount,
            currency=payment.currency,
            sent_at=now,
            response_due_at=now + timedelta(seconds=response_delay) if will_respond else None,
            timeout_at=now + timedelta(seconds=timeout),
            attempt=attempt,
            request_message_id=request_message_id,
            detail={
                "decision": decision.value,
                "responseDelaySeconds": round(response_delay, 3),
                "timeoutSeconds": round(timeout, 3),
                "realisticTimeoutSeconds": scheme.clearing.realistic_timeout_seconds,
                "accelerated": accelerated,
                "operatingHours": scheme.clearing.operating_hours,
                "injectedParameters": params,
            },
        )
        if decision is ClearingDecision.UNAVAILABLE:
            code, text = DECISION_REASONS[ClearingDecision.UNAVAILABLE]
            txn.status_reason_code = code
            txn.status_reason = text
            txn.decision = decision.value
        self.session.add(txn)
        self.session.flush()
        logger.info(
            "dispatched to clearing",
            extra={
                "payment_reference": payment.reference,
                "clearing_reference": reference,
                "decision": decision.value,
                "response_delay_seconds": round(response_delay, 3),
                "timeout_seconds": round(timeout, 3),
            },
        )
        return ClearingDispatch(
            transaction=txn,
            decision=decision,
            response_delay_seconds=response_delay,
            timeout_seconds=timeout,
            will_respond=will_respond,
        )

    def build_response(
        self, transaction: ClearingTransaction, scheme: PaymentScheme
    ) -> ClearingResponse:
        decision = ClearingDecision(transaction.requested_decision or ClearingDecision.ACCEPT.value)
        params = dict((transaction.detail or {}).get("injectedParameters") or {})
        return self.system.response_for(decision, scheme, params)

    def record_response(
        self,
        transaction: ClearingTransaction,
        response: ClearingResponse,
        *,
        response_message_id: str,
    ) -> None:
        now = utcnow()
        transaction.responded_at = now
        transaction.response_count += 1
        transaction.decision = response.decision.value
        transaction.response_message_id = response_message_id
        if transaction.sent_at:
            transaction.response_latency_ms = int((now - transaction.sent_at).total_seconds() * 1000)
        if response.malformed:
            transaction.status = ClearingStatus.AWAITING_RESPONSE.value
            transaction.status_reason_code = "FF01"
            transaction.status_reason = (
                "A status report arrived but could not be matched: the original end-to-end "
                "identification is missing."
            )
        elif response.accepted:
            transaction.status = ClearingStatus.ACCEPTED.value
            transaction.status_reason_code = None
            transaction.status_reason = None
        else:
            transaction.status = ClearingStatus.REJECTED.value
            transaction.status_reason_code = response.reason_code
            transaction.status_reason = response.reason_text
        self.session.flush()

    def record_timeout(self, transaction: ClearingTransaction, elapsed_seconds: float) -> None:
        transaction.status = ClearingStatus.TIMED_OUT.value
        transaction.decision = ClearingDecision.TIMEOUT.value
        transaction.status_reason_code = "TECH"
        transaction.status_reason = (
            f"No status report received within the {transaction.detail.get('timeoutSeconds', '?')}s "
            f"window (waited {elapsed_seconds:.1f}s)."
        )
        self.session.flush()

    def latest(self, payment_id: int) -> ClearingTransaction | None:
        return self.session.execute(
            select(ClearingTransaction)
            .where(ClearingTransaction.payment_id == payment_id)
            .order_by(ClearingTransaction.attempt.desc(), ClearingTransaction.id.desc())
            .limit(1)
        ).scalar_one_or_none()

    def all_for_payment(self, payment_id: int) -> list[ClearingTransaction]:
        return list(
            self.session.execute(
                select(ClearingTransaction)
                .where(ClearingTransaction.payment_id == payment_id)
                .order_by(ClearingTransaction.id.asc())
            ).scalars()
        )


def partial_amount(amount: Decimal, pct: Decimal) -> Decimal:
    return amount * pct
