"""Application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_error_handlers
from app.api.middleware import RateLimitMiddleware, RequestContextMiddleware
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.db.bootstrap import initialise
from app.engines.scheduler import start_scheduler, stop_scheduler

configure_logging()
logger = get_logger(__name__)

DESCRIPTION = """
Simulates the lifecycle of a modern payment from initiation through validation,
screening, ISO 20022 messaging, clearing, settlement, accounting and
reconciliation - including the failures.

**This is a simulator.** It is standards-inspired, contains only fictional data,
and is not an implementation of any bank, SWIFT, SIC, SEPA or clearing system.
Where behaviour is simplified it is labelled as *simulation behaviour* or a
*simplified model*.
"""


@asynccontextmanager
async def lifespan(_: FastAPI):  # noqa: ANN201
    summary = initialise()
    logger.info("startup complete", extra={"seed": summary})
    scheduler = start_scheduler()
    try:
        yield
    finally:
        if scheduler is not None:
            stop_scheduler()
        logger.info("shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=DESCRIPTION,
        summary="Observe. Execute. Break. Investigate. Reconcile.",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
        contact={"name": "Payments Transformation Simulator"},
        license_info={"name": "Simulated environment - fictional data only"},
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["content-type", "x-request-id", "x-correlation-id"],
        expose_headers=["x-request-id"],
        max_age=600,
    )
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(RequestContextMiddleware)
    register_error_handlers(app)
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @app.get("/health", tags=["meta"], summary="Liveness and readiness")
    def health() -> dict:
        from sqlalchemy import text

        from app.db.session import engine

        database_ok = True
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:  # pragma: no cover
            database_ok = False
            logger.exception("health check database failure")
        return {
            "status": "ok" if database_ok else "degraded",
            "application": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
            "database": "ok" if database_ok else "unavailable",
            "demoMode": settings.DEMO_MODE,
        }

    @app.get("/", tags=["meta"], summary="Service index")
    def index() -> dict:
        return {
            "application": settings.APP_NAME,
            "subtitle": "Observe. Execute. Break. Investigate. Reconcile.",
            "version": settings.APP_VERSION,
            "apiBase": settings.API_V1_PREFIX,
            "documentation": "/docs",
            "openapi": "/openapi.json",
            "disclaimer": (
                "Simulated environment. All banks, BICs, IBANs, accounts and references are "
                "fictional. Not an implementation of any real payment system."
            ),
        }

    return app


app = create_app()
