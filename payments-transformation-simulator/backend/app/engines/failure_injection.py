"""Failure injection engine.

Design principle: an injection never fakes a result. It changes the *input* or
the *behaviour of a downstream system*, and the engines then fail for real. That
is what makes a failure reproducible and explainable:

  * data injections mutate the payment before validation runs, so the real rule
    fires and produces a real validation result;
  * clearing injections configure the simulated clearing system's response;
  * settlement / accounting / reconciliation injections are consumed by those
    engines when they execute.

Every injection records what it changed, so the investigation view can show
"this is why it failed" rather than "a failure was requested".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.identifiers import utcnow
from app.core.logging import get_logger
from app.db.models import FailureInjection, Payment
from app.domain.enums import FailureCategory, StageKey

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class FailureDefinition:
    code: str
    label: str
    category: FailureCategory
    stage: StageKey
    description: str
    mechanism: str
    expected_outcome: str
    expected_status: str
    affected_rule_ids: tuple[str, ...] = ()
    parameters: dict = field(default_factory=dict)
    schemes: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "label": self.label,
            "category": self.category.value,
            "stage": self.stage.value,
            "description": self.description,
            "mechanism": self.mechanism,
            "expectedOutcome": self.expected_outcome,
            "expectedStatus": self.expected_status,
            "affectedRuleIds": list(self.affected_rule_ids),
            "parameters": dict(self.parameters),
            "schemes": list(self.schemes),
        }


CATALOGUE: tuple[FailureDefinition, ...] = (
    # --- validation ----------------------------------------------------
    FailureDefinition(
        code="INVALID_CREDITOR_IBAN",
        label="Invalid creditor IBAN",
        category=FailureCategory.VALIDATION,
        stage=StageKey.PRE_VALIDATION,
        description="Corrupts the creditor IBAN so the ISO 13616 check digits no longer validate.",
        mechanism="Replaces the last character of the creditor IBAN, breaking the mod-97 check.",
        expected_outcome="VAL-IBAN-002 fails and the payment is rejected before compliance screening.",
        expected_status="REJECTED",
        affected_rule_ids=("VAL-IBAN-002",),
    ),
    FailureDefinition(
        code="INVALID_CREDITOR_BIC",
        label="Invalid creditor BIC",
        category=FailureCategory.VALIDATION,
        stage=StageKey.PRE_VALIDATION,
        description="Replaces the creditor agent BIC with a structurally invalid value.",
        mechanism="Sets the BIC to a value that violates the ISO 9362 structure.",
        expected_outcome="VAL-BIC-001 fails and the payment is rejected.",
        expected_status="REJECTED",
        affected_rule_ids=("VAL-BIC-001", "SWIFT-BIC-001"),
        parameters={"bic": "12INVALIDBIC"},
    ),
    FailureDefinition(
        code="UNSUPPORTED_CURRENCY",
        label="Unsupported currency for the scheme",
        category=FailureCategory.VALIDATION,
        stage=StageKey.BUSINESS_VALIDATION,
        description="Sets a currency the selected rail does not clear.",
        mechanism="Overwrites the payment currency with one outside the scheme's allowed list.",
        expected_outcome="The scheme currency rule fails and the payment is rejected with AM03.",
        expected_status="REJECTED",
        affected_rule_ids=("SIC-CCY-001", "SEPA-CCY-001", "SWIFT-CCY-001", "VAL-CCY-001"),
        parameters={"currency": "USD"},
    ),
    FailureDefinition(
        code="AMOUNT_EXCEEDS_SCHEME_LIMIT",
        label="Amount exceeds the scheme ceiling",
        category=FailureCategory.VALIDATION,
        stage=StageKey.BUSINESS_VALIDATION,
        description="Raises the amount above the rail's maximum transaction value.",
        mechanism="Sets the amount to the scheme maximum plus a margin.",
        expected_outcome="The scheme amount rule fails with AM04 and the payment is rejected.",
        expected_status="REJECTED",
        affected_rule_ids=("VAL-AMOUNT-003", "SIC-AMOUNT-001", "SEPA-AMOUNT-001"),
        parameters={"overBy": "1000.00"},
    ),
    FailureDefinition(
        code="MISSING_MANDATORY_FIELD",
        label="Missing mandatory field",
        category=FailureCategory.VALIDATION,
        stage=StageKey.PRE_VALIDATION,
        description="Clears a mandatory element from the instruction.",
        mechanism="Blanks the chosen field before validation runs.",
        expected_outcome="VAL-STRUCT-001 (and the field-specific rule) fail; the payment is rejected.",
        expected_status="REJECTED",
        affected_rule_ids=("VAL-STRUCT-001", "VAL-CDTR-001"),
        parameters={"field": "creditor.name"},
    ),
    FailureDefinition(
        code="REMITTANCE_TOO_LONG",
        label="Remittance information too long",
        category=FailureCategory.VALIDATION,
        stage=StageKey.BUSINESS_VALIDATION,
        description="Sets unstructured remittance information longer than the scheme limit.",
        mechanism="Pads the remittance text past the configured maximum length.",
        expected_outcome="VAL-RMT-001 fails and the payment is rejected.",
        expected_status="REJECTED",
        affected_rule_ids=("VAL-RMT-001",),
    ),
    FailureDefinition(
        code="DUPLICATE_END_TO_END_ID",
        label="Duplicate EndToEndId",
        category=FailureCategory.VALIDATION,
        stage=StageKey.BUSINESS_VALIDATION,
        description="Reuses the EndToEndId of an earlier payment on the same rail.",
        mechanism=(
            "Copies the EndToEndId from the most recent other payment on the same scheme, so the "
            "duplicate check genuinely finds a prior instruction."
        ),
        expected_outcome="VAL-DUP-001 fails with AM05 and the payment is rejected as a duplicate.",
        expected_status="REJECTED",
        affected_rule_ids=("VAL-DUP-001",),
    ),
    FailureDefinition(
        code="INSUFFICIENT_FUNDS",
        label="Insufficient funds on the debtor account",
        category=FailureCategory.VALIDATION,
        stage=StageKey.BUSINESS_VALIDATION,
        description="Raises the amount above the debtor's available balance and overdraft.",
        mechanism="Sets the amount to available balance plus a margin.",
        expected_outcome="VAL-ACCT-002 fails with AM04 and the payment is rejected.",
        expected_status="REJECTED",
        affected_rule_ids=("VAL-ACCT-002",),
    ),
    FailureDefinition(
        code="PAST_EXECUTION_DATE",
        label="Execution date in the past",
        category=FailureCategory.VALIDATION,
        stage=StageKey.BUSINESS_VALIDATION,
        description="Back-dates the requested execution date.",
        mechanism="Sets the requested execution date to yesterday.",
        expected_outcome="VAL-DATE-001 fails with DT01 and the payment is rejected.",
        expected_status="REJECTED",
        affected_rule_ids=("VAL-DATE-001",),
    ),
    # --- compliance ----------------------------------------------------
    FailureDefinition(
        code="EMBARGO_HIT",
        label="Embargo jurisdiction hit",
        category=FailureCategory.COMPLIANCE,
        stage=StageKey.COMPLIANCE,
        description="Points the creditor at an embargoed (fictional) jurisdiction.",
        mechanism=(
            "Sets the creditor country to a fictional embargoed country code so the screening "
            "engine produces a genuine list match."
        ),
        expected_outcome="COMP-EMB-001 hits, the payment is BLOCKED and an investigation is opened.",
        expected_status="BLOCKED",
        affected_rule_ids=("COMP-EMB-001",),
        parameters={"country": "ZZ"},
    ),
    FailureDefinition(
        code="SANCTIONS_MATCH",
        label="Sanctions party match",
        category=FailureCategory.COMPLIANCE,
        stage=StageKey.COMPLIANCE,
        description="Renames the creditor to a designated (fictional) entity.",
        mechanism="Sets the creditor name to an entry on the simulator's fictional designated list.",
        expected_outcome="COMP-SANC-001 hits, the payment is BLOCKED and escalated.",
        expected_status="BLOCKED",
        affected_rule_ids=("COMP-SANC-001",),
        parameters={"name": "VOLKOV TRADING LLC"},
    ),
    FailureDefinition(
        code="SUSPICIOUS_REMITTANCE",
        label="Suspicious remittance wording",
        category=FailureCategory.COMPLIANCE,
        stage=StageKey.COMPLIANCE,
        description="Inserts high-risk wording into the remittance information.",
        mechanism="Appends a typology keyword to the remittance text.",
        expected_outcome="COMP-AML-001 alerts and the payment is BLOCKED pending disposition.",
        expected_status="BLOCKED",
        affected_rule_ids=("COMP-AML-001",),
        parameters={"keyword": "ARMS"},
    ),
    # --- clearing ------------------------------------------------------
    FailureDefinition(
        code="CLEARING_REJECT_BUSINESS",
        label="Clearing business rejection (pacs.002 RJCT)",
        category=FailureCategory.CLEARING,
        stage=StageKey.CLEARING_RESPONSE,
        description="The clearing system returns a business rejection.",
        mechanism="Configures the simulated clearing system to answer RJCT with a business reason code.",
        expected_outcome=(
            "A real pacs.002 RJCT is received, the payment moves to CLEARING_REJECTED and any "
            "customer debit is reversed."
        ),
        expected_status="CLEARING_REJECTED",
        parameters={"reasonCode": "AC01"},
    ),
    FailureDefinition(
        code="CLEARING_REJECT_TECHNICAL",
        label="Clearing technical rejection",
        category=FailureCategory.CLEARING,
        stage=StageKey.CLEARING_RESPONSE,
        description="The clearing system rejects the message on technical grounds.",
        mechanism="Configures the simulated clearing system to answer RJCT with FF01.",
        expected_outcome="pacs.002 RJCT/FF01 received; the payment is CLEARING_REJECTED.",
        expected_status="CLEARING_REJECTED",
        parameters={"reasonCode": "FF01"},
    ),
    FailureDefinition(
        code="CLEARING_UNAVAILABLE",
        label="Clearing system unavailable",
        category=FailureCategory.CLEARING,
        stage=StageKey.CLEARING,
        description="The clearing system cannot be reached at dispatch time.",
        mechanism="The adapter records the instruction as not accepted for processing.",
        expected_outcome=(
            "No pacs.008 is accepted, the payment goes to INVESTIGATION_REQUIRED and can be retried."
        ),
        expected_status="INVESTIGATION_REQUIRED",
    ),
    FailureDefinition(
        code="CLEARING_DUPLICATE_RESPONSE",
        label="Duplicate pacs.002 response",
        category=FailureCategory.CLEARING,
        stage=StageKey.CLEARING_RESPONSE,
        description="The clearing system sends the same status report twice.",
        mechanism="A second identical pacs.002 is delivered after the first.",
        expected_outcome=(
            "The payment settles once; the second response is recorded and flagged as a duplicate "
            "rather than being processed again."
        ),
        expected_status="COMPLETED",
    ),
    FailureDefinition(
        code="CLEARING_MALFORMED_RESPONSE",
        label="Malformed pacs.002 response",
        category=FailureCategory.CLEARING,
        stage=StageKey.CLEARING_RESPONSE,
        description="A status report arrives without the original end-to-end identification.",
        mechanism="Generates a pacs.002 with OrgnlEndToEndId omitted.",
        expected_outcome=(
            "The response cannot be matched automatically, the payment stays awaiting a usable "
            "response and an investigation is opened."
        ),
        expected_status="INVESTIGATION_REQUIRED",
    ),
    # --- timeout -------------------------------------------------------
    FailureDefinition(
        code="CLEARING_TIMEOUT",
        label="No pacs.002 received (timeout)",
        category=FailureCategory.TIMEOUT,
        stage=StageKey.CLEARING_RESPONSE,
        description="The clearing system never answers.",
        mechanism=(
            "The adapter schedules no response. When the scheme threshold elapses the timeout "
            "handler fires, sends a pacs.028 status request and opens an investigation."
        ),
        expected_outcome="Payment reaches TIMED_OUT then INVESTIGATION_REQUIRED; pacs.028 is sent.",
        expected_status="INVESTIGATION_REQUIRED",
    ),
    FailureDefinition(
        code="CLEARING_DELAY",
        label="Delayed pacs.002 response",
        category=FailureCategory.TIMEOUT,
        stage=StageKey.CLEARING_RESPONSE,
        description="The status report arrives late but still inside the scheme window.",
        mechanism="Pushes the response time close to the timeout threshold.",
        expected_outcome=(
            "The payment completes, but the clearing latency recorded on the transaction shows the "
            "delay for SLA reporting."
        ),
        expected_status="COMPLETED",
    ),
    # --- settlement ----------------------------------------------------
    FailureDefinition(
        code="SETTLEMENT_REJECTED",
        label="Settlement rejected",
        category=FailureCategory.SETTLEMENT,
        stage=StageKey.SETTLEMENT,
        description="The settlement instruction fails at the settlement agent.",
        mechanism="The settlement engine records a FAILED settlement with a liquidity reason.",
        expected_outcome="Payment moves to SETTLEMENT_FAILED and an investigation is opened.",
        expected_status="SETTLEMENT_FAILED",
    ),
    FailureDefinition(
        code="SETTLEMENT_MISMATCH",
        label="Settlement amount mismatch",
        category=FailureCategory.SETTLEMENT,
        stage=StageKey.SETTLEMENT,
        description="The settled amount differs from the payment amount.",
        mechanism="Applies a delta to the settlement amount.",
        expected_outcome="Settlement succeeds but reconciliation reports an AMOUNT_MISMATCH break.",
        expected_status="RECONCILIATION_BREAK",
        parameters={"deltaAmount": "-50.00"},
    ),
    FailureDefinition(
        code="SETTLEMENT_PARTIAL",
        label="Partial settlement",
        category=FailureCategory.SETTLEMENT,
        stage=StageKey.SETTLEMENT,
        description="Only part of the payment amount settles.",
        mechanism="Settles a configurable percentage of the amount.",
        expected_outcome="Settlement status PARTIALLY_SETTLED; reconciliation reports a break.",
        expected_status="RECONCILIATION_BREAK",
        parameters={"settledPercent": "60"},
    ),
    FailureDefinition(
        code="SETTLEMENT_STATUS_NOT_UPDATED",
        label="Settled but internal status not updated",
        category=FailureCategory.SETTLEMENT,
        stage=StageKey.SETTLEMENT,
        description="Settlement completes but the status update to the payment engine is lost.",
        mechanism=(
            "The settlement engine posts a SETTLED transaction while suppressing the status "
            "transition, so the payment remains SETTLEMENT_PENDING."
        ),
        expected_outcome=(
            "A classic operational break: the settlement record says settled while the payment "
            "status says pending. An investigation is opened."
        ),
        expected_status="INVESTIGATION_REQUIRED",
    ),
    # --- accounting ----------------------------------------------------
    FailureDefinition(
        code="ACCOUNTING_MISSING_ENTRY",
        label="Customer debited, accounting entry missing",
        category=FailureCategory.ACCOUNTING,
        stage=StageKey.ACCOUNTING,
        description="The customer debit posts but the settlement credit leg never does.",
        mechanism="The accounting engine omits the credit leg of the journal.",
        expected_outcome="The journal does not balance; ACCOUNTING_BREAK and an investigation.",
        expected_status="ACCOUNTING_BREAK",
    ),
    FailureDefinition(
        code="ACCOUNTING_DUPLICATE_ENTRY",
        label="Duplicated accounting entry",
        category=FailureCategory.ACCOUNTING,
        stage=StageKey.ACCOUNTING,
        description="The settlement credit leg is posted twice.",
        mechanism="The accounting engine posts a second identical credit entry.",
        expected_outcome="Ledger overstated; ACCOUNTING_BREAK with a duplicate classification.",
        expected_status="ACCOUNTING_BREAK",
    ),
    FailureDefinition(
        code="ACCOUNTING_WRONG_AMOUNT",
        label="Debit/credit amount mismatch",
        category=FailureCategory.ACCOUNTING,
        stage=StageKey.ACCOUNTING,
        description="The two legs of the journal carry different amounts.",
        mechanism="Applies a delta to the credit leg only.",
        expected_outcome="ACCOUNTING_BREAK; reconciliation shows the difference.",
        expected_status="ACCOUNTING_BREAK",
        parameters={"deltaAmount": "-50.00"},
    ),
    FailureDefinition(
        code="ACCOUNTING_WRONG_CURRENCY",
        label="Debit/credit currency mismatch",
        category=FailureCategory.ACCOUNTING,
        stage=StageKey.ACCOUNTING,
        description="The credit leg is booked in the wrong currency.",
        mechanism="Posts the credit leg in a different currency from the debit leg.",
        expected_outcome="ACCOUNTING_BREAK with a currency mismatch classification.",
        expected_status="ACCOUNTING_BREAK",
        parameters={"currency": "EUR"},
    ),
    FailureDefinition(
        code="ACCOUNTING_DELAYED_POSTING",
        label="Delayed posting",
        category=FailureCategory.ACCOUNTING,
        stage=StageKey.ACCOUNTING,
        description="The customer debit stays in a pending state.",
        mechanism="Posts the debit leg with status PENDING instead of POSTED.",
        expected_outcome="ACCOUNTING_BREAK: the credit is applied while the debit is still pending.",
        expected_status="ACCOUNTING_BREAK",
    ),
    # --- reconciliation ------------------------------------------------
    FailureDefinition(
        code="RECON_MISSING_CAMT054",
        label="Missing camt.054 notification",
        category=FailureCategory.RECONCILIATION,
        stage=StageKey.RECONCILIATION,
        description="The account servicer never notifies the account movement.",
        mechanism="The statement feed publishes no entry for the payment.",
        expected_outcome="Reconciliation status MISSING_ENTRY; RECONCILIATION_BREAK.",
        expected_status="RECONCILIATION_BREAK",
    ),
    FailureDefinition(
        code="RECON_AMOUNT_MISMATCH",
        label="Statement amount mismatch",
        category=FailureCategory.RECONCILIATION,
        stage=StageKey.RECONCILIATION,
        description="The statement entry amount differs from the internal amount.",
        mechanism="Applies a delta to the published statement entry.",
        expected_outcome="Reconciliation status AMOUNT_MISMATCH; RECONCILIATION_BREAK.",
        expected_status="RECONCILIATION_BREAK",
        parameters={"deltaAmount": "-50.00"},
    ),
    FailureDefinition(
        code="RECON_CURRENCY_MISMATCH",
        label="Statement currency mismatch",
        category=FailureCategory.RECONCILIATION,
        stage=StageKey.RECONCILIATION,
        description="The statement entry is in a different currency.",
        mechanism="Publishes the statement entry in another currency.",
        expected_outcome="Reconciliation status CURRENCY_MISMATCH; RECONCILIATION_BREAK.",
        expected_status="RECONCILIATION_BREAK",
        parameters={"currency": "EUR"},
    ),
    FailureDefinition(
        code="RECON_DUPLICATE_SETTLEMENT",
        label="Duplicate settlement notification",
        category=FailureCategory.RECONCILIATION,
        stage=StageKey.RECONCILIATION,
        description="Two statement entries are received for the same payment.",
        mechanism="Publishes a second identical statement entry.",
        expected_outcome="Reconciliation status DUPLICATE; RECONCILIATION_BREAK.",
        expected_status="RECONCILIATION_BREAK",
    ),
    FailureDefinition(
        code="RECON_UNMATCHED_STATEMENT",
        label="Unmatched statement entry",
        category=FailureCategory.RECONCILIATION,
        stage=StageKey.RECONCILIATION,
        description="The statement contains a movement with no internal payment record.",
        mechanism="Publishes an orphan statement entry alongside the matched one.",
        expected_outcome=(
            "The payment itself reconciles, but an unmatched entry appears in the reconciliation "
            "exception queue for investigation."
        ),
        expected_status="COMPLETED",
        parameters={"endToEndId": "E2EUNKNOWN0000"},
    ),
    FailureDefinition(
        code="RECON_TIMING_DIFFERENCE",
        label="Booking date timing difference",
        category=FailureCategory.RECONCILIATION,
        stage=StageKey.RECONCILIATION,
        description="The statement books the entry in a later period.",
        mechanism="Shifts the statement booking date forward.",
        expected_outcome="Reconciliation status TIMING_DIFFERENCE; flagged but low severity.",
        expected_status="RECONCILIATION_BREAK",
        parameters={"bookingDateOffsetDays": 2},
    ),
    FailureDefinition(
        code="RECON_REFERENCE_MISMATCH",
        label="Statement reference mismatch",
        category=FailureCategory.RECONCILIATION,
        stage=StageKey.RECONCILIATION,
        description="The statement entry carries a different end-to-end reference.",
        mechanism="Publishes the statement entry with an altered EndToEndId.",
        expected_outcome="Reconciliation status REFERENCE_MISMATCH; automatic matching fails.",
        expected_status="RECONCILIATION_BREAK",
    ),
    # --- returns -------------------------------------------------------
    FailureDefinition(
        code="BENEFICIARY_RETURN",
        label="Beneficiary bank returns the payment",
        category=FailureCategory.RETURN,
        stage=StageKey.COMPLETION,
        description=(
            "The payment is accepted and settled, then returned by the beneficiary bank because "
            "the account is closed."
        ),
        mechanism=(
            "After completion a real pacs.004 is received, the journal is reversed and the payment "
            "moves to RETURNED."
        ),
        expected_outcome="Payment status RETURNED with reversal entries and a pacs.004 on file.",
        expected_status="RETURNED",
        parameters={"reasonCode": "AC04"},
    ),
    FailureDefinition(
        code="BENEFICIARY_NOT_CREDITED",
        label="Clearing accepted but beneficiary not credited",
        category=FailureCategory.RETURN,
        stage=StageKey.RECONCILIATION,
        description=(
            "The clearing system accepted the payment and our side settled, but the beneficiary "
            "never received the funds."
        ),
        mechanism=(
            "The payment completes normally, then a customer claim opens an investigation and a "
            "camt.056 cancellation request is sent."
        ),
        expected_outcome="An open investigation with a camt.056 sent and a camt.029 response.",
        expected_status="INVESTIGATION_REQUIRED",
    ),
)

CATALOGUE_BY_CODE: dict[str, FailureDefinition] = {d.code: d for d in CATALOGUE}

PRE_EXECUTION_CODES = frozenset(
    {
        "INVALID_CREDITOR_IBAN",
        "INVALID_CREDITOR_BIC",
        "UNSUPPORTED_CURRENCY",
        "AMOUNT_EXCEEDS_SCHEME_LIMIT",
        "MISSING_MANDATORY_FIELD",
        "REMITTANCE_TOO_LONG",
        "DUPLICATE_END_TO_END_ID",
        "INSUFFICIENT_FUNDS",
        "PAST_EXECUTION_DATE",
        "EMBARGO_HIT",
        "SANCTIONS_MATCH",
        "SUSPICIOUS_REMITTANCE",
    }
)


class FailureInjectionEngine:
    def __init__(self, session: Session) -> None:
        self.session = session

    # -- registration ---------------------------------------------------
    def register(
        self,
        payment: Payment,
        code: str,
        parameters: dict | None = None,
        *,
        created_by: str = "qa.lab",
    ) -> FailureInjection:
        definition = CATALOGUE_BY_CODE.get(code)
        if definition is None:
            raise KeyError(code)
        merged = {**definition.parameters, **(parameters or {})}
        row = FailureInjection(
            payment_id=payment.id,
            code=code,
            category=definition.category.value,
            label=definition.label,
            stage_key=definition.stage.value,
            parameters=merged,
            active=True,
            consumed=False,
            created_at=utcnow(),
            created_by=created_by,
        )
        self.session.add(row)
        self.session.flush()
        logger.info(
            "failure injection registered",
            extra={"payment_reference": payment.reference, "code": code, "parameters": merged},
        )
        return row

    def active_for(self, payment_id: int) -> list[FailureInjection]:
        return list(
            self.session.execute(
                select(FailureInjection)
                .where(FailureInjection.payment_id == payment_id, FailureInjection.active.is_(True))
                .order_by(FailureInjection.created_at.asc())
            ).scalars()
        )

    def all_for(self, payment_id: int) -> list[FailureInjection]:
        return list(
            self.session.execute(
                select(FailureInjection)
                .where(FailureInjection.payment_id == payment_id)
                .order_by(FailureInjection.created_at.asc())
            ).scalars()
        )

    def deactivate(self, injection_id: int) -> FailureInjection | None:
        row = self.session.get(FailureInjection, injection_id)
        if row is None:
            return None
        row.active = False
        self.session.flush()
        return row

    def clear_for_payment(self, payment_id: int) -> int:
        rows = self.active_for(payment_id)
        for row in rows:
            row.active = False
        self.session.flush()
        return len(rows)

    # -- application ----------------------------------------------------
    def apply_pre_execution(self, payment: Payment) -> list[dict]:
        """Mutate the instruction so that the real rules fail.

        Returns a list of change records for the audit trail and investigation view.
        """
        from app.schemes.registry import get_scheme

        scheme = get_scheme(payment.scheme)
        changes: list[dict] = []
        for injection in self.active_for(payment.id):
            if injection.code not in PRE_EXECUTION_CODES or injection.consumed:
                continue
            change = self._mutate(payment, scheme, injection)
            if change:
                injection.consumed = True
                injection.effect_summary = change["summary"]
                changes.append(change)
        if changes:
            self.session.flush()
        return changes

    def _mutate(self, payment: Payment, scheme, injection: FailureInjection) -> dict | None:  # noqa: ANN001
        params = dict(injection.parameters or {})
        code = injection.code
        creditor = payment.creditor
        debtor = payment.debtor

        def record(field: str, before, after, summary: str) -> dict:
            return {
                "code": code,
                "field": field,
                "before": None if before is None else str(before),
                "after": None if after is None else str(after),
                "summary": summary,
            }

        if code == "INVALID_CREDITOR_IBAN" and creditor and creditor.iban:
            before = creditor.iban
            last = before[-1]
            replacement = "0" if last != "0" else "1"
            creditor.iban = before[:-1] + replacement
            return record(
                "creditor.iban",
                before,
                creditor.iban,
                f"Creditor IBAN corrupted from {before} to {creditor.iban}; mod-97 check now fails.",
            )

        if code == "INVALID_CREDITOR_BIC" and creditor:
            before = creditor.bic
            creditor.bic = str(params.get("bic", "12INVALIDBIC"))
            return record(
                "creditor.bic",
                before,
                creditor.bic,
                f"Creditor BIC replaced with structurally invalid value {creditor.bic}.",
            )

        if code == "UNSUPPORTED_CURRENCY":
            before = payment.currency
            candidate = str(params.get("currency", "")).upper()
            if not candidate or candidate in scheme.rules.allowed_currencies:
                candidate = next(
                    (c for c in ("USD", "GBP", "INR", "SEK") if c not in scheme.rules.allowed_currencies),
                    "USD",
                )
            payment.currency = candidate
            return record(
                "currency",
                before,
                candidate,
                f"Currency changed from {before} to {candidate}, which {scheme.short_name} does not clear.",
            )

        if code == "AMOUNT_EXCEEDS_SCHEME_LIMIT":
            limit = scheme.rules.limit_for(payment.currency or "")
            if limit is None:
                return None
            before = payment.amount
            over = Decimal(str(params.get("overBy", "1000.00")))
            payment.amount = limit.maximum + over
            return record(
                "amount",
                before,
                payment.amount,
                (
                    f"Amount raised from {before} to {payment.amount} {payment.currency}, above the "
                    f"{limit.maximum} {limit.currency} scheme ceiling."
                ),
            )

        if code == "MISSING_MANDATORY_FIELD":
            target = str(params.get("field", "creditor.name"))
            mapping = {
                "creditor.name": (creditor, "name"),
                "debtor.name": (debtor, "name"),
                "creditor.iban": (creditor, "iban"),
                "debtor.iban": (debtor, "iban"),
                "creditor.account": (creditor, "account_identifier"),
            }
            if target == "endToEndId":
                before = payment.end_to_end_id
                payment.end_to_end_id = ""
                return record("endToEndId", before, "", "EndToEndId cleared from the instruction.")
            holder, attribute = mapping.get(target, (creditor, "name"))
            if holder is None:
                return None
            before = getattr(holder, attribute)
            setattr(holder, attribute, "" if attribute != "iban" else None)
            if attribute == "iban":
                holder.account_identifier = ""
            return record(
                target, before, "", f"Mandatory field {target} cleared from the instruction."
            )

        if code == "REMITTANCE_TOO_LONG":
            before = payment.remittance_information
            maximum = scheme.rules.max_remittance_length
            payment.remittance_information = (
                "INVOICE SETTLEMENT REFERENCE " * ((maximum // 28) + 2)
            )[: maximum + 25]
            return record(
                "remittanceInformation",
                f"{len(before or '')} characters",
                f"{len(payment.remittance_information)} characters",
                (
                    f"Remittance information padded to {len(payment.remittance_information)} "
                    f"characters, above the {maximum} character limit."
                ),
            )

        if code == "DUPLICATE_END_TO_END_ID":
            prior = self.session.execute(
                select(Payment)
                .where(
                    Payment.scheme == payment.scheme,
                    Payment.id != payment.id,
                    Payment.end_to_end_id != "",
                    Payment.status.notin_(("DRAFT", "REJECTED", "CANCELLED")),
                )
                .order_by(Payment.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if prior is None:
                return None
            before = payment.end_to_end_id
            payment.end_to_end_id = prior.end_to_end_id
            return record(
                "endToEndId",
                before,
                payment.end_to_end_id,
                (
                    f"EndToEndId replaced with {prior.end_to_end_id}, already used by "
                    f"{prior.reference}."
                ),
            )

        if code == "INSUFFICIENT_FUNDS":
            account = payment.debtor_account
            if account is None:
                return None
            before = payment.amount
            available = (account.balance or Decimal("0")) + (account.overdraft_limit or Decimal("0"))
            payment.amount = available + Decimal(str(params.get("overBy", "1000.00")))
            return record(
                "amount",
                before,
                payment.amount,
                (
                    f"Amount raised from {before} to {payment.amount} {payment.currency}, above the "
                    f"{available} {account.currency} available on the debtor account."
                ),
            )

        if code == "PAST_EXECUTION_DATE":
            before = payment.requested_execution_date
            payment.requested_execution_date = (utcnow() - timedelta(days=1)).date()
            return record(
                "requestedExecutionDate",
                before,
                payment.requested_execution_date,
                "Requested execution date back-dated by one day.",
            )

        if code == "EMBARGO_HIT" and creditor:
            before = creditor.country
            creditor.country = str(params.get("country", "ZZ")).upper()
            return record(
                "creditor.country",
                before,
                creditor.country,
                f"Creditor country set to {creditor.country}, an embargoed jurisdiction.",
            )

        if code == "SANCTIONS_MATCH" and creditor:
            before = creditor.name
            creditor.name = str(params.get("name", "VOLKOV TRADING LLC")).upper()
            return record(
                "creditor.name",
                before,
                creditor.name,
                f"Creditor renamed to '{creditor.name}', an entry on the designated-party list.",
            )

        if code == "SUSPICIOUS_REMITTANCE":
            before = payment.remittance_information
            keyword = str(params.get("keyword", "ARMS"))
            payment.remittance_information = f"{(before or '').strip()} {keyword} SHIPMENT".strip()[:140]
            return record(
                "remittanceInformation",
                before,
                payment.remittance_information,
                f"Remittance wording now contains the high-risk keyword '{keyword}'.",
            )

        return None

    def compliance_overrides(self, payment: Payment) -> dict:
        """Values that make the compliance engine produce a genuine list hit."""
        overrides: dict = {}
        for injection in self.all_for(payment.id):
            if not injection.active:
                continue
            params = dict(injection.parameters or {})
            if injection.code == "EMBARGO_HIT":
                overrides["embargo_country"] = params.get("country", "ZZ")
            if injection.code == "SANCTIONS_MATCH":
                overrides["sanctioned_party"] = params.get("name", "VOLKOV TRADING LLC")
        return overrides

    def has_active(self, payment_id: int, code: str) -> bool:
        return any(i.code == code and i.active for i in self.all_for(payment_id))


def catalogue() -> list[dict]:
    return [definition.as_dict() for definition in CATALOGUE]
