"""The scenario library: 20 executable end-to-end scenarios.

Each scenario is a complete, runnable payment plus the failure injections that
reproduce a specific operational situation, and the assertions that say what
"correct" looks like. The QA Lab executes them and compares actual against
expected.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import Scenario
from app.domain.identifiers_bank import compute_iban

logger = get_logger(__name__)

# --- fictional counterparties ------------------------------------------------
CH_CREDITOR = {
    "name": "Zentrum Bauservice AG",
    "iban": compute_iban("CH", "0092010088776655"),
    "bic": "ALPNCHZZXXX",
    "bankName": "Alpine Kantonalbank",
    "country": "CH",
    "town": "Bern",
    "addressLines": ["Bundesgasse 14"],
}
CH_CREDITOR_2 = {
    "name": "Rigi Elektro GmbH",
    "iban": compute_iban("CH", "0093020011223344"),
    "bic": "HELVCHZZXXX",
    "bankName": "Helvetia Privatbank",
    "country": "CH",
    "town": "Basel",
    "addressLines": ["Freie Strasse 2"],
}
DE_CREDITOR = {
    "name": "Hanse Maschinen GmbH",
    "iban": compute_iban("DE", "500105170032198765"),
    "bic": "NORDDEFFXXX",
    "bankName": "Norddeutsche Handelsbank",
    "country": "DE",
    "town": "Hamburg",
    "addressLines": ["Speicherstadt 8"],
}
FR_CREDITOR = {
    "name": "Atelier Lumiere SARL",
    "iban": compute_iban("FR", "300060000112345678901"),
    "bic": "SEINFRPPXXX",
    "bankName": "Banque de la Seine",
    "country": "FR",
    "town": "Lyon",
    "addressLines": ["12 Rue de la Republique"],
}
NL_CREDITOR = {
    "name": "Delta Groothandel BV",
    "iban": compute_iban("NL", "AMST0123456789"),
    "bic": "AMSTNL2AXXX",
    "bankName": "Amstel Handelsbank",
    "country": "NL",
    "town": "Rotterdam",
    "addressLines": ["Havenweg 221"],
}
US_CREDITOR = {
    "name": "Mercer Analytics Inc",
    "accountIdentifier": "4410028876",
    "bic": "HUDSUS33XXX",
    "bankName": "Hudson River Bank",
    "country": "US",
    "town": "New York",
    "addressLines": ["120 Water Street", "Floor 9"],
}
IN_CREDITOR = {
    "name": "Sahyadri Components Pvt Ltd",
    "accountIdentifier": "9100245566778",
    "bic": "GANGINBBXXX",
    "bankName": "Ganga National Bank",
    "country": "IN",
    "town": "Pune",
    "addressLines": ["Plot 44, MIDC Industrial Area"],
}
GB_CREDITOR = {
    "name": "Thameside Freight Ltd",
    "iban": compute_iban("GB", "THAM20415538294"),
    "bic": "THAMGB2LXXX",
    "bankName": "Thames Commercial Bank",
    "country": "GB",
    "town": "London",
    "addressLines": ["4 Dockside Walk"],
}

CH_DEBTOR = {
    "name": "Lindenhof Maschinenbau AG",
    "iban": compute_iban("CH", "0091000012345678"),
    "bic": "SIMUCHZZXXX",
    "bankName": "Simulator Bank AG",
    "country": "CH",
    "town": "Zurich",
    "addressLines": ["Lindenhofstrasse 42"],
}
EUR_DEBTOR = {
    "name": "Lindenhof Maschinenbau AG",
    "iban": compute_iban("CH", "0091000012345679"),
    "bic": "SIMUCHZZXXX",
    "bankName": "Simulator Bank AG",
    "country": "CH",
    "town": "Zurich",
    "addressLines": ["Lindenhofstrasse 42"],
}
USD_DEBTOR = {
    "name": "Quintet Pharma Holding",
    "iban": compute_iban("CH", "0091000044112233"),
    "bic": "SIMUCHZZXXX",
    "bankName": "Simulator Bank AG",
    "country": "CH",
    "town": "Zug",
    "addressLines": ["Baarerstrasse 7"],
}
GBP_DEBTOR = {
    "name": "Rheintal Textil AG",
    "iban": compute_iban("CH", "0091000055998877"),
    "bic": "SIMUCHZZXXX",
    "bankName": "Simulator Bank AG",
    "country": "CH",
    "town": "St. Gallen",
    "addressLines": ["Rorschacher Strasse 19"],
}
INR_DEBTOR = {
    "name": "Matterhorn Imports AG",
    "iban": compute_iban("CH", "0091000077224466"),
    "bic": "SIMUCHZZXXX",
    "bankName": "Simulator Bank AG",
    "country": "CH",
    "town": "Lucerne",
    "addressLines": ["Pilatusstrasse 3"],
}


def sic(amount: str, creditor: dict | None = None, **overrides) -> dict:  # noqa: ANN003
    payload = {
        "scheme": "SIC_INSTANT",
        "amount": amount,
        "currency": "CHF",
        "debtor": dict(CH_DEBTOR),
        "creditor": dict(creditor or CH_CREDITOR),
        "remittanceInformation": "Invoice 2026-0481",
        "purposeCode": "GDDS",
        "serviceLevel": "INST",
        "localInstrument": "INST",
        "chargeBearer": "SLEV",
    }
    payload.update(overrides)
    return payload


def sepa(amount: str, creditor: dict | None = None, **overrides) -> dict:  # noqa: ANN003
    payload = {
        "scheme": "SEPA_INSTANT",
        "amount": amount,
        "currency": "EUR",
        "debtor": dict(EUR_DEBTOR),
        "creditor": dict(creditor or DE_CREDITOR),
        "remittanceInformation": "Order 884512 part delivery",
        "purposeCode": "SUPP",
        "serviceLevel": "SEPA",
        "localInstrument": "INST",
        "chargeBearer": "SLEV",
    }
    payload.update(overrides)
    return payload


def swift(amount: str, currency: str = "USD", creditor: dict | None = None, **overrides) -> dict:  # noqa: ANN003
    debtor = {"USD": USD_DEBTOR, "GBP": GBP_DEBTOR, "INR": INR_DEBTOR}.get(currency, USD_DEBTOR)
    payload = {
        "scheme": "SWIFT_CROSS_BORDER",
        "amount": amount,
        "currency": currency,
        "debtor": dict(debtor),
        "creditor": dict(creditor or US_CREDITOR),
        "remittanceInformation": "Consultancy services Q1",
        "purposeCode": "SERV",
        "serviceLevel": "G001",
        "chargeBearer": "SHAR",
    }
    payload.update(overrides)
    return payload


def generic(amount: str, currency: str = "GBP", creditor: dict | None = None, **overrides) -> dict:  # noqa: ANN003
    payload = {
        "scheme": "GENERIC_ISO20022",
        "amount": amount,
        "currency": currency,
        "debtor": dict(GBP_DEBTOR if currency == "GBP" else CH_DEBTOR),
        "creditor": dict(creditor or GB_CREDITOR),
        "remittanceInformation": "Freight settlement week 12",
        "chargeBearer": "SHAR",
    }
    payload.update(overrides)
    return payload


STANDARD_STEPS = [
    "Create the payment with the scenario input data",
    "Execute the payment",
    "Observe validation, compliance and message generation",
    "Observe the clearing dispatch and the pacs.002 response",
    "Observe settlement, accounting and reconciliation",
    "Inspect the resulting payment status",
]

SCENARIOS: tuple[dict, ...] = (
    {
        "code": "SC-01",
        "title": "Successful instant payment (SIC)",
        "category": "HAPPY_PATH",
        "scheme": "SIC_INSTANT",
        "description": (
            "A domestic CHF instant payment that passes every check, is accepted by the clearing "
            "system, settles, is accounted for and reconciles cleanly."
        ),
        "business_context": (
            "The reference case. Everything an operations team expects to see when nothing goes "
            "wrong, and the baseline every failure scenario is compared against."
        ),
        "preconditions": [
            "The debtor CHF account exists and has sufficient funds",
            "The creditor is a reachable domestic participant",
            "No failure injection is registered",
        ],
        "input_data": sic("4850.00"),
        "failure_codes": [],
        "execution_steps": STANDARD_STEPS,
        "expected_status": "COMPLETED",
        "expected_result": [
            "All validation rules pass",
            "No compliance hits",
            "pacs.008 generated and dispatched",
            "pacs.002 ACSC received",
            "Settlement status SETTLED",
            "Balanced double-entry journal posted",
            "Reconciliation MATCHED",
        ],
        "expected_messages": ["pacs.008", "pacs.002", "camt.054"],
        "expected_accounting": [
            "DEBIT customer CHF account 4850.00",
            "CREDIT settlement CHF account 4850.00",
        ],
        "expected_reconciliation": "MATCHED",
        "failure_conditions": [
            "Any validation rule fails",
            "pacs.002 is not received",
            "Reconciliation reports anything other than MATCHED",
        ],
        "is_demo_highlight": True,
        "sort_order": 1,
    },
    {
        "code": "SC-02",
        "title": "Invalid IBAN",
        "category": "VALIDATION",
        "scheme": "SIC_INSTANT",
        "description": "The creditor IBAN fails the ISO 13616 check-digit test.",
        "business_context": (
            "The most common data-quality rejection. The payment never reaches the clearing "
            "system, so no funds move and no reversal is needed."
        ),
        "preconditions": ["A valid payment is prepared", "The creditor IBAN is then corrupted"],
        "input_data": sic("1200.00"),
        "failure_codes": ["INVALID_CREDITOR_IBAN"],
        "execution_steps": STANDARD_STEPS[:3] + ["Inspect the failing validation result"],
        "expected_status": "REJECTED",
        "expected_result": [
            "VAL-IBAN-002 status FAILED with reason code AC01",
            "Payment status REJECTED",
            "No pacs.008 generated",
            "No accounting entries",
        ],
        "expected_messages": [],
        "expected_accounting": ["No entries: the payment was rejected before execution"],
        "expected_reconciliation": "NOT_RUN",
        "failure_conditions": ["The payment reaches the clearing stage"],
        "sort_order": 2,
    },
    {
        "code": "SC-03",
        "title": "Duplicate payment",
        "category": "VALIDATION",
        "scheme": "SIC_INSTANT",
        "description": "The EndToEndId has already been used on the same rail inside the duplicate window.",
        "business_context": (
            "Duplicate submission is a leading cause of customer double debits. The check must "
            "fire before the instruction is sent."
        ),
        "preconditions": ["At least one earlier payment exists on the same scheme"],
        "input_data": sic("760.00", CH_CREDITOR_2),
        "failure_codes": ["DUPLICATE_END_TO_END_ID"],
        "execution_steps": STANDARD_STEPS[:3] + ["Inspect the duplicate check result"],
        "expected_status": "REJECTED",
        "expected_result": [
            "VAL-DUP-001 status FAILED with reason code AM05",
            "The validation result names the earlier payment reference",
            "Payment status REJECTED",
        ],
        "expected_messages": [],
        "expected_accounting": ["No entries"],
        "expected_reconciliation": "NOT_RUN",
        "failure_conditions": ["The duplicate is accepted for clearing"],
        "is_demo_highlight": True,
        "sort_order": 3,
    },
    {
        "code": "SC-04",
        "title": "Embargo hit",
        "category": "COMPLIANCE",
        "scheme": "SWIFT_CROSS_BORDER",
        "description": "The creditor is located in a (fictional) embargoed jurisdiction.",
        "business_context": (
            "The payment must stop before any message leaves the bank, and the alert must reach "
            "the financial-crime team with the matched value and list reference."
        ),
        "preconditions": ["Screening is enabled", "The creditor country is set to an embargoed code"],
        "input_data": swift("25000.00"),
        "failure_codes": ["EMBARGO_HIT"],
        "execution_steps": STANDARD_STEPS[:3] + ["Inspect the compliance stage and the investigation"],
        "expected_status": "INVESTIGATION_REQUIRED",
        "expected_result": [
            "COMP-EMB-001 status FAILED",
            "Payment passes through BLOCKED",
            "An investigation is opened with reason COMPLIANCE_BLOCK",
            "No pacs.008 is dispatched",
        ],
        "expected_messages": [],
        "expected_accounting": ["No entries"],
        "expected_reconciliation": "NOT_RUN",
        "failure_conditions": ["The payment is sent to clearing despite the hit"],
        "is_demo_highlight": True,
        "sort_order": 4,
    },
    {
        "code": "SC-05",
        "title": "Clearing rejection",
        "category": "CLEARING",
        "scheme": "SIC_INSTANT",
        "description": "The clearing system returns pacs.002 RJCT with AC01.",
        "business_context": (
            "The instruction was valid on our side but the beneficiary bank cannot apply it. Any "
            "customer debit must be reversed."
        ),
        "preconditions": ["The payment passes all our own checks"],
        "input_data": sic("3300.00"),
        "failure_codes": ["CLEARING_REJECT_BUSINESS"],
        "execution_steps": STANDARD_STEPS,
        "expected_status": "CLEARING_REJECTED",
        "expected_result": [
            "pacs.008 dispatched",
            "pacs.002 RJCT received with reason AC01",
            "Payment status CLEARING_REJECTED",
            "Clearing transaction status REJECTED",
        ],
        "expected_messages": ["pacs.008", "pacs.002"],
        "expected_accounting": ["No net customer debit remains"],
        "expected_reconciliation": "NOT_RUN",
        "failure_conditions": ["The payment settles despite the rejection"],
        "is_demo_highlight": True,
        "sort_order": 5,
    },
    {
        "code": "SC-06",
        "title": "Clearing timeout",
        "category": "TIMEOUT",
        "scheme": "SIC_INSTANT",
        "description": "No pacs.002 arrives within the scheme threshold.",
        "business_context": (
            "The hardest operational case: the payment may or may not have been processed. The "
            "bank must investigate rather than resend."
        ),
        "preconditions": ["The clearing system is configured not to answer"],
        "input_data": sic("9900.00"),
        "failure_codes": ["CLEARING_TIMEOUT"],
        "execution_steps": STANDARD_STEPS[:4]
        + ["Wait for the scheme timeout", "Inspect the pacs.028 and the investigation"],
        "expected_status": "INVESTIGATION_REQUIRED",
        "expected_result": [
            "Clearing transaction status TIMED_OUT",
            "Payment passes through TIMED_OUT",
            "pacs.028 status request sent",
            "An investigation is opened with reason CLEARING_TIMEOUT",
        ],
        "expected_messages": ["pacs.008", "pacs.028"],
        "expected_accounting": ["No entries: settlement never happened"],
        "expected_reconciliation": "NOT_RUN",
        "failure_conditions": ["The payment completes", "No investigation is opened"],
        "is_demo_highlight": True,
        "sort_order": 6,
    },
    {
        "code": "SC-07",
        "title": "pacs.002 delayed",
        "category": "TIMEOUT",
        "scheme": "SEPA_INSTANT",
        "description": "The status report arrives late, but still inside the scheme window.",
        "business_context": (
            "A latency problem rather than a payment problem. The payment completes, but the "
            "recorded latency should be visible for SLA reporting."
        ),
        "preconditions": ["The clearing system is configured to answer close to the threshold"],
        "input_data": sepa("15400.00"),
        "failure_codes": ["CLEARING_DELAY"],
        "execution_steps": STANDARD_STEPS,
        "expected_status": "COMPLETED",
        "expected_result": [
            "pacs.002 ACSC received",
            "Clearing response latency recorded and elevated",
            "Payment status COMPLETED",
            "Reconciliation MATCHED",
        ],
        "expected_messages": ["pacs.008", "pacs.002", "camt.054"],
        "expected_accounting": ["DEBIT customer EUR account", "CREDIT settlement EUR account"],
        "expected_reconciliation": "MATCHED",
        "failure_conditions": ["The payment times out"],
        "sort_order": 7,
    },
    {
        "code": "SC-08",
        "title": "Customer debited but clearing rejected",
        "category": "CLEARING",
        "scheme": "SEPA_INSTANT",
        "description": (
            "A technical rejection arrives from the clearing system; the customer debit must be "
            "reversed and the customer made whole."
        ),
        "business_context": (
            "Tests the reversal path. The customer must not be left out of pocket for a payment "
            "the scheme refused."
        ),
        "preconditions": ["The payment passes validation", "Clearing returns a technical rejection"],
        "input_data": sepa("2750.00", FR_CREDITOR),
        "failure_codes": ["CLEARING_REJECT_TECHNICAL"],
        "execution_steps": STANDARD_STEPS + ["Inspect the reversal entries"],
        "expected_status": "CLEARING_REJECTED",
        "expected_result": [
            "pacs.002 RJCT / FF01 received",
            "Payment status CLEARING_REJECTED",
            "Any posted customer debit is reversed",
        ],
        "expected_messages": ["pacs.008", "pacs.002"],
        "expected_accounting": ["Reversal entries bring the net customer movement to zero"],
        "expected_reconciliation": "NOT_RUN",
        "failure_conditions": ["A net customer debit remains"],
        "sort_order": 8,
    },
    {
        "code": "SC-09",
        "title": "Clearing accepted but beneficiary not credited",
        "category": "INVESTIGATION",
        "scheme": "SWIFT_CROSS_BORDER",
        "description": (
            "Everything on our side succeeded, but the customer reports the beneficiary never "
            "received the funds."
        ),
        "business_context": (
            "The classic cross-border claim. The investigation must go out to the beneficiary "
            "bank; the customer debit must not be unilaterally reversed."
        ),
        "preconditions": ["The payment completes end to end", "The customer then raises a claim"],
        "input_data": swift("48000.00"),
        "failure_codes": ["BENEFICIARY_NOT_CREDITED"],
        "execution_steps": STANDARD_STEPS + ["Inspect the claim investigation and the camt.056/camt.029"],
        "expected_status": "INVESTIGATION_REQUIRED",
        "expected_result": [
            "Payment reaches COMPLETED before the claim",
            "An investigation with reason BENEFICIARY_NOT_CREDITED is opened",
            "camt.056 cancellation request sent",
            "camt.029 resolution received",
        ],
        "expected_messages": ["pacs.008", "pacs.002", "camt.054", "camt.056", "camt.029", "MT103"],
        "expected_accounting": ["Original entries remain; nothing is reversed unilaterally"],
        "expected_reconciliation": "MATCHED",
        "failure_conditions": ["The customer debit is reversed without the beneficiary bank's answer"],
        "is_demo_highlight": True,
        "sort_order": 9,
    },
    {
        "code": "SC-10",
        "title": "Settlement completed but internal status remains pending",
        "category": "SETTLEMENT",
        "scheme": "SIC_INSTANT",
        "description": "The settlement platform settled, but the status callback to the payment engine was lost.",
        "business_context": (
            "A stale-status break. Value has moved; the payment engine does not know it. Re-"
            "settling would double the movement."
        ),
        "preconditions": ["Clearing accepts the payment"],
        "input_data": sic("6400.00"),
        "failure_codes": ["SETTLEMENT_STATUS_NOT_UPDATED"],
        "execution_steps": STANDARD_STEPS + ["Compare the settlement record against the payment status"],
        "expected_status": "INVESTIGATION_REQUIRED",
        "expected_result": [
            "Settlement transaction status SETTLED",
            "Payment does not reach SETTLED",
            "An investigation with reason SETTLEMENT_FAILURE is opened",
        ],
        "expected_messages": ["pacs.008", "pacs.002"],
        "expected_accounting": ["No journal posted: the lifecycle stopped at settlement"],
        "expected_reconciliation": "NOT_RUN",
        "failure_conditions": ["The payment is marked completed"],
        "sort_order": 10,
    },
    {
        "code": "SC-11",
        "title": "Settlement completed but camt.054 missing",
        "category": "RECONCILIATION",
        "scheme": "SIC_INSTANT",
        "description": "No statement notification is received for a payment that settled and was accounted for.",
        "business_context": (
            "A reconciliation break caused by a missing notification rather than a missing "
            "movement. The resolution is a statement re-send, not a repair of the payment."
        ),
        "preconditions": ["The payment settles and the journal is posted"],
        "input_data": sic("5000.00"),
        "failure_codes": ["RECON_MISSING_CAMT054"],
        "execution_steps": STANDARD_STEPS + ["Inspect the reconciliation record and its legs"],
        "expected_status": "INVESTIGATION_REQUIRED",
        "expected_result": [
            "Reconciliation status MISSING_ENTRY",
            "The statement leg is marked as not present",
            "An investigation with reason RECONCILIATION_BREAK is opened",
        ],
        "expected_messages": ["pacs.008", "pacs.002"],
        "expected_accounting": ["Balanced journal posted"],
        "expected_reconciliation": "MISSING_ENTRY",
        "failure_conditions": ["Reconciliation reports MATCHED"],
        "is_demo_highlight": True,
        "sort_order": 11,
    },
    {
        "code": "SC-12",
        "title": "Statement contains an unmatched transaction",
        "category": "RECONCILIATION",
        "scheme": "SIC_INSTANT",
        "description": "An extra movement appears on the statement with no internal payment record.",
        "business_context": (
            "The payment itself reconciles, but the account shows a movement the bank cannot "
            "explain. It belongs in the reconciliation exception queue."
        ),
        "preconditions": ["The payment completes normally"],
        "input_data": sic("2100.00", CH_CREDITOR_2),
        "failure_codes": ["RECON_UNMATCHED_STATEMENT"],
        "execution_steps": STANDARD_STEPS + ["Open the reconciliation exception queue"],
        "expected_status": "COMPLETED",
        "expected_result": [
            "Payment reconciliation MATCHED",
            "One orphan statement entry exists",
            "The orphan entry appears in the unmatched statement queue",
        ],
        "expected_messages": ["pacs.008", "pacs.002", "camt.054"],
        "expected_accounting": ["Balanced journal posted"],
        "expected_reconciliation": "MATCHED",
        "failure_conditions": ["No unmatched entry is reported"],
        "sort_order": 12,
    },
    {
        "code": "SC-13",
        "title": "Amount mismatch",
        "category": "RECONCILIATION",
        "scheme": "SWIFT_CROSS_BORDER",
        "description": "The statement amount is lower than the internal amount.",
        "business_context": (
            "Typical of correspondent charges deducted in transit against a payment instructed "
            "with the charges on the ordering customer."
        ),
        "preconditions": ["The payment completes", "The statement entry carries a deduction"],
        "input_data": swift("12000.00"),
        "failure_codes": ["RECON_AMOUNT_MISMATCH"],
        "execution_steps": STANDARD_STEPS + ["Compare the four reconciliation legs"],
        "expected_status": "INVESTIGATION_REQUIRED",
        "expected_result": [
            "Reconciliation status AMOUNT_MISMATCH",
            "The difference amount is recorded",
            "The probable cause names charges or FX as the likely explanation",
        ],
        "expected_messages": ["pacs.008", "pacs.002", "camt.054", "MT103"],
        "expected_accounting": ["Balanced journal posted"],
        "expected_reconciliation": "AMOUNT_MISMATCH",
        "failure_conditions": ["Reconciliation reports MATCHED"],
        "is_demo_highlight": True,
        "sort_order": 13,
    },
    {
        "code": "SC-14",
        "title": "Currency mismatch",
        "category": "RECONCILIATION",
        "scheme": "GENERIC_ISO20022",
        "description": "The statement entry is denominated in a different currency.",
        "business_context": (
            "Usually a nostro mapping error: the movement hit the wrong currency account. It must "
            "not be auto-matched."
        ),
        "preconditions": ["The payment completes"],
        "input_data": generic("8800.00", "GBP"),
        "failure_codes": ["RECON_CURRENCY_MISMATCH"],
        "execution_steps": STANDARD_STEPS + ["Inspect the currency on each leg"],
        "expected_status": "INVESTIGATION_REQUIRED",
        "expected_result": [
            "Reconciliation status CURRENCY_MISMATCH",
            "The statement leg shows a different currency from the internal leg",
        ],
        "expected_messages": ["pacs.008", "pacs.002", "camt.054"],
        "expected_accounting": ["Balanced journal posted"],
        "expected_reconciliation": "CURRENCY_MISMATCH",
        "failure_conditions": ["Reconciliation reports MATCHED"],
        "sort_order": 14,
    },
    {
        "code": "SC-15",
        "title": "Accounting entry missing",
        "category": "ACCOUNTING",
        "scheme": "SIC_INSTANT",
        "description": "The customer is debited but the settlement credit leg is never posted.",
        "business_context": (
            "An unbalanced journal. The ledger will not agree with the statement and the general "
            "ledger control account will be out."
        ),
        "preconditions": ["The payment settles"],
        "input_data": sic("3150.00"),
        "failure_codes": ["ACCOUNTING_MISSING_ENTRY"],
        "execution_steps": STANDARD_STEPS + ["Inspect the journal and the totals"],
        "expected_status": "INVESTIGATION_REQUIRED",
        "expected_result": [
            "Only one accounting entry exists",
            "Total debits do not equal total credits",
            "Payment passes through ACCOUNTING_BREAK",
            "An investigation with reason ACCOUNTING_BREAK is opened",
        ],
        "expected_messages": ["pacs.008", "pacs.002"],
        "expected_accounting": ["DEBIT customer account only; credit leg absent"],
        "expected_reconciliation": "MISSING_ENTRY",
        "failure_conditions": ["The journal balances"],
        "is_demo_highlight": True,
        "sort_order": 15,
    },
    {
        "code": "SC-16",
        "title": "Duplicate settlement",
        "category": "ACCOUNTING",
        "scheme": "SIC_INSTANT",
        "description": "The settlement credit leg is posted twice.",
        "business_context": (
            "Double posting overstates the ledger. The duplicate must be identified and reversed, "
            "not netted off silently."
        ),
        "preconditions": ["The payment settles"],
        "input_data": sic("1875.00", CH_CREDITOR_2),
        "failure_codes": ["ACCOUNTING_DUPLICATE_ENTRY"],
        "execution_steps": STANDARD_STEPS + ["Inspect the duplicate entry flag"],
        "expected_status": "INVESTIGATION_REQUIRED",
        "expected_result": [
            "Two credit entries exist, one flagged as a duplicate",
            "Reconciliation status DUPLICATE",
            "An investigation is opened",
        ],
        "expected_messages": ["pacs.008", "pacs.002"],
        "expected_accounting": ["One debit, two credits"],
        "expected_reconciliation": "DUPLICATE",
        "failure_conditions": ["Only one credit entry is recorded"],
        "sort_order": 16,
    },
    {
        "code": "SC-17",
        "title": "Payment returned",
        "category": "RETURN",
        "scheme": "SEPA_INSTANT",
        "description": "The beneficiary bank returns the payment with pacs.004 because the account is closed.",
        "business_context": (
            "A completed payment can still come back. The journal must be reversed and the "
            "customer re-credited."
        ),
        "preconditions": ["The payment completes end to end"],
        "input_data": sepa("4300.00", NL_CREDITOR),
        "failure_codes": ["BENEFICIARY_RETURN"],
        "execution_steps": STANDARD_STEPS + ["Inspect the pacs.004 and the reversal journal"],
        "expected_status": "RETURNED",
        "expected_result": [
            "pacs.004 received with reason AC04",
            "Payment status RETURNED",
            "Reversal entries posted",
            "Settlement transaction status REVERSED",
        ],
        "expected_messages": ["pacs.008", "pacs.002", "camt.054", "pacs.004"],
        "expected_accounting": ["Original journal reversed; net customer movement zero"],
        "expected_reconciliation": "MATCHED",
        "failure_conditions": ["The customer is left debited"],
        "is_demo_highlight": True,
        "sort_order": 17,
    },
    {
        "code": "SC-18",
        "title": "Cancellation request",
        "category": "INVESTIGATION",
        "scheme": "SWIFT_CROSS_BORDER",
        "description": "The operator sends a camt.056 cancellation request for a payment in flight.",
        "business_context": (
            "A cancellation request is a request, not a guarantee. The beneficiary bank decides, "
            "and the camt.029 records the answer."
        ),
        "preconditions": ["The payment has been dispatched to clearing"],
        "input_data": swift("31000.00", "GBP", GB_CREDITOR),
        "failure_codes": ["CLEARING_TIMEOUT"],
        "execution_steps": STANDARD_STEPS[:4]
        + [
            "Wait for the timeout and the investigation",
            "Send a camt.056 cancellation request from the investigation workbench",
            "Inspect the camt.029 resolution",
        ],
        "expected_status": "INVESTIGATION_REQUIRED",
        "expected_result": [
            "An investigation is open",
            "camt.056 can be sent from the investigation",
            "camt.029 records the resolution",
        ],
        "expected_messages": ["pacs.008", "pacs.028", "MT103"],
        "expected_accounting": ["No entries"],
        "expected_reconciliation": "NOT_RUN",
        "failure_conditions": ["The cancellation request cannot be sent"],
        "sort_order": 18,
    },
    {
        "code": "SC-19",
        "title": "Investigation required - malformed status report",
        "category": "INVESTIGATION",
        "scheme": "SIC_INSTANT",
        "description": "A pacs.002 arrives without the original end-to-end identification and cannot be matched.",
        "business_context": (
            "A real integration problem: a response exists but cannot be applied automatically. "
            "The payment must not be retried blindly."
        ),
        "preconditions": ["The payment is dispatched to clearing"],
        "input_data": sic("7250.00"),
        "failure_codes": ["CLEARING_MALFORMED_RESPONSE"],
        "execution_steps": STANDARD_STEPS + ["Inspect the unmatched status report and the investigation"],
        "expected_status": "INVESTIGATION_REQUIRED",
        "expected_result": [
            "A pacs.002 is recorded and flagged as malformed",
            "The clearing transaction is still awaiting a usable response",
            "An investigation is opened",
        ],
        "expected_messages": ["pacs.008", "pacs.002"],
        "expected_accounting": ["No entries"],
        "expected_reconciliation": "NOT_RUN",
        "failure_conditions": ["The malformed response is processed as valid"],
        "sort_order": 19,
    },
    {
        "code": "SC-20",
        "title": "Successful end-to-end cross-border payment",
        "category": "HAPPY_PATH",
        "scheme": "SWIFT_CROSS_BORDER",
        "description": (
            "A USD correspondent-banking payment that completes end to end, with UETR tracking "
            "and the MT103 legacy equivalent for MT to MX comparison."
        ),
        "business_context": (
            "The cross-border reference case. Shows nostro settlement, UETR tracking and the "
            "legacy message alongside the ISO 20022 message."
        ),
        "preconditions": [
            "The USD nostro account is funded",
            "The creditor agent BIC and address are supplied",
        ],
        "input_data": swift("86500.00", "USD", US_CREDITOR),
        "failure_codes": [],
        "execution_steps": STANDARD_STEPS + ["Open the MT to MX mapping view", "Inspect the UETR tracking"],
        "expected_status": "COMPLETED",
        "expected_result": [
            "All validation and compliance checks pass",
            "pacs.008 generated with a UETR",
            "MT103 legacy equivalent generated",
            "Settlement across the USD nostro, value date T+1",
            "Reconciliation MATCHED",
        ],
        "expected_messages": ["pacs.008", "MT103", "pacs.002", "camt.054"],
        "expected_accounting": [
            "DEBIT customer USD account 86500.00",
            "CREDIT USD nostro account 86500.00",
        ],
        "expected_reconciliation": "MATCHED",
        "failure_conditions": ["No UETR is present", "No MT103 is generated"],
        "is_demo_highlight": True,
        "sort_order": 20,
    },
)


def seed_scenarios(session: Session) -> dict[str, int]:
    stats = {"created": 0, "updated": 0}
    existing = {s.code: s for s in session.execute(select(Scenario)).scalars()}
    for spec in SCENARIOS:
        current = existing.get(spec["code"])
        if current is None:
            session.add(Scenario(**spec))
            stats["created"] += 1
        else:
            for key, value in spec.items():
                setattr(current, key, value)
            stats["updated"] += 1
    session.flush()
    logger.info("scenarios seeded", extra=stats)
    return stats
