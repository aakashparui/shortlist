"""Payment scheme abstraction.

A scheme bundles everything that differs between payment rails:

    PaymentScheme
        -> SchemeRules       (limits, currencies, country scope, cut-offs)
        -> ValidationRules    (which rule ids apply)
        -> MessageRules       (which ISO 20022 messages are exchanged)
        -> ClearingAdapter    (how the clearing system behaves and responds)
        -> SettlementAdapter  (how settlement is effected)

Adding a rail means adding one module and registering it. Nothing in the
engines, API or UI needs to change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from app.domain.enums import MessageType, SchemeCode


@dataclass(frozen=True, slots=True)
class AmountLimit:
    currency: str
    minimum: Decimal
    maximum: Decimal


@dataclass(frozen=True, slots=True)
class SchemeRules:
    """Functional rule set of a rail. All values are configuration, not code."""

    settlement_currency: str
    allowed_currencies: tuple[str, ...]
    amount_limits: tuple[AmountLimit, ...]
    requires_iban_debtor: bool = True
    requires_iban_creditor: bool = True
    requires_bic_creditor_agent: bool = True
    country_scope: tuple[str, ...] | None = None  # None == global
    max_remittance_length: int = 140
    allows_structured_remittance: bool = True
    requires_purpose_code: bool = False
    allowed_charge_bearers: tuple[str, ...] = ("SLEV",)
    allowed_service_levels: tuple[str, ...] = ("SEPA",)
    allowed_local_instruments: tuple[str, ...] = ()
    allows_future_dated: bool = False
    max_future_days: int = 0
    duplicate_window_minutes: int = 1440
    cutoff_time_utc: time | None = None
    is_instant: bool = True
    uses_uetr: bool = False
    supports_cancellation: bool = True
    supports_return: bool = True
    requires_creditor_address_for_cross_border: bool = False

    def limit_for(self, currency: str) -> AmountLimit | None:
        for limit in self.amount_limits:
            if limit.currency == currency.upper():
                return limit
        return None


@dataclass(frozen=True, slots=True)
class MessageRules:
    """Which ISO 20022 messages this rail exchanges, and under what name."""

    instruction_message: MessageType = MessageType.PACS_008
    status_message: MessageType = MessageType.PACS_002
    return_message: MessageType = MessageType.PACS_004
    status_request_message: MessageType = MessageType.PACS_028
    cancellation_message: MessageType = MessageType.CAMT_056
    resolution_message: MessageType = MessageType.CAMT_029
    notification_message: MessageType = MessageType.CAMT_054
    statement_message: MessageType = MessageType.CAMT_053
    legacy_message: MessageType | None = None
    pacs008_namespace: str = "urn:iso:std:iso:20022:tech:xsd:pacs.008.001.08"
    pacs002_namespace: str = "urn:iso:std:iso:20022:tech:xsd:pacs.002.001.10"
    settlement_method: str = "CLRG"
    clearing_system_proprietary: str | None = None
    clearing_system_code: str | None = None

    @property
    def message_set(self) -> tuple[MessageType, ...]:
        values = [
            self.instruction_message,
            self.status_message,
            self.return_message,
            self.status_request_message,
            self.cancellation_message,
            self.resolution_message,
            self.notification_message,
            self.statement_message,
        ]
        if self.legacy_message:
            values.append(self.legacy_message)
        return tuple(dict.fromkeys(values))


@dataclass(frozen=True, slots=True)
class ClearingProfile:
    """How the simulated clearing system for this rail behaves."""

    clearing_system_name: str
    operator: str
    realistic_response_seconds: float
    realistic_timeout_seconds: int
    investigation_threshold_seconds: int
    settlement_finality: str
    operating_hours: str
    rejection_reason_codes: tuple[str, ...] = ("AM04", "AC01", "RR04", "FF01")


@dataclass(frozen=True, slots=True)
class SettlementProfile:
    settlement_method: str
    settlement_account_type: str
    settles_in_scheme_currency: bool
    value_date_offset_days: int
    description: str


@dataclass(frozen=True, slots=True)
class PaymentScheme:
    code: SchemeCode
    name: str
    short_name: str
    operator: str
    jurisdiction: str
    description: str
    simulation_notes: str
    rules: SchemeRules
    messages: MessageRules
    clearing: ClearingProfile
    settlement: SettlementProfile
    validation_rule_ids: tuple[str, ...] = field(default_factory=tuple)
    reference_links: tuple[str, ...] = field(default_factory=tuple)

    # -- behaviour -------------------------------------------------------
    def in_country_scope(self, country: str | None) -> bool:
        if self.rules.country_scope is None:
            return True
        return (country or "").upper() in self.rules.country_scope

    def value_date(self, base: date | None = None) -> date:
        return (base or datetime.now(UTC).date()) + timedelta(
            days=self.settlement.value_date_offset_days
        )

    def as_dict(self) -> dict:
        return {
            "code": self.code.value,
            "name": self.name,
            "shortName": self.short_name,
            "operator": self.operator,
            "jurisdiction": self.jurisdiction,
            "description": self.description,
            "simulationNotes": self.simulation_notes,
            "isInstant": self.rules.is_instant,
            "settlementCurrency": self.rules.settlement_currency,
            "allowedCurrencies": list(self.rules.allowed_currencies),
            "amountLimits": [
                {"currency": limit.currency, "minimum": str(limit.minimum), "maximum": str(limit.maximum)}
                for limit in self.rules.amount_limits
            ],
            "countryScope": list(self.rules.country_scope) if self.rules.country_scope else None,
            "maxRemittanceLength": self.rules.max_remittance_length,
            "requiresPurposeCode": self.rules.requires_purpose_code,
            "allowedServiceLevels": list(self.rules.allowed_service_levels),
            "allowedLocalInstruments": list(self.rules.allowed_local_instruments),
            "allowsFutureDated": self.rules.allows_future_dated,
            "maxFutureDays": self.rules.max_future_days,
            "duplicateWindowMinutes": self.rules.duplicate_window_minutes,
            "usesUetr": self.rules.uses_uetr,
            "supportsCancellation": self.rules.supports_cancellation,
            "supportsReturn": self.rules.supports_return,
            "messages": [m.value for m in self.messages.message_set],
            "legacyMessage": self.messages.legacy_message.value if self.messages.legacy_message else None,
            "clearing": {
                "system": self.clearing.clearing_system_name,
                "operator": self.clearing.operator,
                "responseSeconds": self.clearing.realistic_response_seconds,
                "timeoutSeconds": self.clearing.realistic_timeout_seconds,
                "investigationThresholdSeconds": self.clearing.investigation_threshold_seconds,
                "settlementFinality": self.clearing.settlement_finality,
                "operatingHours": self.clearing.operating_hours,
                "rejectionReasonCodes": list(self.clearing.rejection_reason_codes),
            },
            "settlement": {
                "method": self.settlement.settlement_method,
                "accountType": self.settlement.settlement_account_type,
                "settlesInSchemeCurrency": self.settlement.settles_in_scheme_currency,
                "valueDateOffsetDays": self.settlement.value_date_offset_days,
                "description": self.settlement.description,
            },
            "validationRuleIds": list(self.validation_rule_ids),
            "referenceLinks": list(self.reference_links),
        }
