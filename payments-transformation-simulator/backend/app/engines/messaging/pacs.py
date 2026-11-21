"""pacs.* message builders.

Structurally realistic ISO 20022 payment-clearing-and-settlement messages. These
are SIMULATED messages: they are not schema-validated against the official XSDs
and are never transmitted to a real network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.core.identifiers import iso_date, iso_datetime, utcnow
from app.db.models import Payment
from app.domain.enums import MESSAGE_METADATA, MessageType
from app.engines.messaging.xmlutil import (
    account,
    agent,
    amount,
    amount_text,
    document,
    maybe,
    party,
    serialise,
    sub,
)
from app.schemes.base import PaymentScheme

# Our own institution in the simulated world.
OUR_BANK_BIC = "SIMUCHZZXXX"
OUR_BANK_NAME = "Simulator Bank AG (fictional)"
OUR_BANK_COUNTRY = "CH"


@dataclass(slots=True)
class BuiltMessage:
    message_type: MessageType
    message_id: str
    xml: str
    business_summary: dict
    field_mappings: list[dict] = field(default_factory=list)
    related_message_id: str | None = None
    reason_code: str | None = None
    iso_identifier: str = ""
    paths: dict[str, str] = field(default_factory=dict)


def _debtor_agent(payment: Payment) -> tuple[str, str, str]:
    debtor = payment.debtor
    bic = (debtor.bic if debtor else None) or OUR_BANK_BIC
    name = (debtor.bank_name if debtor else None) or OUR_BANK_NAME
    country = (debtor.country if debtor else None) or OUR_BANK_COUNTRY
    return bic, name, country


def _creditor_agent(payment: Payment) -> tuple[str | None, str, str]:
    creditor = payment.creditor
    bic = (creditor.bic if creditor else None) or None
    name = (creditor.bank_name if creditor else None) or "Beneficiary bank (fictional)"
    country = (creditor.country if creditor else None) or ""
    return bic, name, country


# ---------------------------------------------------------------------------
# pacs.008 — FIToFICustomerCreditTransfer
# ---------------------------------------------------------------------------


def build_pacs008(
    payment: Payment,
    scheme: PaymentScheme,
    message_id: str,
    *,
    settlement_date: date | None = None,
    instructed_amount: Decimal | None = None,
    malform: bool = False,
) -> BuiltMessage:
    meta = MESSAGE_METADATA[MessageType.PACS_008]
    root = document(scheme.messages.pacs008_namespace)
    doc = sub(root, "FIToFICstmrCdtTrf")

    created = utcnow()
    settle_date = settlement_date or scheme.value_date()
    instructed = instructed_amount if instructed_amount is not None else payment.amount

    # --- group header ---
    grp = sub(doc, "GrpHdr")
    sub(grp, "MsgId", message_id)
    sub(grp, "CreDtTm", iso_datetime(created))
    sub(grp, "NbOfTxs", "1")
    amount(grp, "TtlIntrBkSttlmAmt", payment.amount, payment.currency)
    sub(grp, "IntrBkSttlmDt", iso_date(settle_date))
    sttlm = sub(grp, "SttlmInf")
    if not malform:
        sub(sttlm, "SttlmMtd", scheme.messages.settlement_method)
    if scheme.messages.clearing_system_proprietary:
        clr = sub(sttlm, "ClrSys")
        sub(clr, "Prtry", scheme.messages.clearing_system_proprietary)
    if payment.settlement_account and scheme.settlement.settlement_method != "CLRG":
        sttlm_acct = sub(sttlm, "SttlmAcct")
        acct_id = sub(sttlm_acct, "Id")
        othr = sub(acct_id, "Othr")
        sub(othr, "Id", payment.settlement_account.account_number)
    instg = sub(grp, "InstgAgt")
    agent_bic, agent_name, agent_country = _debtor_agent(payment)
    fi = sub(instg, "FinInstnId")
    sub(fi, "BICFI", agent_bic)
    cdt_bic, cdt_bank_name, cdt_country = _creditor_agent(payment)
    if cdt_bic:
        instd = sub(grp, "InstdAgt")
        fi2 = sub(instd, "FinInstnId")
        sub(fi2, "BICFI", cdt_bic)

    # --- transaction ---
    txn = sub(doc, "CdtTrfTxInf")
    pmt_id = sub(txn, "PmtId")
    maybe(pmt_id, "InstrId", payment.instruction_id)
    if not malform:
        sub(pmt_id, "EndToEndId", payment.end_to_end_id)
    maybe(pmt_id, "TxId", payment.transaction_id)
    if scheme.rules.uses_uetr:
        maybe(pmt_id, "UETR", payment.uetr)

    pmt_tp = sub(txn, "PmtTpInf")
    maybe(pmt_tp, "InstrPrty", payment.priority)
    if payment.service_level:
        svc = sub(pmt_tp, "SvcLvl")
        sub(svc, "Cd", payment.service_level)
    if payment.local_instrument:
        lcl = sub(pmt_tp, "LclInstrm")
        sub(lcl, "Cd", payment.local_instrument)
    if payment.category_purpose:
        ctgy = sub(pmt_tp, "CtgyPurp")
        sub(ctgy, "Cd", payment.category_purpose)

    amount(txn, "IntrBkSttlmAmt", payment.amount, payment.currency)
    sub(txn, "IntrBkSttlmDt", iso_date(settle_date))
    if instructed is not None:
        amount(txn, "InstdAmt", instructed, payment.currency)
    sub(txn, "ChrgBr", payment.charge_bearer or "SLEV")

    debtor = payment.debtor
    party(
        txn,
        "Dbtr",
        debtor.name if debtor else None,
        country=debtor.country if debtor else None,
        town=debtor.town if debtor else None,
        address_lines=list(debtor.address_lines or []) if debtor else None,
    )
    account(
        txn,
        "DbtrAcct",
        debtor.iban if debtor else None,
        other=debtor.account_identifier if debtor else None,
        currency=payment.debtor_account.currency if payment.debtor_account else None,
    )
    agent(txn, "DbtrAgt", agent_bic, name=agent_name, country=agent_country)

    if cdt_bic or cdt_bank_name:
        agent(txn, "CdtrAgt", cdt_bic, name=cdt_bank_name, country=cdt_country or None)

    creditor = payment.creditor
    party(
        txn,
        "Cdtr",
        creditor.name if creditor else None,
        country=creditor.country if creditor else None,
        town=creditor.town if creditor else None,
        address_lines=list(creditor.address_lines or []) if creditor else None,
    )
    account(
        txn,
        "CdtrAcct",
        creditor.iban if creditor else None,
        other=creditor.account_identifier if creditor else None,
    )

    if payment.purpose_code:
        purp = sub(txn, "Purp")
        sub(purp, "Cd", payment.purpose_code)

    if payment.remittance_information or payment.remittance_structured:
        rmt = sub(txn, "RmtInf")
        maybe(rmt, "Ustrd", payment.remittance_information)
        structured = payment.remittance_structured or {}
        if structured:
            strd = sub(rmt, "Strd")
            if structured.get("creditorReference"):
                cdtr_ref = sub(strd, "CdtrRefInf")
                tp = sub(cdtr_ref, "Tp")
                or_node = sub(tp, "CdOrPrtry")
                sub(or_node, "Cd", structured.get("referenceType", "SCOR"))
                sub(cdtr_ref, "Ref", structured["creditorReference"])
            if structured.get("invoiceNumber"):
                rfrd = sub(strd, "RfrdDocInf")
                tp = sub(rfrd, "Tp")
                or_node = sub(tp, "CdOrPrtry")
                sub(or_node, "Cd", "CINV")
                sub(rfrd, "Nb", structured["invoiceNumber"])

    xml = serialise(root)
    summary = {
        "messageName": meta["name"],
        "isoIdentifier": meta["iso_identifier"],
        "purpose": meta["purpose"],
        "plainEnglish": (
            f"{(debtor.name if debtor else 'The debtor')} instructs "
            f"{amount_text(payment.amount, payment.currency)} {payment.currency} to be paid to "
            f"{(creditor.name if creditor else 'the creditor')}. "
            f"{agent_name} asks {cdt_bank_name} to credit the beneficiary, settling via "
            f"{scheme.clearing.clearing_system_name} with value date {iso_date(settle_date)}."
        ),
        "keyFacts": [
            {"label": "Message identification", "value": message_id},
            {"label": "End-to-end identification", "value": payment.end_to_end_id},
            {"label": "Interbank settlement amount", "value": f"{amount_text(payment.amount, payment.currency)} {payment.currency}"},
            {"label": "Interbank settlement date", "value": iso_date(settle_date)},
            {"label": "Settlement method", "value": scheme.messages.settlement_method},
            {"label": "Charge bearer", "value": payment.charge_bearer or "SLEV"},
            {"label": "Debtor agent", "value": f"{agent_name} ({agent_bic})"},
            {"label": "Creditor agent", "value": f"{cdt_bank_name} ({cdt_bic or 'not supplied'})"},
        ],
        "simulationNote": (
            "Generated by the simulator. Structurally realistic but not XSD-validated and "
            "never transmitted to a live network."
        ),
    }
    if scheme.rules.uses_uetr and payment.uetr:
        summary["keyFacts"].append({"label": "UETR", "value": payment.uetr})

    mappings = _pacs008_mappings(payment, scheme, message_id, settle_date, instructed)
    from xml.etree import ElementTree as ET

    from app.engines.messaging.xmlutil import element_paths

    return BuiltMessage(
        message_type=MessageType.PACS_008,
        message_id=message_id,
        xml=xml,
        business_summary=summary,
        field_mappings=mappings,
        iso_identifier=meta["iso_identifier"],
        paths=element_paths(ET.fromstring(xml)),
    )


def _pacs008_mappings(
    payment: Payment,
    scheme: PaymentScheme,
    message_id: str,
    settle_date: date,
    instructed: Decimal | None,
) -> list[dict]:
    debtor = payment.debtor
    creditor = payment.creditor
    rows = [
        ("Payment reference", "reference", "FIToFICstmrCdtTrf/GrpHdr/MsgId", message_id, "DERIVED",
         "The message identification is generated per message, not copied from the payment reference."),
        ("Instruction ID", "instructionId", "CdtTrfTxInf/PmtId/InstrId", payment.instruction_id, "DIRECT", ""),
        ("End-to-end ID", "endToEndId", "CdtTrfTxInf/PmtId/EndToEndId", payment.end_to_end_id, "DIRECT",
         "Carried unchanged along the whole payment chain."),
        ("Transaction ID", "transactionId", "CdtTrfTxInf/PmtId/TxId", payment.transaction_id, "DIRECT", ""),
        ("Amount", "amount", "CdtTrfTxInf/IntrBkSttlmAmt", f"{amount_text(payment.amount, payment.currency)}", "DIRECT", ""),
        ("Currency", "currency", "CdtTrfTxInf/IntrBkSttlmAmt/@Ccy", payment.currency, "DIRECT", ""),
        ("Amount", "amount", "CdtTrfTxInf/InstdAmt",
         amount_text(instructed, payment.currency) if instructed is not None else None, "DIRECT",
         "Equal to the settlement amount when no charges or FX apply."),
        ("Execution date", "requestedExecutionDate", "CdtTrfTxInf/IntrBkSttlmDt", iso_date(settle_date), "TRANSFORMED",
         "The interbank settlement date is derived from the requested execution date and the scheme value-date rule."),
        ("Debtor name", "debtor.name", "CdtTrfTxInf/Dbtr/Nm", debtor.name if debtor else None, "DIRECT", ""),
        ("Debtor IBAN", "debtor.iban", "CdtTrfTxInf/DbtrAcct/Id/IBAN", debtor.iban if debtor else None, "DIRECT", ""),
        ("Debtor country", "debtor.country", "CdtTrfTxInf/Dbtr/PstlAdr/Ctry", debtor.country if debtor else None, "DIRECT", ""),
        ("Debtor bank BIC", "debtor.bic", "CdtTrfTxInf/DbtrAgt/FinInstnId/BICFI", _debtor_agent(payment)[0], "DIRECT", ""),
        ("Creditor name", "creditor.name", "CdtTrfTxInf/Cdtr/Nm", creditor.name if creditor else None, "DIRECT", ""),
        ("Creditor IBAN", "creditor.iban", "CdtTrfTxInf/CdtrAcct/Id/IBAN", creditor.iban if creditor else None, "DIRECT", ""),
        ("Creditor country", "creditor.country", "CdtTrfTxInf/Cdtr/PstlAdr/Ctry", creditor.country if creditor else None, "DIRECT", ""),
        ("Creditor bank BIC", "creditor.bic", "CdtTrfTxInf/CdtrAgt/FinInstnId/BICFI", _creditor_agent(payment)[0], "DIRECT", ""),
        ("Remittance information", "remittanceInformation", "CdtTrfTxInf/RmtInf/Ustrd", payment.remittance_information, "DIRECT", ""),
        ("Purpose code", "purposeCode", "CdtTrfTxInf/Purp/Cd", payment.purpose_code, "DIRECT", ""),
        ("Service level", "serviceLevel", "CdtTrfTxInf/PmtTpInf/SvcLvl/Cd", payment.service_level, "DIRECT", ""),
        ("Clearing channel", "clearingChannel", "GrpHdr/SttlmInf/ClrSys/Prtry",
         scheme.messages.clearing_system_proprietary, "TRANSFORMED",
         "Derived from the selected scheme rather than entered by the user."),
        ("Charge bearer", "chargeBearer", "CdtTrfTxInf/ChrgBr", payment.charge_bearer, "DIRECT", ""),
        ("UETR", "uetr", "CdtTrfTxInf/PmtId/UETR", payment.uetr if scheme.rules.uses_uetr else None,
         "DIRECT" if scheme.rules.uses_uetr else "NO_EQUIVALENT",
         "" if scheme.rules.uses_uetr else "This rail does not carry a UETR."),
    ]
    return [
        {
            "sourceLabel": label,
            "sourceField": source,
            "isoPath": path,
            "value": value,
            "mappingType": mapping_type,
            "note": note,
            "present": value is not None and str(value).strip() != "",
        }
        for label, source, path, value, mapping_type, note in rows
    ]


# ---------------------------------------------------------------------------
# pacs.002 — FIToFIPaymentStatusReport
# ---------------------------------------------------------------------------

STATUS_REASON_TEXT: dict[str, str] = {
    "AM04": "Insufficient funds or amount exceeds the agreed limit at the receiving side.",
    "AM02": "Amount exceeds the scheme maximum permitted for this service.",
    "AM03": "Currency is not supported for this account or service.",
    "AM05": "Duplicate payment detected by the receiving institution.",
    "AM09": "Wrong amount: the amount does not match the underlying obligation.",
    "AC01": "Creditor account number is invalid or missing.",
    "AC04": "Creditor account is closed.",
    "AC06": "Creditor account is blocked.",
    "BE01": "Creditor name and account do not match.",
    "RR04": "Regulatory reason prevents execution.",
    "FF01": "File or transaction format is invalid.",
    "AG01": "Transaction is forbidden on this type of account.",
    "RC01": "Bank identifier is incorrect.",
    "CUST": "Cancelled or rejected at the request of the customer.",
    "NARR": "See the narrative reason text.",
    "TECH": "Technical problem at the receiving institution.",
}


def build_pacs002(
    payment: Payment,
    scheme: PaymentScheme,
    message_id: str,
    original_message_id: str,
    *,
    accepted: bool,
    reason_code: str | None = None,
    reason_text: str | None = None,
    status_code: str | None = None,
    malform: bool = False,
    clearing_reference: str | None = None,
) -> BuiltMessage:
    meta = MESSAGE_METADATA[MessageType.PACS_002]
    root = document(scheme.messages.pacs002_namespace)
    doc = sub(root, "FIToFIPmtStsRpt")

    grp = sub(doc, "GrpHdr")
    sub(grp, "MsgId", message_id)
    sub(grp, "CreDtTm", iso_datetime())
    instg = sub(grp, "InstgAgt")
    fi = sub(instg, "FinInstnId")
    sub(fi, "BICFI", "SIMCLRXXXXX")

    org = sub(doc, "OrgnlGrpInfAndSts")
    sub(org, "OrgnlMsgId", original_message_id)
    sub(org, "OrgnlMsgNmId", "pacs.008.001.08")
    sub(org, "OrgnlCreDtTm", iso_datetime())
    sub(org, "OrgnlNbOfTxs", "1")

    status = status_code or ("ACSC" if accepted else "RJCT")
    txn = sub(doc, "TxInfAndSts")
    sub(txn, "StsId", f"STS{message_id[-10:]}")
    maybe(txn, "OrgnlInstrId", payment.instruction_id)
    if not malform:
        sub(txn, "OrgnlEndToEndId", payment.end_to_end_id)
    maybe(txn, "OrgnlTxId", payment.transaction_id)
    if scheme.rules.uses_uetr:
        maybe(txn, "OrgnlUETR", payment.uetr)
    sub(txn, "TxSts", status)

    if not accepted:
        code = reason_code or "NARR"
        sts_rsn = sub(txn, "StsRsnInf")
        rsn = sub(sts_rsn, "Rsn")
        if code in STATUS_REASON_TEXT and code != "NARR":
            sub(rsn, "Cd", code)
        else:
            sub(rsn, "Prtry", code)
        text = reason_text or STATUS_REASON_TEXT.get(code, "Rejected by the clearing system.")
        sub(sts_rsn, "AddtlInf", text[:105])

    accept_dt = sub(txn, "AccptncDtTm", iso_datetime())  # noqa: F841
    if clearing_reference:
        clr = sub(txn, "ClrSysRef", clearing_reference)  # noqa: F841

    orgl = sub(txn, "OrgnlTxRef")
    amount(orgl, "IntrBkSttlmAmt", payment.amount, payment.currency)
    sub(orgl, "IntrBkSttlmDt", iso_date(scheme.value_date()))

    xml = serialise(root)
    code = reason_code if not accepted else None
    summary = {
        "messageName": meta["name"],
        "isoIdentifier": meta["iso_identifier"],
        "purpose": meta["purpose"],
        "plainEnglish": (
            f"The clearing system reports status '{status}' for payment {payment.reference}. "
            + (
                "The payment was accepted and settlement is complete."
                if accepted
                else f"The payment was rejected with reason {code}: "
                + (reason_text or STATUS_REASON_TEXT.get(code or "", "no further detail."))
            )
        ),
        "keyFacts": [
            {"label": "Transaction status", "value": status},
            {"label": "Original message identification", "value": original_message_id},
            {"label": "Original end-to-end identification", "value": payment.end_to_end_id},
            {"label": "Reason code", "value": code or "n/a"},
            {"label": "Clearing system reference", "value": clearing_reference or "n/a"},
        ],
        "statusMeaning": _status_meaning(status),
        "simulationNote": "Produced by the simulated clearing system, not a real payment system.",
    }
    return BuiltMessage(
        message_type=MessageType.PACS_002,
        message_id=message_id,
        xml=xml,
        business_summary=summary,
        related_message_id=original_message_id,
        reason_code=code,
        iso_identifier=meta["iso_identifier"],
    )


def _status_meaning(status: str) -> str:
    return {
        "ACSC": "AcceptedSettlementCompleted - settlement on the debtor side has been completed.",
        "ACSP": "AcceptedSettlementInProcess - accepted, settlement still in progress.",
        "ACCP": "AcceptedCustomerProfile - preceding checks passed.",
        "ACTC": "AcceptedTechnicalValidation - technical validation passed.",
        "RJCT": "Rejected - the instruction has not been and will not be executed.",
        "PDNG": "Pending - the instruction is awaiting further processing.",
    }.get(status, "Unknown status code.")


# ---------------------------------------------------------------------------
# pacs.004 — PaymentReturn
# ---------------------------------------------------------------------------


def build_pacs004(
    payment: Payment,
    scheme: PaymentScheme,
    message_id: str,
    original_message_id: str,
    *,
    return_reason_code: str = "AC04",
    return_reason_text: str | None = None,
    returned_amount: Decimal | None = None,
    charges: Decimal | None = None,
) -> BuiltMessage:
    meta = MESSAGE_METADATA[MessageType.PACS_004]
    root = document("urn:iso:std:iso:20022:tech:xsd:pacs.004.001.09")
    doc = sub(root, "PmtRtr")

    returned = returned_amount if returned_amount is not None else payment.amount
    grp = sub(doc, "GrpHdr")
    sub(grp, "MsgId", message_id)
    sub(grp, "CreDtTm", iso_datetime())
    sub(grp, "NbOfTxs", "1")
    amount(grp, "TtlRtrdIntrBkSttlmAmt", returned, payment.currency)
    sub(grp, "IntrBkSttlmDt", iso_date(scheme.value_date()))
    sttlm = sub(grp, "SttlmInf")
    sub(sttlm, "SttlmMtd", scheme.messages.settlement_method)

    txn = sub(doc, "TxInf")
    sub(txn, "RtrId", f"RTN{message_id[-10:]}")
    maybe(txn, "OrgnlInstrId", payment.instruction_id)
    sub(txn, "OrgnlEndToEndId", payment.end_to_end_id)
    maybe(txn, "OrgnlTxId", payment.transaction_id)
    if scheme.rules.uses_uetr:
        maybe(txn, "OrgnlUETR", payment.uetr)
    amount(txn, "OrgnlIntrBkSttlmAmt", payment.amount, payment.currency)
    amount(txn, "RtrdIntrBkSttlmAmt", returned, payment.currency)
    sub(txn, "IntrBkSttlmDt", iso_date(scheme.value_date()))
    if charges is not None and charges > 0:
        chrg = sub(txn, "ChrgsInf")
        amount(chrg, "Amt", charges, payment.currency)
        pty = sub(chrg, "Pty")
        fi = sub(pty, "FinInstnId")
        sub(fi, "BICFI", (payment.creditor.bic if payment.creditor else None) or "SIMBENKXXXX")
    rsn = sub(txn, "RtrRsnInf")
    reason = sub(rsn, "Rsn")
    sub(reason, "Cd", return_reason_code)
    sub(rsn, "AddtlInf", (return_reason_text or STATUS_REASON_TEXT.get(return_reason_code, "Returned."))[:105])

    orgl = sub(txn, "OrgnlTxRef")
    debtor = payment.debtor
    creditor = payment.creditor
    party(orgl, "Dbtr", debtor.name if debtor else None)
    party(orgl, "Cdtr", creditor.name if creditor else None)

    xml = serialise(root)
    summary = {
        "messageName": meta["name"],
        "isoIdentifier": meta["iso_identifier"],
        "purpose": meta["purpose"],
        "plainEnglish": (
            f"The beneficiary bank could not apply the funds and is returning "
            f"{amount_text(returned, payment.currency)} {payment.currency} for payment "
            f"{payment.reference}. Return reason {return_reason_code}: "
            + (return_reason_text or STATUS_REASON_TEXT.get(return_reason_code, ""))
        ),
        "keyFacts": [
            {"label": "Return reason", "value": return_reason_code},
            {"label": "Original amount", "value": f"{amount_text(payment.amount, payment.currency)} {payment.currency}"},
            {"label": "Returned amount", "value": f"{amount_text(returned, payment.currency)} {payment.currency}"},
            {"label": "Deducted charges", "value": f"{amount_text(charges or 0, payment.currency)} {payment.currency}"},
            {"label": "Original end-to-end identification", "value": payment.end_to_end_id},
        ],
        "simulationNote": "Return simulated locally; no funds actually move.",
    }
    return BuiltMessage(
        message_type=MessageType.PACS_004,
        message_id=message_id,
        xml=xml,
        business_summary=summary,
        related_message_id=original_message_id,
        reason_code=return_reason_code,
        iso_identifier=meta["iso_identifier"],
    )


# ---------------------------------------------------------------------------
# pacs.028 — FIToFIPaymentStatusRequest (used after a timeout)
# ---------------------------------------------------------------------------


def build_pacs028(
    payment: Payment,
    scheme: PaymentScheme,
    message_id: str,
    original_message_id: str,
    *,
    elapsed_seconds: float,
    threshold_seconds: float,
) -> BuiltMessage:
    meta = MESSAGE_METADATA[MessageType.PACS_028]
    root = document("urn:iso:std:iso:20022:tech:xsd:pacs.028.001.03")
    doc = sub(root, "FIToFIPmtStsReq")

    grp = sub(doc, "GrpHdr")
    sub(grp, "MsgId", message_id)
    sub(grp, "CreDtTm", iso_datetime())
    instg = sub(grp, "InstgAgt")
    fi = sub(instg, "FinInstnId")
    sub(fi, "BICFI", OUR_BANK_BIC)

    org = sub(doc, "OrgnlGrpInf")
    sub(org, "OrgnlMsgId", original_message_id)
    sub(org, "OrgnlMsgNmId", "pacs.008.001.08")

    txn = sub(doc, "TxInf")
    sub(txn, "StsReqId", f"REQ{message_id[-10:]}")
    maybe(txn, "OrgnlInstrId", payment.instruction_id)
    sub(txn, "OrgnlEndToEndId", payment.end_to_end_id)
    maybe(txn, "OrgnlTxId", payment.transaction_id)
    if scheme.rules.uses_uetr:
        maybe(txn, "OrgnlUETR", payment.uetr)
    orgl = sub(txn, "OrgnlTxRef")
    amount(orgl, "IntrBkSttlmAmt", payment.amount, payment.currency)
    sub(orgl, "IntrBkSttlmDt", iso_date(scheme.value_date()))

    xml = serialise(root)
    summary = {
        "messageName": meta["name"],
        "isoIdentifier": meta["iso_identifier"],
        "purpose": meta["purpose"],
        "plainEnglish": (
            f"No status report was received for payment {payment.reference} within "
            f"{threshold_seconds:.0f}s"
            + (
                ". The clearing system did not answer at all. "
                if elapsed_seconds < 0.05
                else f" (waited {elapsed_seconds:.1f}s). "
            )
            + "The bank is asking the clearing system what happened to the instruction before "
            "taking any further action."
        ),
        "keyFacts": [
            {"label": "Original message identification", "value": original_message_id},
            {
                "label": "Waited",
                "value": "no response at all" if elapsed_seconds < 0.05 else f"{elapsed_seconds:.1f} s",
            },
            {"label": "Scheme threshold", "value": f"{threshold_seconds:.0f} s"},
            {"label": "Original end-to-end identification", "value": payment.end_to_end_id},
        ],
        "simulationNote": (
            "Investigation flow is simulated. Real schemes differ in whether a status request, "
            "a cancellation request or a direct operational enquiry is the correct first step."
        ),
    }
    return BuiltMessage(
        message_type=MessageType.PACS_028,
        message_id=message_id,
        xml=xml,
        business_summary=summary,
        related_message_id=original_message_id,
        iso_identifier=meta["iso_identifier"],
    )
