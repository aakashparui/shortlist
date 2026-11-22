"""Identifier and reference generation.

Correlation is the backbone of the simulator: every artefact a payment produces
carries identifiers that let an investigator walk from a bank statement line all
the way back to the original customer instruction.

All identifiers are fictional. UETR values follow the RFC 4122 version-4 shape
used by SWIFT gpi but are generated locally and are not registered anywhere.
"""

from __future__ import annotations

import random
import string
import threading
import uuid
from collections.abc import Mapping
from datetime import UTC, date, datetime

_ALNUM = string.ascii_uppercase + string.digits
_lock = threading.Lock()
_counters: dict[str, int] = {}

# Every counter-backed sequence, and the number it starts from on an empty
# database. Declared in one place because each entry must also be primed from
# the database at startup -- see `app.db.bootstrap.prime_sequences`, and the
# test that asserts the two lists cannot drift apart.
SEQUENCE_STARTS: dict[str, int] = {
    "TXN": 10001,
    "ACC": 500001,
    "GL": 900001,
    "STMT": 8801,
    "RECON": 4001,
    "INV": 7001,
    "RUN": 1,
}


def _next(prefix: str) -> int:
    with _lock:
        value = _counters.get(prefix, SEQUENCE_STARTS[prefix] - 1) + 1
        _counters[prefix] = value
        return value


def prime_counters(highest: Mapping[str, int]) -> None:
    """Advance each sequence past the values already stored.

    These counters live in process memory, so they restart when the process
    does. Without priming, the first payment created after a restart is handed
    `TXN-10001` again and the insert fails on the unique constraint -- and for
    the sequences that carry no unique constraint (`ACC`, `GL`, `STMT`) it is
    worse than a failure: the reference silently duplicates one an investigator
    is supposed to be able to trace back to a single artefact.

    Only ever moves a sequence forward, so priming twice is harmless.
    """
    with _lock:
        for prefix, value in highest.items():
            if prefix in SEQUENCE_STARTS and value > _counters.get(prefix, 0):
                _counters[prefix] = value


def reset_counters() -> None:
    """Test helper: make identifier sequences deterministic again."""
    with _lock:
        _counters.clear()


def utcnow() -> datetime:
    return datetime.now(UTC)


def _rand(n: int, rng: random.Random | None = None) -> str:
    r = rng or random
    return "".join(r.choice(_ALNUM) for _ in range(n))


def payment_reference(rng: random.Random | None = None) -> str:
    return f"TXN-{_next('TXN')}"


def correlation_id() -> str:
    return f"CORR-{uuid.uuid4().hex[:16].upper()}"


def instruction_id(rng: random.Random | None = None) -> str:
    return f"INSTR{_rand(12, rng)}"


def end_to_end_id(rng: random.Random | None = None) -> str:
    return f"E2E{_rand(14, rng)}"


def transaction_id(rng: random.Random | None = None) -> str:
    return f"TXID{_rand(14, rng)}"


def message_id(message_type: str, rng: random.Random | None = None) -> str:
    stamp = utcnow().strftime("%Y%m%d")
    token = message_type.replace(".", "").upper()
    return f"{token}-{stamp}-{_rand(10, rng)}"


def uetr() -> str:
    """Unique End-to-end Transaction Reference (UUIDv4 shape)."""
    return str(uuid.uuid4())


def clearing_reference(scheme: str, rng: random.Random | None = None) -> str:
    prefix = {"SIC_INSTANT": "SIC", "SEPA_INSTANT": "SCT", "SWIFT_CROSS_BORDER": "SWF"}.get(
        scheme, "CLR"
    )
    return f"{prefix}-{utcnow().strftime('%y%j')}-{_rand(8, rng)}"


def settlement_reference(rng: random.Random | None = None) -> str:
    return f"STL-{utcnow().strftime('%y%m%d')}-{_rand(8, rng)}"


def accounting_reference(rng: random.Random | None = None) -> str:
    return f"ACC-{_next('ACC')}"


def accounting_entry_id(rng: random.Random | None = None) -> str:
    return f"GL-{_next('GL')}"


def statement_entry_reference(rng: random.Random | None = None) -> str:
    return f"STMT-{_next('STMT')}"


def reconciliation_reference(rng: random.Random | None = None) -> str:
    return f"RECON-{_next('RECON')}"


def investigation_reference(rng: random.Random | None = None) -> str:
    return f"INV-{_next('INV')}"


def scenario_execution_reference(rng: random.Random | None = None) -> str:
    return f"RUN-{_next('RUN')}"


def request_id() -> str:
    return uuid.uuid4().hex


def iso_datetime(value: datetime | None = None) -> str:
    """ISO 20022 ISODateTime."""
    dt = value or utcnow()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def iso_date(value: date | datetime | None = None) -> str:
    dt = value or utcnow()
    if isinstance(dt, datetime):
        return dt.date().isoformat()
    return dt.isoformat()
