"""Compliance screening simulation.

SIMULATION BEHAVIOUR. Real sanctions screening uses licensed watch-list data,
fuzzy name matching, alert queues and a human disposition workflow. This engine
screens against a small, entirely fictional list so that an embargo or sanctions
hit can be reproduced deterministically in a demo.

Screening results are written to the same `validation_result` table as rule-book
results, with category COMPLIANCE, so the investigation view shows one unified
list of checks.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import Payment, ValidationResult
from app.domain.enums import Severity, StageKey, ValidationCategory, ValidationStatus
from app.domain.identifiers_bank import bic_country

logger = get_logger(__name__)

# --- fictional screening data ------------------------------------------------
EMBARGOED_COUNTRIES: dict[str, str] = {
    "ZZ": "Republic of Zedland (fictional embargo jurisdiction)",
    "XA": "Arcadia Protectorate (fictional embargo jurisdiction)",
    "QX": "Quorex Territory (fictional embargo jurisdiction)",
}

SANCTIONED_PARTIES: dict[str, str] = {
    "VOLKOV TRADING LLC": "SIM-SDN-0001 - fictional designated entity",
    "ORION ARMS EXPORT": "SIM-SDN-0002 - fictional designated entity",
    "NORDWIND SHIPPING AG": "SIM-SDN-0003 - fictional designated vessel operator",
    "KASPAR DELTA HOLDINGS": "SIM-SDN-0004 - fictional designated entity",
}

SANCTIONED_BICS: dict[str, str] = {
    "ZZZZZZ22XXX": "SIM-FI-0001 - fictional designated financial institution",
    "QXBKQX22XXX": "SIM-FI-0002 - fictional designated financial institution",
}

HIGH_RISK_KEYWORDS: dict[str, str] = {
    "ARMS": "Weapons-related remittance wording",
    "WEAPON": "Weapons-related remittance wording",
    "URANIUM": "Dual-use goods wording",
    "CRYPTO MIXER": "Illicit finance typology wording",
    "CASH FOR": "Structuring typology wording",
}

PEP_NAMES: dict[str, str] = {
    "MARGARETHE DUBOIS": "SIM-PEP-0001 - fictional politically exposed person",
    "SAMUEL OKONKWO": "SIM-PEP-0002 - fictional politically exposed person",
}

RULE_METADATA: dict[str, dict[str, str]] = {
    "COMP-EMB-001": {
        "name": "Embargo jurisdiction screening",
        "description": "Blocks payments touching an embargoed jurisdiction.",
        "severity": Severity.FATAL.value,
    },
    "COMP-SANC-001": {
        "name": "Sanctions party screening",
        "description": "Blocks payments where a party matches a designated entity.",
        "severity": Severity.FATAL.value,
    },
    "COMP-SANC-002": {
        "name": "Sanctions institution screening",
        "description": "Blocks payments routed through a designated financial institution.",
        "severity": Severity.FATAL.value,
    },
    "COMP-AML-001": {
        "name": "High-risk remittance wording",
        "description": "Raises an alert for remittance wording associated with high-risk typologies.",
        "severity": Severity.ERROR.value,
    },
    "COMP-PEP-001": {
        "name": "Politically exposed person screening",
        "description": "Flags a PEP match for enhanced due diligence; does not block.",
        "severity": Severity.WARNING.value,
    },
}


@dataclass(slots=True)
class ComplianceHit:
    rule_id: str
    match_value: str
    list_reference: str
    detail: str
    blocking: bool


@dataclass(slots=True)
class ComplianceOutcome:
    blocked: bool
    hits: list[ComplianceHit]
    results: list[ValidationResult]
    screened_values: list[str]

    @property
    def blocking_hit(self) -> ComplianceHit | None:
        for hit in self.hits:
            if hit.blocking:
                return hit
        return None


class ComplianceEngine:
    """Deterministic screening over fictional lists."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def screen(self, payment: Payment, *, forced: dict | None = None) -> ComplianceOutcome:
        started = time.perf_counter()
        hits: list[ComplianceHit] = []
        screened: list[str] = []

        debtor = payment.debtor
        creditor = payment.creditor
        names = [
            (debtor.name if debtor else "") or "",
            (creditor.name if creditor else "") or "",
        ]
        countries = [
            (debtor.country if debtor else "") or "",
            (creditor.country if creditor else "") or "",
            bic_country(creditor.bic if creditor else None),
        ]
        bics = [
            (debtor.bic if debtor else "") or "",
            (creditor.bic if creditor else "") or "",
        ]
        remittance = (payment.remittance_information or "").upper()
        screened.extend([n for n in names if n])
        screened.extend([c for c in countries if c])
        screened.extend([b for b in bics if b])

        # Forced hits come from the failure-injection engine. They inject a real
        # list entry for this payment rather than faking the screening result.
        forced = forced or {}
        if forced.get("embargo_country"):
            country = str(forced["embargo_country"]).upper()
            hits.append(
                ComplianceHit(
                    rule_id="COMP-EMB-001",
                    match_value=country,
                    list_reference=EMBARGOED_COUNTRIES.get(country, "SIM-EMB-INJECTED"),
                    detail=f"Injected embargo jurisdiction match on {country}.",
                    blocking=True,
                )
            )
        if forced.get("sanctioned_party"):
            name = str(forced["sanctioned_party"]).upper()
            hits.append(
                ComplianceHit(
                    rule_id="COMP-SANC-001",
                    match_value=name,
                    list_reference=SANCTIONED_PARTIES.get(name, "SIM-SDN-INJECTED"),
                    detail=f"Injected designated-party match on '{name}'.",
                    blocking=True,
                )
            )

        for country in {c.upper() for c in countries if c}:
            if country in EMBARGOED_COUNTRIES and not any(
                h.rule_id == "COMP-EMB-001" and h.match_value == country for h in hits
            ):
                hits.append(
                    ComplianceHit(
                        rule_id="COMP-EMB-001",
                        match_value=country,
                        list_reference=EMBARGOED_COUNTRIES[country],
                        detail=f"Party country {country} is on the embargo list.",
                        blocking=True,
                    )
                )

        for name in names:
            upper = name.upper().strip()
            if upper in SANCTIONED_PARTIES and not any(
                h.rule_id == "COMP-SANC-001" and h.match_value == upper for h in hits
            ):
                hits.append(
                    ComplianceHit(
                        rule_id="COMP-SANC-001",
                        match_value=upper,
                        list_reference=SANCTIONED_PARTIES[upper],
                        detail=f"Exact name match against designated entity '{upper}'.",
                        blocking=True,
                    )
                )
            if upper in PEP_NAMES:
                hits.append(
                    ComplianceHit(
                        rule_id="COMP-PEP-001",
                        match_value=upper,
                        list_reference=PEP_NAMES[upper],
                        detail="PEP match: enhanced due diligence recorded, payment not blocked.",
                        blocking=False,
                    )
                )

        for bic in bics:
            upper = bic.upper().strip()
            if upper and upper in SANCTIONED_BICS:
                hits.append(
                    ComplianceHit(
                        rule_id="COMP-SANC-002",
                        match_value=upper,
                        list_reference=SANCTIONED_BICS[upper],
                        detail=f"Agent BIC {upper} is a designated institution.",
                        blocking=True,
                    )
                )

        for keyword, reason in HIGH_RISK_KEYWORDS.items():
            if keyword in remittance:
                hits.append(
                    ComplianceHit(
                        rule_id="COMP-AML-001",
                        match_value=keyword,
                        list_reference="SIM-TYPOLOGY-001",
                        detail=f"{reason} detected in remittance information.",
                        blocking=True,
                    )
                )

        duration_ms = int((time.perf_counter() - started) * 1000)
        results = self._persist(payment, hits, screened, duration_ms, injected=bool(forced))
        blocked = any(h.blocking for h in hits)
        logger.info(
            "compliance screening complete",
            extra={
                "payment_reference": payment.reference,
                "hit_count": len(hits),
                "blocked": blocked,
            },
        )
        return ComplianceOutcome(blocked=blocked, hits=hits, results=results, screened_values=screened)

    def _persist(
        self,
        payment: Payment,
        hits: list[ComplianceHit],
        screened: list[str],
        duration_ms: int,
        injected: bool,
    ) -> list[ValidationResult]:
        from app.engines.validation.rules import utc_now

        now = utc_now()
        results: list[ValidationResult] = []
        hit_rule_ids = {h.rule_id for h in hits}

        for hit in hits:
            meta = RULE_METADATA[hit.rule_id]
            results.append(
                ValidationResult(
                    payment_id=payment.id,
                    run_id=1,
                    rule_id=hit.rule_id,
                    rule_name=meta["name"],
                    category=ValidationCategory.COMPLIANCE.value,
                    severity=meta["severity"],
                    status=ValidationStatus.FAILED.value,
                    stage=StageKey.COMPLIANCE.value,
                    message=hit.detail,
                    field="party",
                    actual_value=hit.match_value,
                    expected_value="no match on any screening list",
                    iso_reason_code="RR04" if hit.blocking else None,
                    remediation=(
                        "Escalate to the financial-crime team. The payment must not be released "
                        "until the alert is dispositioned."
                        if hit.blocking
                        else "Record enhanced due diligence evidence; no release restriction."
                    ),
                    executed_at=now,
                    duration_ms=duration_ms,
                    injected=injected,
                )
            )

        for rule_id, meta in RULE_METADATA.items():
            if rule_id in hit_rule_ids:
                continue
            results.append(
                ValidationResult(
                    payment_id=payment.id,
                    run_id=1,
                    rule_id=rule_id,
                    rule_name=meta["name"],
                    category=ValidationCategory.COMPLIANCE.value,
                    severity=meta["severity"],
                    status=ValidationStatus.PASSED.value,
                    stage=StageKey.COMPLIANCE.value,
                    message="No match against the screening list.",
                    field="party",
                    actual_value=", ".join(screened[:4]) if screened else None,
                    expected_value="no match on any screening list",
                    executed_at=now,
                    duration_ms=duration_ms,
                )
            )

        for result in results:
            self.session.add(result)
        self.session.flush()
        return results
