"""End-to-end lifecycle, state machine, clearing, settlement, accounting, reconciliation."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.api.schemas import FailureInjectionInput, PaymentCreate
from app.domain.enums import (
    AccountingStatus,
    ClearingStatus,
    EntrySide,
    PaymentStatus,
    ProcessingMode,
    ReconciliationStatus,
    SettlementStatus,
    StageKey,
    StageState,
)
from app.engines.state_machine import (
    IllegalTransitionError,
    allowed_targets,
    can_transition,
    graph,
)
from app.schemes.registry import get_scheme
from app.seed.scenarios import sepa, sic, swift


def create_and_run(payments, payload: dict, injections: list[str] | None = None):  # noqa: ANN201
    data = {**payload, "processingMode": "IMMEDIATE"}
    data["failureInjections"] = [
        FailureInjectionInput(code=code).model_dump() for code in (injections or [])
    ]
    payment = payments.create(PaymentCreate.model_validate(data))
    payments.execute(payment, mode=ProcessingMode.IMMEDIATE)
    payments.session.refresh(payment)
    return payment


def stage_of(payment, key: StageKey):  # noqa: ANN201
    return next(s for s in payment.stages if s.stage_key == key.value)


class TestHappyPath:
    def test_domestic_instant_payment_completes(self, payments) -> None:
        payment = create_and_run(payments, sic("4850.00"))
        assert payment.status == PaymentStatus.COMPLETED.value
        assert payment.completed_at is not None
        assert payment.failure_summary is None

    def test_every_stage_is_completed(self, payments) -> None:
        payment = create_and_run(payments, sic("4850.00"))
        states = {s.stage_key: s.state for s in payment.stages}
        assert len(states) == 13
        assert set(states.values()) == {StageState.COMPLETED.value}

    def test_stages_record_timing(self, payments) -> None:
        payment = create_and_run(payments, sic("1200.00"))
        for stage in payment.stages:
            assert stage.started_at is not None
            assert stage.completed_at is not None
            assert stage.duration_ms is not None and stage.duration_ms >= 0

    def test_messages_generated_in_order(self, payments) -> None:
        payment = create_and_run(payments, sic("1200.00"))
        types = [m.message_type for m in payments.messages.all_for_payment(payment.id)]
        assert types[0] == "pacs.008"
        assert "pacs.002" in types
        assert "camt.054" in types

    def test_clearing_accepted_and_latency_recorded(self, payments) -> None:
        payment = create_and_run(payments, sic("1200.00"))
        clearing = payments.clearing.latest(payment.id)
        assert clearing is not None
        assert clearing.status == ClearingStatus.ACCEPTED.value
        assert clearing.clearing_reference.startswith("SIC-")
        assert clearing.response_latency_ms is not None

    def test_settlement_is_recorded(self, payments) -> None:
        payment = create_and_run(payments, sic("1200.00"))
        settlement = payments.settlement.latest(payment.id)
        assert settlement is not None
        assert settlement.status == SettlementStatus.SETTLED.value
        assert settlement.settlement_amount == Decimal("1200.00")
        assert settlement.settlement_currency == "CHF"
        assert settlement.settlement_reference.startswith("STL-")

    def test_journal_is_balanced_double_entry(self, payments) -> None:
        payment = create_and_run(payments, sic("1200.00"))
        entries = payments.accounting.entries_for_payment(payment.id)
        assert len(entries) == 2
        debits = sum(e.amount for e in entries if e.side == EntrySide.DEBIT.value)
        credits = sum(e.amount for e in entries if e.side == EntrySide.CREDIT.value)
        assert debits == credits == Decimal("1200.00")
        assert {e.side for e in entries} == {"DEBIT", "CREDIT"}

    def test_customer_balance_is_reduced(self, payments) -> None:
        payload = sic("1200.00")
        payment = payments.create(
            PaymentCreate.model_validate({**payload, "processingMode": "IMMEDIATE"})
        )
        account = payment.debtor_account
        assert account is not None
        before = account.balance
        payments.execute(payment, mode=ProcessingMode.IMMEDIATE)
        payments.session.refresh(account)
        assert account.balance == before - Decimal("1200.00")

    def test_reconciliation_matches(self, payments) -> None:
        payment = create_and_run(payments, sic("1200.00"))
        records = payments.reconciliation.records_for_payment(payment.id)
        assert records
        assert records[-1].status == ReconciliationStatus.MATCHED.value
        assert records[-1].difference_amount == Decimal("0")
        assert len(records[-1].legs) == 4
        assert all(leg["present"] for leg in records[-1].legs)

    def test_cross_border_settles_over_nostro_with_uetr_and_mt103(self, payments) -> None:
        payment = create_and_run(payments, swift("86500.00", "USD"))
        assert payment.status == PaymentStatus.COMPLETED.value
        assert payment.uetr
        types = {m.message_type for m in payments.messages.all_for_payment(payment.id)}
        assert "MT103" in types
        settlement = payments.settlement.latest(payment.id)
        assert settlement is not None
        assert settlement.detail["accountType"] == "NOSTRO"
        credit = next(
            e
            for e in payments.accounting.entries_for_payment(payment.id)
            if e.side == EntrySide.CREDIT.value
        )
        assert credit.account_type == "NOSTRO"

    def test_sepa_payment_completes(self, payments) -> None:
        payment = create_and_run(payments, sepa("9340.00"))
        assert payment.status == PaymentStatus.COMPLETED.value
        assert payment.currency == "EUR"

    def test_correlation_id_propagates_to_every_artefact(self, payments) -> None:
        payment = create_and_run(payments, sic("1200.00"))
        correlation = payment.correlation_id
        for message in payments.messages.all_for_payment(payment.id):
            assert message.correlation_id == correlation
        for event in payments.events.for_payment(payment.id):
            assert event.correlation_id == correlation

    def test_events_are_sequenced(self, payments) -> None:
        payment = create_and_run(payments, sic("1200.00"))
        events = payments.events.for_payment(payment.id)
        sequences = [e.sequence for e in events]
        assert sequences == sorted(sequences)
        assert sequences[0] == 1
        assert len(set(sequences)) == len(sequences)


class TestValidationFailurePath:
    def test_invalid_iban_rejects_before_any_message(self, payments) -> None:
        payment = create_and_run(payments, sic("1200.00"), ["INVALID_CREDITOR_IBAN"])
        assert payment.status == PaymentStatus.REJECTED.value
        assert not payments.messages.all_for_payment(payment.id)
        assert not payments.accounting.entries_for_payment(payment.id)
        assert payments.clearing.latest(payment.id) is None

    def test_rejection_names_the_rule_and_reason(self, payments) -> None:
        payment = create_and_run(payments, sic("1200.00"), ["INVALID_CREDITOR_IBAN"])
        assert "VAL-IBAN-002" in (payment.failure_summary or "")
        stage = stage_of(payment, StageKey.PRE_VALIDATION)
        assert stage.state == StageState.REJECTED.value
        assert stage.iso_reason_code == "AC01"

    def test_downstream_stages_are_marked_skipped_not_pending(self, payments) -> None:
        payment = create_and_run(payments, sic("1200.00"), ["INVALID_CREDITOR_IBAN"])
        downstream = [
            s for s in payment.stages if s.sequence > stage_of(payment, StageKey.PRE_VALIDATION).sequence
        ]
        assert downstream
        assert {s.state for s in downstream} == {StageState.SKIPPED.value}

    def test_injection_mutates_real_data_and_records_the_change(self, payments) -> None:
        payment = create_and_run(payments, sic("1200.00"), ["INVALID_CREDITOR_IBAN"])
        injection = payment.failure_injections[0]
        assert injection.consumed
        assert "corrupted" in (injection.effect_summary or "")
        stage = stage_of(payment, StageKey.CHANNEL_INTAKE)
        assert stage.detail["injectedChanges"]
        change = stage.detail["injectedChanges"][0]
        assert change["before"] != change["after"]

    def test_amount_over_limit_is_rejected(self, payments) -> None:
        payment = create_and_run(payments, sic("1200.00"), ["AMOUNT_EXCEEDS_SCHEME_LIMIT"])
        assert payment.status == PaymentStatus.REJECTED.value
        assert payment.amount > Decimal("20000.00")

    def test_duplicate_is_rejected_against_a_real_prior_payment(self, payments) -> None:
        create_and_run(payments, sic("500.00"))
        duplicate = create_and_run(payments, sic("500.00"), ["DUPLICATE_END_TO_END_ID"])
        assert duplicate.status == PaymentStatus.REJECTED.value
        assert "VAL-DUP-001" in (duplicate.failure_summary or "")


class TestCompliance:
    def test_embargo_hit_blocks_before_dispatch(self, payments) -> None:
        payment = create_and_run(payments, swift("25000.00"), ["EMBARGO_HIT"])
        assert payment.status == PaymentStatus.INVESTIGATION_REQUIRED.value
        assert payment.previous_status == PaymentStatus.BLOCKED.value
        assert not payments.messages.all_for_payment(payment.id)

    def test_embargo_hit_opens_an_investigation_with_cause_and_action(self, payments) -> None:
        payment = create_and_run(payments, swift("25000.00"), ["EMBARGO_HIT"])
        investigations = payments.investigations.open_for_payment(payment.id)
        assert investigations
        inv = investigations[0]
        assert inv.reason == "COMPLIANCE_BLOCK"
        assert inv.probable_cause
        assert inv.recommended_action
        assert inv.expected_behaviour

    def test_sanctions_match_blocks(self, payments) -> None:
        payment = create_and_run(payments, swift("25000.00"), ["SANCTIONS_MATCH"])
        assert payment.status == PaymentStatus.INVESTIGATION_REQUIRED.value
        assert payment.creditor.name == "VOLKOV TRADING LLC"

    def test_compliance_results_are_recorded_as_validations(self, payments) -> None:
        payment = create_and_run(payments, swift("25000.00"), ["SANCTIONS_MATCH"])
        compliance = [v for v in payment.validations if v.category == "COMPLIANCE"]
        assert compliance
        failed = [v for v in compliance if v.status == "FAILED"]
        assert failed and failed[0].rule_id.startswith("COMP-")

    def test_clean_payment_records_passing_compliance_checks(self, payments) -> None:
        payment = create_and_run(payments, sic("1200.00"))
        compliance = [v for v in payment.validations if v.category == "COMPLIANCE"]
        assert compliance
        assert all(v.status == "PASSED" for v in compliance)


class TestClearingBehaviour:
    def test_business_rejection_moves_to_clearing_rejected(self, payments) -> None:
        payment = create_and_run(payments, sic("3300.00"), ["CLEARING_REJECT_BUSINESS"])
        assert payment.status == PaymentStatus.CLEARING_REJECTED.value
        clearing = payments.clearing.latest(payment.id)
        assert clearing.status == ClearingStatus.REJECTED.value
        assert clearing.status_reason_code == "AC01"

    def test_rejection_produces_a_real_negative_pacs002(self, payments) -> None:
        payment = create_and_run(payments, sic("3300.00"), ["CLEARING_REJECT_BUSINESS"])
        pacs002 = next(
            m for m in payments.messages.all_for_payment(payment.id) if m.message_type == "pacs.002"
        )
        assert pacs002.reason_code == "AC01"
        assert "RJCT" in pacs002.xml_payload
        assert pacs002.business_summary["keyFacts"]

    def test_rejection_leaves_no_net_customer_debit(self, payments) -> None:
        payload = sic("3300.00")
        payment = payments.create(
            PaymentCreate.model_validate(
                {
                    **payload,
                    "processingMode": "IMMEDIATE",
                    "failureInjections": [{"code": "CLEARING_REJECT_BUSINESS", "parameters": {}}],
                }
            )
        )
        account = payment.debtor_account
        before = account.balance
        payments.execute(payment, mode=ProcessingMode.IMMEDIATE)
        payments.session.refresh(account)
        assert account.balance == before

    def test_timeout_raises_pacs028_and_investigation(self, payments) -> None:
        payment = create_and_run(payments, sic("9900.00"), ["CLEARING_TIMEOUT"])
        assert payment.status == PaymentStatus.INVESTIGATION_REQUIRED.value
        clearing = payments.clearing.latest(payment.id)
        assert clearing.status == ClearingStatus.TIMED_OUT.value
        types = {m.message_type for m in payments.messages.all_for_payment(payment.id)}
        assert "pacs.028" in types
        assert "pacs.002" not in types
        investigations = payments.investigations.open_for_payment(payment.id)
        assert investigations[0].reason == "CLEARING_TIMEOUT"

    def test_timeout_stage_detail_explains_expected_vs_actual(self, payments) -> None:
        payment = create_and_run(payments, sic("9900.00"), ["CLEARING_TIMEOUT"])
        stage = stage_of(payment, StageKey.CLEARING_RESPONSE)
        assert stage.state == StageState.TIMED_OUT.value
        assert "expected" in stage.detail
        assert "actual" in stage.detail
        assert stage.detail["schemeThresholdSeconds"] == 25

    def test_timeout_recommends_investigation_not_resend(self, payments) -> None:
        payment = create_and_run(payments, sic("9900.00"), ["CLEARING_TIMEOUT"])
        inv = payments.investigations.open_for_payment(payment.id)[0]
        assert "not re-send" in inv.recommended_action or "Do not re-send" in inv.recommended_action

    def test_clearing_unavailable_does_not_dispatch(self, payments) -> None:
        payment = create_and_run(payments, sic("1200.00"), ["CLEARING_UNAVAILABLE"])
        assert payment.status == PaymentStatus.INVESTIGATION_REQUIRED.value
        clearing = payments.clearing.latest(payment.id)
        assert clearing.status == ClearingStatus.UNAVAILABLE.value
        assert not payments.accounting.entries_for_payment(payment.id)

    def test_malformed_response_is_not_processed_as_valid(self, payments) -> None:
        payment = create_and_run(payments, sic("7250.00"), ["CLEARING_MALFORMED_RESPONSE"])
        assert payment.status == PaymentStatus.INVESTIGATION_REQUIRED.value
        pacs002 = next(
            m for m in payments.messages.all_for_payment(payment.id) if m.message_type == "pacs.002"
        )
        assert pacs002.is_malformed
        assert "OrgnlEndToEndId" not in pacs002.xml_payload
        assert payments.settlement.latest(payment.id) is None

    def test_duplicate_response_is_recorded_once_only(self, payments) -> None:
        payment = create_and_run(payments, sic("1200.00"), ["CLEARING_DUPLICATE_RESPONSE"])
        assert payment.status == PaymentStatus.COMPLETED.value
        settlements = payments.settlement.all_for_payment(payment.id)
        assert len(settlements) == 1

    def test_delayed_response_still_completes(self, payments) -> None:
        payment = create_and_run(payments, sepa("15400.00"), ["CLEARING_DELAY"])
        assert payment.status == PaymentStatus.COMPLETED.value
        clearing = payments.clearing.latest(payment.id)
        assert clearing.requested_decision == "DELAY"


class TestSettlementAndAccounting:
    def test_settlement_failure_opens_investigation(self, payments) -> None:
        payment = create_and_run(payments, sic("1200.00"), ["SETTLEMENT_REJECTED"])
        assert payment.status == PaymentStatus.INVESTIGATION_REQUIRED.value
        settlement = payments.settlement.latest(payment.id)
        assert settlement.status == SettlementStatus.FAILED.value
        assert settlement.failure_reason
        assert payments.investigations.open_for_payment(payment.id)[0].reason == "SETTLEMENT_FAILURE"

    def test_partial_settlement_is_flagged(self, payments) -> None:
        payment = create_and_run(payments, sic("1000.00"), ["SETTLEMENT_PARTIAL"])
        settlement = payments.settlement.latest(payment.id)
        assert settlement.status == SettlementStatus.PARTIALLY_SETTLED.value
        assert settlement.settlement_amount < settlement.payment_amount

    def test_settled_but_status_not_updated_is_detected(self, payments) -> None:
        payment = create_and_run(payments, sic("6400.00"), ["SETTLEMENT_STATUS_NOT_UPDATED"])
        settlement = payments.settlement.latest(payment.id)
        assert settlement.status == SettlementStatus.SETTLED.value
        assert payment.status == PaymentStatus.INVESTIGATION_REQUIRED.value
        assert not payments.accounting.entries_for_payment(payment.id)

    def test_missing_accounting_entry_unbalances_the_journal(self, payments) -> None:
        payment = create_and_run(payments, sic("3150.00"), ["ACCOUNTING_MISSING_ENTRY"])
        entries = payments.accounting.entries_for_payment(payment.id)
        assert len(entries) == 1
        assert entries[0].side == EntrySide.DEBIT.value
        assert payment.status == PaymentStatus.INVESTIGATION_REQUIRED.value

    def test_duplicate_accounting_entry_is_flagged(self, payments) -> None:
        payment = create_and_run(payments, sic("1875.00"), ["ACCOUNTING_DUPLICATE_ENTRY"])
        entries = payments.accounting.entries_for_payment(payment.id)
        duplicates = [e for e in entries if e.is_duplicate]
        assert len(duplicates) == 1
        assert duplicates[0].status == AccountingStatus.DUPLICATE.value

    def test_amount_mismatch_between_legs_is_detected(self, payments) -> None:
        payment = create_and_run(payments, sic("1000.00"), ["ACCOUNTING_WRONG_AMOUNT"])
        entries = payments.accounting.entries_for_payment(payment.id)
        debit = next(e for e in entries if e.side == EntrySide.DEBIT.value)
        credit = next(e for e in entries if e.side == EntrySide.CREDIT.value)
        assert debit.amount != credit.amount
        assert payment.status == PaymentStatus.INVESTIGATION_REQUIRED.value

    def test_currency_mismatch_between_legs_is_detected(self, payments) -> None:
        payment = create_and_run(payments, sic("1000.00"), ["ACCOUNTING_WRONG_CURRENCY"])
        entries = payments.accounting.entries_for_payment(payment.id)
        assert len({e.currency for e in entries}) == 2
        assert payment.status == PaymentStatus.INVESTIGATION_REQUIRED.value

    def test_delayed_posting_leaves_debit_pending(self, payments) -> None:
        payment = create_and_run(payments, sic("1000.00"), ["ACCOUNTING_DELAYED_POSTING"])
        debit = next(
            e
            for e in payments.accounting.entries_for_payment(payment.id)
            if e.side == EntrySide.DEBIT.value
        )
        assert debit.status == AccountingStatus.PENDING.value

    def test_entries_record_running_balances(self, payments) -> None:
        payment = create_and_run(payments, sic("1200.00"))
        for entry in payments.accounting.entries_for_payment(payment.id):
            assert entry.balance_after is not None

    def test_outgoing_payment_reduces_the_nostro_position(self, payments) -> None:
        """A nostro is an asset: spending it must reduce it, not increase it."""
        from app.api.schemas import PaymentCreate

        payload = swift("10000.00", "USD")
        payment = payments.create(
            PaymentCreate.model_validate({**payload, "processingMode": "IMMEDIATE"})
        )
        nostro = payments.settlement.settlement_account(payment, get_scheme(payment.scheme))
        assert nostro is not None and nostro.account_type == "NOSTRO"
        before = nostro.balance

        payments.execute(payment, mode=ProcessingMode.IMMEDIATE)
        payments.session.refresh(nostro)

        assert nostro.balance == before - Decimal("10000.00"), (
            "an outgoing cross-border payment spends the money we hold at the correspondent"
        )

    def test_settlement_account_falls_when_we_pay_out(self, payments) -> None:
        from app.api.schemas import PaymentCreate

        payment = payments.create(
            PaymentCreate.model_validate({**sic("1200.00"), "processingMode": "IMMEDIATE"})
        )
        account = payments.settlement.settlement_account(payment, get_scheme(payment.scheme))
        assert account is not None
        before = account.balance

        payments.execute(payment, mode=ProcessingMode.IMMEDIATE)
        payments.session.refresh(account)

        assert account.balance == before - Decimal("1200.00")

    def test_reversal_restores_both_sides(self, payments) -> None:
        from app.api.schemas import PaymentCreate

        payment = payments.create(
            PaymentCreate.model_validate(
                {
                    **sepa("4300.00"),
                    "processingMode": "IMMEDIATE",
                    "failureInjections": [{"code": "BENEFICIARY_RETURN", "parameters": {}}],
                }
            )
        )
        debtor = payment.debtor_account
        settlement_account = payments.settlement.settlement_account(
            payment, get_scheme(payment.scheme)
        )
        assert debtor is not None and settlement_account is not None
        debtor_before = debtor.balance
        settlement_before = settlement_account.balance

        payments.execute(payment, mode=ProcessingMode.IMMEDIATE)
        payments.session.refresh(debtor)
        payments.session.refresh(settlement_account)

        # The return reverses both legs, so both accounts end where they started.
        assert debtor.balance == debtor_before
        assert settlement_account.balance == settlement_before


class TestReconciliation:
    @pytest.mark.parametrize(
        ("injection", "expected"),
        [
            ("RECON_MISSING_CAMT054", ReconciliationStatus.MISSING_ENTRY),
            ("RECON_AMOUNT_MISMATCH", ReconciliationStatus.AMOUNT_MISMATCH),
            ("RECON_CURRENCY_MISMATCH", ReconciliationStatus.CURRENCY_MISMATCH),
            ("RECON_DUPLICATE_SETTLEMENT", ReconciliationStatus.DUPLICATE),
            ("RECON_TIMING_DIFFERENCE", ReconciliationStatus.TIMING_DIFFERENCE),
            ("RECON_REFERENCE_MISMATCH", ReconciliationStatus.REFERENCE_MISMATCH),
        ],
    )
    def test_each_break_is_classified(self, payments, injection: str, expected) -> None:  # noqa: ANN001
        payment = create_and_run(payments, sic("5000.00"), [injection])
        record = payments.reconciliation.records_for_payment(payment.id)[-1]
        assert record.status == expected.value
        assert record.probable_cause
        assert record.recommended_action

    def test_break_opens_an_investigation(self, payments) -> None:
        payment = create_and_run(payments, sic("5000.00"), ["RECON_MISSING_CAMT054"])
        assert payment.status == PaymentStatus.INVESTIGATION_REQUIRED.value
        inv = payments.investigations.open_for_payment(payment.id)[0]
        assert inv.reconciliation_record_id is not None

    def test_amount_mismatch_records_the_difference(self, payments) -> None:
        payment = create_and_run(payments, sic("5000.00"), ["RECON_AMOUNT_MISMATCH"])
        record = payments.reconciliation.records_for_payment(payment.id)[-1]
        assert record.difference_amount == Decimal("-50.00")
        assert record.statement_amount == Decimal("4950.00")
        assert record.internal_amount == Decimal("5000.00")

    def test_unmatched_statement_entry_is_queued(self, payments) -> None:
        payment = create_and_run(payments, sic("2100.00"), ["RECON_UNMATCHED_STATEMENT"])
        assert payment.status == PaymentStatus.COMPLETED.value
        orphans = payments.reconciliation.unmatched_statement_entries()
        assert orphans
        assert orphans[0].payment_id is None

    def test_all_four_legs_are_reported(self, payments) -> None:
        payment = create_and_run(payments, sic("1200.00"))
        record = payments.reconciliation.records_for_payment(payment.id)[-1]
        names = {leg["source"] for leg in record.legs}
        assert names == {"payment", "accounting", "clearing", "statement"}

    def test_manual_reconcile_can_be_rerun(self, payments) -> None:
        payment = create_and_run(payments, sic("1200.00"))
        before = len(payments.reconciliation.records_for_payment(payment.id))
        payments.reconcile_now(payment)
        after = payments.reconciliation.records_for_payment(payment.id)
        assert len(after) == before + 1
        assert after[-1].status == ReconciliationStatus.MATCHED.value


class TestReturnsAndCancellation:
    def test_return_reverses_the_journal(self, payments) -> None:
        payment = create_and_run(payments, sepa("4300.00"), ["BENEFICIARY_RETURN"])
        assert payment.status == PaymentStatus.RETURNED.value
        entries = payments.accounting.entries_for_payment(payment.id)
        reversed_entries = [e for e in entries if e.status == AccountingStatus.REVERSED.value]
        assert reversed_entries
        active = [e for e in entries if e.status == AccountingStatus.POSTED.value]
        debits = sum(e.amount for e in active if e.side == EntrySide.DEBIT.value)
        credits = sum(e.amount for e in active if e.side == EntrySide.CREDIT.value)
        assert debits == credits

    def test_return_produces_a_pacs004(self, payments) -> None:
        payment = create_and_run(payments, sepa("4300.00"), ["BENEFICIARY_RETURN"])
        pacs004 = next(
            m for m in payments.messages.all_for_payment(payment.id) if m.message_type == "pacs.004"
        )
        assert pacs004.reason_code == "AC04"
        assert "RtrdIntrBkSttlmAmt" in pacs004.xml_payload

    def test_return_reverses_the_settlement(self, payments) -> None:
        payment = create_and_run(payments, sepa("4300.00"), ["BENEFICIARY_RETURN"])
        assert payments.settlement.latest(payment.id).status == SettlementStatus.REVERSED.value

    def test_cancellation_of_settled_payment_is_refused(self, payments) -> None:
        payment = create_and_run(payments, sic("1200.00"))
        _, resolution = payments.orchestrator.request_cancellation(
            payment, reason_code="CUST", narrative="customer changed their mind"
        )
        assert resolution is not None
        assert "RJCR" in resolution.xml_payload
        payments.session.refresh(payment)
        assert payment.status == PaymentStatus.COMPLETED.value

    def test_cancellation_before_settlement_succeeds(self, payments) -> None:
        payment = create_and_run(payments, sic("9900.00"), ["CLEARING_TIMEOUT"])
        request, resolution = payments.orchestrator.request_cancellation(
            payment, reason_code="CUTA", narrative="no response from clearing"
        )
        assert request.message_type == "camt.056"
        assert resolution is not None
        assert "CNCL" in resolution.xml_payload
        payments.session.refresh(payment)
        assert payment.status == PaymentStatus.CANCELLED.value

    def test_beneficiary_claim_opens_investigation_without_reversing(self, payments) -> None:
        payment = create_and_run(payments, swift("48000.00"), ["BENEFICIARY_NOT_CREDITED"])
        assert payment.status == PaymentStatus.INVESTIGATION_REQUIRED.value
        active = [
            e
            for e in payments.accounting.entries_for_payment(payment.id)
            if e.status == AccountingStatus.POSTED.value
        ]
        assert len(active) == 2
        reasons = {i.reason for i in payments.investigations.open_for_payment(payment.id)}
        assert "BENEFICIARY_NOT_CREDITED" in reasons


class TestStateMachine:
    def test_known_transitions_are_allowed(self) -> None:
        assert can_transition(PaymentStatus.INITIATED, PaymentStatus.VALIDATING).allowed
        assert can_transition(PaymentStatus.SETTLED, PaymentStatus.ACCOUNTED).allowed

    def test_illegal_transitions_are_blocked(self) -> None:
        check = can_transition(PaymentStatus.INITIATED, PaymentStatus.COMPLETED)
        assert not check.allowed
        assert "can only move to" in (check.reason or "")

    def test_terminal_states_have_no_forward_path(self) -> None:
        assert allowed_targets(PaymentStatus.CANCELLED) == []

    def test_graph_is_serialisable(self) -> None:
        rows = graph()
        assert rows
        assert {"from", "to", "isTerminal", "isFailure"} <= set(rows[0])

    def test_orchestrator_refuses_an_illegal_transition(self, payments) -> None:
        payment = create_and_run(payments, sic("1200.00"))
        with pytest.raises(IllegalTransitionError):
            payments.orchestrator.set_status(payment, PaymentStatus.VALIDATING)

    def test_completed_payment_cannot_be_re_executed(self, payments) -> None:
        payment = create_and_run(payments, sic("1200.00"))
        with pytest.raises(IllegalTransitionError):
            payments.execute(payment, mode=ProcessingMode.IMMEDIATE)


class TestRetry:
    def test_retry_of_a_rejected_payment_reruns_validation(self, payments) -> None:
        payment = create_and_run(payments, sic("1200.00"), ["INVALID_CREDITOR_IBAN"])
        assert payment.status == PaymentStatus.REJECTED.value
        payments.orchestrator.retry(
            payment, reason="Customer re-confirmed the IBAN", mode=ProcessingMode.IMMEDIATE
        )
        payments.session.refresh(payment)
        assert payment.retry_count == 1
        # The corrupted IBAN was not corrected, so the payment must fail again.
        assert payment.status == PaymentStatus.REJECTED.value

    def test_retry_succeeds_once_the_data_is_corrected(self, payments) -> None:
        payment = create_and_run(payments, sic("1200.00"), ["INVALID_CREDITOR_IBAN"])
        payment.creditor.iban = sic("1200.00")["creditor"]["iban"]
        payments.session.flush()
        payments.orchestrator.retry(
            payment, reason="IBAN corrected from the customer's invoice", mode=ProcessingMode.IMMEDIATE
        )
        payments.session.refresh(payment)
        assert payment.status == PaymentStatus.COMPLETED.value

    def test_retry_is_audited(self, payments) -> None:
        from sqlalchemy import select

        from app.db.models import AuditEvent

        payment = create_and_run(payments, sic("1200.00"), ["INVALID_CREDITOR_IBAN"])
        payments.orchestrator.retry(payment, reason="retry under test", mode=ProcessingMode.IMMEDIATE)
        rows = list(
            payments.session.execute(
                select(AuditEvent).where(
                    AuditEvent.entity_id == payment.reference, AuditEvent.action == "RETRY"
                )
            ).scalars()
        )
        assert rows
        assert rows[0].reason == "retry under test"
        assert rows[0].before["status"] == PaymentStatus.REJECTED.value

    def test_timeout_resolved_by_investigation_response_completes(self, payments) -> None:
        payment = create_and_run(payments, sic("9900.00"), ["CLEARING_TIMEOUT"])
        payments.orchestrator.resolve_timeout_with_response(payment, accepted=True)
        payments.session.refresh(payment)
        assert payment.status == PaymentStatus.COMPLETED.value
        assert payments.settlement.latest(payment.id).status == SettlementStatus.SETTLED.value

    def test_recovered_payment_keeps_no_stale_failure_summary(self, payments) -> None:
        payment = create_and_run(payments, sic("9900.00"), ["CLEARING_TIMEOUT"])
        assert payment.failure_summary is not None
        payments.orchestrator.resolve_timeout_with_response(payment, accepted=True)
        payments.session.refresh(payment)
        assert payment.failure_summary is None

    def test_answering_the_status_request_closes_the_investigation(self, payments) -> None:
        payment = create_and_run(payments, sic("9900.00"), ["CLEARING_TIMEOUT"])
        opened = payments.investigations.open_for_payment(payment.id)
        assert opened and opened[0].status == "OPEN"

        payments.orchestrator.resolve_timeout_with_response(payment, accepted=True)
        payments.session.refresh(payment)

        resolved = payments.investigations.open_for_payment(payment.id)[0]
        assert resolved.status == "RESOLVED"
        assert resolved.resolved_at is not None
        assert "accepted" in (resolved.resolution or "")
        actions = {action["action"] for action in resolved.actions}
        assert "RESPONSE_RECEIVED" in actions

    def test_timeout_resolved_as_rejection_reverses(self, payments) -> None:
        payment = create_and_run(payments, sic("9900.00"), ["CLEARING_TIMEOUT"])
        payments.orchestrator.resolve_timeout_with_response(
            payment, accepted=False, reason_code="AC01"
        )
        payments.session.refresh(payment)
        assert payment.status == PaymentStatus.CLEARING_REJECTED.value

    def test_rejection_after_a_timeout_reports_the_real_reason(self, payments) -> None:
        payment = create_and_run(payments, sic("9900.00"), ["CLEARING_TIMEOUT"])
        payments.orchestrator.resolve_timeout_with_response(
            payment, accepted=False, reason_code="AC01"
        )
        payments.session.refresh(payment)
        # The failure is now the rejection, not the timeout that preceded it.
        assert "AC01" in (payment.failure_summary or "")
        assert "no pacs.002" not in (payment.failure_summary or "")
        investigation = payments.investigations.open_for_payment(payment.id)[0]
        assert investigation.status == "RESOLVED"
