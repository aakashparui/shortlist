"""Shared API dependencies."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.services.ba_service import BaService
from app.services.payment_service import PaymentService
from app.services.scenario_service import ScenarioService
from app.services.search_service import SearchService
from app.services.testcase_service import TestCaseService

DbSession = Annotated[Session, Depends(get_db)]


def payment_service(session: DbSession) -> Iterator[PaymentService]:
    yield PaymentService(session)


def scenario_service(session: DbSession) -> Iterator[ScenarioService]:
    yield ScenarioService(session)


def testcase_service(session: DbSession) -> Iterator[TestCaseService]:
    yield TestCaseService(session)


def ba_service(session: DbSession) -> Iterator[BaService]:
    yield BaService(session)


def search_service(session: DbSession) -> Iterator[SearchService]:
    yield SearchService(session)


Payments = Annotated[PaymentService, Depends(payment_service)]
Scenarios = Annotated[ScenarioService, Depends(scenario_service)]
TestCases = Annotated[TestCaseService, Depends(testcase_service)]
Ba = Annotated[BaService, Depends(ba_service)]
Search = Annotated[SearchService, Depends(search_service)]


def page_size_param(
    pageSize: int = Query(default=25, ge=1, le=500, description="Items per page"),
) -> int:
    return min(pageSize, settings.MAX_PAGE_SIZE)


PageSize = Annotated[int, Depends(page_size_param)]


def not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def conflict(detail: str, extra: dict | None = None) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"message": detail, **(extra or {})} if extra else detail,
    )
