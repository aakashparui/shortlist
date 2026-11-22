"""camt.* message builders (cash management).

SIMULATED messages: structurally realistic, not XSD-validated, never transmitted.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.core.identifiers import iso_date, iso_datetime, utcnow
from app.db.models import Account, Payment, StatementEntry
from app.domain.enums import MESSAGE_METADATA, MessageType
from app.domain.money import quantize
from app.engines.messaging.pacs import OUR_BANK_BIC, OUR_BANK_NAME, BuiltMessage
from app.engines.messaging.xmlutil import amount, amount_text, document, maybe, serialise, sub
from app.schemes.base import PaymentScheme

CANCELLATION_REASONS: dict[str, str] = {
    "DUPL": "Payment is a duplicate of another payment.",
    "TECH": "Technical problem resulting in an erroneous payment.",
    "FRAD": "Payment is the result of fraudulent activity.",
    "CUST": "Cancellation requested by the customer.",
    "AGNT": "Cancellation requested by the agent.",
    "CUTA": "Cancellation requested because an investigation is pending.",
    "UPAY": "Payment is not justified.",
}

RESOLUTION_STATUS: dict[str, str] = {
    "CNCL": "Cancelled - the cancellation request was accepted and the payment was cancelled.",
    "RJCR": "RejectedCancellationRequest - the cancellation request was rejected.",
    "PDCR": "PendingCancellationRequest - the cancellation request is still being processed.",
    "ACVC": "AcceptedValueDateCorrection - accepted with a value-date correction.",
}


def build_camt056(
    payment: Payment,
    scheme: PaymentScheme,
    message_id: str,
    original_message_id: str,
    *,
    cancellation_reason_code: str = "CUST",
    additional_information: str | None = None,
) -> BuiltMessage:
    meta = MESSAGE_METADATA[MessageType.CAMT_056]
    root = document("urn:iso:std:iso:20022:tech:xsd:camt.056.001.08")
    doc = sub(root, "FIToFIPmtCxlReq")

    assgnmt = sub(doc, "Assgnmt")
    sub(assgnmt, "Id", message_id)
    assgnr = sub(assgnmt, "Assgnr")
    agt = sub(assgnr, "Agt")
    fi = sub(agt, "FinInstnId")
    sub(fi, "BICFI", OUR_BANK_BIC)
    assgne = sub(assgnmt, "Assgne")
    agt2 = sub(assgne, "Agt")
    fi2 = sub(agt2, "FinInstnId")
    sub(fi2, "BICFI", (payment.creditor.bic if payment.creditor else None) or "SIMBENKXXXX")
    sub(assgnmt, "CreDtTm", iso_datetime())

    undrlyg = sub(doc, "Undrlyg")
    tx_inf = sub(undrlyg, "TxInf")
    sub(tx_inf, "CxlId", f"CXL{message_id[-10:]}")
    orgl_grp = sub(tx_inf, "OrgnlGrpInf")
    sub(orgl_grp, "OrgnlMsgId", original_message_id)
    sub(orgl_grp, "OrgnlMsgNmId", "pacs.008.001.08")
    maybe(tx_inf, "OrgnlInstrId", payment.instruction_id)
    sub(tx_inf, "OrgnlEndToEndId", payment.end_to_end_id)
    maybe(tx_inf, "OrgnlTxId", payment.transaction_id)
    if scheme.rules.uses_uetr:
        maybe(tx_inf, "OrgnlUETR", payment.uetr)
    amount(tx_inf, "OrgnlIntrBkSttlmAmt", payment.amount, payment.currency)
    sub(tx_inf, "OrgnlIntrBkSttlmDt", iso_date(scheme.value_date()))
    cxl_rsn = sub(tx_inf, "CxlRsnInf")
    rsn = sub(cxl_rsn, "Rsn")
    sub(rsn, "Cd", cancellation_reason_code)
    sub(
        cxl_rsn,
        "AddtlInf",
        (additional_information or CANCELLATION_REASONS.get(cancellation_reason_code, "Cancellation requested."))[:105],
    )

    xml = serialise(root)
    summary = {
        "messageName": meta["name"],
        "isoIdentifier": meta["iso_identifier"],
        "purpose": meta["purpose"],
        "plainEnglish": (
            f"The bank asks the beneficiary side to cancel payment {payment.reference} "
            f"({amount_text(payment.amount, payment.currency)} {payment.currency}). Reason "
            f"{cancellation_reason_code}: {CANCELLATION_REASONS.get(cancellation_reason_code, '')} "
            "A cancellation request is only a request; the beneficiary bank decides."
        ),
        "keyFacts": [
            {"label": "Cancellation reason", "value": cancellation_reason_code},
            {"label": "Original message identification", "value": original_message_id},
            {"label": "Original end-to-end identification", "value": payment.end_to_end_id},
            {"label": "Amount", "value": f"{amount_text(payment.amount, payment.currency)} {payment.currency}"},
        ],
        "simulationNote": "The simulator always resolves the request with a camt.029.",
    }
    return BuiltMessage(
        message_type=MessageType.CAMT_056,
        message_id=message_id,
        xml=xml,
        business_summary=summary,
        related_message_id=original_message_id,
        reason_code=cancellation_reason_code,
        iso_identifier=meta["iso_identifier"],
    )


def build_camt029(
    payment: Payment,
    scheme: PaymentScheme,
    message_id: str,
    original_message_id: str,
    *,
    resolution_status: str = "CNCL",
    reason_code: str | None = None,
    narrative: str | None = None,
) -> BuiltMessage:
    meta = MESSAGE_METADATA[MessageType.CAMT_029]
    root = document("urn:iso:std:iso:20022:tech:xsd:camt.029.001.09")
    doc = sub(root, "RsltnOfInvstgtn")

    assgnmt = sub(doc, "Assgnmt")
    sub(assgnmt, "Id", message_id)
    assgnr = sub(assgnmt, "Assgnr")
    agt = sub(assgnr, "Agt")
    fi = sub(agt, "FinInstnId")
    sub(fi, "BICFI", (payment.creditor.bic if payment.creditor else None) or "SIMBENKXXXX")
    assgne = sub(assgnmt, "Assgne")
    agt2 = sub(assgne, "Agt")
    fi2 = sub(agt2, "FinInstnId")
    sub(fi2, "BICFI", OUR_BANK_BIC)
    sub(assgnmt, "CreDtTm", iso_datetime())

    sts = sub(doc, "Sts")
    conf = sub(sts, "Conf", resolution_status)  # noqa: F841

    cxl_dtls = sub(doc, "CxlDtls")
    tx_inf = sub(cxl_dtls, "TxInfAndSts")
    sub(tx_inf, "CxlStsId", f"RES{message_id[-10:]}")
    orgl_grp = sub(tx_inf, "OrgnlGrpInf")
    sub(orgl_grp, "OrgnlMsgId", original_message_id)
    sub(orgl_grp, "OrgnlMsgNmId", "camt.056.001.08")
    sub(tx_inf, "OrgnlEndToEndId", payment.end_to_end_id)
    if scheme.rules.uses_uetr:
        maybe(tx_inf, "OrgnlUETR", payment.uetr)
    sts_rsn = sub(tx_inf, "CxlStsRsnInf")
    rsn = sub(sts_rsn, "Rsn")
    sub(rsn, "Cd", reason_code or ("CUST" if resolution_status == "CNCL" else "NARR"))
    if narrative:
        sub(sts_rsn, "AddtlInf", narrative[:105])

    xml = serialise(root)
    summary = {
        "messageName": meta["name"],
        "isoIdentifier": meta["iso_identifier"],
        "purpose": meta["purpose"],
        "plainEnglish": (
            f"The counterparty has answered the investigation on payment {payment.reference}: "
            f"{RESOLUTION_STATUS.get(resolution_status, resolution_status)}"
            + (f" Narrative: {narrative}" if narrative else "")
        ),
        "keyFacts": [
            {"label": "Resolution", "value": resolution_status},
            {"label": "Meaning", "value": RESOLUTION_STATUS.get(resolution_status, "")},
            {"label": "Reason code", "value": reason_code or "n/a"},
            {"label": "Original end-to-end identification", "value": payment.end_to_end_id},
        ],
        "simulationNote": "Investigation responses are generated deterministically by the simulator.",
    }
    return BuiltMessage(
        message_type=MessageType.CAMT_029,
        message_id=message_id,
        xml=xml,
        business_summary=summary,
        related_message_id=original_message_id,
        reason_code=reason_code,
        iso_identifier=meta["iso_identifier"],
    )


def build_camt054(
    payment: Payment,
    scheme: PaymentScheme,
    message_id: str,
    account: Account,
    *,
    side: str,
    entry_amount: Decimal,
    entry_currency: str,
    booking_date: date,
    value_date: date,
    statement_reference: str,
    narrative: str = "",
) -> BuiltMessage:
    meta = MESSAGE_METADATA[MessageType.CAMT_054]
    root = document("urn:iso:std:iso:20022:tech:xsd:camt.054.001.08")
    doc = sub(root, "BkToCstmrDbtCdtNtfctn")

    grp = sub(doc, "GrpHdr")
    sub(grp, "MsgId", message_id)
    sub(grp, "CreDtTm", iso_datetime())

    ntfctn = sub(doc, "Ntfctn")
    sub(ntfctn, "Id", statement_reference)
    sub(ntfctn, "CreDtTm", iso_datetime())
    acct = sub(ntfctn, "Acct")
    acct_id = sub(acct, "Id")
    if account.iban:
        sub(acct_id, "IBAN", account.iban)
    else:
        othr = sub(acct_id, "Othr")
        sub(othr, "Id", account.account_number)
    sub(acct, "Ccy", account.currency)
    svcr = sub(acct, "Svcr")
    fi = sub(svcr, "FinInstnId")
    sub(fi, "BICFI", OUR_BANK_BIC)
    sub(fi, "Nm", OUR_BANK_NAME)

    entry = sub(ntfctn, "Ntry")
    sub(entry, "NtryRef", statement_reference)
    amount(entry, "Amt", entry_amount, entry_currency)
    sub(entry, "CdtDbtInd", "DBIT" if side == "DEBIT" else "CRDT")
    sub(entry, "Sts").append(_code("BOOK"))
    bookg = sub(entry, "BookgDt")
    sub(bookg, "Dt", iso_date(booking_date))
    val = sub(entry, "ValDt")
    sub(val, "Dt", iso_date(value_date))
    btc = sub(entry, "BkTxCd")
    domn = sub(btc, "Domn")
    sub(domn, "Cd", "PMNT")
    fmly = sub(domn, "Fmly")
    sub(fmly, "Cd", "ICDT")
    sub(fmly, "SubFmlyCd", "ESCT")
    dtls = sub(entry, "NtryDtls")
    tx_dtls = sub(dtls, "TxDtls")
    refs = sub(tx_dtls, "Refs")
    sub(refs, "EndToEndId", payment.end_to_end_id)
    maybe(refs, "InstrId", payment.instruction_id)
    maybe(refs, "TxId", payment.transaction_id)
    if scheme.rules.uses_uetr:
        maybe(refs, "UETR", payment.uetr)
    amount(tx_dtls, "Amt", entry_amount, entry_currency)
    if narrative:
        rmt = sub(tx_dtls, "RmtInf")
        sub(rmt, "Ustrd", narrative[:140])

    xml = serialise(root)
    summary = {
        "messageName": meta["name"],
        "isoIdentifier": meta["iso_identifier"],
        "purpose": meta["purpose"],
        "plainEnglish": (
            f"Account {account.account_number} has been "
            f"{'debited' if side == 'DEBIT' else 'credited'} with "
            f"{amount_text(entry_amount, entry_currency)} {entry_currency}, booked "
            f"{iso_date(booking_date)} with value date {iso_date(value_date)}. "
            "Reconciliation matches this notification to the internal payment record."
        ),
        "keyFacts": [
            {"label": "Account", "value": account.account_number},
            {"label": "Entry reference", "value": statement_reference},
            {"label": "Credit/debit indicator", "value": "DBIT" if side == "DEBIT" else "CRDT"},
            {"label": "Amount", "value": f"{amount_text(entry_amount, entry_currency)} {entry_currency}"},
            {"label": "Booking date", "value": iso_date(booking_date)},
            {"label": "Value date", "value": iso_date(value_date)},
            {"label": "End-to-end identification", "value": payment.end_to_end_id},
        ],
        "simulationNote": "Intraday notification generated by the simulated accounting platform.",
    }
    return BuiltMessage(
        message_type=MessageType.CAMT_054,
        message_id=message_id,
        xml=xml,
        business_summary=summary,
        iso_identifier=meta["iso_identifier"],
    )


def build_camt053(
    account: Account,
    message_id: str,
    statement_id: str,
    entries: list[StatementEntry],
    *,
    opening_balance: Decimal,
    closing_balance: Decimal,
    from_date: date,
    to_date: date,
) -> BuiltMessage:
    meta = MESSAGE_METADATA[MessageType.CAMT_053]
    root = document("urn:iso:std:iso:20022:tech:xsd:camt.053.001.08")
    doc = sub(root, "BkToCstmrStmt")

    grp = sub(doc, "GrpHdr")
    sub(grp, "MsgId", message_id)
    sub(grp, "CreDtTm", iso_datetime())

    stmt = sub(doc, "Stmt")
    sub(stmt, "Id", statement_id)
    sub(stmt, "CreDtTm", iso_datetime())
    period = sub(stmt, "FrToDt")
    sub(period, "FrDtTm", iso_datetime(utcnow().replace(hour=0, minute=0, second=0, microsecond=0)))
    sub(period, "ToDtTm", iso_datetime())
    acct = sub(stmt, "Acct")
    acct_id = sub(acct, "Id")
    if account.iban:
        sub(acct_id, "IBAN", account.iban)
    else:
        othr = sub(acct_id, "Othr")
        sub(othr, "Id", account.account_number)
    sub(acct, "Ccy", account.currency)
    maybe(acct, "Nm", account.name)

    for code, value, dt in (
        ("OPBD", opening_balance, from_date),
        ("CLBD", closing_balance, to_date),
    ):
        bal = sub(stmt, "Bal")
        tp = sub(bal, "Tp")
        cd_or = sub(tp, "CdOrPrtry")
        sub(cd_or, "Cd", code)
        amount(bal, "Amt", value, account.currency)
        sub(bal, "CdtDbtInd", "CRDT" if value >= 0 else "DBIT")
        bal_dt = sub(bal, "Dt")
        sub(bal_dt, "Dt", iso_date(dt))

    for item in entries:
        entry = sub(stmt, "Ntry")
        sub(entry, "NtryRef", item.statement_reference)
        amount(entry, "Amt", item.amount, item.currency)
        sub(entry, "CdtDbtInd", "DBIT" if item.side == "DEBIT" else "CRDT")
        sub(entry, "Sts").append(_code("BOOK"))
        bookg = sub(entry, "BookgDt")
        sub(bookg, "Dt", iso_date(item.booking_date or to_date))
        val = sub(entry, "ValDt")
        sub(val, "Dt", iso_date(item.value_date or to_date))
        btc = sub(entry, "BkTxCd")
        prtry = sub(btc, "Prtry")
        sub(prtry, "Cd", item.bank_transaction_code)
        dtls = sub(entry, "NtryDtls")
        tx_dtls = sub(dtls, "TxDtls")
        refs = sub(tx_dtls, "Refs")
        maybe(refs, "EndToEndId", item.end_to_end_id)
        if item.narrative:
            rmt = sub(tx_dtls, "RmtInf")
            sub(rmt, "Ustrd", item.narrative[:140])

    xml = serialise(root)
    total_debits = sum((e.amount for e in entries if e.side == "DEBIT"), Decimal("0"))
    total_credits = sum((e.amount for e in entries if e.side == "CREDIT"), Decimal("0"))
    summary = {
        "messageName": meta["name"],
        "isoIdentifier": meta["iso_identifier"],
        "purpose": meta["purpose"],
        "plainEnglish": (
            f"Statement {statement_id} for account {account.account_number} covering "
            f"{iso_date(from_date)} to {iso_date(to_date)}: {len(entries)} booked entries, "
            f"{amount_text(total_debits, account.currency)} debited and "
            f"{amount_text(total_credits, account.currency)} credited. The closing balance is the "
            "figure reconciliation treats as the external source of truth."
        ),
        "keyFacts": [
            {"label": "Statement identification", "value": statement_id},
            {"label": "Account", "value": account.account_number},
            {"label": "Entries", "value": str(len(entries))},
            {"label": "Opening balance", "value": f"{amount_text(opening_balance, account.currency)} {account.currency}"},
            {"label": "Closing balance", "value": f"{amount_text(closing_balance, account.currency)} {account.currency}"},
            {"label": "Total debits", "value": f"{amount_text(total_debits, account.currency)} {account.currency}"},
            {"label": "Total credits", "value": f"{amount_text(total_credits, account.currency)} {account.currency}"},
        ],
        "simulationNote": (
            "Statement assembled from the simulator's own statement-entry table, which the "
            "reconciliation engine treats as if it had been received from the account servicer."
        ),
    }
    return BuiltMessage(
        message_type=MessageType.CAMT_053,
        message_id=message_id,
        xml=xml,
        business_summary=summary,
        iso_identifier=meta["iso_identifier"],
    )


def _code(value: str):  # noqa: ANN201
    from xml.etree import ElementTree as ET

    node = ET.Element("Cd")
    node.text = value
    return node


def normalise_statement_amount(value: Decimal, currency: str) -> Decimal:
    return quantize(value, currency)
