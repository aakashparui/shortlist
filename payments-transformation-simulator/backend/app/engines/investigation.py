"""Investigation desk.

An investigation is opened whenever the lifecycle cannot proceed on its own.
It always records the same six things an operations analyst needs:

    what happened / where / why / what message was produced /
    what state the payment is in / what the next possible action is
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.identifiers import investigation_reference, utcnow
from app.core.logging import get_logger
from app.db.models import Investigation, Payment, ReconciliationRecord
from app.domain.enums import InvestigationReason, InvestigationStatus

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class InvestigationTemplate:
    title: str
    expected: str
    priority: str


TEMPLATES: dict[InvestigationReason, InvestigationTemplate] = {
    InvestigationReason.CLEARING_TIMEOUT: InvestigationTemplate(
        title="No clearing status report received",
        expected="A pacs.002 status report within the scheme response window",
        priority="HIGH",
    ),
    InvestigationReason.RECONCILIATION_BREAK: InvestigationTemplate(
        title="Reconciliation break",
        expected="The statement entry to match the internal record on amount, currency and reference",
        priority="NORMAL",
    ),
    InvestigationReason.ACCOUNTING_BREAK: InvestigationTemplate(
        title="Accounting break",
        expected="A balanced double-entry journal for the payment",
        priority="HIGH",
    ),
    InvestigationReason.SETTLEMENT_FAILURE: InvestigationTemplate(
        title="Settlement failure",
        expected="Settlement across the settlement account for the full payment amount",
        priority="HIGH",
    ),
    InvestigationReason.COMPLIANCE_BLOCK: InvestigationTemplate(
        title="Compliance block requires disposition",
        expected="No match against any screening list",
        priority="HIGH",
    ),
    InvestigationReason.CANCELLATION_REQUEST: InvestigationTemplate(
        title="Cancellation request outstanding",
        expected="A camt.029 resolution confirming whether the payment was cancelled",
        priority="NORMAL",
    ),
    InvestigationReason.BENEFICIARY_NOT_CREDITED: InvestigationTemplate(
        title="Beneficiary not credited despite acceptance",
        expected="The beneficiary account credited after the clearing system accepted the payment",
        priority="HIGH",
    ),
    InvestigationReason.CUSTOMER_QUERY: InvestigationTemplate(
        title="Customer query on a payment",
        expected="The payment to have completed as instructed",
        priority="LOW",
    ),
}


class InvestigationDesk:
    def __init__(self, session: Session) -> None:
        self.session = session

    def open(
        self,
        payment: Payment | None,
        reason: InvestigationReason,
        *,
        actual: str,
        probable_cause: str,
        recommended_action: str,
        summary: str = "",
        title: str | None = None,
        detail: dict | None = None,
        reconciliation_record: ReconciliationRecord | None = None,
        assigned_to: str = "payments.operations",
    ) -> Investigation:
        template = TEMPLATES[reason]
        existing = self._open_for(payment.id, reason) if payment else None
        if existing is not None:
            existing.actual_behaviour = actual
            existing.probable_cause = probable_cause
            existing.recommended_action = recommended_action
            existing.updated_at = utcnow()
            merged = dict(existing.detail or {})
            merged.update(detail or {})
            existing.detail = merged
            self.session.flush()
            return existing

        investigation = Investigation(
            payment_id=payment.id if payment else None,
            reference=investigation_reference(),
            status=InvestigationStatus.OPEN.value,
            reason=reason.value,
            priority=template.priority,
            title=title or template.title,
            summary=summary or template.title,
            expected_behaviour=template.expected,
            actual_behaviour=actual,
            probable_cause=probable_cause,
            recommended_action=recommended_action,
            assigned_to=assigned_to,
            opened_at=utcnow(),
            reconciliation_record_id=reconciliation_record.id if reconciliation_record else None,
            actions=[
                {
                    "at": utcnow().isoformat(),
                    "actor": "system",
                    "action": "OPENED",
                    "note": f"Opened automatically: {actual}",
                }
            ],
            detail=detail or {},
        )
        self.session.add(investigation)
        self.session.flush()
        logger.info(
            "investigation opened",
            extra={
                "investigation_reference": investigation.reference,
                "reason": reason.value,
                "payment_reference": payment.reference if payment else None,
            },
        )
        return investigation

    def add_action(
        self,
        investigation: Investigation,
        *,
        actor: str,
        action: str,
        note: str,
        status: InvestigationStatus | None = None,
    ) -> Investigation:
        actions = list(investigation.actions or [])
        actions.append(
            {"at": utcnow().isoformat(), "actor": actor, "action": action, "note": note}
        )
        investigation.actions = actions
        if status is not None:
            investigation.status = status.value
            if status in (InvestigationStatus.RESOLVED, InvestigationStatus.CLOSED_UNRESOLVED):
                investigation.resolved_at = utcnow()
        investigation.updated_at = utcnow()
        self.session.flush()
        return investigation

    def resolve(
        self,
        investigation: Investigation,
        *,
        resolution: str,
        actor: str = "payments.operations",
        status: InvestigationStatus = InvestigationStatus.RESOLVED,
    ) -> Investigation:
        investigation.resolution = resolution
        self.add_action(
            investigation, actor=actor, action="RESOLVED", note=resolution, status=status
        )
        return investigation

    def _open_for(self, payment_id: int, reason: InvestigationReason) -> Investigation | None:
        return self.session.execute(
            select(Investigation)
            .where(
                Investigation.payment_id == payment_id,
                Investigation.reason == reason.value,
                Investigation.status.in_(
                    (
                        InvestigationStatus.OPEN.value,
                        InvestigationStatus.IN_PROGRESS.value,
                        InvestigationStatus.AWAITING_RESPONSE.value,
                    )
                ),
            )
            .order_by(Investigation.id.desc())
            .limit(1)
        ).scalar_one_or_none()

    def open_for_payment(self, payment_id: int) -> list[Investigation]:
        return list(
            self.session.execute(
                select(Investigation)
                .where(Investigation.payment_id == payment_id)
                .order_by(Investigation.opened_at.desc())
            ).scalars()
        )
