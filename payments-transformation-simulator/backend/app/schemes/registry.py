"""Scheme registry — the single lookup point for rail configuration."""

from __future__ import annotations

from app.core.config import settings
from app.domain.enums import SchemeCode
from app.schemes.base import PaymentScheme
from app.schemes.definitions import ALL_SCHEMES

_REGISTRY: dict[SchemeCode, PaymentScheme] = {scheme.code: scheme for scheme in ALL_SCHEMES}

DEFAULT_SCHEME = SchemeCode.SIC_INSTANT


class UnknownSchemeError(KeyError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def register(scheme: PaymentScheme) -> None:
    """Plug in an additional rail at runtime (used by tests and extensions)."""
    _REGISTRY[scheme.code] = scheme


def get_scheme(code: str | SchemeCode) -> PaymentScheme:
    try:
        key = code if isinstance(code, SchemeCode) else SchemeCode(str(code))
    except ValueError as exc:
        raise UnknownSchemeError(str(code)) from exc
    try:
        return _REGISTRY[key]
    except KeyError as exc:
        raise UnknownSchemeError(str(code)) from exc


def list_schemes() -> list[PaymentScheme]:
    return [_REGISTRY[code] for code in SchemeCode if code in _REGISTRY]


def clearing_timeout_seconds(scheme: PaymentScheme, accelerated: bool = True) -> float:
    """Timeout threshold for this rail.

    The realistic value comes from the scheme profile (not a global constant);
    `CLEARING_TIMEOUT_SECONDS` only acts as a fallback for rails without one.
    Demo mode divides it by `SIMULATION_SPEED_FACTOR` so a demo does not require
    the operator to wait a full scheme window.
    """
    realistic = float(scheme.clearing.realistic_timeout_seconds or settings.CLEARING_TIMEOUT_SECONDS)
    return settings.accelerate(realistic) if accelerated else realistic


def clearing_response_seconds(scheme: PaymentScheme, accelerated: bool = True) -> float:
    realistic = float(scheme.clearing.realistic_response_seconds)
    return settings.accelerate(realistic) if accelerated else realistic
