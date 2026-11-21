"""Payment endpoints."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Body, Query

from app.api import serializers as ser
from app.api.deps import DbSession, PageSize, Payments, bad_request, conflict, not_found
from app.api.schemas import (
    CancellationRequest,
    FailureInjectionInput,
    PaymentCreate,
    PaymentExecuteRequest,
    ReconcileRequest,
    ResolveTimeoutRequest,
    RetryRequest,
    ReturnRequest,
)
from app.core.logging import correlation_id_var, get_logger
from app.db.models import StatementEntry, ValidationResult
from app.domain.enums import ProcessingMode
from app.engines.failure_injection import CATALOGUE_BY_CODE, FailureInjectionEngine, catalogue
from app.engines.messaging import mt
from app.engines.scheduler import drain, wait_for_quiet
from app.engines.state_machine import IllegalTransitionError, allowed_targets
from app.schemes.registry import get_scheme

logger = get_logger(__name__)
router = APIRouter(prefix="/payments", tags=["payments"])


@router.get("", summary="Search and list payments")
def list_payments(
    service: Payments,
    pageSize: PageSize,
    page: int = Query(default=1, ge=1),
    status: Annotated[list[str] | None, Query()] = None,
    scheme: Annotated[list[str] | None, Query()] = None,
    currency: Annotated[list[str] | None, Query()] = None,
    query: str | None = None,
    failuresOnly: bool = False,
    amountMin: Decimal | None = None,
    amountMax: Decimal | None = None,
    createdFrom: datetime | None = None,
    createdTo: datetime | None = None,
    sort: str = "createdAt",
    direction: str = "desc",
) -> dict:
    page_result = service.search(
        page=page,
        page_size=pageSize,
        status=status,
        scheme=scheme,
        currency=currency,
        query=query,
        failures_only=failuresOnly,
        amount_min=amountMin,
        amount_max=amountMax,
        created_from=createdFrom,
        created_to=createdTo,
        sort=sort,
        direction=direction,
    )
    return {
        "items": [ser.payment_summary(p) for p in page_result.items],
        "total": page_result.total,
        "page": page_result.page,
        "pageSize": page_result.page_size,
        "pages": max(1, -(-page_result.total // page_result.page_size)),
    }


@router.get("/statistics", summary="Portfolio statistics")
def statistics(service: Payments) -> dict:
    return service.statistics()


@router.get("/failure-catalogue", summary="Available failure injections")
def failure_catalogue() -> dict:
    return {"items": catalogue()}


@router.post("", status_code=201, summary="Create a payment")
def create_payment(payload: PaymentCreate, service: Payments) -> dict:
    try:
        get_scheme(payload.scheme)
    except KeyError as exc:
        raise bad_request(f"Unknown scheme '{payload.scheme}'") from exc
    for injection in payload.failureInjections:
        if injection.code not in CATALOGUE_BY_CODE:
            raise bad_request(f"Unknown failure injection '{injection.code}'")
    payment = service.create(payload)
    correlation_id_var.set(payment.correlation_id)
    return service.full_view(payment)


@router.get("/{identifier}", summary="Full payment view")
def get_payment(identifier: str, service: Payments) -> dict:
    try:
        payment = service.require(identifier)
    except LookupError as exc:
        raise not_found(str(exc)) from exc
    return service.full_view(payment)


@router.post("/{identifier}/execute", summary="Execute the payment lifecycle")
def execute_payment(
    identifier: str,
    service: Payments,
    payload: PaymentExecuteRequest = Body(default_factory=PaymentExecuteRequest),
) -> dict:
    try:
        payment = service.require(identifier)
    except LookupError as exc:
        raise not_found(str(exc)) from exc
    mode = ProcessingMode(payload.processingMode) if payload.processingMode else None
    try:
        result = service.execute(payment, mode)
    except IllegalTransitionError as exc:
        raise conflict(str(exc), {"allowedTransitions": exc.allowed}) from exc
    service.session.commit()
    if payload.waitForCompletion:
        if ProcessingMode(payment.processing_mode) is ProcessingMode.SIMULATED:
            wait_for_quiet(payload.waitTimeoutSeconds)
        else:
            drain()
        service.session.expire_all()
        payment = service.require(identifier)
    view = service.full_view(payment)
    view["execution"] = {
        "status": result.status.value,
        "stagesCompleted": result.stages_completed,
        "failureStage": result.failure_stage.value if result.failure_stage else None,
        "failureReason": result.failure_reason,
        "awaitingAsync": result.awaiting_async,
        "notes": result.notes,
    }
    return view


@router.get("/{identifier}/timeline", summary="Payment journey timeline")
def timeline(identifier: str, service: Payments) -> dict:
    try:
        payment = service.require(identifier)
    except LookupError as exc:
        raise not_found(str(exc)) from exc
    scheme = get_scheme(payment.scheme)
    return {
        "reference": payment.reference,
        "status": payment.status,
        "previousStatus": payment.previous_status,
        "allowedTransitions": allowed_targets(payment.status),
        "scheme": scheme.as_dict(),
        "stages": [ser.stage(s) for s in sorted(payment.stages, key=lambda s: s.sequence)],
        "failureSummary": payment.failure_summary,
        "pendingJobs": [
            {"jobType": j.job_type, "dueAt": j.due_at.isoformat(), "status": j.status}
            for j in service.orchestrator.pending_jobs(payment.id)
        ],
    }


@router.get("/{identifier}/messages", summary="ISO 20022 messages for a payment")
def messages(identifier: str, service: Payments, includeXml: bool = True) -> dict:
    try:
        payment = service.require(identifier)
    except LookupError as exc:
        raise not_found(str(exc)) from exc
    rows = service.messages.all_for_payment(payment.id)
    return {
        "reference": payment.reference,
        "items": [ser.message(m, include_xml=includeXml) for m in rows],
    }


@router.get("/{identifier}/messages/{message_id}", summary="One message in full")
def message_detail(identifier: str, message_id: str, service: Payments) -> dict:
    try:
        payment = service.require(identifier)
    except LookupError as exc:
        raise not_found(str(exc)) from exc
    for row in service.messages.all_for_payment(payment.id):
        if row.message_id == message_id or str(row.id) == message_id:
            return ser.message(row)
    raise not_found(f"Message '{message_id}' not found on payment {payment.reference}")


@router.get("/{identifier}/events", summary="Event log for a payment")
def events(
    identifier: str,
    service: Payments,
    eventType: Annotated[list[str] | None, Query()] = None,
    sourceSystem: Annotated[list[str] | None, Query()] = None,
    severity: Annotated[list[str] | None, Query()] = None,
) -> dict:
    try:
        payment = service.require(identifier)
    except LookupError as exc:
        raise not_found(str(exc)) from exc
    rows = service.events.for_payment(payment.id)
    if eventType:
        rows = [r for r in rows if r.event_type in eventType]
    if sourceSystem:
        rows = [r for r in rows if r.source_system in sourceSystem]
    if severity:
        rows = [r for r in rows if r.severity in severity]
    return {"reference": payment.reference, "items": [ser.event(e) for e in rows]}


@router.get("/{identifier}/validations", summary="Validation results for a payment")
def validations(identifier: str, service: Payments, session: DbSession) -> dict:
    from sqlalchemy import select

    try:
        payment = service.require(identifier)
    except LookupError as exc:
        raise not_found(str(exc)) from exc
    rows = list(
        session.execute(
            select(ValidationResult)
            .where(ValidationResult.payment_id == payment.id)
            .order_by(ValidationResult.run_id.asc(), ValidationResult.id.asc())
        ).scalars()
    )
    return {"reference": payment.reference, "items": [ser.validation(v) for v in rows]}


@router.get("/{identifier}/accounting", summary="Accounting journal for a payment")
def accounting(identifier: str, service: Payments, session: DbSession) -> dict:
    from sqlalchemy import select

    try:
        payment = service.require(identifier)
    except LookupError as exc:
        raise not_found(str(exc)) from exc
    entries = service.accounting.entries_for_payment(payment.id)
    statement_rows = list(
        session.execute(
            select(StatementEntry).where(StatementEntry.payment_id == payment.id)
        ).scalars()
    )
    debits = sum((e.amount for e in entries if e.side == "DEBIT" and e.status != "REVERSED"), Decimal("0"))
    credits = sum((e.amount for e in entries if e.side == "CREDIT" and e.status != "REVERSED"), Decimal("0"))
    return {
        "reference": payment.reference,
        "entries": [ser.accounting_entry(e) for e in entries],
        "statementEntries": [ser.statement_entry(s) for s in statement_rows],
        "totals": {
            "debits": str(debits),
            "credits": str(credits),
            "balanced": debits == credits,
            "currency": payment.currency,
        },
    }


@router.get("/{identifier}/settlement", summary="Settlement records for a payment")
def settlement(identifier: str, service: Payments) -> dict:
    try:
        payment = service.require(identifier)
    except LookupError as exc:
        raise not_found(str(exc)) from exc
    return {
        "reference": payment.reference,
        "items": [ser.settlement(s) for s in service.settlement.all_for_payment(payment.id)],
    }


@router.get("/{identifier}/clearing", summary="Clearing records for a payment")
def clearing(identifier: str, service: Payments) -> dict:
    try:
        payment = service.require(identifier)
    except LookupError as exc:
        raise not_found(str(exc)) from exc
    return {
        "reference": payment.reference,
        "items": [ser.clearing(c) for c in service.clearing.all_for_payment(payment.id)],
    }


@router.get("/{identifier}/reconciliation", summary="Reconciliation records for a payment")
def reconciliation(identifier: str, service: Payments) -> dict:
    try:
        payment = service.require(identifier)
    except LookupError as exc:
        raise not_found(str(exc)) from exc
    return {
        "reference": payment.reference,
        "items": [
            ser.reconciliation(r) for r in service.reconciliation.records_for_payment(payment.id)
        ],
    }


@router.post("/{identifier}/reconcile", summary="Run reconciliation again")
def reconcile(
    identifier: str,
    service: Payments,
    payload: ReconcileRequest = Body(default_factory=ReconcileRequest),
) -> dict:
    try:
        payment = service.require(identifier)
    except LookupError as exc:
        raise not_found(str(exc)) from exc
    outcome = service.reconcile_now(payment, actor=payload.actor)
    return ser.reconciliation(outcome.record)


@router.get("/{identifier}/mt-mx", summary="MT to MX mapping for a payment")
def mt_mx(identifier: str, service: Payments) -> dict:
    try:
        payment = service.require(identifier)
    except LookupError as exc:
        raise not_found(str(exc)) from exc
    return {
        "reference": payment.reference,
        "scheme": payment.scheme,
        "rows": mt.mapping_rows(payment),
        "note": (
            "There is no universal one-to-one MT to MX mapping. Direct, transformed, derived and "
            "no-equivalent mappings are distinguished explicitly."
        ),
    }


@router.get("/{identifier}/failures", summary="Failure injections on a payment")
def list_failures(identifier: str, service: Payments) -> dict:
    try:
        payment = service.require(identifier)
    except LookupError as exc:
        raise not_found(str(exc)) from exc
    engine = FailureInjectionEngine(service.session)
    return {
        "reference": payment.reference,
        "items": [ser.failure_injection(f) for f in engine.all_for(payment.id)],
    }


@router.post("/{identifier}/failures", status_code=201, summary="Register a failure injection")
def inject_failure(identifier: str, payload: FailureInjectionInput, service: Payments) -> dict:
    try:
        payment = service.require(identifier)
    except LookupError as exc:
        raise not_found(str(exc)) from exc
    if payload.code not in CATALOGUE_BY_CODE:
        raise bad_request(f"Unknown failure injection '{payload.code}'")
    engine = FailureInjectionEngine(service.session)
    row = engine.register(payment, payload.code, payload.parameters)
    service.events.audit(
        actor="qa.lab",
        action=f"INJECT_REGISTERED:{payload.code}",
        entity_type="Payment",
        entity_id=payment.reference,
        reason=CATALOGUE_BY_CODE[payload.code].description,
        after={"code": payload.code, "parameters": payload.parameters},
        correlation_id=payment.correlation_id,
    )
    return ser.failure_injection(row)


@router.delete("/{identifier}/failures/{injection_id}", summary="Deactivate a failure injection")
def remove_failure(identifier: str, injection_id: int, service: Payments) -> dict:
    try:
        payment = service.require(identifier)
    except LookupError as exc:
        raise not_found(str(exc)) from exc
    engine = FailureInjectionEngine(service.session)
    row = engine.deactivate(injection_id)
    if row is None or row.payment_id != payment.id:
        raise not_found(f"Injection {injection_id} not found on {payment.reference}")
    return ser.failure_injection(row)


@router.post("/{identifier}/retry", summary="Controlled reprocessing")
def retry(identifier: str, payload: RetryRequest, service: Payments) -> dict:
    try:
        payment = service.require(identifier)
    except LookupError as exc:
        raise not_found(str(exc)) from exc
    mode = ProcessingMode(payload.processingMode) if payload.processingMode else None
    try:
        result = service.orchestrator.retry(
            payment, reason=payload.reason, actor=payload.actor, mode=mode
        )
    except IllegalTransitionError as exc:
        raise conflict(str(exc), {"allowedTransitions": exc.allowed}) from exc
    service.session.commit()
    view = service.full_view(payment)
    view["execution"] = {
        "status": result.status.value,
        "stagesCompleted": result.stages_completed,
        "awaitingAsync": result.awaiting_async,
        "notes": result.notes,
    }
    return view


@router.post("/{identifier}/resolve-timeout", summary="Apply the clearing system's late answer")
def resolve_timeout(identifier: str, payload: ResolveTimeoutRequest, service: Payments) -> dict:
    try:
        payment = service.require(identifier)
    except LookupError as exc:
        raise not_found(str(exc)) from exc
    try:
        service.orchestrator.resolve_timeout_with_response(
            payment,
            accepted=payload.accepted,
            reason_code=payload.reasonCode,
            actor=payload.actor,
        )
    except LookupError as exc:
        raise bad_request(str(exc)) from exc
    except IllegalTransitionError as exc:
        raise conflict(str(exc), {"allowedTransitions": exc.allowed}) from exc
    return service.full_view(payment)


@router.post("/{identifier}/cancel", summary="Send a camt.056 cancellation request")
def cancel(identifier: str, payload: CancellationRequest, service: Payments) -> dict:
    try:
        payment = service.require(identifier)
    except LookupError as exc:
        raise not_found(str(exc)) from exc
    try:
        camt056, camt029 = service.orchestrator.request_cancellation(
            payment,
            reason_code=payload.reasonCode,
            narrative=payload.narrative,
            actor=payload.actor,
            auto_resolve=payload.autoResolve,
        )
    except ValueError as exc:
        raise bad_request(str(exc)) from exc
    view = service.full_view(payment)
    view["cancellation"] = {
        "requestMessage": ser.message(camt056),
        "resolutionMessage": ser.message(camt029) if camt029 else None,
    }
    return view


@router.post("/{identifier}/return", summary="Apply an inbound pacs.004 return")
def apply_return(identifier: str, payload: ReturnRequest, service: Payments) -> dict:
    try:
        payment = service.require(identifier)
    except LookupError as exc:
        raise not_found(str(exc)) from exc
    message = service.orchestrator.apply_return(
        payment,
        reason_code=payload.reasonCode,
        narrative=payload.narrative,
        returned_amount=payload.returnedAmount,
        charges=payload.charges,
        actor=payload.actor,
    )
    view = service.full_view(payment)
    view["returnMessage"] = ser.message(message)
    return view


@router.get("/{identifier}/tracking", summary="UETR tracking timeline (cross-border)")
def tracking(identifier: str, service: Payments) -> dict:
    try:
        payment = service.require(identifier)
    except LookupError as exc:
        raise not_found(str(exc)) from exc
    scheme = get_scheme(payment.scheme)
    if not scheme.rules.uses_uetr:
        return {
            "reference": payment.reference,
            "supported": False,
            "note": f"{scheme.short_name} does not carry a UETR.",
            "events": [],
        }
    events_rows = service.events.for_payment(payment.id)
    tracked = [
        e
        for e in events_rows
        if e.event_type
        in (
            "PAYMENT_CREATED",
            "MESSAGE_GENERATED",
            "MESSAGE_SENT",
            "CLEARING_DISPATCHED",
            "CLEARING_RESPONSE",
            "CLEARING_TIMEOUT",
            "SETTLEMENT_POSTED",
            "ACCOUNTING_POSTED",
            "PAYMENT_RETURNED",
            "STATUS_CHANGED",
        )
    ]
    return {
        "reference": payment.reference,
        "supported": True,
        "uetr": payment.uetr,
        "status": payment.status,
        "simulationNote": (
            "Tracking is simulated locally. This is not connected to SWIFT gpi or any real "
            "tracking service, and the UETR is generated by this application."
        ),
        "events": [
            {
                "at": e.occurred_at.isoformat(),
                "agent": e.source_system,
                "event": e.event_type,
                "description": e.summary,
                "severity": e.severity,
            }
            for e in tracked
        ],
    }
