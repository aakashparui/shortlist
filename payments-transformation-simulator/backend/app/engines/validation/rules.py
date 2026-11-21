"""The rule book.

Each rule is a declarative definition plus a pure-ish evaluator function. Rules
live here — never inside UI components or API handlers — so that the Business
Rule Explorer, the test-case generator and the processing engine all read from
exactly the same source of truth.

ISO 20022 external reason codes (AM04, AC01, ...) are real code values from the
ExternalStatusReason code set. Their assignment to simulator rules is a
reasonable mapping, not an authoritative scheme mapping.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.domain.enums import Severity, StageKey, ValidationCategory
from app.domain.identifiers_bank import (
    SEPA_COUNTRIES,
    check_iban,
    is_valid_bic,
    normalise_bic,
)
from app.domain.money import has_valid_scale, is_supported_currency, scale_for
from app.engines.validation.context import RuleDefinition, RuleOutcome, ValidationContext

NA = RuleOutcome(passed=None)


def _party_country(party, fallback_iban: str | None = None) -> str:
    if party is None:
        return ""
    if party.country:
        return party.country.upper()
    if party.bic:
        from app.domain.identifiers_bank import bic_country

        return bic_country(party.bic)
    if fallback_iban:
        return fallback_iban[:2].upper()
    return ""


# ---------------------------------------------------------------------------
# Structural / technical
# ---------------------------------------------------------------------------


def _eval_struct_mandatory(ctx: ValidationContext) -> RuleOutcome:
    p = ctx.payment
    missing: list[str] = []
    if not (p.debtor and p.debtor.name.strip()):
        missing.append("debtor.name")
    if not (p.creditor and p.creditor.name.strip()):
        missing.append("creditor.name")
    if p.amount is None:
        missing.append("amount")
    if not p.currency:
        missing.append("currency")
    if not p.end_to_end_id:
        missing.append("endToEndId")
    if not p.instruction_id:
        missing.append("instructionId")
    if missing:
        return RuleOutcome(
            passed=False,
            message=f"Mandatory field(s) missing: {', '.join(missing)}",
            field=missing[0],
            actual_value="<empty>",
            expected_value="a non-empty value",
            remediation="Populate every mandatory element before resubmitting the instruction.",
            iso_reason_code="FF01",
        )
    return RuleOutcome(passed=True, message="All mandatory instruction elements are present.")


def _eval_amount_positive(ctx: ValidationContext) -> RuleOutcome:
    amount = ctx.payment.amount
    if amount is None:
        return RuleOutcome(
            passed=False,
            message="Amount is absent.",
            field="amount",
            actual_value="<empty>",
            expected_value="> 0",
            iso_reason_code="AM01",
        )
    if amount <= 0:
        return RuleOutcome(
            passed=False,
            message="Instructed amount must be greater than zero.",
            field="amount",
            actual_value=str(amount),
            expected_value="> 0",
            remediation="Instruct a positive amount; zero and negative amounts are not creditable.",
            iso_reason_code="AM01",
        )
    return RuleOutcome(
        passed=True, message="Instructed amount is positive.", field="amount", actual_value=str(amount)
    )


def _eval_amount_scale(ctx: ValidationContext) -> RuleOutcome:
    p = ctx.payment
    if p.amount is None or not p.currency:
        return NA
    digits = scale_for(p.currency)
    if not has_valid_scale(p.amount, p.currency):
        return RuleOutcome(
            passed=False,
            message=f"{p.currency} supports at most {digits} decimal place(s).",
            field="amount",
            actual_value=str(p.amount),
            expected_value=f"max {digits} decimal place(s)",
            remediation="Round the instructed amount to the currency's minor-unit precision.",
            iso_reason_code="AM11",
        )
    return RuleOutcome(
        passed=True,
        message=f"Amount precision is valid for {p.currency} ({digits} decimals).",
        field="amount",
    )


def _eval_amount_scheme_limit(ctx: ValidationContext) -> RuleOutcome:
    p = ctx.payment
    limit = ctx.scheme.rules.limit_for(p.currency or "")
    if limit is None or p.amount is None:
        return NA
    if p.amount > limit.maximum:
        return RuleOutcome(
            passed=False,
            message=(
                f"Instructed amount exceeds the {ctx.scheme.short_name} maximum of "
                f"{limit.maximum} {limit.currency}."
            ),
            field="amount",
            actual_value=f"{p.amount} {p.currency}",
            expected_value=f"<= {limit.maximum} {limit.currency}",
            remediation="Use a non-instant rail for this amount or split the instruction.",
            iso_reason_code="AM04",
        )
    if p.amount < limit.minimum:
        return RuleOutcome(
            passed=False,
            message=(
                f"Instructed amount is below the {ctx.scheme.short_name} minimum of "
                f"{limit.minimum} {limit.currency}."
            ),
            field="amount",
            actual_value=f"{p.amount} {p.currency}",
            expected_value=f">= {limit.minimum} {limit.currency}",
            iso_reason_code="AM03",
        )
    return RuleOutcome(
        passed=True,
        message=f"Amount is within the scheme range {limit.minimum}-{limit.maximum} {limit.currency}.",
        field="amount",
        actual_value=f"{p.amount} {p.currency}",
        expected_value=f"{limit.minimum} - {limit.maximum} {limit.currency}",
    )


def _eval_currency_known(ctx: ValidationContext) -> RuleOutcome:
    ccy = (ctx.payment.currency or "").upper()
    if not ccy:
        return RuleOutcome(
            passed=False,
            message="Currency is absent.",
            field="currency",
            actual_value="<empty>",
            expected_value="an ISO 4217 alphabetic code",
            iso_reason_code="FF01",
        )
    if len(ccy) != 3 or not ccy.isalpha():
        return RuleOutcome(
            passed=False,
            message="Currency must be a 3-letter ISO 4217 alphabetic code.",
            field="currency",
            actual_value=ccy,
            expected_value="3 alphabetic characters",
            iso_reason_code="FF01",
        )
    if not is_supported_currency(ccy):
        return RuleOutcome(
            passed=False,
            message=f"Currency {ccy} is not configured in this simulator.",
            field="currency",
            actual_value=ccy,
            expected_value="a configured simulator currency",
            remediation="Pick a currency that the simulator and the selected scheme support.",
            iso_reason_code="AM03",
        )
    return RuleOutcome(passed=True, message=f"{ccy} is a known currency.", field="currency", actual_value=ccy)


def _eval_scheme_currency(ctx: ValidationContext) -> RuleOutcome:
    ccy = (ctx.payment.currency or "").upper()
    allowed = ctx.scheme.rules.allowed_currencies
    if not ccy:
        return NA
    if ccy not in allowed:
        return RuleOutcome(
            passed=False,
            message=f"{ctx.scheme.short_name} does not clear {ccy}.",
            field="currency",
            actual_value=ccy,
            expected_value=", ".join(allowed),
            remediation=f"Route {ccy} payments to a rail that supports the currency.",
            iso_reason_code="AM03",
        )
    return RuleOutcome(
        passed=True,
        message=f"{ccy} is supported by {ctx.scheme.short_name}.",
        field="currency",
        actual_value=ccy,
        expected_value=", ".join(allowed),
    )


def _eval_debtor_name(ctx: ValidationContext) -> RuleOutcome:
    debtor = ctx.payment.debtor
    name = (debtor.name if debtor else "") or ""
    if not name.strip():
        return RuleOutcome(
            passed=False,
            message="Debtor name is mandatory.",
            field="debtor.name",
            actual_value="<empty>",
            expected_value="1-140 characters",
            iso_reason_code="FF01",
        )
    if len(name) > 140:
        return RuleOutcome(
            passed=False,
            message="Debtor name exceeds the ISO 20022 Max140Text limit.",
            field="debtor.name",
            actual_value=f"{len(name)} characters",
            expected_value="<= 140 characters",
            iso_reason_code="FF01",
        )
    return RuleOutcome(passed=True, message="Debtor name is present and within length.", field="debtor.name")


def _eval_debtor_account(ctx: ValidationContext) -> RuleOutcome:
    debtor = ctx.payment.debtor
    identifier = (debtor.iban or debtor.account_identifier if debtor else "") or ""
    if not identifier.strip():
        return RuleOutcome(
            passed=False,
            message="Debtor account identification is mandatory.",
            field="debtor.account",
            actual_value="<empty>",
            expected_value="IBAN or other account identifier",
            iso_reason_code="AC01",
        )
    return RuleOutcome(
        passed=True, message="Debtor account is identified.", field="debtor.account", actual_value=identifier
    )


def _eval_creditor_name(ctx: ValidationContext) -> RuleOutcome:
    creditor = ctx.payment.creditor
    name = (creditor.name if creditor else "") or ""
    if not name.strip():
        return RuleOutcome(
            passed=False,
            message="Creditor name is mandatory.",
            field="creditor.name",
            actual_value="<empty>",
            expected_value="1-140 characters",
            iso_reason_code="FF01",
        )
    if len(name) > 140:
        return RuleOutcome(
            passed=False,
            message="Creditor name exceeds the ISO 20022 Max140Text limit.",
            field="creditor.name",
            actual_value=f"{len(name)} characters",
            expected_value="<= 140 characters",
            iso_reason_code="FF01",
        )
    return RuleOutcome(passed=True, message="Creditor name is present and within length.", field="creditor.name")


def _eval_creditor_account(ctx: ValidationContext) -> RuleOutcome:
    creditor = ctx.payment.creditor
    identifier = (creditor.iban or creditor.account_identifier if creditor else "") or ""
    if not identifier.strip():
        return RuleOutcome(
            passed=False,
            message="Creditor account identification is mandatory.",
            field="creditor.account",
            actual_value="<empty>",
            expected_value="IBAN or other account identifier",
            remediation="Obtain the beneficiary account details from the customer.",
            iso_reason_code="AC01",
        )
    return RuleOutcome(
        passed=True,
        message="Creditor account is identified.",
        field="creditor.account",
        actual_value=identifier,
    )


def _eval_bic_structure(ctx: ValidationContext) -> RuleOutcome:
    creditor = ctx.payment.creditor
    bic = normalise_bic(creditor.bic if creditor else None)
    if not bic:
        return NA
    if not is_valid_bic(bic):
        return RuleOutcome(
            passed=False,
            message="Creditor agent BIC is not a valid ISO 9362 identifier.",
            field="creditor.bic",
            actual_value=bic,
            expected_value="4 letters + 2 letter country + 2 alphanumeric [+ 3 alphanumeric branch]",
            remediation="Correct the BIC; an 8- or 11-character ISO 9362 value is required.",
            iso_reason_code="RC01",
        )
    return RuleOutcome(
        passed=True,
        message="Creditor agent BIC is structurally valid.",
        field="creditor.bic",
        actual_value=bic,
    )


def _eval_debtor_iban(ctx: ValidationContext) -> RuleOutcome:
    party = ctx.payment.debtor
    iban = (party.iban if party else None) or ""
    required = ctx.scheme.rules.requires_iban_debtor
    if not iban:
        if required:
            return RuleOutcome(
                passed=False,
                message=f"{ctx.scheme.short_name} requires the debtor account to be an IBAN.",
                field="debtor.iban",
                actual_value="<empty>",
                expected_value="a valid IBAN",
                iso_reason_code="AC01",
            )
        return NA
    check = check_iban(iban)
    if not check.valid:
        return RuleOutcome(
            passed=False,
            message=f"Debtor IBAN is invalid: {check.reason}.",
            field="debtor.iban",
            actual_value=check.iban,
            expected_value=(
                f"{check.expected_length} characters for {check.country} and a valid mod-97 check"
                if check.expected_length
                else "a valid ISO 13616 IBAN"
            ),
            remediation="Re-key the debtor IBAN; the ISO 13616 check digits did not validate.",
            iso_reason_code="AC01",
        )
    return RuleOutcome(
        passed=True,
        message="Debtor IBAN passes the ISO 13616 mod-97 check.",
        field="debtor.iban",
        actual_value=check.iban,
    )


def _eval_creditor_iban(ctx: ValidationContext) -> RuleOutcome:
    party = ctx.payment.creditor
    iban = (party.iban if party else None) or ""
    required = ctx.scheme.rules.requires_iban_creditor
    if not iban:
        if required:
            return RuleOutcome(
                passed=False,
                message=f"{ctx.scheme.short_name} requires the creditor account to be an IBAN.",
                field="creditor.iban",
                actual_value="<empty>",
                expected_value="a valid IBAN",
                iso_reason_code="AC01",
            )
        return NA
    check = check_iban(iban)
    if not check.valid:
        return RuleOutcome(
            passed=False,
            message=f"Creditor IBAN is invalid: {check.reason}.",
            field="creditor.iban",
            actual_value=check.iban,
            expected_value=(
                f"{check.expected_length} characters for {check.country} and a valid mod-97 check"
                if check.expected_length
                else "a valid ISO 13616 IBAN"
            ),
            remediation="Confirm the beneficiary IBAN with the customer and resubmit.",
            iso_reason_code="AC01",
        )
    return RuleOutcome(
        passed=True,
        message="Creditor IBAN passes the ISO 13616 mod-97 check.",
        field="creditor.iban",
        actual_value=check.iban,
    )


def _eval_e2e_format(ctx: ValidationContext) -> RuleOutcome:
    e2e = ctx.payment.end_to_end_id or ""
    if not e2e:
        return RuleOutcome(
            passed=False,
            message="EndToEndId is mandatory.",
            field="endToEndId",
            actual_value="<empty>",
            expected_value="1-35 characters",
            iso_reason_code="FF01",
        )
    if len(e2e) > 35:
        return RuleOutcome(
            passed=False,
            message="EndToEndId exceeds the ISO 20022 Max35Text limit.",
            field="endToEndId",
            actual_value=f"{len(e2e)} characters",
            expected_value="<= 35 characters",
            iso_reason_code="FF01",
        )
    return RuleOutcome(
        passed=True, message="EndToEndId is present and within Max35Text.", field="endToEndId", actual_value=e2e
    )


def _eval_duplicate(ctx: ValidationContext) -> RuleOutcome:
    from app.db.models import Payment

    p = ctx.payment
    window = timedelta(minutes=ctx.scheme.rules.duplicate_window_minutes)
    since = ctx.now - window
    stmt = (
        select(Payment.reference, Payment.created_at)
        .where(
            Payment.end_to_end_id == p.end_to_end_id,
            Payment.scheme == p.scheme,
            Payment.id != p.id,
            Payment.created_at >= since,
            Payment.status.notin_(("DRAFT", "REJECTED", "CANCELLED")),
        )
        .order_by(Payment.created_at.desc())
        .limit(1)
    )
    hit = ctx.session.execute(stmt).first()
    if hit:
        return RuleOutcome(
            passed=False,
            message=(
                f"EndToEndId '{p.end_to_end_id}' was already used by {hit[0]} within the "
                f"{ctx.scheme.rules.duplicate_window_minutes} minute duplicate window."
            ),
            field="endToEndId",
            actual_value=f"{p.end_to_end_id} (also on {hit[0]})",
            expected_value=f"unique per scheme within {ctx.scheme.rules.duplicate_window_minutes} minutes",
            remediation=(
                "Confirm with the customer whether this is a genuine repeat instruction. "
                "If so, assign a new EndToEndId."
            ),
            iso_reason_code="AM05",
        )
    return RuleOutcome(
        passed=True,
        message="No prior payment with this EndToEndId inside the duplicate window.",
        field="endToEndId",
        actual_value=p.end_to_end_id,
    )


def _eval_remittance_length(ctx: ValidationContext) -> RuleOutcome:
    text = ctx.payment.remittance_information or ""
    maximum = ctx.scheme.rules.max_remittance_length
    if len(text) > maximum:
        return RuleOutcome(
            passed=False,
            message=f"Unstructured remittance information exceeds {maximum} characters.",
            field="remittanceInformation",
            actual_value=f"{len(text)} characters",
            expected_value=f"<= {maximum} characters",
            remediation="Shorten the remittance text or use structured remittance information.",
            iso_reason_code="FF01",
        )
    return RuleOutcome(
        passed=True,
        message=f"Remittance information is within the {maximum} character scheme limit.",
        field="remittanceInformation",
        actual_value=f"{len(text)} characters",
        expected_value=f"<= {maximum} characters",
    )


def _eval_execution_date(ctx: ValidationContext) -> RuleOutcome:
    p = ctx.payment
    requested = p.requested_execution_date
    if requested is None:
        return NA
    today = ctx.now.date()
    if requested < today:
        return RuleOutcome(
            passed=False,
            message="Requested execution date is in the past.",
            field="requestedExecutionDate",
            actual_value=requested.isoformat(),
            expected_value=f">= {today.isoformat()}",
            remediation="Re-date the instruction to today or a permitted future date.",
            iso_reason_code="DT01",
        )
    if requested > today:
        if not ctx.scheme.rules.allows_future_dated:
            return RuleOutcome(
                passed=False,
                message=f"{ctx.scheme.short_name} executes immediately and does not accept future dating.",
                field="requestedExecutionDate",
                actual_value=requested.isoformat(),
                expected_value=today.isoformat(),
                iso_reason_code="DT01",
            )
        horizon = today + timedelta(days=ctx.scheme.rules.max_future_days)
        if requested > horizon:
            return RuleOutcome(
                passed=False,
                message=(
                    f"Requested execution date is beyond the {ctx.scheme.rules.max_future_days} day "
                    "warehousing horizon."
                ),
                field="requestedExecutionDate",
                actual_value=requested.isoformat(),
                expected_value=f"<= {horizon.isoformat()}",
                iso_reason_code="DT01",
            )
    return RuleOutcome(
        passed=True,
        message="Requested execution date is acceptable for this rail.",
        field="requestedExecutionDate",
        actual_value=requested.isoformat(),
    )


def _eval_debtor_account_exists(ctx: ValidationContext) -> RuleOutcome:
    account = ctx.payment.debtor_account
    if account is None:
        return RuleOutcome(
            passed=False,
            message="Debtor account is not held at this institution.",
            field="debtor.account",
            actual_value=(ctx.payment.debtor.iban if ctx.payment.debtor else None) or "<unknown>",
            expected_value="an active account on the bank's book",
            remediation="Check the debtor account number; the simulator holds a fixed demo book.",
            iso_reason_code="AC01",
        )
    if not account.is_active:
        return RuleOutcome(
            passed=False,
            message="Debtor account is blocked or closed.",
            field="debtor.account",
            actual_value=f"{account.account_number} (inactive)",
            expected_value="an active account",
            iso_reason_code="AC06",
        )
    if account.currency != (ctx.payment.currency or "").upper():
        return RuleOutcome(
            passed=True,
            message=(
                f"Debtor account is held in {account.currency}; the instruction is in "
                f"{ctx.payment.currency}. A currency conversion will be required."
            ),
            field="debtor.account",
            actual_value=account.currency,
            expected_value=ctx.payment.currency,
            severity_override=Severity.WARNING,
        )
    return RuleOutcome(
        passed=True,
        message="Debtor account exists, is active and matches the instructed currency.",
        field="debtor.account",
        actual_value=account.account_number,
    )


def _eval_debtor_funds(ctx: ValidationContext) -> RuleOutcome:
    account = ctx.payment.debtor_account
    p = ctx.payment
    if account is None or p.amount is None:
        return NA
    if account.currency != (p.currency or "").upper():
        return RuleOutcome(
            passed=True,
            message="Cover check skipped: account and instruction currencies differ (FX required).",
            field="amount",
            severity_override=Severity.INFO,
        )
    available = (account.balance or Decimal("0")) + (account.overdraft_limit or Decimal("0"))
    if p.amount > available:
        return RuleOutcome(
            passed=False,
            message="Insufficient funds on the debtor account including the agreed overdraft.",
            field="amount",
            actual_value=f"available {available} {account.currency}",
            expected_value=f"at least {p.amount} {p.currency}",
            remediation="Fund the account or reduce the instructed amount.",
            iso_reason_code="AM04",
        )
    return RuleOutcome(
        passed=True,
        message="Debtor account holds sufficient available funds.",
        field="amount",
        actual_value=f"available {available} {account.currency}",
        expected_value=f"at least {p.amount} {p.currency}",
    )


# ---------------------------------------------------------------------------
# Message-level (executed at message generation)
# ---------------------------------------------------------------------------


def _eval_msg_group_header(ctx: ValidationContext) -> RuleOutcome:
    p = ctx.payment
    required = {
        "GrpHdr/MsgId": bool(ctx.extras.get("message_id")),
        "GrpHdr/CreDtTm": True,
        "GrpHdr/NbOfTxs": True,
        "GrpHdr/SttlmInf/SttlmMtd": bool(ctx.scheme.messages.settlement_method),
        "CdtTrfTxInf/PmtId/EndToEndId": bool(p.end_to_end_id),
        "CdtTrfTxInf/IntrBkSttlmAmt": p.amount is not None,
        "CdtTrfTxInf/Dbtr/Nm": bool(p.debtor and p.debtor.name),
        "CdtTrfTxInf/Cdtr/Nm": bool(p.creditor and p.creditor.name),
    }
    missing = [path for path, present in required.items() if not present]
    if missing:
        return RuleOutcome(
            passed=False,
            message=f"pacs.008 is missing mandatory element(s): {', '.join(missing)}",
            field=missing[0],
            actual_value="<absent>",
            expected_value="present",
            iso_reason_code="FF01",
        )
    return RuleOutcome(
        passed=True, message="pacs.008 mandatory element coverage is complete.", field="GrpHdr"
    )


def _eval_msg_amount_consistency(ctx: ValidationContext) -> RuleOutcome:
    p = ctx.payment
    instructed = ctx.extras.get("instructed_amount", p.amount)
    settlement = ctx.extras.get("settlement_amount", p.amount)
    if instructed is None or settlement is None:
        return NA
    if Decimal(str(instructed)) != Decimal(str(settlement)):
        return RuleOutcome(
            passed=False,
            message="InstdAmt and IntrBkSttlmAmt differ without a charge or FX explanation.",
            field="IntrBkSttlmAmt",
            actual_value=f"instructed {instructed} / settlement {settlement}",
            expected_value="equal amounts, or a documented charge/FX difference",
            iso_reason_code="AM09",
        )
    return RuleOutcome(
        passed=True,
        message="Instructed amount and interbank settlement amount agree.",
        field="IntrBkSttlmAmt",
        actual_value=str(settlement),
    )


# ---------------------------------------------------------------------------
# Scheme-specific
# ---------------------------------------------------------------------------


def _eval_sic_country(ctx: ValidationContext) -> RuleOutcome:
    p = ctx.payment
    debtor_country = _party_country(p.debtor, p.debtor.iban if p.debtor else None)
    creditor_country = _party_country(p.creditor, p.creditor.iban if p.creditor else None)
    scope = ctx.scheme.rules.country_scope or ()
    offending = [c for c in (debtor_country, creditor_country) if c and c not in scope]
    if offending:
        return RuleOutcome(
            passed=False,
            message=(
                f"{ctx.scheme.short_name} is a domestic rail; both parties must be in "
                f"{'/'.join(scope)} (found {', '.join(offending)})."
            ),
            field="creditor.country",
            actual_value=f"debtor {debtor_country or '??'} / creditor {creditor_country or '??'}",
            expected_value="/".join(scope),
            remediation="Route the payment cross-border via the SWIFT rail instead.",
            iso_reason_code="RR04",
        )
    return RuleOutcome(
        passed=True,
        message="Both parties are inside the domestic scheme scope.",
        field="creditor.country",
        actual_value=f"debtor {debtor_country} / creditor {creditor_country}",
    )


def _eval_sepa_country(ctx: ValidationContext) -> RuleOutcome:
    p = ctx.payment
    debtor_country = _party_country(p.debtor, p.debtor.iban if p.debtor else None)
    creditor_country = _party_country(p.creditor, p.creditor.iban if p.creditor else None)
    offending = [c for c in (debtor_country, creditor_country) if c and c not in SEPA_COUNTRIES]
    if offending:
        return RuleOutcome(
            passed=False,
            message=f"Party country outside the SEPA area: {', '.join(offending)}.",
            field="creditor.country",
            actual_value=f"debtor {debtor_country or '??'} / creditor {creditor_country or '??'}",
            expected_value="a SEPA scheme country",
            remediation="Use the cross-border rail for non-SEPA beneficiaries.",
            iso_reason_code="RR04",
        )
    return RuleOutcome(
        passed=True,
        message="Both parties are inside the SEPA area.",
        field="creditor.country",
        actual_value=f"debtor {debtor_country} / creditor {creditor_country}",
    )


def _eval_swift_bic_required(ctx: ValidationContext) -> RuleOutcome:
    creditor = ctx.payment.creditor
    bic = normalise_bic(creditor.bic if creditor else None)
    if not bic:
        return RuleOutcome(
            passed=False,
            message="Creditor agent BIC is mandatory for cross-border payments.",
            field="creditor.bic",
            actual_value="<empty>",
            expected_value="an ISO 9362 BIC",
            remediation="Obtain the beneficiary bank's BIC; routing cannot be derived without it.",
            iso_reason_code="RC01",
        )
    return RuleOutcome(
        passed=True, message="Creditor agent BIC is present.", field="creditor.bic", actual_value=bic
    )


def _eval_swift_address(ctx: ValidationContext) -> RuleOutcome:
    creditor = ctx.payment.creditor
    lines = (creditor.address_lines if creditor else None) or []
    town = (creditor.town if creditor else "") or ""
    country = (creditor.country if creditor else "") or ""
    if not country:
        return RuleOutcome(
            passed=False,
            message="Creditor country is mandatory for cross-border payments.",
            field="creditor.country",
            actual_value="<empty>",
            expected_value="ISO 3166 alpha-2 country code",
            iso_reason_code="FF01",
        )
    if not (lines or town):
        return RuleOutcome(
            passed=False,
            message=(
                "Creditor postal address is required for cross-border payments "
                "(town/city or address line)."
            ),
            field="creditor.address",
            actual_value="<empty>",
            expected_value="town/city and/or address line",
            remediation=(
                "Capture the beneficiary address. Cross-border transparency expectations "
                "require structured party data."
            ),
            iso_reason_code="FF01",
        )
    return RuleOutcome(
        passed=True,
        message="Creditor address data is sufficient for cross-border transparency.",
        field="creditor.address",
        actual_value=", ".join([*lines, town, country]).strip(", "),
    )


def _eval_swift_cutoff(ctx: ValidationContext) -> RuleOutcome:
    cutoff = ctx.scheme.rules.cutoff_time_utc
    if cutoff is None:
        return NA
    now_utc = ctx.now.astimezone(UTC).time()
    if now_utc > cutoff:
        return RuleOutcome(
            passed=True,
            message=(
                f"Instruction received after the {cutoff.strftime('%H:%M')} UTC cut-off; "
                "value date will roll to the next business day."
            ),
            field="requestedExecutionDate",
            actual_value=now_utc.strftime("%H:%M UTC"),
            expected_value=f"before {cutoff.strftime('%H:%M')} UTC for same-day value",
            severity_override=Severity.WARNING,
        )
    return RuleOutcome(
        passed=True,
        message=f"Instruction received before the {cutoff.strftime('%H:%M')} UTC cut-off.",
        field="requestedExecutionDate",
        actual_value=now_utc.strftime("%H:%M UTC"),
    )


def _eval_swift_uetr(ctx: ValidationContext) -> RuleOutcome:
    uetr = ctx.payment.uetr or ""
    if not uetr:
        return RuleOutcome(
            passed=False,
            message="UETR is mandatory for cross-border tracking.",
            field="uetr",
            actual_value="<empty>",
            expected_value="a UUID v4 value",
            iso_reason_code="FF01",
        )
    parts = uetr.split("-")
    shape_ok = len(parts) == 5 and [len(x) for x in parts] == [8, 4, 4, 4, 12]
    if not shape_ok or (len(parts[2]) == 4 and parts[2][0] != "4"):
        return RuleOutcome(
            passed=False,
            message="UETR does not have the required UUID version 4 shape.",
            field="uetr",
            actual_value=uetr,
            expected_value="xxxxxxxx-xxxx-4xxx-xxxx-xxxxxxxxxxxx",
            iso_reason_code="FF01",
        )
    return RuleOutcome(passed=True, message="UETR is well formed.", field="uetr", actual_value=uetr)


def _eval_sepa_remittance_structure(ctx: ValidationContext) -> RuleOutcome:
    p = ctx.payment
    if p.remittance_structured and p.remittance_information:
        return RuleOutcome(
            passed=False,
            message=(
                "SEPA allows either structured or unstructured remittance information, not both "
                "in the same instruction."
            ),
            field="remittanceInformation",
            actual_value="both populated",
            expected_value="exactly one of structured / unstructured",
            remediation="Keep the creditor reference in the structured block and clear the free text.",
            iso_reason_code="FF01",
        )
    return RuleOutcome(
        passed=True, message="Remittance information structure is scheme compliant.", field="remittanceInformation"
    )


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------

RULES: tuple[RuleDefinition, ...] = (
    RuleDefinition(
        rule_id="VAL-STRUCT-001",
        name="Mandatory instruction elements present",
        description=(
            "Every credit transfer must carry debtor name, creditor name, amount, currency, "
            "instruction identification and end-to-end identification."
        ),
        category=ValidationCategory.TECHNICAL,
        severity=Severity.FATAL,
        stage=StageKey.PRE_VALIDATION,
        evaluator=_eval_struct_mandatory,
        failure_behaviour="Reject before any downstream processing",
        iso_reason_code="FF01",
        rationale="A structurally incomplete instruction cannot be mapped to a pacs.008 message.",
        standard_basis="ISO 20022 pacs.008 message definition — mandatory elements.",
    ),
    RuleDefinition(
        rule_id="VAL-AMOUNT-001",
        name="Instructed amount must be positive",
        description="The instructed amount must be strictly greater than zero.",
        category=ValidationCategory.BUSINESS,
        severity=Severity.ERROR,
        stage=StageKey.PRE_VALIDATION,
        evaluator=_eval_amount_positive,
        field="amount",
        iso_reason_code="AM01",
        rationale="Zero and negative amounts are not creditable instructions.",
        standard_basis="ISO 20022 ActiveCurrencyAndAmount — amount must be positive.",
    ),
    RuleDefinition(
        rule_id="VAL-AMOUNT-002",
        name="Amount precision matches currency minor units",
        description="The number of decimal places must not exceed the currency's minor-unit digits.",
        category=ValidationCategory.TECHNICAL,
        severity=Severity.ERROR,
        stage=StageKey.PRE_VALIDATION,
        evaluator=_eval_amount_scale,
        field="amount",
        iso_reason_code="AM11",
        rationale="JPY has no minor units; CHF/EUR have two. Excess precision cannot be booked.",
        standard_basis="ISO 4217 currency minor units.",
    ),
    RuleDefinition(
        rule_id="VAL-AMOUNT-003",
        name="Amount within scheme range",
        description="The instructed amount must sit inside the configured minimum and maximum for the rail.",
        category=ValidationCategory.SCHEME,
        severity=Severity.ERROR,
        stage=StageKey.BUSINESS_VALIDATION,
        evaluator=_eval_amount_scheme_limit,
        field="amount",
        iso_reason_code="AM04",
        rationale="Instant rails cap individual transaction values.",
        standard_basis="Scheme configuration (simulator values).",
    ),
    RuleDefinition(
        rule_id="VAL-CCY-001",
        name="Currency is a known ISO 4217 code",
        description="Currency must be a three-letter alphabetic code configured in the simulator.",
        category=ValidationCategory.TECHNICAL,
        severity=Severity.ERROR,
        stage=StageKey.PRE_VALIDATION,
        evaluator=_eval_currency_known,
        field="currency",
        iso_reason_code="AM03",
        rationale="An unknown currency cannot be priced, booked or settled.",
        standard_basis="ISO 4217.",
    ),
    RuleDefinition(
        rule_id="VAL-DBTR-001",
        name="Debtor name present and within Max140Text",
        description="Debtor name is mandatory and limited to 140 characters.",
        category=ValidationCategory.TECHNICAL,
        severity=Severity.ERROR,
        stage=StageKey.PRE_VALIDATION,
        evaluator=_eval_debtor_name,
        field="debtor.name",
        iso_reason_code="FF01",
        standard_basis="ISO 20022 Max140Text.",
    ),
    RuleDefinition(
        rule_id="VAL-DBTR-002",
        name="Debtor account identified",
        description="The debtor account must be identified by IBAN or another account identifier.",
        category=ValidationCategory.ACCOUNT,
        severity=Severity.ERROR,
        stage=StageKey.PRE_VALIDATION,
        evaluator=_eval_debtor_account,
        field="debtor.account",
        iso_reason_code="AC01",
    ),
    RuleDefinition(
        rule_id="VAL-CDTR-001",
        name="Creditor name present and within Max140Text",
        description="Creditor name is mandatory and limited to 140 characters.",
        category=ValidationCategory.TECHNICAL,
        severity=Severity.ERROR,
        stage=StageKey.PRE_VALIDATION,
        evaluator=_eval_creditor_name,
        field="creditor.name",
        iso_reason_code="FF01",
        standard_basis="ISO 20022 Max140Text.",
    ),
    RuleDefinition(
        rule_id="VAL-CDTR-002",
        name="Creditor account identified",
        description="The creditor account must be identified by IBAN or another account identifier.",
        category=ValidationCategory.ACCOUNT,
        severity=Severity.ERROR,
        stage=StageKey.PRE_VALIDATION,
        evaluator=_eval_creditor_account,
        field="creditor.account",
        iso_reason_code="AC01",
    ),
    RuleDefinition(
        rule_id="VAL-BIC-001",
        name="BIC structurally valid",
        description="When a creditor agent BIC is supplied it must satisfy the ISO 9362 structure.",
        category=ValidationCategory.TECHNICAL,
        severity=Severity.ERROR,
        stage=StageKey.PRE_VALIDATION,
        evaluator=_eval_bic_structure,
        field="creditor.bic",
        iso_reason_code="RC01",
        standard_basis="ISO 9362 — 8 or 11 character business identifier code.",
    ),
    RuleDefinition(
        rule_id="VAL-IBAN-001",
        name="Debtor IBAN check digits valid",
        description="Debtor IBAN must pass the ISO 13616 mod-97-10 check and the country length rule.",
        category=ValidationCategory.TECHNICAL,
        severity=Severity.ERROR,
        stage=StageKey.PRE_VALIDATION,
        evaluator=_eval_debtor_iban,
        field="debtor.iban",
        iso_reason_code="AC01",
        standard_basis="ISO 13616 / ISO 7064 mod-97-10.",
    ),
    RuleDefinition(
        rule_id="VAL-IBAN-002",
        name="Creditor IBAN check digits valid",
        description="Creditor IBAN must pass the ISO 13616 mod-97-10 check and the country length rule.",
        category=ValidationCategory.TECHNICAL,
        severity=Severity.ERROR,
        stage=StageKey.PRE_VALIDATION,
        evaluator=_eval_creditor_iban,
        field="creditor.iban",
        iso_reason_code="AC01",
        standard_basis="ISO 13616 / ISO 7064 mod-97-10.",
    ),
    RuleDefinition(
        rule_id="VAL-E2E-001",
        name="EndToEndId present and within Max35Text",
        description="EndToEndId is the customer's reference carried unchanged through the chain.",
        category=ValidationCategory.TECHNICAL,
        severity=Severity.ERROR,
        stage=StageKey.PRE_VALIDATION,
        evaluator=_eval_e2e_format,
        field="endToEndId",
        iso_reason_code="FF01",
        standard_basis="ISO 20022 PaymentIdentification — EndToEndIdentification, Max35Text.",
    ),
    RuleDefinition(
        rule_id="VAL-DUP-001",
        name="Duplicate EndToEndId detection",
        description=(
            "An EndToEndId already seen for the same scheme inside the duplicate window is "
            "treated as a suspected duplicate instruction."
        ),
        category=ValidationCategory.DUPLICATE,
        severity=Severity.ERROR,
        stage=StageKey.BUSINESS_VALIDATION,
        evaluator=_eval_duplicate,
        field="endToEndId",
        failure_behaviour="Reject and refer to the originating channel",
        iso_reason_code="AM05",
        rationale="Duplicate submission is one of the most common causes of customer double debits.",
    ),
    RuleDefinition(
        rule_id="VAL-RMT-001",
        name="Remittance information length",
        description="Unstructured remittance information must respect the scheme character limit.",
        category=ValidationCategory.SCHEME,
        severity=Severity.ERROR,
        stage=StageKey.BUSINESS_VALIDATION,
        evaluator=_eval_remittance_length,
        field="remittanceInformation",
        iso_reason_code="FF01",
        standard_basis="ISO 20022 RemittanceInformation/Ustrd Max140Text.",
    ),
    RuleDefinition(
        rule_id="VAL-DATE-001",
        name="Requested execution date acceptable",
        description="The execution date must not be in the past, nor beyond the rail's warehousing horizon.",
        category=ValidationCategory.BUSINESS,
        severity=Severity.ERROR,
        stage=StageKey.BUSINESS_VALIDATION,
        evaluator=_eval_execution_date,
        field="requestedExecutionDate",
        iso_reason_code="DT01",
    ),
    RuleDefinition(
        rule_id="VAL-ACCT-001",
        name="Debtor account exists and is active",
        description="The debtor account must exist on the bank's book and be open for debits.",
        category=ValidationCategory.ACCOUNT,
        severity=Severity.ERROR,
        stage=StageKey.BUSINESS_VALIDATION,
        evaluator=_eval_debtor_account_exists,
        field="debtor.account",
        iso_reason_code="AC01",
    ),
    RuleDefinition(
        rule_id="VAL-ACCT-002",
        name="Sufficient available funds",
        description="Available balance plus agreed overdraft must cover the instructed amount.",
        category=ValidationCategory.ACCOUNT,
        severity=Severity.ERROR,
        stage=StageKey.BUSINESS_VALIDATION,
        evaluator=_eval_debtor_funds,
        field="amount",
        failure_behaviour="Reject with insufficient funds",
        iso_reason_code="AM04",
    ),
    RuleDefinition(
        rule_id="VAL-MSG-001",
        name="pacs.008 mandatory element coverage",
        description="The generated message must populate every mandatory group-header and transaction element.",
        category=ValidationCategory.MESSAGE,
        severity=Severity.FATAL,
        stage=StageKey.MESSAGE_GENERATION,
        evaluator=_eval_msg_group_header,
        applies_to=("pacs.008",),
        iso_reason_code="FF01",
        standard_basis="ISO 20022 pacs.008.001.08 message definition.",
    ),
    RuleDefinition(
        rule_id="VAL-MSG-002",
        name="Instructed and settlement amount consistency",
        description="InstdAmt and IntrBkSttlmAmt must agree unless charges or FX explain the difference.",
        category=ValidationCategory.MESSAGE,
        severity=Severity.ERROR,
        stage=StageKey.MESSAGE_GENERATION,
        evaluator=_eval_msg_amount_consistency,
        applies_to=("pacs.008",),
        iso_reason_code="AM09",
    ),
    # --- SIC -----------------------------------------------------------
    RuleDefinition(
        rule_id="SIC-AMOUNT-001",
        name="SIC Instant amount ceiling",
        description="Payment amount must not exceed the configured SIC Instant transaction ceiling.",
        category=ValidationCategory.SCHEME,
        severity=Severity.ERROR,
        stage=StageKey.BUSINESS_VALIDATION,
        evaluator=_eval_amount_scheme_limit,
        schemes=("SIC_INSTANT",),
        field="amount",
        iso_reason_code="AM04",
        parameters={"maxAmount": "20000.00", "currency": "CHF"},
        rationale="Instant rails cap per-transaction value to contain settlement risk.",
        standard_basis="SIMULATED: a plausible ceiling, not the live SIC rulebook value.",
    ),
    RuleDefinition(
        rule_id="SIC-CCY-001",
        name="SIC Instant settles CHF only",
        description="Only CHF may be cleared on the domestic Swiss instant rail.",
        category=ValidationCategory.SCHEME,
        severity=Severity.ERROR,
        stage=StageKey.BUSINESS_VALIDATION,
        evaluator=_eval_scheme_currency,
        schemes=("SIC_INSTANT",),
        field="currency",
        iso_reason_code="AM03",
    ),
    RuleDefinition(
        rule_id="SIC-COUNTRY-001",
        name="SIC Instant domestic reach",
        description="Both parties must be located in the domestic scheme area (CH/LI).",
        category=ValidationCategory.SCHEME,
        severity=Severity.ERROR,
        stage=StageKey.BUSINESS_VALIDATION,
        evaluator=_eval_sic_country,
        schemes=("SIC_INSTANT",),
        field="creditor.country",
        iso_reason_code="RR04",
    ),
    # --- SEPA ----------------------------------------------------------
    RuleDefinition(
        rule_id="SEPA-AMOUNT-001",
        name="SEPA Instant amount ceiling",
        description="Payment amount must not exceed the configured SCT Inst maximum.",
        category=ValidationCategory.SCHEME,
        severity=Severity.ERROR,
        stage=StageKey.BUSINESS_VALIDATION,
        evaluator=_eval_amount_scheme_limit,
        schemes=("SEPA_INSTANT",),
        field="amount",
        iso_reason_code="AM02",
        parameters={"maxAmount": "100000.00", "currency": "EUR"},
        standard_basis="SIMULATED: SCT Inst maximum amounts have changed across rulebook versions.",
    ),
    RuleDefinition(
        rule_id="SEPA-CCY-001",
        name="SEPA Instant is euro only",
        description="Only EUR may be cleared on the SEPA instant rail.",
        category=ValidationCategory.SCHEME,
        severity=Severity.ERROR,
        stage=StageKey.BUSINESS_VALIDATION,
        evaluator=_eval_scheme_currency,
        schemes=("SEPA_INSTANT",),
        field="currency",
        iso_reason_code="AM03",
    ),
    RuleDefinition(
        rule_id="SEPA-COUNTRY-001",
        name="SEPA reachability",
        description="Debtor and creditor countries must both be inside the SEPA area.",
        category=ValidationCategory.SCHEME,
        severity=Severity.ERROR,
        stage=StageKey.BUSINESS_VALIDATION,
        evaluator=_eval_sepa_country,
        schemes=("SEPA_INSTANT",),
        field="creditor.country",
        iso_reason_code="RR04",
    ),
    RuleDefinition(
        rule_id="SEPA-RMT-001",
        name="Structured or unstructured remittance, not both",
        description="SEPA permits either structured or unstructured remittance information.",
        category=ValidationCategory.SCHEME,
        severity=Severity.ERROR,
        stage=StageKey.BUSINESS_VALIDATION,
        evaluator=_eval_sepa_remittance_structure,
        schemes=("SEPA_INSTANT",),
        field="remittanceInformation",
        iso_reason_code="FF01",
    ),
    # --- SWIFT ---------------------------------------------------------
    RuleDefinition(
        rule_id="SWIFT-BIC-001",
        name="Creditor agent BIC mandatory cross-border",
        description="Cross-border routing requires the creditor agent BIC.",
        category=ValidationCategory.SCHEME,
        severity=Severity.ERROR,
        stage=StageKey.BUSINESS_VALIDATION,
        evaluator=_eval_swift_bic_required,
        schemes=("SWIFT_CROSS_BORDER",),
        field="creditor.bic",
        iso_reason_code="RC01",
    ),
    RuleDefinition(
        rule_id="SWIFT-ADDR-001",
        name="Creditor address required cross-border",
        description="Cross-border payments require creditor country and a town or address line.",
        category=ValidationCategory.COMPLIANCE,
        severity=Severity.ERROR,
        stage=StageKey.BUSINESS_VALIDATION,
        evaluator=_eval_swift_address,
        schemes=("SWIFT_CROSS_BORDER",),
        field="creditor.address",
        iso_reason_code="FF01",
        rationale="Party transparency is a standing expectation for cross-border transfers.",
        standard_basis="SIMULATED simplification of cross-border party-data expectations.",
    ),
    RuleDefinition(
        rule_id="SWIFT-CCY-001",
        name="Cross-border currency supported",
        description="The instructed currency must be one the correspondent network supports.",
        category=ValidationCategory.SCHEME,
        severity=Severity.ERROR,
        stage=StageKey.BUSINESS_VALIDATION,
        evaluator=_eval_scheme_currency,
        schemes=("SWIFT_CROSS_BORDER",),
        field="currency",
        iso_reason_code="AM03",
    ),
    RuleDefinition(
        rule_id="SWIFT-CUTOFF-001",
        name="Currency cut-off time",
        description="Instructions received after the cut-off take the next business day's value date.",
        category=ValidationCategory.BUSINESS,
        severity=Severity.WARNING,
        stage=StageKey.BUSINESS_VALIDATION,
        evaluator=_eval_swift_cutoff,
        schemes=("SWIFT_CROSS_BORDER",),
        field="requestedExecutionDate",
        failure_behaviour="Warn and roll the value date",
    ),
    RuleDefinition(
        rule_id="SWIFT-UETR-001",
        name="UETR present and well formed",
        description="A UUID v4 UETR must accompany every cross-border instruction for tracking.",
        category=ValidationCategory.TECHNICAL,
        severity=Severity.ERROR,
        stage=StageKey.PRE_VALIDATION,
        evaluator=_eval_swift_uetr,
        schemes=("SWIFT_CROSS_BORDER",),
        field="uetr",
        iso_reason_code="FF01",
        standard_basis="RFC 4122 version 4 UUID, as used for the SWIFT UETR.",
    ),
)

RULES_BY_ID: dict[str, RuleDefinition] = {rule.rule_id: rule for rule in RULES}


def rules_for_scheme(scheme_code: str, rule_ids: tuple[str, ...]) -> list[RuleDefinition]:
    """Resolve the ordered rule set for a scheme, respecting scheme restrictions."""
    resolved: list[RuleDefinition] = []
    for rule_id in rule_ids:
        rule = RULES_BY_ID.get(rule_id)
        if rule is None:
            continue
        if rule.schemes and scheme_code not in rule.schemes:
            continue
        resolved.append(rule)
    return resolved


def utc_now() -> datetime:
    return datetime.now(UTC)
