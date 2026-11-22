"""Centralised error handling.

Error responses carry a stable shape and never leak internals: an unexpected
exception returns a request id the operator can quote, and the detail stays in
the structured log.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import correlation_id_var, get_logger, request_id_var
from app.engines.state_machine import IllegalTransitionError
from app.schemes.registry import UnknownSchemeError

logger = get_logger(__name__)


def _body(
    *,
    code: str,
    message: str,
    status_code: int,
    detail: object | None = None,
) -> JSONResponse:
    payload: dict = {
        "error": {
            "code": code,
            "message": message,
            "requestId": request_id_var.get(),
            "correlationId": correlation_id_var.get(),
        }
    }
    if detail is not None:
        payload["error"]["detail"] = detail
    return JSONResponse(status_code=status_code, content=payload)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _body(
            code=f"HTTP_{exc.status_code}",
            message=exc.detail if isinstance(exc.detail, str) else "Request could not be completed",
            status_code=exc.status_code,
            detail=None if isinstance(exc.detail, str) else exc.detail,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _body(
            code="VALIDATION_ERROR",
            message="The request body or query parameters are not valid.",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=[
                {
                    "field": ".".join(str(p) for p in err.get("loc", [])[1:]),
                    "message": err.get("msg"),
                    "type": err.get("type"),
                }
                for err in exc.errors()
            ],
        )

    @app.exception_handler(IllegalTransitionError)
    async def illegal_transition(_: Request, exc: IllegalTransitionError) -> JSONResponse:
        return _body(
            code="ILLEGAL_STATE_TRANSITION",
            message=str(exc),
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "currentStatus": exc.current.value,
                "attemptedStatus": exc.target.value,
                "allowedTransitions": exc.allowed,
            },
        )

    @app.exception_handler(UnknownSchemeError)
    async def unknown_scheme(_: Request, exc: UnknownSchemeError) -> JSONResponse:
        return _body(
            code="UNKNOWN_SCHEME",
            message=f"Payment scheme '{exc.code}' is not registered.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    @app.exception_handler(LookupError)
    async def lookup_error(_: Request, exc: LookupError) -> JSONResponse:
        return _body(
            code="NOT_FOUND", message=str(exc) or "Not found", status_code=status.HTTP_404_NOT_FOUND
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error(_: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.exception("database error", extra={"error_type": type(exc).__name__})
        return _body(
            code="DATABASE_ERROR",
            message="A database error occurred. The request id has been logged.",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error", extra={"error_type": type(exc).__name__})
        return _body(
            code="INTERNAL_ERROR",
            message="An unexpected error occurred. The request id has been logged.",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
