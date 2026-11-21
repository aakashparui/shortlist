"""Column widths must fit the values the application actually writes.

SQLite ignores VARCHAR lengths, so a column that is too narrow passes every
test here and then fails on PostgreSQL with
`value too long for type character varying(n)`. These tests close that gap by
checking the declared widths against the real sources of those values: the
enums, the scheme configuration, the failure-injection catalogue and the API's
own input limits.
"""

from __future__ import annotations

from sqlalchemy import String

from app.api.schemas import PartyInput, PaymentCreate
from app.db.models import (
    AccountingEntry,
    ClearingTransaction,
    FailureInjection,
    Investigation,
    Payment,
    PaymentEvent,
    PaymentMessage,
    PaymentParty,
    PaymentStage,
    ReconciliationRecord,
    ScenarioExecution,
    SettlementTransaction,
    ValidationResult,
)
from app.domain.enums import (
    AccountType,
    ClearingDecision,
    ClearingStatus,
    EntrySide,
    EventType,
    FailureCategory,
    InvestigationReason,
    InvestigationStatus,
    MessageDirection,
    MessageState,
    MessageType,
    PaymentStatus,
    ProcessingMode,
    ReconciliationStatus,
    SchemeCode,
    SettlementStatus,
    Severity,
    SourceSystem,
    StageKey,
    StageState,
    ValidationCategory,
    ValidationStatus,
)
from app.engines.failure_injection import CATALOGUE
from app.schemes.registry import list_schemes


def width(model, column_name: str) -> int:  # noqa: ANN001
    column = model.__table__.columns[column_name]
    assert isinstance(column.type, String), f"{column_name} is not a String column"
    assert column.type.length is not None, f"{column_name} has no declared length"
    return column.type.length


def longest(values) -> str:  # noqa: ANN001
    return max(values, key=len)


class TestEnumBackedColumns:
    """Every column that stores an enum value must fit the longest member."""

    CASES = [
        (Payment, "status", PaymentStatus),
        (Payment, "previous_status", PaymentStatus),
        (Payment, "scheme", SchemeCode),
        (Payment, "processing_mode", ProcessingMode),
        (PaymentStage, "stage_key", StageKey),
        (PaymentStage, "state", StageState),
        (PaymentStage, "owner_system", SourceSystem),
        (PaymentEvent, "event_type", EventType),
        (PaymentEvent, "source_system", SourceSystem),
        (PaymentEvent, "severity", Severity),
        (PaymentEvent, "stage_key", StageKey),
        (PaymentMessage, "message_type", MessageType),
        (PaymentMessage, "direction", MessageDirection),
        (PaymentMessage, "state", MessageState),
        (ValidationResult, "category", ValidationCategory),
        (ValidationResult, "severity", Severity),
        (ValidationResult, "status", ValidationStatus),
        (ValidationResult, "stage", StageKey),
        (ClearingTransaction, "status", ClearingStatus),
        (ClearingTransaction, "decision", ClearingDecision),
        (ClearingTransaction, "requested_decision", ClearingDecision),
        (ClearingTransaction, "scheme", SchemeCode),
        (SettlementTransaction, "status", SettlementStatus),
        (AccountingEntry, "side", EntrySide),
        (AccountingEntry, "account_type", AccountType),
        (ReconciliationRecord, "status", ReconciliationStatus),
        (Investigation, "status", InvestigationStatus),
        (Investigation, "reason", InvestigationReason),
        (FailureInjection, "category", FailureCategory),
        (FailureInjection, "stage_key", StageKey),
        (ScenarioExecution, "actual_status", PaymentStatus),
        (ScenarioExecution, "expected_status", PaymentStatus),
    ]

    def test_every_enum_column_fits_its_longest_member(self) -> None:
        failures = []
        for model, column_name, enum in self.CASES:
            value = longest([member.value for member in enum])
            declared = width(model, column_name)
            if len(value) > declared:
                failures.append(
                    f"{model.__tablename__}.{column_name} is String({declared}) "
                    f"but {enum.__name__}.{value} needs {len(value)}"
                )
        assert not failures, "columns too narrow for their enum:\n  " + "\n  ".join(failures)


class TestSchemeDerivedColumns:
    """Values copied out of the scheme configuration must fit."""

    def test_clearing_channel_fits_every_proprietary_code(self) -> None:
        codes = [
            scheme.messages.clearing_system_proprietary
            for scheme in list_schemes()
            if scheme.messages.clearing_system_proprietary
        ]
        assert codes
        value = longest(codes)
        declared = width(Payment, "clearing_channel")
        assert len(value) <= declared, (
            f"payment.clearing_channel is String({declared}) but {value!r} needs {len(value)}"
        )

    def test_clearing_system_name_fits(self) -> None:
        names = [scheme.clearing.clearing_system_name for scheme in list_schemes()]
        value = longest(names)
        declared = width(ClearingTransaction, "clearing_system")
        assert len(value) <= declared, (
            f"clearing_transaction.clearing_system is String({declared}) "
            f"but {value!r} needs {len(value)}"
        )

    def test_service_level_and_local_instrument_fit(self) -> None:
        service_levels = [s for scheme in list_schemes() for s in scheme.rules.allowed_service_levels]
        instruments = [i for scheme in list_schemes() for i in scheme.rules.allowed_local_instruments]
        assert len(longest(service_levels)) <= width(Payment, "service_level")
        if instruments:
            assert len(longest(instruments)) <= width(Payment, "local_instrument")

    def test_charge_bearer_fits(self) -> None:
        bearers = [b for scheme in list_schemes() for b in scheme.rules.allowed_charge_bearers]
        assert len(longest(bearers)) <= width(Payment, "charge_bearer")

    def test_settlement_method_fits(self) -> None:
        methods = [scheme.settlement.settlement_method for scheme in list_schemes()]
        assert len(longest(methods)) <= width(SettlementTransaction, "settlement_method")


class TestInjectionWrittenColumns:
    """Failure injections write values directly onto the payment, bypassing the
    API's own validation. Those values must still fit."""

    def test_injection_codes_and_categories_fit(self) -> None:
        assert len(longest([d.code for d in CATALOGUE])) <= width(FailureInjection, "code")
        assert len(longest([d.label for d in CATALOGUE])) <= width(FailureInjection, "label")

    def test_injected_bic_fits(self) -> None:
        """INVALID_CREDITOR_BIC writes a deliberately malformed BIC.

        It must reach the rule engine and be rejected with RC01, not blow up the
        insert, so the column has to be wider than ISO 9362 allows.
        """
        bics = [
            str(d.parameters["bic"]) for d in CATALOGUE if "bic" in d.parameters
        ]
        assert bics, "expected at least one injection to set a BIC"
        value = longest(bics)
        declared = width(PaymentParty, "bic")
        assert len(value) <= declared, (
            f"payment_party.bic is String({declared}) but the injected {value!r} needs {len(value)}"
        )

    def test_injected_party_name_fits(self) -> None:
        names = [str(d.parameters["name"]) for d in CATALOGUE if "name" in d.parameters]
        if names:
            assert len(longest(names)) <= width(PaymentParty, "name")

    def test_injected_currency_fits(self) -> None:
        currencies = [str(d.parameters["currency"]) for d in CATALOGUE if "currency" in d.parameters]
        if currencies:
            assert len(longest(currencies)) <= width(Payment, "currency")


class TestApiInputsFitTheirColumns:
    """Anything the API accepts must be storable. If the API allows a longer
    value than the column holds, a valid request becomes a 500 on PostgreSQL."""

    CASES = [
        (PaymentCreate, "remittanceInformation", Payment, "remittance_information"),
        (PaymentCreate, "purposeCode", Payment, "purpose_code"),
        (PaymentCreate, "categoryPurpose", Payment, "category_purpose"),
        (PaymentCreate, "serviceLevel", Payment, "service_level"),
        (PaymentCreate, "localInstrument", Payment, "local_instrument"),
        (PaymentCreate, "clearingChannel", Payment, "clearing_channel"),
        (PaymentCreate, "chargeBearer", Payment, "charge_bearer"),
        (PaymentCreate, "priority", Payment, "priority"),
        (PaymentCreate, "instructionId", Payment, "instruction_id"),
        (PaymentCreate, "endToEndId", Payment, "end_to_end_id"),
        (PaymentCreate, "transactionId", Payment, "transaction_id"),
        (PaymentCreate, "uetr", Payment, "uetr"),
        (PaymentCreate, "createdBy", Payment, "created_by"),
        (PaymentCreate, "source", Payment, "source"),
        (PartyInput, "name", PaymentParty, "name"),
        (PartyInput, "accountIdentifier", PaymentParty, "account_identifier"),
        (PartyInput, "iban", PaymentParty, "iban"),
        (PartyInput, "bic", PaymentParty, "bic"),
        (PartyInput, "bankName", PaymentParty, "bank_name"),
        (PartyInput, "country", PaymentParty, "country"),
        (PartyInput, "town", PaymentParty, "town"),
    ]

    @staticmethod
    def _schema_max(model, field_name: str) -> int | None:  # noqa: ANN001
        field = model.model_fields[field_name]
        for item in field.metadata:
            limit = getattr(item, "max_length", None)
            if limit is not None:
                return int(limit)
        return None

    def test_no_accepted_input_can_overflow_its_column(self) -> None:
        failures = []
        for schema, field_name, model, column_name in self.CASES:
            accepted = self._schema_max(schema, field_name)
            if accepted is None:
                continue
            declared = width(model, column_name)
            if accepted > declared:
                failures.append(
                    f"{schema.__name__}.{field_name} accepts {accepted} characters but "
                    f"{model.__tablename__}.{column_name} is String({declared})"
                )
        assert not failures, (
            "the API accepts values its own columns cannot store; on PostgreSQL these "
            "become a 500 instead of a validation error:\n  " + "\n  ".join(failures)
        )
