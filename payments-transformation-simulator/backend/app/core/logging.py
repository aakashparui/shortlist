"""Structured logging with request/correlation context.

Every log line carries request_id and (where known) correlation_id and payment_id,
so a single payment can be traced across every subsystem in the log stream.
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import time
from typing import Any

from app.core.config import settings

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
correlation_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)
payment_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("payment_id", default=None)

_RESERVED = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename", "module",
    "exc_info", "exc_text", "stack_info", "lineno", "funcName", "created", "msecs",
    "relativeCreated", "thread", "threadName", "processName", "process", "taskName",
    "message", "asctime",
}


class SafeLogger(logging.Logger):
    """A logger whose `extra` can never crash the caller.

    `logging` raises if an `extra` key collides with a LogRecord attribute, so a
    perfectly reasonable structured field such as `created` or `module` would
    take down whatever was being logged. Colliding keys are prefixed instead.
    """

    def makeRecord(  # noqa: PLR0913
        self,
        name,  # noqa: ANN001
        level,  # noqa: ANN001
        fn,  # noqa: ANN001
        lno,  # noqa: ANN001
        msg,  # noqa: ANN001
        args,  # noqa: ANN001
        exc_info,  # noqa: ANN001
        func=None,  # noqa: ANN001
        extra=None,  # noqa: ANN001
        sinfo=None,  # noqa: ANN001
    ) -> logging.LogRecord:
        if extra:
            extra = {(f"field_{k}" if k in _RESERVED else k): v for k, v in extra.items()}
        return super().makeRecord(name, level, fn, lno, msg, args, exc_info, func, extra, sinfo)


# Installed at import time so that every `get_logger` call in the application
# returns a SafeLogger, including in modules imported before configure_logging().
logging.setLoggerClass(SafeLogger)


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        record.correlation_id = correlation_id_var.get()
        record.payment_id = payment_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "service": "payments-simulator",
            "logger": record.name,
            "operation": record.funcName,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
            "correlation_id": getattr(record, "correlation_id", None),
            "payment_id": getattr(record, "payment_id", None),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and key not in payload and not key.startswith("_"):
                try:
                    json.dumps(value)
                except (TypeError, ValueError):
                    value = repr(value)
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps({k: v for k, v in payload.items() if v is not None})


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = (
            f"{time.strftime('%H:%M:%S', time.localtime(record.created))}.{int(record.msecs):03d} "
            f"{record.levelname:<7} {record.name:<34} {record.getMessage()}"
        )
        pid = getattr(record, "payment_id", None)
        if pid:
            base += f"  [payment={pid}]"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def configure_logging() -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if settings.LOG_FORMAT == "json" else TextFormatter())
    handler.addFilter(ContextFilter())
    root.addHandler(handler)
    root.setLevel(settings.LOG_LEVEL)
    logging.getLogger("uvicorn.access").handlers = []
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.DB_ECHO else logging.WARNING
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
