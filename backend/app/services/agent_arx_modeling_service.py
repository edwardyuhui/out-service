"""Deterministic ARX structure recommendation and confirmed Agent modeling."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.agent_execution import AgentExecutionSession, AgentStepRun
from app.schemas.copilot import (
    ArxStructureManualOverrides,
    ArxStructureValidationData,
)
from app.schemas.modeling import ArxFitRequest
from app.services.agent_execution_service import (
    ExecutionStateError,
    approve_step,
    mark_step_failed,
    mark_step_succeeded,
)
from app.services.agent_tool_adapter import execute_agent_tool
from app.services.modeling_service import ModelingDomainError, _orders, fit_arx_core
from app.services.optimization_service import _structure_grid, objective_value
from app.services.version_data import load_version_series
from app.services.version_provenance_service import (
    VersionProvenanceError,
)
from app.services.version_provenance_service import (
    resolve_arx_lag_provenance as _resolve_arx_lag_provenance,
)


class ArxStructureError(Exception):
    """A deterministic recommendation, validation, or completed-replay error."""

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
class ArxModelingOutcome:
    execution: AgentExecutionSession
    validation: ArxStructureValidationData


async def prepare_arx_confirmation(
    session: AsyncSession,
    execution: AgentExecutionSession,
    *,
    step_id: str,
    artifact_root: Path,
) -> dict[str, Any]:
    """Build a validation-only recommendation before the fit confirmation gate."""

    step = _step(execution, step_id)
    if step.tool_name != "fit_arx":
        raise ArxStructureError("ARX_FIT_STEP_REQUIRED", "当前步骤不是 ARX 拟合步骤。")
    series = await load_version_series(
        session,
        version_id=execution.current_version_id,
        dataset_id=execution.dataset_id,
        artifact_root=artifact_root,
    )
    input_columns, output_column = series.resolve_columns(
        input_columns=None,
        output_column=None,
    )
    delays, lag_version_id, delay_source = await resolve_agent_arx_lag_provenance(
        session,
        execution=execution,
        fit_step=step,
        input_columns=input_columns,
    )
    recommendation = _recommend_structure(
        version_id=execution.current_version_id,
        input_columns=input_columns,
        output_column=output_column,
        inputs={column: series.values[column] for column in input_columns},
        output=series.values[output_column],
        delays=delays,
        lag_version_id=lag_version_id,
        delay_source=delay_source,
    )
    return {"arx_structure_recommendation": recommendation}


async def validate_arx_structure(
    session: AsyncSession,
    *,
    execution_id: UUID,
    step_id: str,
    manual_overrides: ArxStructureManualOverrides,
    artifact_root: Path,
) -> ArxStructureValidationData:
    """Authoritatively validate controlled na/nb overrides without persistence."""

    execution = await _load_execution(session, execution_id)
    step = _step(execution, step_id)
    return await _validate(
        session,
        execution,
        step,
        manual_overrides=manual_overrides,
        artifact_root=artifact_root,
    )


async def is_arx_fit_step(
    session: AsyncSession, *, execution_id: UUID, step_id: str
) -> bool:
    """Identify the persisted ARX fit step without trusting client metadata."""

    execution = await _load_execution(session, execution_id)
    return _step(execution, step_id).tool_name == "fit_arx"


async def approve_and_execute_arx_step(
    session: AsyncSession,
    *,
    execution_id: UUID,
    step_id: str,
    manual_overrides: ArxStructureManualOverrides,
    artifact_root: Path,
) -> ArxModelingOutcome:
    """Approve and formally fit exactly one recommended ARX structure."""

    execution = await _load_execution(session, execution_id)
    step = _step(execution, step_id)
    if step.status == "SUCCEEDED" and step.confirmation_status == "APPROVED":
        _require_completed_replay_matches(step, manual_overrides)
        return ArxModelingOutcome(execution=execution, validation=_stored_validation(step))

    if (
        execution.workflow_status != "WAITING_CONFIRMATION"
        or execution.pending_confirmation_step_id != step.step_id
        or step.status != "WAITING_CONFIRMATION"
        or step.confirmation_status != "PENDING"
    ):
        raise ExecutionStateError(
            "approve_and_execute_arx_step",
            execution_id=execution.id,
            execution_status=execution.workflow_status,
            step_id=step.step_id,
            step_status=step.status,
        )

    validation = await _validate(
        session,
        execution,
        step,
        manual_overrides=manual_overrides,
        artifact_root=artifact_root,
    )
    if validation.overall_status == "INVALID":
        raise ArxStructureError(
            "ARX_STRUCTURE_INVALID",
            "ARX 结构未通过正式数据与模型硬约束校验。",
            status_code=422,
            details={"validation": validation.model_dump(mode="json")},
        )

    input_payload = dict(step.input_payload)
    input_payload.update(
        {
            "manual_overrides": dict(validation.manual_overrides),
            "final_structure": dict(validation.final_structure),
            "structure_sources": dict(validation.structure_sources),
            "arx_structure_validation": validation.model_dump(mode="json"),
        }
    )
    execution = await approve_step(
        session,
        execution_id=execution.id,
        step_id=step.step_id,
    )
    approved_step = _step(execution, step.step_id)
    try:
        result = await execute_agent_tool(
            session,
            execution=execution,
            step=approved_step,
            parameters=dict(validation.final_structure),
            artifact_root=artifact_root,
        )
    except Exception as error:
        error_code = getattr(error, "code", "AGENT_ARX_FIT_FAILED")
        error_message = getattr(error, "message", str(error))
        await mark_step_failed(
            session,
            execution_id=execution.id,
            step_id=approved_step.step_id,
            error_code=error_code,
            error_message=error_message,
            result_payload={"arx_structure_validation": validation.model_dump(mode="json")},
        )
        raise

    execution = await mark_step_succeeded(
        session,
        execution_id=execution.id,
        step_id=approved_step.step_id,
        input_payload=input_payload,
        result_payload=result.result_payload,
        source_version_id=result.source_version_id,
        result_version_id=None,
        processing_run_ids=result.processing_run_ids,
    )
    return ArxModelingOutcome(execution=execution, validation=validation)


def _recommend_structure(
    *,
    version_id: UUID,
    input_columns: list[str],
    output_column: str,
    inputs: dict[str, Any],
    output: Any,
    delays: dict[str, int],
    lag_version_id: UUID,
    delay_source: str,
) -> dict[str, Any]:
    best_value = float("-inf")
    best_candidate: dict[str, Any] | None = None
    best_breakdown: dict[str, Any] = {}
    candidate_summary: list[dict[str, Any]] = []
    valid_candidates = 0

    for candidate in _structure_grid({}):
        # The explicit fit_arx confirmation contract exposes ARX orders only.
        # FIR remains available to the general optimizer and standalone modeling UI.
        if candidate.get("model_type", "ARX") != "ARX":
            continue
        estimator = str(candidate["estimator"])
        payload = ArxFitRequest(
            version_id=version_id,
            input_columns=input_columns,
            output_column=output_column,
            na=int(candidate["na"]),
            nb={column: int(candidate["nb"]) for column in input_columns},
            delays=delays,
            estimator=estimator,
            ridge_alpha=(
                float(candidate["ridge_alpha"])
                if candidate.get("ridge_alpha") is not None
                else None
            ),
            evaluate_test=False,
        )
        normalized_nb = _orders(payload.nb, input_columns, "nb", 1)
        summary: dict[str, Any] = {
            "na": payload.na,
            "nb": normalized_nb,
            "estimator": estimator,
            "ridge_alpha": payload.ridge_alpha,
        }
        try:
            result = fit_arx_core(
                inputs=inputs,
                output=output,
                payload=payload,
                input_columns=input_columns,
            )
            value, breakdown = objective_value(result)
        except ModelingDomainError as error:
            summary.update({"status": "INVALID", "error_code": error.code})
            candidate_summary.append(summary)
            continue
        valid_candidates += 1
        finite_value = float(value) if math.isfinite(value) else None
        summary.update(
            {
                "status": "VALID" if finite_value is not None else "REJECTED",
                "objective": finite_value,
                "validation": breakdown,
            }
        )
        candidate_summary.append(summary)
        if value > best_value:
            best_value = value
            best_candidate = candidate
            best_breakdown = breakdown

    if best_candidate is None:
        raise ArxStructureError(
            "ARX_STRUCTURE_RECOMMENDATION_UNAVAILABLE",
            "当前正式数据无法产生满足稳定性与可辨识性要求的 ARX 结构建议。",
            status_code=422,
            details={"candidate_summary": candidate_summary},
        )

    recommended_nb = {
        column: int(best_candidate["nb"]) for column in input_columns
    }
    return {
        "source_version_id": str(version_id),
        "input_columns": list(input_columns),
        "output_column": output_column,
        "recommended_na": int(best_candidate["na"]),
        "recommended_nb": recommended_nb,
        "recommended_delays": dict(delays),
        "recommended_estimator": str(best_candidate["estimator"]),
        "recommended_ridge_alpha": best_candidate.get("ridge_alpha"),
        "delay_source": delay_source,
        "lag_compensation_version_id": (
            str(lag_version_id)
            if delay_source == "derived_from_lag_compensated_version"
            else None
        ),
        "effective_lag_version_id": str(lag_version_id),
        "selection_method": "existing_deterministic_arx_structure_grid",
        "validation_metric": "optimization_objective_validation_only",
        "tie_break": "first_candidate_in_fixed_grid_on_equal_objective",
        "complexity_rule": "parameter_count_divided_by_40_in_existing_objective",
        "selected_objective": float(best_value),
        "selection_evidence": {
            "best_breakdown": best_breakdown,
            "evaluated_candidates": len(candidate_summary),
            "valid_candidates": valid_candidates,
            "test_partition_used": False,
        },
        "candidate_summary": candidate_summary,
    }


async def _validate(
    session: AsyncSession,
    execution: AgentExecutionSession,
    step: AgentStepRun,
    *,
    manual_overrides: ArxStructureManualOverrides,
    artifact_root: Path,
) -> ArxStructureValidationData:
    if step.tool_name != "fit_arx":
        raise ArxStructureError("ARX_FIT_STEP_REQUIRED", "当前步骤不是 ARX 拟合步骤。")
    recommendation = _stored_recommendation(step)
    if recommendation.get("source_version_id") != str(execution.current_version_id):
        raise ArxStructureError(
            "ARX_RECOMMENDATION_VERSION_MISMATCH",
            "ARX 结构推荐与当前 Execution 数据版本不一致。",
        )

    input_columns = _string_list(recommendation.get("input_columns"), "input_columns")
    recommended_nb = _integer_map(recommendation.get("recommended_nb"), "recommended_nb")
    recommended_delays = _integer_map(
        recommendation.get("recommended_delays"), "recommended_delays"
    )
    recommended_na = recommendation.get("recommended_na")
    issues: list[str] = []
    final_na = recommended_na
    if manual_overrides.na is not None:
        if isinstance(manual_overrides.na, bool) or not isinstance(manual_overrides.na, int):
            issues.append("na 必须是整数。")
        elif not 1 <= manual_overrides.na <= 100:
            issues.append("na 必须位于正式 Schema 的 1 到 100 范围内。")
        else:
            final_na = manual_overrides.na

    final_nb = dict(recommended_nb)
    unknown = sorted(set(manual_overrides.nb) - set(input_columns))
    if unknown:
        issues.append(f"nb 包含当前版本不存在的输入变量：{', '.join(unknown)}。")
    for column, value in manual_overrides.nb.items():
        if column not in input_columns:
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            issues.append(f"{column} 的 nb 必须是整数。")
        elif value < 1:
            issues.append(f"{column} 的 nb 必须大于等于 1。")
        else:
            final_nb[column] = value

    estimator = recommendation.get("recommended_estimator")
    ridge_alpha = recommendation.get("recommended_ridge_alpha")
    final_structure = {
        "input_columns": input_columns,
        "output_column": recommendation.get("output_column"),
        "na": final_na,
        "nb": final_nb,
        "delays": recommended_delays,
        "estimator": estimator,
        "ridge_alpha": ridge_alpha,
    }
    sources = {"na": "structure_recommendation"}
    sources.update({f"nb.{column}": "structure_recommendation" for column in input_columns})
    if manual_overrides.na is not None:
        sources["na"] = "manual_override"
    sources.update(
        {
            f"nb.{column}": "manual_override"
            for column in manual_overrides.nb
            if column in input_columns
        }
    )

    if not issues:
        series = await load_version_series(
            session,
            version_id=execution.current_version_id,
            dataset_id=execution.dataset_id,
            artifact_root=artifact_root,
        )
        try:
            payload = ArxFitRequest(
                version_id=execution.current_version_id,
                dataset_id=execution.dataset_id,
                evaluate_test=False,
                **final_structure,
            )
            fit_arx_core(
                inputs={column: series.values[column] for column in input_columns},
                output=series.values[str(final_structure["output_column"])],
                payload=payload,
                input_columns=input_columns,
            )
        except (ModelingDomainError, ValueError, TypeError) as error:
            issues.append(getattr(error, "message", str(error)))

    return ArxStructureValidationData(
        recommended_structure={
            "na": recommended_na,
            "nb": recommended_nb,
            "delays": recommended_delays,
            "estimator": estimator,
            "ridge_alpha": ridge_alpha,
        },
        manual_overrides=_manual_payload(manual_overrides),
        final_structure=final_structure,
        structure_sources=sources,
        selection_evidence=dict(recommendation),
        overall_status="INVALID" if issues else "VALID",
        issues=issues,
    )


async def resolve_arx_lag_provenance(
    session: AsyncSession,
    *,
    version_id: UUID,
    input_columns: list[str],
) -> tuple[dict[str, int], UUID]:
    try:
        return await _resolve_arx_lag_provenance(
            session,
            version_id=version_id,
            input_columns=input_columns,
        )
    except VersionProvenanceError as error:
        raise ArxStructureError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error


async def resolve_agent_arx_lag_provenance(
    session: AsyncSession,
    *,
    execution: AgentExecutionSession,
    fit_step: AgentStepRun,
    input_columns: list[str],
) -> tuple[dict[str, int], UUID, str]:
    """Resolve global Lag lineage or a version-scoped confirmation from this execution."""

    try:
        delays, lag_version_id = await resolve_arx_lag_provenance(
            session,
            version_id=execution.current_version_id,
            input_columns=input_columns,
        )
    except ArxStructureError:
        delays = _confirmed_zero_lag_noop(
            execution,
            fit_step=fit_step,
            version_id=execution.current_version_id,
            input_columns=input_columns,
        )
        if delays is None:
            raise
        return delays, execution.current_version_id, "confirmed_zero_lag_no_op"
    return delays, lag_version_id, "derived_from_lag_compensated_version"


def _confirmed_zero_lag_noop(
    execution: AgentExecutionSession,
    *,
    fit_step: AgentStepRun,
    version_id: UUID,
    input_columns: list[str],
) -> dict[str, int] | None:
    candidates = sorted(
        (
            step
            for step in execution.step_runs
            if step.sequence < fit_step.sequence
            and step.tool_name == "apply_lag_compensation"
            and step.status == "SUCCEEDED"
            and step.confirmation_status == "APPROVED"
        ),
        key=lambda step: step.sequence,
        reverse=True,
    )
    for candidate in candidates:
        payload = candidate.result_payload
        if (
            payload.get("disposition") != "CONFIRMED_NO_OP"
            or payload.get("user_confirmed") is not True
            or payload.get("source_version_id") != str(version_id)
            or payload.get("effective_version_id") != str(version_id)
            or candidate.source_version_id != version_id
            or candidate.result_version_id is not None
        ):
            continue
        lag_map = payload.get("final_lag_map")
        sources = payload.get("parameter_sources")
        if (
            not isinstance(lag_map, dict)
            or set(lag_map) != set(input_columns)
            or any(
                isinstance(lag_map[column], bool)
                or not isinstance(lag_map[column], int)
                or lag_map[column] != 0
                for column in input_columns
            )
            or not isinstance(sources, dict)
            or set(sources) != set(input_columns)
            or any(
                sources[column] not in {"delay_recommendation", "manual_override"}
                for column in input_columns
            )
        ):
            continue
        if any(
            step.sequence > candidate.sequence
            and step.sequence < fit_step.sequence
            and step.result_version_id is not None
            for step in execution.step_runs
        ):
            return None
        return {column: 0 for column in input_columns}
    return None


def _stored_recommendation(step: AgentStepRun) -> dict[str, Any]:
    raw = step.input_payload.get("arx_structure_recommendation")
    if not isinstance(raw, dict):
        raise ArxStructureError(
            "ARX_STRUCTURE_RECOMMENDATION_REQUIRED",
            "当前 ARX 步骤缺少正式结构推荐。",
        )
    return raw


def _manual_payload(overrides: ArxStructureManualOverrides) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if overrides.na is not None:
        payload["na"] = overrides.na
    if overrides.nb:
        payload["nb"] = dict(overrides.nb)
    return payload


def _require_completed_replay_matches(
    step: AgentStepRun,
    manual_overrides: ArxStructureManualOverrides,
) -> None:
    stored = step.input_payload.get("manual_overrides")
    if not isinstance(stored, dict):
        raise ArxStructureError(
            "COMPLETED_ARX_PROVENANCE_MISSING",
            "已完成 ARX 步骤缺少结构选择溯源。",
        )
    if stored != _manual_payload(manual_overrides):
        raise ArxStructureError(
            "COMPLETED_ARX_STRUCTURE_CONFLICT",
            "已完成 ARX 步骤不能更换 na 或 nb 后重新训练。",
        )


def _stored_validation(step: AgentStepRun) -> ArxStructureValidationData:
    raw = step.input_payload.get("arx_structure_validation")
    if not isinstance(raw, dict):
        raise ArxStructureError(
            "COMPLETED_ARX_PROVENANCE_MISSING",
            "已完成 ARX 步骤缺少结构校验溯源。",
        )
    return ArxStructureValidationData.model_validate(raw)


def _string_list(value: object, name: str) -> list[str]:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) for item in value):
        raise ArxStructureError("ARX_RECOMMENDATION_INVALID", f"{name} 格式无效。")
    return list(value)


def _integer_map(value: object, name: str) -> dict[str, int]:
    if not isinstance(value, dict) or any(
        not isinstance(key, str) or isinstance(item, bool) or not isinstance(item, int)
        for key, item in value.items()
    ):
        raise ArxStructureError("ARX_RECOMMENDATION_INVALID", f"{name} 格式无效。")
    return dict(value)


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
