"""Payment domain enumerations.

Status vocabulary is standards-inspired. Where a value has no exact ISO 20022 or
scheme equivalent it is a SIMULATED IMPLEMENTATION concept and is documented as
such in docs/payments-domain.md.
"""

from __future__ import annotations

from enum import StrEnum


class PaymentStatus(StrEnum):
    """Overall lifecycle status held by the payment aggregate."""

    DRAFT = "DRAFT"
    INITIATED = "INITIATED"
    VALIDATING = "VALIDATING"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    COMPLIANCE_CHECK = "COMPLIANCE_CHECK"
    BLOCKED = "BLOCKED"
    MESSAGE_GENERATED = "MESSAGE_GENERATED"
    SENT_TO_CLEARING = "SENT_TO_CLEARING"
    CLEARING_ACCEPTED = "CLEARING_ACCEPTED"
    CLEARING_REJECTED = "CLEARING_REJECTED"
    TIMED_OUT = "TIMED_OUT"
    INVESTIGATION_REQUIRED = "INVESTIGATION_REQUIRED"
    REPROCESSING = "REPROCESSING"
    SETTLEMENT_PENDING = "SETTLEMENT_PENDING"
    SETTLED = "SETTLED"
    SETTLEMENT_FAILED = "SETTLEMENT_FAILED"
    ACCOUNTED = "ACCOUNTED"
    ACCOUNTING_BREAK = "ACCOUNTING_BREAK"
    RECONCILED = "RECONCILED"
    RECONCILIATION_BREAK = "RECONCILIATION_BREAK"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    RETURNED = "RETURNED"
    REVERSED = "REVERSED"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL_STATUSES

    @property
    def is_failure(self) -> bool:
        return self in _FAILURE_STATUSES


_TERMINAL_STATUSES = frozenset(
    {
        PaymentStatus.COMPLETED,
        PaymentStatus.REJECTED,
        PaymentStatus.BLOCKED,
        PaymentStatus.CLEARING_REJECTED,
        PaymentStatus.CANCELLED,
        PaymentStatus.RETURNED,
        PaymentStatus.REVERSED,
    }
)

_FAILURE_STATUSES = frozenset(
    {
        PaymentStatus.REJECTED,
        PaymentStatus.BLOCKED,
        PaymentStatus.CLEARING_REJECTED,
        PaymentStatus.TIMED_OUT,
        PaymentStatus.SETTLEMENT_FAILED,
        PaymentStatus.ACCOUNTING_BREAK,
        PaymentStatus.RECONCILIATION_BREAK,
        PaymentStatus.INVESTIGATION_REQUIRED,
        PaymentStatus.RETURNED,
        PaymentStatus.REVERSED,
    }
)


class StageKey(StrEnum):
    """The processing stages rendered on the payment journey graph."""

    INITIATION = "INITIATION"
    CHANNEL_INTAKE = "CHANNEL_INTAKE"
    PRE_VALIDATION = "PRE_VALIDATION"
    BUSINESS_VALIDATION = "BUSINESS_VALIDATION"
    COMPLIANCE = "COMPLIANCE"
    ORCHESTRATION = "ORCHESTRATION"
    MESSAGE_GENERATION = "MESSAGE_GENERATION"
    CLEARING = "CLEARING"
    CLEARING_RESPONSE = "CLEARING_RESPONSE"
    SETTLEMENT = "SETTLEMENT"
    ACCOUNTING = "ACCOUNTING"
    RECONCILIATION = "RECONCILIATION"
    COMPLETION = "COMPLETION"


STAGE_ORDER: tuple[StageKey, ...] = (
    StageKey.INITIATION,
    StageKey.CHANNEL_INTAKE,
    StageKey.PRE_VALIDATION,
    StageKey.BUSINESS_VALIDATION,
    StageKey.COMPLIANCE,
    StageKey.ORCHESTRATION,
    StageKey.MESSAGE_GENERATION,
    StageKey.CLEARING,
    StageKey.CLEARING_RESPONSE,
    StageKey.SETTLEMENT,
    StageKey.ACCOUNTING,
    StageKey.RECONCILIATION,
    StageKey.COMPLETION,
)

STAGE_LABELS: dict[StageKey, dict[str, str]] = {
    StageKey.INITIATION: {
        "business": "Customer instruction received",
        "technical": "Initiation / payment object created",
    },
    StageKey.CHANNEL_INTAKE: {
        "business": "Accepted by the bank's channel",
        "technical": "Channel / API intake, correlation ID assigned",
    },
    StageKey.PRE_VALIDATION: {
        "business": "Basic checks on the instruction",
        "technical": "Technical & structural pre-validation",
    },
    StageKey.BUSINESS_VALIDATION: {
        "business": "Bank and scheme rule checks",
        "technical": "Business validation rule engine execution",
    },
    StageKey.COMPLIANCE: {
        "business": "Sanctions and embargo screening",
        "technical": "Compliance screening simulation",
    },
    StageKey.ORCHESTRATION: {
        "business": "Payment routed for processing",
        "technical": "Payment orchestration & scheme routing",
    },
    StageKey.MESSAGE_GENERATION: {
        "business": "Payment message prepared",
        "technical": "ISO 20022 pacs.008 generation",
    },
    StageKey.CLEARING: {
        "business": "Sent to the payment system",
        "technical": "Dispatched to clearing adapter",
    },
    StageKey.CLEARING_RESPONSE: {
        "business": "Payment system response",
        "technical": "pacs.002 status report handling",
    },
    StageKey.SETTLEMENT: {
        "business": "Funds settled between banks",
        "technical": "Settlement engine posting",
    },
    StageKey.ACCOUNTING: {
        "business": "Accounts updated",
        "technical": "Double-entry accounting postings",
    },
    StageKey.RECONCILIATION: {
        "business": "Records matched against the statement",
        "technical": "Reconciliation across internal / clearing / statement records",
    },
    StageKey.COMPLETION: {
        "business": "Payment complete",
        "technical": "Terminal lifecycle state reached",
    },
}


class StageState(StrEnum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"
    REVERSED = "REVERSED"
    INVESTIGATION_REQUIRED = "INVESTIGATION_REQUIRED"
    REPROCESSING = "REPROCESSING"
    SKIPPED = "SKIPPED"


class SchemeCode(StrEnum):
    SIC_INSTANT = "SIC_INSTANT"
    SEPA_INSTANT = "SEPA_INSTANT"
    GENERIC_ISO20022 = "GENERIC_ISO20022"
    SWIFT_CROSS_BORDER = "SWIFT_CROSS_BORDER"


class MessageType(StrEnum):
    PACS_008 = "pacs.008"
    PACS_002 = "pacs.002"
    PACS_004 = "pacs.004"
    PACS_028 = "pacs.028"
    CAMT_056 = "camt.056"
    CAMT_029 = "camt.029"
    CAMT_053 = "camt.053"
    CAMT_054 = "camt.054"
    MT_103 = "MT103"


MESSAGE_METADATA: dict[MessageType, dict[str, str]] = {
    MessageType.PACS_008: {
        "name": "FIToFICustomerCreditTransfer",
        "iso_identifier": "pacs.008.001.08",
        "direction": "OUTBOUND",
        "purpose": "Instructs the movement of funds from the debtor agent to the creditor agent.",
    },
    MessageType.PACS_002: {
        "name": "FIToFIPaymentStatusReport",
        "iso_identifier": "pacs.002.001.10",
        "direction": "INBOUND",
        "purpose": "Reports the status (accepted / rejected) of a previously sent instruction.",
    },
    MessageType.PACS_004: {
        "name": "PaymentReturn",
        "iso_identifier": "pacs.004.001.09",
        "direction": "INBOUND",
        "purpose": "Returns funds for a payment that cannot be applied by the creditor agent.",
    },
    MessageType.PACS_028: {
        "name": "FIToFIPaymentStatusRequest",
        "iso_identifier": "pacs.028.001.03",
        "direction": "OUTBOUND",
        "purpose": "Requests the status of a payment for which no status report was received.",
    },
    MessageType.CAMT_056: {
        "name": "FIToFIPaymentCancellationRequest",
        "iso_identifier": "camt.056.001.08",
        "direction": "OUTBOUND",
        "purpose": "Requests cancellation of a payment already sent to the clearing system.",
    },
    MessageType.CAMT_029: {
        "name": "ResolutionOfInvestigation",
        "iso_identifier": "camt.029.001.09",
        "direction": "INBOUND",
        "purpose": "Communicates the outcome of a cancellation request or investigation.",
    },
    MessageType.CAMT_053: {
        "name": "BankToCustomerStatement",
        "iso_identifier": "camt.053.001.08",
        "direction": "INBOUND",
        "purpose": "End-of-day account statement used as the reconciliation source of truth.",
    },
    MessageType.CAMT_054: {
        "name": "BankToCustomerDebitCreditNotification",
        "iso_identifier": "camt.054.001.08",
        "direction": "INBOUND",
        "purpose": "Intraday debit/credit notification confirming an account movement.",
    },
    MessageType.MT_103: {
        "name": "Single Customer Credit Transfer",
        "iso_identifier": "MT103",
        "direction": "OUTBOUND",
        "purpose": "Legacy FIN message equivalent of a customer credit transfer.",
    },
}


class MessageDirection(StrEnum):
    OUTBOUND = "OUTBOUND"
    INBOUND = "INBOUND"


class MessageState(StrEnum):
    GENERATED = "GENERATED"
    SENT = "SENT"
    RECEIVED = "RECEIVED"
    REJECTED = "REJECTED"
    MALFORMED = "MALFORMED"


class ValidationCategory(StrEnum):
    TECHNICAL = "TECHNICAL"
    BUSINESS = "BUSINESS"
    SCHEME = "SCHEME"
    COMPLIANCE = "COMPLIANCE"
    ACCOUNT = "ACCOUNT"
    MESSAGE = "MESSAGE"
    DUPLICATE = "DUPLICATE"


class Severity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    FATAL = "FATAL"


class ValidationStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ClearingDecision(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    DELAY = "DELAY"
    TIMEOUT = "TIMEOUT"
    DUPLICATE_RESPONSE = "DUPLICATE_RESPONSE"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
    TECHNICAL_ERROR = "TECHNICAL_ERROR"
    BUSINESS_ERROR = "BUSINESS_ERROR"
    UNAVAILABLE = "UNAVAILABLE"


class ClearingStatus(StrEnum):
    NOT_SENT = "NOT_SENT"
    SENT = "SENT"
    AWAITING_RESPONSE = "AWAITING_RESPONSE"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    TIMED_OUT = "TIMED_OUT"
    UNAVAILABLE = "UNAVAILABLE"
    CANCELLED = "CANCELLED"


class SettlementStatus(StrEnum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    SETTLED = "SETTLED"
    FAILED = "FAILED"
    PARTIALLY_SETTLED = "PARTIALLY_SETTLED"
    REVERSED = "REVERSED"


class AccountingStatus(StrEnum):
    POSTED = "POSTED"
    PENDING = "PENDING"
    REVERSED = "REVERSED"
    FAILED = "FAILED"
    DUPLICATE = "DUPLICATE"


class EntrySide(StrEnum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class AccountType(StrEnum):
    CUSTOMER = "CUSTOMER"
    NOSTRO = "NOSTRO"
    VOSTRO = "VOSTRO"
    SETTLEMENT = "SETTLEMENT"
    SUSPENSE = "SUSPENSE"
    FEE = "FEE"


class ReconciliationStatus(StrEnum):
    MATCHED = "MATCHED"
    UNMATCHED = "UNMATCHED"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    DUPLICATE = "DUPLICATE"
    MISSING_ENTRY = "MISSING_ENTRY"
    TIMING_DIFFERENCE = "TIMING_DIFFERENCE"
    REFERENCE_MISMATCH = "REFERENCE_MISMATCH"
    NOT_RUN = "NOT_RUN"

    @property
    def is_break(self) -> bool:
        return self not in (ReconciliationStatus.MATCHED, ReconciliationStatus.NOT_RUN)


class InvestigationStatus(StrEnum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_RESPONSE = "AWAITING_RESPONSE"
    RESOLVED = "RESOLVED"
    CLOSED_UNRESOLVED = "CLOSED_UNRESOLVED"


class InvestigationReason(StrEnum):
    CLEARING_TIMEOUT = "CLEARING_TIMEOUT"
    RECONCILIATION_BREAK = "RECONCILIATION_BREAK"
    ACCOUNTING_BREAK = "ACCOUNTING_BREAK"
    SETTLEMENT_FAILURE = "SETTLEMENT_FAILURE"
    COMPLIANCE_BLOCK = "COMPLIANCE_BLOCK"
    CANCELLATION_REQUEST = "CANCELLATION_REQUEST"
    BENEFICIARY_NOT_CREDITED = "BENEFICIARY_NOT_CREDITED"
    CUSTOMER_QUERY = "CUSTOMER_QUERY"


class EventType(StrEnum):
    PAYMENT_CREATED = "PAYMENT_CREATED"
    PAYMENT_UPDATED = "PAYMENT_UPDATED"
    STAGE_STARTED = "STAGE_STARTED"
    STAGE_COMPLETED = "STAGE_COMPLETED"
    STAGE_FAILED = "STAGE_FAILED"
    STATUS_CHANGED = "STATUS_CHANGED"
    VALIDATION_EXECUTED = "VALIDATION_EXECUTED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    COMPLIANCE_SCREENED = "COMPLIANCE_SCREENED"
    MESSAGE_GENERATED = "MESSAGE_GENERATED"
    MESSAGE_SENT = "MESSAGE_SENT"
    MESSAGE_RECEIVED = "MESSAGE_RECEIVED"
    CLEARING_DISPATCHED = "CLEARING_DISPATCHED"
    CLEARING_RESPONSE = "CLEARING_RESPONSE"
    CLEARING_TIMEOUT = "CLEARING_TIMEOUT"
    SETTLEMENT_POSTED = "SETTLEMENT_POSTED"
    SETTLEMENT_FAILED = "SETTLEMENT_FAILED"
    ACCOUNTING_POSTED = "ACCOUNTING_POSTED"
    ACCOUNTING_BREAK = "ACCOUNTING_BREAK"
    RECONCILIATION_RUN = "RECONCILIATION_RUN"
    RECONCILIATION_BREAK = "RECONCILIATION_BREAK"
    INVESTIGATION_OPENED = "INVESTIGATION_OPENED"
    INVESTIGATION_UPDATED = "INVESTIGATION_UPDATED"
    INVESTIGATION_RESOLVED = "INVESTIGATION_RESOLVED"
    FAILURE_INJECTED = "FAILURE_INJECTED"
    RETRY_REQUESTED = "RETRY_REQUESTED"
    CANCELLATION_REQUESTED = "CANCELLATION_REQUESTED"
    PAYMENT_RETURNED = "PAYMENT_RETURNED"
    SCENARIO_EXECUTED = "SCENARIO_EXECUTED"


class SourceSystem(StrEnum):
    CHANNEL = "CHANNEL"
    ORCHESTRATOR = "ORCHESTRATOR"
    VALIDATION_ENGINE = "VALIDATION_ENGINE"
    COMPLIANCE_ENGINE = "COMPLIANCE_ENGINE"
    MESSAGE_ENGINE = "MESSAGE_ENGINE"
    CLEARING_ADAPTER = "CLEARING_ADAPTER"
    CLEARING_SYSTEM = "CLEARING_SYSTEM"
    SETTLEMENT_ENGINE = "SETTLEMENT_ENGINE"
    ACCOUNTING_ENGINE = "ACCOUNTING_ENGINE"
    RECONCILIATION_ENGINE = "RECONCILIATION_ENGINE"
    INVESTIGATION_DESK = "INVESTIGATION_DESK"
    QA_LAB = "QA_LAB"


class FailureCategory(StrEnum):
    VALIDATION = "VALIDATION"
    COMPLIANCE = "COMPLIANCE"
    CLEARING = "CLEARING"
    TIMEOUT = "TIMEOUT"
    SETTLEMENT = "SETTLEMENT"
    ACCOUNTING = "ACCOUNTING"
    RECONCILIATION = "RECONCILIATION"
    RETURN = "RETURN"


class ProcessingMode(StrEnum):
    """How quickly the lifecycle runs when executed."""

    IMMEDIATE = "IMMEDIATE"  # run synchronously, no artificial delays (tests, QA)
    SIMULATED = "SIMULATED"  # realistic async delays via the scheduler (UI demos)
