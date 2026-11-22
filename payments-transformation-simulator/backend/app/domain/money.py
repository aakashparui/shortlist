"""Monetary helpers.

Amounts are stored as Decimal with explicit scale per currency. Floats are never
used for money anywhere in the engine.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CURRENCY_SCALE: dict[str, int] = {
    "CHF": 2,
    "EUR": 2,
    "GBP": 2,
    "USD": 2,
    "INR": 2,
    "JPY": 0,
    "SEK": 2,
    "NOK": 2,
    "AUD": 2,
    "CAD": 2,
    "SGD": 2,
}

SUPPORTED_CURRENCIES: tuple[str, ...] = tuple(sorted(CURRENCY_SCALE))

CURRENCY_NAMES: dict[str, str] = {
    "CHF": "Swiss Franc",
    "EUR": "Euro",
    "GBP": "Pound Sterling",
    "USD": "US Dollar",
    "INR": "Indian Rupee",
    "JPY": "Japanese Yen",
    "SEK": "Swedish Krona",
    "NOK": "Norwegian Krone",
    "AUD": "Australian Dollar",
    "CAD": "Canadian Dollar",
    "SGD": "Singapore Dollar",
}

# Indicative, fictional reference rates used only by the settlement engine when a
# cross-currency settlement is simulated. SIMULATION BEHAVIOUR: real banks source
# rates from a treasury/FX system.
REFERENCE_RATES_TO_CHF: dict[str, Decimal] = {
    "CHF": Decimal("1.0000"),
    "EUR": Decimal("0.9450"),
    "GBP": Decimal("1.1200"),
    "USD": Decimal("0.8900"),
    "INR": Decimal("0.0106"),
    "JPY": Decimal("0.0059"),
    "SEK": Decimal("0.0840"),
    "NOK": Decimal("0.0810"),
    "AUD": Decimal("0.5900"),
    "CAD": Decimal("0.6500"),
    "SGD": Decimal("0.6700"),
}


def scale_for(currency: str) -> int:
    return CURRENCY_SCALE.get((currency or "").upper(), 2)


def is_supported_currency(currency: str) -> bool:
    return (currency or "").upper() in CURRENCY_SCALE


def to_decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:  # pragma: no cover - guard
        raise ValueError(f"Not a valid amount: {value!r}") from exc


def quantize(amount: Decimal | str | float | int, currency: str) -> Decimal:
    exp = Decimal(1).scaleb(-scale_for(currency))
    return to_decimal(amount).quantize(exp, rounding=ROUND_HALF_UP)


def format_amount(amount: Decimal | str | float | int, currency: str) -> str:
    q = quantize(amount, currency)
    digits = scale_for(currency)
    return f"{q:,.{digits}f} {currency.upper()}"


def convert(amount: Decimal, from_currency: str, to_currency: str) -> Decimal:
    """Indicative FX conversion for simulated cross-currency settlement."""
    src = from_currency.upper()
    dst = to_currency.upper()
    if src == dst:
        return quantize(amount, dst)
    rate_src = REFERENCE_RATES_TO_CHF.get(src)
    rate_dst = REFERENCE_RATES_TO_CHF.get(dst)
    if rate_src is None or rate_dst is None:
        raise ValueError(f"No indicative rate for {src}->{dst}")
    return quantize(to_decimal(amount) * rate_src / rate_dst, dst)


def has_valid_scale(amount: Decimal, currency: str) -> bool:
    exponent = amount.normalize().as_tuple().exponent
    if not isinstance(exponent, int):
        return False
    return -exponent <= scale_for(currency)
