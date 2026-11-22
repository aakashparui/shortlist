"""Reconciliation engine.

Reconciliation compares four views of the same payment:

    1. INTERNAL    the payment record held by the payment engine
    2. ACCOUNTING  the general-ledger journal posted for the payment
    3. CLEARING    the clearing system's own record of the instruction
    4. STATEMENT   the account servicer's camt.054 / camt.053 entry

The statement leg is the external source of truth, exactly as it is in a real
operations team: if the statement and the internal record disagree, the internal
record is the one under suspicion.

SIMPLIFIED MODEL: production reconciliation engines match many-to-many across
batches with tolerance rules, ageing and auto-matching heuristics. This engine
reconciles one payment at a time plus unmatched statement entries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.identifiers import reconciliation_reference, statement_entry_reference, utcnow
from app.core.logging import get_logger
from app.db.models import (
    Account,
    AccountingEntry,
    ClearingTransaction,
    FailureInjection,
    Payment,
    ReconciliationRecord,
    SettlementTransaction,
    StatementEntry,
)
from app.domain.enums import (
    AccountingStatus,
    ClearingStatus,
    EntrySide,
    FailureCategory,
    ReconciliationStatus,
)
from app.domain.money import quantize

logger = get_logger(__name__)

RECONCILIATION_INJECTIONS = {
    "RECON_MISSING_CAMT054",
    "RECON_AMOUNT_MISMATCH",
    "RECON_CURRENCY_MISMATCH",
    "RECON_DUPLICATE_SETTLEMENT",
    "RECON_UNMATCHED_STATEMENT",
    "RECON_TIMING_DIFFERENCE",
    "RECON_REFERENCE_MISMATCH",
}

CAUSE_LIBRARY: dict[ReconciliationStatus, tuple[str, str]] = {
    ReconciliationStatus.MATCHED: (
        "All four views agree on amount, currency and reference.",
        "No action required. The payment can be closed.",
    ),
    ReconciliationStatus.MISSING_ENTRY: (
        "The statement does not contain an entry for this payment. Either the account servicer "
        "never sent the camt.054 notification, the notification was dropped in transit, or the "
        "booking happened after the statement cut-off.",
        "Request a statement re-send for the account and date. If the entry is genuinely absent, "
        "confirm with the settlement agent whether the movement occurred before releasing any "
        "credit to the customer.",
    ),
    ReconciliationStatus.AMOUNT_MISMATCH: (
        "The statement amount differs from the internal amount. Common causes are correspondent "
        "charges deducted in transit, an FX rate applied at a different time, or a partial "
        "settlement.",
        "Compare the statement narrative against the charge-bearer instruction. If charges were "
        "deducted against an SLEV/DEBT instruction, raise a claim with the deducting agent.",
    ),
    ReconciliationStatus.CURRENCY_MISMATCH: (
        "The statement entry is denominated in a different currency from the internal record. "
        "This normally points at the wrong nostro account being credited, or an accounting "
        "configuration error on the settlement leg.",
        "Suspend auto-matching for the account, verify the nostro account mapping for this "
        "currency, and correct the posting before the next cut-off.",
    ),
    ReconciliationStatus.DUPLICATE: (
        "More than one statement entry matches the same payment reference. The payment was either "
        "settled twice or notified twice.",
        "Establish whether value moved twice. If so, initiate a return of the duplicate amount "
        "and inform the counterparty; if only the notification duplicated, suppress the second "
        "entry from matching.",
    ),
    ReconciliationStatus.TIMING_DIFFERENCE: (
        "The amounts agree but the booking date falls in a different reconciliation period from "
        "the internal record. This is a cut-off difference rather than a value difference.",
        "Carry the item forward as a timing difference and confirm it clears on the following "
        "statement. No customer impact is expected.",
    ),
    ReconciliationStatus.REFERENCE_MISMATCH: (
        "An entry of the right amount and currency exists, but its end-to-end reference does not "
        "match the internal record, so automatic matching failed.",
        "Match manually on amount, date and counterparty, then investigate why the reference was "
        "not carried through the chain.",
    ),
    ReconciliationStatus.UNMATCHED: (
        "No statement entry could be associated with this payment, and no other view explains "
        "the difference.",
        "Open an investigation and trace the payment from the clearing reference forward.",
    ),
}


@dataclass(slots=True)
class ReconciliationLeg:
    name: str
    source: str
    reference: str | None
    amount: Decimal | None
    currency: str | None
    booking_date: date | None
    present: bool
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "source": self.source,
            "reference": self.reference,
            "amount": str(self.amount) if self.amount is not None else None,
            "currency": self.currency,
            "bookingDate": self.booking_date.isoformat() if self.booking_date else None,
            "present": self.present,
            "note": self.note,
        }


@dataclass(slots=True)
class ReconciliationOutcome:
    record: ReconciliationRecord
    status: ReconciliationStatus
    legs: list[ReconciliationLeg] = field(default_factory=list)

    @property
    def is_break(self) -> bool:
        return self.status.is_break


class StatementFeedSimulator:
    """Produces the statement entries that reconciliation later matches against.

    This stands in for the account servicer: it is what turns a posted journal
    into an externally visible camt.054 entry.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def injections(self, payment: Payment) -> dict[str, dict]:
        rows = self.session.execute(
            select(FailureInjection).where(
                FailureInjection.payment_id == payment.id,
                FailureInjection.active.is_(True),
                FailureInjection.consumed.is_(False),
                FailureInjection.category == FailureCategory.RECONCILIATION.value,
            )
        ).scalars()
        found: dict[str, dict] = {}
        for row in rows:
            if row.code in RECONCILIATION_INJECTIONS:
                found[row.code] = dict(row.parameters or {})
                row.consumed = True
                row.effect_summary = (
                    f"Reconciliation anomaly '{row.code}' applied to {payment.reference}."
                )
        if found:
            self.session.flush()
        return found

    def publish(
        self,
        payment: Payment,
        account: Account | None,
        *,
        amount: Decimal,
        currency: str,
        side: EntrySide = EntrySide.DEBIT,
        narrative: str = "",
    ) -> tuple[list[StatementEntry], dict[str, dict]]:
        """Create the statement entries for a payment, applying any injections."""
        injections = self.injections(payment)
        entries: list[StatementEntry] = []
        if account is None:
            return entries, injections

        now = utcnow()
        booking = now.date()
        value = booking
        entry_amount = quantize(amount, currency)
        entry_currency = currency
        end_to_end = payment.end_to_end_id

        if "RECON_MISSING_CAMT054" in injections:
            logger.info(
                "statement notification suppressed by injection",
                extra={"payment_reference": payment.reference},
            )
            return entries, injections

        if "RECON_AMOUNT_MISMATCH" in injections:
            delta = Decimal(str(injections["RECON_AMOUNT_MISMATCH"].get("deltaAmount", "-50.00")))
            entry_amount = quantize(entry_amount + delta, entry_currency)
        if "RECON_CURRENCY_MISMATCH" in injections:
            entry_currency = str(injections["RECON_CURRENCY_MISMATCH"].get("currency", "EUR")).upper()
        if "RECON_TIMING_DIFFERENCE" in injections:
            days = int(injections["RECON_TIMING_DIFFERENCE"].get("bookingDateOffsetDays", 2))
            booking = booking + timedelta(days=days)
        if "RECON_REFERENCE_MISMATCH" in injections:
            end_to_end = str(
                injections["RECON_REFERENCE_MISMATCH"].get("endToEndId", f"{payment.end_to_end_id}X")
            )

        entries.append(
            self._entry(
                payment,
                account,
                side=side,
                amount=entry_amount,
                currency=entry_currency,
                booking_date=booking,
                value_date=value,
                end_to_end_id=end_to_end,
                narrative=narrative or f"Payment {payment.reference}",
            )
        )

        if "RECON_DUPLICATE_SETTLEMENT" in injections:
            entries.append(
                self._entry(
                    payment,
                    account,
                    side=side,
                    amount=entry_amount,
                    currency=entry_currency,
                    booking_date=booking,
                    value_date=value,
                    end_to_end_id=end_to_end,
                    narrative=f"DUPLICATE settlement notification for {payment.reference}",
                )
            )

        if "RECON_UNMATCHED_STATEMENT" in injections:
            params = injections["RECON_UNMATCHED_STATEMENT"]
            orphan_amount = quantize(
                Decimal(str(params.get("amount", entry_amount))), entry_currency
            )
            orphan = StatementEntry(
                payment_id=None,
                statement_reference=statement_entry_reference(),
                account_number=account.account_number,
                account_id=account.id,
                side=side.value,
                amount=orphan_amount,
                currency=entry_currency,
                booking_date=booking,
                value_date=value,
                end_to_end_id=str(params.get("endToEndId", "E2EUNKNOWN0000")),
                narrative="Unidentified movement on the account - no internal payment record",
                source_message_type="camt.053",
                is_orphan=True,
            )
            self.session.add(orphan)
            entries.append(orphan)

        self.session.flush()
        return entries, injections

    def _entry(
        self,
        payment: Payment,
        account: Account,
        *,
        side: EntrySide,
        amount: Decimal,
        currency: str,
        booking_date: date,
        value_date: date,
        end_to_end_id: str,
        narrative: str,
    ) -> StatementEntry:
        entry = StatementEntry(
            payment_id=payment.id,
            statement_reference=statement_entry_reference(),
            account_number=account.account_number,
            account_id=account.id,
            side=side.value,
            amount=amount,
            currency=currency,
            booking_date=booking_date,
            value_date=value_date,
            end_to_end_id=end_to_end_id,
            narrative=narrative[:240],
            source_message_type="camt.054",
        )
        self.session.add(entry)
        return entry


class ReconciliationEngine:
    def __init__(self, session: Session) -> None:
        self.session = session

    def reconcile_payment(self, payment: Payment) -> ReconciliationOutcome:
        now = utcnow()
        internal_amount = quantize(payment.amount, payment.currency)
        internal_currency = (payment.currency or "").upper()

        accounting_entries = list(
            self.session.execute(
                select(AccountingEntry).where(AccountingEntry.payment_id == payment.id)
            ).scalars()
        )
        debit_entries = [
            e
            for e in accounting_entries
            if e.side == EntrySide.DEBIT.value and e.status != AccountingStatus.REVERSED.value
        ]
        credit_entries = [
            e
            for e in accounting_entries
            if e.side == EntrySide.CREDIT.value and e.status != AccountingStatus.REVERSED.value
        ]
        clearing = self.session.execute(
            select(ClearingTransaction)
            .where(ClearingTransaction.payment_id == payment.id)
            .order_by(ClearingTransaction.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        settlement = self.session.execute(
            select(SettlementTransaction)
            .where(SettlementTransaction.payment_id == payment.id)
            .order_by(SettlementTransaction.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        statement_entries = list(
            self.session.execute(
                select(StatementEntry)
                .where(StatementEntry.payment_id == payment.id)
                .order_by(StatementEntry.id.asc())
            ).scalars()
        )

        legs: list[ReconciliationLeg] = [
            ReconciliationLeg(
                name="Internal payment record",
                source="payment",
                reference=payment.reference,
                amount=internal_amount,
                currency=internal_currency,
                booking_date=now.date(),
                present=True,
                note=f"End-to-end id {payment.end_to_end_id}",
            )
        ]

        accounting_amount = debit_entries[0].amount if debit_entries else None
        accounting_currency = debit_entries[0].currency if debit_entries else None
        legs.append(
            ReconciliationLeg(
                name="Accounting journal (customer debit)",
                source="accounting",
                reference=debit_entries[0].accounting_reference if debit_entries else None,
                amount=accounting_amount,
                currency=accounting_currency,
                booking_date=debit_entries[0].posting_date if debit_entries else None,
                present=bool(debit_entries),
                note=(
                    f"{len(credit_entries)} credit leg(s) posted"
                    if debit_entries
                    else "No customer debit entry found"
                ),
            )
        )
        legs.append(
            ReconciliationLeg(
                name="Clearing record",
                source="clearing",
                reference=clearing.clearing_reference if clearing else None,
                amount=clearing.amount if clearing else None,
                currency=clearing.currency if clearing else None,
                booking_date=clearing.sent_at.date() if clearing and clearing.sent_at else None,
                present=clearing is not None,
                note=f"Clearing status {clearing.status}" if clearing else "Never dispatched",
            )
        )
        matched_statement = statement_entries[0] if statement_entries else None
        legs.append(
            ReconciliationLeg(
                name="Statement entry (camt.054 / camt.053)",
                source="statement",
                reference=matched_statement.statement_reference if matched_statement else None,
                amount=matched_statement.amount if matched_statement else None,
                currency=matched_statement.currency if matched_statement else None,
                booking_date=matched_statement.booking_date if matched_statement else None,
                present=matched_statement is not None,
                note=(
                    f"{len(statement_entries)} entr{'y' if len(statement_entries) == 1 else 'ies'} "
                    f"on account {matched_statement.account_number}"
                    if matched_statement
                    else "No statement entry received"
                ),
            )
        )

        status, difference = self._classify(
            payment=payment,
            internal_amount=internal_amount,
            internal_currency=internal_currency,
            accounting_debits=debit_entries,
            accounting_credits=credit_entries,
            statement_entries=statement_entries,
            now_date=now.date(),
        )
        cause, action = CAUSE_LIBRARY.get(status, CAUSE_LIBRARY[ReconciliationStatus.UNMATCHED])

        record = ReconciliationRecord(
            payment_id=payment.id,
            reference=reconciliation_reference(),
            status=status.value,
            run_at=now,
            internal_reference=payment.reference,
            internal_amount=internal_amount,
            internal_currency=internal_currency,
            accounting_reference=debit_entries[0].accounting_reference if debit_entries else None,
            accounting_amount=accounting_amount,
            clearing_reference=clearing.clearing_reference if clearing else None,
            clearing_amount=clearing.amount if clearing else None,
            statement_reference=matched_statement.statement_reference if matched_statement else None,
            statement_amount=matched_statement.amount if matched_statement else None,
            statement_currency=matched_statement.currency if matched_statement else None,
            difference_amount=difference,
            probable_cause=cause,
            recommended_action=action,
            legs=[leg.as_dict() for leg in legs],
            detail={
                "statementEntryCount": len(statement_entries),
                "accountingEntryCount": len(accounting_entries),
                "settlementStatus": settlement.status if settlement else None,
                "settlementAmount": str(settlement.settlement_amount) if settlement else None,
                "settlementCurrency": settlement.settlement_currency if settlement else None,
                "clearingStatus": clearing.status if clearing else None,
                "orphanEntries": [
                    e.statement_reference for e in statement_entries if e.is_orphan
                ],
            },
        )
        self.session.add(record)
        self.session.flush()
        logger.info(
            "reconciliation executed",
            extra={
                "payment_reference": payment.reference,
                "reconciliation_reference": record.reference,
                "status": status.value,
            },
        )
        return ReconciliationOutcome(record=record, status=status, legs=legs)

    def _classify(
        self,
        *,
        payment: Payment,
        internal_amount: Decimal,
        internal_currency: str,
        accounting_debits: list[AccountingEntry],
        accounting_credits: list[AccountingEntry],
        statement_entries: list[StatementEntry],
        now_date: date,
    ) -> tuple[ReconciliationStatus, Decimal | None]:
        own_entries = [e for e in statement_entries if not e.is_orphan]

        # Accounting integrity first: a journal that does not balance is a break
        # regardless of what the statement says.
        if accounting_debits and not accounting_credits:
            return ReconciliationStatus.MISSING_ENTRY, internal_amount
        duplicate_credits = [e for e in accounting_credits if e.is_duplicate]
        if duplicate_credits:
            return ReconciliationStatus.DUPLICATE, duplicate_credits[0].amount
        for credit in accounting_credits:
            if credit.currency != internal_currency:
                return ReconciliationStatus.CURRENCY_MISMATCH, None
            if credit.amount != internal_amount:
                return ReconciliationStatus.AMOUNT_MISMATCH, credit.amount - internal_amount

        if not own_entries:
            return ReconciliationStatus.MISSING_ENTRY, internal_amount

        if len(own_entries) > 1:
            return ReconciliationStatus.DUPLICATE, own_entries[1].amount

        entry = own_entries[0]
        if entry.currency != internal_currency:
            return ReconciliationStatus.CURRENCY_MISMATCH, None
        if entry.amount != internal_amount:
            return ReconciliationStatus.AMOUNT_MISMATCH, entry.amount - internal_amount
        if (entry.end_to_end_id or "") != (payment.end_to_end_id or ""):
            return ReconciliationStatus.REFERENCE_MISMATCH, None
        if entry.booking_date and entry.booking_date != now_date:
            return ReconciliationStatus.TIMING_DIFFERENCE, None
        return ReconciliationStatus.MATCHED, Decimal("0")

    # -- portfolio level -------------------------------------------------
    def unmatched_statement_entries(self) -> list[StatementEntry]:
        return list(
            self.session.execute(
                select(StatementEntry)
                .where(StatementEntry.is_orphan.is_(True))
                .order_by(StatementEntry.id.desc())
            ).scalars()
        )

    def records_for_payment(self, payment_id: int) -> list[ReconciliationRecord]:
        return list(
            self.session.execute(
                select(ReconciliationRecord)
                .where(ReconciliationRecord.payment_id == payment_id)
                .order_by(ReconciliationRecord.id.asc())
            ).scalars()
        )

    def clearing_without_statement(self) -> list[Payment]:
        """Payments the clearing system accepted but which never reached a statement."""
        stmt = (
            select(Payment)
            .join(ClearingTransaction, ClearingTransaction.payment_id == Payment.id)
            .outerjoin(StatementEntry, StatementEntry.payment_id == Payment.id)
            .where(
                ClearingTransaction.status == ClearingStatus.ACCEPTED.value,
                StatementEntry.id.is_(None),
            )
            .order_by(Payment.created_at.desc())
        )
        return list(self.session.execute(stmt).scalars().unique())
