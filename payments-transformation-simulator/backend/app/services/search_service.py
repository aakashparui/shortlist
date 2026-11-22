"""Command-centre search.

Parses natural-ish operator input ("payment TXN-10293", "UETR abc...",
"find failed payments", "show unmatched reconciliations", "open pacs.008") and
returns navigable results. Pure lookup, no AI required.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import (
    Account,
    BusinessRule,
    ClearingTransaction,
    Investigation,
    Payment,
    PaymentMessage,
    PaymentParty,
    ReconciliationRecord,
    Scenario,
    SettlementTransaction,
    StatementEntry,
)
from app.domain.enums import MESSAGE_METADATA, MessageType, PaymentStatus
from app.domain.money import format_amount

UETR_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
AMOUNT_RE = re.compile(r"^-?\d+(\.\d+)?$")

FAILURE_STATUSES = [s.value for s in PaymentStatus if s.is_failure]


@dataclass(slots=True)
class SearchHit:
    kind: str
    title: str
    subtitle: str
    route: str
    badge: str | None = None
    score: int = 0

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "title": self.title,
            "subtitle": self.subtitle,
            "route": self.route,
            "badge": self.badge,
        }


INTENTS: tuple[tuple[str, tuple[str, ...], str, str], ...] = (
    (
        "FAILED_PAYMENTS",
        ("failed payments", "failures", "failed", "exceptions", "broken payments"),
        "Failed payments",
        "/payments?failuresOnly=true",
    ),
    (
        "UNMATCHED_RECONCILIATIONS",
        ("unmatched reconciliation", "unmatched reconciliations", "reconciliation breaks", "breaks"),
        "Reconciliation breaks",
        "/reconciliation?status=breaks",
    ),
    (
        "OPEN_INVESTIGATIONS",
        ("open investigations", "investigations", "investigation queue"),
        "Open investigations",
        "/investigations",
    ),
    (
        "TIMEOUTS",
        ("timeouts", "timed out", "timeout"),
        "Timed-out payments",
        "/payments?status=TIMED_OUT&status=INVESTIGATION_REQUIRED",
    ),
    ("SCENARIOS", ("scenarios", "scenario library", "demo"), "Scenario library", "/qa/scenarios"),
    ("RULES", ("rules", "rule engine", "rule book"), "Business rule explorer", "/system/rules"),
    ("EVENTS", ("event log", "events", "audit"), "Event log", "/system/events"),
    ("MT_MX", ("mt mx", "mt to mx", "mt103", "mapping"), "MT to MX mapping", "/messages/mt-mx"),
    ("NOSTRO", ("nostro", "vostro", "accounts", "balances"), "Accounts and positions", "/system/accounts"),
    ("BA", ("requirements", "ba", "traceability"), "BA workbench", "/ba/requirements"),
    ("TEST_CASES", ("test cases", "tests", "test case generator"), "Test cases", "/qa/test-cases"),
)


class SearchService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def search(self, query: str, limit: int = 12) -> list[dict]:
        raw = (query or "").strip()
        if not raw:
            return []
        lowered = raw.lower()
        token = self._strip_keywords(raw)
        hits: list[SearchHit] = []

        for _, phrases, title, route in INTENTS:
            if any(phrase in lowered for phrase in phrases):
                hits.append(
                    SearchHit(
                        kind="VIEW",
                        title=title,
                        subtitle="Open the view",
                        route=route,
                        badge="VIEW",
                        score=90,
                    )
                )

        message_match = self._message_type_from(lowered)
        if message_match is not None:
            meta = MESSAGE_METADATA[message_match]
            hits.append(
                SearchHit(
                    kind="MESSAGE_TYPE",
                    title=f"{message_match.value} - {meta['name']}",
                    subtitle=meta["purpose"],
                    route=f"/messages/explorer?type={message_match.value}",
                    badge="ISO 20022",
                    score=95,
                )
            )

        uetr = UETR_RE.search(raw)
        if uetr:
            token = uetr.group(0)

        if token:
            hits.extend(self._payment_hits(token))
            hits.extend(self._message_hits(token))
            hits.extend(self._reference_hits(token))
            hits.extend(self._investigation_hits(token))
            hits.extend(self._rule_hits(token))
            hits.extend(self._scenario_hits(token))
            hits.extend(self._account_hits(token))

        seen: set[tuple[str, str]] = set()
        unique: list[SearchHit] = []
        for hit in sorted(hits, key=lambda h: -h.score):
            key = (hit.kind, hit.route)
            if key in seen:
                continue
            seen.add(key)
            unique.append(hit)
        return [h.as_dict() for h in unique[:limit]]

    # ------------------------------------------------------------------
    def _strip_keywords(self, raw: str) -> str:
        cleaned = raw
        for word in (
            "payment",
            "payments",
            "show",
            "find",
            "open",
            "uetr",
            "e2e",
            "endtoendid",
            "reference",
            "search",
            "trace",
            "goto",
            "go to",
        ):
            cleaned = re.sub(rf"\b{word}\b", " ", cleaned, flags=re.I)
        return cleaned.strip(" :,-")

    def _message_type_from(self, lowered: str) -> MessageType | None:
        for message in MessageType:
            if message.value.lower() in lowered:
                return message
        return None

    def _payment_hits(self, token: str) -> list[SearchHit]:
        like = f"%{token}%"
        stmt = (
            select(Payment)
            .where(
                or_(
                    Payment.reference.ilike(like),
                    Payment.end_to_end_id.ilike(like),
                    Payment.instruction_id.ilike(like),
                    Payment.transaction_id.ilike(like),
                    Payment.uetr.ilike(like),
                    Payment.correlation_id.ilike(like),
                    Payment.id.in_(
                        select(PaymentParty.payment_id).where(
                            or_(
                                PaymentParty.name.ilike(like),
                                PaymentParty.iban.ilike(like),
                                PaymentParty.bic.ilike(like),
                            )
                        )
                    ),
                )
            )
            .order_by(Payment.created_at.desc())
            .limit(8)
        )
        rows = list(self.session.execute(stmt).scalars().unique())
        if not rows and AMOUNT_RE.match(token):
            rows = list(
                self.session.execute(
                    select(Payment)
                    .where(Payment.amount == token)
                    .order_by(Payment.created_at.desc())
                    .limit(8)
                )
                .scalars()
                .unique()
            )
        return [
            SearchHit(
                kind="PAYMENT",
                title=f"{row.reference} - {format_amount(row.amount, row.currency)}",
                subtitle=(
                    f"{row.scheme} | {row.status} | "
                    f"{(row.debtor.name if row.debtor else '?')} -> "
                    f"{(row.creditor.name if row.creditor else '?')}"
                ),
                route=f"/payments/{row.reference}",
                badge=row.status,
                score=100 if row.reference.lower() == token.lower() else 80,
            )
            for row in rows
        ]

    def _message_hits(self, token: str) -> list[SearchHit]:
        like = f"%{token}%"
        rows = list(
            self.session.execute(
                select(PaymentMessage)
                .where(PaymentMessage.message_id.ilike(like))
                .order_by(PaymentMessage.created_at.desc())
                .limit(5)
            ).scalars()
        )
        out: list[SearchHit] = []
        for row in rows:
            payment = self.session.get(Payment, row.payment_id)
            out.append(
                SearchHit(
                    kind="MESSAGE",
                    title=f"{row.message_type} {row.message_id}",
                    subtitle=f"{row.direction} | {row.state} | payment {payment.reference if payment else '?'}",
                    route=f"/payments/{payment.reference if payment else row.payment_id}?tab=messages",
                    badge=row.message_type,
                    score=85,
                )
            )
        return out

    def _reference_hits(self, token: str) -> list[SearchHit]:
        like = f"%{token}%"
        out: list[SearchHit] = []
        for row in self.session.execute(
            select(ClearingTransaction)
            .where(ClearingTransaction.clearing_reference.ilike(like))
            .limit(5)
        ).scalars():
            payment = self.session.get(Payment, row.payment_id)
            out.append(
                SearchHit(
                    kind="CLEARING",
                    title=f"Clearing {row.clearing_reference}",
                    subtitle=f"{row.status} | {row.clearing_system}",
                    route=f"/payments/{payment.reference if payment else row.payment_id}?tab=clearing",
                    badge="CLEARING",
                    score=86,
                )
            )
        for row in self.session.execute(
            select(SettlementTransaction)
            .where(SettlementTransaction.settlement_reference.ilike(like))
            .limit(5)
        ).scalars():
            payment = self.session.get(Payment, row.payment_id)
            out.append(
                SearchHit(
                    kind="SETTLEMENT",
                    title=f"Settlement {row.settlement_reference}",
                    subtitle=f"{row.status} | {row.settlement_amount} {row.settlement_currency}",
                    route=f"/payments/{payment.reference if payment else row.payment_id}?tab=settlement",
                    badge="SETTLEMENT",
                    score=86,
                )
            )
        for row in self.session.execute(
            select(ReconciliationRecord)
            .where(ReconciliationRecord.reference.ilike(like))
            .limit(5)
        ).scalars():
            out.append(
                SearchHit(
                    kind="RECONCILIATION",
                    title=f"Reconciliation {row.reference}",
                    subtitle=f"{row.status} | internal {row.internal_amount} {row.internal_currency}",
                    route=f"/reconciliation/{row.reference}",
                    badge=row.status,
                    score=86,
                )
            )
        for row in self.session.execute(
            select(StatementEntry)
            .where(
                or_(
                    StatementEntry.statement_reference.ilike(like),
                    StatementEntry.end_to_end_id.ilike(like),
                )
            )
            .limit(5)
        ).scalars():
            out.append(
                SearchHit(
                    kind="STATEMENT",
                    title=f"Statement entry {row.statement_reference}",
                    subtitle=(
                        f"{row.side} {row.amount} {row.currency} on {row.account_number}"
                        + (" (unmatched)" if row.is_orphan else "")
                    ),
                    route="/reconciliation?tab=statement",
                    badge="UNMATCHED" if row.is_orphan else "STATEMENT",
                    score=80,
                )
            )
        return out

    def _investigation_hits(self, token: str) -> list[SearchHit]:
        like = f"%{token}%"
        rows = list(
            self.session.execute(
                select(Investigation)
                .where(
                    or_(
                        Investigation.reference.ilike(like),
                        Investigation.title.ilike(like),
                        Investigation.reason.ilike(like),
                    )
                )
                .order_by(Investigation.opened_at.desc())
                .limit(5)
            ).scalars()
        )
        return [
            SearchHit(
                kind="INVESTIGATION",
                title=f"{row.reference} - {row.title}",
                subtitle=f"{row.status} | {row.reason} | {row.priority}",
                route=f"/investigations/{row.reference}",
                badge=row.status,
                score=88,
            )
            for row in rows
        ]

    def _rule_hits(self, token: str) -> list[SearchHit]:
        like = f"%{token}%"
        rows = list(
            self.session.execute(
                select(BusinessRule)
                .where(or_(BusinessRule.rule_id.ilike(like), BusinessRule.name.ilike(like)))
                .limit(5)
            ).scalars()
        )
        return [
            SearchHit(
                kind="RULE",
                title=f"{row.rule_id} - {row.name}",
                subtitle=f"{row.category} | {row.severity} | {'enabled' if row.enabled else 'disabled'}",
                route=f"/system/rules?ruleId={row.rule_id}",
                badge="RULE",
                score=84,
            )
            for row in rows
        ]

    def _scenario_hits(self, token: str) -> list[SearchHit]:
        like = f"%{token}%"
        rows = list(
            self.session.execute(
                select(Scenario)
                .where(or_(Scenario.code.ilike(like), Scenario.title.ilike(like)))
                .limit(5)
            ).scalars()
        )
        return [
            SearchHit(
                kind="SCENARIO",
                title=f"{row.code} - {row.title}",
                subtitle=f"{row.category} | {row.scheme} | expects {row.expected_status}",
                route=f"/qa/scenarios?code={row.code}",
                badge="SCENARIO",
                score=82,
            )
            for row in rows
        ]

    def _account_hits(self, token: str) -> list[SearchHit]:
        like = f"%{token}%"
        rows = list(
            self.session.execute(
                select(Account)
                .where(
                    or_(
                        Account.account_number.ilike(like),
                        Account.iban.ilike(like),
                        Account.name.ilike(like),
                    )
                )
                .limit(5)
            ).scalars()
        )
        return [
            SearchHit(
                kind="ACCOUNT",
                title=f"{row.account_number} - {row.name}",
                subtitle=f"{row.account_type} | {format_amount(row.balance, row.currency)}",
                route=f"/system/accounts?account={row.account_number}",
                badge=row.account_type,
                score=78,
            )
            for row in rows
        ]
