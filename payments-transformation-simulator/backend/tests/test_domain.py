"""Domain primitives: IBAN, BIC, money."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain.identifiers_bank import (
    check_iban,
    compute_iban,
    format_iban,
    is_sepa_country,
    is_valid_bic,
    is_valid_iban,
)
from app.domain.money import (
    convert,
    format_amount,
    has_valid_scale,
    is_supported_currency,
    quantize,
    scale_for,
)


class TestIban:
    def test_computed_ibans_are_valid(self) -> None:
        for country, bban in (
            ("CH", "0091000012345678"),
            ("DE", "500105170032198765"),
            ("FR", "300060000112345678901"),
            ("GB", "THAM20415538294"),
            ("NL", "AMST0123456789"),
        ):
            iban = compute_iban(country, bban)
            assert is_valid_iban(iban), f"{country} IBAN {iban} should validate"

    def test_known_valid_iban(self) -> None:
        # Published ISO 13616 example value.
        assert is_valid_iban("GB82WEST12345698765432")

    def test_check_digit_failure_is_reported(self) -> None:
        iban = compute_iban("CH", "0091000012345678")
        broken = iban[:-1] + ("0" if iban[-1] != "0" else "1")
        result = check_iban(broken)
        assert not result.valid
        assert "mod-97" in (result.reason or "")

    def test_wrong_length_is_reported(self) -> None:
        result = check_iban("CH93007601234567")
        assert not result.valid
        assert result.expected_length == 21
        assert "length" in (result.reason or "")

    def test_unknown_country_is_reported(self) -> None:
        result = check_iban("QQ93007601234567890")
        assert not result.valid
        assert "not a recognised IBAN country" in (result.reason or "")

    def test_empty_iban(self) -> None:
        assert not check_iban("").valid
        assert not check_iban(None).valid

    def test_normalisation_handles_spaces(self) -> None:
        iban = compute_iban("CH", "0091000012345678")
        spaced = format_iban(iban)
        assert " " in spaced
        assert is_valid_iban(spaced)

    def test_sepa_country_scope(self) -> None:
        assert is_sepa_country("DE")
        assert is_sepa_country("ch")
        assert not is_sepa_country("US")
        assert not is_sepa_country("")


class TestBic:
    @pytest.mark.parametrize("bic", ["SIMUCHZZXXX", "NORDDEFF", "HUDSUS33XXX", "GANGINBB"])
    def test_valid_bics(self, bic: str) -> None:
        assert is_valid_bic(bic)

    @pytest.mark.parametrize(
        "bic", ["12INVALIDBIC", "SHORT", "SIMUCHZZXX", "SIMU1HZZXXX", "", None]
    )
    def test_invalid_bics(self, bic: str | None) -> None:
        assert not is_valid_bic(bic)


class TestMoney:
    def test_scale_per_currency(self) -> None:
        assert scale_for("CHF") == 2
        assert scale_for("JPY") == 0
        assert scale_for("unknown") == 2

    def test_supported_currencies(self) -> None:
        assert is_supported_currency("chf")
        assert not is_supported_currency("XYZ")

    def test_quantize_rounds_half_up(self) -> None:
        assert quantize("10.005", "CHF") == Decimal("10.01")
        assert quantize("10.4", "JPY") == Decimal("10")

    def test_valid_scale_detection(self) -> None:
        assert has_valid_scale(Decimal("10.00"), "CHF")
        assert not has_valid_scale(Decimal("10.001"), "CHF")
        assert not has_valid_scale(Decimal("10.5"), "JPY")

    def test_format_amount(self) -> None:
        assert format_amount(Decimal("1234.5"), "CHF") == "1,234.50 CHF"
        assert format_amount(Decimal("1234"), "JPY") == "1,234 JPY"

    def test_conversion_is_symmetric_for_same_currency(self) -> None:
        assert convert(Decimal("100.00"), "CHF", "CHF") == Decimal("100.00")

    def test_conversion_between_currencies(self) -> None:
        result = convert(Decimal("100.00"), "EUR", "CHF")
        assert result == Decimal("94.50")

    def test_conversion_rejects_unknown_currency(self) -> None:
        with pytest.raises(ValueError):
            convert(Decimal("100.00"), "EUR", "XYZ")
