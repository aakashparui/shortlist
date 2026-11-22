"""ORM -> API response shaping.

Responses are camelCase and include both the business and technical views of
each object, so the UI can switch modes without a second round trip.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.db.models import (
    Account,
    AccountingEntry,
    Bank,
    BusinessRule,
    ClearingTransaction,
    FailureInjection,
    Investigation,
    Payment,
    PaymentEvent,
    PaymentMessage,
    PaymentParty,
    PaymentStage,
    ReconciliationRecord,
    Scenario,
    ScenarioExecution,
    SettlementTransaction,
    StatementEntry,
    TestCase,
    ValidationResult,
)
from app.domain.enums import (
    MESSAGE_METADATA,
    STAGE_LABELS,
    MessageType,
    PaymentStatus,
    StageKey,
)
from app.domain.money import format_amount


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _d(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _amt(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def party(row: PaymentParty | None) -> dict | None:
    if row is None:
        return None
    return {
        "role": row.role,
        "name": row.name,
        "accountIdentifier": row.account_identifier,
        "iban": row.iban,
        "bic": row.bic,
        "bankName": row.bank_name,
        "country": row.country,
        "town": row.town,
        "addressLines": list(row.address_lines or []),
    }


def account(row: Account | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "accountNumber": row.account_number,
        "iban": row.iban,
        "name": row.name,
        "accountType": row.account_type,
        "currency": row.currency,
        "balance": _amt(row.balance),
        "balanceFormatted": format_amount(row.balance or Decimal("0"), row.currency),
        "openingBalance": _amt(row.opening_balance),
        "overdraftLimit": _amt(row.overdraft_limit),
        "isActive": row.is_active,
        "description": row.description,
        "bank": {"bic": row.bank.bic, "name": row.bank.name} if row.bank else None,
        "correspondentBank": (
            {"bic": row.correspondent_bank.bic, "name": row.correspondent_bank.name}
            if row.correspondent_bank
            else None
        ),
    }


def bank(row: Bank) -> dict:
    return {
        "bic": row.bic,
        "name": row.name,
        "country": row.country,
        "city": row.city,
        "nationalClearingCode": row.national_clearing_code,
        "isDirectParticipant": row.is_direct_participant,
        "supportedSchemes": list(row.supported_schemes or []),
        "isInternal": row.is_internal,
        "notes": row.notes,
    }


def stage(row: PaymentStage) -> dict:
    try:
        labels = STAGE_LABELS[StageKey(row.stage_key)]
    except (KeyError, ValueError):  # pragma: no cover
        labels = {"business": row.stage_key, "technical": row.stage_key}
    return {
        "stageKey": row.stage_key,
        "sequence": row.sequence,
        "state": row.state,
        "businessLabel": labels["business"],
        "technicalLabel": labels["technical"],
        "ownerSystem": row.owner_system,
        "startedAt": _dt(row.started_at),
        "completedAt": _dt(row.completed_at),
        "durationMs": row.duration_ms,
        "summary": row.summary,
        "failureReason": row.failure_reason,
        "isoReasonCode": row.iso_reason_code,
        "detail": row.detail or {},
    }


def validation(row: ValidationResult) -> dict:
    return {
        "id": row.id,
        "runId": row.run_id,
        "ruleId": row.rule_id,
        "ruleName": row.rule_name,
        "category": row.category,
        "severity": row.severity,
        "status": row.status,
        "stage": row.stage,
        "message": row.message,
        "field": row.field,
        "actualValue": row.actual_value,
        "expectedValue": row.expected_value,
        "isoReasonCode": row.iso_reason_code,
        "remediation": row.remediation,
        "executedAt": _dt(row.executed_at),
        "durationMs": row.duration_ms,
        "injected": row.injected,
    }


def message(row: PaymentMessage, *, include_xml: bool = True) -> dict:
    try:
        meta = MESSAGE_METADATA[MessageType(row.message_type)]
    except (KeyError, ValueError):  # pragma: no cover
        meta = {"name": row.message_type, "purpose": ""}
    return {
        "id": row.id,
        "messageType": row.message_type,
        "messageName": meta["name"],
        "isoIdentifier": row.iso_identifier,
        "messageId": row.message_id,
        "direction": row.direction,
        "state": row.state,
        "relatedMessageId": row.related_message_id,
        "reasonCode": row.reason_code,
        "isMalformed": row.is_malformed,
        "createdAt": _dt(row.created_at),
        "sentAt": _dt(row.sent_at),
        "receivedAt": _dt(row.received_at),
        "notes": row.notes,
        "businessSummary": row.business_summary or {},
        "fieldMappings": row.field_mappings or [],
        "validationSummary": row.validation_summary or [],
        "payload": row.xml_payload if include_xml else None,
        "payloadFormat": "FIN" if row.message_type == "MT103" else "XML",
        "correlationId": row.correlation_id,
    }


def event(row: PaymentEvent) -> dict:
    return {
        "id": row.id,
        "paymentId": row.payment_id,
        "sequence": row.sequence,
        "eventType": row.event_type,
        "sourceSystem": row.source_system,
        "severity": row.severity,
        "stageKey": row.stage_key,
        "summary": row.summary,
        "detail": row.detail or {},
        "occurredAt": _dt(row.occurred_at),
        "durationMs": row.duration_ms,
        "correlationId": row.correlation_id,
    }


def clearing(row: ClearingTransaction) -> dict:
    return {
        "id": row.id,
        "clearingReference": row.clearing_reference,
        "clearingSystem": row.clearing_system,
        "scheme": row.scheme,
        "status": row.status,
        "decision": row.decision,
        "requestedDecision": row.requested_decision,
        "amount": _amt(row.amount),
        "currency": row.currency,
        "sentAt": _dt(row.sent_at),
        "responseDueAt": _dt(row.response_due_at),
        "timeoutAt": _dt(row.timeout_at),
        "respondedAt": _dt(row.responded_at),
        "responseLatencyMs": row.response_latency_ms,
        "statusReasonCode": row.status_reason_code,
        "statusReason": row.status_reason,
        "attempt": row.attempt,
        "responseCount": row.response_count,
        "requestMessageId": row.request_message_id,
        "responseMessageId": row.response_message_id,
        "detail": row.detail or {},
    }


def settlement(row: SettlementTransaction) -> dict:
    return {
        "id": row.id,
        "settlementReference": row.settlement_reference,
        "status": row.status,
        "paymentAmount": _amt(row.payment_amount),
        "paymentCurrency": row.payment_currency,
        "settlementAmount": _amt(row.settlement_amount),
        "settlementCurrency": row.settlement_currency,
        "settlementAmountFormatted": format_amount(
            row.settlement_amount or Decimal("0"), row.settlement_currency
        ),
        "settlementMethod": row.settlement_method,
        "valueDate": _d(row.value_date),
        "submittedAt": _dt(row.submitted_at),
        "settledAt": _dt(row.settled_at),
        "failureReason": row.failure_reason,
        "isoReasonCode": row.iso_reason_code,
        "account": account(row.settlement_account),
        "detail": row.detail or {},
    }


def accounting_entry(row: AccountingEntry) -> dict:
    return {
        "id": row.id,
        "entryId": row.entry_id,
        "accountingReference": row.accounting_reference,
        "journalSequence": row.journal_sequence,
        "side": row.side,
        "accountNumber": row.account_number,
        "accountName": row.account_name,
        "accountType": row.account_type,
        "amount": _amt(row.amount),
        "currency": row.currency,
        "amountFormatted": format_amount(row.amount or Decimal("0"), row.currency),
        "postingDate": _d(row.posting_date),
        "valueDate": _d(row.value_date),
        "postedAt": _dt(row.posted_at),
        "status": row.status,
        "narrative": row.narrative,
        "isDuplicate": row.is_duplicate,
        "isInjectedAnomaly": row.is_injected_anomaly,
        "anomalyNote": row.anomaly_note,
        "balanceAfter": _amt(row.balance_after),
    }


def statement_entry(row: StatementEntry) -> dict:
    return {
        "id": row.id,
        "paymentId": row.payment_id,
        "statementReference": row.statement_reference,
        "accountNumber": row.account_number,
        "side": row.side,
        "amount": _amt(row.amount),
        "currency": row.currency,
        "amountFormatted": format_amount(row.amount or Decimal("0"), row.currency),
        "bookingDate": _d(row.booking_date),
        "valueDate": _d(row.value_date),
        "endToEndId": row.end_to_end_id,
        "bankTransactionCode": row.bank_transaction_code,
        "narrative": row.narrative,
        "sourceMessageType": row.source_message_type,
        "sourceMessageId": row.source_message_id,
        "isOrphan": row.is_orphan,
        "createdAt": _dt(row.created_at),
    }


def reconciliation(row: ReconciliationRecord) -> dict:
    return {
        "id": row.id,
        "paymentId": row.payment_id,
        "paymentReference": row.payment.reference if row.payment else None,
        "reference": row.reference,
        "status": row.status,
        "runAt": _dt(row.run_at),
        "internalReference": row.internal_reference,
        "internalAmount": _amt(row.internal_amount),
        "internalCurrency": row.internal_currency,
        "accountingReference": row.accounting_reference,
        "accountingAmount": _amt(row.accounting_amount),
        "clearingReference": row.clearing_reference,
        "clearingAmount": _amt(row.clearing_amount),
        "statementReference": row.statement_reference,
        "statementAmount": _amt(row.statement_amount),
        "statementCurrency": row.statement_currency,
        "differenceAmount": _amt(row.difference_amount),
        "probableCause": row.probable_cause,
        "recommendedAction": row.recommended_action,
        "legs": row.legs or [],
        "detail": row.detail or {},
        "resolved": row.resolved,
    }


def investigation(row: Investigation) -> dict:
    return {
        "id": row.id,
        "reference": row.reference,
        "paymentId": row.payment_id,
        "paymentReference": row.payment.reference if row.payment else None,
        "status": row.status,
        "reason": row.reason,
        "priority": row.priority,
        "title": row.title,
        "summary": row.summary,
        "expectedBehaviour": row.expected_behaviour,
        "actualBehaviour": row.actual_behaviour,
        "probableCause": row.probable_cause,
        "recommendedAction": row.recommended_action,
        "assignedTo": row.assigned_to,
        "openedAt": _dt(row.opened_at),
        "updatedAt": _dt(row.updated_at),
        "resolvedAt": _dt(row.resolved_at),
        "resolution": row.resolution,
        "actions": row.actions or [],
        "detail": row.detail or {},
    }


def failure_injection(row: FailureInjection) -> dict:
    return {
        "id": row.id,
        "paymentId": row.payment_id,
        "code": row.code,
        "category": row.category,
        "label": row.label,
        "stageKey": row.stage_key,
        "parameters": row.parameters or {},
        "active": row.active,
        "consumed": row.consumed,
        "createdAt": _dt(row.created_at),
        "createdBy": row.created_by,
        "effectSummary": row.effect_summary,
    }


def business_rule(row: BusinessRule) -> dict:
    return {
        "ruleId": row.rule_id,
        "name": row.name,
        "description": row.description,
        "category": row.category,
        "severity": row.severity,
        "stage": row.stage,
        "schemes": list(row.schemes or []),
        "appliesTo": list(row.applies_to or []),
        "field": row.field,
        "failureBehaviour": row.failure_behaviour,
        "isoReasonCode": row.iso_reason_code,
        "rationale": row.rationale,
        "standardBasis": row.standard_basis,
        "enabled": row.enabled,
        "parameters": row.parameters or {},
    }


def scenario(row: Scenario) -> dict:
    return {
        "code": row.code,
        "title": row.title,
        "category": row.category,
        "scheme": row.scheme,
        "description": row.description,
        "businessContext": row.business_context,
        "preconditions": list(row.preconditions or []),
        "inputData": row.input_data or {},
        "failureCodes": list(row.failure_codes or []),
        "executionSteps": list(row.execution_steps or []),
        "expectedStatus": row.expected_status,
        "expectedResult": list(row.expected_result or []),
        "expectedMessages": list(row.expected_messages or []),
        "expectedAccounting": list(row.expected_accounting or []),
        "expectedReconciliation": row.expected_reconciliation,
        "failureConditions": list(row.failure_conditions or []),
        "isDemoHighlight": row.is_demo_highlight,
        "sortOrder": row.sort_order,
    }


def scenario_execution(row: ScenarioExecution, *, payment_reference: str | None = None) -> dict:
    return {
        "id": row.id,
        "reference": row.reference,
        "scenarioCode": row.scenario_code,
        "scenarioTitle": row.scenario.title if row.scenario else None,
        "paymentId": row.payment_id,
        "paymentReference": payment_reference,
        "startedAt": _dt(row.started_at),
        "finishedAt": _dt(row.finished_at),
        "outcome": row.outcome,
        "actualStatus": row.actual_status,
        "expectedStatus": row.expected_status,
        "assertions": list(row.assertions or []),
        "notes": row.notes,
    }


def test_case(row: TestCase) -> dict:
    return {
        "id": row.id,
        "caseId": row.case_id,
        "suite": row.suite,
        "ruleId": row.rule_id,
        "scheme": row.scheme,
        "testType": row.test_type,
        "title": row.title,
        "preconditions": list(row.preconditions or []),
        "steps": list(row.steps or []),
        "inputData": row.input_data or {},
        "expectedResult": row.expected_result,
        "expectedStatus": row.expected_status,
        "expectedRuleOutcome": row.expected_rule_outcome,
        "priority": row.priority,
        "requirementId": row.requirement_id,
        "createdAt": _dt(row.created_at),
        "lastRunAt": _dt(row.last_run_at),
        "lastRunOutcome": row.last_run_outcome,
        "lastRunDetail": row.last_run_detail or {},
    }


def payment_summary(row: Payment) -> dict:
    status = PaymentStatus(row.status)
    debtor = row.debtor
    creditor = row.creditor
    return {
        "id": row.id,
        "reference": row.reference,
        "correlationId": row.correlation_id,
        "scheme": row.scheme,
        "status": row.status,
        "isFailure": status.is_failure,
        "isTerminal": status.is_terminal,
        "amount": _amt(row.amount),
        "currency": row.currency,
        "amountFormatted": format_amount(row.amount or Decimal("0"), row.currency),
        "debtorName": debtor.name if debtor else "",
        "creditorName": creditor.name if creditor else "",
        "creditorCountry": creditor.country if creditor else "",
        "endToEndId": row.end_to_end_id,
        "uetr": row.uetr,
        "createdAt": _dt(row.created_at),
        "updatedAt": _dt(row.updated_at),
        "completedAt": _dt(row.completed_at),
        "failureSummary": row.failure_summary,
        "scenarioCode": row.scenario_code,
        "retryCount": row.retry_count,
        "isDemoData": row.is_demo_data,
        "tags": list(row.tags or []),
    }


def payment_detail(row: Payment, *, extras: dict[str, Any] | None = None) -> dict:
    status = PaymentStatus(row.status)
    data = {
        **payment_summary(row),
        "previousStatus": row.previous_status,
        "processingMode": row.processing_mode,
        "direction": row.direction,
        "requestedExecutionDate": _d(row.requested_execution_date),
        "instructionId": row.instruction_id,
        "transactionId": row.transaction_id,
        "remittanceInformation": row.remittance_information,
        "remittanceStructured": row.remittance_structured or {},
        "purposeCode": row.purpose_code,
        "categoryPurpose": row.category_purpose,
        "serviceLevel": row.service_level,
        "localInstrument": row.local_instrument,
        "clearingChannel": row.clearing_channel,
        "chargeBearer": row.charge_bearer,
        "priority": row.priority,
        "createdBy": row.created_by,
        "source": row.source,
        "notes": row.notes,
        "executedAt": _dt(row.executed_at),
        "statusIsFailure": status.is_failure,
        "debtor": party(row.debtor),
        "creditor": party(row.creditor),
        "debtorAccount": account(row.debtor_account),
        "stages": [stage(s) for s in sorted(row.stages, key=lambda s: s.sequence)],
        "failureInjections": [failure_injection(f) for f in row.failure_injections],
    }
    if extras:
        data.update(extras)
    return data
