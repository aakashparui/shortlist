"""Settlement engine.

Settlement is modelled as a distinct step from clearing: clearing decides
whether the instruction is accepted, settlement effects the movement of value
across the settlement or nostro account.

SIMPLIFIED MODEL: real settlement depends on liquidity management, settlement
windows, netting cycles and (for cross-border) correspondent value dating.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.identifiers import settlement_reference, utcnow
from app.core.logging import get_logger
from app.db.models import Account, FailureInjection, Payment, SettlementTransaction
from app.domain.enums import FailureCategory, SettlementStatus
from app.domain.money import convert, quantize
from app.schemes.base import PaymentScheme

logger = get_logger(__name__)

SETTLEMENT_INJECTIONS = {
    "SETTLEMENT_REJECTED",
    "SETTLEMENT_MISMATCH",
    "SETTLEMENT_PARTIAL",
    "SETTLEMENT_STATUS_NOT_UPDATED",
}


@dataclass(slots=True)
class SettlementResult:
    transaction: SettlementTransaction
    status: SettlementStatus
    failure_reason: str | None = None
    anomaly: str | None = None
    account: Account | None = None
    status_update_suppressed: bool = False

    @property
    def succeeded(self) -> bool:
        return self.status in (SettlementStatus.SETTLED, SettlementStatus.PARTIALLY_SETTLED)


class SettlementEngine:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _injections(self, payment: Payment) -> dict[str, dict]:
        rows = self.session.execute(
            select(FailureInjection).where(
                FailureInjection.payment_id == payment.id,
                FailureInjection.active.is_(True),
                FailureInjection.consumed.is_(False),
                FailureInjection.category == FailureCategory.SETTLEMENT.value,
            )
        ).scalars()
        found: dict[str, dict] = {}
        for row in rows:
            if row.code in SETTLEMENT_INJECTIONS:
                found[row.code] = dict(row.parameters or {})
                row.consumed = True
                row.effect_summary = f"Settlement anomaly '{row.code}' applied to {payment.reference}."
        if found:
            self.session.flush()
        return found

    def settlement_account(self, payment: Payment, scheme: PaymentScheme) -> Account | None:
        wanted_type = scheme.settlement.settlement_account_type
        currency = (
            scheme.rules.settlement_currency
            if scheme.settlement.settles_in_scheme_currency
            else (payment.currency or "").upper()
        )
        account = self.session.execute(
            select(Account)
            .where(
                Account.account_type == wanted_type,
                Account.currency == currency,
                Account.is_active.is_(True),
            )
            .order_by(Account.id.asc())
            .limit(1)
        ).scalar_one_or_none()
        if account is not None:
            return account
        return self.session.execute(
            select(Account)
            .where(Account.account_type == wanted_type, Account.is_active.is_(True))
            .order_by(Account.id.asc())
            .limit(1)
        ).scalar_one_or_none()

    def settle(self, payment: Payment, scheme: PaymentScheme) -> SettlementResult:
        injections = self._injections(payment)
        account = self.settlement_account(payment, scheme)
        now = utcnow()
        payment_currency = (payment.currency or "").upper()
        settlement_currency = (
            scheme.rules.settlement_currency
            if scheme.settlement.settles_in_scheme_currency
            else payment_currency
        )
        payment_amount = quantize(payment.amount, payment_currency)
        if settlement_currency != payment_currency:
            try:
                settlement_amount = convert(payment_amount, payment_currency, settlement_currency)
            except ValueError:
                settlement_currency = payment_currency
                settlement_amount = payment_amount
        else:
            settlement_amount = payment_amount

        status = SettlementStatus.SETTLED
        failure_reason: str | None = None
        anomaly: str | None = None
        iso_reason: str | None = None

        if "SETTLEMENT_REJECTED" in injections:
            status = SettlementStatus.FAILED
            failure_reason = str(
                injections["SETTLEMENT_REJECTED"].get(
                    "reason",
                    "Settlement was rejected: insufficient liquidity on the settlement account at "
                    "the time of the settlement cycle.",
                )
            )
            iso_reason = "AM04"
        elif "SETTLEMENT_PARTIAL" in injections:
            pct = Decimal(str(injections["SETTLEMENT_PARTIAL"].get("settledPercent", "60"))) / Decimal(100)
            settlement_amount = quantize(settlement_amount * pct, settlement_currency)
            status = SettlementStatus.PARTIALLY_SETTLED
            anomaly = (
                f"Only {settlement_amount} {settlement_currency} of "
                f"{payment_amount} {payment_currency} settled."
            )
            iso_reason = "AM09"
        elif "SETTLEMENT_MISMATCH" in injections:
            delta = Decimal(str(injections["SETTLEMENT_MISMATCH"].get("deltaAmount", "-50.00")))
            settlement_amount = quantize(settlement_amount + delta, settlement_currency)
            anomaly = (
                f"Settlement amount {settlement_amount} {settlement_currency} does not match the "
                f"payment amount {payment_amount} {payment_currency}."
            )
            iso_reason = "AM09"

        txn = SettlementTransaction(
            payment_id=payment.id,
            settlement_reference=settlement_reference(),
            status=status.value,
            payment_amount=payment_amount,
            payment_currency=payment_currency,
            settlement_amount=settlement_amount,
            settlement_currency=settlement_currency,
            settlement_method=scheme.settlement.settlement_method,
            settlement_account_id=account.id if account else None,
            value_date=scheme.value_date(now.date()),
            submitted_at=now,
            settled_at=now if status != SettlementStatus.FAILED else None,
            failure_reason=failure_reason,
            iso_reason_code=iso_reason,
            detail={
                "settlementSystem": scheme.clearing.clearing_system_name,
                "finality": scheme.clearing.settlement_finality,
                "accountType": scheme.settlement.settlement_account_type,
                "accountNumber": account.account_number if account else None,
                "fxApplied": settlement_currency != payment_currency,
                "anomaly": anomaly,
                "injections": sorted(injections),
            },
        )
        self.session.add(txn)
        self.session.flush()
        logger.info(
            "settlement processed",
            extra={
                "payment_reference": payment.reference,
                "settlement_reference": txn.settlement_reference,
                "status": status.value,
            },
        )
        return SettlementResult(
            transaction=txn,
            status=status,
            failure_reason=failure_reason,
            anomaly=anomaly,
            account=account,
            status_update_suppressed="SETTLEMENT_STATUS_NOT_UPDATED" in injections,
        )

    def reverse(self, payment: Payment, reason: str) -> SettlementTransaction | None:
        txn = self.latest(payment.id)
        if txn is None:
            return None
        txn.status = SettlementStatus.REVERSED.value
        txn.failure_reason = reason
        detail = dict(txn.detail or {})
        detail["reversedAt"] = utcnow().isoformat()
        txn.detail = detail
        self.session.flush()
        return txn

    def latest(self, payment_id: int) -> SettlementTransaction | None:
        return self.session.execute(
            select(SettlementTransaction)
            .where(SettlementTransaction.payment_id == payment_id)
            .order_by(SettlementTransaction.id.desc())
            .limit(1)
        ).scalar_one_or_none()

    def all_for_payment(self, payment_id: int) -> list[SettlementTransaction]:
        return list(
            self.session.execute(
                select(SettlementTransaction)
                .where(SettlementTransaction.payment_id == payment_id)
                .order_by(SettlementTransaction.id.asc())
            ).scalars()
        )
