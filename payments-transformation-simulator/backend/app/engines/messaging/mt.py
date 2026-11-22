"""Legacy MT103 generation and MT to MX mapping.

Why this exists
---------------
Cross-border payment transformation programmes spend a great deal of effort on
the MT to MX transition. The mapping below is an educational comparison: it
distinguishes DIRECT mappings, TRANSFORMED mappings, DERIVED values and fields
with NO direct equivalent.

DOMAIN ACCURACY: there is no universal one-to-one MT to MX mapping. The
authoritative translation rules are the CBPR+ usage guidelines and the published
translation rules; several MT fields are structurally richer or poorer than their
MX counterparts. Nothing here should be used as an implementation specification.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.core.identifiers import utcnow
from app.db.models import Payment
from app.domain.enums import MESSAGE_METADATA, MessageType
from app.domain.money import scale_for
from app.engines.messaging.pacs import OUR_BANK_BIC, BuiltMessage
from app.schemes.base import PaymentScheme


def _mt_amount(amount, currency: str) -> str:
    """MT amounts use a comma decimal separator and no thousands separator."""
    digits = scale_for(currency)
    text = f"{amount:.{digits}f}"
    return text.replace(".", ",")


def build_mt103(payment: Payment, scheme: PaymentScheme, message_id: str) -> BuiltMessage:
    meta = MESSAGE_METADATA[MessageType.MT_103]
    debtor = payment.debtor
    creditor = payment.creditor
    settle_date: date = scheme.value_date()
    value_date = settle_date.strftime("%y%m%d")
    charges = {"DEBT": "OUR", "CRED": "BEN", "SHAR": "SHA", "SLEV": "SHA"}.get(
        payment.charge_bearer or "SHAR", "SHA"
    )

    debtor_lines = [f"/{debtor.iban or debtor.account_identifier}" if debtor else "/NOTPROVIDED"]
    if debtor:
        debtor_lines.append(debtor.name[:35])
        for line in list(debtor.address_lines or [])[:2]:
            debtor_lines.append(line[:35])
        if debtor.town or debtor.country:
            debtor_lines.append(f"{debtor.town} {debtor.country}".strip()[:35])

    creditor_lines = [f"/{creditor.iban or creditor.account_identifier}" if creditor else "/NOTPROVIDED"]
    if creditor:
        creditor_lines.append(creditor.name[:35])
        for line in list(creditor.address_lines or [])[:2]:
            creditor_lines.append(line[:35])
        if creditor.town or creditor.country:
            creditor_lines.append(f"{creditor.town} {creditor.country}".strip()[:35])

    blocks: list[str] = []
    blocks.append("{1:F01" + f"{OUR_BANK_BIC[:8]}AXXX0000000000" + "}")
    blocks.append("{2:I103" + f"{(creditor.bic if creditor and creditor.bic else 'SIMBENKXXXX')[:11]}N" + "}")
    body_lines = [
        f":20:{payment.reference.replace('-', '')[:16]}",
        ":23B:CRED",
        f":32A:{value_date}{payment.currency}{_mt_amount(payment.amount, payment.currency)}",
        f":33B:{payment.currency}{_mt_amount(payment.amount, payment.currency)}",
        ":50K:" + "\n".join(debtor_lines),
    ]
    if creditor and creditor.bic:
        body_lines.append(f":57A:{creditor.bic}")
    body_lines.append(":59:" + "\n".join(creditor_lines))
    if payment.remittance_information:
        body_lines.append(f":70:{payment.remittance_information[:140]}")
    body_lines.append(f":71A:{charges}")
    if payment.purpose_code:
        body_lines.append(f":26T:{payment.purpose_code[:3]}")
    body_lines.append(":72:/INS/" + OUR_BANK_BIC[:11])

    text_block = "{4:\n" + "\n".join(body_lines) + "\n-}"
    blocks.append("{3:{121:" + (payment.uetr or "") + "}}" if payment.uetr else "")
    message = "".join(b for b in blocks if b) + "\n" + text_block + "\n"

    summary = {
        "messageName": meta["name"],
        "isoIdentifier": meta["iso_identifier"],
        "purpose": meta["purpose"],
        "plainEnglish": (
            f"Legacy FIN equivalent of the pacs.008 for payment {payment.reference}. Field :32A "
            f"carries value date {value_date}, currency {payment.currency} and the amount; the "
            "ordering and beneficiary customers are in :50K and :59."
        ),
        "keyFacts": [
            {"label": "Sender's reference (:20)", "value": payment.reference.replace("-", "")[:16]},
            {"label": "Value date / currency / amount (:32A)", "value": f"{value_date} {payment.currency} {_mt_amount(payment.amount, payment.currency)}"},
            {"label": "Details of charges (:71A)", "value": charges},
            {"label": "UETR (block 3, field 121)", "value": payment.uetr or "not present"},
        ],
        "simulationNote": (
            "Illustrative FIN text. Real MT103 messages are subject to FIN network validation "
            "rules that are not reproduced here, and the MT standard has been retired for "
            "cross-border interbank payments in favour of ISO 20022."
        ),
    }
    return BuiltMessage(
        message_type=MessageType.MT_103,
        message_id=message_id,
        xml=message,
        business_summary=summary,
        iso_identifier="MT103",
    )


@dataclass(frozen=True, slots=True)
class MtMxMapping:
    mt_tag: str
    mt_name: str
    mx_path: str
    mapping_type: str  # DIRECT | TRANSFORMED | DERIVED | NO_DIRECT_EQUIVALENT
    note: str


MT103_TO_PACS008: tuple[MtMxMapping, ...] = (
    MtMxMapping(
        ":20",
        "Sender's Reference",
        "GrpHdr/MsgId and CdtTrfTxInf/PmtId/InstrId",
        "TRANSFORMED",
        "One MT reference splits across the MX message identification and the instruction "
        "identification; they are not the same concept.",
    ),
    MtMxMapping(
        ":21",
        "Related Reference",
        "CdtTrfTxInf/PmtId/EndToEndId",
        "TRANSFORMED",
        "Where :21 is absent the EndToEndId is often populated with NOTPROVIDED rather than "
        "being left empty.",
    ),
    MtMxMapping(
        ":23B",
        "Bank Operation Code",
        "CdtTrfTxInf/PmtTpInf/SvcLvl/Cd (or omitted)",
        "DERIVED",
        "CRED has no direct MX element; it is implied by the message type and service level.",
    ),
    MtMxMapping(
        ":23E",
        "Instruction Code",
        "CdtTrfTxInf/InstrForNxtAgt/Cd or InstrForCdtrAgt/Cd",
        "TRANSFORMED",
        "Several MT instruction codes map to different MX structures depending on who the "
        "instruction is for.",
    ),
    MtMxMapping(
        ":26T",
        "Transaction Type Code",
        "CdtTrfTxInf/Purp/Cd",
        "TRANSFORMED",
        "Code sets differ: MT uses a 3-character national code, MX uses the ExternalPurpose code set.",
    ),
    MtMxMapping(
        ":32A",
        "Value Date / Currency / Interbank Settled Amount",
        "CdtTrfTxInf/IntrBkSttlmDt + CdtTrfTxInf/IntrBkSttlmAmt (+ @Ccy)",
        "TRANSFORMED",
        "One concatenated MT field becomes three distinct MX elements. The MT comma decimal "
        "separator becomes an XML decimal point.",
    ),
    MtMxMapping(
        ":33B",
        "Currency / Instructed Amount",
        "CdtTrfTxInf/InstdAmt (+ @Ccy)",
        "DIRECT",
        "Present when the instructed amount differs from the settled amount, or for EEA "
        "transparency.",
    ),
    MtMxMapping(
        ":36",
        "Exchange Rate",
        "CdtTrfTxInf/XchgRate",
        "DIRECT",
        "",
    ),
    MtMxMapping(
        ":50A/F/K",
        "Ordering Customer",
        "CdtTrfTxInf/Dbtr (+ DbtrAcct)",
        "TRANSFORMED",
        "Option A carries a BIC, option F structured party data and option K unstructured name "
        "and address. Only option F maps cleanly to the structured MX Dbtr; K requires parsing "
        "free-text address lines.",
    ),
    MtMxMapping(
        ":52A/D",
        "Ordering Institution",
        "CdtTrfTxInf/DbtrAgt",
        "TRANSFORMED",
        "Option D is name and address, which must be fitted into FinInstnId/Nm and PstlAdr.",
    ),
    MtMxMapping(
        ":53A/B/D",
        "Sender's Correspondent",
        "GrpHdr/SttlmInf/SttlmAcct or InstgRmbrsmntAgt",
        "TRANSFORMED",
        "Whether this becomes a settlement account or a reimbursement agent depends on the "
        "settlement method.",
    ),
    MtMxMapping(
        ":54A",
        "Receiver's Correspondent",
        "GrpHdr/SttlmInf/InstdRmbrsmntAgt",
        "TRANSFORMED",
        "",
    ),
    MtMxMapping(
        ":56A/C/D",
        "Intermediary Institution",
        "CdtTrfTxInf/IntrmyAgt1",
        "DIRECT",
        "MX allows up to three intermediary agents; MT103 allows one.",
    ),
    MtMxMapping(
        ":57A/B/C/D",
        "Account With Institution",
        "CdtTrfTxInf/CdtrAgt",
        "TRANSFORMED",
        "The MT option letter determines whether a BIC, a clearing-system member id or a name "
        "and address populates the MX agent.",
    ),
    MtMxMapping(
        ":59/59A/59F",
        "Beneficiary Customer",
        "CdtTrfTxInf/Cdtr (+ CdtrAcct)",
        "TRANSFORMED",
        "The leading /account line becomes CdtrAcct/Id/IBAN or Othr/Id; the remaining lines "
        "become Cdtr/Nm and PstlAdr.",
    ),
    MtMxMapping(
        ":70",
        "Remittance Information",
        "CdtTrfTxInf/RmtInf/Ustrd",
        "DIRECT",
        "MT allows 4 lines of 35 characters; MX allows Max140Text, so line structure is lost.",
    ),
    MtMxMapping(
        ":71A",
        "Details of Charges",
        "CdtTrfTxInf/ChrgBr",
        "TRANSFORMED",
        "OUR becomes DEBT, BEN becomes CRED, SHA becomes SHAR. Instant schemes use SLEV, which "
        "has no MT equivalent.",
    ),
    MtMxMapping(
        ":71F/:71G",
        "Sender's / Receiver's Charges",
        "CdtTrfTxInf/ChrgsInf",
        "TRANSFORMED",
        "MX carries a repeating structured charges block with the charging party.",
    ),
    MtMxMapping(
        ":72",
        "Sender to Receiver Information",
        "CdtTrfTxInf/InstrForNxtAgt/InstrInf (partial)",
        "NO_DIRECT_EQUIVALENT",
        "Free-text :72 codewords are the classic truncation problem in MT to MX translation. "
        "Some codewords map to structured MX elements, many do not.",
    ),
    MtMxMapping(
        ":77B",
        "Regulatory Reporting",
        "CdtTrfTxInf/RgltryRptg",
        "TRANSFORMED",
        "",
    ),
    MtMxMapping(
        "Block 3 {121:}",
        "UETR",
        "CdtTrfTxInf/PmtId/UETR",
        "DIRECT",
        "The UETR was retro-fitted to MT in block 3 and is a first-class element in MX.",
    ),
    MtMxMapping(
        "(none)",
        "No MT equivalent",
        "GrpHdr/NbOfTxs, GrpHdr/SttlmInf/SttlmMtd, CdtTrfTxInf/UltmtDbtr, CdtTrfTxInf/UltmtCdtr",
        "NO_DIRECT_EQUIVALENT",
        "MX adds batch metadata, an explicit settlement method and ultimate parties that MT103 "
        "cannot represent without using :50/:59 or :72 workarounds.",
    ),
)


def mapping_rows(payment: Payment | None = None) -> list[dict]:
    """Serialise the mapping table, optionally with this payment's actual values."""
    rows: list[dict] = []
    values = _payment_values(payment) if payment else {}
    for mapping in MT103_TO_PACS008:
        rows.append(
            {
                "mtTag": mapping.mt_tag,
                "mtName": mapping.mt_name,
                "mxPath": mapping.mx_path,
                "mappingType": mapping.mapping_type,
                "note": mapping.note,
                "mtValue": values.get(mapping.mt_tag, {}).get("mt"),
                "mxValue": values.get(mapping.mt_tag, {}).get("mx"),
            }
        )
    return rows


def _payment_values(payment: Payment) -> dict[str, dict[str, str | None]]:
    debtor = payment.debtor
    creditor = payment.creditor
    value_date = utcnow().date().strftime("%y%m%d")
    amount_mt = _mt_amount(payment.amount, payment.currency)
    return {
        ":20": {"mt": payment.reference.replace("-", "")[:16], "mx": payment.instruction_id},
        ":21": {"mt": "NOTPROVIDED", "mx": payment.end_to_end_id},
        ":23B": {"mt": "CRED", "mx": payment.service_level or "(derived)"},
        ":26T": {"mt": payment.purpose_code, "mx": payment.purpose_code},
        ":32A": {
            "mt": f"{value_date}{payment.currency}{amount_mt}",
            "mx": f"{payment.amount} {payment.currency} / {utcnow().date().isoformat()}",
        },
        ":33B": {"mt": f"{payment.currency}{amount_mt}", "mx": f"{payment.amount} {payment.currency}"},
        ":50A/F/K": {
            "mt": f"/{(debtor.iban or debtor.account_identifier) if debtor else ''} {debtor.name if debtor else ''}".strip(),
            "mx": debtor.name if debtor else None,
        },
        ":52A/D": {"mt": debtor.bic if debtor else None, "mx": debtor.bic if debtor else None},
        ":57A/B/C/D": {"mt": creditor.bic if creditor else None, "mx": creditor.bic if creditor else None},
        ":59/59A/59F": {
            "mt": f"/{(creditor.iban or creditor.account_identifier) if creditor else ''} {creditor.name if creditor else ''}".strip(),
            "mx": creditor.name if creditor else None,
        },
        ":70": {"mt": payment.remittance_information, "mx": payment.remittance_information},
        ":71A": {
            "mt": {"DEBT": "OUR", "CRED": "BEN", "SHAR": "SHA", "SLEV": "SHA"}.get(
                payment.charge_bearer or "SHAR", "SHA"
            ),
            "mx": payment.charge_bearer,
        },
        "Block 3 {121:}": {"mt": payment.uetr, "mx": payment.uetr},
    }
