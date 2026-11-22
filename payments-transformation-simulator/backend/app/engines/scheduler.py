"""Durable background worker.

Asynchronous payment behaviour (a clearing response arriving later, a timeout
firing, a delayed notification) is persisted in `scheduled_job` and executed by
this worker. Persisting the work rather than holding in-memory timers means
pending work is visible in the database, survives a restart, and can be driven
synchronously by the test suite.
"""

from __future__ import annotations

import threading
import time

from sqlalchemy import select

from app.core.config import settings
from app.core.identifiers import utcnow
from app.core.logging import get_logger
from app.db.models import ScheduledJob
from app.db.session import session_scope
from app.engines.orchestrator import PaymentOrchestrator

logger = get_logger(__name__)


def claim_due_jobs(limit: int = 20) -> list[int]:
    """Mark due jobs as RUNNING in their own transaction and return their ids."""
    with session_scope() as session:
        rows = list(
            session.execute(
                select(ScheduledJob)
                .where(ScheduledJob.status == "PENDING", ScheduledJob.due_at <= utcnow())
                .order_by(ScheduledJob.due_at.asc())
                .limit(limit)
            ).scalars()
        )
        ids: list[int] = []
        for job in rows:
            job.status = "RUNNING"
            job.started_at = utcnow()
            job.attempts += 1
            ids.append(job.id)
        return ids


def run_job(job_id: int) -> None:
    with session_scope() as session:
        job = session.get(ScheduledJob, job_id)
        if job is None:
            return
        orchestrator = PaymentOrchestrator(session)
        try:
            orchestrator.run_job(job)
            job.status = "DONE"
        except Exception as exc:  # a failed job must never take the worker down
            logger.exception("scheduled job failed", extra={"job_id": job_id, "job_type": job.job_type})
            job.status = "FAILED"
            job.last_error = f"{type(exc).__name__}: {exc}"
        finally:
            job.finished_at = utcnow()


def drain(max_iterations: int = 200) -> int:
    """Run every job that is currently due. Used by tests and the QA Lab."""
    processed = 0
    for _ in range(max_iterations):
        ids = claim_due_jobs()
        if not ids:
            break
        for job_id in ids:
            run_job(job_id)
            processed += 1
    return processed


class SchedulerThread(threading.Thread):
    def __init__(self) -> None:
        super().__init__(name="payment-scheduler", daemon=True)
        self._stop = threading.Event()

    def run(self) -> None:  # pragma: no cover - timing dependent
        logger.info("payment scheduler started")
        while not self._stop.is_set():
            try:
                ids = claim_due_jobs()
                for job_id in ids:
                    run_job(job_id)
            except Exception:
                logger.exception("scheduler loop error")
            self._stop.wait(settings.SCHEDULER_POLL_INTERVAL_SECONDS)
        logger.info("payment scheduler stopped")

    def stop(self) -> None:
        self._stop.set()


_thread: SchedulerThread | None = None


def start_scheduler() -> SchedulerThread | None:
    global _thread
    if not settings.SCHEDULER_ENABLED:
        logger.info("scheduler disabled by configuration")
        return None
    if _thread is not None and _thread.is_alive():
        return _thread
    _thread = SchedulerThread()
    _thread.start()
    return _thread


def stop_scheduler() -> None:
    global _thread
    if _thread is not None:
        _thread.stop()
        _thread.join(timeout=5)
        _thread = None


def wait_for_quiet(timeout_seconds: float = 30.0, poll: float = 0.1) -> bool:
    """Block until no PENDING or RUNNING jobs remain. Used by demo/QA endpoints."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        with session_scope() as session:
            outstanding = session.execute(
                select(ScheduledJob.id).where(ScheduledJob.status.in_(("PENDING", "RUNNING"))).limit(1)
            ).first()
        if outstanding is None:
            return True
        time.sleep(poll)
    return False
