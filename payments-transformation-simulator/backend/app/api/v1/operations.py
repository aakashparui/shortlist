"""Operations: investigations, exceptions and reconciliation."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api import serializers as ser
from app.api.deps import DbSession, PageSize, Payments, not_found
from app.api.schemas import InvestigationActionRequest, InvestigationResolveRequest
from app.db.models import (
    Investigation,
    Payment,
    ReconciliationRecord,
    StatementEntry,
)
from app.domain.enums import InvestigationStatus, PaymentStatus, ReconciliationStatus
from app.engines.investigation import InvestigationDesk
from app.engines.reconciliation import CAUSE_LIBRARY, ReconciliationEngine

router = APIRouter(tags=["operations"])

OPEN_STATES = (
    InvestigationStatus.OPEN.value,
    InvestigationStatus.IN_PROGRESS.value,
    InvestigationStatus.AWAITING_RESPONSE.value,
)


# ---------------------------------------------------------------------------
# investigations
# ---------------------------------------------------------------------------


@router.get("/investigations", summary="Investigation queue")
def list_investigations(
    session: DbSession,
    pageSize: PageSize,
    page: int = Query(default=1, ge=1),
    status: Annotated[list[str] | None, Query()] = None,
    reason: Annotated[list[str] | None, Query()] = None,
    openOnly: bool = False,
) -> dict:
    stmt = select(Investigation)
    if status:
        stmt = stmt.where(Investigation.status.in_(status))
    if openOnly:
        stmt = stmt.where(Investigation.status.in_(OPEN_STATES))
    if reason:
        stmt = stmt.where(Investigation.reason.in_(reason))
    total = session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = list(
        session.execute(
            stmt.order_by(Investigation.opened_at.desc())
            .offset((page - 1) * pageSize)
            .limit(pageSize)
        ).scalars()
    )
    counts = dict(
        session.execute(
            select(Investigation.reason, func.count(Investigation.id)).group_by(Investigation.reason)
        ).all()
    )
    return {
        "items": [ser.investigation(i) for i in rows],
        "total": total,
        "page": page,
        "pageSize": pageSize,
        "byReason": counts,
    }


@router.get("/investigations/{reference}", summary="Investigation detail with the full payment trail")
def get_investigation(reference: str, session: DbSession, service: Payments) -> dict:
    row = session.execute(
        select(Investigation).where(Investigation.reference == reference.upper()).limit(1)
    ).scalar_one_or_none()
    if row is None:
        raise not_found(f"Investigation '{reference}' not found")
    data = ser.investigation(row)
    if row.payment_id:
        payment = session.get(Payment, row.payment_id)
        if payment is not None:
            data["payment"] = service.full_view(payment)
    if row.reconciliation_record_id:
        record = session.get(ReconciliationRecord, row.reconciliation_record_id)
        if record is not None:
            data["reconciliationRecord"] = ser.reconciliation(record)
    return data


@router.post("/investigations/{reference}/actions", summary="Record an investigation action")
def add_action(
    reference: str, payload: InvestigationActionRequest, session: DbSession, service: Payments
) -> dict:
    row = session.execute(
        select(Investigation).where(Investigation.reference == reference.upper()).limit(1)
    ).scalar_one_or_none()
    if row is None:
        raise not_found(f"Investigation '{reference}' not found")
    desk = InvestigationDesk(session)
    before = {"status": row.status, "actionCount": len(row.actions or [])}
    desk.add_action(
        row,
        actor=payload.actor,
        action=payload.action,
        note=payload.note,
        status=InvestigationStatus(payload.status) if payload.status else None,
    )
    service.events.audit(
        actor=payload.actor,
        action=f"INVESTIGATION_ACTION:{payload.action}",
        entity_type="Investigation",
        entity_id=row.reference,
        reason=payload.note,
        before=before,
        after={"status": row.status, "actionCount": len(row.actions or [])},
    )
    return ser.investigation(row)


@router.post("/investigations/{reference}/resolve", summary="Resolve an investigation")
def resolve_investigation(
    reference: str, payload: InvestigationResolveRequest, session: DbSession, service: Payments
) -> dict:
    row = session.execute(
        select(Investigation).where(Investigation.reference == reference.upper()).limit(1)
    ).scalar_one_or_none()
    if row is None:
        raise not_found(f"Investigation '{reference}' not found")
    desk = InvestigationDesk(session)
    before = {"status": row.status}
    desk.resolve(
        row,
        resolution=payload.resolution,
        actor=payload.actor,
        status=InvestigationStatus(payload.status),
    )
    if row.reconciliation_record_id:
        record = session.get(ReconciliationRecord, row.reconciliation_record_id)
        if record is not None:
            record.resolved = True
    service.events.audit(
        actor=payload.actor,
        action="INVESTIGATION_RESOLVED",
        entity_type="Investigation",
        entity_id=row.reference,
        reason=payload.resolution,
        before=before,
        after={"status": row.status},
    )
    return ser.investigation(row)


# ---------------------------------------------------------------------------
# exceptions
# ---------------------------------------------------------------------------


@router.get("/exceptions", summary="Everything currently in an exception state")
def exceptions(session: DbSession, service: Payments) -> dict:
    failure_statuses = [s.value for s in PaymentStatus if s.is_failure]
    payments = list(
        session.execute(
            select(Payment)
            .where(Payment.status.in_(failure_statuses))
            .order_by(Payment.updated_at.desc())
            .limit(200)
        )
        .scalars()
        .unique()
    )
    breaks = list(
        session.execute(
            select(ReconciliationRecord)
            .where(
                ReconciliationRecord.status.notin_(
                    (ReconciliationStatus.MATCHED.value, ReconciliationStatus.NOT_RUN.value)
                ),
                ReconciliationRecord.resolved.is_(False),
            )
            .order_by(ReconciliationRecord.created_at.desc())
            .limit(200)
        ).scalars()
    )
    investigations = list(
        session.execute(
            select(Investigation)
            .where(Investigation.status.in_(OPEN_STATES))
            .order_by(Investigation.opened_at.desc())
            .limit(200)
        ).scalars()
    )
    orphans = ReconciliationEngine(session).unmatched_statement_entries()
    by_status: dict[str, int] = {}
    for payment in payments:
        by_status[payment.status] = by_status.get(payment.status, 0) + 1
    return {
        "summary": {
            "failedPayments": len(payments),
            "reconciliationBreaks": len(breaks),
            "openInvestigations": len(investigations),
            "unmatchedStatementEntries": len(orphans),
            "byStatus": by_status,
        },
        "payments": [ser.payment_summary(p) for p in payments],
        "reconciliationBreaks": [ser.reconciliation(r) for r in breaks],
        "investigations": [ser.investigation(i) for i in investigations],
        "unmatchedStatementEntries": [ser.statement_entry(s) for s in orphans],
    }


# ---------------------------------------------------------------------------
# reconciliation
# ---------------------------------------------------------------------------


@router.get("/reconciliation", summary="Reconciliation records")
def list_reconciliation(
    session: DbSession,
    pageSize: PageSize,
    page: int = Query(default=1, ge=1),
    status: Annotated[list[str] | None, Query()] = None,
    breaksOnly: bool = False,
) -> dict:
    stmt = select(ReconciliationRecord)
    if status:
        stmt = stmt.where(ReconciliationRecord.status.in_(status))
    if breaksOnly:
        stmt = stmt.where(
            ReconciliationRecord.status.notin_(
                (ReconciliationStatus.MATCHED.value, ReconciliationStatus.NOT_RUN.value)
            )
        )
    total = session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = list(
        session.execute(
            stmt.order_by(ReconciliationRecord.created_at.desc())
            .offset((page - 1) * pageSize)
            .limit(pageSize)
        ).scalars()
    )
    counts = dict(
        session.execute(
            select(ReconciliationRecord.status, func.count(ReconciliationRecord.id)).group_by(
                ReconciliationRecord.status
            )
        ).all()
    )
    return {
        "items": [ser.reconciliation(r) for r in rows],
        "total": total,
        "page": page,
        "pageSize": pageSize,
        "byStatus": counts,
        "classifications": [
            {
                "status": key.value,
                "isBreak": key.is_break,
                "probableCause": cause,
                "recommendedAction": action,
            }
            for key, (cause, action) in CAUSE_LIBRARY.items()
        ],
    }


@router.get("/reconciliation/unmatched", summary="Statement entries with no internal record")
def unmatched(session: DbSession) -> dict:
    rows = ReconciliationEngine(session).unmatched_statement_entries()
    return {"items": [ser.statement_entry(s) for s in rows], "total": len(rows)}


@router.get("/reconciliation/statement-entries", summary="Statement entries")
def statement_entries(
    session: DbSession,
    pageSize: PageSize,
    page: int = Query(default=1, ge=1),
    accountNumber: str | None = None,
) -> dict:
    stmt = select(StatementEntry)
    if accountNumber:
        stmt = stmt.where(StatementEntry.account_number == accountNumber)
    total = session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = list(
        session.execute(
            stmt.order_by(StatementEntry.id.desc()).offset((page - 1) * pageSize).limit(pageSize)
        ).scalars()
    )
    return {
        "items": [ser.statement_entry(s) for s in rows],
        "total": total,
        "page": page,
        "pageSize": pageSize,
    }


@router.get("/reconciliation/{reference}", summary="One reconciliation record in full")
def get_reconciliation(reference: str, session: DbSession, service: Payments) -> dict:
    row = session.execute(
        select(ReconciliationRecord)
        .where(ReconciliationRecord.reference == reference.upper())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        raise not_found(f"Reconciliation record '{reference}' not found")
    data = ser.reconciliation(row)
    if row.payment_id:
        payment = session.get(Payment, row.payment_id)
        if payment is not None:
            data["payment"] = service.full_view(payment)
    return data
