"""Portable column types.

`Money` stores exact decimals on both PostgreSQL (NUMERIC) and SQLite (scaled
BIGINT), so amounts are never round-tripped through a float and remain sortable
and range-queryable in SQL.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import BigInteger, DateTime, Numeric
from sqlalchemy.types import TypeDecorator


class Money(TypeDecorator):
    impl = Numeric(20, 4)
    cache_ok = True

    SCALE = Decimal(10_000)

    def load_dialect_impl(self, dialect):  # noqa: ANN001, ANN201
        if dialect.name == "sqlite":
            return dialect.type_descriptor(BigInteger())
        return dialect.type_descriptor(Numeric(20, 4, asdecimal=True))

    def process_bind_param(self, value, dialect):  # noqa: ANN001, ANN201
        if value is None:
            return None
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
        if dialect.name == "sqlite":
            return int((amount * self.SCALE).to_integral_value(rounding=ROUND_HALF_UP))
        return amount

    def process_result_value(self, value, dialect):  # noqa: ANN001, ANN201
        if value is None:
            return None
        if dialect.name == "sqlite":
            return Decimal(int(value)) / self.SCALE
        return Decimal(value)


class UTCDateTime(TypeDecorator):
    """Always hand back timezone-aware UTC datetimes, including on SQLite."""

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):  # noqa: ANN001, ANN201
        return dialect.type_descriptor(DateTime(timezone=dialect.name != "sqlite"))

    def process_bind_param(self, value, dialect):  # noqa: ANN001, ANN201
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError(f"Expected datetime, got {type(value)!r}")
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value, dialect):  # noqa: ANN001, ANN201
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
