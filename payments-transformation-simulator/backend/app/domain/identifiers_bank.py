"""IBAN and BIC handling.

The IBAN check-digit algorithm (ISO 13616 / mod-97-10) and the BIC structure
rules (ISO 9362) implemented here are the real standards. The *bank directory*
the simulator screens against is entirely fictional.
"""

from __future__ import annotations

import re
import string

# ISO 13616 IBAN lengths per country (subset covering the simulator's demo data).
IBAN_LENGTHS: dict[str, int] = {
    "AT": 20, "BE": 16, "CH": 21, "CZ": 24, "DE": 22, "DK": 18, "EE": 20, "ES": 24,
    "FI": 18, "FR": 27, "GB": 22, "GR": 27, "HU": 28, "IE": 22, "IT": 27, "LI": 21,
    "LT": 20, "LU": 20, "LV": 21, "MT": 31, "NL": 18, "NO": 15, "PL": 28, "PT": 25,
    "RO": 24, "SE": 24, "SI": 19, "SK": 24,
}

SEPA_COUNTRIES: frozenset[str] = frozenset(
    {
        "AT", "BE", "BG", "CH", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GB",
        "GR", "HR", "HU", "IE", "IS", "IT", "LI", "LT", "LU", "LV", "MC", "MT", "NL",
        "NO", "PL", "PT", "RO", "SE", "SI", "SK", "SM",
    }
)

_BIC_RE = re.compile(r"^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$")
_IBAN_CLEAN_RE = re.compile(r"[\s-]")
_IBAN_SHAPE_RE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]+$")

_CHAR_VALUES = {
    **{str(d): str(d) for d in range(10)},
    **{c: str(10 + i) for i, c in enumerate(string.ascii_uppercase)},
}


def normalise_iban(value: str | None) -> str:
    return _IBAN_CLEAN_RE.sub("", (value or "")).upper()


def normalise_bic(value: str | None) -> str:
    return _IBAN_CLEAN_RE.sub("", (value or "")).upper()


def format_iban(value: str | None) -> str:
    iban = normalise_iban(value)
    return " ".join(iban[i : i + 4] for i in range(0, len(iban), 4))


def iban_country(value: str | None) -> str:
    return normalise_iban(value)[:2]


def iban_check_digits(value: str | None) -> str:
    return normalise_iban(value)[2:4]


def _mod97(iban: str) -> int:
    rearranged = iban[4:] + iban[:4]
    numeric = "".join(_CHAR_VALUES[ch] for ch in rearranged)
    remainder = 0
    for chunk_start in range(0, len(numeric), 9):
        remainder = int(str(remainder) + numeric[chunk_start : chunk_start + 9]) % 97
    return remainder


class IbanCheck:
    """Result of a structural + check-digit IBAN assessment."""

    __slots__ = ("iban", "valid", "reason", "country", "expected_length", "actual_length")

    def __init__(
        self,
        iban: str,
        valid: bool,
        reason: str | None,
        country: str,
        expected_length: int | None,
        actual_length: int,
    ) -> None:
        self.iban = iban
        self.valid = valid
        self.reason = reason
        self.country = country
        self.expected_length = expected_length
        self.actual_length = actual_length

    def as_dict(self) -> dict[str, object]:
        return {
            "iban": self.iban,
            "valid": self.valid,
            "reason": self.reason,
            "country": self.country,
            "expectedLength": self.expected_length,
            "actualLength": self.actual_length,
        }


def check_iban(value: str | None) -> IbanCheck:
    iban = normalise_iban(value)
    country = iban[:2]
    expected = IBAN_LENGTHS.get(country)
    if not iban:
        return IbanCheck(iban, False, "IBAN is empty", country, expected, 0)
    if not _IBAN_SHAPE_RE.match(iban):
        return IbanCheck(
            iban,
            False,
            "IBAN must start with 2 letters, 2 check digits, then alphanumerics",
            country,
            expected,
            len(iban),
        )
    if expected is None:
        return IbanCheck(
            iban, False, f"Country code '{country}' is not a recognised IBAN country", country, None, len(iban)
        )
    if len(iban) != expected:
        return IbanCheck(
            iban,
            False,
            f"IBAN length for {country} must be {expected} characters",
            country,
            expected,
            len(iban),
        )
    if _mod97(iban) != 1:
        return IbanCheck(
            iban, False, "IBAN check digits failed the ISO 13616 mod-97 test", country, expected, len(iban)
        )
    return IbanCheck(iban, True, None, country, expected, len(iban))


def is_valid_iban(value: str | None) -> bool:
    return check_iban(value).valid


def compute_iban(country: str, bban: str) -> str:
    """Build a structurally valid IBAN for fictional demo data."""
    country = country.upper()
    bban = bban.upper()
    expected = IBAN_LENGTHS.get(country)
    if expected is not None:
        bban = bban[: expected - 4].ljust(expected - 4, "0")
    temp = bban + country + "00"
    numeric = "".join(_CHAR_VALUES[ch] for ch in temp)
    remainder = 0
    for chunk_start in range(0, len(numeric), 9):
        remainder = int(str(remainder) + numeric[chunk_start : chunk_start + 9]) % 97
    check = 98 - remainder
    return f"{country}{check:02d}{bban}"


def is_valid_bic(value: str | None) -> bool:
    bic = normalise_bic(value)
    return bool(bic) and bool(_BIC_RE.match(bic)) and len(bic) in (8, 11)


def bic_country(value: str | None) -> str:
    bic = normalise_bic(value)
    return bic[4:6] if len(bic) >= 6 else ""


def bic_branch(value: str | None) -> str:
    bic = normalise_bic(value)
    return bic[8:11] if len(bic) == 11 else "XXX"


def bic_institution(value: str | None) -> str:
    return normalise_bic(value)[:4]


def is_sepa_country(country: str | None) -> bool:
    return (country or "").upper() in SEPA_COUNTRIES
