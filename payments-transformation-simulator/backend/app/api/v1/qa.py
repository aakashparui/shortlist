"""QA Lab: scenarios, failure injection catalogue, test-case generator, demo mode."""

from __future__ import annotations

from fastapi import APIRouter, Body, Query
from sqlalchemy import select

from app.api import serializers as ser
from app.api.deps import DbSession, Payments, Scenarios, TestCases, bad_request, not_found
from app.api.schemas import ScenarioRunRequest, TestCaseGenerateRequest, TestCaseRunRequest
from app.db.models import Payment, Scenario, TestCase
from app.domain.enums import ProcessingMode
from app.engines.failure_injection import catalogue
from app.engines.scheduler import wait_for_quiet
from app.engines.validation.rules import RULES

router = APIRouter(tags=["qa-lab"])

DEMO_BUTTONS: tuple[dict, ...] = (
    {
        "id": "demo-success-sic",
        "label": "Run successful SIC payment",
        "scenarioCode": "SC-01",
        "description": "A clean domestic CHF instant payment, end to end.",
    },
    {
        "id": "demo-clearing-timeout",
        "label": "Simulate clearing timeout",
        "scenarioCode": "SC-06",
        "description": "No pacs.002 arrives; pacs.028 is sent and an investigation is opened.",
    },
    {
        "id": "demo-duplicate",
        "label": "Simulate duplicate payment",
        "scenarioCode": "SC-03",
        "description": "The EndToEndId has already been used; the duplicate check rejects it.",
    },
    {
        "id": "demo-recon-break",
        "label": "Simulate reconciliation break",
        "scenarioCode": "SC-11",
        "description": "The payment settles but no camt.054 arrives, leaving a MISSING_ENTRY break.",
    },
    {
        "id": "demo-embargo",
        "label": "Simulate embargo hit",
        "scenarioCode": "SC-04",
        "description": "Screening blocks the payment before any message is dispatched.",
    },
    {
        "id": "demo-cross-border",
        "label": "Run cross-border payment",
        "scenarioCode": "SC-20",
        "description": "A USD correspondent payment with UETR tracking and the MT103 equivalent.",
    },
)


@router.get("/scenarios", summary="Scenario library")
def list_scenarios(service: Scenarios, category: str | None = None) -> dict:
    rows = service.list_scenarios()
    if category:
        rows = [r for r in rows if r.category == category.upper()]
    return {
        "items": [ser.scenario(s) for s in rows],
        "categories": sorted({s.category for s in service.list_scenarios()}),
        "demoButtons": list(DEMO_BUTTONS),
    }


@router.get("/scenarios/executions", summary="Recent scenario executions")
def scenario_executions(service: Scenarios, session: DbSession, limit: int = Query(50, ge=1, le=200)) -> dict:
    rows = service.executions(limit=limit)
    out = []
    for row in rows:
        payment = session.get(Payment, row.payment_id) if row.payment_id else None
        out.append(
            ser.scenario_execution(row, payment_reference=payment.reference if payment else None)
        )
    return {"items": out}


@router.get("/scenarios/{code}", summary="One scenario")
def get_scenario(code: str, service: Scenarios) -> dict:
    try:
        return ser.scenario(service.require(code))
    except LookupError as exc:
        raise not_found(str(exc)) from exc


@router.post("/scenarios/{code}/run", summary="Execute a scenario and compare actual vs expected")
def run_scenario(
    code: str,
    service: Scenarios,
    payments: Payments,
    session: DbSession,
    payload: ScenarioRunRequest = Body(default_factory=ScenarioRunRequest),
) -> dict:
    try:
        scenario = service.require(code)
    except LookupError as exc:
        raise not_found(str(exc)) from exc
    mode = ProcessingMode(payload.processingMode)
    result = service.run(scenario, mode=mode)
    session.commit()
    if mode is ProcessingMode.SIMULATED:
        wait_for_quiet(payload.waitTimeoutSeconds)
        session.expire_all()
        refreshed = session.get(Payment, result.payment.id)
        if refreshed is not None:
            result.execution.actual_status = refreshed.status
            result.assertions = service.assert_scenario(scenario, refreshed)
            result.execution.assertions = [a.as_dict() for a in result.assertions]
            result.execution.outcome = "PASSED" if result.passed else "FAILED"
            session.commit()
            result.payment = refreshed
    return {
        "scenario": ser.scenario(scenario),
        "execution": ser.scenario_execution(
            result.execution, payment_reference=result.payment.reference
        ),
        "assertions": [a.as_dict() for a in result.assertions],
        "passed": result.passed,
        "payment": payments.full_view(result.payment),
    }


@router.post("/scenarios/run-all", summary="Execute the whole scenario library")
def run_all(service: Scenarios, session: DbSession) -> dict:
    results = []
    for scenario in service.list_scenarios():
        result = service.run(scenario, mode=ProcessingMode.IMMEDIATE)
        results.append(
            {
                "scenarioCode": scenario.code,
                "title": scenario.title,
                "expectedStatus": scenario.expected_status,
                "actualStatus": result.payment.status,
                "paymentReference": result.payment.reference,
                "passed": result.passed,
                "assertions": [a.as_dict() for a in result.assertions],
            }
        )
    session.commit()
    passed = sum(1 for r in results if r["passed"])
    return {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "results": results,
    }


@router.get("/failure-injections", summary="Failure injection catalogue")
def failure_injections() -> dict:
    items = catalogue()
    return {
        "items": items,
        "byCategory": {
            category: [i for i in items if i["category"] == category]
            for category in sorted({i["category"] for i in items})
        },
        "note": (
            "An injection changes the input or a downstream system's behaviour. The engines then "
            "fail for real, so every failure is reproducible and explainable."
        ),
    }


@router.get("/test-cases", summary="Generated test cases")
def list_test_cases(service: TestCases, suite: str | None = None, ruleId: str | None = None) -> dict:
    rows = service.list_cases(suite=suite, rule_id=ruleId)
    return {
        "items": [ser.test_case(c) for c in rows],
        "suites": service.suites(),
        "generatableRules": [
            {
                "ruleId": rule.rule_id,
                "name": rule.name,
                "category": rule.category.value,
                "field": rule.field,
                "hasBoundaryAnalysis": rule.rule_id
                in ("VAL-AMOUNT-003", "SIC-AMOUNT-001", "SEPA-AMOUNT-001"),
            }
            for rule in RULES
        ],
    }


@router.post("/test-cases/generate", summary="Generate test cases from a rule")
def generate_test_cases(payload: TestCaseGenerateRequest, service: TestCases) -> dict:
    rule_id = payload.ruleId or "VAL-AMOUNT-003"
    try:
        cases = service.generate_for_rule(rule_id, payload.scheme)
    except LookupError as exc:
        raise not_found(str(exc)) from exc
    except KeyError as exc:
        raise bad_request(f"Unknown scheme '{payload.scheme}'") from exc
    suite = payload.suite or f"{rule_id}-{payload.scheme}"
    if payload.persist:
        rows = service.persist(cases, suite=suite, rule_id=rule_id, scheme=payload.scheme)
        return {
            "suite": suite,
            "ruleId": rule_id,
            "scheme": payload.scheme,
            "items": [ser.test_case(r) for r in rows],
        }
    return {
        "suite": suite,
        "ruleId": rule_id,
        "scheme": payload.scheme,
        "items": [
            {
                "caseId": c.case_id,
                "testType": c.test_type,
                "title": c.title,
                "preconditions": c.preconditions,
                "steps": c.steps,
                "inputData": c.input_data,
                "expectedResult": c.expected_result,
                "expectedStatus": c.expected_status,
                "expectedRuleOutcome": c.expected_rule_outcome,
                "priority": c.priority,
            }
            for c in cases
        ],
    }


@router.post("/test-cases/run", summary="Execute generated test cases against the engine")
def run_test_cases(payload: TestCaseRunRequest, service: TestCases, session: DbSession) -> dict:
    stmt = select(TestCase)
    if payload.caseIds:
        stmt = stmt.where(TestCase.case_id.in_(payload.caseIds))
    if payload.ruleId:
        stmt = stmt.where(TestCase.rule_id == payload.ruleId)
    if payload.scheme:
        stmt = stmt.where(TestCase.scheme == payload.scheme)
    cases = list(session.execute(stmt.order_by(TestCase.id.asc())).scalars())
    if not cases:
        raise not_found("No matching test cases. Generate a suite first.")
    summary = service.run_suite(cases)
    session.commit()
    return summary


@router.get("/demo", summary="Demo mode buttons")
def demo(service: Scenarios) -> dict:
    highlights = [s for s in service.list_scenarios() if s.is_demo_highlight]
    return {
        "buttons": list(DEMO_BUTTONS),
        "highlightScenarios": [ser.scenario(s) for s in highlights],
    }


@router.get("/scenario-categories", summary="Scenario categories with counts")
def scenario_categories(session: DbSession) -> dict:
    rows = session.execute(select(Scenario.category, Scenario.code)).all()
    counts: dict[str, int] = {}
    for category, _ in rows:
        counts[category] = counts.get(category, 0) + 1
    return {"items": [{"category": k, "count": v} for k, v in sorted(counts.items())]}
