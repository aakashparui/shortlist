"""Message engine: builds, validates and persists ISO 20022 messages."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.identifiers import message_id as new_message_id
from app.core.identifiers import utcnow
from app.core.logging import get_logger
from app.db.models import Account, Payment, PaymentMessage, StatementEntry
from app.domain.enums import (
    MessageDirection,
    MessageState,
    MessageType,
    StageKey,
)
from app.engines.messaging import camt, mt, pacs
from app.engines.messaging.pacs import BuiltMessage
from app.engines.validation.engine import ValidationEngine
from app.schemes.base import PaymentScheme

logger = get_logger(__name__)

_INBOUND = {
    MessageType.PACS_002,
    MessageType.PACS_004,
    MessageType.CAMT_029,
    MessageType.CAMT_053,
    MessageType.CAMT_054,
}


class MessageEngine:
    def __init__(self, session: Session) -> None:
        self.session = session

    # -- persistence helper ---------------------------------------------
    def _persist(
        self,
        payment: Payment,
        built: BuiltMessage,
        *,
        state: MessageState,
        notes: str = "",
        validation_summary: list[dict] | None = None,
        is_malformed: bool = False,
    ) -> PaymentMessage:
        direction = (
            MessageDirection.INBOUND if built.message_type in _INBOUND else MessageDirection.OUTBOUND
        )
        now = utcnow()
        row = PaymentMessage(
            payment_id=payment.id,
            correlation_id=payment.correlation_id,
            message_type=built.message_type.value,
            iso_identifier=built.iso_identifier,
            message_id=built.message_id,
            direction=direction.value,
            state=state.value,
            xml_payload=built.xml,
            business_summary=built.business_summary,
            field_mappings=built.field_mappings,
            validation_summary=validation_summary or [],
            related_message_id=built.related_message_id,
            reason_code=built.reason_code,
            is_malformed=is_malformed,
            created_at=now,
            sent_at=now if direction == MessageDirection.OUTBOUND and state != MessageState.GENERATED else None,
            received_at=now if direction == MessageDirection.INBOUND else None,
            notes=notes,
        )
        self.session.add(row)
        self.session.flush()
        logger.info(
            "message persisted",
            extra={
                "message_type": built.message_type.value,
                "message_id": built.message_id,
                "payment_reference": payment.reference,
                "direction": direction.value,
            },
        )
        return row

    # -- pacs.008 -------------------------------------------------------
    def generate_pacs008(
        self,
        payment: Payment,
        scheme: PaymentScheme,
        *,
        settlement_date: date | None = None,
        instructed_amount: Decimal | None = None,
        malform: bool = False,
        validation_engine: ValidationEngine | None = None,
    ) -> tuple[PaymentMessage, list[dict]]:
        msg_id = new_message_id(MessageType.PACS_008.value)
        built = pacs.build_pacs008(
            payment,
            scheme,
            msg_id,
            settlement_date=settlement_date,
            instructed_amount=instructed_amount,
            malform=malform,
        )
        summary: list[dict] = []
        if validation_engine is not None:
            run = validation_engine.run(
                payment,
                scheme,
                StageKey.MESSAGE_GENERATION,
                extras={
                    "message_id": msg_id,
                    "instructed_amount": instructed_amount if instructed_amount is not None else payment.amount,
                    "settlement_amount": payment.amount,
                },
            )
            summary = [
                {
                    "ruleId": r.rule_id,
                    "ruleName": r.rule_name,
                    "status": r.status,
                    "severity": r.severity,
                    "message": r.message,
                    "field": r.field,
                }
                for r in run.results
            ]
        summary.extend(_field_presence_summary(built))
        row = self._persist(
            payment,
            built,
            state=MessageState.GENERATED,
            validation_summary=summary,
            is_malformed=malform,
            notes="Malformed on purpose by failure injection." if malform else "",
        )
        return row, summary

    def mark_sent(self, message: PaymentMessage) -> None:
        message.state = MessageState.SENT.value
        message.sent_at = utcnow()
        self.session.flush()

    # -- pacs.002 -------------------------------------------------------
    def receive_pacs002(
        self,
        payment: Payment,
        scheme: PaymentScheme,
        original_message_id: str,
        *,
        accepted: bool,
        reason_code: str | None = None,
        reason_text: str | None = None,
        status_code: str | None = None,
        malform: bool = False,
        clearing_reference: str | None = None,
        duplicate_of: str | None = None,
    ) -> PaymentMessage:
        built = pacs.build_pacs002(
            payment,
            scheme,
            new_message_id(MessageType.PACS_002.value),
            original_message_id,
            accepted=accepted,
            reason_code=reason_code,
            reason_text=reason_text,
            status_code=status_code,
            malform=malform,
            clearing_reference=clearing_reference,
        )
        notes = ""
        if malform:
            notes = (
                "Malformed response: OrgnlEndToEndId is absent, so the status report cannot be "
                "matched to the original instruction automatically."
            )
        if duplicate_of:
            notes = f"Duplicate status report; the first response was {duplicate_of}."
        return self._persist(
            payment,
            built,
            state=MessageState.MALFORMED if malform else MessageState.RECEIVED,
            notes=notes,
            is_malformed=malform,
        )

    # -- pacs.004 / pacs.028 / camt -------------------------------------
    def receive_pacs004(
        self,
        payment: Payment,
        scheme: PaymentScheme,
        original_message_id: str,
        *,
        return_reason_code: str = "AC04",
        return_reason_text: str | None = None,
        returned_amount: Decimal | None = None,
        charges: Decimal | None = None,
    ) -> PaymentMessage:
        built = pacs.build_pacs004(
            payment,
            scheme,
            new_message_id(MessageType.PACS_004.value),
            original_message_id,
            return_reason_code=return_reason_code,
            return_reason_text=return_reason_text,
            returned_amount=returned_amount,
            charges=charges,
        )
        return self._persist(payment, built, state=MessageState.RECEIVED)

    def send_pacs028(
        self,
        payment: Payment,
        scheme: PaymentScheme,
        original_message_id: str,
        *,
        elapsed_seconds: float,
        threshold_seconds: float,
    ) -> PaymentMessage:
        built = pacs.build_pacs028(
            payment,
            scheme,
            new_message_id(MessageType.PACS_028.value),
            original_message_id,
            elapsed_seconds=elapsed_seconds,
            threshold_seconds=threshold_seconds,
        )
        return self._persist(payment, built, state=MessageState.SENT)

    def send_camt056(
        self,
        payment: Payment,
        scheme: PaymentScheme,
        original_message_id: str,
        *,
        cancellation_reason_code: str = "CUST",
        additional_information: str | None = None,
    ) -> PaymentMessage:
        built = camt.build_camt056(
            payment,
            scheme,
            new_message_id(MessageType.CAMT_056.value),
            original_message_id,
            cancellation_reason_code=cancellation_reason_code,
            additional_information=additional_information,
        )
        return self._persist(payment, built, state=MessageState.SENT)

    def receive_camt029(
        self,
        payment: Payment,
        scheme: PaymentScheme,
        original_message_id: str,
        *,
        resolution_status: str = "CNCL",
        reason_code: str | None = None,
        narrative: str | None = None,
    ) -> PaymentMessage:
        built = camt.build_camt029(
            payment,
            scheme,
            new_message_id(MessageType.CAMT_029.value),
            original_message_id,
            resolution_status=resolution_status,
            reason_code=reason_code,
            narrative=narrative,
        )
        return self._persist(payment, built, state=MessageState.RECEIVED)

    def receive_camt054(
        self,
        payment: Payment,
        scheme: PaymentScheme,
        account: Account,
        *,
        side: str,
        entry_amount: Decimal,
        entry_currency: str,
        booking_date: date,
        value_date: date,
        statement_reference: str,
        narrative: str = "",
    ) -> PaymentMessage:
        built = camt.build_camt054(
            payment,
            scheme,
            new_message_id(MessageType.CAMT_054.value),
            account,
            side=side,
            entry_amount=entry_amount,
            entry_currency=entry_currency,
            booking_date=booking_date,
            value_date=value_date,
            statement_reference=statement_reference,
            narrative=narrative,
        )
        return self._persist(payment, built, state=MessageState.RECEIVED)

    def build_camt053(
        self,
        account: Account,
        entries: list[StatementEntry],
        *,
        opening_balance: Decimal,
        closing_balance: Decimal,
        from_date: date,
        to_date: date,
    ) -> BuiltMessage:
        return camt.build_camt053(
            account,
            new_message_id(MessageType.CAMT_053.value),
            f"STMT-{account.account_number}-{to_date.isoformat()}",
            entries,
            opening_balance=opening_balance,
            closing_balance=closing_balance,
            from_date=from_date,
            to_date=to_date,
        )

    def generate_mt103(self, payment: Payment, scheme: PaymentScheme) -> PaymentMessage:
        built = mt.build_mt103(payment, scheme, new_message_id("MT103"))
        return self._persist(
            payment,
            built,
            state=MessageState.GENERATED,
            notes="Legacy equivalent generated for MT to MX comparison. Not dispatched.",
        )

    # -- lookups --------------------------------------------------------
    def latest(self, payment_id: int, message_type: MessageType) -> PaymentMessage | None:
        return self.session.execute(
            select(PaymentMessage)
            .where(
                PaymentMessage.payment_id == payment_id,
                PaymentMessage.message_type == message_type.value,
            )
            .order_by(PaymentMessage.created_at.desc(), PaymentMessage.id.desc())
            .limit(1)
        ).scalar_one_or_none()

    def all_for_payment(self, payment_id: int) -> list[PaymentMessage]:
        return list(
            self.session.execute(
                select(PaymentMessage)
                .where(PaymentMessage.payment_id == payment_id)
                .order_by(PaymentMessage.created_at.asc(), PaymentMessage.id.asc())
            ).scalars()
        )


# (label, candidate element paths, severity). A check passes when ANY candidate
# is populated, which is how ISO 20022 "choice" elements such as
# CdtrAcct/Id/IBAN or CdtrAcct/Id/Othr/Id actually behave.
_PACS008_FIELD_CHECKS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("Message identification", ("GrpHdr/MsgId",), "ERROR"),
    ("Creation date time", ("GrpHdr/CreDtTm",), "ERROR"),
    ("Number of transactions", ("GrpHdr/NbOfTxs",), "ERROR"),
    ("Settlement method", ("GrpHdr/SttlmInf/SttlmMtd",), "ERROR"),
    ("Total interbank settlement amount", ("GrpHdr/TtlIntrBkSttlmAmt",), "ERROR"),
    ("End-to-end identification", ("CdtTrfTxInf/PmtId/EndToEndId",), "ERROR"),
    ("Interbank settlement amount", ("CdtTrfTxInf/IntrBkSttlmAmt",), "ERROR"),
    ("Settlement currency", ("CdtTrfTxInf/IntrBkSttlmAmt/@Ccy",), "ERROR"),
    ("Interbank settlement date", ("CdtTrfTxInf/IntrBkSttlmDt",), "ERROR"),
    ("Charge bearer", ("CdtTrfTxInf/ChrgBr",), "ERROR"),
    ("Debtor name", ("CdtTrfTxInf/Dbtr/Nm",), "ERROR"),
    (
        "Debtor account identification",
        ("CdtTrfTxInf/DbtrAcct/Id/IBAN", "CdtTrfTxInf/DbtrAcct/Id/Othr/Id"),
        "ERROR",
    ),
    ("Debtor agent BIC", ("CdtTrfTxInf/DbtrAgt/FinInstnId/BICFI",), "ERROR"),
    ("Creditor name", ("CdtTrfTxInf/Cdtr/Nm",), "ERROR"),
    (
        "Creditor account identification",
        ("CdtTrfTxInf/CdtrAcct/Id/IBAN", "CdtTrfTxInf/CdtrAcct/Id/Othr/Id"),
        "ERROR",
    ),
    (
        "Creditor agent identification",
        ("CdtTrfTxInf/CdtrAgt/FinInstnId/BICFI", "CdtTrfTxInf/CdtrAgt/FinInstnId/Nm"),
        "WARNING",
    ),
    (
        "Remittance information",
        ("CdtTrfTxInf/RmtInf/Ustrd", "CdtTrfTxInf/RmtInf/Strd/CdtrRefInf/Ref"),
        "WARNING",
    ),
)


def _field_presence_summary(built: BuiltMessage) -> list[dict]:
    """Per-field 'is it populated in the generated XML?' view."""
    if not built.paths:
        return []
    out: list[dict] = []
    prefix = "FIToFICstmrCdtTrf/"
    for label, candidates, severity in _PACS008_FIELD_CHECKS:
        found_path: str | None = None
        found_value: str | None = None
        for candidate in candidates:
            value = built.paths.get(prefix + candidate)
            if value:
                found_path, found_value = candidate, value
                break
        expected = " or ".join(candidates)
        out.append(
            {
                "ruleId": f"MSG-FIELD/{candidates[0]}",
                "ruleName": f"{label} populated",
                "status": "PASSED" if found_value else "FAILED",
                "severity": severity,
                "message": (
                    f"{prefix}{found_path} = '{found_value}'"
                    if found_value
                    else f"Absent from the generated message: {expected}"
                ),
                "field": found_path or candidates[0],
            }
        )
    return out
