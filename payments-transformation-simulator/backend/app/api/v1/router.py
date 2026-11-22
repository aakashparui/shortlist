"""v1 router assembly."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import ba, operations, payments, qa, system

api_router = APIRouter()
api_router.include_router(payments.router)
api_router.include_router(operations.router)
api_router.include_router(qa.router)
api_router.include_router(ba.router)
api_router.include_router(system.router)
