"""Event and audit recording.

Every meaningful action produces a `PaymentEvent`. Changes an operator makes
also produce an `AuditEvent` carrying who / what / when / before / after / why.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.identifiers import utcnow
from app.core.logging import correlation_id_var, get_logger, payment_id_var, request_id_var
from app.db.models import AuditEvent, Payment, PaymentEvent
from app.domain.enums import EventType, Severity, SourceSystem, StageKey

logger = get_logger(__name__)


class EventRecorder:
    def __init__(self, session: Session) -> None:
        self.session = session
        self._sequences: dict[int, int] = {}

    def _next_sequence(self, payment_id: int | None) -> int:
        if payment_id is None:
            return 0
        if payment_id not in self._sequences:
            current = self.session.execute(
                select(func.max(PaymentEvent.sequence)).where(PaymentEvent.payment_id == payment_id)
            ).scalar()
            self._sequences[payment_id] = int(current or 0)
        self._sequences[payment_id] += 1
        return self._sequences[payment_id]

    def record(
        self,
        payment: Payment | None,
        event_type: EventType,
        source: SourceSystem,
        summary: str,
        *,
        severity: Severity = Severity.INFO,
        stage: StageKey | None = None,
        detail: dict | None = None,
        duration_ms: int | None = None,
    ) -> PaymentEvent:
        payment_id = payment.id if payment else None
        event = PaymentEvent(
            payment_id=payment_id,
            correlation_id=(payment.correlation_id if payment else correlation_id_var.get()),
            sequence=self._next_sequence(payment_id),
            event_type=event_type.value,
            source_system=source.value,
            severity=severity.value,
            stage_key=stage.value if stage else None,
            summary=summary[:300],
            detail=detail or {},
            occurred_at=utcnow(),
            duration_ms=duration_ms,
        )
        self.session.add(event)
        self.session.flush()
        logger.info(
            summary,
            extra={
                "event_type": event_type.value,
                "source_system": source.value,
                "stage": stage.value if stage else None,
                "payment_reference": payment.reference if payment else None,
            },
        )
        return event

    def audit(
        self,
        *,
        actor: str,
        action: str,
        entity_type: str,
        entity_id: str,
        reason: str = "",
        before: dict | None = None,
        after: dict | None = None,
        correlation_id: str | None = None,
    ) -> AuditEvent:
        row = AuditEvent(
            actor=actor,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            occurred_at=utcnow(),
            reason=reason,
            before=before or {},
            after=after or {},
            request_id=request_id_var.get(),
            correlation_id=correlation_id or correlation_id_var.get(),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def bind_context(self, payment: Payment) -> None:
        payment_id_var.set(payment.reference)
        correlation_id_var.set(payment.correlation_id)

    def for_payment(self, payment_id: int) -> list[PaymentEvent]:
        return list(
            self.session.execute(
                select(PaymentEvent)
                .where(PaymentEvent.payment_id == payment_id)
                .order_by(PaymentEvent.sequence.asc(), PaymentEvent.id.asc())
            ).scalars()
        )
