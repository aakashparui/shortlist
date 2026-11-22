"""API integration tests, including the full create-execute-investigate journey."""

from __future__ import annotations

import pytest

from app.seed.scenarios import sepa, sic, swift

IMMEDIATE = {"processingMode": "IMMEDIATE"}


def create(client, payload: dict, injections: list[str] | None = None) -> dict:
    body = {
        **payload,
        "processingMode": "IMMEDIATE",
        "failureInjections": [{"code": code, "parameters": {}} for code in (injections or [])],
    }
    response = client.post("/api/v1/payments", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def execute(client, reference: str) -> dict:
    response = client.post(f"/api/v1/payments/{reference}/execute", json=IMMEDIATE)
    assert response.status_code == 200, response.text
    return response.json()


class TestMeta:
    def test_health(self, api_client) -> None:
        body = api_client.get("/health").json()
        assert body["status"] == "ok"
        assert body["database"] == "ok"

    def test_index_carries_the_disclaimer(self, api_client) -> None:
        body = api_client.get("/").json()
        assert "fictional" in body["disclaimer"]

    def test_openapi_is_served(self, api_client) -> None:
        spec = api_client.get("/openapi.json").json()
        assert spec["info"]["title"]
        assert len(spec["paths"]) > 50

    def test_request_id_is_echoed(self, api_client) -> None:
        response = api_client.get("/health", headers={"x-request-id": "abc123"})
        assert response.headers["x-request-id"] == "abc123"

    def test_config_exposes_no_secrets(self, api_client) -> None:
        body = api_client.get("/api/v1/config").json()
        serialised = str(body).lower()
        assert "api_key" not in serialised
        assert "apikey" not in serialised
        assert body["simulationDisclaimer"]


class TestPaymentJourneyApi:
    def test_create_returns_the_full_view(self, api_client) -> None:
        body = create(api_client, sic("2500.00"))
        assert body["reference"].startswith("TXN-")
        assert body["status"] == "INITIATED"
        assert len(body["stages"]) == 13
        assert body["debtor"]["name"]
        assert body["creditor"]["name"]
        assert body["schemeDetail"]["code"] == "SIC_INSTANT"

    def test_execute_completes_and_returns_every_subsystem(self, api_client) -> None:
        reference = create(api_client, sic("2500.00"))["reference"]
        body = execute(api_client, reference)
        assert body["status"] == "COMPLETED"
        assert body["messages"]
        assert body["clearing"]
        assert body["settlements"]
        assert body["accountingEntries"]
        assert body["reconciliationRecords"]
        assert body["events"]
        assert body["validations"]
        assert body["execution"]["stagesCompleted"]

    def test_timeline_endpoint(self, api_client) -> None:
        reference = create(api_client, sic("2500.00"))["reference"]
        execute(api_client, reference)
        body = api_client.get(f"/api/v1/payments/{reference}/timeline").json()
        assert body["status"] == "COMPLETED"
        assert len(body["stages"]) == 13
        assert body["stages"][0]["businessLabel"]
        assert body["stages"][0]["technicalLabel"]
        assert body["scheme"]["clearing"]["system"]

    def test_messages_endpoint_includes_payload_and_mapping(self, api_client) -> None:
        reference = create(api_client, sic("2500.00"))["reference"]
        execute(api_client, reference)
        body = api_client.get(f"/api/v1/payments/{reference}/messages").json()
        pacs008 = next(m for m in body["items"] if m["messageType"] == "pacs.008")
        assert pacs008["payload"].startswith("<?xml")
        assert pacs008["fieldMappings"]
        assert pacs008["businessSummary"]["plainEnglish"]
        assert pacs008["validationSummary"]

    def test_single_message_endpoint(self, api_client) -> None:
        reference = create(api_client, sic("2500.00"))["reference"]
        execute(api_client, reference)
        listing = api_client.get(f"/api/v1/payments/{reference}/messages").json()
        message_id = listing["items"][0]["messageId"]
        body = api_client.get(f"/api/v1/payments/{reference}/messages/{message_id}").json()
        assert body["messageId"] == message_id

    def test_accounting_endpoint_reports_balance(self, api_client) -> None:
        reference = create(api_client, sic("2500.00"))["reference"]
        execute(api_client, reference)
        body = api_client.get(f"/api/v1/payments/{reference}/accounting").json()
        assert body["totals"]["balanced"] is True
        assert body["totals"]["debits"] == body["totals"]["credits"]
        assert body["statementEntries"]

    def test_events_can_be_filtered(self, api_client) -> None:
        reference = create(api_client, sic("2500.00"))["reference"]
        execute(api_client, reference)
        body = api_client.get(
            f"/api/v1/payments/{reference}/events?eventType=STATUS_CHANGED"
        ).json()
        assert body["items"]
        assert {e["eventType"] for e in body["items"]} == {"STATUS_CHANGED"}

    def test_lookup_by_end_to_end_id(self, api_client) -> None:
        created = create(api_client, sic("2500.00"))
        body = api_client.get(f"/api/v1/payments/{created['endToEndId']}").json()
        assert body["reference"] == created["reference"]

    def test_cross_border_exposes_tracking_and_mt_mx(self, api_client) -> None:
        reference = create(api_client, swift("50000.00"))["reference"]
        execute(api_client, reference)
        tracking = api_client.get(f"/api/v1/payments/{reference}/tracking").json()
        assert tracking["supported"] is True
        assert tracking["uetr"]
        assert tracking["events"]
        assert "not connected to SWIFT" in tracking["simulationNote"]
        mapping = api_client.get(f"/api/v1/payments/{reference}/mt-mx").json()
        assert mapping["rows"]
        assert "no universal one-to-one" in mapping["note"]

    def test_domestic_payment_reports_tracking_unsupported(self, api_client) -> None:
        reference = create(api_client, sic("100.00"))["reference"]
        body = api_client.get(f"/api/v1/payments/{reference}/tracking").json()
        assert body["supported"] is False

    def test_listing_filters_and_paginates(self, api_client) -> None:
        for amount in ("100.00", "200.00", "300.00"):
            execute(api_client, create(api_client, sic(amount))["reference"])
        body = api_client.get("/api/v1/payments?pageSize=2&status=COMPLETED").json()
        assert body["total"] >= 3
        assert len(body["items"]) == 2
        assert body["pages"] >= 2
        assert {i["status"] for i in body["items"]} == {"COMPLETED"}

    def test_listing_search_by_query(self, api_client) -> None:
        created = create(api_client, sic("100.00"))
        body = api_client.get(f"/api/v1/payments?query={created['reference']}").json()
        assert body["total"] == 1

    def test_statistics(self, api_client) -> None:
        execute(api_client, create(api_client, sic("100.00"))["reference"])
        body = api_client.get("/api/v1/payments/statistics").json()
        assert body["totalPayments"] >= 1
        assert "COMPLETED" in body["byStatus"]
        assert body["byCurrency"]
        assert body["successRate"] > 0


class TestFailureInjectionApi:
    def test_catalogue_is_grouped_by_category(self, api_client) -> None:
        body = api_client.get("/api/v1/failure-injections").json()
        assert body["items"]
        assert body["byCategory"]
        assert "reproducible" in body["note"]

    def test_inject_then_execute_actually_fails(self, api_client) -> None:
        reference = create(api_client, sic("1000.00"))["reference"]
        injected = api_client.post(
            f"/api/v1/payments/{reference}/failures",
            json={"code": "CLEARING_TIMEOUT", "parameters": {}},
        )
        assert injected.status_code == 201
        body = execute(api_client, reference)
        assert body["status"] == "INVESTIGATION_REQUIRED"
        assert body["investigations"]
        assert any(m["messageType"] == "pacs.028" for m in body["messages"])

    def test_unknown_injection_is_rejected(self, api_client) -> None:
        reference = create(api_client, sic("1000.00"))["reference"]
        response = api_client.post(
            f"/api/v1/payments/{reference}/failures", json={"code": "NOT_A_CODE", "parameters": {}}
        )
        assert response.status_code == 400

    def test_injection_can_be_deactivated(self, api_client) -> None:
        reference = create(api_client, sic("1000.00"))["reference"]
        injected = api_client.post(
            f"/api/v1/payments/{reference}/failures",
            json={"code": "CLEARING_TIMEOUT", "parameters": {}},
        ).json()
        removed = api_client.delete(f"/api/v1/payments/{reference}/failures/{injected['id']}")
        assert removed.status_code == 200
        assert removed.json()["active"] is False
        body = execute(api_client, reference)
        assert body["status"] == "COMPLETED"


class TestOperationsApi:
    def test_investigation_workflow(self, api_client) -> None:
        reference = create(api_client, sic("9900.00"), ["CLEARING_TIMEOUT"])["reference"]
        execute(api_client, reference)
        queue = api_client.get("/api/v1/investigations?openOnly=true").json()
        assert queue["items"]
        investigation = queue["items"][0]
        assert investigation["expectedBehaviour"]
        assert investigation["actualBehaviour"]
        assert investigation["probableCause"]
        assert investigation["recommendedAction"]

        detail = api_client.get(f"/api/v1/investigations/{investigation['reference']}").json()
        assert detail["payment"]["reference"] == reference

        acted = api_client.post(
            f"/api/v1/investigations/{investigation['reference']}/actions",
            json={"action": "CALLED_CLEARING", "note": "Operations desk confirmed receipt."},
        )
        assert acted.status_code == 200
        assert len(acted.json()["actions"]) >= 2

        resolved = api_client.post(
            f"/api/v1/investigations/{investigation['reference']}/resolve",
            json={"resolution": "Clearing confirmed acceptance; reprocessed."},
        )
        assert resolved.status_code == 200
        assert resolved.json()["status"] == "RESOLVED"
        assert resolved.json()["resolvedAt"]

    def test_resolve_timeout_then_complete(self, api_client) -> None:
        reference = create(api_client, sic("9900.00"), ["CLEARING_TIMEOUT"])["reference"]
        execute(api_client, reference)
        body = api_client.post(
            f"/api/v1/payments/{reference}/resolve-timeout", json={"accepted": True}
        ).json()
        assert body["status"] == "COMPLETED"
        assert body["settlements"][0]["status"] == "SETTLED"

    def test_exceptions_dashboard(self, api_client) -> None:
        execute(api_client, create(api_client, sic("5000.00"), ["RECON_MISSING_CAMT054"])["reference"])
        execute(api_client, create(api_client, sic("1000.00"), ["INVALID_CREDITOR_IBAN"])["reference"])
        body = api_client.get("/api/v1/exceptions").json()
        assert body["summary"]["failedPayments"] >= 2
        assert body["summary"]["reconciliationBreaks"] >= 1
        assert body["summary"]["openInvestigations"] >= 1
        assert body["payments"]
        assert body["reconciliationBreaks"]

    def test_reconciliation_listing_and_classifications(self, api_client) -> None:
        execute(api_client, create(api_client, sic("5000.00"), ["RECON_AMOUNT_MISMATCH"])["reference"])
        body = api_client.get("/api/v1/reconciliation?breaksOnly=true").json()
        assert body["items"]
        record = body["items"][0]
        assert record["status"] == "AMOUNT_MISMATCH"
        assert record["probableCause"]
        assert record["recommendedAction"]
        assert len(record["legs"]) == 4
        assert body["classifications"]

    def test_reconciliation_detail_includes_the_payment(self, api_client) -> None:
        reference = create(api_client, sic("5000.00"), ["RECON_AMOUNT_MISMATCH"])["reference"]
        execute(api_client, reference)
        listing = api_client.get("/api/v1/reconciliation?breaksOnly=true").json()
        detail = api_client.get(f"/api/v1/reconciliation/{listing['items'][0]['reference']}").json()
        assert detail["payment"]["reference"] == reference

    def test_unmatched_statement_entries(self, api_client) -> None:
        execute(
            api_client, create(api_client, sic("2100.00"), ["RECON_UNMATCHED_STATEMENT"])["reference"]
        )
        body = api_client.get("/api/v1/reconciliation/unmatched").json()
        assert body["total"] >= 1
        assert body["items"][0]["isOrphan"] is True

    def test_manual_reconcile(self, api_client) -> None:
        reference = create(api_client, sic("1000.00"))["reference"]
        execute(api_client, reference)
        body = api_client.post(f"/api/v1/payments/{reference}/reconcile", json={}).json()
        assert body["status"] == "MATCHED"

    def test_cancellation_and_return(self, api_client) -> None:
        reference = create(api_client, sepa("4300.00"))["reference"]
        execute(api_client, reference)
        cancelled = api_client.post(
            f"/api/v1/payments/{reference}/cancel",
            json={"reasonCode": "CUST", "narrative": "customer asked"},
        ).json()
        assert cancelled["cancellation"]["requestMessage"]["messageType"] == "camt.056"
        assert cancelled["cancellation"]["resolutionMessage"]["messageType"] == "camt.029"

        returned = api_client.post(
            f"/api/v1/payments/{reference}/return",
            json={"reasonCode": "AC04", "narrative": "account closed"},
        ).json()
        assert returned["status"] == "RETURNED"
        assert returned["returnMessage"]["messageType"] == "pacs.004"


class TestSystemApi:
    def test_schemes_listing(self, api_client) -> None:
        body = api_client.get("/api/v1/schemes").json()
        assert len(body["items"]) == 4
        codes = {s["code"] for s in body["items"]}
        assert codes == {"SIC_INSTANT", "SEPA_INSTANT", "SWIFT_CROSS_BORDER", "GENERIC_ISO20022"}
        for scheme in body["items"]:
            assert scheme["simulationNotes"]
            assert scheme["clearing"]["timeoutSeconds"] > 0

    def test_scheme_detail_includes_rules(self, api_client) -> None:
        body = api_client.get("/api/v1/schemes/SIC_INSTANT").json()
        assert body["rules"]
        assert body["messageCatalogue"]
        assert any(r["ruleId"] == "SIC-AMOUNT-001" for r in body["rules"])

    def test_unknown_scheme_is_404(self, api_client) -> None:
        assert api_client.get("/api/v1/schemes/NOPE").status_code == 404

    def test_rule_explorer_and_toggle(self, api_client) -> None:
        listing = api_client.get("/api/v1/rules").json()
        assert listing["total"] > 20
        assert listing["categories"]

        detail = api_client.get("/api/v1/rules/SIC-AMOUNT-001").json()
        assert detail["parameters"]["maxAmount"] == "20000.00"
        assert detail["relatedFailureInjections"]

        disabled = api_client.patch(
            "/api/v1/rules/SIC-AMOUNT-001", json={"enabled": False, "reason": "demo"}
        ).json()
        assert disabled["enabled"] is False

        # With the rule disabled the over-limit payment is no longer stopped by it.
        reference = create(api_client, sic("25000.00"))["reference"]
        body = execute(api_client, reference)
        skipped = [v for v in body["validations"] if v["ruleId"] == "SIC-AMOUNT-001"]
        assert skipped and skipped[0]["status"] == "SKIPPED"

        api_client.patch("/api/v1/rules/SIC-AMOUNT-001", json={"enabled": True, "reason": "restore"})

    def test_rule_toggle_is_audited(self, api_client) -> None:
        api_client.patch("/api/v1/rules/VAL-DUP-001", json={"enabled": False, "reason": "testing"})
        api_client.patch("/api/v1/rules/VAL-DUP-001", json={"enabled": True, "reason": "restore"})
        body = api_client.get("/api/v1/audit?entityType=BusinessRule&entityId=VAL-DUP-001").json()
        assert body["total"] >= 2
        assert body["items"][0]["before"] != body["items"][0]["after"]

    def test_state_machine_endpoint(self, api_client) -> None:
        body = api_client.get("/api/v1/state-machine").json()
        assert body["transitions"]
        assert len(body["stages"]) == 13
        assert any(s["isFailure"] for s in body["statuses"])

    def test_global_event_log_with_filters(self, api_client) -> None:
        execute(api_client, create(api_client, sic("1000.00"))["reference"])
        body = api_client.get("/api/v1/events?severity=INFO&pageSize=10").json()
        assert body["items"]
        assert body["filters"]["eventTypes"]
        assert all(e["severity"] == "INFO" for e in body["items"])
        assert body["items"][0]["paymentReference"]

    def test_accounts_and_nostro_explainer(self, api_client) -> None:
        body = api_client.get("/api/v1/accounts").json()
        assert body["byType"]["NOSTRO"]
        assert body["byType"]["VOSTRO"]
        assert "Italian for" in body["explainer"]["NOSTRO"]

    def test_account_detail_shows_movement(self, api_client) -> None:
        reference = create(api_client, sic("1000.00"))["reference"]
        execute(api_client, reference)
        body = api_client.get("/api/v1/accounts/0012-345678-01").json()
        assert body["accountingEntries"]
        assert body["movement"]["netMovement"].startswith("-")

    def test_statement_generation(self, api_client) -> None:
        execute(api_client, create(api_client, sic("1000.00"))["reference"])
        body = api_client.get("/api/v1/statement/0012-345678-01").json()
        assert body["messageType"] == "camt.053"
        assert body["payload"].startswith("<?xml")
        assert body["entries"]

    def test_banks_directory_is_marked_fictional(self, api_client) -> None:
        body = api_client.get("/api/v1/banks").json()
        assert body["items"]
        assert "fictional" in body["note"]

    def test_message_explorer(self, api_client) -> None:
        execute(api_client, create(api_client, sic("1000.00"))["reference"])
        body = api_client.get("/api/v1/messages?messageType=pacs.008").json()
        assert body["items"]
        assert body["items"][0]["paymentReference"]
        assert body["catalogue"]

    def test_message_catalogue_carries_the_simulation_note(self, api_client) -> None:
        body = api_client.get("/api/v1/messages/catalogue").json()
        assert "not validated against the official ISO" in body["simulationNote"]
        assert len(body["items"]) >= 9

    def test_mt_mx_reference_warns_against_one_to_one(self, api_client) -> None:
        body = api_client.get("/api/v1/messages/mt-mx").json()
        assert "no universal one-to-one" in body["warning"]
        assert len(body["mappingTypes"]) == 4

    def test_command_search(self, api_client) -> None:
        created = create(api_client, sic("1000.00"))
        body = api_client.get(f"/api/v1/search?q={created['reference']}").json()
        assert body["items"][0]["kind"] == "PAYMENT"
        views = api_client.get("/api/v1/search?q=find failed payments").json()
        assert any(i["kind"] == "VIEW" for i in views["items"])

    def test_enums(self, api_client) -> None:
        body = api_client.get("/api/v1/enums").json()
        assert "COMPLETED" in body["paymentStatuses"]
        assert "pacs.008" in body["messageTypes"]


class TestQaApi:
    def test_scenario_listing_with_demo_buttons(self, api_client) -> None:
        body = api_client.get("/api/v1/scenarios").json()
        assert len(body["items"]) == 20
        assert body["demoButtons"]
        assert body["categories"]

    def test_scenario_run_reports_assertions(self, api_client) -> None:
        body = api_client.post("/api/v1/scenarios/SC-06/run", json=IMMEDIATE).json()
        assert body["passed"] is True
        assert body["execution"]["actualStatus"] == "INVESTIGATION_REQUIRED"
        assert body["assertions"]
        assert body["payment"]["investigations"]

    def test_scenario_run_unknown_code(self, api_client) -> None:
        assert api_client.post("/api/v1/scenarios/SC-99/run", json=IMMEDIATE).status_code == 404

    def test_run_all_scenarios(self, api_client) -> None:
        body = api_client.post("/api/v1/scenarios/run-all", json={}).json()
        assert body["total"] == 20
        failures = [r for r in body["results"] if not r["passed"]]
        assert not failures, failures

    def test_test_case_generation_and_execution(self, api_client) -> None:
        generated = api_client.post(
            "/api/v1/test-cases/generate",
            json={"ruleId": "SIC-AMOUNT-001", "scheme": "SIC_INSTANT"},
        ).json()
        assert len(generated["items"]) >= 7
        types = {c["testType"] for c in generated["items"]}
        assert "BOUNDARY" in types and "NEGATIVE" in types

        result = api_client.post("/api/v1/test-cases/run", json={"ruleId": "SIC-AMOUNT-001"}).json()
        assert result["failed"] == 0, result["results"]

    def test_running_without_generating_is_404(self, api_client) -> None:
        response = api_client.post("/api/v1/test-cases/run", json={"ruleId": "VAL-RMT-001"})
        assert response.status_code == 404

    def test_demo_endpoint(self, api_client) -> None:
        body = api_client.get("/api/v1/demo").json()
        assert body["buttons"]
        assert body["highlightScenarios"]


class TestBaApi:
    def test_context(self, api_client) -> None:
        body = api_client.get("/api/v1/ba/context").json()
        assert len(body["schemes"]) == 4
        assert body["artefactChain"][0] == "Business Requirement"

    def test_package_get_and_post_agree(self, api_client) -> None:
        via_get = api_client.get("/api/v1/ba/package?scheme=SIC_INSTANT").json()
        via_post = api_client.post("/api/v1/ba/package", json={"scheme": "SIC_INSTANT"}).json()
        assert via_get["businessRequirement"]["id"] == via_post["businessRequirement"]["id"]
        assert via_get["functionalRequirements"]

    def test_traceability_endpoint(self, api_client) -> None:
        body = api_client.get("/api/v1/ba/traceability?scheme=SEPA_INSTANT").json()
        assert body["rows"]
        assert body["businessRequirement"]

    def test_unknown_scheme_is_400(self, api_client) -> None:
        assert api_client.get("/api/v1/ba/package?scheme=NOPE").status_code == 400


class TestErrorHandling:
    def test_unknown_payment_is_404_with_structured_body(self, api_client) -> None:
        response = api_client.get("/api/v1/payments/TXN-00000")
        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "HTTP_404"
        assert body["error"]["requestId"]

    def test_validation_error_lists_fields(self, api_client) -> None:
        response = api_client.post("/api/v1/payments", json={"amount": "not-a-number"})
        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert body["error"]["detail"]

    def test_unknown_scheme_on_create_is_400(self, api_client) -> None:
        response = api_client.post("/api/v1/payments", json={**sic("100.00"), "scheme": "NOPE"})
        assert response.status_code == 400

    def test_illegal_transition_is_409_with_allowed_targets(self, api_client) -> None:
        reference = create(api_client, sic("100.00"))["reference"]
        execute(api_client, reference)
        response = api_client.post(f"/api/v1/payments/{reference}/execute", json=IMMEDIATE)
        assert response.status_code == 409
        detail = response.json()["error"]["detail"]
        assert detail["allowedTransitions"]

    def test_extra_fields_are_rejected(self, api_client) -> None:
        response = api_client.post(
            "/api/v1/payments", json={**sic("100.00"), "unexpectedField": "x"}
        )
        assert response.status_code == 422

    def test_page_size_is_capped(self, api_client) -> None:
        response = api_client.get("/api/v1/payments?pageSize=100000")
        assert response.status_code == 422


@pytest.mark.parametrize(
    ("injection", "expected_status"),
    [
        ("INVALID_CREDITOR_IBAN", "REJECTED"),
        ("AMOUNT_EXCEEDS_SCHEME_LIMIT", "REJECTED"),
        ("CLEARING_REJECT_BUSINESS", "CLEARING_REJECTED"),
        ("CLEARING_TIMEOUT", "INVESTIGATION_REQUIRED"),
        ("SETTLEMENT_REJECTED", "INVESTIGATION_REQUIRED"),
        ("ACCOUNTING_MISSING_ENTRY", "INVESTIGATION_REQUIRED"),
        ("RECON_AMOUNT_MISMATCH", "INVESTIGATION_REQUIRED"),
        ("RECON_UNMATCHED_STATEMENT", "COMPLETED"),
    ],
)
def test_failure_paths_end_to_end(api_client, injection: str, expected_status: str) -> None:
    reference = create(api_client, sic("5000.00"), [injection])["reference"]
    body = execute(api_client, reference)
    assert body["status"] == expected_status, body.get("failureSummary")
