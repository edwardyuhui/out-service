"""RQ identity, submission and authoritative failure evidence for optimization studies."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from app.core.config import get_settings

QUEUE_NAME = "indusopt"
JOB_FUNCTION = "app.worker.run_optimization_job"
JOB_TIMEOUT_SECONDS = 3600
RESULT_TTL_SECONDS = 86_400
FAILURE_CALLBACK_TIMEOUT_SECONDS = 30

SubmissionOutcome = Literal[
    "SUBMITTED",
    "CONFIRMED_NOT_ENQUEUED",
    "SUBMISSION_UNKNOWN",
    "SUBMISSION_CONFLICT",
]
JobAvailability = Literal[
    "AVAILABLE",
    "NOT_FOUND",
    "UNAVAILABLE",
    "IDENTITY_MISMATCH",
]
RqEvidenceSource = Literal[
    "failure_callback",
    "failed_registry",
    "started_registry_cleanup",
]
RqEvidenceKind = Literal[
    "job_timeout",
    "work_horse_terminated",
    "abandoned_execution",
    "ordinary_exception",
]
RqEvidenceConfidence = Literal["HIGH", "GENERIC"]


@dataclass(frozen=True)
class RqTerminalEvidence:
    """Compact, typed evidence; never contains the exception message or traceback."""

    source: RqEvidenceSource
    kind: RqEvidenceKind
    confidence: RqEvidenceConfidence
    rq_job_id: str
    rq_status: str
    exception_type: str
    observed_at: datetime
    error_code: str
    job_timeout_seconds: int | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "kind": self.kind,
            "confidence": self.confidence,
            "rq_job_id": self.rq_job_id,
            "rq_status": self.rq_status,
            "exception_type": self.exception_type,
            "observed_at": self.observed_at.isoformat(),
            "error_code": self.error_code,
            "job_timeout_seconds": self.job_timeout_seconds,
        }


@dataclass(frozen=True)
class JobObservation:
    availability: JobAvailability
    job_id: str
    queue_name: str
    raw_status: str | None = None
    created_at: datetime | None = None
    enqueued_at: datetime | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    error_code: str | None = None
    terminal_evidence: RqTerminalEvidence | None = None


@dataclass(frozen=True)
class Submission:
    """Outcome of one enqueue attempt without hiding ambiguous delivery."""

    outcome: SubmissionOutcome
    job_id: str | None
    reason: str | None
    observation: JobObservation | None = None

    @property
    def queued(self) -> bool:
        """Compatibility name: true means the caller must not execute inline."""

        return self.outcome == "SUBMITTED"

    @property
    def allows_inline(self) -> bool:
        return self.outcome == "CONFIRMED_NOT_ENQUEUED"

    def to_payload(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "queued": self.queued,
            "job_id": self.job_id,
            "reason": self.reason,
        }


def background_optimization_enabled() -> bool:
    return get_settings().background_optimization


def submit_optimization(study_id: UUID, payload: dict[str, Any]) -> Submission:
    """Submit one stable, unique RQ job or report why inline execution is safe/unsafe."""

    settings = get_settings()
    job_id = str(study_id)
    if not settings.background_optimization:
        return Submission(
            outcome="CONFIRMED_NOT_ENQUEUED",
            job_id=None,
            reason="后台执行未启用（INDUSOPT_BACKGROUND_OPTIMIZATION）",
        )

    try:
        from redis import Redis
        from rq import Queue
        from rq.job import Callback

        connection = Redis.from_url(settings.redis_url)
        connection.ping()
        queue = Queue(
            QUEUE_NAME,
            connection=connection,
            default_timeout=JOB_TIMEOUT_SECONDS,
        )
    except Exception as error:  # noqa: BLE001 - enqueue has definitely not been attempted
        return Submission(
            outcome="CONFIRMED_NOT_ENQUEUED",
            job_id=None,
            reason=f"队列不可用（{type(error).__name__}）",
        )

    try:
        job = queue.enqueue(
            JOB_FUNCTION,
            job_id,
            payload,
            job_id=job_id,
            unique=True,
            meta={"study_id": job_id, "job_kind": "optimization"},
            job_timeout=JOB_TIMEOUT_SECONDS,
            result_ttl=RESULT_TTL_SECONDS,
            on_failure=Callback(
                "app.worker.handle_optimization_job_failure",
                timeout=FAILURE_CALLBACK_TIMEOUT_SECONDS,
            ),
        )
    except Exception as error:  # enqueue acknowledgement can fail after Redis accepted it
        return _recover_enqueue_outcome(
            connection=connection,
            study_id=study_id,
            error=error,
        )

    observation = _observe_job(job, study_id=study_id)
    if observation.availability != "AVAILABLE":
        return Submission(
            outcome="SUBMISSION_CONFLICT",
            job_id=job_id,
            reason="RQ 作业身份与 OptimizationStudy 不一致。",
            observation=observation,
        )
    return Submission(
        outcome="SUBMITTED",
        job_id=job_id,
        reason=None,
        observation=observation,
    )


def observe_optimization_job(*, study_id: UUID, job_id: str, queue_name: str) -> JobObservation:
    """Read one RQ Job without cleaning registries or changing either persistence system."""

    settings = get_settings()
    try:
        from redis import Redis
        from rq.job import Job

        connection = Redis.from_url(settings.redis_url)
        connection.ping()
        job = Job.fetch(job_id, connection=connection)
    except Exception as error:  # noqa: BLE001 - NoSuchJob is a normal observation
        if _is_no_such_job(error):
            return JobObservation(
                availability="NOT_FOUND",
                job_id=job_id,
                queue_name=queue_name,
                error_code="RQ_JOB_NOT_FOUND",
            )
        return JobObservation(
            availability="UNAVAILABLE",
            job_id=job_id,
            queue_name=queue_name,
            error_code="RQ_RECONCILIATION_UNAVAILABLE",
        )
    return _observe_job(job, study_id=study_id, expected_queue_name=queue_name)


def reconcile_optimization_job(
    *,
    study_id: UUID,
    job_id: str,
    queue_name: str,
    expected_timeout_seconds: int,
) -> JobObservation:
    """Observe one RQ job and derive terminal evidence from official persisted state.

    This function is intentionally synchronous. Async callers must run it in a threadpool,
    because registry cleanup can execute the failure callback and that callback owns an
    independent ``asyncio.run`` lifecycle.
    """

    settings = get_settings()
    try:
        from redis import Redis
        from rq.job import Job
        from rq.registry import StartedJobRegistry

        connection = Redis.from_url(settings.redis_url)
        connection.ping()
        job = Job.fetch(job_id, connection=connection)
    except Exception as error:  # noqa: BLE001 - availability is part of the API contract
        return _unavailable_observation(
            error=error,
            job_id=job_id,
            queue_name=queue_name,
        )

    observation = _observe_job(job, study_id=study_id, expected_queue_name=queue_name)
    if observation.availability != "AVAILABLE":
        return observation

    evidence_source: RqEvidenceSource = "failed_registry"
    if observation.raw_status == "started":
        try:
            StartedJobRegistry(queue_name, connection=connection).cleanup()
            job = Job.fetch(job_id, connection=connection)
        except Exception as error:  # noqa: BLE001 - cleanup/fetch is best-effort observation
            return _unavailable_observation(
                error=error,
                job_id=job_id,
                queue_name=queue_name,
            )
        observation = _observe_job(job, study_id=study_id, expected_queue_name=queue_name)
        if observation.availability != "AVAILABLE":
            return observation
        evidence_source = "started_registry_cleanup"

    if observation.raw_status != "failed":
        return observation

    evidence = _failed_registry_evidence(
        job,
        queue_name=queue_name,
        expected_timeout_seconds=expected_timeout_seconds,
        source=evidence_source,
    )
    return replace(observation, terminal_evidence=evidence)


def callback_terminal_evidence(
    job: Any,
    *,
    exc_type: type[BaseException],
) -> RqTerminalEvidence | None:
    """Classify the job-body exception supplied by RQ's failure callback."""

    study_id = _validated_callback_study_id(job)
    if study_id is None:
        return None

    exception_type = f"{exc_type.__module__}.{exc_type.__qualname__}"
    rq_status = _cached_job_status(job)
    try:
        from rq.exceptions import AbandonedJobError
        from rq.timeouts import JobTimeoutException
    except ImportError:
        return None

    if issubclass(exc_type, JobTimeoutException) and _job_timeout_matches(
        job, JOB_TIMEOUT_SECONDS
    ):
        return RqTerminalEvidence(
            source="failure_callback",
            kind="job_timeout",
            confidence="HIGH",
            rq_job_id=study_id,
            rq_status=rq_status,
            exception_type=exception_type,
            observed_at=datetime.now(UTC),
            error_code="RQ_JOB_TIMEOUT",
            job_timeout_seconds=JOB_TIMEOUT_SECONDS,
        )
    if issubclass(exc_type, AbandonedJobError):
        return RqTerminalEvidence(
            source="failure_callback",
            kind="abandoned_execution",
            confidence="HIGH",
            rq_job_id=study_id,
            rq_status=rq_status,
            exception_type=exception_type,
            observed_at=datetime.now(UTC),
            error_code="RQ_ABANDONED_EXECUTION",
            job_timeout_seconds=_job_timeout(job),
        )
    return RqTerminalEvidence(
        source="failure_callback",
        kind="ordinary_exception",
        confidence="GENERIC",
        rq_job_id=study_id,
        rq_status=rq_status,
        exception_type=exception_type,
        observed_at=datetime.now(UTC),
        error_code="RQ_JOB_EXECUTION_FAILED",
        job_timeout_seconds=_job_timeout(job),
    )


def persist_job_terminal_evidence_best_effort(
    job: Any, evidence: RqTerminalEvidence
) -> None:
    """Keep compact callback evidence in Redis without allowing failure to escape."""

    try:
        meta = dict(job.meta) if isinstance(job.meta, dict) else {}
        meta["terminal_evidence"] = evidence.to_payload()
        job.meta = meta
        job.save_meta()
    except BaseException:  # noqa: BLE001 - a failure callback must never replace job failure
        return


def _recover_enqueue_outcome(*, connection: Any, study_id: UUID, error: Exception) -> Submission:
    job_id = str(study_id)
    try:
        from rq.job import Job

        job = Job.fetch(job_id, connection=connection)
    except Exception as fetch_error:  # noqa: BLE001 - Redis may now be unavailable
        if _is_no_such_job(fetch_error):
            return Submission(
                outcome="CONFIRMED_NOT_ENQUEUED",
                job_id=None,
                reason=f"队列未接收作业（{type(error).__name__}）",
            )
        return Submission(
            outcome="SUBMISSION_UNKNOWN",
            job_id=job_id,
            reason=f"队列提交结果暂不可确认（{type(error).__name__}）",
            observation=JobObservation(
                availability="UNAVAILABLE",
                job_id=job_id,
                queue_name=QUEUE_NAME,
                error_code="RQ_RECONCILIATION_UNAVAILABLE",
            ),
        )

    observation = _observe_job(job, study_id=study_id)
    if observation.availability != "AVAILABLE":
        return Submission(
            outcome="SUBMISSION_CONFLICT",
            job_id=job_id,
            reason="RQ 已存在同 ID 作业，但身份信息不匹配。",
            observation=observation,
        )
    return Submission(
        outcome="SUBMITTED",
        job_id=job_id,
        reason=f"已恢复现有 RQ 作业（{type(error).__name__}）。",
        observation=observation,
    )


def _observe_job(
    job: Any,
    *,
    study_id: UUID,
    expected_queue_name: str = QUEUE_NAME,
) -> JobObservation:
    job_id = str(study_id)
    meta = job.meta if isinstance(job.meta, dict) else {}
    if (
        job.id != job_id
        or meta.get("study_id") != job_id
        or meta.get("job_kind") != "optimization"
        or job.func_name != JOB_FUNCTION
        or job.origin != expected_queue_name
    ):
        return JobObservation(
            availability="IDENTITY_MISMATCH",
            job_id=job_id,
            queue_name=expected_queue_name,
            error_code="RQ_JOB_IDENTITY_MISMATCH",
        )

    try:
        status = job.get_status(refresh=True)
        raw_status = status.value if hasattr(status, "value") else str(status)
    except Exception:  # noqa: BLE001 - the Job exists but its current state is unavailable
        return JobObservation(
            availability="UNAVAILABLE",
            job_id=job_id,
            queue_name=expected_queue_name,
            error_code="RQ_RECONCILIATION_UNAVAILABLE",
        )

    return JobObservation(
        availability="AVAILABLE",
        job_id=job_id,
        queue_name=expected_queue_name,
        raw_status=raw_status,
        created_at=getattr(job, "created_at", None),
        enqueued_at=getattr(job, "enqueued_at", None),
        started_at=getattr(job, "started_at", None),
        ended_at=getattr(job, "ended_at", None),
    )


def _is_no_such_job(error: Exception) -> bool:
    try:
        from rq.exceptions import NoSuchJobError
    except ImportError:
        return False
    return isinstance(error, NoSuchJobError)


def _unavailable_observation(
    *, error: Exception, job_id: str, queue_name: str
) -> JobObservation:
    if _is_no_such_job(error):
        return JobObservation(
            availability="NOT_FOUND",
            job_id=job_id,
            queue_name=queue_name,
            error_code="RQ_JOB_NOT_FOUND",
        )
    return JobObservation(
        availability="UNAVAILABLE",
        job_id=job_id,
        queue_name=queue_name,
        error_code="RQ_RECONCILIATION_UNAVAILABLE",
    )


def _validated_callback_study_id(job: Any) -> str | None:
    meta = job.meta if isinstance(getattr(job, "meta", None), dict) else {}
    job_id = getattr(job, "id", None)
    if (
        not isinstance(job_id, str)
        or meta.get("study_id") != job_id
        or meta.get("job_kind") != "optimization"
        or getattr(job, "func_name", None) != JOB_FUNCTION
        or getattr(job, "origin", None) != QUEUE_NAME
    ):
        return None
    return job_id


def _cached_job_status(job: Any) -> str:
    status = getattr(job, "_status", None)
    return status.value if hasattr(status, "value") else str(status or "started")


def _job_timeout(job: Any) -> int | None:
    value = getattr(job, "timeout", None)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _job_timeout_matches(job: Any, expected: int) -> bool:
    return _job_timeout(job) == expected


def _failed_registry_evidence(
    job: Any,
    *,
    queue_name: str,
    expected_timeout_seconds: int,
    source: RqEvidenceSource,
) -> RqTerminalEvidence | None:
    try:
        from rq.registry import FailedJobRegistry

        registry = FailedJobRegistry(queue_name, connection=job.connection)
        if job.id not in registry:
            return None
        result = job.latest_result(timeout=0)
    except Exception:  # noqa: BLE001 - absence of authoritative evidence is not terminal
        return None

    exc_string = getattr(result, "exc_string", None)
    if not isinstance(exc_string, str) or not exc_string.strip():
        return None
    final_line = next(
        (line.strip() for line in reversed(exc_string.splitlines()) if line.strip()),
        "",
    )
    common = {
        "source": source,
        "confidence": "HIGH",
        "rq_job_id": job.id,
        "rq_status": "failed",
        "observed_at": datetime.now(UTC),
        "job_timeout_seconds": _job_timeout(job),
    }

    timeout_line = (
        "rq.timeouts.JobTimeoutException: Task exceeded maximum timeout value "
        f"({expected_timeout_seconds} seconds)"
    )
    if (
        final_line == timeout_line
        and _job_timeout_matches(job, expected_timeout_seconds)
    ):
        return RqTerminalEvidence(
            **common,
            kind="job_timeout",
            exception_type="rq.timeouts.JobTimeoutException",
            error_code="RQ_JOB_TIMEOUT",
        )
    if re.fullmatch(
        r"Work-horse terminated unexpectedly; waitpid returned .+;",
        final_line,
    ):
        return RqTerminalEvidence(
            **common,
            kind="work_horse_terminated",
            exception_type="rq.worker.WorkHorseTerminated",
            error_code="RQ_WORK_HORSE_TERMINATED",
        )
    if re.fullmatch(
        r"Moved to FailedJobRegistry, due to AbandonedJobError, at .+",
        final_line,
    ):
        return RqTerminalEvidence(
            **common,
            kind="abandoned_execution",
            exception_type="rq.exceptions.AbandonedJobError",
            error_code="RQ_ABANDONED_EXECUTION",
        )
    return None
