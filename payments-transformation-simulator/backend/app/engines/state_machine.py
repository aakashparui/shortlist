"""Payment state machine.

The backend owns the state. Every transition is checked against this table, and
an illegal transition raises rather than being silently applied — that is what
makes "retry" a controlled operation instead of a way to turn a failed payment
into a successful one.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.enums import PaymentStatus as S

TRANSITIONS: dict[S, frozenset[S]] = {
    S.DRAFT: frozenset({S.INITIATED, S.CANCELLED}),
    S.INITIATED: frozenset({S.VALIDATING, S.CANCELLED}),
    S.VALIDATING: frozenset({S.VALIDATED, S.REJECTED}),
    S.VALIDATED: frozenset({S.COMPLIANCE_CHECK, S.REJECTED, S.CANCELLED}),
    S.COMPLIANCE_CHECK: frozenset({S.MESSAGE_GENERATED, S.BLOCKED, S.REJECTED}),
    S.MESSAGE_GENERATED: frozenset({S.SENT_TO_CLEARING, S.REJECTED, S.CANCELLED, S.INVESTIGATION_REQUIRED}),
    S.SENT_TO_CLEARING: frozenset(
        {
            S.CLEARING_ACCEPTED,
            S.CLEARING_REJECTED,
            S.TIMED_OUT,
            S.INVESTIGATION_REQUIRED,
            S.CANCELLED,
        }
    ),
    S.CLEARING_ACCEPTED: frozenset(
        {S.SETTLEMENT_PENDING, S.SETTLED, S.SETTLEMENT_FAILED, S.INVESTIGATION_REQUIRED, S.RETURNED}
    ),
    S.CLEARING_REJECTED: frozenset({S.REVERSED, S.REPROCESSING, S.INVESTIGATION_REQUIRED}),
    S.TIMED_OUT: frozenset({S.INVESTIGATION_REQUIRED, S.REPROCESSING, S.CLEARING_ACCEPTED, S.CLEARING_REJECTED}),
    S.INVESTIGATION_REQUIRED: frozenset(
        {
            S.REPROCESSING,
            S.CLEARING_ACCEPTED,
            S.CLEARING_REJECTED,
            S.SETTLED,
            S.SETTLEMENT_PENDING,
            S.RECONCILED,
            S.COMPLETED,
            S.CANCELLED,
            S.RETURNED,
            S.REVERSED,
            S.RECONCILIATION_BREAK,
            S.ACCOUNTING_BREAK,
        }
    ),
    S.REPROCESSING: frozenset(
        {S.VALIDATING, S.MESSAGE_GENERATED, S.SENT_TO_CLEARING, S.REJECTED, S.CANCELLED}
    ),
    S.SETTLEMENT_PENDING: frozenset({S.SETTLED, S.SETTLEMENT_FAILED, S.INVESTIGATION_REQUIRED}),
    S.SETTLED: frozenset({S.ACCOUNTED, S.ACCOUNTING_BREAK, S.INVESTIGATION_REQUIRED, S.RETURNED}),
    S.SETTLEMENT_FAILED: frozenset({S.INVESTIGATION_REQUIRED, S.REPROCESSING, S.REVERSED}),
    S.ACCOUNTED: frozenset(
        {S.RECONCILED, S.RECONCILIATION_BREAK, S.INVESTIGATION_REQUIRED, S.RETURNED, S.COMPLETED}
    ),
    S.ACCOUNTING_BREAK: frozenset({S.INVESTIGATION_REQUIRED, S.ACCOUNTED, S.REVERSED, S.RECONCILIATION_BREAK}),
    S.RECONCILED: frozenset({S.COMPLETED, S.RETURNED, S.INVESTIGATION_REQUIRED}),
    S.RECONCILIATION_BREAK: frozenset({S.INVESTIGATION_REQUIRED, S.RECONCILED, S.COMPLETED}),
    S.COMPLETED: frozenset({S.RETURNED, S.REVERSED, S.INVESTIGATION_REQUIRED}),
    S.REJECTED: frozenset({S.REPROCESSING}),
    S.BLOCKED: frozenset({S.REJECTED, S.CANCELLED, S.REPROCESSING, S.INVESTIGATION_REQUIRED}),
    S.CANCELLED: frozenset(),
    S.RETURNED: frozenset({S.REVERSED, S.INVESTIGATION_REQUIRED}),
    S.REVERSED: frozenset({S.INVESTIGATION_REQUIRED}),
}


class IllegalTransitionError(Exception):
    def __init__(self, current: S, target: S) -> None:
        super().__init__(
            f"Transition {current.value} -> {target.value} is not permitted by the payment state machine."
        )
        self.current = current
        self.target = target
        self.allowed = sorted(s.value for s in TRANSITIONS.get(current, frozenset()))


@dataclass(frozen=True, slots=True)
class TransitionCheck:
    allowed: bool
    reason: str | None = None


def can_transition(current: S | str, target: S | str) -> TransitionCheck:
    cur = S(current)
    tgt = S(target)
    if cur == tgt:
        return TransitionCheck(True)
    permitted = TRANSITIONS.get(cur, frozenset())
    if tgt in permitted:
        return TransitionCheck(True)
    return TransitionCheck(
        False,
        f"{cur.value} can only move to: {', '.join(sorted(s.value for s in permitted)) or '(terminal)'}",
    )


def assert_transition(current: S | str, target: S | str) -> None:
    check = can_transition(current, target)
    if not check.allowed:
        raise IllegalTransitionError(S(current), S(target))


def allowed_targets(current: S | str) -> list[str]:
    return sorted(s.value for s in TRANSITIONS.get(S(current), frozenset()))


def graph() -> list[dict]:
    """Serialise the state machine for the UI / documentation."""
    return [
        {
            "from": state.value,
            "to": sorted(s.value for s in targets),
            "isTerminal": not targets,
            "isFailure": state.is_failure,
        }
        for state, targets in TRANSITIONS.items()
    ]
