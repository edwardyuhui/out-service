"""RQ worker entry point: the long closed-loop search, run outside the request.

Start with::

    PYTHONPATH=. rq worker indusopt --url redis://localhost:6379/0

The job function is deliberately thin. It reuses the same async services the HTTP handler
uses rather than growing a second implementation that would drift — a worker that computes
something subtly different from the API is worse than no worker.

Idempotence: the job is keyed on a ``study_id`` the API allocated and already inserted as
``queued``. Re-running the same job overwrites that row rather than creating a second
study, so an RQ retry after a worker crash cannot leave two records for one request.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.schemas.optimization import OptimizationStartRequest

logger = logging.getLogger(__name__)


def run_optimization_job(study_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """RQ entry point. Synchronous by contract, async underneath.

    The worker process owns its own engine: the cached one in ``app.core.db`` belongs to
    whichever event loop created it, and sharing an asyncpg pool across processes is how
    you get connections that answer the wrong query.
    """

    return asyncio.run(_execute(UUID(study_id), payload))


async def _execute(study_id: UUID, payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.optimization_service import execute_study

    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            outcome = await execute_study(
                session,
                study_id=study_id,
                payload=OptimizationStartRequest.model_validate(payload),
                artifact_root=settings.artifact_root,
            )
        return outcome
    finally:
        await engine.dispose()


def handle_optimization_job_failure(
    job: Any,
    connection: Any,
    exc_type: type[BaseException],
    exc_value: BaseException,
    traceback: Any,
) -> None:
    """Best-effort RQ failure callback that can never replace the job-body exception."""

    del connection, exc_value, traceback
    try:
        from app.services.job_queue import (
            callback_terminal_evidence,
            persist_job_terminal_evidence_best_effort,
        )

        evidence = callback_terminal_evidence(job, exc_type=exc_type)
        if evidence is None:
            logger.warning("Rejected optimization failure callback with invalid job identity")
            return

        try:
            asyncio.run(_persist_failure_evidence(UUID(evidence.rq_job_id), evidence))
        except BaseException:  # noqa: BLE001 - never replace the original RQ failure
            logger.exception(
                "Could not persist optimization failure evidence for study %s",
                evidence.rq_job_id,
            )
        persist_job_terminal_evidence_best_effort(job, evidence)
    except BaseException:  # noqa: BLE001 - RQ must retain the original job-body exception
        logger.exception("Optimization failure callback failed safely")


async def _persist_failure_evidence(study_id: UUID, evidence: Any) -> None:
    from app.services.optimization_service import persist_rq_terminal_evidence

    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            await persist_rq_terminal_evidence(
                session,
                study_id=study_id,
                evidence=evidence,
            )
    finally:
        await engine.dispose()
