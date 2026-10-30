"""Persistent state transitions for the Agent execution workflow."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from algorithms.agent.compliance import ComplianceProof
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.agent_execution import AgentExecutionSession, AgentStepRun
from app.schemas.copilot import (
    CopilotExecutionSnapshotData,
    CopilotExecutionStepSnapshot,
    ExecutionPlan,
)

_TERMINAL_EXECUTION_STATUSES = frozenset({"SUCCEEDED", "FAILED", "CANCELLED"})
_TERMINAL_STEP_STATUSES = frozenset({"SUCCEEDED", "SKIPPED"})


class ExecutionStateError(Exception):
    """An attempted state transition conflicts with the persisted workflow state."""

    def __init__(
        self,
        attempted_transition: str,
        *,
        execution_id: UUID | None = None,
        execution_status: str | None = None,
        step_id: str | None = None,
        step_status: str | None = None,
    ) -> None:
        details = [f"transition={attempted_transition}"]
        if execution_id is not None:
            details.append(f"execution_id={execution_id}")
        if execution_status is not None:
            details.append(f"execution_status={execution_status}")
        if step_id is not None:
            details.append(f"step_id={step_id}")
        if step_status is not None:
            details.append(f"step_status={step_status}")
        super().__init__("Illegal Agent execution state transition: " + ", ".join(details))


async def create_execution(
    session: AsyncSession,
    *,
    dataset_id: UUID,
    initial_version_id: UUID,
    planner_source: str,
    plan: ExecutionPlan,
    compliance_proof: ComplianceProof,
    copilot_run_id: UUID | None = None,
) -> AgentExecutionSession:
    """Persist one compliance-approved plan and its ordered pending step runs."""

    if not compliance_proof.passed:
        raise ExecutionStateError("create_execution_from_rejected_plan")

    execution = AgentExecutionSession(
        id=uuid4(),
        copilot_run_id=copilot_run_id,
        dataset_id=dataset_id,
        initial_version_id=initial_version_id,
        current_version_id=initial_version_id,
        planner_source=planner_source,
        plan_json=plan.model_dump(mode="json"),
        workflow_status="PLANNED",
        current_step_id=None,
        pending_confirmation_step_id=None,
        artifacts={},
        finished_at=None,
    )
    step_runs = [
        AgentStepRun(
            id=uuid4(),
            execution_id=execution.id,
            step_id=step.step_id,
            sequence=sequence,
            tool_name=step.tool,
            status="PENDING",
            requires_confirmation=step.requires_confirmation,
            confirmation_status="PENDING" if step.requires_confirmation else "NOT_REQUIRED",
            attempt_count=0,
            input_payload={
                "depends_on": list(step.depends_on),
                "parameters": dict(step.parameters),
            },
            result_payload={},
            processing_run_ids=[],
        )
        for sequence, step in enumerate(plan.steps, start=1)
    ]

    try:
        session.add(execution)
        await session.flush()
        session.add_all(step_runs)
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return execution


async def get_execution(session: AsyncSession, *, execution_id: UUID) -> AgentExecutionSession:
    """Load one persisted execution together with its ordered step runs."""

    return await _load_execution(session, execution_id)

def to_copilot_execution_snapshot(
    execution: AgentExecutionSession,
) -> CopilotExecutionSnapshotData:
    """Serialize persisted execution control state without performing a transition."""

    return CopilotExecutionSnapshotData(
        execution_id=execution.id,
        copilot_run_id=execution.copilot_run_id,
        dataset_id=execution.dataset_id,
        initial_version_id=execution.initial_version_id,
        current_version_id=execution.current_version_id,
        planner_source=execution.planner_source,
        workflow_status=execution.workflow_status,
        current_step_id=execution.current_step_id,
        pending_confirmation_step_id=execution.pending_confirmation_step_id,
        plan=ExecutionPlan.model_validate(execution.plan_json),
        artifacts=dict(execution.artifacts),
        error_code=execution.error_code,
        error_message=execution.error_message,
        created_at=execution.created_at,
        updated_at=execution.updated_at,
        finished_at=execution.finished_at,
        step_runs=[
            CopilotExecutionStepSnapshot(
                step_id=step.step_id,
                sequence=step.sequence,
                tool=step.tool_name,
                status=step.status,
                requires_confirmation=step.requires_confirmation,
                confirmation_status=step.confirmation_status,
                attempt_count=step.attempt_count,
                source_version_id=step.source_version_id,
                result_version_id=step.result_version_id,
                input_payload=dict(step.input_payload),
                result_payload=dict(step.result_payload),
                processing_run_ids=list(step.processing_run_ids),
                error_code=step.error_code,
                error_message=step.error_message,
                started_at=step.started_at,
                finished_at=step.finished_at,
            )
            for step in execution.step_runs
        ],
    )


async def claim_approved_optimization_step(
    session: AsyncSession, *, execution_id: UUID, step_id: str
) -> tuple[AgentExecutionSession, UUID]:
    """Atomically bind one approved optimization step to exactly one Study UUID."""

    execution = await _load_execution(session, execution_id, for_update=True)
    step = _step(execution, step_id)
    if (
        execution.workflow_status != "RUNNING"
        or execution.current_step_id != step.step_id
        or step.tool_name != "optimize_pipeline"
        or step.status != "RUNNING"
        or step.confirmation_status != "APPROVED"
    ):
        raise _transition_error("claim_approved_optimization_step", execution, step)

    raw_study_id = step.input_payload.get("optimization_study_id")
    if raw_study_id is not None:
        raise _transition_error("claim_approved_optimization_step_replay", execution, step)

    study_id = uuid4()
    step.input_payload = {
        **step.input_payload,
        "optimization_study_id": str(study_id),
        "optimization_execution_claimed_at": datetime.now(UTC).isoformat(),
    }
    await _commit(session)
    return execution, study_id

async def start_step(
    session: AsyncSession,
    *,
    execution_id: UUID,
    step_id: str,
    input_payload_update: dict[str, Any] | None = None,
) -> AgentExecutionSession:
    """Start one pending step or persist its confirmation gate without executing a tool."""

    execution = await _load_execution(session, execution_id)
    step = _step(execution, step_id)
    _require_startable(execution, step)
    _require_declared_dependencies_satisfied(execution, step)

    now = datetime.now(UTC)
    execution.current_step_id = step.step_id
    execution.finished_at = None
    if input_payload_update is not None:
        step.input_payload = {**step.input_payload, **input_payload_update}
    if step.requires_confirmation:
        step.status = "WAITING_CONFIRMATION"
        step.confirmation_status = "PENDING"
        execution.workflow_status = "WAITING_CONFIRMATION"
        execution.pending_confirmation_step_id = step.step_id
    else:
        step.status = "RUNNING"
        step.started_at = now
        execution.workflow_status = "RUNNING"
        execution.pending_confirmation_step_id = None

    await _commit(session)
    return execution


async def mark_step_succeeded(
    session: AsyncSession,
    *,
    execution_id: UUID,
    step_id: str,
    result_payload: dict[str, Any] | None = None,
    input_payload: dict[str, Any] | None = None,
    source_version_id: UUID | None = None,
    result_version_id: UUID | None = None,
    processing_run_ids: list[str] | None = None,
) -> AgentExecutionSession:
    """Mark a running step successful and complete the workflow only at its true terminal state."""

    execution = await _load_execution(session, execution_id)
    step = _step(execution, step_id)
    if execution.workflow_status != "RUNNING" or step.status != "RUNNING":
        raise _transition_error("mark_step_succeeded", execution, step)

    now = datetime.now(UTC)
    step.status = "SUCCEEDED"
    if result_payload is not None:
        step.result_payload = dict(result_payload)
    if input_payload is not None:
        step.input_payload = dict(input_payload)
    if source_version_id is not None:
        step.source_version_id = source_version_id
    if result_version_id is not None:
        step.result_version_id = result_version_id
        execution.current_version_id = result_version_id
    if processing_run_ids is not None:
        step.processing_run_ids = list(processing_run_ids)
    step.finished_at = now
    execution.current_step_id = None
    execution.pending_confirmation_step_id = None
    if all(item.status in _TERMINAL_STEP_STATUSES for item in execution.step_runs):
        execution.workflow_status = "SUCCEEDED"
        execution.finished_at = now
    else:
        execution.workflow_status = "RUNNING"
        execution.finished_at = None

    await _commit(session)
    return execution


async def mark_step_failed(
    session: AsyncSession,
    *,
    execution_id: UUID,
    step_id: str,
    error_code: str,
    error_message: str,
    result_payload: dict[str, Any] | None = None,
) -> AgentExecutionSession:
    """Record an unrecoverable running-step failure and stop the workflow."""

    execution = await _load_execution(session, execution_id)
    step = _step(execution, step_id)
    if execution.workflow_status != "RUNNING" or step.status != "RUNNING":
        raise _transition_error("mark_step_failed", execution, step)

    now = datetime.now(UTC)
    step.status = "FAILED"
    step.error_code = error_code
    step.error_message = error_message
    if result_payload is not None:
        step.result_payload = dict(result_payload)
    step.finished_at = now
    execution.workflow_status = "FAILED"
    execution.error_code = error_code
    execution.error_message = error_message
    execution.current_step_id = step.step_id
    execution.pending_confirmation_step_id = None
    execution.finished_at = now

    await _commit(session)
    return execution


async def mark_step_preparation_failed(
    session: AsyncSession,
    *,
    execution_id: UUID,
    step_id: str,
    error_code: str,
    error_message: str,
) -> AgentExecutionSession:
    """Persist a failure raised before a pending confirmation step can start."""

    execution = await _load_execution(session, execution_id)
    step = _step(execution, step_id)
    _require_startable(execution, step)
    _require_declared_dependencies_satisfied(execution, step)

    now = datetime.now(UTC)
    step.status = "FAILED"
    step.error_code = error_code
    step.error_message = error_message
    step.finished_at = now
    execution.workflow_status = "FAILED"
    execution.error_code = error_code
    execution.error_message = error_message
    execution.current_step_id = step.step_id
    execution.pending_confirmation_step_id = None
    execution.finished_at = now

    await _commit(session)
    return execution


async def approve_step(
    session: AsyncSession, *, execution_id: UUID, step_id: str
) -> AgentExecutionSession:
    """Approve the current confirmation gate and make its step runnable."""

    execution = await _load_execution(session, execution_id)
    step = _step(execution, step_id)
    if _is_approved_step_replay(execution, step):
        return execution
    if (
        execution.workflow_status != "WAITING_CONFIRMATION"
        or execution.pending_confirmation_step_id != step.step_id
        or step.status != "WAITING_CONFIRMATION"
        or step.confirmation_status != "PENDING"
    ):
        raise _transition_error("approve_step", execution, step)

    if step.started_at is None:
        step.started_at = datetime.now(UTC)
    step.status = "RUNNING"
    step.confirmation_status = "APPROVED"
    execution.workflow_status = "RUNNING"
    execution.current_step_id = step.step_id
    execution.pending_confirmation_step_id = None
    execution.finished_at = None

    await _commit(session)
    return execution


def _is_approved_step_replay(
    execution: AgentExecutionSession, step: AgentStepRun
) -> bool:
    if step.confirmation_status != "APPROVED":
        return False
    if step.status in {"SUCCEEDED", "FAILED"}:
        return True
    return (
        execution.workflow_status == "RUNNING"
        and execution.current_step_id == step.step_id
        and step.status == "RUNNING"
    )


async def reject_step(
    session: AsyncSession, *, execution_id: UUID, step_id: str
) -> AgentExecutionSession:
    """Cancel a waiting confirmation and terminate the first-version workflow."""

    execution = await _load_execution(session, execution_id)
    step = _step(execution, step_id)
    if (
        execution.workflow_status != "WAITING_CONFIRMATION"
        or execution.pending_confirmation_step_id != step.step_id
        or step.status != "WAITING_CONFIRMATION"
    ):
        raise _transition_error("reject_step", execution, step)

    now = datetime.now(UTC)
    step.status = "CANCELLED"
    step.confirmation_status = "REJECTED"
    step.finished_at = now
    execution.workflow_status = "CANCELLED"
    execution.pending_confirmation_step_id = None
    execution.finished_at = now

    await _commit(session)
    return execution


async def _load_execution(
    session: AsyncSession, execution_id: UUID, *, for_update: bool = False
) -> AgentExecutionSession:
    statement = (
        select(AgentExecutionSession)
        .where(AgentExecutionSession.id == execution_id)
        .options(selectinload(AgentExecutionSession.step_runs))
    )
    if for_update:
        statement = statement.with_for_update()
    execution = await session.scalar(statement)
    if execution is None:
        raise ExecutionStateError("load_execution", execution_id=execution_id)
    return execution


def _step(execution: AgentExecutionSession, step_id: str) -> AgentStepRun:
    for step in execution.step_runs:
        if step.step_id == step_id:
            return step
    raise ExecutionStateError(
        "load_step",
        execution_id=execution.id,
        execution_status=execution.workflow_status,
        step_id=step_id,
    )


def _require_startable(execution: AgentExecutionSession, step: AgentStepRun) -> None:
    if execution.workflow_status in _TERMINAL_EXECUTION_STATUSES:
        raise _transition_error("start_step", execution, step)
    if execution.workflow_status == "WAITING_CONFIRMATION" or step.status != "PENDING":
        raise _transition_error("start_step", execution, step)
    if execution.workflow_status not in {"PLANNED", "RUNNING"}:
        raise _transition_error("start_step", execution, step)
    if any(
        prior.sequence < step.sequence and prior.status not in _TERMINAL_STEP_STATUSES
        for prior in execution.step_runs
    ):
        raise _transition_error("start_step_before_prior_step", execution, step)


def _require_declared_dependencies_satisfied(
    execution: AgentExecutionSession, step: AgentStepRun
) -> None:
    plan_steps = execution.plan_json.get("steps", [])
    plan_step = next(
        (item for item in plan_steps if item.get("step_id") == step.step_id), None
    )
    if plan_step is None:
        raise _transition_error("start_step_missing_plan_step", execution, step)

    step_runs_by_id = {item.step_id: item for item in execution.step_runs}
    for dependency_step_id in plan_step.get("depends_on", []):
        dependency = step_runs_by_id.get(dependency_step_id)
        if dependency is None or dependency.status not in _TERMINAL_STEP_STATUSES:
            raise _transition_error("start_step_dependencies_not_satisfied", execution, step)
def _transition_error(
    attempted_transition: str, execution: AgentExecutionSession, step: AgentStepRun
) -> ExecutionStateError:
    return ExecutionStateError(
        attempted_transition,
        execution_id=execution.id,
        execution_status=execution.workflow_status,
        step_id=step.step_id,
        step_status=step.status,
    )


async def _commit(session: AsyncSession) -> None:
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
