"""Structured logging must never crash the code that is logging."""

from __future__ import annotations

import json
import logging

from app.core.logging import (
    ContextFilter,
    JsonFormatter,
    SafeLogger,
    correlation_id_var,
    get_logger,
    payment_id_var,
    request_id_var,
)


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []
        self.addFilter(ContextFilter())
        self.setFormatter(JsonFormatter())

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)
        self.format(record)


def _logger_with_capture(name: str) -> tuple[logging.Logger, _Capture]:
    logger = get_logger(name)
    handler = _Capture()
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    return logger, handler


def test_get_logger_returns_a_safe_logger() -> None:
    assert isinstance(get_logger("app.test.safe"), SafeLogger)


def test_reserved_extra_keys_do_not_raise() -> None:
    logger, handler = _logger_with_capture("app.test.reserved")
    # 'created', 'module' and 'message' all collide with LogRecord attributes.
    logger.info("seeded", extra={"created": 37, "updated": 0, "module": "seed", "message": "x"})
    assert len(handler.records) == 1
    record = handler.records[0]
    assert record.field_created == 37
    assert record.updated == 0
    assert record.getMessage() == "seeded"


def test_json_formatter_includes_context_and_extras() -> None:
    logger, handler = _logger_with_capture("app.test.json")
    request_id_var.set("req-1")
    correlation_id_var.set("CORR-1")
    payment_id_var.set("TXN-10001")
    try:
        logger.info("payment executed", extra={"stage": "CLEARING", "created": 2})
    finally:
        request_id_var.set(None)
        correlation_id_var.set(None)
        payment_id_var.set(None)

    payload = json.loads(JsonFormatter().format(handler.records[0]))
    assert payload["message"] == "payment executed"
    assert payload["request_id"] == "req-1"
    assert payload["correlation_id"] == "CORR-1"
    assert payload["payment_id"] == "TXN-10001"
    assert payload["stage"] == "CLEARING"
    assert payload["field_created"] == 2
    assert payload["service"] == "payments-simulator"


def test_unserialisable_extras_are_repr_ed_not_dropped() -> None:
    logger, handler = _logger_with_capture("app.test.repr")

    class Opaque:
        def __repr__(self) -> str:
            return "<opaque>"

    logger.info("odd value", extra={"thing": Opaque()})
    payload = json.loads(JsonFormatter().format(handler.records[0]))
    assert payload["thing"] == "<opaque>"


def test_seeding_logs_without_raising(db_session) -> None:  # noqa: ANN001
    """Regression: the seed summary contains a 'created' key."""
    from app.seed import seed_static_data

    summary = seed_static_data(db_session)
    assert summary["rules"]["created"] >= 0
    assert "banks" in summary["reference"]
