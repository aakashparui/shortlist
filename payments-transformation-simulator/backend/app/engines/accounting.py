"""Double-entry accounting engine.

Each payment produces a balanced journal:

    DEBIT   customer account        (the debtor is debited)
    CREDIT  nostro / settlement a/c (the counter-position of the outgoing payment)

SIMPLIFIED MODEL: a real core-banking ledger has multi-currency position
keeping, suspense handling, charge and FX legs, accrual accounting and
end-of-day cut-off logic. This engine keeps one journal per payment so that a
break between the customer leg and the settlement leg is easy to observe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.identifiers import accounting_entry_id, accounting_reference, utcnow
from app.core.logging import get_logger
from app.db.models import Account, AccountingEntry, FailureInjection, Payment
from app.domain.enums import AccountingStatus, AccountType, EntrySide, FailureCategory
from app.domain.money import convert, quantize

logger = get_logger(__name__)


@dataclass(slots=True)
class AccountingResult:
    reference: str
    entries: list[AccountingEntry] = field(default_factory=list)
    balanced: bool = True
    break_reason: str | None = None
    break_detail: dict = field(default_factory=dict)
    anomalies: list[str] = field(default_factory=list)

    @property
    def total_debits(self) -> Decimal:
        return sum(
            (e.amount for e in self.entries if e.side == EntrySide.DEBIT.value), Decimal("0")
        )

    @property
    def total_credits(self) -> Decimal:
        return sum(
            (e.amount for e in self.entries if e.side == EntrySide.CREDIT.value), Decimal("0")
        )


ACCOUNTING_INJECTIONS = {
    "ACCOUNTING_MISSING_ENTRY",
    "ACCOUNTING_DUPLICATE_ENTRY",
    "ACCOUNTING_WRONG_AMOUNT",
    "ACCOUNTING_WRONG_CURRENCY",
    "ACCOUNTING_DELAYED_POSTING",
}


class AccountingEngine:
    def __init__(self, session: Session) -> None:
        self.session = session

    # -- injections -----------------------------------------------------
    def _injections(self, payment: Payment) -> dict[str, dict]:
        rows = self.session.execute(
            select(FailureInjection).where(
                FailureInjection.payment_id == payment.id,
                FailureInjection.active.is_(True),
                FailureInjection.consumed.is_(False),
                FailureInjection.category == FailureCategory.ACCOUNTING.value,
            )
        ).scalars()
        found: dict[str, dict] = {}
        for row in rows:
            if row.code in ACCOUNTING_INJECTIONS:
                found[row.code] = dict(row.parameters or {})
                row.consumed = True
                row.effect_summary = f"Accounting anomaly '{row.code}' applied to {payment.reference}."
        if found:
            self.session.flush()
        return found

    # -- accounts -------------------------------------------------------
    def settlement_account_for(self, payment: Payment, account_type: str) -> Account | None:
        currency = (payment.currency or "").upper()
        stmt = (
            select(Account)
            .where(
                Account.account_type == account_type,
                Account.currency == currency,
                Account.is_active.is_(True),
            )
            .order_by(Account.id.asc())
            .limit(1)
        )
        account = self.session.execute(stmt).scalar_one_or_none()
        if account is not None:
            return account
        # Fall back to any settlement-class account so the journal can still balance.
        return self.session.execute(
            select(Account)
            .where(
                Account.account_type.in_((AccountType.SETTLEMENT.value, AccountType.NOSTRO.value)),
                Account.is_active.is_(True),
            )
            .order_by(Account.id.asc())
            .limit(1)
        ).scalar_one_or_none()

    # -- posting --------------------------------------------------------
    def post_payment_journal(
        self,
        payment: Payment,
        *,
        settlement_account: Account | None,
        posting_date: date | None = None,
        value_date: date | None = None,
    ) -> AccountingResult:
        injections = self._injections(payment)
        reference = accounting_reference()
        now = utcnow()
        posting = posting_date or now.date()
        value = value_date or posting
        result = AccountingResult(reference=reference)

        debtor_account = payment.debtor_account
        credit_account = settlement_account

        currency = (payment.currency or "").upper()
        amount = quantize(payment.amount, currency)

        debit_amount = amount
        credit_amount = amount
        credit_currency = currency
        debit_status = AccountingStatus.POSTED

        if "ACCOUNTING_WRONG_AMOUNT" in injections:
            delta = Decimal(str(injections["ACCOUNTING_WRONG_AMOUNT"].get("deltaAmount", "-50.00")))
            credit_amount = quantize(amount + delta, currency)
            result.anomalies.append(
                f"Credit leg posted {credit_amount} instead of {amount} ({delta:+} injected)."
            )
        if "ACCOUNTING_WRONG_CURRENCY" in injections:
            credit_currency = str(injections["ACCOUNTING_WRONG_CURRENCY"].get("currency", "EUR")).upper()
            result.anomalies.append(
                f"Credit leg posted in {credit_currency} while the debit leg is in {currency}."
            )
        if "ACCOUNTING_DELAYED_POSTING" in injections:
            debit_status = AccountingStatus.PENDING
            result.anomalies.append(
                "Customer debit left in PENDING: the posting was accepted but not yet applied."
            )

        sequence = 1
        if debtor_account is not None:
            entry = self._entry(
                payment,
                reference,
                sequence,
                EntrySide.DEBIT,
                debtor_account,
                debit_amount,
                currency,
                posting,
                value,
                status=debit_status,
                narrative=f"Outgoing payment {payment.reference} to {payment.creditor.name if payment.creditor else 'beneficiary'}",
            )
            result.entries.append(entry)
            sequence += 1
            if debit_status is AccountingStatus.POSTED:
                self._apply_balance(
                    debtor_account,
                    self.balance_delta(debtor_account, EntrySide.DEBIT, debit_amount),
                    currency,
                )
                entry.balance_after = debtor_account.balance

        if "ACCOUNTING_MISSING_ENTRY" in injections:
            result.balanced = False
            result.break_reason = (
                "The customer account was debited but the corresponding settlement credit entry "
                "was never posted. The journal does not balance."
            )
            result.break_detail = {
                "missingLeg": "CREDIT",
                "expectedAccount": credit_account.account_number if credit_account else None,
                "expectedAmount": str(amount),
                "currency": currency,
            }
            result.anomalies.append("Settlement credit leg missing.")
        elif credit_account is not None:
            posted_amount = credit_amount
            if credit_currency != currency:
                try:
                    posted_amount = convert(credit_amount, currency, credit_currency)
                except ValueError:
                    posted_amount = credit_amount
            entry = self._entry(
                payment,
                reference,
                sequence,
                EntrySide.CREDIT,
                credit_account,
                posted_amount,
                credit_currency,
                posting,
                value,
                status=AccountingStatus.POSTED,
                narrative=f"Settlement counter-entry for {payment.reference}",
                anomaly_note=(
                    "Injected currency mismatch" if credit_currency != currency else None
                )
                or ("Injected amount mismatch" if credit_amount != amount else None),
            )
            result.entries.append(entry)
            sequence += 1
            self._apply_balance(
                credit_account,
                self.balance_delta(credit_account, EntrySide.CREDIT, posted_amount),
                credit_currency,
            )
            entry.balance_after = credit_account.balance

            if "ACCOUNTING_DUPLICATE_ENTRY" in injections:
                duplicate = self._entry(
                    payment,
                    reference,
                    sequence,
                    EntrySide.CREDIT,
                    credit_account,
                    posted_amount,
                    credit_currency,
                    posting,
                    value,
                    status=AccountingStatus.DUPLICATE,
                    narrative=f"DUPLICATE settlement counter-entry for {payment.reference}",
                    is_duplicate=True,
                    anomaly_note="Injected duplicate posting",
                )
                result.entries.append(duplicate)
                sequence += 1
                self._apply_balance(
                    credit_account,
                    self.balance_delta(credit_account, EntrySide.CREDIT, posted_amount),
                    credit_currency,
                )
                duplicate.balance_after = credit_account.balance
                result.balanced = False
                result.break_reason = (
                    "The settlement credit entry was posted twice, so the ledger is overstated "
                    "by the payment amount."
                )
                result.break_detail = {
                    "duplicatedEntryId": duplicate.entry_id,
                    "amount": str(posted_amount),
                    "currency": credit_currency,
                }
                result.anomalies.append("Duplicate credit leg posted.")

        if credit_currency != currency or credit_amount != amount:
            result.balanced = False
            result.break_reason = result.break_reason or (
                "Debit and credit legs do not agree: "
                f"debit {debit_amount} {currency} vs credit {credit_amount} {credit_currency}."
            )
            result.break_detail = result.break_detail or {
                "debit": f"{debit_amount} {currency}",
                "credit": f"{credit_amount} {credit_currency}",
            }

        if debit_status is AccountingStatus.PENDING:
            result.balanced = False
            result.break_reason = result.break_reason or (
                "The customer debit is still PENDING while the settlement credit has been posted."
            )

        self.session.flush()
        logger.info(
            "accounting journal posted",
            extra={
                "payment_reference": payment.reference,
                "accounting_reference": reference,
                "entries": len(result.entries),
                "balanced": result.balanced,
            },
        )
        return result

    def _entry(
        self,
        payment: Payment,
        reference: str,
        sequence: int,
        side: EntrySide,
        account: Account,
        amount: Decimal,
        currency: str,
        posting_date: date,
        value_date: date,
        *,
        status: AccountingStatus,
        narrative: str,
        is_duplicate: bool = False,
        anomaly_note: str | None = None,
    ) -> AccountingEntry:
        entry = AccountingEntry(
            payment_id=payment.id,
            entry_id=accounting_entry_id(),
            accounting_reference=reference,
            journal_sequence=sequence,
            side=side.value,
            account_id=account.id,
            account_number=account.account_number,
            account_name=account.name,
            account_type=account.account_type,
            amount=quantize(amount, currency),
            currency=currency,
            posting_date=posting_date,
            value_date=value_date,
            posted_at=utcnow(),
            status=status.value,
            narrative=narrative[:240],
            is_duplicate=is_duplicate,
            is_injected_anomaly=bool(anomaly_note),
            anomaly_note=anomaly_note,
        )
        self.session.add(entry)
        return entry

    @staticmethod
    def balance_delta(account: Account, side: EntrySide, amount: Decimal) -> Decimal:
        """How a posting moves the balance the account holder would recognise.

        The `balance` column is the account's own view of itself, not a signed
        ledger figure, so the direction depends on what kind of account it is:

        * **Liability** (customer deposits, a correspondent's vostro with us) —
          the money belongs to someone else and we owe it. A credit increases
          what we owe; a debit reduces it.
        * **Asset** (our nostro with a correspondent, a settlement account,
          suspense) — the money is ours and is held elsewhere. A debit increases
          what we hold; a credit reduces it.

        This is why an outgoing cross-border payment *reduces* the nostro: we
        are spending money we hold abroad, even though the ledger entry on that
        leg is a credit.
        """
        liability = account.account_type in (AccountType.CUSTOMER.value, AccountType.VOSTRO.value)
        if liability:
            return amount if side is EntrySide.CREDIT else -amount
        return amount if side is EntrySide.DEBIT else -amount

    def _apply_balance(self, account: Account, delta: Decimal, currency: str) -> None:
        if account.currency != currency:
            try:
                delta = convert(delta, currency, account.currency)
            except ValueError:
                return
        account.balance = quantize((account.balance or Decimal("0")) + delta, account.currency)

    # -- reversal (used by returns and reversals) ------------------------
    def reverse_journal(self, payment: Payment, reason: str) -> AccountingResult:
        original = list(
            self.session.execute(
                select(AccountingEntry)
                .where(
                    AccountingEntry.payment_id == payment.id,
                    AccountingEntry.status == AccountingStatus.POSTED.value,
                )
                .order_by(AccountingEntry.journal_sequence.asc())
            ).scalars()
        )
        reference = accounting_reference()
        result = AccountingResult(reference=reference)
        now = utcnow()
        for index, entry in enumerate(original, start=1):
            account = entry.account
            opposite = EntrySide.CREDIT if entry.side == EntrySide.DEBIT.value else EntrySide.DEBIT
            if account is None:
                continue
            reversal = self._entry(
                payment,
                reference,
                index,
                opposite,
                account,
                entry.amount,
                entry.currency,
                now.date(),
                now.date(),
                status=AccountingStatus.POSTED,
                narrative=f"Reversal of {entry.entry_id}: {reason}",
            )
            self._apply_balance(
                account, self.balance_delta(account, opposite, entry.amount), entry.currency
            )
            reversal.balance_after = account.balance
            result.entries.append(reversal)
            entry.status = AccountingStatus.REVERSED.value
        self.session.flush()
        return result

    def entries_for_payment(self, payment_id: int) -> list[AccountingEntry]:
        return list(
            self.session.execute(
                select(AccountingEntry)
                .where(AccountingEntry.payment_id == payment_id)
                .order_by(AccountingEntry.journal_sequence.asc(), AccountingEntry.id.asc())
            ).scalars()
        )
