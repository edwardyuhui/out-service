"""Agent orchestration: plan, verify, execute real tools, decide (phase 9).

Four layers, matching the phase plan:

* **Planner** turns the request into a whitelisted step list (``algorithms.agent.planner``).
* **Validator** statically verifies it and emits a compliance proof
  (``algorithms.agent.compliance``). A plan that fails does not run.
* **Executor** dispatches each step to the same services the REST API uses. It never
  evaluates model-authored code and never computes a metric itself — every number in a run
  record comes from an algorithm module.
* **Controller** decides after each step whether to continue, stop, or wait for a human.

The agent's own output is a plan and an explanation. All arithmetic belongs to the tools,
which is what makes the audit trail meaningful.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from algorithms.agent.compliance import ComplianceProof, verify_plan
from algorithms.agent.llm import LlmProvider
from algorithms.agent.llm_planner import LlmPlanner, PlanOutcome
from algorithms.agent.planner import PlannedStep, parse_intent
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.models.agent_execution import AgentExecutionSession
from app.models.dataset import ProcessingRun
from app.models.operation_log import OperationLog
from app.schemas.copilot import (
    AgentStepRun,
    ComplianceProofData,
    CopilotChatData,
    CopilotChatRequest,
    ExecutionPlan,
    ExecutionPlanStep,
)
from app.schemas.modeling import ArxFitRequest
from app.schemas.optimization import OptimizationStartRequest
from app.schemas.preprocessing import SegmentRequest
from app.services.agent_arx_modeling_service import (
    ArxStructureError,
    prepare_arx_confirmation,
    resolve_arx_lag_provenance,
)
from app.services.agent_execution_service import (
    claim_approved_optimization_step,
    create_execution,
    get_execution,
    mark_step_failed,
    mark_step_preparation_failed,
    mark_step_succeeded,
    start_step,
)
from app.services.agent_feature_selection_service import (
    FeatureSelectionError,
    prepare_feature_confirmation,
)
from app.services.agent_lag_apply_service import LagOverrideError, prepare_lag_confirmation
from app.services.agent_tool_adapter import AgentToolAdapterError, execute_agent_tool
from app.services.cleaning_service import CleaningDomainError
from app.services.contract_stubs import completed_task
from app.services.modeling_service import ModelingDomainError, fit_arx_core
from app.services.optimization_service import run_study
from app.services.preprocessing_analysis_service import AnalysisDomainError
from app.services.report_service import ReportDomainError
from app.services.segment_service import SegmentDomainError, run_segment_selection
from app.services.version_data import VersionDataError, VersionSeries, load_version_series

CODE_VERSION = "1.1.0-agent"


class AgentDomainError(Exception):
    """A client-safe agent failure for the standard error envelope."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


@dataclass
class StepExecution:
    """The record of one executed step, kept whether it succeeded or not."""

    step_id: str
    tool: str
    status: str
    parameters: dict[str, Any]
    summary: str
    result: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    error_code: str | None = None


@dataclass(frozen=True)
class ToolCapability:
    """One planner tool's persisted execution ownership contract."""

    mode: str
    requires_confirmation: bool
    handler: str
    continuation: str


_TOOL_CAPABILITIES: dict[str, ToolCapability] = {
    "profile_dataset": ToolCapability("DIRECT_EXECUTABLE", False, "direct", "controller"),
    "align_and_resample": ToolCapability("DIRECT_EXECUTABLE", False, "direct", "controller"),
    "detect_anomalies": ToolCapability("DIRECT_EXECUTABLE", False, "direct", "controller"),
    "clean_data": ToolCapability("FORMAL_EXECUTABLE", False, "formal", "controller"),
    "detect_dynamic_segments": ToolCapability("FORMAL_EXECUTABLE", False, "formal", "controller"),
    "estimate_delays": ToolCapability("FORMAL_EXECUTABLE", False, "formal", "controller"),
    "apply_lag_compensation": ToolCapability("WAITING_CONFIRMATION", True, "formal", "confirm"),
    "analyze_collinearity": ToolCapability("FORMAL_EXECUTABLE", False, "formal", "controller"),
    "select_variables": ToolCapability("WAITING_CONFIRMATION", True, "formal", "confirm"),
    "fit_arx": ToolCapability("WAITING_CONFIRMATION", True, "formal", "confirm"),
    "evaluate_model": ToolCapability("FORMAL_EXECUTABLE", False, "formal", "controller"),
    "optimize_pipeline": ToolCapability("WAITING_CONFIRMATION", True, "formal", "confirm"),
    "generate_report": ToolCapability("FORMAL_EXECUTABLE", False, "formal", "controller"),
    "export_dataset": ToolCapability("WAITING_CONFIRMATION", True, "formal", "confirm"),
}

_FORMAL_ADAPTER_TOOLS = frozenset(
    tool for tool, capability in _TOOL_CAPABILITIES.items() if capability.handler == "formal"
)
_DEFERRED_TOOLS = frozenset()


def _validate_plan_capabilities(steps: list[PlannedStep]) -> None:
    """Reject planner/executor drift before a persistent execution is created."""

    for step in steps:
        capability = _TOOL_CAPABILITIES.get(step.tool)
        if capability is None:
            raise AgentDomainError(
                "AGENT_TOOL_CAPABILITY_UNAVAILABLE",
                f"工具 {step.tool} 没有合法的 Agent 执行能力。",
                status_code=409,
            )
        if step.requires_confirmation != capability.requires_confirmation:
            raise AgentDomainError(
                "AGENT_TOOL_CONFIRMATION_POLICY_MISMATCH",
                f"工具 {step.tool} 的计划确认策略与执行能力不一致。",
                status_code=409,
            )


async def execute_approved_optimization_step(
    session: AsyncSession,
    *,
    execution_id: UUID,
    artifact_root: Path,
) -> AgentExecutionSession:
    """Execute one confirmed optimization step once; terminal replays return its snapshot."""

    execution = await get_execution(session, execution_id=execution_id)
    steps = [step for step in execution.step_runs if step.tool_name == "optimize_pipeline"]
    if len(steps) != 1:
        raise AgentDomainError(
            "OPTIMIZATION_STEP_REQUIRED",
            "当前执行必须恰好包含一个 optimize_pipeline 步骤。",
            status_code=409,
            details={"execution_id": str(execution_id), "count": len(steps)},
        )
    optimization = steps[0]
    if optimization.status in {"SUCCEEDED", "FAILED"}:
        return execution

    execution, _ = await claim_approved_optimization_step(
        session, execution_id=execution.id, step_id=optimization.step_id
    )
    optimization = next(step for step in execution.step_runs if step.step_id == optimization.step_id)
    try:
        result = await execute_agent_tool(
            session,
            execution=execution,
            step=optimization,
            parameters=dict(optimization.input_payload["parameters"]),
            artifact_root=artifact_root,
        )
    except Exception as error:
        return await mark_step_failed(
            session,
            execution_id=execution.id,
            step_id=optimization.step_id,
            error_code=getattr(error, "code", "AGENT_OPTIMIZATION_FAILED"),
            error_message=getattr(error, "message", str(error)),
        )

    return await mark_step_succeeded(
        session,
        execution_id=execution.id,
        step_id=optimization.step_id,
        result_payload=result.result_payload,
        source_version_id=result.source_version_id,
        result_version_id=None,
        processing_run_ids=result.processing_run_ids,
    )

async def execute_pending_evaluation_step(
    session: AsyncSession,
    *,
    execution_id: UUID,
    artifact_root: Path,
) -> AgentExecutionSession:
    """Execute only the persisted pending evaluate_model step for one execution."""

    execution = await get_execution(session, execution_id=execution_id)
    evaluation_steps = [step for step in execution.step_runs if step.tool_name == "evaluate_model"]
    if len(evaluation_steps) != 1:
        raise AgentDomainError(
            "EVALUATION_STEP_REQUIRED",
            "当前执行必须恰好包含一个 evaluate_model 步骤。",
            status_code=409,
            details={"execution_id": str(execution_id), "count": len(evaluation_steps)},
        )

    evaluation = evaluation_steps[0]
    if evaluation.status in {"SUCCEEDED", "FAILED"}:
        return execution
    execution = await start_step(session, execution_id=execution.id, step_id=evaluation.step_id)
    evaluation = next(step for step in execution.step_runs if step.step_id == evaluation.step_id)
    if evaluation.status != "RUNNING":
        raise AgentDomainError(
            "EVALUATION_STEP_NOT_RUNNING",
            "模型评价步骤未进入可执行状态。",
            status_code=409,
            details={"execution_id": str(execution.id), "step_id": evaluation.step_id},
        )

    try:
        result = await execute_agent_tool(
            session,
            execution=execution,
            step=evaluation,
            parameters=dict(evaluation.input_payload["parameters"]),
            artifact_root=artifact_root,
        )
    except Exception as error:
        return await mark_step_failed(
            session,
            execution_id=execution.id,
            step_id=evaluation.step_id,
            error_code=getattr(error, "code", "AGENT_EVALUATION_FAILED"),
            error_message=getattr(error, "message", str(error)),
        )

    return await mark_step_succeeded(
        session,
        execution_id=execution.id,
        step_id=evaluation.step_id,
        result_payload=result.result_payload,
        source_version_id=result.source_version_id,
        result_version_id=result.result_version_id,
        processing_run_ids=result.processing_run_ids,
    )

async def run_copilot(
    session: AsyncSession,
    *,
    payload: CopilotChatRequest,
    artifact_root: Path,
    provider: LlmProvider | None = None,
) -> CopilotChatData:
    """Plan, verify, execute once, and mirror real outcomes into durable workflow state."""

    series: VersionSeries | None = None
    lag_ready: bool | None = None
    if payload.active_version_id is not None:
        try:
            series = await load_version_series(
                session,
                version_id=payload.active_version_id,
                artifact_root=artifact_root,
                dataset_id=payload.dataset_id,
            )
            input_columns, _ = series.resolve_columns(input_columns=None, output_column=None)
            try:
                await resolve_arx_lag_provenance(
                    session,
                    version_id=series.version_id,
                    input_columns=input_columns,
                )
            except ArxStructureError as error:
                if error.code not in {
                    "ARX_LAG_COMPENSATED_VERSION_REQUIRED",
                    "ARX_LAG_PROVENANCE_INCOMPLETE",
                }:
                    raise
                lag_ready = False
            else:
                lag_ready = True
        except VersionDataError as error:
            raise AgentDomainError(
                error.code, error.message, status_code=error.status_code, details=error.details
            ) from error

    intent = parse_intent(payload.message)
    planner = LlmPlanner(provider or _resolve_provider(), code_version=CODE_VERSION)
    outcome: PlanOutcome = planner.plan(payload.message, intent, lag_ready=lag_ready)
    steps, assumptions, stop_conditions = (
        outcome.steps,
        list(outcome.assumptions),
        outcome.stop_conditions,
    )


    steps, lag_steps_removed = _normalize_plan_for_lag_context(
        steps, lag_ready=lag_ready
    )
    _validate_plan_capabilities(steps)
    if lag_steps_removed:
        assumptions.append(
            "当前 DatasetVersion 已由服务器验证为时滞补偿就绪，计划已跳过重复的时滞估计与补偿。"
        )
    if outcome.fallback_reason:
        assumptions.append(f"未采用大模型计划：{outcome.fallback_reason}")

    confirmed = frozenset(
        str(step_id) for step_id in payload.context.get("confirmed_steps", []) or []
    )
    raw_steps = [
        {
            "step_id": step.step_id,
            "tool": step.tool,
            "depends_on": list(step.depends_on),
            "parameters": dict(step.parameters),
            "requires_confirmation": step.requires_confirmation,
        }
        for step in steps
    ]
    proof = verify_plan(
        raw_steps,
        code_version=CODE_VERSION,
        confirmed_steps=confirmed,
        lag_ready=lag_ready,
    )
    execution_plan = ExecutionPlan(
        goal=payload.message,
        dataset_id=payload.dataset_id,
        steps=[
            ExecutionPlanStep(
                step_id=step.step_id,
                tool=step.tool,
                depends_on=list(step.depends_on),
                parameters=dict(step.parameters),
                requires_confirmation=step.requires_confirmation,
            )
            for step in steps
        ],
        stop_conditions=stop_conditions,
        assumptions=assumptions,
    )

    run_id = uuid4()
    executions: list[StepExecution] = []
    persistent_execution: AgentExecutionSession | None = None

    if proof.passed and payload.active_version_id is not None:
        assert series is not None
        persistent_execution = await create_execution(
            session,
            dataset_id=series.dataset_id,
            initial_version_id=series.version_id,
            planner_source=outcome.source,
            plan=execution_plan,
            compliance_proof=proof,
            copilot_run_id=run_id,
        )
        if _uses_formal_tool_adapter(steps):
            persistent_execution, executions = await _execute_with_formal_tools(
                session,
                execution=persistent_execution,
                series=series,
                steps=steps,
                hints=intent.parameters,
                artifact_root=artifact_root,
            )
        else:
            # _execute (and the _dispatch it drives) is synchronous and can run a full
            # Optuna closed-loop search (optimize_pipeline) inline. Off the event loop via
            # a worker thread so one chat turn can't freeze every other request this
            # process is serving.
            executions = await run_in_threadpool(_execute, series, steps, intent.parameters)
            persistent_execution = await _sync_execution_state(
                session,
                execution=persistent_execution,
                executions=executions,
            )

    conclusion = _conclusion(proof, executions, intent.goals)
    await _persist(
        session,
        run_id=run_id,
        payload=payload,
        proof=proof,
        executions=executions,
        series=series,
        plan_source=outcome.source,
        llm_model=outcome.model,
    )

    return CopilotChatData(
        copilot_run_id=run_id,
        execution_id=persistent_execution.id if persistent_execution else None,
        workflow_status=persistent_execution.workflow_status if persistent_execution else None,
        current_version_id=persistent_execution.current_version_id if persistent_execution else None,
        pending_confirmation_step_id=(
            persistent_execution.pending_confirmation_step_id if persistent_execution else None
        ),
        plan=ExecutionPlan(
            goal=execution_plan.goal,
            dataset_id=execution_plan.dataset_id,
            steps=[
                ExecutionPlanStep(
                    step_id=step.step_id,
                    tool=step.tool,
                    depends_on=list(step.depends_on),
                    parameters=dict(step.parameters),
                    requires_confirmation=step.requires_confirmation,
                    status=_status_of(step.step_id, executions),
                )
                for step in steps
            ],
            stop_conditions=execution_plan.stop_conditions,
            assumptions=execution_plan.assumptions,
        ),
        task=completed_task(stage="copilot_plan", message=conclusion),
        compliance=ComplianceProofData(**proof.to_payload()),
        step_runs=[
            AgentStepRun(
                step_id=execution.step_id,
                tool=execution.tool,
                status=execution.status,
                parameters=execution.parameters,
                summary=execution.summary,
                result=execution.result,
                duration_ms=execution.duration_ms,
                error_code=execution.error_code,
            )
            for execution in executions
        ],
        conclusion=conclusion,
        executed=any(execution.status != "pending" for execution in executions),
        plan_source=outcome.source,
        llm_provider=outcome.provider,
        llm_model=outcome.model,
        llm_fallback_reason=outcome.fallback_reason,
    )


async def execute_approved_export_step(
    session: AsyncSession,
    *,
    execution_id: UUID,
    step_id: str,
    artifact_root: Path,
) -> AgentExecutionSession:
    """Execute one already-approved export step and always persist a terminal outcome."""

    execution = await get_execution(session, execution_id=execution_id)
    export = next(
        (
            step
            for step in execution.step_runs
            if step.step_id == step_id and step.tool_name == "export_dataset"
        ),
        None,
    )
    if export is None:
        raise AgentDomainError(
            "EXPORT_STEP_REQUIRED",
            "当前执行中不存在指定的 export_dataset 步骤。",
            status_code=409,
        )
    if export.status in {"SUCCEEDED", "FAILED"}:
        return execution
    if export.status != "RUNNING" or export.confirmation_status != "APPROVED":
        raise AgentDomainError(
            "EXPORT_STEP_NOT_APPROVED",
            "优选数据导出步骤尚未获得人工确认。",
            status_code=409,
        )

    try:
        result = await execute_agent_tool(
            session,
            execution=execution,
            step=export,
            parameters=dict(export.input_payload["parameters"]),
            artifact_root=artifact_root,
        )
    except Exception as error:
        return await mark_step_failed(
            session,
            execution_id=execution.id,
            step_id=export.step_id,
            error_code=getattr(error, "code", "AGENT_EXPORT_FAILED"),
            error_message=getattr(error, "message", "优选数据导出失败。"),
        )

    return await mark_step_succeeded(
        session,
        execution_id=execution.id,
        step_id=export.step_id,
        result_payload=result.result_payload,
        source_version_id=result.source_version_id,
        result_version_id=result.result_version_id,
        processing_run_ids=result.processing_run_ids,
    )

def _normalize_plan_for_lag_context(
    steps: list[PlannedStep], *, lag_ready: bool | None
) -> tuple[list[PlannedStep], bool]:
    """Remove redundant lag work only while the initial lineage remains valid."""

    if lag_ready is not True or not any(step.tool == "fit_arx" for step in steps):
        return steps, False
    clean_seen = False
    for step in steps:
        if step.tool == "clean_data":
            clean_seen = True
        elif step.tool == "fit_arx" and clean_seen:
            # Cleaning produces a preprocessing.clean version, which is intentionally not
            # ARX-eligible. Preserve the plan's post-clean Delay -> Lag chain so it can
            # establish fresh provenance for the version the fit will actually consume.
            return steps, False
    removed_ids = {
        step.step_id
        for step in steps
        if step.tool in {"estimate_delays", "apply_lag_compensation"}
    }
    if not removed_ids:
        return steps, False

    by_id = {step.step_id: step for step in steps}

    def retained_dependencies(step_id: str) -> list[str]:
        if step_id not in removed_ids:
            return [step_id]
        expanded: list[str] = []
        for dependency in by_id[step_id].depends_on:
            for retained in retained_dependencies(dependency):
                if retained not in expanded:
                    expanded.append(retained)
        return expanded

    kept = [step for step in steps if step.step_id not in removed_ids]
    new_ids = {step.step_id: f"s{index}" for index, step in enumerate(kept, start=1)}
    normalized: list[PlannedStep] = []
    for step in kept:
        dependencies: list[str] = []
        for dependency in step.depends_on:
            for retained in retained_dependencies(dependency):
                mapped = new_ids[retained]
                if mapped not in dependencies:
                    dependencies.append(mapped)
        normalized.append(
            PlannedStep(
                step_id=new_ids[step.step_id],
                tool=step.tool,
                depends_on=tuple(dependencies),
                parameters=dict(step.parameters),
                requires_confirmation=step.requires_confirmation,
            )
        )
    return normalized, True


def _uses_formal_tool_adapter(steps: list[PlannedStep]) -> bool:
    return any(step.tool in _FORMAL_ADAPTER_TOOLS for step in steps)


async def continue_agent_execution(
    session: AsyncSession,
    *,
    execution_id: UUID,
    artifact_root: Path,
) -> AgentExecutionSession:
    """Resume pending ordinary steps until the next persisted workflow boundary."""

    execution = await get_execution(session, execution_id=execution_id)
    if execution.workflow_status in {"SUCCEEDED", "FAILED", "CANCELLED", "WAITING_CONFIRMATION"}:
        return execution
    series = await load_version_series(
        session,
        version_id=execution.current_version_id,
        dataset_id=execution.dataset_id,
        artifact_root=artifact_root,
    )
    plan = ExecutionPlan.model_validate(execution.plan_json)
    steps = [
        PlannedStep(
            step_id=step.step_id,
            tool=step.tool,
            depends_on=tuple(step.depends_on),
            parameters=dict(step.parameters),
            requires_confirmation=step.requires_confirmation,
        )
        for step in plan.steps
    ]
    execution, _ = await _execute_with_formal_tools(
        session,
        execution=execution,
        series=series,
        steps=steps,
        hints={},
        artifact_root=artifact_root,
    )
    return execution


async def _execute_with_formal_tools(
    session: AsyncSession,
    *,
    execution: AgentExecutionSession,
    series: VersionSeries,
    steps: list[PlannedStep],
    hints: dict[str, Any],
    artifact_root: Path,
) -> tuple[AgentExecutionSession, list[StepExecution]]:
    """Run a mixed plan once while formal tools resolve the latest persisted Version."""

    current = await get_execution(session, execution_id=execution.id)
    executions: list[StepExecution] = []

    for step in steps:
        persisted_step = next(item for item in current.step_runs if item.step_id == step.step_id)
        if persisted_step.status in {"SUCCEEDED", "SKIPPED"}:
            continue
        if persisted_step.status != "PENDING":
            break

        try:
            step_series = await load_version_series(
                session,
                version_id=current.current_version_id,
                dataset_id=current.dataset_id,
                artifact_root=artifact_root,
            )
            input_columns, output_column = step_series.resolve_columns(
                input_columns=None,
                output_column=None,
            )
        except VersionDataError as error:
            current = await mark_step_preparation_failed(
                session,
                execution_id=current.id,
                step_id=step.step_id,
                error_code=error.code,
                error_message=error.message,
            )
            executions.append(
                StepExecution(
                    step_id=step.step_id,
                    tool=step.tool,
                    status="failed",
                    parameters=dict(step.parameters),
                    summary=error.message,
                    error_code=error.code,
                )
            )
            break

        context: dict[str, Any] = {
            "input_columns": input_columns,
            "output_column": output_column,
            "selected_indices": [],
            "delays": {column: 0 for column in input_columns},
            "na": 2,
            "nb": 2,
        }

        confirmation_input: dict[str, Any] | None = None
        try:
            if step.tool == "apply_lag_compensation":
                confirmation_input = await prepare_lag_confirmation(
                    current, step_id=step.step_id
                )
            elif step.tool == "select_variables":
                confirmation_input = await prepare_feature_confirmation(
                    current, step_id=step.step_id
                )
            elif step.tool == "fit_arx":
                confirmation_input = await prepare_arx_confirmation(
                    session,
                    current,
                    step_id=step.step_id,
                    artifact_root=artifact_root,
                )
        except (
            LagOverrideError,
            FeatureSelectionError,
            ArxStructureError,
            VersionDataError,
        ) as error:
            current = await mark_step_preparation_failed(
                session,
                execution_id=current.id,
                step_id=step.step_id,
                error_code=error.code,
                error_message=error.message,
            )
            executions.append(
                StepExecution(
                    step_id=step.step_id,
                    tool=step.tool,
                    status="failed",
                    parameters=dict(step.parameters),
                    summary=error.message,
                    error_code=error.code,
                )
            )
            break

        current = await start_step(
            session,
            execution_id=current.id,
            step_id=step.step_id,
            input_payload_update=confirmation_input,
        )
        persisted_step = next(item for item in current.step_runs if item.step_id == step.step_id)
        if step.requires_confirmation:
            executions.append(
                StepExecution(
                    step_id=step.step_id,
                    tool=step.tool,
                    status="waiting_confirmation",
                    parameters=dict(step.parameters),
                    summary="高影响操作，等待人工确认后执行。",
                    result=confirmation_input or {},
                )
            )
            break

        started = time.perf_counter()
        try:
            if step.tool in _FORMAL_ADAPTER_TOOLS:
                tool_result = await execute_agent_tool(
                    session,
                    execution=current,
                    step=persisted_step,
                    parameters=dict(step.parameters),
                    artifact_root=artifact_root,
                )
                result = dict(tool_result.result_payload)
                summary = tool_result.summary
                current = await mark_step_succeeded(
                    session,
                    execution_id=current.id,
                    step_id=step.step_id,
                    result_payload=result,
                    source_version_id=tool_result.source_version_id,
                    result_version_id=tool_result.result_version_id,
                    processing_run_ids=tool_result.processing_run_ids,
                )
            else:
                # See the comment on the sibling _execute() call site: _dispatch can run
                # optimize_pipeline's synchronous Optuna search, so it must not run on the
                # event loop thread.
                summary, result = await run_in_threadpool(
                    _dispatch,
                    step,
                    step_series,
                    context,
                    hints,
                )
                if result.get("deferred"):
                    raise AgentDomainError(
                        "UNEXPECTED_DEFERRED_AGENT_TOOL",
                        f"持久 Agent 执行器遇到未声明的 deferred 工具：{step.tool}",
                        status_code=500,
                    )
                current = await mark_step_succeeded(
                    session,
                    execution_id=current.id,
                    step_id=step.step_id,
                    result_payload={
                        "summary": summary,
                        "result": dict(result),
                    },
                )
            executions.append(
                StepExecution(
                    step_id=step.step_id,
                    tool=step.tool,
                    status="completed",
                    parameters=dict(step.parameters),
                    summary=summary,
                    result=result,
                    duration_ms=(time.perf_counter() - started) * 1000.0,
                )
            )
        except (
            AgentDomainError,
            AgentToolAdapterError,
            ArxStructureError,
            CleaningDomainError,
            FeatureSelectionError,
            LagOverrideError,
            SegmentDomainError,
            ModelingDomainError,
            AnalysisDomainError,
            ReportDomainError,
            VersionDataError,
        ) as error:
            error_code = getattr(error, "code", "AGENT_STEP_FAILED")
            error_message = getattr(error, "message", str(error))
            current = await mark_step_failed(
                session,
                execution_id=current.id,
                step_id=step.step_id,
                error_code=error_code,
                error_message=error_message,
            )
            executions.append(
                StepExecution(
                    step_id=step.step_id,
                    tool=step.tool,
                    status="failed",
                    parameters=dict(step.parameters),
                    summary=error_message,
                    duration_ms=(time.perf_counter() - started) * 1000.0,
                    error_code=error_code,
                )
            )
            break
        except Exception:
            error_code = "AGENT_UNEXPECTED_STEP_ERROR"
            error_message = "步骤执行期间发生未预期错误。"
            current = await mark_step_failed(
                session,
                execution_id=current.id,
                step_id=step.step_id,
                error_code=error_code,
                error_message=error_message,
            )
            executions.append(
                StepExecution(
                    step_id=step.step_id,
                    tool=step.tool,
                    status="failed",
                    parameters=dict(step.parameters),
                    summary=error_message,
                    duration_ms=(time.perf_counter() - started) * 1000.0,
                    error_code=error_code,
                )
            )
            break

    if current.workflow_status in {"PLANNED", "RUNNING"}:
        orphan = next(
            (
                item
                for item in current.step_runs
                if item.status in {"PENDING", "RUNNING"}
            ),
            None,
        )
        if orphan is not None:
            if orphan.status == "PENDING":
                current = await start_step(
                    session,
                    execution_id=current.id,
                    step_id=orphan.step_id,
                )
                orphan = next(item for item in current.step_runs if item.step_id == orphan.step_id)
            if orphan.status == "RUNNING":
                current = await mark_step_failed(
                    session,
                    execution_id=current.id,
                    step_id=orphan.step_id,
                    error_code="AGENT_CONTROLLER_OWNER_MISSING",
                    error_message="执行器退出时该步骤没有合法的 continuation owner。",
                )
                executions.append(
                    StepExecution(
                        step_id=orphan.step_id,
                        tool=orphan.tool_name,
                        status="failed",
                        parameters=dict(orphan.input_payload.get("parameters") or {}),
                        summary="执行器退出时该步骤没有合法的 continuation owner。",
                        error_code="AGENT_CONTROLLER_OWNER_MISSING",
                    )
                )
    return current, executions

def _execute(
    series: VersionSeries,
    steps: list[PlannedStep],
    hints: dict[str, Any],
) -> list[StepExecution]:
    """Run each step against the real services, stopping at the first hard failure."""

    try:
        input_columns, output_column = series.resolve_columns(
            input_columns=None, output_column=None
        )
    except VersionDataError as error:
        return [
            StepExecution(
                step_id="s0",
                tool="profile_dataset",
                status="failed",
                parameters={},
                summary=error.message,
                error_code=error.code,
            )
        ]

    context: dict[str, Any] = {
        "input_columns": input_columns,
        "output_column": output_column,
        "selected_indices": [],
        "delays": {column: 0 for column in input_columns},
        "na": 2,
        "nb": 2,
    }
    executions: list[StepExecution] = []

    for step in steps:
        if step.requires_confirmation:
            executions.append(
                StepExecution(
                    step_id=step.step_id,
                    tool=step.tool,
                    status="waiting_confirmation",
                    parameters=dict(step.parameters),
                    summary="高影响操作，等待人工确认后执行。",
                )
            )
            return executions

        started = time.perf_counter()
        try:
            summary, result = _dispatch(step, series, context, hints)
            status = "pending" if result.get("deferred") else "completed"
            error_code = None
        except (SegmentDomainError, ModelingDomainError, AnalysisDomainError) as error:
            summary, result, status, error_code = error.message, {}, "failed", error.code
        except VersionDataError as error:
            summary, result, status, error_code = error.message, {}, "failed", error.code

        executions.append(
            StepExecution(
                step_id=step.step_id,
                tool=step.tool,
                status=status,
                parameters=dict(step.parameters),
                summary=summary,
                result=result,
                duration_ms=(time.perf_counter() - started) * 1000.0,
                error_code=error_code,
            )
        )
        if status in {"failed", "pending"}:
            break
    return executions


async def _sync_execution_state(
    session: AsyncSession,
    *,
    execution: AgentExecutionSession,
    executions: list[StepExecution],
) -> AgentExecutionSession:
    """Mirror executor outcomes without dispatching a tool a second time."""

    current = execution
    for executed in executions:
        if executed.status == "pending":
            break

        current = await start_step(
            session,
            execution_id=current.id,
            step_id=executed.step_id,
        )
        if executed.status == "waiting_confirmation":
            break

        result_payload = {
            "summary": executed.summary,
            "result": dict(executed.result),
            "duration_ms": executed.duration_ms,
            "error_code": executed.error_code,
        }
        if executed.status == "completed":
            current = await mark_step_succeeded(
                session,
                execution_id=current.id,
                step_id=executed.step_id,
                result_payload=result_payload,
            )
        elif executed.status == "failed":
            current = await mark_step_failed(
                session,
                execution_id=current.id,
                step_id=executed.step_id,
                error_code=executed.error_code or "AGENT_STEP_FAILED",
                error_message=executed.summary,
                result_payload=result_payload,
            )
            break
        else:
            raise AgentDomainError(
                "INVALID_AGENT_STEP_STATUS",
                f"Agent 执行器返回了无法持久化的步骤状态：{executed.status}",
                status_code=500,
            )
    return current

def _dispatch(
    step: PlannedStep,
    series: VersionSeries,
    context: dict[str, Any],
    hints: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Map one whitelisted tool to the service that implements it."""

    inputs = {column: series.values[column] for column in context["input_columns"]}
    output = series.values[context["output_column"]]

    if step.tool == "profile_dataset":
        from algorithms.pipeline.fingerprint import build_fingerprint

        fingerprint = build_fingerprint(inputs=inputs, output=output)
        return (
            f"数据画像完成：{series.n_samples} 个样本，"
            f"{len(context['input_columns'])} 个输入变量。",
            {"fingerprint": fingerprint.to_payload(), "n_samples": series.n_samples},
        )

    if step.tool in {"detect_anomalies", "clean_data", "align_and_resample"}:
        from algorithms.identifiability.gating import estimate_noise_sigma, hampel_anomaly_mask

        mask = hampel_anomaly_mask(output)
        ratio = float(mask.mean()) if mask.size else 0.0
        return (
            f"检出疑似异常点 {int(mask.sum())} 个（占比 {ratio:.2%}），"
            f"噪声水平估计 {estimate_noise_sigma(output):.4g}。",
            {"anomaly_count": int(mask.sum()), "anomaly_ratio": ratio},
        )

    if step.tool == "detect_dynamic_segments":
        segment_request = SegmentRequest(
            version_id=series.version_id,
            input_columns=context["input_columns"],
            output_column=context["output_column"],
            window_size=int(step.parameters.get("window_size", hints.get("window_size", 60))),
            max_segments=int(step.parameters.get("max_segments", hints.get("max_segments", 8))),
        )
        outcome = run_segment_selection(series, segment_request)
        context["selected_indices"] = outcome.selected_sample_indices
        return (
            f"质量门控通过 {outcome.gating.accepted_count}/{len(outcome.gating.windows)} 个窗口，"
            f"D-最优优选出 {len(outcome.selection.selected)} 个区间，"
            f"采样占比 {outcome.selection.coverage_ratio:.2%}。",
            {
                "selected_count": len(outcome.selection.selected),
                "coverage_ratio": outcome.selection.coverage_ratio,
                "gated_count": outcome.gating.accepted_count,
                "candidate_count": len(outcome.gating.windows),
            },
        )

    if step.tool == "estimate_delays":
        from algorithms.identifiability.delay import estimate_delays

        delay_result = estimate_delays(
            inputs=inputs,
            output=output,
            max_lag=int(step.parameters.get("max_lag", hints.get("max_lag", 30))),
        )
        context["delays"] = dict(delay_result.refined_delays)
        rendered = ", ".join(f"{k}={v}" for k, v in delay_result.refined_delays.items())
        return (
            f"预白化互相关与验证集复核给出时滞：{rendered}；"
            f"验证集自由仿真 FIT {delay_result.validation_fit:.2f}%。",
            {
                "delays": dict(delay_result.refined_delays),
                "validation_fit": delay_result.validation_fit,
            },
        )

    if step.tool in {"analyze_collinearity", "select_variables"}:
        from algorithms.identifiability.collinearity import analyze_collinearity

        if len(inputs) < 2:
            return "输入变量少于两个，跳过共线性分析。", {"skipped": True}
        collinearity = analyze_collinearity(inputs=inputs)
        drops = [item.variable for item in collinearity.advice if item.action == "drop"]
        return (
            f"条件数 {collinearity.condition_number:.1f}，"
            f"检出 {len(collinearity.groups)} 个高相关变量组"
            + (f"，建议剔除 {', '.join(drops)}（需人工确认）。" if drops else "。"),
            {
                "condition_number": collinearity.condition_number,
                "groups": [list(group) for group in collinearity.groups],
                "suggested_drops": drops,
            },
        )

    if step.tool in {"fit_arx", "evaluate_model"}:
        fit_request = ArxFitRequest(
            version_id=series.version_id,
            input_columns=context["input_columns"],
            output_column=context["output_column"],
            na=int(context["na"]),
            nb={column: int(context["nb"]) for column in context["input_columns"]},
            delays={column: int(context["delays"][column]) for column in context["input_columns"]},
            training_sample_indices=list(context["selected_indices"]),
        )
        fit_result = fit_arx_core(
            inputs=inputs,
            output=output,
            payload=fit_request,
            input_columns=context["input_columns"],
        )
        free_run = fit_result.metrics.val_free_run_fit or float("nan")
        one_step = fit_result.metrics.val_fit or float("nan")
        return (
            f"ARX 辨识完成：验证集自由仿真 FIT {free_run:.2f}%"
            f"（一步预测 {one_step:.2f}%，差值 {fit_result.validation.fit_gap:.2f}），"
            f"模型{'稳定' if fit_result.validation.stable else '不稳定'}。",
            {
                "val_free_run_fit": free_run,
                "val_one_step_fit": one_step,
                "fit_gap": fit_result.validation.fit_gap,
                "stable": fit_result.validation.stable,
                "training_rows": fit_result.training_rows,
            },
        )

    if step.tool == "optimize_pipeline":
        study_request = OptimizationStartRequest(
            version_id=series.version_id,
            input_columns=context["input_columns"],
            output_column=context["output_column"],
            max_trials=int(step.parameters.get("max_trials", hints.get("max_trials", 15))),
        )
        study = run_study(
            series,
            study_request,
            input_columns=context["input_columns"],
            output_column=context["output_column"],
        )
        return (
            f"闭环寻优完成：{study.statistics['completed_trials']} 个有效试验，"
            f"最优目标值 {study.best_value:.4f}，"
            f"验证集自由仿真 FIT {study.best_metrics.get('val_free_run_fit', float('nan')):.2f}%。",
            {
                "best_value": study.best_value,
                "best_params": study.best_params,
                "statistics": study.statistics,
            },
        )

    if step.tool == "generate_report":
        return "报告生成已排入交付阶段，所有数值均从运行记录解析。", {"deferred": True}

    if step.tool == "export_dataset":
        return "数据集导出为高影响操作，需人工确认后执行。", {"deferred": True}

    return f"工具 {step.tool} 暂无执行实现。", {"skipped": True}


def _status_of(step_id: str, executions: list[StepExecution]) -> str:
    for execution in executions:
        if execution.step_id == step_id:
            return execution.status
    return "pending"


def _conclusion(
    proof: ComplianceProof,
    executions: list[StepExecution],
    goals: frozenset[str],
) -> str:
    if not proof.passed:
        reasons = "；".join(check.detail for check in proof.failures)
        return f"计划未通过合规校验，已阻止执行：{reasons}"
    if not executions:
        return "计划已生成并通过合规校验；请指定数据版本后执行。"
    failed = [execution for execution in executions if execution.status == "failed"]
    waiting = [execution for execution in executions if execution.status == "waiting_confirmation"]
    completed = [execution for execution in executions if execution.status == "completed"]
    parts = [f"已执行 {len(completed)} 个步骤"]
    if waiting:
        parts.append(f"{len(waiting)} 个高影响步骤等待人工确认")
    if failed:
        parts.append(f"{len(failed)} 个步骤失败（{failed[0].error_code}）")
    parts.append(f"识别到的意图：{', '.join(sorted(goals)) or '仅数据诊断'}")
    return "；".join(parts) + "。"


def _resolve_provider() -> LlmProvider:
    """Build the environment or process-local runtime provider."""

    from app.services.llm_runtime_config_service import build_effective_llm_provider

    return build_effective_llm_provider()


def _processing_run_status(proof: ComplianceProof, executions: list[StepExecution]) -> str:
    """Summarise the actual executor state without calling an incomplete run successful."""

    if not proof.passed:
        return "rejected"
    if any(execution.status == "failed" for execution in executions):
        return "failed"
    if any(execution.status == "waiting_confirmation" for execution in executions):
        return "waiting_confirmation"
    if any(execution.status == "pending" for execution in executions):
        return "running"
    return "succeeded"


async def _persist(
    session: AsyncSession,
    *,
    run_id: UUID,
    payload: CopilotChatRequest,
    proof: ComplianceProof,
    executions: list[StepExecution],
    series: VersionSeries | None,
    plan_source: str = "rule_based",
    llm_model: str = "none",
) -> None:
    """Persist the full audit trail: request, proof, every step's input and output."""

    now = datetime.now(UTC)
    run_status = _processing_run_status(proof, executions)
    finished_at = None if run_status in {"waiting_confirmation", "running"} else now
    session.add(
        ProcessingRun(
            id=run_id,
            dataset_id=series.dataset_id if series and series.origin == "dataset" else None,
            source_version_id=series.version_id if series and series.origin == "dataset" else None,
            run_type="agent.copilot",
            status=run_status,
            parameters=payload.model_dump(mode="json"),
            result={
                "plan_source": plan_source,
                "llm_model": llm_model,
                "compliance": proof.to_payload(),
                "steps": [
                    {
                        "step_id": execution.step_id,
                        "tool": execution.tool,
                        "status": execution.status,
                        "parameters": execution.parameters,
                        "summary": execution.summary,
                        "result": execution.result,
                        "duration_ms": execution.duration_ms,
                        "error_code": execution.error_code,
                    }
                    for execution in executions
                ],
            },
            created_at=now,
            finished_at=finished_at,
        )
    )
    session.add(
        OperationLog(
            id=uuid4(),
            event_type=f"agent.copilot.{run_status}",
            subject_id=str(payload.dataset_id) if payload.dataset_id else str(run_id),
            payload_json=json.dumps(
                {
                    "copilot_run_id": str(run_id),
                    "message": payload.message,
                    "compliance_passed": proof.passed,
                    "run_status": run_status,
                    "proof_id": proof.proof_id,
                    "executed_steps": len(executions),
                    "plan_source": plan_source,
                    "llm_model": llm_model,
                    "executed_at": now.isoformat(),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            created_at=now,
        )
    )
    await session.commit()
