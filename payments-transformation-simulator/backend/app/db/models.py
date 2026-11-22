"""Relational model for the Payments Transformation Simulator.

Design notes
------------
* The `Payment` row is the aggregate root. Every downstream artefact (message,
  event, validation result, clearing / settlement / accounting / reconciliation
  record, investigation) references it, and also carries its own business
  reference so an investigator can search from any direction.
* `correlation_id` is stamped on the payment and copied onto every event and
  message, giving one key that spans all subsystems.
* Enum columns are stored as short strings rather than database enums so that
  adding a new scheme or status needs no migration of a type.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.core.identifiers import utcnow
from app.db.types import Money, UTCDateTime


class Base(DeclarativeBase):
    type_annotation_map = {
        Decimal: Money,
        datetime: UTCDateTime,
        date: Date,
        dict: JSON,
        list: JSON,
    }


def _now() -> datetime:
    return utcnow()


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------


class Bank(Base):
    """Fictional financial institution directory."""

    __tablename__ = "bank"

    id: Mapped[int] = mapped_column(primary_key=True)
    bic: Mapped[str] = mapped_column(String(11), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(140))
    country: Mapped[str] = mapped_column(String(2), index=True)
    city: Mapped[str] = mapped_column(String(80), default="")
    national_clearing_code: Mapped[str | None] = mapped_column(String(20), default=None)
    is_direct_participant: Mapped[bool] = mapped_column(Boolean, default=True)
    supported_schemes: Mapped[list] = mapped_column(default=list)
    is_internal: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")


class Account(Base):
    """Customer, nostro, vostro, settlement and suspense accounts."""

    __tablename__ = "account"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_number: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    iban: Mapped[str | None] = mapped_column(String(34), index=True, default=None)
    name: Mapped[str] = mapped_column(String(140))
    account_type: Mapped[str] = mapped_column(String(20), index=True)
    currency: Mapped[str] = mapped_column(String(3), index=True)
    bank_id: Mapped[int | None] = mapped_column(ForeignKey("bank.id"), default=None)
    correspondent_bank_id: Mapped[int | None] = mapped_column(ForeignKey("bank.id"), default=None)
    balance: Mapped[Decimal] = mapped_column(default=Decimal("0"))
    opening_balance: Mapped[Decimal] = mapped_column(default=Decimal("0"))
    overdraft_limit: Mapped[Decimal] = mapped_column(default=Decimal("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str] = mapped_column(Text, default="")

    bank: Mapped[Bank | None] = relationship(foreign_keys=[bank_id], lazy="selectin")
    correspondent_bank: Mapped[Bank | None] = relationship(
        foreign_keys=[correspondent_bank_id], lazy="selectin"
    )


class BusinessRule(Base):
    """A rule in the validation / processing rule book, inspectable and toggleable."""

    __tablename__ = "business_rule"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(20), index=True)
    severity: Mapped[str] = mapped_column(String(10))
    stage: Mapped[str] = mapped_column(String(30), index=True)
    schemes: Mapped[list] = mapped_column(default=list)
    applies_to: Mapped[list] = mapped_column(default=list)
    field: Mapped[str | None] = mapped_column(String(60), default=None)
    failure_behaviour: Mapped[str] = mapped_column(String(80), default="Reject payment")
    iso_reason_code: Mapped[str | None] = mapped_column(String(10), default=None)
    rationale: Mapped[str] = mapped_column(Text, default="")
    standard_basis: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    parameters: Mapped[dict] = mapped_column(default=dict)


# ---------------------------------------------------------------------------
# Payment aggregate
# ---------------------------------------------------------------------------


class Payment(Base):
    __tablename__ = "payment"
    __table_args__ = (
        Index("ix_payment_status_created", "status", "created_at"),
        Index("ix_payment_scheme_status", "scheme", "status"),
        Index("ix_payment_amount", "amount"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    correlation_id: Mapped[str] = mapped_column(String(40), index=True)

    scheme: Mapped[str] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    previous_status: Mapped[str | None] = mapped_column(String(30), default=None)
    processing_mode: Mapped[str] = mapped_column(String(12), default="SIMULATED")
    direction: Mapped[str] = mapped_column(String(10), default="OUTBOUND")

    amount: Mapped[Decimal] = mapped_column()
    currency: Mapped[str] = mapped_column(String(3), index=True)
    requested_execution_date: Mapped[date | None] = mapped_column(default=None)

    instruction_id: Mapped[str] = mapped_column(String(40), index=True)
    end_to_end_id: Mapped[str] = mapped_column(String(40), index=True)
    transaction_id: Mapped[str] = mapped_column(String(40), index=True)
    uetr: Mapped[str | None] = mapped_column(String(40), index=True, default=None)

    remittance_information: Mapped[str] = mapped_column(String(240), default="")
    remittance_structured: Mapped[dict] = mapped_column(default=dict)
    purpose_code: Mapped[str | None] = mapped_column(String(10), default=None)
    category_purpose: Mapped[str | None] = mapped_column(String(10), default=None)
    service_level: Mapped[str | None] = mapped_column(String(10), default=None)
    local_instrument: Mapped[str | None] = mapped_column(String(35), default=None)
    # ISO 20022 ClearingSystemIdentification3Choice/Prtry is Max35Text. The
    # original String(10) was too small for a proprietary code such as
    # "GENERIC-CSM" and only failed on PostgreSQL, because SQLite does not
    # enforce VARCHAR lengths.
    clearing_channel: Mapped[str | None] = mapped_column(String(35), default=None)
    charge_bearer: Mapped[str] = mapped_column(String(10), default="SLEV")
    priority: Mapped[str] = mapped_column(String(10), default="NORM")

    debtor_account_id: Mapped[int | None] = mapped_column(ForeignKey("account.id"), default=None)
    settlement_account_id: Mapped[int | None] = mapped_column(ForeignKey("account.id"), default=None)

    created_at: Mapped[datetime] = mapped_column(default=_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)
    executed_at: Mapped[datetime | None] = mapped_column(default=None)
    completed_at: Mapped[datetime | None] = mapped_column(default=None)

    created_by: Mapped[str] = mapped_column(String(60), default="simulator.operator")
    source: Mapped[str] = mapped_column(String(30), default="UI")
    is_demo_data: Mapped[bool] = mapped_column(Boolean, default=False)
    scenario_code: Mapped[str | None] = mapped_column(String(20), index=True, default=None)
    failure_summary: Mapped[str | None] = mapped_column(Text, default=None)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(default=list)

    debtor_account: Mapped[Account | None] = relationship(foreign_keys=[debtor_account_id], lazy="selectin")
    settlement_account: Mapped[Account | None] = relationship(
        foreign_keys=[settlement_account_id], lazy="selectin"
    )
    parties: Mapped[list[PaymentParty]] = relationship(
        back_populates="payment", cascade="all, delete-orphan", lazy="selectin"
    )
    stages: Mapped[list[PaymentStage]] = relationship(
        back_populates="payment", cascade="all, delete-orphan", lazy="selectin"
    )
    messages: Mapped[list[PaymentMessage]] = relationship(
        back_populates="payment", cascade="all, delete-orphan", lazy="select"
    )
    events: Mapped[list[PaymentEvent]] = relationship(
        back_populates="payment", cascade="all, delete-orphan", lazy="select"
    )
    validations: Mapped[list[ValidationResult]] = relationship(
        back_populates="payment", cascade="all, delete-orphan", lazy="select"
    )
    clearing: Mapped[list[ClearingTransaction]] = relationship(
        back_populates="payment", cascade="all, delete-orphan", lazy="select"
    )
    settlements: Mapped[list[SettlementTransaction]] = relationship(
        back_populates="payment", cascade="all, delete-orphan", lazy="select"
    )
    accounting_entries: Mapped[list[AccountingEntry]] = relationship(
        back_populates="payment", cascade="all, delete-orphan", lazy="select"
    )
    reconciliation_records: Mapped[list[ReconciliationRecord]] = relationship(
        back_populates="payment", cascade="all, delete-orphan", lazy="select"
    )
    investigations: Mapped[list[Investigation]] = relationship(
        back_populates="payment", cascade="all, delete-orphan", lazy="select"
    )
    failure_injections: Mapped[list[FailureInjection]] = relationship(
        back_populates="payment", cascade="all, delete-orphan", lazy="selectin"
    )

    def party(self, role: str) -> PaymentParty | None:
        for p in self.parties:
            if p.role == role:
                return p
        return None

    @property
    def debtor(self) -> PaymentParty | None:
        return self.party("DEBTOR")

    @property
    def creditor(self) -> PaymentParty | None:
        return self.party("CREDITOR")


class PaymentParty(Base):
    __tablename__ = "payment_party"
    __table_args__ = (
        UniqueConstraint("payment_id", "role", name="uq_payment_party_role"),
        Index("ix_party_iban", "iban"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payment.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # DEBTOR | CREDITOR | ULTIMATE_DEBTOR | ...
    name: Mapped[str] = mapped_column(String(140))
    account_identifier: Mapped[str] = mapped_column(String(40), default="")
    # Deliberately wider than the standards allow (ISO 13616 caps an IBAN at 34
    # and ISO 9362 a BIC at 11). Malformed values must reach the rule engine and
    # be rejected with AC01 / RC01, which is the behaviour this simulator exists
    # to show. A column sized to the standard would instead fail the insert on
    # PostgreSQL and surface as a 500.
    iban: Mapped[str | None] = mapped_column(String(42), default=None)
    bic: Mapped[str | None] = mapped_column(String(14), index=True, default=None)
    bank_name: Mapped[str] = mapped_column(String(140), default="")
    country: Mapped[str] = mapped_column(String(2), default="")
    address_lines: Mapped[list] = mapped_column(default=list)
    town: Mapped[str] = mapped_column(String(80), default="")

    payment: Mapped[Payment] = relationship(back_populates="parties")


class PaymentStage(Base):
    __tablename__ = "payment_stage"
    __table_args__ = (
        UniqueConstraint("payment_id", "stage_key", name="uq_payment_stage"),
        Index("ix_stage_state", "state"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payment.id", ondelete="CASCADE"), index=True)
    stage_key: Mapped[str] = mapped_column(String(30))
    sequence: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(30), default="PENDING")
    started_at: Mapped[datetime | None] = mapped_column(default=None)
    completed_at: Mapped[datetime | None] = mapped_column(default=None)
    duration_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    owner_system: Mapped[str] = mapped_column(String(30), default="ORCHESTRATOR")
    summary: Mapped[str] = mapped_column(Text, default="")
    detail: Mapped[dict] = mapped_column(default=dict)
    failure_reason: Mapped[str | None] = mapped_column(Text, default=None)
    iso_reason_code: Mapped[str | None] = mapped_column(String(10), default=None)

    payment: Mapped[Payment] = relationship(back_populates="stages")


class PaymentMessage(Base):
    __tablename__ = "payment_message"
    __table_args__ = (
        Index("ix_message_type_created", "message_type", "created_at"),
        Index("ix_message_msgid", "message_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payment.id", ondelete="CASCADE"), index=True)
    correlation_id: Mapped[str] = mapped_column(String(40), index=True)
    message_type: Mapped[str] = mapped_column(String(12))
    iso_identifier: Mapped[str] = mapped_column(String(24), default="")
    message_id: Mapped[str] = mapped_column(String(60))
    direction: Mapped[str] = mapped_column(String(10))
    state: Mapped[str] = mapped_column(String(12), default="GENERATED")
    xml_payload: Mapped[str] = mapped_column(Text)
    business_summary: Mapped[dict] = mapped_column(default=dict)
    field_mappings: Mapped[list] = mapped_column(default=list)
    validation_summary: Mapped[list] = mapped_column(default=list)
    related_message_id: Mapped[str | None] = mapped_column(String(60), default=None)
    reason_code: Mapped[str | None] = mapped_column(String(10), default=None)
    is_malformed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=_now, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(default=None)
    received_at: Mapped[datetime | None] = mapped_column(default=None)
    notes: Mapped[str] = mapped_column(Text, default="")

    payment: Mapped[Payment] = relationship(back_populates="messages")


class PaymentEvent(Base):
    __tablename__ = "payment_event"
    __table_args__ = (
        Index("ix_event_payment_seq", "payment_id", "sequence"),
        Index("ix_event_type_time", "event_type", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("payment.id", ondelete="CASCADE"), index=True, default=None
    )
    correlation_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None)
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    source_system: Mapped[str] = mapped_column(String(30), index=True)
    severity: Mapped[str] = mapped_column(String(10), default="INFO", index=True)
    stage_key: Mapped[str | None] = mapped_column(String(30), default=None)
    summary: Mapped[str] = mapped_column(String(300))
    detail: Mapped[dict] = mapped_column(default=dict)
    occurred_at: Mapped[datetime] = mapped_column(default=_now, index=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, default=None)

    payment: Mapped[Payment | None] = relationship(back_populates="events")


class ValidationResult(Base):
    __tablename__ = "validation_result"
    __table_args__ = (Index("ix_validation_payment_rule", "payment_id", "rule_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payment.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[int] = mapped_column(Integer, default=1)
    rule_id: Mapped[str] = mapped_column(String(40), index=True)
    rule_name: Mapped[str] = mapped_column(String(160), default="")
    category: Mapped[str] = mapped_column(String(20), index=True)
    severity: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), index=True)
    stage: Mapped[str] = mapped_column(String(30), default="PRE_VALIDATION")
    message: Mapped[str] = mapped_column(Text, default="")
    field: Mapped[str | None] = mapped_column(String(60), default=None)
    actual_value: Mapped[str | None] = mapped_column(String(300), default=None)
    expected_value: Mapped[str | None] = mapped_column(String(300), default=None)
    iso_reason_code: Mapped[str | None] = mapped_column(String(10), default=None)
    remediation: Mapped[str] = mapped_column(Text, default="")
    executed_at: Mapped[datetime] = mapped_column(default=_now)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    injected: Mapped[bool] = mapped_column(Boolean, default=False)

    payment: Mapped[Payment] = relationship(back_populates="validations")


class ClearingTransaction(Base):
    __tablename__ = "clearing_transaction"
    __table_args__ = (Index("ix_clearing_ref", "clearing_reference"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payment.id", ondelete="CASCADE"), index=True)
    clearing_reference: Mapped[str] = mapped_column(String(40), index=True)
    clearing_system: Mapped[str] = mapped_column(String(40))
    scheme: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), index=True, default="NOT_SENT")
    decision: Mapped[str | None] = mapped_column(String(24), default=None)
    requested_decision: Mapped[str | None] = mapped_column(String(24), default=None)
    amount: Mapped[Decimal] = mapped_column()
    currency: Mapped[str] = mapped_column(String(3))
    sent_at: Mapped[datetime | None] = mapped_column(default=None)
    response_due_at: Mapped[datetime | None] = mapped_column(default=None)
    timeout_at: Mapped[datetime | None] = mapped_column(default=None, index=True)
    responded_at: Mapped[datetime | None] = mapped_column(default=None)
    response_latency_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    status_reason_code: Mapped[str | None] = mapped_column(String(10), default=None)
    status_reason: Mapped[str | None] = mapped_column(Text, default=None)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    response_count: Mapped[int] = mapped_column(Integer, default=0)
    request_message_id: Mapped[str | None] = mapped_column(String(60), default=None)
    response_message_id: Mapped[str | None] = mapped_column(String(60), default=None)
    detail: Mapped[dict] = mapped_column(default=dict)

    payment: Mapped[Payment] = relationship(back_populates="clearing")


class SettlementTransaction(Base):
    __tablename__ = "settlement_transaction"
    __table_args__ = (Index("ix_settlement_ref", "settlement_reference"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payment.id", ondelete="CASCADE"), index=True)
    settlement_reference: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True, default="PENDING")
    payment_amount: Mapped[Decimal] = mapped_column()
    payment_currency: Mapped[str] = mapped_column(String(3))
    settlement_amount: Mapped[Decimal] = mapped_column()
    settlement_currency: Mapped[str] = mapped_column(String(3))
    settlement_method: Mapped[str] = mapped_column(String(20), default="CLRG")
    settlement_account_id: Mapped[int | None] = mapped_column(ForeignKey("account.id"), default=None)
    value_date: Mapped[date | None] = mapped_column(default=None)
    submitted_at: Mapped[datetime | None] = mapped_column(default=None)
    settled_at: Mapped[datetime | None] = mapped_column(default=None)
    failure_reason: Mapped[str | None] = mapped_column(Text, default=None)
    iso_reason_code: Mapped[str | None] = mapped_column(String(10), default=None)
    detail: Mapped[dict] = mapped_column(default=dict)

    payment: Mapped[Payment] = relationship(back_populates="settlements")
    settlement_account: Mapped[Account | None] = relationship(lazy="selectin")


class AccountingEntry(Base):
    __tablename__ = "accounting_entry"
    __table_args__ = (
        Index("ix_accounting_payment_ref", "payment_id", "accounting_reference"),
        Index("ix_accounting_entry_id", "entry_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payment.id", ondelete="CASCADE"), index=True)
    entry_id: Mapped[str] = mapped_column(String(30), index=True)
    accounting_reference: Mapped[str] = mapped_column(String(30), index=True)
    journal_sequence: Mapped[int] = mapped_column(Integer, default=1)
    side: Mapped[str] = mapped_column(String(6))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("account.id"), default=None)
    account_number: Mapped[str] = mapped_column(String(40), index=True)
    account_name: Mapped[str] = mapped_column(String(140), default="")
    account_type: Mapped[str] = mapped_column(String(20), default="CUSTOMER")
    amount: Mapped[Decimal] = mapped_column()
    currency: Mapped[str] = mapped_column(String(3))
    posting_date: Mapped[date | None] = mapped_column(default=None)
    value_date: Mapped[date | None] = mapped_column(default=None)
    posted_at: Mapped[datetime] = mapped_column(default=_now)
    status: Mapped[str] = mapped_column(String(12), default="POSTED", index=True)
    narrative: Mapped[str] = mapped_column(String(240), default="")
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    is_injected_anomaly: Mapped[bool] = mapped_column(Boolean, default=False)
    anomaly_note: Mapped[str | None] = mapped_column(Text, default=None)
    balance_after: Mapped[Decimal | None] = mapped_column(default=None)

    payment: Mapped[Payment] = relationship(back_populates="accounting_entries")
    account: Mapped[Account | None] = relationship(lazy="selectin")


class StatementEntry(Base):
    """A line on a simulated camt.053 statement / camt.054 notification."""

    __tablename__ = "statement_entry"
    __table_args__ = (Index("ix_statement_ref", "statement_reference"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("payment.id", ondelete="CASCADE"), index=True, default=None
    )
    statement_reference: Mapped[str] = mapped_column(String(30), index=True)
    account_number: Mapped[str] = mapped_column(String(40), index=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("account.id"), default=None)
    side: Mapped[str] = mapped_column(String(6))
    amount: Mapped[Decimal] = mapped_column()
    currency: Mapped[str] = mapped_column(String(3))
    booking_date: Mapped[date | None] = mapped_column(default=None)
    value_date: Mapped[date | None] = mapped_column(default=None)
    end_to_end_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None)
    bank_transaction_code: Mapped[str] = mapped_column(String(20), default="PMNT-ICDT-ESCT")
    narrative: Mapped[str] = mapped_column(String(240), default="")
    source_message_type: Mapped[str] = mapped_column(String(12), default="camt.054")
    source_message_id: Mapped[str | None] = mapped_column(String(60), default=None)
    is_orphan: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=_now)

    account: Mapped[Account | None] = relationship(lazy="selectin")


class ReconciliationRecord(Base):
    __tablename__ = "reconciliation_record"
    __table_args__ = (Index("ix_recon_status_created", "status", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("payment.id", ondelete="CASCADE"), index=True, default=None
    )
    reference: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    run_at: Mapped[datetime] = mapped_column(default=_now)
    created_at: Mapped[datetime] = mapped_column(default=_now, index=True)

    internal_reference: Mapped[str | None] = mapped_column(String(40), default=None)
    internal_amount: Mapped[Decimal | None] = mapped_column(default=None)
    internal_currency: Mapped[str | None] = mapped_column(String(3), default=None)

    accounting_reference: Mapped[str | None] = mapped_column(String(40), default=None)
    accounting_amount: Mapped[Decimal | None] = mapped_column(default=None)

    clearing_reference: Mapped[str | None] = mapped_column(String(40), default=None)
    clearing_amount: Mapped[Decimal | None] = mapped_column(default=None)

    statement_reference: Mapped[str | None] = mapped_column(String(40), default=None)
    statement_amount: Mapped[Decimal | None] = mapped_column(default=None)
    statement_currency: Mapped[str | None] = mapped_column(String(3), default=None)

    difference_amount: Mapped[Decimal | None] = mapped_column(default=None)
    probable_cause: Mapped[str] = mapped_column(Text, default="")
    recommended_action: Mapped[str] = mapped_column(Text, default="")
    legs: Mapped[list] = mapped_column(default=list)
    detail: Mapped[dict] = mapped_column(default=dict)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)

    payment: Mapped[Payment | None] = relationship(back_populates="reconciliation_records")


class Investigation(Base):
    __tablename__ = "investigation"
    __table_args__ = (Index("ix_investigation_status_opened", "status", "opened_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("payment.id", ondelete="CASCADE"), index=True, default=None
    )
    reference: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(24), index=True, default="OPEN")
    reason: Mapped[str] = mapped_column(String(40), index=True)
    priority: Mapped[str] = mapped_column(String(10), default="NORMAL")
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text, default="")
    expected_behaviour: Mapped[str] = mapped_column(Text, default="")
    actual_behaviour: Mapped[str] = mapped_column(Text, default="")
    probable_cause: Mapped[str] = mapped_column(Text, default="")
    recommended_action: Mapped[str] = mapped_column(Text, default="")
    assigned_to: Mapped[str] = mapped_column(String(60), default="payments.operations")
    opened_at: Mapped[datetime] = mapped_column(default=_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)
    resolved_at: Mapped[datetime | None] = mapped_column(default=None)
    resolution: Mapped[str | None] = mapped_column(Text, default=None)
    reconciliation_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("reconciliation_record.id", ondelete="SET NULL"), default=None
    )
    actions: Mapped[list] = mapped_column(default=list)
    detail: Mapped[dict] = mapped_column(default=dict)

    payment: Mapped[Payment | None] = relationship(back_populates="investigations")


class FailureInjection(Base):
    __tablename__ = "failure_injection"

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("payment.id", ondelete="CASCADE"), index=True, default=None
    )
    code: Mapped[str] = mapped_column(String(40), index=True)
    category: Mapped[str] = mapped_column(String(20), index=True)
    label: Mapped[str] = mapped_column(String(140), default="")
    stage_key: Mapped[str] = mapped_column(String(30), default="PRE_VALIDATION")
    parameters: Mapped[dict] = mapped_column(default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    created_by: Mapped[str] = mapped_column(String(60), default="qa.lab")
    effect_summary: Mapped[str | None] = mapped_column(Text, default=None)

    payment: Mapped[Payment | None] = relationship(back_populates="failure_injections")


class Scenario(Base):
    __tablename__ = "scenario"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(30), index=True)
    scheme: Mapped[str] = mapped_column(String(30))
    description: Mapped[str] = mapped_column(Text, default="")
    business_context: Mapped[str] = mapped_column(Text, default="")
    preconditions: Mapped[list] = mapped_column(default=list)
    input_data: Mapped[dict] = mapped_column(default=dict)
    failure_codes: Mapped[list] = mapped_column(default=list)
    execution_steps: Mapped[list] = mapped_column(default=list)
    expected_status: Mapped[str] = mapped_column(String(30), default="COMPLETED")
    expected_result: Mapped[list] = mapped_column(default=list)
    expected_messages: Mapped[list] = mapped_column(default=list)
    expected_accounting: Mapped[list] = mapped_column(default=list)
    expected_reconciliation: Mapped[str] = mapped_column(String(24), default="MATCHED")
    failure_conditions: Mapped[list] = mapped_column(default=list)
    is_demo_highlight: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ScenarioExecution(Base):
    __tablename__ = "scenario_execution"

    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("scenario.id", ondelete="CASCADE"), index=True)
    scenario_code: Mapped[str] = mapped_column(String(20), index=True)
    payment_id: Mapped[int | None] = mapped_column(ForeignKey("payment.id", ondelete="SET NULL"), default=None)
    started_at: Mapped[datetime] = mapped_column(default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)
    outcome: Mapped[str] = mapped_column(String(12), default="RUNNING", index=True)
    actual_status: Mapped[str | None] = mapped_column(String(30), default=None)
    expected_status: Mapped[str | None] = mapped_column(String(30), default=None)
    assertions: Mapped[list] = mapped_column(default=list)
    notes: Mapped[str] = mapped_column(Text, default="")

    scenario: Mapped[Scenario] = relationship(lazy="selectin")


class TestCase(Base):
    __tablename__ = "test_case"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(String(30), index=True)
    suite: Mapped[str] = mapped_column(String(60), index=True)
    rule_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None)
    scheme: Mapped[str] = mapped_column(String(30), default="SIC_INSTANT")
    test_type: Mapped[str] = mapped_column(String(20), index=True)
    title: Mapped[str] = mapped_column(String(200))
    preconditions: Mapped[list] = mapped_column(default=list)
    steps: Mapped[list] = mapped_column(default=list)
    input_data: Mapped[dict] = mapped_column(default=dict)
    expected_result: Mapped[str] = mapped_column(Text, default="")
    expected_status: Mapped[str | None] = mapped_column(String(30), default=None)
    expected_rule_outcome: Mapped[str | None] = mapped_column(String(20), default=None)
    priority: Mapped[str] = mapped_column(String(10), default="MEDIUM")
    requirement_id: Mapped[str | None] = mapped_column(String(30), default=None)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    last_run_at: Mapped[datetime | None] = mapped_column(default=None)
    last_run_outcome: Mapped[str | None] = mapped_column(String(12), default=None)
    last_run_detail: Mapped[dict] = mapped_column(default=dict)
    last_run_payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("payment.id", ondelete="SET NULL"), default=None
    )


class AuditEvent(Base):
    __tablename__ = "audit_event"
    __table_args__ = (Index("ix_audit_entity", "entity_type", "entity_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(60), default="simulator.operator", index=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(40))
    occurred_at: Mapped[datetime] = mapped_column(default=_now, index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    before: Mapped[dict] = mapped_column(default=dict)
    after: Mapped[dict] = mapped_column(default=dict)
    request_id: Mapped[str | None] = mapped_column(String(40), default=None)
    correlation_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None)


class ScheduledJob(Base):
    """Internal durable work queue.

    Asynchronous behaviour (clearing responses arriving later, timeout detection,
    camt.054 notifications, reconciliation runs) is modelled as scheduled jobs
    rather than in-memory timers, so pending work survives a restart and is
    inspectable.
    """

    __tablename__ = "scheduled_job"
    __table_args__ = (Index("ix_job_due", "status", "due_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_type: Mapped[str] = mapped_column(String(40), index=True)
    payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("payment.id", ondelete="CASCADE"), index=True, default=None
    )
    correlation_id: Mapped[str | None] = mapped_column(String(40), default=None)
    due_at: Mapped[datetime] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    started_at: Mapped[datetime | None] = mapped_column(default=None)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(String(12), default="PENDING", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(default=dict)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
