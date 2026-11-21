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
from datetime import UTC, date, datetime

_ALNUM = string.ascii_uppercase + string.digits
_lock = threading.Lock()
_counters: dict[str, int] = {}


def _next(prefix: str, start: int = 1) -> int:
    with _lock:
        value = _counters.get(prefix, start - 1) + 1
        _counters[prefix] = value
        return value


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
    return f"TXN-{_next('TXN', 10001)}"


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
    return f"ACC-{_next('ACC', 500001)}"


def accounting_entry_id(rng: random.Random | None = None) -> str:
    return f"GL-{_next('GL', 900001)}"


def statement_entry_reference(rng: random.Random | None = None) -> str:
    return f"STMT-{_next('STMT', 8801)}"


def reconciliation_reference(rng: random.Random | None = None) -> str:
    return f"RECON-{_next('RECON', 4001)}"


def investigation_reference(rng: random.Random | None = None) -> str:
    return f"INV-{_next('INV', 7001)}"


def scenario_execution_reference(rng: random.Random | None = None) -> str:
    return f"RUN-{_next('RUN', 1)}"


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
