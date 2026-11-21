"""Seeding must be idempotent: a restart must not duplicate or crash."""

from __future__ import annotations

from sqlalchemy import func, select

from app.db.models import Account, Bank, BusinessRule, Scenario
from app.seed import seed_static_data


def _counts(session) -> dict[str, int]:  # noqa: ANN001
    return {
        "banks": session.execute(select(func.count(Bank.id))).scalar_one(),
        "accounts": session.execute(select(func.count(Account.id))).scalar_one(),
        "rules": session.execute(select(func.count(BusinessRule.id))).scalar_one(),
        "scenarios": session.execute(select(func.count(Scenario.id))).scalar_one(),
    }


def test_second_seed_run_adds_nothing(db_session) -> None:  # noqa: ANN001
    before = _counts(db_session)
    summary = seed_static_data(db_session)
    after = _counts(db_session)
    assert after == before
    assert summary["reference"]["banks"] == 0
    assert summary["reference"]["accounts"] == 0
    assert summary["rules"]["created"] == 0
    assert summary["rules"]["updated"] > 0
    assert summary["scenarios"]["created"] == 0


def test_seeding_three_times_is_stable(db_session) -> None:  # noqa: ANN001
    seed_static_data(db_session)
    seed_static_data(db_session)
    counts = _counts(db_session)
    assert counts["banks"] == 16
    assert counts["scenarios"] == 20
    assert counts["accounts"] > 20


def test_rule_sync_preserves_an_operator_disable(db_session) -> None:  # noqa: ANN001
    rule = db_session.query(BusinessRule).filter_by(rule_id="SIC-AMOUNT-001").one()
    rule.enabled = False
    db_session.flush()

    seed_static_data(db_session)

    db_session.refresh(rule)
    assert rule.enabled is False, "re-syncing the rule book must not silently re-enable a rule"


def test_rule_sync_refreshes_metadata(db_session) -> None:  # noqa: ANN001
    rule = db_session.query(BusinessRule).filter_by(rule_id="SIC-AMOUNT-001").one()
    rule.description = "stale text"
    db_session.flush()

    seed_static_data(db_session)

    db_session.refresh(rule)
    assert rule.description != "stale text"
    assert "ceiling" in rule.description
