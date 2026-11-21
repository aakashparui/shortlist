"""Scenario library, test-case generator and BA workbench."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain.enums import ProcessingMode
from app.engines.failure_injection import CATALOGUE, CATALOGUE_BY_CODE
from app.engines.validation.rules import RULES_BY_ID
from app.services.ba_service import BaService
from app.services.search_service import SearchService
from app.services.testcase_service import TestCaseService as CaseGenerator


class TestScenarioLibrary:
    def test_twenty_scenarios_are_seeded(self, scenarios) -> None:
        rows = scenarios.list_scenarios()
        assert len(rows) == 20
        assert [r.code for r in rows] == [f"SC-{i:02d}" for i in range(1, 21)]

    def test_every_scenario_declares_its_expectations(self, scenarios) -> None:
        for scenario in scenarios.list_scenarios():
            assert scenario.preconditions, scenario.code
            assert scenario.input_data, scenario.code
            assert scenario.execution_steps, scenario.code
            assert scenario.expected_status, scenario.code
            assert scenario.expected_result, scenario.code
            assert scenario.failure_conditions, scenario.code
            assert scenario.business_context, scenario.code

    def test_every_scenario_failure_code_exists(self, scenarios) -> None:
        for scenario in scenarios.list_scenarios():
            for code in scenario.failure_codes or []:
                assert code in CATALOGUE_BY_CODE, f"{scenario.code} references unknown {code}"

    @pytest.mark.parametrize("code", [f"SC-{i:02d}" for i in range(1, 21)])
    def test_scenario_executes_as_specified(self, scenarios, code: str) -> None:
        scenario = scenarios.require(code)
        result = scenarios.run(scenario, mode=ProcessingMode.IMMEDIATE)
        failed = [a for a in result.assertions if not a.passed]
        assert not failed, [
            f"{a.name}: expected {a.expected!r}, got {a.actual!r}" for a in failed
        ]
        assert result.execution.outcome == "PASSED"

    def test_execution_is_recorded_with_assertions(self, scenarios) -> None:
        scenario = scenarios.require("SC-01")
        result = scenarios.run(scenario, mode=ProcessingMode.IMMEDIATE)
        assert result.execution.reference.startswith("RUN-")
        assert result.execution.finished_at is not None
        assert result.execution.actual_status == "COMPLETED"
        assert result.execution.assertions
        assert scenarios.executions()

    def test_demo_highlights_exist(self, scenarios) -> None:
        highlights = [s for s in scenarios.list_scenarios() if s.is_demo_highlight]
        assert len(highlights) >= 5


class TestFailureCatalogue:
    def test_every_definition_is_complete(self) -> None:
        for definition in CATALOGUE:
            assert definition.description
            assert definition.mechanism
            assert definition.expected_outcome
            assert definition.expected_status

    def test_referenced_rule_ids_exist(self) -> None:
        compliance = {"COMP-EMB-001", "COMP-SANC-001", "COMP-SANC-002", "COMP-AML-001", "COMP-PEP-001"}
        for definition in CATALOGUE:
            for rule_id in definition.affected_rule_ids:
                assert rule_id in RULES_BY_ID or rule_id in compliance, rule_id

    def test_catalogue_covers_every_category(self) -> None:
        from app.domain.enums import FailureCategory

        covered = {d.category for d in CATALOGUE}
        assert covered == set(FailureCategory)

    def test_injection_is_recorded_as_consumed_with_an_explanation(self, payments) -> None:
        from app.api.schemas import PaymentCreate
        from app.seed.scenarios import sic

        payment = payments.create(
            PaymentCreate.model_validate(
                {
                    **sic("1000.00"),
                    "processingMode": "IMMEDIATE",
                    "failureInjections": [{"code": "UNSUPPORTED_CURRENCY", "parameters": {}}],
                }
            )
        )
        payments.execute(payment, mode=ProcessingMode.IMMEDIATE)
        payments.session.refresh(payment)
        injection = payment.failure_injections[0]
        assert injection.consumed
        assert injection.effect_summary
        assert payment.currency != "CHF"


class TestTestCaseGenerator:
    def test_amount_rule_produces_real_boundary_values(self, db_session) -> None:
        service = CaseGenerator(db_session)
        cases = service.generate_for_rule("SIC-AMOUNT-001", "SIC_INSTANT")
        amounts = {c.input_data["amount"] for c in cases if "amount" in c.input_data}
        assert "19999.99" in amounts
        assert "20000.00" in amounts
        assert "20000.01" in amounts
        assert "0" in amounts
        assert "-100.00" in amounts

    def test_all_test_types_are_generated(self, db_session) -> None:
        service = CaseGenerator(db_session)
        cases = service.generate_for_rule("SIC-AMOUNT-001", "SIC_INSTANT")
        types = {c.test_type for c in cases}
        assert {"POSITIVE", "NEGATIVE", "BOUNDARY", "EXCEPTION", "INTEGRATION", "REGRESSION", "RECONCILIATION"} <= types

    def test_generated_cases_carry_full_specifications(self, db_session) -> None:
        service = CaseGenerator(db_session)
        for case in service.generate_for_rule("VAL-IBAN-002", "SIC_INSTANT"):
            assert case.title
            assert case.preconditions
            assert case.steps
            assert case.expected_result

    def test_generated_cases_actually_execute_and_pass(self, db_session) -> None:
        service = CaseGenerator(db_session)
        cases = service.generate_for_rule("SIC-AMOUNT-001", "SIC_INSTANT")
        rows = service.persist(cases, suite="unit-sic-amount", rule_id="SIC-AMOUNT-001", scheme="SIC_INSTANT")
        summary = service.run_suite(rows)
        failures = [r for r in summary["results"] if r["outcome"] != "PASSED"]
        assert not failures, failures
        assert summary["passed"] == summary["total"]

    def test_regression_case_reports_the_rule_as_skipped(self, db_session) -> None:
        service = CaseGenerator(db_session)
        cases = service.generate_for_rule("SIC-AMOUNT-001", "SIC_INSTANT")
        rows = service.persist(cases, suite="unit-regression", rule_id="SIC-AMOUNT-001", scheme="SIC_INSTANT")
        regression = next(r for r in rows if r.test_type == "REGRESSION")
        outcome = service.run_case(regression)
        assert outcome.passed
        checks = outcome.detail["checks"]
        assert any(c["actual"] == "SKIPPED" for c in checks)

    def test_regression_case_restores_the_rule(self, db_session) -> None:
        from app.db.models import BusinessRule

        service = CaseGenerator(db_session)
        cases = service.generate_for_rule("SIC-AMOUNT-001", "SIC_INSTANT")
        rows = service.persist(cases, suite="unit-restore", rule_id="SIC-AMOUNT-001", scheme="SIC_INSTANT")
        regression = next(r for r in rows if r.test_type == "REGRESSION")
        service.run_case(regression)
        rule = db_session.query(BusinessRule).filter_by(rule_id="SIC-AMOUNT-001").one()
        assert rule.enabled is True

    def test_unknown_rule_raises(self, db_session) -> None:
        with pytest.raises(LookupError):
            CaseGenerator(db_session).generate_for_rule("NOPE-001", "SIC_INSTANT")

    def test_persisting_a_suite_replaces_the_previous_run(self, db_session) -> None:
        service = CaseGenerator(db_session)
        cases = service.generate_for_rule("SIC-AMOUNT-001", "SIC_INSTANT")
        service.persist(cases, suite="dup", rule_id="SIC-AMOUNT-001", scheme="SIC_INSTANT")
        service.persist(cases, suite="dup", rule_id="SIC-AMOUNT-001", scheme="SIC_INSTANT")
        assert len(service.list_cases(suite="dup")) == len(cases)


class TestBaWorkbench:
    def test_package_contains_the_full_artefact_chain(self, db_session) -> None:
        package = BaService(db_session).build_package(scheme_code="SIC_INSTANT").data
        for key in (
            "businessRequirement",
            "functionalRequirements",
            "businessRules",
            "processFlow",
            "acceptanceCriteria",
            "exceptionScenarios",
            "testScenarios",
            "traceabilityMatrix",
            "messageCatalogue",
        ):
            assert package[key], key

    def test_acceptance_criteria_use_given_when_then(self, db_session) -> None:
        package = BaService(db_session).build_package(scheme_code="SIC_INSTANT").data
        for criterion in package["acceptanceCriteria"]:
            assert criterion["given"]
            assert criterion["when"]
            assert criterion["then"]

    def test_acceptance_criteria_reference_the_real_scheme_limit(self, db_session) -> None:
        package = BaService(db_session).build_package(scheme_code="SIC_INSTANT").data
        text = " ".join(c["given"] + c["then"] for c in package["acceptanceCriteria"])
        assert "20000.00" in text

    def test_traceability_links_requirements_to_rules_and_tests(self, db_session) -> None:
        package = BaService(db_session).build_package(scheme_code="SIC_INSTANT").data
        rows = package["traceabilityMatrix"]
        assert rows
        for row in rows:
            assert row["businessRequirementId"]
            assert row["functionalRequirementId"]
            assert row["stage"]
            assert row["testScenarioIds"]

    def test_cross_border_package_adds_uetr_and_mt_requirements(self, db_session) -> None:
        package = BaService(db_session).build_package(scheme_code="SWIFT_CROSS_BORDER").data
        titles = " ".join(fr["title"] for fr in package["functionalRequirements"])
        assert "UETR" in titles
        assert "MT to MX" in titles

    def test_process_flow_covers_all_thirteen_stages(self, db_session) -> None:
        package = BaService(db_session).build_package(scheme_code="SEPA_INSTANT").data
        assert len(package["processFlow"]) == 13
        for step in package["processFlow"]:
            assert step["actor"]
            assert step["output"]
            assert step["businessLabel"]
            assert step["technicalLabel"]

    def test_exception_scenarios_state_customer_impact(self, db_session) -> None:
        package = BaService(db_session).build_package(scheme_code="SIC_INSTANT").data
        for row in package["exceptionScenarios"]:
            assert row["customerImpact"]
            assert row["operationalResponse"]

    def test_scenario_specific_package_adds_its_criterion(self, db_session) -> None:
        package = BaService(db_session).build_package(
            scheme_code="SIC_INSTANT", scenario_code="SC-06"
        ).data
        assert package["scenarioCode"] == "SC-06"
        assert any("SC-06" in c["when"] for c in package["acceptanceCriteria"])

    def test_unknown_scheme_raises(self, db_session) -> None:
        with pytest.raises(KeyError):
            BaService(db_session).build_package(scheme_code="NOPE")


class TestSearch:
    def test_payment_is_found_by_reference(self, payments, db_session) -> None:
        from app.api.schemas import PaymentCreate
        from app.seed.scenarios import sic

        payment = payments.create(PaymentCreate.model_validate(sic("1000.00")))
        hits = SearchService(db_session).search(payment.reference)
        assert hits
        assert hits[0]["kind"] == "PAYMENT"
        assert payment.reference in hits[0]["title"]

    def test_payment_is_found_by_end_to_end_id(self, payments, db_session) -> None:
        from app.api.schemas import PaymentCreate
        from app.seed.scenarios import sic

        payment = payments.create(PaymentCreate.model_validate(sic("1000.00")))
        hits = SearchService(db_session).search(payment.end_to_end_id)
        assert any(h["kind"] == "PAYMENT" for h in hits)

    def test_payment_is_found_by_creditor_name(self, payments, db_session) -> None:
        from app.api.schemas import PaymentCreate
        from app.seed.scenarios import sic

        payments.create(PaymentCreate.model_validate(sic("1000.00")))
        hits = SearchService(db_session).search("Zentrum")
        assert any(h["kind"] == "PAYMENT" for h in hits)

    def test_uetr_is_recognised(self, payments, db_session) -> None:
        from app.api.schemas import PaymentCreate
        from app.seed.scenarios import swift

        payment = payments.create(PaymentCreate.model_validate(swift("1000.00")))
        hits = SearchService(db_session).search(f"UETR {payment.uetr}")
        assert any(h["kind"] == "PAYMENT" for h in hits)

    def test_intent_queries_route_to_views(self, db_session) -> None:
        service = SearchService(db_session)
        for query, expected_route in (
            ("find failed payments", "/payments?failuresOnly=true"),
            ("show unmatched reconciliations", "/reconciliation?status=breaks"),
            ("open investigations", "/investigations"),
        ):
            hits = service.search(query)
            assert any(h["route"] == expected_route for h in hits), query

    def test_message_type_query(self, db_session) -> None:
        hits = SearchService(db_session).search("open pacs.008")
        assert any(h["kind"] == "MESSAGE_TYPE" for h in hits)

    def test_rule_query(self, db_session) -> None:
        hits = SearchService(db_session).search("SIC-AMOUNT-001")
        assert any(h["kind"] == "RULE" for h in hits)

    def test_scenario_query(self, db_session) -> None:
        hits = SearchService(db_session).search("SC-06")
        assert any(h["kind"] == "SCENARIO" for h in hits)

    def test_account_query(self, db_session) -> None:
        hits = SearchService(db_session).search("NOSTRO-USD-HUDSUS33")
        assert any(h["kind"] == "ACCOUNT" for h in hits)

    def test_clearing_reference_query(self, payments, db_session) -> None:
        from app.api.schemas import PaymentCreate
        from app.seed.scenarios import sic

        payment = payments.create(
            PaymentCreate.model_validate({**sic("1000.00"), "processingMode": "IMMEDIATE"})
        )
        payments.execute(payment, mode=ProcessingMode.IMMEDIATE)
        clearing = payments.clearing.latest(payment.id)
        hits = SearchService(db_session).search(clearing.clearing_reference)
        assert any(h["kind"] == "CLEARING" for h in hits)

    def test_empty_query_returns_nothing(self, db_session) -> None:
        assert SearchService(db_session).search("   ") == []

    def test_amount_query_finds_a_payment(self, payments, db_session) -> None:
        from app.api.schemas import PaymentCreate
        from app.seed.scenarios import sic

        payments.create(PaymentCreate.model_validate(sic("4242.00")))
        hits = SearchService(db_session).search("4242.00")
        assert any(h["kind"] == "PAYMENT" for h in hits)


class TestSeededReferenceData:
    def test_accounts_cover_every_account_type(self, db_session) -> None:
        from app.db.models import Account
        from app.domain.enums import AccountType

        types = {a.account_type for a in db_session.query(Account).all()}
        assert types == {t.value for t in AccountType} - {AccountType.FEE.value}

    def test_customer_ibans_are_valid(self, db_session) -> None:
        from app.db.models import Account
        from app.domain.identifiers_bank import is_valid_iban

        for account in db_session.query(Account).filter(Account.iban.isnot(None)).all():
            assert is_valid_iban(account.iban), account.account_number

    def test_bank_bics_are_structurally_valid(self, db_session) -> None:
        from app.db.models import Bank
        from app.domain.identifiers_bank import is_valid_bic

        for bank in db_session.query(Bank).all():
            assert is_valid_bic(bank.bic), bank.bic

    def test_nostro_accounts_name_a_correspondent(self, db_session) -> None:
        from app.db.models import Account

        rows = db_session.query(Account).filter(Account.account_type == "NOSTRO").all()
        assert rows
        for account in rows:
            assert account.correspondent_bank_id is not None

    def test_rule_book_is_synchronised(self, db_session) -> None:
        from app.db.models import BusinessRule

        rows = db_session.query(BusinessRule).all()
        assert len(rows) >= len(RULES_BY_ID)
        for row in rows:
            assert row.description
            assert row.failure_behaviour

    def test_settlement_accounts_are_funded(self, db_session) -> None:
        from app.db.models import Account

        rows = db_session.query(Account).filter(Account.account_type == "SETTLEMENT").all()
        assert rows
        for account in rows:
            assert account.balance > Decimal("0")
