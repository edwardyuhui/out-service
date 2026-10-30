"""Controlled human overrides and confirmed lag-apply orchestration for Agent steps."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.agent_execution import AgentExecutionSession, AgentStepRun
from app.models.dataset import DatasetColumn, DatasetVersion
from app.schemas.copilot import (
    LagOverrideEntry,
    LagOverrideParameterValidation,
    LagOverrideValidationData,
)
from app.services.agent_execution_service import (
    ExecutionStateError,
    approve_step,
    mark_step_failed,
    mark_step_succeeded,
)
from app.services.agent_tool_adapter import execute_agent_tool


class LagOverrideError(Exception):
    """A deterministic, side-effect-free validation or replay error."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 409,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


@dataclass(frozen=True)
class LagApplyOutcome:
    execution: AgentExecutionSession
    validation: LagOverrideValidationData


async def prepare_lag_confirmation(
    execution: AgentExecutionSession, *, step_id: str
) -> dict[str, Any]:
    """Persist the immutable upstream recommendation before the human confirmation gate."""

    step = _step(execution, step_id)
    recommended, analyzed_max = _delay_recommendation(execution, step)
    return {
        "recommended_lag_map": recommended,
        "manual_overrides": {},
        "final_lag_map": dict(recommended),
        "parameter_sources": {name: "delay_recommendation" for name in recommended},
        "analyzed_max_lag": analyzed_max,
    }


async def validate_lag_overrides(
    session: AsyncSession,
    *,
    execution_id: UUID,
    step_id: str,
    manual_overrides: list[LagOverrideEntry],
) -> LagOverrideValidationData:
    """Return an authoritative validation preview without changing workflow state."""

    execution = await _load_execution(session, execution_id)
    step = _step(execution, step_id)
    return await _validate(execution, step, session=session, manual_overrides=manual_overrides)


async def is_lag_apply_step(
    session: AsyncSession, *, execution_id: UUID, step_id: str
) -> bool:
    """Identify the persisted step without inferring from client-controlled identifiers."""

    execution = await _load_execution(session, execution_id)
    return _step(execution, step_id).tool_name == "apply_lag_compensation"


async def approve_and_execute_lag_step(
    session: AsyncSession,
    *,
    execution_id: UUID,
    step_id: str,
    manual_overrides: list[LagOverrideEntry],
    warning_acknowledged: bool,
    artifact_root: Path,
) -> LagApplyOutcome:
    """Approve exactly one lag step and execute it once through the formal adapter."""

    execution = await _load_execution(session, execution_id)
    step = _step(execution, step_id)
    if step.status == "SUCCEEDED" and step.confirmation_status == "APPROVED":
        _require_completed_replay_matches(step, manual_overrides)
        return LagApplyOutcome(execution=execution, validation=_stored_validation(step))

    if (
        execution.workflow_status != "WAITING_CONFIRMATION"
        or execution.pending_confirmation_step_id != step.step_id
        or step.status != "WAITING_CONFIRMATION"
        or step.confirmation_status != "PENDING"
    ):
        raise ExecutionStateError(
            "approve_and_execute_lag_step",
            execution_id=execution.id,
            execution_status=execution.workflow_status,
            step_id=step.step_id,
            step_status=step.status,
        )

    validation = await _validate(execution, step, session=session, manual_overrides=manual_overrides)
    if validation.overall_status == "INVALID":
        raise LagOverrideError(
            "LAG_OVERRIDE_INVALID",
            "时滞补偿参数未通过硬约束校验。",
            status_code=422,
            details={"validation": validation.model_dump(mode="json")},
        )
    if validation.overall_status == "WARNING" and not warning_acknowledged:
        raise LagOverrideError(
            "LAG_OVERRIDE_WARNING_ACK_REQUIRED",
            "人工时滞覆盖超出本次 Delay Analyze 的搜索范围，确认后才会执行。",
            details={"validation": validation.model_dump(mode="json")},
        )

    input_payload = _completed_input_payload(step, validation, warning_acknowledged)
    execution = await approve_step(session, execution_id=execution.id, step_id=step.step_id)
    approved_step = _step(execution, step.step_id)
    if validation.disposition == "CONFIRMED_NO_OP":
        source_version_id = execution.current_version_id
        result_payload = {
            "disposition": "CONFIRMED_NO_OP",
            "final_lag_map": dict(validation.final_lag_map),
            "parameter_sources": dict(validation.parameter_sources),
            "user_confirmed": True,
            "source_version_id": str(source_version_id),
            "effective_version_id": str(source_version_id),
            "lag_override_validation": validation.model_dump(mode="json"),
        }
        execution = await mark_step_succeeded(
            session,
            execution_id=execution.id,
            step_id=approved_step.step_id,
            input_payload=input_payload,
            result_payload=result_payload,
            source_version_id=source_version_id,
            result_version_id=None,
            processing_run_ids=[],
        )
        return LagApplyOutcome(execution=execution, validation=validation)

    try:
        result = await execute_agent_tool(
            session,
            execution=execution,
            step=approved_step,
            parameters={
                "lag_map": validation.final_lag_map,
                "user_confirmed": True,
                "recommendation_source": "delay_analysis",
                "evidence_summary": _evidence_summary(validation),
            },
            artifact_root=artifact_root,
        )
    except Exception as error:
        error_code = getattr(error, "code", "AGENT_LAG_APPLY_FAILED")
        error_message = getattr(error, "message", str(error))
        await mark_step_failed(
            session,
            execution_id=execution.id,
            step_id=approved_step.step_id,
            error_code=error_code,
            error_message=error_message,
            result_payload={"lag_override_validation": validation.model_dump(mode="json")},
        )
        raise

    execution = await mark_step_succeeded(
        session,
        execution_id=execution.id,
        step_id=approved_step.step_id,
        input_payload=input_payload,
        result_payload=result.result_payload,
        source_version_id=result.source_version_id,
        result_version_id=result.result_version_id,
        processing_run_ids=result.processing_run_ids,
    )
    return LagApplyOutcome(execution=execution, validation=validation)


async def _validate(
    execution: AgentExecutionSession,
    step: AgentStepRun,
    *,
    session: AsyncSession,
    manual_overrides: list[LagOverrideEntry],
) -> LagOverrideValidationData:
    if step.tool_name != "apply_lag_compensation":
        raise LagOverrideError("LAG_STEP_REQUIRED", "当前步骤不是时滞补偿步骤。")

    recommended, analyzed_max = _delay_recommendation(execution, step)
    version = await session.get(DatasetVersion, execution.current_version_id)
    if version is None:
        raise LagOverrideError("DATASET_VERSION_NOT_FOUND", "当前 Execution 数据版本不存在。")
    input_columns = set(
        (
            await session.scalars(
                select(DatasetColumn.name).where(
                    DatasetColumn.version_id == version.id,
                    DatasetColumn.role == "input",
                )
            )
        ).all()
    )

    per_parameter: list[LagOverrideParameterValidation] = []
    accepted: dict[str, int] = {}
    seen: set[str] = set()
    for override in manual_overrides:
        variable = override.variable
        value = override.value
        issues: list[str] = []
        recommended_value = recommended.get(variable)
        if variable in seen:
            issues.append("同一变量只能人工覆盖一次。")
        seen.add(variable)
        if variable not in recommended or variable not in input_columns:
            issues.append("变量不是当前版本可补偿的输入变量。")
        if isinstance(value, bool) or not isinstance(value, int):
            issues.append("时滞必须是整数。")
        elif value < 0:
            issues.append("时滞必须为非负整数。")
        elif value >= version.row_count:
            issues.append("时滞不能使数据行全部被边界裁剪。")

        if issues:
            per_parameter.append(
                LagOverrideParameterValidation(
                    variable=variable,
                    recommended_value=recommended_value,
                    manual_value=value,
                    status="INVALID",
                    issues=issues,
                )
            )
            continue

        status = "WARNING" if value > analyzed_max[variable] else "VALID"
        warning = (
            ["人工覆盖超过当前 Delay Analyze 实际搜索范围，需要再次确认。"]
            if status == "WARNING"
            else []
        )
        accepted[variable] = value
        per_parameter.append(
            LagOverrideParameterValidation(
                variable=variable,
                recommended_value=recommended_value,
                manual_value=value,
                final_value=value,
                status=status,
                issues=warning,
            )
        )

    final_lag_map = dict(recommended)
    final_lag_map.update(accepted)
    sources: dict[str, str] = {name: "delay_recommendation" for name in recommended}
    sources.update({name: "manual_override" for name in accepted})
    issues = [issue for item in per_parameter for issue in item.issues]
    disposition = "APPLY_VERSION"
    if any(item.status == "INVALID" for item in per_parameter):
        overall_status = "INVALID"
    elif final_lag_map and max(final_lag_map.values()) == 0:
        overall_status = "VALID"
        disposition = "CONFIRMED_NO_OP"
    elif any(item.status == "WARNING" for item in per_parameter):
        overall_status = "WARNING"
    else:
        overall_status = "VALID"

    return LagOverrideValidationData(
        recommended_lag_map=recommended,
        manual_overrides=accepted,
        final_lag_map=final_lag_map,
        parameter_sources=sources,
        disposition=disposition,
        per_parameter_validation=per_parameter,
        overall_status=overall_status,
        issues=issues,
    )


def _delay_recommendation(
    execution: AgentExecutionSession, step: AgentStepRun
) -> tuple[dict[str, int], dict[str, int]]:
    dependency_ids = step.input_payload.get("depends_on", [])
    if not isinstance(dependency_ids, list):
        raise LagOverrideError("LAG_DEPENDENCY_INVALID", "时滞补偿步骤缺少合法的上游依赖。")
    delay_steps = [
        candidate
        for candidate in execution.step_runs
        if candidate.step_id in dependency_ids and candidate.tool_name == "estimate_delays"
    ]
    if len(delay_steps) != 1 or delay_steps[0].status != "SUCCEEDED":
        raise LagOverrideError("LAG_DELAY_RESULT_REQUIRED", "时滞补偿必须使用同一 Execution 已完成的 Delay Analyze 结果。")
    payload = delay_steps[0].result_payload
    raw_recommended = payload.get("best_delays")
    raw_correlations = payload.get("correlations")
    if not isinstance(raw_recommended, dict) or not isinstance(raw_correlations, dict):
        raise LagOverrideError("LAG_DELAY_RESULT_INVALID", "Delay Analyze 未保存可用于补偿的正式建议。")

    recommended: dict[str, int] = {}
    analyzed_max: dict[str, int] = {}
    for variable, value in raw_recommended.items():
        correlations = raw_correlations.get(variable)
        if (
            not isinstance(variable, str)
            or isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
            or not isinstance(correlations, list)
            or not correlations
        ):
            raise LagOverrideError("LAG_DELAY_RESULT_INVALID", "Delay Analyze 建议或搜索证据格式无效。")
        recommended[variable] = value
        analyzed_max[variable] = len(correlations) - 1
    if not recommended:
        raise LagOverrideError("LAG_DELAY_RESULT_INVALID", "Delay Analyze 未返回输入变量的时滞建议。")
    return recommended, analyzed_max


def _completed_input_payload(
    step: AgentStepRun,
    validation: LagOverrideValidationData,
    warning_acknowledged: bool,
) -> dict[str, Any]:
    payload = dict(step.input_payload)
    payload.update(
        {
            "recommended_lag_map": dict(validation.recommended_lag_map),
            "manual_overrides": dict(validation.manual_overrides),
            "final_lag_map": dict(validation.final_lag_map),
            "parameter_sources": dict(validation.parameter_sources),
            "lag_override_validation": validation.model_dump(mode="json"),
            "warning_acknowledged": warning_acknowledged,
        }
    )
    return payload


def _evidence_summary(validation: LagOverrideValidationData) -> dict[str, str]:
    return {
        variable: (
            "manual_override"
            if validation.parameter_sources[variable] == "manual_override"
            else "delay_analysis_recommendation"
        )
        for variable in validation.final_lag_map
    }


def _require_completed_replay_matches(
    step: AgentStepRun, manual_overrides: list[LagOverrideEntry]
) -> None:
    requested: dict[str, int] = {}
    for override in manual_overrides:
        if (
            override.variable in requested
            or isinstance(override.value, bool)
            or not isinstance(override.value, int)
        ):
            raise LagOverrideError(
                "COMPLETED_LAG_OVERRIDE_CONFLICT",
                "已完成时滞补偿只能按原始人工覆盖参数幂等重放。",
            )
        requested[override.variable] = override.value
    completed = step.input_payload.get("manual_overrides", {})
    if not isinstance(completed, dict) or requested != completed:
        raise LagOverrideError(
            "COMPLETED_LAG_OVERRIDE_CONFLICT",
            "已完成时滞补偿不能更换人工覆盖参数。",
        )


def _stored_validation(step: AgentStepRun) -> LagOverrideValidationData:
    raw = step.input_payload.get("lag_override_validation")
    if not isinstance(raw, dict):
        raise LagOverrideError("COMPLETED_LAG_PROVENANCE_MISSING", "已完成步骤缺少时滞覆盖溯源。")
    return LagOverrideValidationData.model_validate(raw)


async def _load_execution(session: AsyncSession, execution_id: UUID) -> AgentExecutionSession:
    execution = await session.scalar(
        select(AgentExecutionSession)
        .where(AgentExecutionSession.id == execution_id)
        .options(selectinload(AgentExecutionSession.step_runs))
    )
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
