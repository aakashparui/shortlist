"""Concrete scheme definitions.

IMPORTANT — DOMAIN ACCURACY
These definitions are *standards-inspired* configurations for a simulator. Real
scheme rulebooks (SIC/euroSIC, SEPA Instant Credit Transfer, SWIFT CBPR+) are
owned by their operators, change over time and contain far more detail than is
modelled here. Limits, cut-offs and timeouts below are plausible simulator
values, not an authoritative statement of any live rulebook.
"""

from __future__ import annotations

from datetime import time
from decimal import Decimal

from app.domain.enums import MessageType, SchemeCode
from app.domain.identifiers_bank import SEPA_COUNTRIES
from app.schemes.base import (
    AmountLimit,
    ClearingProfile,
    MessageRules,
    PaymentScheme,
    SchemeRules,
    SettlementProfile,
)

COMMON_RULE_IDS: tuple[str, ...] = (
    "VAL-STRUCT-001",
    "VAL-AMOUNT-001",
    "VAL-AMOUNT-002",
    "VAL-AMOUNT-003",
    "VAL-CCY-001",
    "VAL-DBTR-001",
    "VAL-DBTR-002",
    "VAL-CDTR-001",
    "VAL-CDTR-002",
    "VAL-BIC-001",
    "VAL-IBAN-001",
    "VAL-IBAN-002",
    "VAL-E2E-001",
    "VAL-DUP-001",
    "VAL-RMT-001",
    "VAL-DATE-001",
    "VAL-ACCT-001",
    "VAL-ACCT-002",
    "VAL-MSG-001",
    "VAL-MSG-002",
)


SIC_INSTANT = PaymentScheme(
    code=SchemeCode.SIC_INSTANT,
    name="SIC Instant Payments (simulated)",
    short_name="SIC Instant",
    operator="Simulated Swiss interbank clearing operator",
    jurisdiction="Switzerland (CHF)",
    description=(
        "Domestic Swiss instant credit transfer rail. Payments settle in CHF with "
        "near-real-time finality and a short status-report window."
    ),
    simulation_notes=(
        "SIMULATED IMPLEMENTATION. The real SIC/SIC IP service is operated by SIX Interbank "
        "Clearing on behalf of the Swiss National Bank. Participant obligations, amount "
        "thresholds and the reachability directory are not reproduced here."
    ),
    rules=SchemeRules(
        settlement_currency="CHF",
        allowed_currencies=("CHF",),
        amount_limits=(AmountLimit("CHF", Decimal("0.01"), Decimal("20000.00")),),
        requires_iban_debtor=True,
        requires_iban_creditor=True,
        requires_bic_creditor_agent=True,
        country_scope=("CH", "LI"),
        max_remittance_length=140,
        requires_purpose_code=False,
        allowed_charge_bearers=("SLEV",),
        allowed_service_levels=("SDVA", "URGP", "INST"),
        allowed_local_instruments=("INST",),
        allows_future_dated=False,
        duplicate_window_minutes=1440,
        cutoff_time_utc=None,
        is_instant=True,
        uses_uetr=False,
        supports_cancellation=True,
        supports_return=True,
    ),
    messages=MessageRules(
        settlement_method="CLRG",
        clearing_system_proprietary="SIC-IP",
        clearing_system_code=None,
    ),
    clearing=ClearingProfile(
        clearing_system_name="SIC Instant Clearing (simulated)",
        operator="SIMULATED-SIX-IC",
        realistic_response_seconds=2.0,
        realistic_timeout_seconds=25,
        investigation_threshold_seconds=25,
        settlement_finality="Immediate and irrevocable once accepted",
        operating_hours="24/7/365",
        rejection_reason_codes=("AM04", "AC01", "AC04", "RR04", "FF01", "AG01"),
    ),
    settlement=SettlementProfile(
        settlement_method="CLRG",
        settlement_account_type="SETTLEMENT",
        settles_in_scheme_currency=True,
        value_date_offset_days=0,
        description="Settled across the participant's central-bank settlement account, same day.",
    ),
    validation_rule_ids=COMMON_RULE_IDS + ("SIC-AMOUNT-001", "SIC-CCY-001", "SIC-COUNTRY-001"),
)


SEPA_INSTANT = PaymentScheme(
    code=SchemeCode.SEPA_INSTANT,
    name="SEPA Instant Credit Transfer (simulated)",
    short_name="SEPA Instant",
    operator="Simulated SEPA instant clearing and settlement mechanism",
    jurisdiction="SEPA area (EUR)",
    description=(
        "Euro instant credit transfer across the SEPA area. End-to-end execution is "
        "expected within seconds, with a hard scheme maximum execution time."
    ),
    simulation_notes=(
        "SIMULATED IMPLEMENTATION. The real SCT Inst scheme rulebook is published by the "
        "European Payments Council; maximum amounts and timing requirements have changed "
        "over successive rulebook versions and are not tracked here."
    ),
    rules=SchemeRules(
        settlement_currency="EUR",
        allowed_currencies=("EUR",),
        amount_limits=(AmountLimit("EUR", Decimal("0.01"), Decimal("100000.00")),),
        requires_iban_debtor=True,
        requires_iban_creditor=True,
        requires_bic_creditor_agent=False,
        country_scope=tuple(sorted(SEPA_COUNTRIES)),
        max_remittance_length=140,
        requires_purpose_code=False,
        allowed_charge_bearers=("SLEV",),
        allowed_service_levels=("SEPA", "INST"),
        allowed_local_instruments=("INST",),
        allows_future_dated=False,
        duplicate_window_minutes=1440,
        is_instant=True,
        uses_uetr=False,
        supports_cancellation=True,
        supports_return=True,
    ),
    messages=MessageRules(settlement_method="CLRG", clearing_system_proprietary="SCT-INST"),
    clearing=ClearingProfile(
        clearing_system_name="SEPA Instant CSM (simulated)",
        operator="SIMULATED-CSM",
        realistic_response_seconds=3.0,
        realistic_timeout_seconds=20,
        investigation_threshold_seconds=20,
        settlement_finality="Irrevocable once the positive status report is received",
        operating_hours="24/7/365",
        rejection_reason_codes=("AM02", "AC01", "AC06", "RR04", "FF01", "NARR"),
    ),
    settlement=SettlementProfile(
        settlement_method="CLRG",
        settlement_account_type="SETTLEMENT",
        settles_in_scheme_currency=True,
        value_date_offset_days=0,
        description="Pre-funded settlement position at the clearing and settlement mechanism.",
    ),
    validation_rule_ids=COMMON_RULE_IDS
    + ("SEPA-AMOUNT-001", "SEPA-CCY-001", "SEPA-COUNTRY-001", "SEPA-RMT-001"),
)


SWIFT_CROSS_BORDER = PaymentScheme(
    code=SchemeCode.SWIFT_CROSS_BORDER,
    name="SWIFT Cross-Border Credit Transfer (simulated)",
    short_name="SWIFT",
    operator="Simulated correspondent banking network",
    jurisdiction="Cross-border, multi-currency",
    description=(
        "Correspondent-banking credit transfer. Funds move through nostro/vostro "
        "accounts, tracking is by UETR, and the legacy MT103 equivalent is available "
        "for MT to MX comparison."
    ),
    simulation_notes=(
        "SIMULATED IMPLEMENTATION. Real cross-border payments depend on CBPR+ usage "
        "guidelines, correspondent agreements, FX execution and gpi tracking services. "
        "The UETR values here are locally generated and tracked only inside this simulator."
    ),
    rules=SchemeRules(
        settlement_currency="USD",
        allowed_currencies=("CHF", "EUR", "GBP", "USD", "INR", "JPY", "SGD", "AUD", "CAD"),
        amount_limits=(
            AmountLimit("CHF", Decimal("0.01"), Decimal("50000000.00")),
            AmountLimit("EUR", Decimal("0.01"), Decimal("50000000.00")),
            AmountLimit("GBP", Decimal("0.01"), Decimal("50000000.00")),
            AmountLimit("USD", Decimal("0.01"), Decimal("50000000.00")),
            AmountLimit("INR", Decimal("1.00"), Decimal("500000000.00")),
            AmountLimit("JPY", Decimal("1"), Decimal("5000000000")),
            AmountLimit("SGD", Decimal("0.01"), Decimal("50000000.00")),
            AmountLimit("AUD", Decimal("0.01"), Decimal("50000000.00")),
            AmountLimit("CAD", Decimal("0.01"), Decimal("50000000.00")),
        ),
        requires_iban_debtor=False,
        requires_iban_creditor=False,
        requires_bic_creditor_agent=True,
        country_scope=None,
        max_remittance_length=140,
        requires_purpose_code=False,
        allowed_charge_bearers=("DEBT", "CRED", "SHAR"),
        allowed_service_levels=("G001", "G002", "G003", "G004"),
        allowed_local_instruments=(),
        allows_future_dated=True,
        max_future_days=30,
        duplicate_window_minutes=2880,
        cutoff_time_utc=time(15, 0),
        is_instant=False,
        uses_uetr=True,
        supports_cancellation=True,
        supports_return=True,
        requires_creditor_address_for_cross_border=True,
    ),
    messages=MessageRules(
        settlement_method="INDA",
        clearing_system_proprietary=None,
        legacy_message=MessageType.MT_103,
    ),
    clearing=ClearingProfile(
        clearing_system_name="Correspondent Network (simulated)",
        operator="SIMULATED-CORRESPONDENT",
        realistic_response_seconds=8.0,
        realistic_timeout_seconds=60,
        investigation_threshold_seconds=60,
        settlement_finality="Final on correspondent account posting; intermediaries may deduct charges",
        operating_hours="Business hours of each correspondent, cut-off 15:00 UTC",
        rejection_reason_codes=("AC01", "BE01", "RR04", "FF01", "RC01", "CUST"),
    ),
    settlement=SettlementProfile(
        settlement_method="INDA",
        settlement_account_type="NOSTRO",
        settles_in_scheme_currency=False,
        value_date_offset_days=1,
        description=(
            "Settled by debiting the customer and crediting the correspondent's vostro / "
            "our nostro position, value date T+1."
        ),
    ),
    validation_rule_ids=COMMON_RULE_IDS
    + ("SWIFT-BIC-001", "SWIFT-ADDR-001", "SWIFT-CCY-001", "SWIFT-CUTOFF-001", "SWIFT-UETR-001"),
)


GENERIC_ISO20022 = PaymentScheme(
    code=SchemeCode.GENERIC_ISO20022,
    name="Generic ISO 20022 Credit Transfer (simulated)",
    short_name="Generic ISO",
    operator="Simulated generic clearing system",
    jurisdiction="Scheme-agnostic",
    description=(
        "A deliberately permissive rail used for teaching and for testing ISO 20022 "
        "message structure without scheme-specific restrictions."
    ),
    simulation_notes=(
        "SIMULATED IMPLEMENTATION. This rail exists only inside the simulator; there is no "
        "real-world equivalent. It applies the common validation rules and nothing more."
    ),
    rules=SchemeRules(
        settlement_currency="EUR",
        allowed_currencies=("CHF", "EUR", "GBP", "USD", "INR", "SEK", "NOK", "SGD", "AUD", "CAD"),
        amount_limits=(
            AmountLimit("CHF", Decimal("0.01"), Decimal("10000000.00")),
            AmountLimit("EUR", Decimal("0.01"), Decimal("10000000.00")),
            AmountLimit("GBP", Decimal("0.01"), Decimal("10000000.00")),
            AmountLimit("USD", Decimal("0.01"), Decimal("10000000.00")),
            AmountLimit("INR", Decimal("1.00"), Decimal("100000000.00")),
            AmountLimit("SEK", Decimal("0.01"), Decimal("10000000.00")),
            AmountLimit("NOK", Decimal("0.01"), Decimal("10000000.00")),
            AmountLimit("SGD", Decimal("0.01"), Decimal("10000000.00")),
            AmountLimit("AUD", Decimal("0.01"), Decimal("10000000.00")),
            AmountLimit("CAD", Decimal("0.01"), Decimal("10000000.00")),
        ),
        requires_iban_debtor=False,
        requires_iban_creditor=False,
        requires_bic_creditor_agent=False,
        country_scope=None,
        max_remittance_length=140,
        requires_purpose_code=False,
        allowed_charge_bearers=("SLEV", "DEBT", "CRED", "SHAR"),
        allowed_service_levels=("NURG", "SEPA", "SDVA"),
        allowed_local_instruments=(),
        allows_future_dated=True,
        max_future_days=90,
        duplicate_window_minutes=720,
        is_instant=False,
        uses_uetr=False,
        supports_cancellation=True,
        supports_return=True,
    ),
    messages=MessageRules(settlement_method="CLRG", clearing_system_proprietary="GENERIC-CSM"),
    clearing=ClearingProfile(
        clearing_system_name="Generic Clearing System (simulated)",
        operator="SIMULATED-GENERIC",
        realistic_response_seconds=4.0,
        realistic_timeout_seconds=30,
        investigation_threshold_seconds=30,
        settlement_finality="Final on acceptance",
        operating_hours="Business days 06:00-22:00 UTC",
        rejection_reason_codes=("AM04", "AC01", "RR04", "FF01", "NARR"),
    ),
    settlement=SettlementProfile(
        settlement_method="CLRG",
        settlement_account_type="SETTLEMENT",
        settles_in_scheme_currency=False,
        value_date_offset_days=0,
        description="Settled over a generic settlement account in the instructed currency.",
    ),
    validation_rule_ids=COMMON_RULE_IDS,
)

ALL_SCHEMES: tuple[PaymentScheme, ...] = (
    SIC_INSTANT,
    SEPA_INSTANT,
    SWIFT_CROSS_BORDER,
    GENERIC_ISO20022,
)
