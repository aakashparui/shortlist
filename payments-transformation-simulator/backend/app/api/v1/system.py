"""System: schemes, rule engine, event log, accounts, messages explorer, search, config."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, or_, select

from app.api import serializers as ser
from app.api.deps import DbSession, PageSize, Payments, Search, bad_request, not_found
from app.api.schemas import RuleToggleRequest
from app.core.config import settings
from app.db.models import (
    Account,
    AuditEvent,
    Bank,
    BusinessRule,
    Payment,
    PaymentEvent,
    PaymentMessage,
    StatementEntry,
)
from app.domain.enums import (
    MESSAGE_METADATA,
    STAGE_LABELS,
    STAGE_ORDER,
    AccountType,
    EventType,
    MessageType,
    PaymentStatus,
    ReconciliationStatus,
    Severity,
    SourceSystem,
    StageKey,
    ValidationCategory,
)
from app.domain.money import CURRENCY_NAMES, SUPPORTED_CURRENCIES
from app.engines.messaging import mt
from app.engines.messaging.engine import MessageEngine
from app.engines.state_machine import graph
from app.engines.validation.engine import ValidationEngine
from app.schemes.registry import clearing_timeout_seconds, get_scheme, list_schemes

router = APIRouter(tags=["system"])


# ---------------------------------------------------------------------------
# schemes
# ---------------------------------------------------------------------------


@router.get("/schemes", summary="Supported payment schemes")
def schemes() -> dict:
    return {
        "items": [
            {
                **scheme.as_dict(),
                "acceleratedTimeoutSeconds": round(clearing_timeout_seconds(scheme), 2),
            }
            for scheme in list_schemes()
        ],
        "default": "SIC_INSTANT",
    }


@router.get("/schemes/{code}", summary="One scheme in full")
def scheme_detail(code: str, session: DbSession) -> dict:
    try:
        scheme = get_scheme(code)
    except KeyError as exc:
        raise not_found(f"Scheme '{code}' not found") from exc
    rules = list(
        session.execute(
            select(BusinessRule).where(BusinessRule.rule_id.in_(scheme.validation_rule_ids))
        ).scalars()
    )
    order = {rule_id: i for i, rule_id in enumerate(scheme.validation_rule_ids)}
    rules.sort(key=lambda r: order.get(r.rule_id, 999))
    counts = dict(
        session.execute(
            select(Payment.status, func.count(Payment.id))
            .where(Payment.scheme == scheme.code.value)
            .group_by(Payment.status)
        ).all()
    )
    return {
        **scheme.as_dict(),
        "acceleratedTimeoutSeconds": round(clearing_timeout_seconds(scheme), 2),
        "rules": [ser.business_rule(r) for r in rules],
        "paymentCounts": counts,
        "messageCatalogue": [
            {
                "messageType": message.value,
                "name": MESSAGE_METADATA[message]["name"],
                "isoIdentifier": MESSAGE_METADATA[message]["iso_identifier"],
                "direction": MESSAGE_METADATA[message]["direction"],
                "purpose": MESSAGE_METADATA[message]["purpose"],
            }
            for message in scheme.messages.message_set
        ],
    }


# ---------------------------------------------------------------------------
# rule engine
# ---------------------------------------------------------------------------


@router.get("/rules", summary="Business rule explorer")
def list_rules(
    session: DbSession,
    category: Annotated[list[str] | None, Query()] = None,
    scheme: str | None = None,
    stage: str | None = None,
    enabled: bool | None = None,
    query: str | None = None,
) -> dict:
    stmt = select(BusinessRule)
    if category:
        stmt = stmt.where(BusinessRule.category.in_(category))
    if stage:
        stmt = stmt.where(BusinessRule.stage == stage)
    if enabled is not None:
        stmt = stmt.where(BusinessRule.enabled.is_(enabled))
    if query:
        like = f"%{query}%"
        stmt = stmt.where(
            or_(
                BusinessRule.rule_id.ilike(like),
                BusinessRule.name.ilike(like),
                BusinessRule.description.ilike(like),
            )
        )
    rows = list(session.execute(stmt.order_by(BusinessRule.rule_id.asc())).scalars())
    if scheme:
        rows = [r for r in rows if scheme in (r.schemes or [])]
    return {
        "items": [ser.business_rule(r) for r in rows],
        "categories": [c.value for c in ValidationCategory],
        "stages": [s.value for s in STAGE_ORDER],
        "severities": [s.value for s in Severity],
        "total": len(rows),
        "disabledCount": sum(1 for r in rows if not r.enabled),
    }


@router.get("/rules/{rule_id}", summary="One rule")
def get_rule(rule_id: str, session: DbSession) -> dict:
    row = session.execute(
        select(BusinessRule).where(BusinessRule.rule_id == rule_id.upper()).limit(1)
    ).scalar_one_or_none()
    if row is None:
        raise not_found(f"Rule '{rule_id}' not found")
    from app.engines.failure_injection import CATALOGUE

    related = [d.as_dict() for d in CATALOGUE if rule_id.upper() in d.affected_rule_ids]
    return {**ser.business_rule(row), "relatedFailureInjections": related}


@router.patch("/rules/{rule_id}", summary="Enable or disable a rule")
def toggle_rule(
    rule_id: str, payload: RuleToggleRequest, session: DbSession, service: Payments
) -> dict:
    row = session.execute(
        select(BusinessRule).where(BusinessRule.rule_id == rule_id.upper()).limit(1)
    ).scalar_one_or_none()
    if row is None:
        raise not_found(f"Rule '{rule_id}' not found")
    before = {"enabled": row.enabled}
    row.enabled = payload.enabled
    session.flush()
    ValidationEngine(session).invalidate_rule_cache()
    service.events.audit(
        actor=payload.actor,
        action="RULE_TOGGLED",
        entity_type="BusinessRule",
        entity_id=row.rule_id,
        reason=payload.reason or ("Enabled" if payload.enabled else "Disabled for simulation"),
        before=before,
        after={"enabled": row.enabled},
    )
    return ser.business_rule(row)


@router.get("/state-machine", summary="Payment state machine")
def state_machine() -> dict:
    return {
        "transitions": graph(),
        "statuses": [
            {"status": s.value, "isTerminal": s.is_terminal, "isFailure": s.is_failure}
            for s in PaymentStatus
        ],
        "stages": [
            {
                "stageKey": key.value,
                "sequence": index,
                "businessLabel": STAGE_LABELS[key]["business"],
                "technicalLabel": STAGE_LABELS[key]["technical"],
            }
            for index, key in enumerate(STAGE_ORDER)
        ],
    }


# ---------------------------------------------------------------------------
# event log and audit
# ---------------------------------------------------------------------------


@router.get("/events", summary="Global event log")
def events(
    session: DbSession,
    pageSize: PageSize,
    page: int = Query(default=1, ge=1),
    eventType: Annotated[list[str] | None, Query()] = None,
    sourceSystem: Annotated[list[str] | None, Query()] = None,
    severity: Annotated[list[str] | None, Query()] = None,
    correlationId: str | None = None,
    stageKey: str | None = None,
    occurredFrom: datetime | None = None,
    occurredTo: datetime | None = None,
    query: str | None = None,
) -> dict:
    stmt = select(PaymentEvent)
    if eventType:
        stmt = stmt.where(PaymentEvent.event_type.in_(eventType))
    if sourceSystem:
        stmt = stmt.where(PaymentEvent.source_system.in_(sourceSystem))
    if severity:
        stmt = stmt.where(PaymentEvent.severity.in_(severity))
    if correlationId:
        stmt = stmt.where(PaymentEvent.correlation_id == correlationId)
    if stageKey:
        stmt = stmt.where(PaymentEvent.stage_key == stageKey)
    if occurredFrom:
        stmt = stmt.where(PaymentEvent.occurred_at >= occurredFrom)
    if occurredTo:
        stmt = stmt.where(PaymentEvent.occurred_at <= occurredTo)
    if query:
        stmt = stmt.where(PaymentEvent.summary.ilike(f"%{query}%"))
    total = session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = list(
        session.execute(
            stmt.order_by(PaymentEvent.occurred_at.desc(), PaymentEvent.id.desc())
            .offset((page - 1) * pageSize)
            .limit(pageSize)
        ).scalars()
    )
    payment_refs: dict[int, str] = {}
    ids = {r.payment_id for r in rows if r.payment_id}
    if ids:
        payment_refs = dict(
            session.execute(
                select(Payment.id, Payment.reference).where(Payment.id.in_(ids))
            ).all()
        )
    return {
        "items": [
            {**ser.event(e), "paymentReference": payment_refs.get(e.payment_id)} for e in rows
        ],
        "total": total,
        "page": page,
        "pageSize": pageSize,
        "filters": {
            "eventTypes": [e.value for e in EventType],
            "sourceSystems": [s.value for s in SourceSystem],
            "severities": [s.value for s in Severity],
            "stages": [s.value for s in StageKey],
        },
    }


@router.get("/audit", summary="Audit trail")
def audit(
    session: DbSession,
    pageSize: PageSize,
    page: int = Query(default=1, ge=1),
    entityType: str | None = None,
    entityId: str | None = None,
    actor: str | None = None,
) -> dict:
    stmt = select(AuditEvent)
    if entityType:
        stmt = stmt.where(AuditEvent.entity_type == entityType)
    if entityId:
        stmt = stmt.where(AuditEvent.entity_id == entityId)
    if actor:
        stmt = stmt.where(AuditEvent.actor == actor)
    total = session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = list(
        session.execute(
            stmt.order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
            .offset((page - 1) * pageSize)
            .limit(pageSize)
        ).scalars()
    )
    return {
        "items": [
            {
                "id": r.id,
                "actor": r.actor,
                "action": r.action,
                "entityType": r.entity_type,
                "entityId": r.entity_id,
                "occurredAt": r.occurred_at.isoformat(),
                "reason": r.reason,
                "before": r.before or {},
                "after": r.after or {},
                "requestId": r.request_id,
                "correlationId": r.correlation_id,
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "pageSize": pageSize,
    }


# ---------------------------------------------------------------------------
# accounts, nostro / vostro
# ---------------------------------------------------------------------------


@router.get("/accounts", summary="Accounts, nostro and vostro positions")
def accounts(session: DbSession, accountType: Annotated[list[str] | None, Query()] = None) -> dict:
    stmt = select(Account)
    if accountType:
        stmt = stmt.where(Account.account_type.in_([a.upper() for a in accountType]))
    rows = list(session.execute(stmt.order_by(Account.account_type.asc(), Account.id.asc())).scalars())
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row.account_type, []).append(ser.account(row))
    return {
        "items": [ser.account(r) for r in rows],
        "byType": grouped,
        "accountTypes": [a.value for a in AccountType],
        "explainer": {
            "NOSTRO": (
                "Our account held with another bank, in that bank's currency and on that bank's "
                "books. 'Nostro' is Italian for 'ours': our money, their books. An outgoing "
                "cross-border payment reduces the nostro position."
            ),
            "VOSTRO": (
                "Another bank's account held on our books. 'Vostro' means 'yours': their money, "
                "our books. The same relationship seen from the other side."
            ),
            "SETTLEMENT": (
                "The account over which a clearing system settles our net or gross obligations. "
                "For an instant rail this is typically a pre-funded or central-bank account."
            ),
            "SUSPENSE": (
                "A holding account for movements that cannot yet be applied to a customer, such as "
                "an unmatched statement entry."
            ),
            "CUSTOMER": "An account of the bank's own customer.",
        },
    }


@router.get("/accounts/{account_number}", summary="One account with its movements")
def account_detail(account_number: str, session: DbSession) -> dict:
    row = session.execute(
        select(Account).where(Account.account_number == account_number).limit(1)
    ).scalar_one_or_none()
    if row is None:
        raise not_found(f"Account '{account_number}' not found")
    from app.db.models import AccountingEntry

    entries = list(
        session.execute(
            select(AccountingEntry)
            .where(AccountingEntry.account_id == row.id)
            .order_by(AccountingEntry.posted_at.desc())
            .limit(100)
        ).scalars()
    )
    statement_rows = list(
        session.execute(
            select(StatementEntry)
            .where(StatementEntry.account_id == row.id)
            .order_by(StatementEntry.id.desc())
            .limit(100)
        ).scalars()
    )
    return {
        **ser.account(row),
        "accountingEntries": [ser.accounting_entry(e) for e in entries],
        "statementEntries": [ser.statement_entry(s) for s in statement_rows],
        "movement": {
            "openingBalance": str(row.opening_balance),
            "currentBalance": str(row.balance),
            "netMovement": str((row.balance or Decimal("0")) - (row.opening_balance or Decimal("0"))),
        },
    }


@router.get("/banks", summary="Fictional bank directory")
def banks(session: DbSession) -> dict:
    rows = list(session.execute(select(Bank).order_by(Bank.country.asc(), Bank.name.asc())).scalars())
    return {
        "items": [ser.bank(b) for b in rows],
        "note": "Every institution and BIC listed here is fictional and exists only in this simulator.",
    }


@router.get("/statement/{account_number}", summary="Generate a camt.053 statement for an account")
def statement(account_number: str, session: DbSession) -> dict:
    from datetime import timedelta

    from app.core.identifiers import utcnow

    account = session.execute(
        select(Account).where(Account.account_number == account_number).limit(1)
    ).scalar_one_or_none()
    if account is None:
        raise not_found(f"Account '{account_number}' not found")
    entries = list(
        session.execute(
            select(StatementEntry)
            .where(StatementEntry.account_id == account.id)
            .order_by(StatementEntry.id.asc())
        ).scalars()
    )
    today = utcnow().date()
    built = MessageEngine(session).build_camt053(
        account,
        entries,
        opening_balance=account.opening_balance or Decimal("0"),
        closing_balance=account.balance or Decimal("0"),
        from_date=today - timedelta(days=1),
        to_date=today,
    )
    return {
        "account": ser.account(account),
        "messageType": built.message_type.value,
        "messageId": built.message_id,
        "isoIdentifier": built.iso_identifier,
        "businessSummary": built.business_summary,
        "payload": built.xml,
        "payloadFormat": "XML",
        "entries": [ser.statement_entry(e) for e in entries],
    }


# ---------------------------------------------------------------------------
# message explorer
# ---------------------------------------------------------------------------


@router.get("/messages", summary="All messages across payments")
def messages(
    session: DbSession,
    pageSize: PageSize,
    page: int = Query(default=1, ge=1),
    messageType: Annotated[list[str] | None, Query()] = None,
    direction: str | None = None,
    query: str | None = None,
) -> dict:
    stmt = select(PaymentMessage)
    if messageType:
        stmt = stmt.where(PaymentMessage.message_type.in_(messageType))
    if direction:
        stmt = stmt.where(PaymentMessage.direction == direction.upper())
    if query:
        like = f"%{query}%"
        stmt = stmt.where(
            or_(PaymentMessage.message_id.ilike(like), PaymentMessage.correlation_id.ilike(like))
        )
    total = session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = list(
        session.execute(
            stmt.order_by(PaymentMessage.created_at.desc(), PaymentMessage.id.desc())
            .offset((page - 1) * pageSize)
            .limit(pageSize)
        ).scalars()
    )
    refs = dict(
        session.execute(
            select(Payment.id, Payment.reference).where(
                Payment.id.in_({r.payment_id for r in rows} or {0})
            )
        ).all()
    )
    counts = dict(
        session.execute(
            select(PaymentMessage.message_type, func.count(PaymentMessage.id)).group_by(
                PaymentMessage.message_type
            )
        ).all()
    )
    return {
        "items": [
            {**ser.message(m, include_xml=False), "paymentReference": refs.get(m.payment_id)}
            for m in rows
        ],
        "total": total,
        "page": page,
        "pageSize": pageSize,
        "byType": counts,
        "catalogue": [
            {
                "messageType": message.value,
                "name": meta["name"],
                "isoIdentifier": meta["iso_identifier"],
                "direction": meta["direction"],
                "purpose": meta["purpose"],
                "count": counts.get(message.value, 0),
            }
            for message, meta in MESSAGE_METADATA.items()
        ],
    }


@router.get("/messages/catalogue", summary="ISO 20022 message catalogue")
def message_catalogue(session: DbSession) -> dict:
    counts = dict(
        session.execute(
            select(PaymentMessage.message_type, func.count(PaymentMessage.id)).group_by(
                PaymentMessage.message_type
            )
        ).all()
    )
    return {
        "items": [
            {
                "messageType": message.value,
                "name": meta["name"],
                "isoIdentifier": meta["iso_identifier"],
                "direction": meta["direction"],
                "purpose": meta["purpose"],
                "count": counts.get(message.value, 0),
                "usedBySchemes": [
                    s.code.value for s in list_schemes() if message in s.messages.message_set
                ],
            }
            for message, meta in MESSAGE_METADATA.items()
        ],
        "simulationNote": (
            "Messages are structurally realistic but are not validated against the official ISO "
            "20022 XSDs and are never transmitted to a real network."
        ),
    }


@router.get("/messages/mt-mx", summary="MT103 to pacs.008 mapping reference")
def mt_mx_reference() -> dict:
    return {
        "source": "MT103",
        "target": "pacs.008.001.08",
        "rows": mt.mapping_rows(),
        "mappingTypes": [
            {
                "type": "DIRECT",
                "meaning": "The MT field maps onto one MX element with the same meaning.",
            },
            {
                "type": "TRANSFORMED",
                "meaning": (
                    "The value must be split, combined, re-coded or restructured. The information "
                    "survives, the shape does not."
                ),
            },
            {
                "type": "DERIVED",
                "meaning": (
                    "The MX element is not copied from the MT field; it is inferred from the "
                    "message type, the scheme or the processing context."
                ),
            },
            {
                "type": "NO_DIRECT_EQUIVALENT",
                "meaning": (
                    "There is no faithful mapping. Either MX adds structure MT cannot express, or "
                    "MT carries free text that MX has no home for."
                ),
            },
        ],
        "warning": (
            "There is no universal one-to-one MT to MX mapping. The authoritative rules are the "
            "CBPR+ usage guidelines and the published translation rules; this table is an "
            "educational comparison, not an implementation specification."
        ),
    }


# ---------------------------------------------------------------------------
# search and config
# ---------------------------------------------------------------------------


@router.get("/search", summary="Command centre search")
def search(service: Search, q: str = Query(default="", max_length=200), limit: int = Query(12, ge=1, le=50)) -> dict:
    return {"query": q, "items": service.search(q, limit)}


@router.get("/config", summary="Effective configuration (no secrets)")
def config() -> dict:
    return {
        "appName": settings.APP_NAME,
        "appVersion": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "demoMode": settings.DEMO_MODE,
        "simulationSpeedFactor": settings.SIMULATION_SPEED_FACTOR,
        "clearingTimeoutSecondsFallback": settings.CLEARING_TIMEOUT_SECONDS,
        "schedulerEnabled": settings.SCHEDULER_ENABLED,
        "schedulerPollIntervalSeconds": settings.SCHEDULER_POLL_INTERVAL_SECONDS,
        "maxPageSize": settings.MAX_PAGE_SIZE,
        "rateLimitEnabled": settings.RATE_LIMIT_ENABLED,
        "aiEnabled": settings.AI_ENABLED,
        "aiProvider": settings.AI_PROVIDER if settings.AI_ENABLED else None,
        "aiModel": settings.AI_MODEL if settings.AI_ENABLED else None,
        "database": "sqlite" if settings.is_sqlite else "postgresql",
        "currencies": [
            {"code": code, "name": CURRENCY_NAMES.get(code, code)} for code in SUPPORTED_CURRENCIES
        ],
        "schemeTimeouts": [
            {
                "scheme": scheme.code.value,
                "realisticSeconds": scheme.clearing.realistic_timeout_seconds,
                "acceleratedSeconds": round(clearing_timeout_seconds(scheme), 2),
            }
            for scheme in list_schemes()
        ],
        "simulationDisclaimer": (
            "This application is a simulator. It is standards-inspired, contains only fictional "
            "data, and is not an implementation of any bank, SWIFT, SIC, SEPA or clearing system."
        ),
    }


@router.get("/enums", summary="Enumerations the UI renders")
def enums() -> dict:
    return {
        "paymentStatuses": [s.value for s in PaymentStatus],
        "stageKeys": [s.value for s in StageKey],
        "messageTypes": [m.value for m in MessageType],
        "eventTypes": [e.value for e in EventType],
        "sourceSystems": [s.value for s in SourceSystem],
        "severities": [s.value for s in Severity],
        "validationCategories": [c.value for c in ValidationCategory],
        "reconciliationStatuses": [r.value for r in ReconciliationStatus],
        "accountTypes": [a.value for a in AccountType],
        "currencies": list(SUPPORTED_CURRENCIES),
    }


@router.get("/reseed", summary="Reseed reference data, rules and scenarios")
def reseed(session: DbSession) -> dict:
    from app.seed import seed_static_data

    try:
        summary = seed_static_data(session)
    except Exception as exc:  # pragma: no cover
        raise bad_request(f"Seeding failed: {exc}") from exc
    return {"seeded": True, **summary}
