"""Fictional reference data: banks, accounts, nostro/vostro positions.

EVERY institution, BIC, IBAN, account number and name in this module is
invented for the simulator. No real customer or institution data is used.
The BICs follow the ISO 9362 *structure* but are not registered codes.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import Account, Bank
from app.domain.enums import AccountType, SchemeCode
from app.domain.identifiers_bank import compute_iban

logger = get_logger(__name__)

ALL = [s.value for s in SchemeCode]
DOMESTIC = [SchemeCode.SIC_INSTANT.value, SchemeCode.GENERIC_ISO20022.value]
SEPA = [SchemeCode.SEPA_INSTANT.value, SchemeCode.GENERIC_ISO20022.value]
CROSS = [SchemeCode.SWIFT_CROSS_BORDER.value, SchemeCode.GENERIC_ISO20022.value]

BANKS: tuple[dict, ...] = (
    {
        "bic": "SIMUCHZZXXX",
        "name": "Simulator Bank AG",
        "country": "CH",
        "city": "Zurich",
        "national_clearing_code": "CH910000",
        "supported_schemes": ALL,
        "is_internal": True,
        "notes": "The simulated institution this platform operates on behalf of. Fictional.",
    },
    {
        "bic": "ALPNCHZZXXX",
        "name": "Alpine Kantonalbank",
        "country": "CH",
        "city": "Bern",
        "national_clearing_code": "CH920100",
        "supported_schemes": DOMESTIC,
        "notes": "Fictional Swiss direct SIC participant.",
    },
    {
        "bic": "HELVCHZZXXX",
        "name": "Helvetia Privatbank",
        "country": "CH",
        "city": "Basel",
        "national_clearing_code": "CH930200",
        "supported_schemes": DOMESTIC,
        "notes": "Fictional Swiss private bank.",
    },
    {
        "bic": "LEMACHGGXXX",
        "name": "Leman Banque SA",
        "country": "CH",
        "city": "Geneva",
        "national_clearing_code": "CH940300",
        "supported_schemes": DOMESTIC,
        "notes": "Fictional Swiss retail bank.",
    },
    {
        "bic": "RHEILI22XXX",
        "name": "Rhein Bank Liechtenstein",
        "country": "LI",
        "city": "Vaduz",
        "supported_schemes": DOMESTIC + SEPA,
        "notes": "Fictional Liechtenstein participant, reachable on the domestic rail.",
    },
    {
        "bic": "NORDDEFFXXX",
        "name": "Norddeutsche Handelsbank",
        "country": "DE",
        "city": "Frankfurt am Main",
        "supported_schemes": SEPA + CROSS,
        "notes": "Fictional German bank and EUR correspondent.",
    },
    {
        "bic": "SEINFRPPXXX",
        "name": "Banque de la Seine",
        "country": "FR",
        "city": "Paris",
        "supported_schemes": SEPA,
        "notes": "Fictional French SEPA participant.",
    },
    {
        "bic": "TIBEITMMXXX",
        "name": "Banca del Tevere",
        "country": "IT",
        "city": "Milan",
        "supported_schemes": SEPA,
        "notes": "Fictional Italian SEPA participant.",
    },
    {
        "bic": "AMSTNL2AXXX",
        "name": "Amstel Handelsbank",
        "country": "NL",
        "city": "Amsterdam",
        "supported_schemes": SEPA,
        "notes": "Fictional Dutch SEPA participant.",
    },
    {
        "bic": "IBERESMMXXX",
        "name": "Banco Iberia",
        "country": "ES",
        "city": "Madrid",
        "supported_schemes": SEPA,
        "notes": "Fictional Spanish SEPA participant.",
    },
    {
        "bic": "THAMGB2LXXX",
        "name": "Thames Commercial Bank",
        "country": "GB",
        "city": "London",
        "supported_schemes": CROSS + SEPA,
        "notes": "Fictional UK bank and GBP correspondent.",
    },
    {
        "bic": "HUDSUS33XXX",
        "name": "Hudson River Bank",
        "country": "US",
        "city": "New York",
        "supported_schemes": CROSS,
        "notes": "Fictional US correspondent holding our USD nostro.",
    },
    {
        "bic": "GANGINBBXXX",
        "name": "Ganga National Bank",
        "country": "IN",
        "city": "Mumbai",
        "supported_schemes": CROSS,
        "notes": "Fictional Indian correspondent holding our INR nostro.",
    },
    {
        "bic": "MARIJPJTXXX",
        "name": "Marina Bank Tokyo",
        "country": "JP",
        "city": "Tokyo",
        "supported_schemes": CROSS,
        "notes": "Fictional Japanese correspondent.",
    },
    {
        "bic": "RAFFSGSGXXX",
        "name": "Raffles Merchant Bank",
        "country": "SG",
        "city": "Singapore",
        "supported_schemes": CROSS,
        "notes": "Fictional Singapore correspondent.",
    },
    {
        "bic": "ZZZZZZ22XXX",
        "name": "Zedland State Bank",
        "country": "ZZ",
        "city": "Zedport",
        "is_direct_participant": False,
        "supported_schemes": [],
        "notes": (
            "Fictional institution in the simulator's fictional embargo jurisdiction. Used to "
            "demonstrate compliance screening; it is not a real bank or a real country code."
        ),
    },
)


def _ch_iban(bban_digits: str) -> str:
    return compute_iban("CH", bban_digits)


CUSTOMER_ACCOUNTS: tuple[dict, ...] = (
    {
        "account_number": "0012-345678-01",
        "bban": "0091000012345678",
        "name": "Lindenhof Maschinenbau AG",
        "currency": "CHF",
        "balance": Decimal("485000.00"),
        "overdraft_limit": Decimal("50000.00"),
        "description": "Fictional corporate current account, primary CHF operating account.",
    },
    {
        "account_number": "0012-345678-02",
        "bban": "0091000012345679",
        "name": "Lindenhof Maschinenbau AG - EUR",
        "currency": "EUR",
        "balance": Decimal("212400.00"),
        "overdraft_limit": Decimal("25000.00"),
        "description": "Fictional corporate EUR account used for SEPA payments.",
    },
    {
        "account_number": "0022-887766-01",
        "bban": "0091000022887766",
        "name": "Seefeld Trading GmbH",
        "currency": "CHF",
        "balance": Decimal("96750.50"),
        "overdraft_limit": Decimal("10000.00"),
        "description": "Fictional SME current account.",
    },
    {
        "account_number": "0033-556677-01",
        "bban": "0091000033556677",
        "name": "Aare Logistics SA",
        "currency": "CHF",
        "balance": Decimal("38900.00"),
        "description": "Fictional logistics company account with no overdraft facility.",
    },
    {
        "account_number": "0044-112233-01",
        "bban": "0091000044112233",
        "name": "Quintet Pharma Holding",
        "currency": "USD",
        "balance": Decimal("1250000.00"),
        "overdraft_limit": Decimal("100000.00"),
        "description": "Fictional USD account used for cross-border payments.",
    },
    {
        "account_number": "0055-998877-01",
        "bban": "0091000055998877",
        "name": "Rheintal Textil AG",
        "currency": "GBP",
        "balance": Decimal("184300.00"),
        "description": "Fictional GBP account.",
    },
    {
        "account_number": "0066-443322-01",
        "bban": "0091000066443322",
        "name": "Bellevue Consulting Sarl",
        "currency": "EUR",
        "balance": Decimal("57200.00"),
        "description": "Fictional consultancy EUR account.",
    },
    {
        "account_number": "0077-224466-01",
        "bban": "0091000077224466",
        "name": "Matterhorn Imports AG",
        "currency": "INR",
        "balance": Decimal("9850000.00"),
        "description": "Fictional INR funding account for Indian supplier payments.",
    },
)

NOSTRO_ACCOUNTS: tuple[dict, ...] = (
    {
        "account_number": "NOSTRO-USD-HUDSUS33",
        "name": "Nostro USD at Hudson River Bank",
        "currency": "USD",
        "correspondent_bic": "HUDSUS33XXX",
        "balance": Decimal("4750000.00"),
        "description": (
            "Our account held with the US correspondent. Outgoing USD payments debit the customer "
            "and credit (reduce) this nostro position."
        ),
    },
    {
        "account_number": "NOSTRO-EUR-NORDDEFF",
        "name": "Nostro EUR at Norddeutsche Handelsbank",
        "currency": "EUR",
        "correspondent_bic": "NORDDEFFXXX",
        "balance": Decimal("3100000.00"),
        "description": "Our EUR account held with the German correspondent.",
    },
    {
        "account_number": "NOSTRO-GBP-THAMGB2L",
        "name": "Nostro GBP at Thames Commercial Bank",
        "currency": "GBP",
        "correspondent_bic": "THAMGB2LXXX",
        "balance": Decimal("1850000.00"),
        "description": "Our GBP account held with the UK correspondent.",
    },
    {
        "account_number": "NOSTRO-INR-GANGINBB",
        "name": "Nostro INR at Ganga National Bank",
        "currency": "INR",
        "correspondent_bic": "GANGINBBXXX",
        "balance": Decimal("185000000.00"),
        "description": "Our INR account held with the Indian correspondent.",
    },
    {
        "account_number": "NOSTRO-JPY-MARIJPJT",
        "name": "Nostro JPY at Marina Bank Tokyo",
        "currency": "JPY",
        "correspondent_bic": "MARIJPJTXXX",
        "balance": Decimal("240000000"),
        "description": "Our JPY account held with the Japanese correspondent.",
    },
    {
        "account_number": "NOSTRO-SGD-RAFFSGSG",
        "name": "Nostro SGD at Raffles Merchant Bank",
        "currency": "SGD",
        "correspondent_bic": "RAFFSGSGXXX",
        "balance": Decimal("920000.00"),
        "description": "Our SGD account held with the Singapore correspondent.",
    },
    {
        "account_number": "NOSTRO-CHF-ALPNCHZZ",
        "name": "Nostro CHF at Alpine Kantonalbank",
        "currency": "CHF",
        "correspondent_bic": "ALPNCHZZXXX",
        "balance": Decimal("2600000.00"),
        "description": "CHF correspondent position used when the domestic rail is not available.",
    },
)

VOSTRO_ACCOUNTS: tuple[dict, ...] = (
    {
        "account_number": "VOSTRO-CHF-NORDDEFF",
        "name": "Vostro CHF for Norddeutsche Handelsbank",
        "currency": "CHF",
        "correspondent_bic": "NORDDEFFXXX",
        "balance": Decimal("780000.00"),
        "description": (
            "The German correspondent's CHF account on our books. It is their nostro and our "
            "vostro: the same account seen from the other side."
        ),
    },
    {
        "account_number": "VOSTRO-CHF-THAMGB2L",
        "name": "Vostro CHF for Thames Commercial Bank",
        "currency": "CHF",
        "correspondent_bic": "THAMGB2LXXX",
        "balance": Decimal("430000.00"),
        "description": "The UK correspondent's CHF account on our books.",
    },
)

SETTLEMENT_ACCOUNTS: tuple[dict, ...] = (
    {
        "account_number": "SETTLE-CHF-CENTRAL",
        "name": "Central bank settlement account CHF",
        "currency": "CHF",
        "balance": Decimal("12500000.00"),
        "description": "Settlement account used by the domestic instant rail.",
    },
    {
        "account_number": "SETTLE-EUR-CSM",
        "name": "CSM settlement position EUR",
        "currency": "EUR",
        "balance": Decimal("8400000.00"),
        "description": "Pre-funded position at the simulated SEPA instant clearing mechanism.",
    },
    {
        "account_number": "SETTLE-USD-GENERIC",
        "name": "Generic settlement account USD",
        "currency": "USD",
        "balance": Decimal("3200000.00"),
        "description": "Settlement account for the generic ISO 20022 rail in USD.",
    },
    {
        "account_number": "SETTLE-GBP-GENERIC",
        "name": "Generic settlement account GBP",
        "currency": "GBP",
        "balance": Decimal("1400000.00"),
        "description": "Settlement account for the generic ISO 20022 rail in GBP.",
    },
    {
        "account_number": "SETTLE-INR-GENERIC",
        "name": "Generic settlement account INR",
        "currency": "INR",
        "balance": Decimal("95000000.00"),
        "description": "Settlement account for the generic ISO 20022 rail in INR.",
    },
)

SUSPENSE_ACCOUNTS: tuple[dict, ...] = (
    {
        "account_number": "SUSPENSE-CHF-001",
        "name": "Payments suspense CHF",
        "currency": "CHF",
        "balance": Decimal("0.00"),
        "description": "Holding account for unidentified or unapplied CHF movements.",
    },
    {
        "account_number": "SUSPENSE-EUR-001",
        "name": "Payments suspense EUR",
        "currency": "EUR",
        "balance": Decimal("0.00"),
        "description": "Holding account for unidentified or unapplied EUR movements.",
    },
)


def seed_reference_data(session: Session) -> dict[str, int]:
    created = {"banks": 0, "accounts": 0}
    bank_by_bic: dict[str, Bank] = {
        b.bic: b for b in session.execute(select(Bank)).scalars()
    }
    for spec in BANKS:
        if spec["bic"] in bank_by_bic:
            continue
        row = Bank(
            bic=spec["bic"],
            name=spec["name"],
            country=spec["country"],
            city=spec.get("city", ""),
            national_clearing_code=spec.get("national_clearing_code"),
            is_direct_participant=spec.get("is_direct_participant", True),
            supported_schemes=list(spec.get("supported_schemes", [])),
            is_internal=spec.get("is_internal", False),
            notes=spec.get("notes", ""),
        )
        session.add(row)
        bank_by_bic[row.bic] = row
        created["banks"] += 1
    session.flush()

    own_bank = bank_by_bic["SIMUCHZZXXX"]
    # `select(Account.account_number)` yields the column values, not ORM rows.
    existing_accounts: set[str] = set(session.execute(select(Account.account_number)).scalars())

    def add_account(**kwargs) -> None:  # noqa: ANN003
        if kwargs["account_number"] in existing_accounts:
            return
        session.add(Account(**kwargs))
        existing_accounts.add(kwargs["account_number"])
        created["accounts"] += 1

    for spec in CUSTOMER_ACCOUNTS:
        add_account(
            account_number=spec["account_number"],
            iban=_ch_iban(spec["bban"]),
            name=spec["name"],
            account_type=AccountType.CUSTOMER.value,
            currency=spec["currency"],
            bank_id=own_bank.id,
            balance=spec["balance"],
            opening_balance=spec["balance"],
            overdraft_limit=spec.get("overdraft_limit", Decimal("0")),
            description=spec["description"],
        )

    for spec in NOSTRO_ACCOUNTS:
        correspondent = bank_by_bic.get(spec["correspondent_bic"])
        add_account(
            account_number=spec["account_number"],
            iban=None,
            name=spec["name"],
            account_type=AccountType.NOSTRO.value,
            currency=spec["currency"],
            bank_id=own_bank.id,
            correspondent_bank_id=correspondent.id if correspondent else None,
            balance=spec["balance"],
            opening_balance=spec["balance"],
            description=spec["description"],
        )

    for spec in VOSTRO_ACCOUNTS:
        correspondent = bank_by_bic.get(spec["correspondent_bic"])
        add_account(
            account_number=spec["account_number"],
            iban=None,
            name=spec["name"],
            account_type=AccountType.VOSTRO.value,
            currency=spec["currency"],
            bank_id=own_bank.id,
            correspondent_bank_id=correspondent.id if correspondent else None,
            balance=spec["balance"],
            opening_balance=spec["balance"],
            description=spec["description"],
        )

    for spec in SETTLEMENT_ACCOUNTS:
        add_account(
            account_number=spec["account_number"],
            iban=None,
            name=spec["name"],
            account_type=AccountType.SETTLEMENT.value,
            currency=spec["currency"],
            bank_id=own_bank.id,
            balance=spec["balance"],
            opening_balance=spec["balance"],
            description=spec["description"],
        )

    for spec in SUSPENSE_ACCOUNTS:
        add_account(
            account_number=spec["account_number"],
            iban=None,
            name=spec["name"],
            account_type=AccountType.SUSPENSE.value,
            currency=spec["currency"],
            bank_id=own_bank.id,
            balance=spec["balance"],
            opening_balance=spec["balance"],
            description=spec["description"],
        )

    session.flush()
    logger.info("reference data seeded", extra=created)
    return created


def counterparty_iban(country: str, bban_seed: str) -> str:
    """Build a structurally valid foreign IBAN for fictional counterparties."""
    return compute_iban(country, bban_seed)
