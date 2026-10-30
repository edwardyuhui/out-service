"""Controlled feature-selection validation and confirmed Agent execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.agent_execution import AgentExecutionSession, AgentStepRun
from app.models.dataset import DatasetColumn, DatasetVersion
from app.schemas.copilot import (
    FeatureSelectionDecision,
    FeatureSelectionValidationData,
)
from app.services.agent_execution_service import (
    ExecutionStateError,
    approve_step,
    mark_step_failed,
    mark_step_succeeded,
)
from app.services.agent_tool_adapter import execute_agent_tool

FeatureAction = Literal["keep", "drop", "merge", "review"]
SelectionSource = Literal["collinearity_analysis", "manual_override"]


class FeatureSelectionError(Exception):
    """A deterministic validation or completed-replay conflict."""

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
class FeatureSelectionOutcome:
    execution: AgentExecutionSession
    validation: FeatureSelectionValidationData


async def prepare_feature_confirmation(
    execution: AgentExecutionSession, *, step_id: str
) -> dict[str, Any]:
    """Persist the formal analysis recommendation before the confirmation gate."""

    step = _step(execution, step_id)
    recommended, evidence = _feature_recommendation(execution, step)
    return {
        "recommended_selection": recommended,
        "recommended_drop_columns": sorted(
            variable for variable, action in recommended.items() if action == "drop"
        ),
        "recommendation_evidence": evidence,
    }


async def validate_feature_selection(
    session: AsyncSession,
    *,
    execution_id: UUID,
    step_id: str,
    drop_columns: list[str] | None,
) -> FeatureSelectionValidationData:
    """Validate a recommendation or controlled checkbox adjustment without side effects."""

    execution = await _load_execution(session, execution_id)
    step = _step(execution, step_id)
    return await _validate(execution, step, session=session, drop_columns=drop_columns)


async def is_feature_apply_step(
    session: AsyncSession, *, execution_id: UUID, step_id: str
) -> bool:
    """Identify the persisted Feature Apply step without trusting client metadata."""

    execution = await _load_execution(session, execution_id)
    return _step(execution, step_id).tool_name == "select_variables"


async def approve_and_execute_feature_step(
    session: AsyncSession,
    *,
    execution_id: UUID,
    step_id: str,
    drop_columns: list[str] | None,
    artifact_root: Path,
) -> FeatureSelectionOutcome:
    """Approve and execute exactly one formal Feature Apply step."""

    execution = await _load_execution(session, execution_id)
    step = _step(execution, step_id)
    if step.status == "SUCCEEDED" and step.confirmation_status == "APPROVED":
        _require_completed_replay_matches(step, drop_columns)
        return FeatureSelectionOutcome(
            execution=execution,
            validation=_stored_validation(step),
        )

    if (
        execution.workflow_status != "WAITING_CONFIRMATION"
        or execution.pending_confirmation_step_id != step.step_id
        or step.status != "WAITING_CONFIRMATION"
        or step.confirmation_status != "PENDING"
    ):
        raise ExecutionStateError(
            "approve_and_execute_feature_step",
            execution_id=execution.id,
            execution_status=execution.workflow_status,
            step_id=step.step_id,
            step_status=step.status,
        )

    validation = await _validate(
        execution,
        step,
        session=session,
        drop_columns=drop_columns,
    )
    if validation.overall_status == "INVALID":
        raise FeatureSelectionError(
            "FEATURE_SELECTION_INVALID",
            "变量选择未通过正式数据版本硬约束校验。",
            status_code=422,
            details={"validation": validation.model_dump(mode="json")},
        )

    input_payload = _completed_input_payload(step, validation)
    execution = await approve_step(
        session,
        execution_id=execution.id,
        step_id=step.step_id,
    )
    approved_step = _step(execution, step.step_id)
    if not validation.final_drop_columns:
        execution = await mark_step_succeeded(
            session,
            execution_id=execution.id,
            step_id=approved_step.step_id,
            input_payload=input_payload,
            result_payload={
                "operation_name": "feature_selection_noop",
                "source_version_id": str(execution.current_version_id),
                "data_changed": False,
                "summary": {
                    "dropped_columns": [],
                    "kept_input_columns": validation.kept_input_columns,
                    "version_created": False,
                    "reason": "确认保留全部输入变量，未创建新数据版本。",
                    "user_confirmed": True,
                },
                "feature_selection_validation": validation.model_dump(mode="json"),
            },
            source_version_id=execution.current_version_id,
            result_version_id=None,
            processing_run_ids=[],
        )
        return FeatureSelectionOutcome(execution=execution, validation=validation)
    evidence = {
        variable: {
            "recommended_action": validation.recommended_selection[variable],
            "final_action": "drop",
            "source": validation.selection_sources[variable],
        }
        for variable in validation.final_drop_columns
    }
    try:
        result = await execute_agent_tool(
            session,
            execution=execution,
            step=approved_step,
            parameters={
                "drop_columns": validation.final_drop_columns,
                "user_confirmed": True,
                "recommendation_source": (
                    "manual"
                    if "manual_override" in validation.selection_sources.values()
                    else "collinearity_analysis"
                ),
                "evidence": evidence,
            },
            artifact_root=artifact_root,
        )
    except Exception as error:
        error_code = getattr(error, "code", "AGENT_FEATURE_APPLY_FAILED")
        error_message = getattr(error, "message", str(error))
        await mark_step_failed(
            session,
            execution_id=execution.id,
            step_id=approved_step.step_id,
            error_code=error_code,
            error_message=error_message,
            result_payload={
                "feature_selection_validation": validation.model_dump(mode="json")
            },
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
    return FeatureSelectionOutcome(execution=execution, validation=validation)


async def _validate(
    execution: AgentExecutionSession,
    step: AgentStepRun,
    *,
    session: AsyncSession,
    drop_columns: list[str] | None,
) -> FeatureSelectionValidationData:
    if step.tool_name != "select_variables":
        raise FeatureSelectionError(
            "FEATURE_SELECTION_STEP_REQUIRED",
            "当前步骤不是变量筛选 Apply 步骤。",
        )

    recommended, _ = _feature_recommendation(execution, step)
    version = await session.get(DatasetVersion, execution.current_version_id)
    if version is None:
        raise FeatureSelectionError(
            "DATASET_VERSION_NOT_FOUND",
            "当前 Execution 数据版本不存在。",
        )
    columns = list(
        (
            await session.scalars(
                select(DatasetColumn)
                .where(DatasetColumn.version_id == version.id)
                .order_by(DatasetColumn.position)
            )
        ).all()
    )
    all_columns = {column.name for column in columns}
    input_columns = [column.name for column in columns if column.role == "input"]
    input_set = set(input_columns)
    recommended_drop = sorted(
        variable for variable, action in recommended.items() if action == "drop"
    )
    requested = recommended_drop if drop_columns is None else list(drop_columns)

    issues: list[str] = []
    duplicates = sorted({name for name in requested if requested.count(name) > 1})
    unknown = sorted(set(requested) - all_columns)
    forbidden = sorted(set(requested) - input_set - set(unknown))
    if duplicates:
        issues.append(f"变量不能重复选择删除：{', '.join(duplicates)}。")
    if unknown:
        issues.append(f"当前版本不存在变量：{', '.join(unknown)}。")
    if forbidden:
        issues.append(f"只有输入变量可以参与 Feature Selection：{', '.join(forbidden)}。")

    final_drop = sorted(set(requested) & input_set)
    kept = [name for name in input_columns if name not in final_drop]
    if not kept:
        issues.append("变量筛选后至少必须保留一个输入变量。")

    sources: dict[str, SelectionSource] = {}
    decisions: list[FeatureSelectionDecision] = []
    for variable in input_columns:
        recommended_action = recommended.get(variable, "keep")
        recommended_final = "drop" if recommended_action == "drop" else "keep"
        final_action = "drop" if variable in final_drop else "keep"
        source: SelectionSource = (
            "collinearity_analysis"
            if final_action == recommended_final
            else "manual_override"
        )
        sources[variable] = source
        decisions.append(
            FeatureSelectionDecision(
                variable=variable,
                recommended_action=recommended_action,
                final_action=final_action,
                source=source,
            )
        )

    return FeatureSelectionValidationData(
        recommended_selection=recommended,
        recommended_drop_columns=recommended_drop,
        manual_drop_columns=None if drop_columns is None else list(drop_columns),
        final_drop_columns=final_drop,
        kept_input_columns=kept,
        selection_sources=sources,
        decisions=decisions,
        overall_status="INVALID" if issues else "VALID",
        issues=issues,
    )


def _feature_recommendation(
    execution: AgentExecutionSession,
    step: AgentStepRun,
) -> tuple[dict[str, FeatureAction], dict[str, dict[str, object]]]:
    dependency_ids = step.input_payload.get("depends_on", [])
    if not isinstance(dependency_ids, list):
        raise FeatureSelectionError(
            "FEATURE_ANALYSIS_DEPENDENCY_INVALID",
            "变量筛选步骤缺少合法的上游依赖。",
        )
    analysis_steps = [
        candidate
        for candidate in execution.step_runs
        if candidate.step_id in dependency_ids
        and candidate.tool_name == "analyze_collinearity"
    ]
    if len(analysis_steps) != 1 or analysis_steps[0].status != "SUCCEEDED":
        raise FeatureSelectionError(
            "FEATURE_ANALYSIS_RESULT_REQUIRED",
            "变量筛选必须使用同一 Execution 已完成的正式共线性分析结果。",
        )
    analysis = analysis_steps[0]
    if analysis.source_version_id != execution.current_version_id:
        raise FeatureSelectionError(
            "FEATURE_ANALYSIS_VERSION_MISMATCH",
            "共线性分析证据与当前 Execution 数据版本不一致。",
        )
    raw_variables = analysis.result_payload.get("variables")
    raw_recommendations = analysis.result_payload.get("recommendations")
    if not isinstance(raw_variables, list) or not isinstance(raw_recommendations, list):
        raise FeatureSelectionError(
            "FEATURE_ANALYSIS_RESULT_INVALID",
            "共线性分析未保存可执行的正式变量建议。",
        )

    allowed_actions: set[FeatureAction] = {"keep", "drop", "merge", "review"}
    variables = {value for value in raw_variables if isinstance(value, str)}
    recommended: dict[str, FeatureAction] = {}
    evidence: dict[str, dict[str, object]] = {}
    for item in raw_recommendations:
        if not isinstance(item, dict):
            raise FeatureSelectionError(
                "FEATURE_ANALYSIS_RESULT_INVALID",
                "共线性分析建议格式无效。",
            )
        variable = item.get("variable")
        action = item.get("action")
        reason = item.get("reason")
        related = item.get("related_variables", [])
        if (
            not isinstance(variable, str)
            or variable not in variables
            or not isinstance(action, str)
            or action not in allowed_actions
            or not isinstance(reason, str)
            or not isinstance(related, list)
            or any(not isinstance(value, str) for value in related)
            or variable in recommended
        ):
            raise FeatureSelectionError(
                "FEATURE_ANALYSIS_RESULT_INVALID",
                "共线性分析建议格式无效。",
            )
        recommended[variable] = action
        evidence[variable] = {
            "action": action,
            "reason": reason,
            "related_variables": list(related),
        }
    if set(recommended) != variables:
        raise FeatureSelectionError(
            "FEATURE_ANALYSIS_RESULT_INVALID",
            "共线性分析建议未覆盖全部输入变量。",
        )
    return recommended, evidence


def _completed_input_payload(
    step: AgentStepRun,
    validation: FeatureSelectionValidationData,
) -> dict[str, Any]:
    payload = dict(step.input_payload)
    payload.update(
        {
            "recommended_selection": dict(validation.recommended_selection),
            "recommended_drop_columns": list(validation.recommended_drop_columns),
            "manual_drop_columns": (
                None
                if validation.manual_drop_columns is None
                else list(validation.manual_drop_columns)
            ),
            "final_drop_columns": list(validation.final_drop_columns),
            "selection_sources": dict(validation.selection_sources),
            "feature_selection_validation": validation.model_dump(mode="json"),
        }
    )
    return payload


def _require_completed_replay_matches(
    step: AgentStepRun,
    drop_columns: list[str] | None,
) -> None:
    stored_final = step.input_payload.get("final_drop_columns")
    stored_recommended = step.input_payload.get("recommended_drop_columns")
    if not isinstance(stored_final, list) or not isinstance(stored_recommended, list):
        raise FeatureSelectionError(
            "COMPLETED_FEATURE_PROVENANCE_MISSING",
            "已完成步骤缺少变量选择溯源。",
        )
    requested = stored_recommended if drop_columns is None else list(drop_columns)
    if len(requested) != len(set(requested)) or sorted(requested) != sorted(stored_final):
        raise FeatureSelectionError(
            "COMPLETED_FEATURE_SELECTION_CONFLICT",
            "已完成变量筛选不能更换最终选择。",
        )


def _stored_validation(step: AgentStepRun) -> FeatureSelectionValidationData:
    raw = step.input_payload.get("feature_selection_validation")
    if not isinstance(raw, dict):
        raise FeatureSelectionError(
            "COMPLETED_FEATURE_PROVENANCE_MISSING",
            "已完成步骤缺少变量选择校验溯源。",
        )
    return FeatureSelectionValidationData.model_validate(raw)


async def _load_execution(
    session: AsyncSession,
    execution_id: UUID,
) -> AgentExecutionSession:
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
