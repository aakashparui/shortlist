"""Business Analyst workbench.

Produces the artefact chain a payments BA is expected to deliver:

    Business Requirement
        -> Functional Requirement
            -> Business Rule
                -> Payment Flow
                    -> ISO 20022 Message
                        -> Test Case

Everything is derived from the live scheme configuration, rule book and scenario
library, so the requirements and the traceability matrix always describe what the
system actually does.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import BusinessRule, Scenario
from app.domain.enums import MESSAGE_METADATA, STAGE_LABELS, STAGE_ORDER, MessageType
from app.engines.failure_injection import CATALOGUE_BY_CODE
from app.schemes.base import PaymentScheme
from app.schemes.registry import get_scheme

logger = get_logger(__name__)


@dataclass(slots=True)
class BaPackage:
    scheme: PaymentScheme
    scenario: Scenario | None
    data: dict


class BaService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def rules_for(self, scheme: PaymentScheme) -> list[BusinessRule]:
        ids = list(scheme.validation_rule_ids)
        rows = list(
            self.session.execute(
                select(BusinessRule).where(BusinessRule.rule_id.in_(ids))
            ).scalars()
        )
        order = {rule_id: index for index, rule_id in enumerate(ids)}
        return sorted(rows, key=lambda r: order.get(r.rule_id, 999))

    def build_package(self, *, scheme_code: str, scenario_code: str | None = None) -> BaPackage:
        scheme = get_scheme(scheme_code)
        scenario = (
            self.session.execute(
                select(Scenario).where(Scenario.code == scenario_code.upper()).limit(1)
            ).scalar_one_or_none()
            if scenario_code
            else None
        )
        rules = self.rules_for(scheme)

        business_requirement = {
            "id": f"BR-{scheme.code.value}-001",
            "title": (
                f"Initiate and track {scheme.short_name} credit transfers end to end"
                if scenario is None
                else f"{scenario.title} on {scheme.short_name}"
            ),
            "statement": (
                f"As a corporate customer of the bank, I want to instruct a "
                f"{scheme.rules.settlement_currency} credit transfer over "
                f"{scheme.name}, so that the beneficiary is credited "
                + ("within seconds" if scheme.rules.is_instant else "on the agreed value date")
                + " and I can see the outcome of my instruction."
            ),
            "rationale": scheme.description,
            "scope": [
                "Payment initiation and data capture",
                "Technical, business and scheme validation",
                "Sanctions and embargo screening",
                f"{scheme.messages.instruction_message.value} generation and dispatch",
                f"{scheme.messages.status_message.value} status handling, including timeout",
                "Settlement and double-entry accounting",
                "Reconciliation against the account statement",
                "Exception handling and investigation",
            ],
            "outOfScope": [
                "Customer onboarding and mandate management",
                "Liquidity and intraday position management",
                "Pricing, billing and FX execution",
                "Regulatory reporting submissions",
            ],
            "assumptions": [
                f"{scheme.short_name} settles in {scheme.rules.settlement_currency}",
                f"The scheme response threshold is {scheme.clearing.realistic_timeout_seconds} seconds",
                "Screening lists are maintained outside this system",
                "SIMULATION: scheme limits and timings in this simulator are plausible values, "
                "not a reproduction of a live rulebook",
            ],
            "stakeholders": [
                "Payments product owner",
                "Payment operations",
                "Financial crime compliance",
                "Finance and reconciliation",
                "QA and release management",
            ],
        }

        functional_requirements = self._functional_requirements(scheme, rules)
        process_flow = [
            {
                "step": index + 1,
                "stage": key.value,
                "businessLabel": STAGE_LABELS[key]["business"],
                "technicalLabel": STAGE_LABELS[key]["technical"],
                "actor": _actor_for(key.value),
                "output": _output_for(key.value, scheme),
            }
            for index, key in enumerate(STAGE_ORDER)
        ]
        exception_scenarios = self._exception_scenarios(scheme)
        acceptance_criteria = self._acceptance_criteria(scheme, scenario)
        test_scenarios = self._test_scenarios(scheme, scenario)
        traceability = self._traceability(
            business_requirement, functional_requirements, rules, scheme, test_scenarios
        )

        data = {
            "scheme": scheme.as_dict(),
            "scenarioCode": scenario.code if scenario else None,
            "scenarioTitle": scenario.title if scenario else None,
            "businessRequirement": business_requirement,
            "functionalRequirements": functional_requirements,
            "businessRules": [
                {
                    "ruleId": r.rule_id,
                    "name": r.name,
                    "description": r.description,
                    "category": r.category,
                    "severity": r.severity,
                    "stage": r.stage,
                    "failureBehaviour": r.failure_behaviour,
                    "isoReasonCode": r.iso_reason_code,
                    "enabled": r.enabled,
                    "standardBasis": r.standard_basis,
                }
                for r in rules
            ],
            "processFlow": process_flow,
            "acceptanceCriteria": acceptance_criteria,
            "exceptionScenarios": exception_scenarios,
            "testScenarios": test_scenarios,
            "messageCatalogue": [
                {
                    "messageType": message.value,
                    "name": MESSAGE_METADATA[message]["name"],
                    "isoIdentifier": MESSAGE_METADATA[message]["iso_identifier"],
                    "direction": MESSAGE_METADATA[message]["direction"],
                    "purpose": MESSAGE_METADATA[message]["purpose"],
                }
                for message in scheme.messages.message_set
            ],
            "traceabilityMatrix": traceability,
        }
        return BaPackage(scheme=scheme, scenario=scenario, data=data)

    # ------------------------------------------------------------------
    def _functional_requirements(
        self, scheme: PaymentScheme, rules: list[BusinessRule]
    ) -> list[dict]:
        code = scheme.code.value
        limit = scheme.rules.amount_limits[0] if scheme.rules.amount_limits else None
        items = [
            {
                "id": f"FR-{code}-010",
                "title": "Capture a complete payment instruction",
                "statement": (
                    "The system shall capture debtor, creditor, amount, currency, execution date "
                    "and remittance information, and shall assign an instruction identification, "
                    "an end-to-end identification and a correlation identifier to every "
                    "instruction."
                ),
                "ruleIds": ["VAL-STRUCT-001", "VAL-E2E-001", "VAL-DBTR-001", "VAL-CDTR-001"],
                "stage": "PRE_VALIDATION",
            },
            {
                "id": f"FR-{code}-020",
                "title": "Validate the instruction against technical and scheme rules",
                "statement": (
                    "The system shall validate every instruction against the configured rule set "
                    "before dispatch and shall record, per rule, the outcome, the actual value, "
                    "the expected value and the ISO 20022 reason code where one applies."
                ),
                "ruleIds": [r.rule_id for r in rules if r.category in ("TECHNICAL", "SCHEME")][:8],
                "stage": "BUSINESS_VALIDATION",
            },
            {
                "id": f"FR-{code}-030",
                "title": "Enforce the scheme amount and currency boundaries",
                "statement": (
                    f"The system shall reject instructions outside the {scheme.short_name} "
                    + (
                        f"range {limit.minimum}-{limit.maximum} {limit.currency}"
                        if limit
                        else "configured amount range"
                    )
                    + f" or in a currency other than {', '.join(scheme.rules.allowed_currencies)}."
                ),
                "ruleIds": [
                    r.rule_id
                    for r in rules
                    if r.field in ("amount", "currency") and r.category == "SCHEME"
                ],
                "stage": "BUSINESS_VALIDATION",
            },
            {
                "id": f"FR-{code}-040",
                "title": "Screen every instruction before release",
                "statement": (
                    "The system shall screen debtor, creditor, agent and remittance data against "
                    "the screening lists and shall block any instruction with a blocking match, "
                    "raising an investigation, before any message is dispatched."
                ),
                "ruleIds": ["COMP-EMB-001", "COMP-SANC-001", "COMP-SANC-002", "COMP-AML-001"],
                "stage": "COMPLIANCE",
            },
            {
                "id": f"FR-{code}-050",
                "title": f"Generate a {scheme.messages.instruction_message.value} message",
                "statement": (
                    f"The system shall generate a structurally valid "
                    f"{scheme.messages.instruction_message.value} message for every released "
                    "instruction, shall record the generated payload, and shall make the "
                    "field-by-field mapping from the instruction to the message inspectable."
                ),
                "ruleIds": ["VAL-MSG-001", "VAL-MSG-002"],
                "stage": "MESSAGE_GENERATION",
            },
            {
                "id": f"FR-{code}-060",
                "title": "Handle the clearing status report, including its absence",
                "statement": (
                    f"The system shall await a {scheme.messages.status_message.value} for "
                    f"{scheme.clearing.realistic_timeout_seconds} seconds. On a positive report it "
                    "shall proceed to settlement; on a negative report it shall reject the payment "
                    "and reverse any customer debit; if no report arrives it shall raise a "
                    f"{scheme.messages.status_request_message.value} status request and open an "
                    "investigation rather than re-sending the instruction."
                ),
                "ruleIds": [],
                "stage": "CLEARING_RESPONSE",
            },
            {
                "id": f"FR-{code}-070",
                "title": "Post a balanced double-entry journal",
                "statement": (
                    "For every settled payment the system shall post a journal that debits the "
                    f"customer account and credits the {scheme.settlement.settlement_account_type} "
                    "account for the same amount and currency, and shall raise an accounting break "
                    "if the journal does not balance."
                ),
                "ruleIds": [],
                "stage": "ACCOUNTING",
            },
            {
                "id": f"FR-{code}-080",
                "title": "Reconcile against the account statement",
                "statement": (
                    "The system shall reconcile the internal record, the accounting journal, the "
                    "clearing record and the statement entry, shall classify any difference, and "
                    "shall state the probable cause and the recommended action for every break."
                ),
                "ruleIds": [],
                "stage": "RECONCILIATION",
            },
            {
                "id": f"FR-{code}-090",
                "title": "Maintain a full audit trail and correlation",
                "statement": (
                    "Every state change, message, validation result and operator action shall be "
                    "recorded with who, what, when, before, after and why, and shall be retrievable "
                    "by payment reference, end-to-end identification, correlation identifier, "
                    "clearing reference or settlement reference."
                ),
                "ruleIds": [],
                "stage": "COMPLETION",
            },
        ]
        if scheme.rules.uses_uetr:
            items.append(
                {
                    "id": f"FR-{code}-100",
                    "title": "Carry and track a UETR",
                    "statement": (
                        "The system shall assign a UUID version 4 UETR to every cross-border "
                        "instruction, carry it in the message, and expose a tracking timeline keyed "
                        "on the UETR."
                    ),
                    "ruleIds": ["SWIFT-UETR-001"],
                    "stage": "PRE_VALIDATION",
                }
            )
            items.append(
                {
                    "id": f"FR-{code}-110",
                    "title": "Provide an MT to MX comparison",
                    "statement": (
                        "For cross-border payments the system shall generate the legacy MT103 "
                        "equivalent and present the field-level mapping, distinguishing direct, "
                        "transformed and derived mappings from fields with no direct equivalent."
                    ),
                    "ruleIds": [],
                    "stage": "MESSAGE_GENERATION",
                }
            )
        return [item for item in items if item["ruleIds"] or not item["ruleIds"]]

    def _acceptance_criteria(self, scheme: PaymentScheme, scenario: Scenario | None) -> list[dict]:
        limit = scheme.rules.amount_limits[0] if scheme.rules.amount_limits else None
        criteria = [
            {
                "id": "AC-01",
                "given": f"a valid {scheme.rules.settlement_currency} instruction within the scheme limits",
                "when": "the payment is executed",
                "then": (
                    "every validation rule passes, a "
                    f"{scheme.messages.instruction_message.value} is dispatched, a positive "
                    f"{scheme.messages.status_message.value} is received, settlement completes, a "
                    "balanced journal is posted and reconciliation reports MATCHED"
                ),
                "linkedRequirement": f"FR-{scheme.code.value}-010",
            },
            {
                "id": "AC-02",
                "given": "an instruction whose creditor IBAN fails the ISO 13616 check",
                "when": "the payment is executed",
                "then": (
                    "VAL-IBAN-002 is recorded as FAILED with reason code AC01, the payment status "
                    "is REJECTED and no message is dispatched"
                ),
                "linkedRequirement": f"FR-{scheme.code.value}-020",
            },
        ]
        if limit:
            criteria.append(
                {
                    "id": "AC-03",
                    "given": f"an instruction for {limit.maximum} {limit.currency}",
                    "when": "the payment is executed",
                    "then": "the amount rule passes, because the ceiling is inclusive",
                    "linkedRequirement": f"FR-{scheme.code.value}-030",
                }
            )
            criteria.append(
                {
                    "id": "AC-04",
                    "given": (
                        f"an instruction for {limit.maximum} + 0.01 {limit.currency}"
                    ),
                    "when": "the payment is executed",
                    "then": (
                        "the scheme amount rule fails with reason code AM04 and the payment is "
                        "REJECTED"
                    ),
                    "linkedRequirement": f"FR-{scheme.code.value}-030",
                }
            )
        criteria.extend(
            [
                {
                    "id": "AC-05",
                    "given": "an instruction whose creditor matches the designated-party list",
                    "when": "the payment is executed",
                    "then": (
                        "the payment is blocked before dispatch, an investigation is opened with "
                        "reason COMPLIANCE_BLOCK and the matched value and list reference are "
                        "recorded"
                    ),
                    "linkedRequirement": f"FR-{scheme.code.value}-040",
                },
                {
                    "id": "AC-06",
                    "given": "a dispatched instruction and a clearing system that does not answer",
                    "when": (
                        f"{scheme.clearing.realistic_timeout_seconds} seconds elapse"
                    ),
                    "then": (
                        f"the payment status is TIMED_OUT, a "
                        f"{scheme.messages.status_request_message.value} is sent, an investigation "
                        "is opened and the instruction is not re-sent"
                    ),
                    "linkedRequirement": f"FR-{scheme.code.value}-060",
                },
                {
                    "id": "AC-07",
                    "given": "a settled payment with no statement notification",
                    "when": "reconciliation runs",
                    "then": (
                        "the reconciliation status is MISSING_ENTRY, the statement leg is marked "
                        "absent and the recommended action is to request a statement re-send"
                    ),
                    "linkedRequirement": f"FR-{scheme.code.value}-080",
                },
                {
                    "id": "AC-08",
                    "given": "a payment rejected by the clearing system after the customer was debited",
                    "when": "the negative status report is processed",
                    "then": "reversal entries bring the net customer movement to zero",
                    "linkedRequirement": f"FR-{scheme.code.value}-070",
                },
            ]
        )
        if scenario is not None:
            criteria.append(
                {
                    "id": "AC-09",
                    "given": "; ".join(scenario.preconditions or ["the scenario preconditions"]),
                    "when": f"scenario {scenario.code} is executed",
                    "then": (
                        f"the payment status is {scenario.expected_status} and "
                        + "; ".join(scenario.expected_result or [])
                    ),
                    "linkedRequirement": f"FR-{scheme.code.value}-010",
                }
            )
        return criteria

    def _exception_scenarios(self, scheme: PaymentScheme) -> list[dict]:
        rows = list(
            self.session.execute(
                select(Scenario)
                .where(Scenario.category != "HAPPY_PATH")
                .order_by(Scenario.sort_order.asc())
            ).scalars()
        )
        out: list[dict] = []
        for row in rows:
            codes = list(row.failure_codes or [])
            definitions = [CATALOGUE_BY_CODE[c] for c in codes if c in CATALOGUE_BY_CODE]
            out.append(
                {
                    "scenarioCode": row.code,
                    "title": row.title,
                    "category": row.category,
                    "trigger": "; ".join(d.description for d in definitions) or row.description,
                    "detectedAt": definitions[0].stage.value if definitions else "RECONCILIATION",
                    "systemBehaviour": row.description,
                    "expectedStatus": row.expected_status,
                    "operationalResponse": (
                        definitions[0].expected_outcome if definitions else row.business_context
                    ),
                    "customerImpact": _customer_impact(row.category),
                }
            )
        return out

    def _test_scenarios(self, scheme: PaymentScheme, scenario: Scenario | None) -> list[dict]:
        rows = list(
            self.session.execute(select(Scenario).order_by(Scenario.sort_order.asc())).scalars()
        )
        selected = [r for r in rows if scenario is None or r.code == scenario.code] or rows
        return [
            {
                "testScenarioId": f"TS-{row.code}",
                "scenarioCode": row.code,
                "title": row.title,
                "category": row.category,
                "scheme": row.scheme,
                "preconditions": list(row.preconditions or []),
                "steps": list(row.execution_steps or []),
                "expectedStatus": row.expected_status,
                "expectedResult": list(row.expected_result or []),
                "expectedMessages": list(row.expected_messages or []),
                "expectedReconciliation": row.expected_reconciliation,
            }
            for row in selected
        ]

    def _traceability(
        self,
        business_requirement: dict,
        functional_requirements: list[dict],
        rules: list[BusinessRule],
        scheme: PaymentScheme,
        test_scenarios: list[dict],
    ) -> list[dict]:
        rule_lookup = {r.rule_id: r for r in rules}
        rows: list[dict] = []
        scenario_by_rule: dict[str, list[str]] = {}
        for ts in test_scenarios:
            for rule_id in rule_lookup:
                if rule_id in " ".join(ts["expectedResult"]):
                    scenario_by_rule.setdefault(rule_id, []).append(ts["testScenarioId"])

        for fr in functional_requirements:
            linked_rules = [rule_lookup[r] for r in fr["ruleIds"] if r in rule_lookup]
            stage = fr["stage"]
            messages = _messages_for_stage(stage, scheme)
            tests = sorted(
                {
                    t
                    for rule in linked_rules
                    for t in scenario_by_rule.get(rule.rule_id, [])
                }
            ) or [ts["testScenarioId"] for ts in test_scenarios[:1]]
            rows.append(
                {
                    "businessRequirementId": business_requirement["id"],
                    "functionalRequirementId": fr["id"],
                    "functionalRequirement": fr["title"],
                    "businessRuleIds": [r.rule_id for r in linked_rules],
                    "stage": stage,
                    "isoMessages": messages,
                    "testScenarioIds": tests,
                    "coverage": "COVERED" if linked_rules or messages else "NEEDS_REVIEW",
                }
            )
        return rows


def _actor_for(stage: str) -> str:
    return {
        "INITIATION": "Customer / channel",
        "CHANNEL_INTAKE": "Channel gateway",
        "PRE_VALIDATION": "Validation engine",
        "BUSINESS_VALIDATION": "Validation engine",
        "COMPLIANCE": "Financial crime screening",
        "ORCHESTRATION": "Payment orchestration",
        "MESSAGE_GENERATION": "Message engine",
        "CLEARING": "Clearing adapter",
        "CLEARING_RESPONSE": "Clearing system",
        "SETTLEMENT": "Settlement engine",
        "ACCOUNTING": "Accounting platform",
        "RECONCILIATION": "Reconciliation engine",
        "COMPLETION": "Payment orchestration",
    }.get(stage, "Payment orchestration")


def _output_for(stage: str, scheme: PaymentScheme) -> str:
    return {
        "INITIATION": "Payment record with references assigned",
        "CHANNEL_INTAKE": "Correlation identifier and audit entry",
        "PRE_VALIDATION": "Technical validation results",
        "BUSINESS_VALIDATION": "Business and scheme validation results",
        "COMPLIANCE": "Screening results and, on a hit, a blocked payment",
        "ORCHESTRATION": f"Routing decision to {scheme.clearing.clearing_system_name}",
        "MESSAGE_GENERATION": f"{scheme.messages.instruction_message.value} payload",
        "CLEARING": "Clearing transaction with a clearing reference",
        "CLEARING_RESPONSE": f"{scheme.messages.status_message.value} status report or a timeout",
        "SETTLEMENT": "Settlement transaction and reference",
        "ACCOUNTING": "Double-entry journal and camt.054 notification",
        "RECONCILIATION": "Reconciliation record with a classification",
        "COMPLETION": "Terminal payment status and audit trail",
    }.get(stage, "")


def _messages_for_stage(stage: str, scheme: PaymentScheme) -> list[str]:
    if stage == "MESSAGE_GENERATION":
        values = [scheme.messages.instruction_message.value]
        if scheme.messages.legacy_message:
            values.append(scheme.messages.legacy_message.value)
        return values
    if stage == "CLEARING_RESPONSE":
        return [
            scheme.messages.status_message.value,
            scheme.messages.status_request_message.value,
        ]
    if stage == "ACCOUNTING":
        return [scheme.messages.notification_message.value]
    if stage == "RECONCILIATION":
        return [
            scheme.messages.statement_message.value,
            scheme.messages.notification_message.value,
        ]
    if stage == "COMPLETION":
        return [
            scheme.messages.return_message.value,
            scheme.messages.cancellation_message.value,
            scheme.messages.resolution_message.value,
        ]
    return []


def _customer_impact(category: str) -> str:
    return {
        "VALIDATION": "Instruction refused at source; the customer can correct and resubmit.",
        "COMPLIANCE": "Payment held; the customer must be contacted carefully and within the "
        "constraints of the applicable disclosure rules.",
        "CLEARING": "Payment not made; any debit must be reversed and the customer informed.",
        "TIMEOUT": "Outcome unknown; the customer must be told the payment is being traced, not "
        "that it has failed.",
        "SETTLEMENT": "Possible funds-in-transit exposure for the bank; customer impact depends on "
        "whether the beneficiary was credited.",
        "ACCOUNTING": "No direct customer impact, but the bank's ledger is wrong until corrected.",
        "RECONCILIATION": "Usually no customer impact; a control failure the bank must clear.",
        "RETURN": "Funds come back; the customer must be re-credited and told why.",
        "INVESTIGATION": "Customer is waiting for an answer; response time is the service measure.",
    }.get(category, "To be assessed.")


def message_catalogue() -> list[dict]:
    return [
        {
            "messageType": message.value,
            "name": meta["name"],
            "isoIdentifier": meta["iso_identifier"],
            "direction": meta["direction"],
            "purpose": meta["purpose"],
        }
        for message, meta in MESSAGE_METADATA.items()
        if isinstance(message, MessageType)
    ]
