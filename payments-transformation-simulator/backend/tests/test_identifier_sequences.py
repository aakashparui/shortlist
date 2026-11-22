"""Identifier sequences must survive a process restart.

The counters behind `TXN-`, `INV-`, `RECON-` and friends live in process
memory. Every test in the suite starts from an empty database, so a sequence
that restarts from its start value looks perfectly correct here -- and then
fails the moment the application is restarted against a database that already
holds references. That is exactly what happened: a restart handed `TXN-10002`
to a book that already ran to `TXN-10035`, and the insert died on
`UNIQUE constraint failed: payment.reference`.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.api.schemas import PaymentCreate
from app.core import identifiers
from app.core.identifiers import SEQUENCE_STARTS, prime_counters, reset_counters
from app.db import bootstrap
from app.db.bootstrap import SEQUENCE_SOURCES, prime_sequences
from app.db.models import Payment

from .conftest import sic_payload


def _create(payments, **overrides):  # noqa: ANN001, ANN003
    return payments.create(PaymentCreate.model_validate(sic_payload(**overrides)))


class TestEverySequenceIsPrimed:
    """The declared sequences and the primed sequences cannot drift apart."""

    def test_every_sequence_has_a_persistence_source(self) -> None:
        declared = set(SEQUENCE_STARTS)
        primed = {prefix for prefix, _ in SEQUENCE_SOURCES}
        missing = declared - primed
        assert not missing, (
            "these sequences are allocated but never primed from the database, so they "
            "restart with the process and collide with stored references: "
            f"{sorted(missing)}. Add each to app.db.bootstrap.SEQUENCE_SOURCES."
        )

    def test_no_source_refers_to_an_unknown_sequence(self) -> None:
        declared = set(SEQUENCE_STARTS)
        primed = {prefix for prefix, _ in SEQUENCE_SOURCES}
        assert not primed - declared, (
            f"SEQUENCE_SOURCES names sequences that do not exist: {sorted(primed - declared)}"
        )

    def test_every_declared_prefix_allocates(self) -> None:
        """A generator calling _next with an undeclared prefix would KeyError."""
        reset_counters()
        for prefix, start in SEQUENCE_STARTS.items():
            assert identifiers._next(prefix) == start
        reset_counters()


class TestPrimingBehaviour:
    def test_priming_only_moves_a_sequence_forward(self) -> None:
        reset_counters()
        prime_counters({"TXN": 10050})
        prime_counters({"TXN": 10020})
        assert identifiers.payment_reference() == "TXN-10051"
        reset_counters()

    def test_priming_is_idempotent(self) -> None:
        reset_counters()
        prime_counters({"TXN": 10050})
        prime_counters({"TXN": 10050})
        assert identifiers.payment_reference() == "TXN-10051"
        reset_counters()

    def test_unknown_prefixes_are_ignored(self) -> None:
        reset_counters()
        prime_counters({"NOPE": 999})
        assert "NOPE" not in identifiers._counters
        reset_counters()

    def test_empty_database_leaves_the_start_values_alone(self, db_session) -> None:  # noqa: ANN001
        reset_counters()
        assert prime_sequences(db_session) == {}
        assert identifiers.payment_reference() == f"TXN-{SEQUENCE_STARTS['TXN']}"


class TestRestartAgainstAPopulatedDatabase:
    """The regression itself, reproduced and then prevented."""

    def test_creation_after_a_restart_does_not_reuse_a_reference(self, payments, db_session) -> None:  # noqa: ANN001
        first = _create(payments)
        db_session.flush()
        assert first.reference == f"TXN-{SEQUENCE_STARTS['TXN']}"

        # Exactly what a restart does: the rows survive, the counters do not.
        reset_counters()
        prime_sequences(db_session)

        second = _create(payments)
        db_session.flush()
        assert second.reference != first.reference
        stored = set(db_session.execute(select(Payment.reference)).scalars())
        assert len(stored) == 2

    def test_restart_without_priming_still_collides(self, payments, db_session) -> None:  # noqa: ANN001
        """Proves the test above is actually exercising the priming.

        Without this, a change that silently stopped priming would leave the
        previous test passing for the wrong reason on a fresh database.
        """
        _create(payments)
        db_session.flush()

        reset_counters()  # a restart, with no priming

        with pytest.raises(Exception) as caught:  # noqa: PT011 - dialect-specific
            _create(payments)
            db_session.flush()
        assert "reference" in str(caught.value).lower()
        db_session.rollback()

    def test_sequences_are_primed_to_the_highest_stored_value(self, payments, db_session) -> None:  # noqa: ANN001
        for _ in range(3):
            _create(payments)
        db_session.flush()
        start = SEQUENCE_STARTS["TXN"]

        reset_counters()
        highest = prime_sequences(db_session)
        assert highest["TXN"] == start + 2
        assert identifiers.payment_reference() == f"TXN-{start + 3}"

    def test_a_non_numeric_suffix_is_ignored(self, payments, db_session) -> None:  # noqa: ANN001
        """Hand-written or imported references must not break startup."""
        payment = _create(payments)
        db_session.flush()
        payment.reference = "TXN-MANUAL"
        db_session.flush()

        reset_counters()
        assert prime_sequences(db_session) == {}


class TestResetClearsTheSequences:
    def test_reset_database_rewinds_the_counters(self, monkeypatch) -> None:  # noqa: ANN001
        prime_counters({"TXN": 10100})
        dropped: list[bool] = []
        monkeypatch.setattr(bootstrap.Base.metadata, "drop_all", lambda **_: dropped.append(True))
        monkeypatch.setattr(bootstrap.Base.metadata, "create_all", lambda **_: None)
        monkeypatch.setattr(bootstrap, "close_all_sessions", lambda: None)

        bootstrap.reset_database()

        assert dropped, "expected the schema to be dropped"
        assert identifiers.payment_reference() == f"TXN-{SEQUENCE_STARTS['TXN']}"
