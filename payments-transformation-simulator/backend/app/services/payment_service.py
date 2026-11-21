"""Payment application service.

Owns creation, lookup and the operator actions the API exposes. All lifecycle
behaviour is delegated to the orchestrator; this layer deals with input mapping,
identifier assignment and querying.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.api.schemas import PaymentCreate
from app.core.identifiers import (
    correlation_id,
    end_to_end_id,
    instruction_id,
    payment_reference,
    transaction_id,
    uetr,
    utcnow,
)
from app.core.logging import get_logger
from app.db.models import (
    Account,
    ClearingTransaction,
    Investigation,
    Payment,
    PaymentParty,
    ReconciliationRecord,
    SettlementTransaction,
    StatementEntry,
)
from app.domain.enums import (
    AccountType,
    EventType,
    PaymentStatus,
    ProcessingMode,
    SourceSystem,
)
from app.domain.identifiers_bank import normalise_bic, normalise_iban
from app.domain.money import quantize
from app.engines.accounting import AccountingEngine
from app.engines.clearing import ClearingAdapter
from app.engines.events import EventRecorder
from app.engines.failure_injection import FailureInjectionEngine
from app.engines.investigation import InvestigationDesk
from app.engines.messaging.engine import MessageEngine
from app.engines.orchestrator import PaymentOrchestrator
from app.engines.reconciliation import ReconciliationEngine
from app.engines.settlement import SettlementEngine
from app.schemes.registry import get_scheme

logger = get_logger(__name__)


@dataclass(slots=True)
class PaymentPage:
    items: list[Payment]
    total: int
    page: int
    page_size: int


class PaymentService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.orchestrator = PaymentOrchestrator(session)
        self.events = EventRecorder(session)
        self.injections = FailureInjectionEngine(session)
        self.messages = MessageEngine(session)
        self.clearing = ClearingAdapter(session)
        self.settlement = SettlementEngine(session)
        self.accounting = AccountingEngine(session)
        self.reconciliation = ReconciliationEngine(session)
        self.investigations = InvestigationDesk(session)

    # ------------------------------------------------------------------
    # creation
    # ------------------------------------------------------------------
    def create(
        self,
        payload: PaymentCreate,
        *,
        is_demo_data: bool = False,
        scenario_code: str | None = None,
    ) -> Payment:
        scheme = get_scheme(payload.scheme)
        now = utcnow()
        currency = (payload.currency or scheme.rules.settlement_currency).upper()

        debtor_iban = normalise_iban(payload.debtor.iban) or None
        debtor_account = self._resolve_debtor_account(
            iban=debtor_iban,
            account_number=payload.debtorAccountNumber or payload.debtor.accountIdentifier or None,
            currency=currency,
        )

        payment = Payment(
            reference=payment_reference(),
            correlation_id=correlation_id(),
            scheme=scheme.code.value,
            status=PaymentStatus.DRAFT.value,
            processing_mode=payload.processingMode,
            direction="OUTBOUND",
            amount=quantize(payload.amount, currency),
            currency=currency,
            requested_execution_date=payload.requestedExecutionDate or now.date(),
            instruction_id=payload.instructionId or instruction_id(),
            end_to_end_id=payload.endToEndId or end_to_end_id(),
            transaction_id=payload.transactionId or transaction_id(),
            uetr=(payload.uetr or uetr()) if scheme.rules.uses_uetr else payload.uetr,
            remittance_information=payload.remittanceInformation,
            remittance_structured=payload.remittanceStructured or {},
            purpose_code=payload.purposeCode,
            category_purpose=payload.categoryPurpose,
            service_level=payload.serviceLevel
            or (scheme.rules.allowed_service_levels[0] if scheme.rules.allowed_service_levels else None),
            local_instrument=payload.localInstrument
            or (scheme.rules.allowed_local_instruments[0] if scheme.rules.allowed_local_instruments else None),
            clearing_channel=payload.clearingChannel or scheme.messages.clearing_system_proprietary,
            charge_bearer=payload.chargeBearer or scheme.rules.allowed_charge_bearers[0],
            priority=payload.priority or ("HIGH" if scheme.rules.is_instant else "NORM"),
            debtor_account_id=debtor_account.id if debtor_account else None,
            created_at=now,
            updated_at=now,
            created_by=payload.createdBy,
            source=payload.source,
            is_demo_data=is_demo_data,
            scenario_code=scenario_code,
            notes=payload.notes,
            tags=list(payload.tags or []),
        )
        self.session.add(payment)
        self.session.flush()

        for role, data in (("DEBTOR", payload.debtor), ("CREDITOR", payload.creditor)):
            self.session.add(
                PaymentParty(
                    payment_id=payment.id,
                    role=role,
                    name=data.name,
                    account_identifier=data.accountIdentifier,
                    iban=normalise_iban(data.iban) or None,
                    bic=normalise_bic(data.bic) or None,
                    bank_name=data.bankName,
                    country=(data.country or "").upper(),
                    town=data.town,
                    address_lines=list(data.addressLines or []),
                )
            )
        self.session.flush()
        self.session.refresh(payment)

        self.orchestrator.ensure_stages(payment)
        self.events.bind_context(payment)
        self.events.record(
            payment,
            EventType.PAYMENT_CREATED,
            SourceSystem.CHANNEL,
            f"Payment {payment.reference} created for {payment.amount} {payment.currency}",
            detail={
                "scheme": scheme.name,
                "endToEndId": payment.end_to_end_id,
                "instructionId": payment.instruction_id,
                "uetr": payment.uetr,
                "debtorAccount": debtor_account.account_number if debtor_account else None,
            },
        )
        self.events.audit(
            actor=payload.createdBy,
            action="CREATE",
            entity_type="Payment",
            entity_id=payment.reference,
            reason="Payment created through the simulator",
            after={
                "amount": str(payment.amount),
                "currency": payment.currency,
                "scheme": payment.scheme,
                "status": payment.status,
            },
            correlation_id=payment.correlation_id,
        )

        for injection in payload.failureInjections:
            try:
                self.injections.register(payment, injection.code, injection.parameters)
            except KeyError:
                logger.warning("unknown failure injection ignored", extra={"code": injection.code})

        self.set_initiated(payment)
        return payment

    def set_initiated(self, payment: Payment) -> None:
        if payment.status == PaymentStatus.DRAFT.value:
            self.orchestrator.set_status(
                payment, PaymentStatus.INITIATED, reason="Instruction accepted by the channel"
            )

    def _resolve_debtor_account(
        self, *, iban: str | None, account_number: str | None, currency: str
    ) -> Account | None:
        if iban:
            account = self.session.execute(
                select(Account).where(Account.iban == iban).limit(1)
            ).scalar_one_or_none()
            if account is not None:
                return account
        if account_number:
            account = self.session.execute(
                select(Account).where(Account.account_number == account_number).limit(1)
            ).scalar_one_or_none()
            if account is not None:
                return account
        return self.session.execute(
            select(Account)
            .where(
                Account.account_type == AccountType.CUSTOMER.value,
                Account.currency == currency,
                Account.is_active.is_(True),
            )
            .order_by(Account.id.asc())
            .limit(1)
        ).scalar_one_or_none()

    # ------------------------------------------------------------------
    # lookup
    # ------------------------------------------------------------------
    def get(self, identifier: str | int) -> Payment | None:
        if isinstance(identifier, int) or str(identifier).isdigit():
            payment = self.session.get(Payment, int(identifier))
            if payment is not None:
                return payment
        token = str(identifier).strip()
        stmt = select(Payment).where(
            or_(
                Payment.reference == token,
                Payment.reference == token.upper(),
                Payment.end_to_end_id == token,
                Payment.instruction_id == token,
                Payment.transaction_id == token,
                Payment.uetr == token.lower(),
                Payment.correlation_id == token.upper(),
            )
        )
        return self.session.execute(stmt.limit(1)).scalar_one_or_none()

    def require(self, identifier: str | int) -> Payment:
        payment = self.get(identifier)
        if payment is None:
            raise LookupError(f"Payment '{identifier}' not found")
        return payment

    def search(
        self,
        *,
        page: int = 1,
        page_size: int = 25,
        status: list[str] | None = None,
        scheme: list[str] | None = None,
        currency: list[str] | None = None,
        query: str | None = None,
        failures_only: bool = False,
        amount_min: Decimal | None = None,
        amount_max: Decimal | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        sort: str = "createdAt",
        direction: str = "desc",
    ) -> PaymentPage:
        stmt: Select = select(Payment)
        if status:
            stmt = stmt.where(Payment.status.in_(status))
        if scheme:
            stmt = stmt.where(Payment.scheme.in_(scheme))
        if currency:
            stmt = stmt.where(Payment.currency.in_([c.upper() for c in currency]))
        if failures_only:
            stmt = stmt.where(
                Payment.status.in_([s.value for s in PaymentStatus if s.is_failure])
            )
        if amount_min is not None:
            stmt = stmt.where(Payment.amount >= amount_min)
        if amount_max is not None:
            stmt = stmt.where(Payment.amount <= amount_max)
        if created_from is not None:
            stmt = stmt.where(Payment.created_at >= created_from)
        if created_to is not None:
            stmt = stmt.where(Payment.created_at <= created_to)
        if query:
            token = query.strip()
            like = f"%{token}%"
            stmt = stmt.where(
                or_(
                    Payment.reference.ilike(like),
                    Payment.end_to_end_id.ilike(like),
                    Payment.instruction_id.ilike(like),
                    Payment.transaction_id.ilike(like),
                    Payment.uetr.ilike(like),
                    Payment.correlation_id.ilike(like),
                    Payment.id.in_(
                        select(PaymentParty.payment_id).where(
                            or_(
                                PaymentParty.name.ilike(like),
                                PaymentParty.iban.ilike(like),
                                PaymentParty.bic.ilike(like),
                            )
                        )
                    ),
                    Payment.id.in_(
                        select(ClearingTransaction.payment_id).where(
                            ClearingTransaction.clearing_reference.ilike(like)
                        )
                    ),
                    Payment.id.in_(
                        select(SettlementTransaction.payment_id).where(
                            SettlementTransaction.settlement_reference.ilike(like)
                        )
                    ),
                )
            )

        total = self.session.execute(
            select(func.count()).select_from(stmt.subquery())
        ).scalar_one()

        sort_column = {
            "createdAt": Payment.created_at,
            "updatedAt": Payment.updated_at,
            "amount": Payment.amount,
            "status": Payment.status,
            "reference": Payment.reference,
            "scheme": Payment.scheme,
        }.get(sort, Payment.created_at)
        ordering = sort_column.desc() if direction.lower() == "desc" else sort_column.asc()
        page = max(1, page)
        rows = list(
            self.session.execute(
                stmt.order_by(ordering, Payment.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            .scalars()
            .unique()
        )
        return PaymentPage(items=rows, total=total, page=page, page_size=page_size)

    # ------------------------------------------------------------------
    # aggregate views
    # ------------------------------------------------------------------
    def full_view(self, payment: Payment) -> dict[str, Any]:
        from app.api import serializers as ser
        from app.db.models import ValidationResult
        from app.engines.messaging import mt
        from app.engines.state_machine import allowed_targets

        validation_rows = list(
            self.session.execute(
                select(ValidationResult)
                .where(ValidationResult.payment_id == payment.id)
                .order_by(ValidationResult.run_id.asc(), ValidationResult.id.asc())
            ).scalars()
        )
        statement_rows = list(
            self.session.execute(
                select(StatementEntry)
                .where(StatementEntry.payment_id == payment.id)
                .order_by(StatementEntry.id.asc())
            ).scalars()
        )
        scheme = get_scheme(payment.scheme)
        return ser.payment_detail(
            payment,
            extras={
                "schemeDetail": scheme.as_dict(),
                "events": [ser.event(e) for e in self.events.for_payment(payment.id)],
                "validations": [ser.validation(v) for v in validation_rows],
                "messages": [ser.message(m) for m in self.messages.all_for_payment(payment.id)],
                "clearing": [ser.clearing(c) for c in self.clearing.all_for_payment(payment.id)],
                "settlements": [ser.settlement(s) for s in self.settlement.all_for_payment(payment.id)],
                "accountingEntries": [
                    ser.accounting_entry(a) for a in self.accounting.entries_for_payment(payment.id)
                ],
                "statementEntries": [ser.statement_entry(s) for s in statement_rows],
                "reconciliationRecords": [
                    ser.reconciliation(r) for r in self.reconciliation.records_for_payment(payment.id)
                ],
                "investigations": [
                    ser.investigation(i) for i in self.investigations.open_for_payment(payment.id)
                ],
                "mtMxMapping": mt.mapping_rows(payment) if scheme.rules.uses_uetr else [],
                "pendingJobs": [
                    {
                        "jobType": j.job_type,
                        "dueAt": j.due_at.isoformat(),
                        "status": j.status,
                    }
                    for j in self.orchestrator.pending_jobs(payment.id)
                ],
                "allowedTransitions": allowed_targets(payment.status),
            },
        )

    def statistics(self) -> dict[str, Any]:
        rows = self.session.execute(
            select(Payment.status, func.count(Payment.id)).group_by(Payment.status)
        ).all()
        by_status = dict(rows)
        scheme_rows = self.session.execute(
            select(Payment.scheme, func.count(Payment.id)).group_by(Payment.scheme)
        ).all()
        currency_rows = self.session.execute(
            select(Payment.currency, func.count(Payment.id), func.sum(Payment.amount)).group_by(
                Payment.currency
            )
        ).all()
        failure_statuses = [s.value for s in PaymentStatus if s.is_failure]
        total = sum(by_status.values())
        failures = sum(count for status, count in by_status.items() if status in failure_statuses)
        open_investigations = self.session.execute(
            select(func.count(Investigation.id)).where(
                Investigation.status.in_(("OPEN", "IN_PROGRESS", "AWAITING_RESPONSE"))
            )
        ).scalar_one()
        recon_breaks = self.session.execute(
            select(func.count(ReconciliationRecord.id)).where(
                ReconciliationRecord.status.notin_(("MATCHED", "NOT_RUN"))
            )
        ).scalar_one()
        unmatched_statements = self.session.execute(
            select(func.count(StatementEntry.id)).where(StatementEntry.is_orphan.is_(True))
        ).scalar_one()
        latency = self.session.execute(
            select(func.avg(ClearingTransaction.response_latency_ms)).where(
                ClearingTransaction.response_latency_ms.isnot(None)
            )
        ).scalar()
        last_24h = self.session.execute(
            select(func.count(Payment.id)).where(Payment.created_at >= utcnow() - timedelta(hours=24))
        ).scalar_one()
        return {
            "totalPayments": total,
            "byStatus": by_status,
            "byScheme": dict(scheme_rows),
            "byCurrency": [
                {"currency": ccy, "count": count, "total": str(amount or Decimal("0"))}
                for ccy, count, amount in currency_rows
            ],
            "failureCount": failures,
            "successRate": round(((total - failures) / total) * 100, 1) if total else 0.0,
            "openInvestigations": open_investigations,
            "reconciliationBreaks": recon_breaks,
            "unmatchedStatementEntries": unmatched_statements,
            "averageClearingLatencyMs": int(latency) if latency else None,
            "createdLast24h": last_24h,
        }

    # ------------------------------------------------------------------
    # actions
    # ------------------------------------------------------------------
    def execute(self, payment: Payment, mode: ProcessingMode | None = None):  # noqa: ANN201
        return self.orchestrator.execute(payment, mode=mode)

    def reconcile_now(self, payment: Payment, actor: str = "payments.operations"):  # noqa: ANN201
        outcome = self.reconciliation.reconcile_payment(payment)
        self.events.record(
            payment,
            EventType.RECONCILIATION_RUN,
            SourceSystem.RECONCILIATION_ENGINE,
            f"Manual reconciliation run {outcome.record.reference}: {outcome.status.value}",
            detail={"reference": outcome.record.reference, "status": outcome.status.value},
        )
        self.events.audit(
            actor=actor,
            action="RECONCILE",
            entity_type="Payment",
            entity_id=payment.reference,
            reason="Manual reconciliation requested",
            after={"status": outcome.status.value, "reference": outcome.record.reference},
            correlation_id=payment.correlation_id,
        )
        return outcome
