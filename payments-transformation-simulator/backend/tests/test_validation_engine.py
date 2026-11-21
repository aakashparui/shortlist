"""Validation engine and rule book."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from app.api.schemas import PaymentCreate
from app.core.identifiers import utcnow
from app.db.models import BusinessRule
from app.domain.enums import StageKey, ValidationStatus
from app.engines.validation.engine import ValidationEngine
from app.schemes.registry import get_scheme
from app.seed.scenarios import sic
from tests.conftest import sic_payload


def _create(payments, **overrides):  # noqa: ANN001, ANN003
    return payments.create(PaymentCreate.model_validate(sic_payload(**overrides)))


class TestRuleOutcomes:
    def test_valid_payment_passes_every_stage(self, payments, db_session) -> None:
        payment = _create(payments)
        engine = ValidationEngine(db_session)
        scheme = get_scheme(payment.scheme)
        for stage in (StageKey.PRE_VALIDATION, StageKey.BUSINESS_VALIDATION):
            run = engine.run(payment, scheme, stage)
            assert run.passed, [f.message for f in run.failures]
            assert run.counts()["executed"] > 0

    def test_invalid_creditor_iban_fails_with_ac01(self, payments, db_session) -> None:
        payment = _create(payments)
        original = payment.creditor.iban
        payment.creditor.iban = original[:-1] + ("1" if original[-1] == "0" else "0")
        db_session.flush()
        run = ValidationEngine(db_session).run(
            payment, get_scheme(payment.scheme), StageKey.PRE_VALIDATION
        )
        failure = next(f for f in run.failures if f.rule_id == "VAL-IBAN-002")
        assert failure.iso_reason_code == "AC01"
        assert "mod-97" in failure.message

    def test_amount_above_scheme_ceiling_fails_with_am04(self, payments, db_session) -> None:
        payment = _create(payments, amount="25000.00")
        run = ValidationEngine(db_session).run(
            payment, get_scheme(payment.scheme), StageKey.BUSINESS_VALIDATION
        )
        failures = {f.rule_id: f for f in run.failures}
        assert "SIC-AMOUNT-001" in failures or "VAL-AMOUNT-003" in failures
        failure = failures.get("SIC-AMOUNT-001") or failures["VAL-AMOUNT-003"]
        assert failure.iso_reason_code == "AM04"
        assert "20000.00" in (failure.expected_value or "")

    @pytest.mark.parametrize("amount", ["0", "-10.00"])
    def test_non_positive_amount_is_rejected(self, payments, db_session, amount: str) -> None:
        payment = _create(payments, amount=amount)
        run = ValidationEngine(db_session).run(
            payment, get_scheme(payment.scheme), StageKey.PRE_VALIDATION
        )
        assert "VAL-AMOUNT-001" in {f.rule_id for f in run.failures}

    def test_excess_decimal_precision_is_rejected(self, payments, db_session) -> None:
        """The create path quantizes to the currency scale, so this rule guards
        amounts that reach the engine from elsewhere (an import or an injection)."""
        payment = _create(payments)
        payment.amount = Decimal("10.001")
        db_session.flush()
        run = ValidationEngine(db_session).run(
            payment, get_scheme(payment.scheme), StageKey.PRE_VALIDATION
        )
        failure = next(f for f in run.failures if f.rule_id == "VAL-AMOUNT-002")
        assert failure.iso_reason_code == "AM11"

    def test_create_quantizes_to_currency_scale(self, payments) -> None:
        payment = _create(payments, amount="10.004")
        assert payment.amount == Decimal("10.00")

    def test_boundary_amount_at_ceiling_passes(self, payments, db_session) -> None:
        payment = _create(payments, amount="20000.00")
        run = ValidationEngine(db_session).run(
            payment, get_scheme(payment.scheme), StageKey.BUSINESS_VALIDATION
        )
        amount_failures = [f for f in run.failures if f.field == "amount"]
        assert not amount_failures, [f.message for f in amount_failures]

    def test_one_cent_above_ceiling_fails(self, payments, db_session) -> None:
        payment = _create(payments, amount="20000.01")
        run = ValidationEngine(db_session).run(
            payment, get_scheme(payment.scheme), StageKey.BUSINESS_VALIDATION
        )
        assert [f for f in run.failures if f.field == "amount"]

    def test_unsupported_currency_for_scheme(self, payments, db_session) -> None:
        payment = _create(payments, currency="USD")
        run = ValidationEngine(db_session).run(
            payment, get_scheme(payment.scheme), StageKey.BUSINESS_VALIDATION
        )
        assert "SIC-CCY-001" in {f.rule_id for f in run.failures}

    def test_missing_creditor_name_fails_structure_rule(self, payments, db_session) -> None:
        payment = _create(payments)
        payment.creditor.name = ""
        db_session.flush()
        run = ValidationEngine(db_session).run(
            payment, get_scheme(payment.scheme), StageKey.PRE_VALIDATION
        )
        failed = {f.rule_id for f in run.failures}
        assert "VAL-STRUCT-001" in failed
        assert "VAL-CDTR-001" in failed

    def test_remittance_over_scheme_limit_fails(self, payments, db_session) -> None:
        payment = _create(payments, remittanceInformation="X" * 200)
        run = ValidationEngine(db_session).run(
            payment, get_scheme(payment.scheme), StageKey.BUSINESS_VALIDATION
        )
        assert "VAL-RMT-001" in {f.rule_id for f in run.failures}

    def test_past_execution_date_fails(self, payments, db_session) -> None:
        payment = _create(payments)
        payment.requested_execution_date = (utcnow() - timedelta(days=2)).date()
        db_session.flush()
        run = ValidationEngine(db_session).run(
            payment, get_scheme(payment.scheme), StageKey.BUSINESS_VALIDATION
        )
        failure = next(f for f in run.failures if f.rule_id == "VAL-DATE-001")
        assert failure.iso_reason_code == "DT01"

    def test_instant_scheme_rejects_future_dating(self, payments, db_session) -> None:
        payment = _create(payments)
        payment.requested_execution_date = (utcnow() + timedelta(days=5)).date()
        db_session.flush()
        run = ValidationEngine(db_session).run(
            payment, get_scheme(payment.scheme), StageKey.BUSINESS_VALIDATION
        )
        assert "VAL-DATE-001" in {f.rule_id for f in run.failures}

    def test_insufficient_funds_fails(self, payments, db_session) -> None:
        payment = _create(payments)
        account = payment.debtor_account
        assert account is not None
        payment.amount = (account.balance or Decimal("0")) + (
            account.overdraft_limit or Decimal("0")
        ) + Decimal("1000")
        db_session.flush()
        run = ValidationEngine(db_session).run(
            payment, get_scheme(payment.scheme), StageKey.BUSINESS_VALIDATION
        )
        assert "VAL-ACCT-002" in {f.rule_id for f in run.failures}

    def test_duplicate_end_to_end_id_is_detected(self, payments, db_session) -> None:
        first = _create(payments)
        second = _create(payments)
        second.end_to_end_id = first.end_to_end_id
        db_session.flush()
        run = ValidationEngine(db_session).run(
            second, get_scheme(second.scheme), StageKey.BUSINESS_VALIDATION
        )
        failure = next(f for f in run.failures if f.rule_id == "VAL-DUP-001")
        assert first.reference in failure.message
        assert failure.iso_reason_code == "AM05"

    def test_cross_border_requires_bic_and_address(self, payments, db_session) -> None:
        from app.seed.scenarios import swift

        payload = swift("1000.00")
        payload["creditor"]["bic"] = None
        payload["creditor"]["addressLines"] = []
        payload["creditor"]["town"] = ""
        payment = payments.create(PaymentCreate.model_validate(payload))
        run = ValidationEngine(db_session).run(
            payment, get_scheme(payment.scheme), StageKey.BUSINESS_VALIDATION
        )
        failed = {f.rule_id for f in run.failures}
        assert "SWIFT-BIC-001" in failed
        assert "SWIFT-ADDR-001" in failed

    def test_cross_border_uetr_is_generated_and_valid(self, payments, db_session) -> None:
        from app.seed.scenarios import swift

        payment = payments.create(PaymentCreate.model_validate(swift("1000.00")))
        assert payment.uetr
        run = ValidationEngine(db_session).run(
            payment, get_scheme(payment.scheme), StageKey.PRE_VALIDATION
        )
        assert "SWIFT-UETR-001" not in {f.rule_id for f in run.failures}

    def test_sepa_outside_area_fails(self, payments, db_session) -> None:
        from app.seed.scenarios import sepa

        payload = sepa("1000.00")
        payload["creditor"]["country"] = "US"
        payment = payments.create(PaymentCreate.model_validate(payload))
        run = ValidationEngine(db_session).run(
            payment, get_scheme(payment.scheme), StageKey.BUSINESS_VALIDATION
        )
        assert "SEPA-COUNTRY-001" in {f.rule_id for f in run.failures}

    def test_domestic_scheme_rejects_foreign_creditor(self, payments, db_session) -> None:
        payload = sic("1000.00")
        payload["creditor"]["country"] = "DE"
        payment = payments.create(PaymentCreate.model_validate(payload))
        run = ValidationEngine(db_session).run(
            payment, get_scheme(payment.scheme), StageKey.BUSINESS_VALIDATION
        )
        failure = next(f for f in run.failures if f.rule_id == "SIC-COUNTRY-001")
        assert failure.iso_reason_code == "RR04"


class TestRuleEngineBehaviour:
    def test_disabled_rule_is_skipped_not_dropped(self, payments, db_session) -> None:
        rule = db_session.query(BusinessRule).filter_by(rule_id="SIC-AMOUNT-001").one()
        rule.enabled = False
        db_session.flush()
        payment = _create(payments, amount="25000.00")
        engine = ValidationEngine(db_session)
        run = engine.run(payment, get_scheme(payment.scheme), StageKey.BUSINESS_VALIDATION)
        skipped = [r for r in run.results if r.rule_id == "SIC-AMOUNT-001"]
        assert skipped and skipped[0].status == ValidationStatus.SKIPPED.value
        assert "disabled" in skipped[0].message

    def test_results_are_persisted_with_run_ids(self, payments, db_session) -> None:
        payment = _create(payments)
        engine = ValidationEngine(db_session)
        scheme = get_scheme(payment.scheme)
        first = engine.run(payment, scheme, StageKey.PRE_VALIDATION)
        second = engine.run(payment, scheme, StageKey.PRE_VALIDATION)
        assert first.results[0].run_id == 1
        assert second.results[0].run_id == 2

    def test_a_broken_rule_does_not_kill_the_payment(self, payments, db_session, monkeypatch) -> None:
        from app.engines.validation import rules as rules_module

        original = rules_module.RULES_BY_ID["VAL-AMOUNT-001"]

        def exploding(_ctx):  # noqa: ANN001, ANN202
            raise RuntimeError("rule bug")

        broken = type(original)(
            rule_id=original.rule_id,
            name=original.name,
            description=original.description,
            category=original.category,
            severity=original.severity,
            stage=original.stage,
            evaluator=exploding,
        )
        monkeypatch.setitem(rules_module.RULES_BY_ID, "VAL-AMOUNT-001", broken)
        payment = _create(payments)
        run = ValidationEngine(db_session).run(
            payment, get_scheme(payment.scheme), StageKey.PRE_VALIDATION
        )
        failure = next(f for f in run.failures if f.rule_id == "VAL-AMOUNT-001")
        assert "RuntimeError" in failure.message

    def test_every_scheme_rule_id_resolves(self) -> None:
        from app.engines.validation.rules import RULES_BY_ID
        from app.schemes.registry import list_schemes

        for scheme in list_schemes():
            for rule_id in scheme.validation_rule_ids:
                assert rule_id in RULES_BY_ID, f"{scheme.code.value} references unknown {rule_id}"
