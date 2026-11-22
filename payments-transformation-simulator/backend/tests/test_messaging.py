"""ISO 20022 message generation, field mapping and MT to MX."""

from __future__ import annotations

from decimal import Decimal
from xml.etree import ElementTree as ET

import pytest

from app.api.schemas import PaymentCreate
from app.domain.enums import MESSAGE_METADATA, MessageType, ProcessingMode
from app.engines.messaging import mt
from app.engines.messaging.engine import MessageEngine
from app.engines.messaging.xmlutil import element_paths, local_name
from app.schemes.registry import get_scheme
from app.seed.scenarios import sepa, sic, swift


def _payment(payments, payload):  # noqa: ANN001, ANN202
    return payments.create(PaymentCreate.model_validate({**payload, "processingMode": "IMMEDIATE"}))


def _paths(xml: str) -> dict[str, str]:
    return element_paths(ET.fromstring(xml))


class TestPacs008:
    def test_generated_xml_is_well_formed(self, payments, db_session) -> None:
        payment = _payment(payments, sic("4850.00"))
        row, _ = MessageEngine(db_session).generate_pacs008(payment, get_scheme(payment.scheme))
        root = ET.fromstring(row.xml_payload)
        assert local_name(root.tag) == "Document"
        assert row.xml_payload.startswith('<?xml version="1.0" encoding="UTF-8"?>')

    def test_namespace_is_the_pacs008_namespace(self, payments, db_session) -> None:
        payment = _payment(payments, sic("4850.00"))
        row, _ = MessageEngine(db_session).generate_pacs008(payment, get_scheme(payment.scheme))
        assert "pacs.008.001.08" in row.xml_payload

    def test_mandatory_elements_are_populated(self, payments, db_session) -> None:
        payment = _payment(payments, sic("4850.00"))
        row, _ = MessageEngine(db_session).generate_pacs008(payment, get_scheme(payment.scheme))
        paths = _paths(row.xml_payload)
        prefix = "FIToFICstmrCdtTrf/"
        for path in (
            "GrpHdr/MsgId",
            "GrpHdr/CreDtTm",
            "GrpHdr/NbOfTxs",
            "GrpHdr/SttlmInf/SttlmMtd",
            "CdtTrfTxInf/PmtId/EndToEndId",
            "CdtTrfTxInf/IntrBkSttlmAmt",
            "CdtTrfTxInf/ChrgBr",
            "CdtTrfTxInf/Dbtr/Nm",
            "CdtTrfTxInf/DbtrAcct/Id/IBAN",
            "CdtTrfTxInf/Cdtr/Nm",
            "CdtTrfTxInf/CdtrAcct/Id/IBAN",
        ):
            assert paths.get(prefix + path), f"{path} should be populated"

    def test_amount_and_currency_match_the_instruction(self, payments, db_session) -> None:
        payment = _payment(payments, sic("4850.00"))
        row, _ = MessageEngine(db_session).generate_pacs008(payment, get_scheme(payment.scheme))
        paths = _paths(row.xml_payload)
        assert paths["FIToFICstmrCdtTrf/CdtTrfTxInf/IntrBkSttlmAmt"] == "4850.00"
        assert paths["FIToFICstmrCdtTrf/CdtTrfTxInf/IntrBkSttlmAmt/@Ccy"] == "CHF"

    def test_end_to_end_id_is_carried_unchanged(self, payments, db_session) -> None:
        payment = _payment(payments, sic("4850.00"))
        row, _ = MessageEngine(db_session).generate_pacs008(payment, get_scheme(payment.scheme))
        paths = _paths(row.xml_payload)
        assert paths["FIToFICstmrCdtTrf/CdtTrfTxInf/PmtId/EndToEndId"] == payment.end_to_end_id

    def test_jpy_amount_has_no_decimals(self, payments, db_session) -> None:
        payload = swift("250000", "JPY")
        payload["creditor"]["bic"] = "MARIJPJTXXX"
        payload["creditor"]["country"] = "JP"
        payment = _payment(payments, payload)
        row, _ = MessageEngine(db_session).generate_pacs008(payment, get_scheme(payment.scheme))
        paths = _paths(row.xml_payload)
        assert paths["FIToFICstmrCdtTrf/CdtTrfTxInf/IntrBkSttlmAmt"] == "250000"

    def test_uetr_present_only_for_cross_border(self, payments, db_session) -> None:
        engine = MessageEngine(db_session)
        domestic = _payment(payments, sic("100.00"))
        row, _ = engine.generate_pacs008(domestic, get_scheme(domestic.scheme))
        assert "UETR" not in row.xml_payload

        cross = _payment(payments, swift("100.00"))
        row2, _ = engine.generate_pacs008(cross, get_scheme(cross.scheme))
        paths = _paths(row2.xml_payload)
        assert paths["FIToFICstmrCdtTrf/CdtTrfTxInf/PmtId/UETR"] == cross.uetr

    def test_clearing_system_proprietary_is_derived_from_the_scheme(self, payments, db_session) -> None:
        payment = _payment(payments, sic("100.00"))
        row, _ = MessageEngine(db_session).generate_pacs008(payment, get_scheme(payment.scheme))
        paths = _paths(row.xml_payload)
        assert paths["FIToFICstmrCdtTrf/GrpHdr/SttlmInf/ClrSys/Prtry"] == "SIC-IP"

    def test_empty_optional_elements_are_omitted(self, payments, db_session) -> None:
        payload = sic("100.00")
        payload["purposeCode"] = None
        payload["remittanceInformation"] = ""
        payment = _payment(payments, payload)
        row, _ = MessageEngine(db_session).generate_pacs008(payment, get_scheme(payment.scheme))
        assert "<Purp>" not in row.xml_payload
        assert "<RmtInf>" not in row.xml_payload

    def test_structured_remittance_is_rendered(self, payments, db_session) -> None:
        payload = sic("100.00")
        payload["remittanceInformation"] = ""
        payload["remittanceStructured"] = {"creditorReference": "RF18539007547034", "referenceType": "SCOR"}
        payment = _payment(payments, payload)
        row, _ = MessageEngine(db_session).generate_pacs008(payment, get_scheme(payment.scheme))
        paths = _paths(row.xml_payload)
        assert paths["FIToFICstmrCdtTrf/CdtTrfTxInf/RmtInf/Strd/CdtrRefInf/Ref"] == "RF18539007547034"

    def test_business_summary_explains_the_message(self, payments, db_session) -> None:
        payment = _payment(payments, sic("4850.00"))
        row, _ = MessageEngine(db_session).generate_pacs008(payment, get_scheme(payment.scheme))
        summary = row.business_summary
        assert summary["messageName"] == "FIToFICustomerCreditTransfer"
        assert summary["isoIdentifier"] == "pacs.008.001.08"
        assert payment.creditor.name in summary["plainEnglish"]
        assert summary["keyFacts"]
        assert "simulationNote" in summary

    def test_field_mapping_covers_the_entry_fields(self, payments, db_session) -> None:
        payment = _payment(payments, sic("4850.00"))
        row, _ = MessageEngine(db_session).generate_pacs008(payment, get_scheme(payment.scheme))
        mappings = {m["sourceField"]: m for m in row.field_mappings}
        assert mappings["endToEndId"]["isoPath"] == "CdtTrfTxInf/PmtId/EndToEndId"
        assert mappings["endToEndId"]["mappingType"] == "DIRECT"
        assert mappings["clearingChannel"]["mappingType"] == "TRANSFORMED"
        assert mappings["creditor.iban"]["value"] == payment.creditor.iban
        assert all("present" in m for m in row.field_mappings)

    def test_malformed_generation_omits_the_end_to_end_id(self, payments, db_session) -> None:
        payment = _payment(payments, sic("100.00"))
        row, summary = MessageEngine(db_session).generate_pacs008(
            payment, get_scheme(payment.scheme), malform=True
        )
        assert "EndToEndId" not in row.xml_payload
        failures = [s for s in summary if s["status"] == "FAILED"]
        assert failures


class TestPacs002:
    def test_positive_status_report(self, payments, db_session) -> None:
        payment = _payment(payments, sic("100.00"))
        engine = MessageEngine(db_session)
        original, _ = engine.generate_pacs008(payment, get_scheme(payment.scheme))
        row = engine.receive_pacs002(
            payment, get_scheme(payment.scheme), original.message_id, accepted=True
        )
        paths = _paths(row.xml_payload)
        assert paths["FIToFIPmtStsRpt/TxInfAndSts/TxSts"] == "ACSC"
        assert paths["FIToFIPmtStsRpt/OrgnlGrpInfAndSts/OrgnlMsgId"] == original.message_id
        assert row.direction == "INBOUND"
        assert "AcceptedSettlementCompleted" in row.business_summary["statusMeaning"]

    def test_negative_status_report_carries_the_reason(self, payments, db_session) -> None:
        payment = _payment(payments, sic("100.00"))
        engine = MessageEngine(db_session)
        original, _ = engine.generate_pacs008(payment, get_scheme(payment.scheme))
        row = engine.receive_pacs002(
            payment,
            get_scheme(payment.scheme),
            original.message_id,
            accepted=False,
            reason_code="AM04",
        )
        paths = _paths(row.xml_payload)
        assert paths["FIToFIPmtStsRpt/TxInfAndSts/TxSts"] == "RJCT"
        assert paths["FIToFIPmtStsRpt/TxInfAndSts/StsRsnInf/Rsn/Cd"] == "AM04"
        assert row.reason_code == "AM04"
        assert "Insufficient funds" in paths["FIToFIPmtStsRpt/TxInfAndSts/StsRsnInf/AddtlInf"]


class TestOtherMessages:
    def test_pacs004_return(self, payments, db_session) -> None:
        payment = _payment(payments, sepa("100.00"))
        engine = MessageEngine(db_session)
        original, _ = engine.generate_pacs008(payment, get_scheme(payment.scheme))
        row = engine.receive_pacs004(
            payment,
            get_scheme(payment.scheme),
            original.message_id,
            return_reason_code="AC04",
            charges=Decimal("5.00"),
        )
        paths = _paths(row.xml_payload)
        assert paths["PmtRtr/TxInf/RtrRsnInf/Rsn/Cd"] == "AC04"
        assert paths["PmtRtr/TxInf/RtrdIntrBkSttlmAmt"] == "100.00"
        assert paths["PmtRtr/TxInf/ChrgsInf/Amt"] == "5.00"

    def test_pacs028_status_request(self, payments, db_session) -> None:
        payment = _payment(payments, sic("100.00"))
        engine = MessageEngine(db_session)
        original, _ = engine.generate_pacs008(payment, get_scheme(payment.scheme))
        row = engine.send_pacs028(
            payment,
            get_scheme(payment.scheme),
            original.message_id,
            elapsed_seconds=26.4,
            threshold_seconds=25,
        )
        paths = _paths(row.xml_payload)
        assert paths["FIToFIPmtStsReq/TxInf/OrgnlEndToEndId"] == payment.end_to_end_id
        assert "26.4" in row.business_summary["plainEnglish"]

    def test_camt056_and_camt029(self, payments, db_session) -> None:
        payment = _payment(payments, sic("100.00"))
        engine = MessageEngine(db_session)
        original, _ = engine.generate_pacs008(payment, get_scheme(payment.scheme))
        request = engine.send_camt056(
            payment, get_scheme(payment.scheme), original.message_id, cancellation_reason_code="DUPL"
        )
        paths = _paths(request.xml_payload)
        assert paths["FIToFIPmtCxlReq/Undrlyg/TxInf/CxlRsnInf/Rsn/Cd"] == "DUPL"

        resolution = engine.receive_camt029(
            payment,
            get_scheme(payment.scheme),
            request.message_id,
            resolution_status="CNCL",
            narrative="Stopped before the beneficiary was credited.",
        )
        rpaths = _paths(resolution.xml_payload)
        assert rpaths["RsltnOfInvstgtn/Sts/Conf"] == "CNCL"
        assert "Cancelled" in resolution.business_summary["keyFacts"][1]["value"]

    def test_camt054_notification(self, payments, db_session) -> None:
        from app.core.identifiers import utcnow

        payment = _payment(payments, sic("250.00"))
        engine = MessageEngine(db_session)
        account = payment.debtor_account
        assert account is not None
        row = engine.receive_camt054(
            payment,
            get_scheme(payment.scheme),
            account,
            side="DEBIT",
            entry_amount=Decimal("250.00"),
            entry_currency="CHF",
            booking_date=utcnow().date(),
            value_date=utcnow().date(),
            statement_reference="STMT-9001",
            narrative="test entry",
        )
        paths = _paths(row.xml_payload)
        assert paths["BkToCstmrDbtCdtNtfctn/Ntfctn/Ntry/CdtDbtInd"] == "DBIT"
        assert paths["BkToCstmrDbtCdtNtfctn/Ntfctn/Ntry/Amt"] == "250.00"
        assert (
            paths["BkToCstmrDbtCdtNtfctn/Ntfctn/Ntry/NtryDtls/TxDtls/Refs/EndToEndId"]
            == payment.end_to_end_id
        )

    def test_camt053_statement_balances(self, payments, db_session) -> None:
        from datetime import timedelta

        from app.core.identifiers import utcnow
        from app.db.models import StatementEntry

        payment = payments.create(
            PaymentCreate.model_validate({**sic("300.00"), "processingMode": "IMMEDIATE"})
        )
        payments.execute(payment, mode=ProcessingMode.IMMEDIATE)
        account = payment.debtor_account
        entries = list(
            db_session.query(StatementEntry).filter(StatementEntry.account_id == account.id).all()
        )
        built = MessageEngine(db_session).build_camt053(
            account,
            entries,
            opening_balance=Decimal("1000.00"),
            closing_balance=Decimal("700.00"),
            from_date=utcnow().date() - timedelta(days=1),
            to_date=utcnow().date(),
        )
        paths = _paths(built.xml)
        assert paths["BkToCstmrStmt/Stmt/Acct/Id/IBAN"] == account.iban
        assert "camt.053.001.08" in built.xml
        assert built.business_summary["keyFacts"]

    def test_mt103_generation(self, payments, db_session) -> None:
        payment = _payment(payments, swift("86500.00", "USD"))
        row = MessageEngine(db_session).generate_mt103(payment, get_scheme(payment.scheme))
        assert row.message_type == "MT103"
        assert ":32A:" in row.xml_payload
        assert ":50K:" in row.xml_payload
        assert ":59:" in row.xml_payload
        assert ":71A:SHA" in row.xml_payload
        assert "86500,00" in row.xml_payload  # MT comma decimal separator
        assert payment.uetr in row.xml_payload


class TestMtMxMapping:
    def test_mapping_table_distinguishes_mapping_types(self) -> None:
        rows = mt.mapping_rows()
        types = {r["mappingType"] for r in rows}
        assert {"DIRECT", "TRANSFORMED", "DERIVED", "NO_DIRECT_EQUIVALENT"} <= types

    def test_mapping_does_not_claim_one_to_one(self) -> None:
        rows = mt.mapping_rows()
        field_72 = next(r for r in rows if r["mtTag"] == ":72")
        assert field_72["mappingType"] == "NO_DIRECT_EQUIVALENT"
        amount = next(r for r in rows if r["mtTag"] == ":32A")
        assert amount["mappingType"] == "TRANSFORMED"
        assert "three distinct MX elements" in amount["note"]

    def test_mapping_includes_actual_values_for_a_payment(self, payments) -> None:
        payment = _payment(payments, swift("86500.00", "USD"))
        rows = mt.mapping_rows(payment)
        amount = next(r for r in rows if r["mtTag"] == ":32A")
        assert "86500,00" in amount["mtValue"]
        uetr = next(r for r in rows if r["mtTag"] == "Block 3 {121:}")
        assert uetr["mtValue"] == payment.uetr


class TestMessageMetadata:
    @pytest.mark.parametrize("message", list(MessageType))
    def test_every_message_type_has_metadata(self, message: MessageType) -> None:
        meta = MESSAGE_METADATA[message]
        assert meta["name"]
        assert meta["iso_identifier"]
        assert meta["purpose"]
        assert meta["direction"] in ("INBOUND", "OUTBOUND")
