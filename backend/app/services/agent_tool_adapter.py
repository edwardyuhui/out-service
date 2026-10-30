"""Narrow bridge from persisted Agent steps to formal domain services."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_execution import AgentExecutionSession, AgentStepRun
from app.models.dataset import ProcessingRun
from app.models.optimization import OptimizationStudy, OptimizationTrialRecord
from app.schemas.modeling import ArxFitRequest
from app.schemas.optimization import OptimizationStartRequest
from app.schemas.preprocessing import (
    CleanRequest,
    CollinearityRequest,
    DelayRequest,
    FeatureSelectionApplyRequest,
    LagCompensationRequest,
    SegmentRequest,
)
from app.schemas.reporting import ExportDatasetRequest, ExportSelectionProvenance, ReportRequest
from app.services.cleaning_service import clean_dataset_version
from app.services.modeling_service import (
    ModelingDomainError,
    evaluate_saved_arx_model,
    fit_arx_on_version,
    load_saved_arx_model,
)
from app.services.optimization_service import execute_agent_optimization_study
from app.services.preprocessing_analysis_service import (
    run_collinearity_analysis,
    run_delay_estimation,
)
from app.services.report_service import export_optimised_dataset, generate_report
from app.services.segment_service import select_dynamic_segments
from app.services.version_data import VersionDataError, load_version_series
from app.services.versioned_preprocessing_service import (
    apply_feature_selection,
    apply_lag_compensation,
)


class AgentToolAdapterError(Exception):
    """A planner payload cannot be mapped to the supported formal tool contract."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class AgentToolResult:
    """Formal service provenance normalized for one persistent Agent step."""

    summary: str
    source_version_id: UUID
    result_version_id: UUID | None
    processing_run_ids: list[str]
    result_payload: dict[str, Any]


_CLEANING_PARAMETER_NAMES = frozenset(CleanRequest.model_fields) - {"version_id", "dataset_id"}
_DELAY_PARAMETER_NAMES = frozenset({"max_lag", "top_k"})
_LAG_PARAMETER_NAMES = frozenset({"lag_map", "user_confirmed", "recommendation_source", "evidence_summary"})
_COLLINEARITY_PARAMETER_NAMES = frozenset({"correlation_threshold", "vif_threshold"})
_FEATURE_PARAMETER_NAMES = frozenset(
    {"drop_columns", "user_confirmed", "recommendation_source", "evidence"}
)


_ARX_PARAMETER_NAMES = frozenset(
    {"input_columns", "output_column", "na", "nb", "delays", "estimator", "ridge_alpha"}
)


async def execute_agent_tool(
    session: AsyncSession,
    *,
    execution: AgentExecutionSession,
    step: AgentStepRun,
    parameters: dict[str, Any],
    artifact_root: Path,
) -> AgentToolResult:
    """Execute only supported formal tools against the execution's current version."""

    if step.tool_name == "clean_data":
        return await _clean(
            session,
            execution=execution,
            parameters=parameters,
            artifact_root=artifact_root,
        )
    if step.tool_name == "estimate_delays":
        return await _estimate_delays(
            session,
            execution=execution,
            parameters=parameters,
            artifact_root=artifact_root,
        )
    if step.tool_name == "apply_lag_compensation":
        return await _apply_lag_compensation(
            session,
            execution=execution,
            parameters=parameters,
            artifact_root=artifact_root,
        )
    if step.tool_name == "analyze_collinearity":
        return await _analyze_collinearity(
            session,
            execution=execution,
            parameters=parameters,
            artifact_root=artifact_root,
        )
    if step.tool_name == "select_variables":
        return await _apply_feature_selection(
            session,
            execution=execution,
            parameters=parameters,
            artifact_root=artifact_root,
        )
    if step.tool_name == "fit_arx":
        return await _fit_arx(
            session,
            execution=execution,
            step=step,
            parameters=parameters,
            artifact_root=artifact_root,
        )
    if step.tool_name == "detect_dynamic_segments":
        return await _detect_dynamic_segments(
            session,
            execution=execution,
            parameters=parameters,
            artifact_root=artifact_root,
        )
    if step.tool_name == "optimize_pipeline":
        return await _optimize_pipeline(
            session,
            execution=execution,
            step=step,
            parameters=parameters,
            artifact_root=artifact_root,
        )
    if step.tool_name == "evaluate_model":
        return await _evaluate_model(
            session,
            execution=execution,
            step=step,
            parameters=parameters,
            artifact_root=artifact_root,
        )
    if step.tool_name == "generate_report":
        return await _generate_report(
            session,
            execution=execution,
            parameters=parameters,
            artifact_root=artifact_root,
        )
    if step.tool_name == "export_dataset":
        return await _export_dataset(
            session,
            execution=execution,
            step=step,
            parameters=parameters,
            artifact_root=artifact_root,
        )
    raise AgentToolAdapterError(
        "UNSUPPORTED_AGENT_TOOL",
        f"Agent Tool Adapter 本轮不支持工具：{step.tool_name}",
    )


def _validated_parameters(
    parameters: dict[str, Any], *, allowed: frozenset[str], tool_name: str
) -> dict[str, Any]:
    unexpected = sorted(set(parameters) - allowed)
    if unexpected:
        raise AgentToolAdapterError(
            "INVALID_AGENT_TOOL_PARAMETERS",
            f"{tool_name} 收到未映射的计划参数：{', '.join(unexpected)}",
        )
    return dict(parameters)


async def _clean(
    session: AsyncSession,
    *,
    execution: AgentExecutionSession,
    parameters: dict[str, Any],
    artifact_root: Path,
) -> AgentToolResult:
    try:
        payload = CleanRequest(
            version_id=execution.current_version_id,
            dataset_id=execution.dataset_id,
            **_validated_parameters(
                parameters, allowed=_CLEANING_PARAMETER_NAMES, tool_name="clean_data"
            ),
        )
    except ValidationError as error:
        raise AgentToolAdapterError("INVALID_AGENT_TOOL_PARAMETERS", str(error)) from error

    data = await clean_dataset_version(session, payload=payload, artifact_root=artifact_root)
    summary = (
        f"正式清洗服务已复用现有不可变版本 {data.effective_version_id}。"
        if data.reused_existing_version
        else f"正式清洗服务已确认版本 {data.effective_version_id} 已收敛，未创建新版本。"
        if not data.created_new_version
        else (
            f"正式清洗服务已生成不可变版本 {data.effective_version_id}，"
            f"共处理 {data.total_cleaned_points} 个数据点。"
        )
    )
    return AgentToolResult(
        summary=summary,
        source_version_id=data.source_version_id,
        result_version_id=data.effective_version_id,
        processing_run_ids=[str(data.processing_run_id)] if data.processing_run_id else [],
        result_payload=data.model_dump(mode="json"),
    )


async def _generate_report(
    session: AsyncSession,
    *,
    execution: AgentExecutionSession,
    parameters: dict[str, Any],
    artifact_root: Path,
) -> AgentToolResult:
    """Generate a provenance-bound report for this execution's current version."""

    _validated_parameters(parameters, allowed=frozenset(), tool_name="generate_report")
    data = await generate_report(
        session,
        payload=ReportRequest(
            execution_id=execution.id,
            dataset_id=execution.dataset_id,
            version_id=execution.current_version_id,
        ),
        artifact_root=artifact_root,
    )
    return AgentToolResult(
        summary=f"正式报告服务已生成报告 {data.report_id}。",
        source_version_id=execution.current_version_id,
        result_version_id=None,
        processing_run_ids=[str(data.report_id)],
        result_payload=data.model_dump(mode="json"),
    )


async def _detect_dynamic_segments(
    session: AsyncSession,
    *,
    execution: AgentExecutionSession,
    parameters: dict[str, Any],
    artifact_root: Path,
) -> AgentToolResult:
    """Persist the current execution's selected samples through the formal segment service."""

    try:
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
        payload = SegmentRequest(
            version_id=execution.current_version_id,
            dataset_id=execution.dataset_id,
            input_columns=input_columns,
            output_column=output_column,
            **_validated_parameters(
                parameters,
                allowed=frozenset(SegmentRequest.model_fields)
                - {"version_id", "dataset_id", "input_columns", "output_column"},
                tool_name="detect_dynamic_segments",
            ),
        )
    except ValidationError as error:
        raise AgentToolAdapterError("INVALID_AGENT_TOOL_PARAMETERS", str(error)) from error

    data = await select_dynamic_segments(session, payload=payload, artifact_root=artifact_root)
    selected_count = data.selection.selected_count if data.selection else len(data.selected_indices)
    return AgentToolResult(
        summary=f"正式样本优选服务已选中 {selected_count} 个动态区间。",
        source_version_id=data.source_version_id,
        result_version_id=None,
        processing_run_ids=[str(data.processing_run_id)] if data.processing_run_id else [],
        result_payload=data.model_dump(mode="json"),
    )


async def _export_dataset(
    session: AsyncSession,
    *,
    execution: AgentExecutionSession,
    step: AgentStepRun,
    parameters: dict[str, Any],
    artifact_root: Path,
) -> AgentToolResult:
    """Export only a formally selected subset from this execution's current version."""

    _validated_parameters(parameters, allowed=frozenset(), tool_name="export_dataset")
    source_version_id = execution.current_version_id
    sample_indices: list[int] = []
    selection_provenance: ExportSelectionProvenance | None = None
    optimization = _latest_successful_optimization(execution, step)
    if optimization is not None:
        source_version_id, sample_indices, selection_provenance = (
            await _resolve_optimization_best_selection(
                session,
                execution=execution,
                optimization=optimization,
                artifact_root=artifact_root,
            )
        )

    data = await export_optimised_dataset(
        session,
        payload=ExportDatasetRequest(
            dataset_id=execution.dataset_id,
            version_id=source_version_id,
            sample_indices=sample_indices,
        ),
        artifact_root=artifact_root,
        selection_provenance=selection_provenance,
    )
    return AgentToolResult(
        summary=f"正式交付服务已导出 {data.exported_rows} 行优选数据。",
        source_version_id=source_version_id,
        result_version_id=None,
        processing_run_ids=[str(data.export_id)],
        result_payload=data.model_dump(mode="json"),
    )


def _latest_successful_optimization(
    execution: AgentExecutionSession, export_step: AgentStepRun
) -> AgentStepRun | None:
    """Use only a successful optimization that precedes this export in the same execution."""

    candidates = [
        item
        for item in execution.step_runs
        if item.tool_name == "optimize_pipeline"
        and item.status == "SUCCEEDED"
        and item.sequence < export_step.sequence
    ]
    return max(candidates, key=lambda item: item.sequence, default=None)


def _required_uuid(payload: dict[str, Any], field: str) -> UUID:
    raw_value = payload.get(field)
    if not isinstance(raw_value, str):
        raise AgentToolAdapterError(
            "OPTIMIZATION_EXPORT_PROVENANCE_INVALID",
            f"优化步骤结果缺少有效的 {field}。",
        )
    try:
        return UUID(raw_value)
    except ValueError as error:
        raise AgentToolAdapterError(
            "OPTIMIZATION_EXPORT_PROVENANCE_INVALID",
            f"优化步骤结果包含无效的 {field}。",
        ) from error


async def _resolve_optimization_best_selection(
    session: AsyncSession,
    *,
    execution: AgentExecutionSession,
    optimization: AgentStepRun,
    artifact_root: Path,
) -> tuple[UUID, list[int], ExportSelectionProvenance]:
    """Resolve and cross-check the exact Best Trial sample selection for delivery."""

    if optimization.source_version_id is None:
        raise AgentToolAdapterError(
            "OPTIMIZATION_EXPORT_PROVENANCE_INVALID",
            "成功的优化步骤缺少来源数据版本。",
        )
    study_id = _required_uuid(optimization.result_payload, "study_id")
    source_version_id = _required_uuid(optimization.result_payload, "source_version_id")
    optimized_model_id = _required_uuid(optimization.result_payload, "optimized_model_id")
    model_id = _required_uuid(optimization.result_payload, "model_id")
    if source_version_id != optimization.source_version_id or model_id != optimized_model_id:
        raise AgentToolAdapterError(
            "OPTIMIZATION_EXPORT_PROVENANCE_INVALID",
            "优化步骤结果中的来源版本或模型标识不一致。",
        )

    study = await session.get(OptimizationStudy, study_id)
    if study is None:
        raise AgentToolAdapterError(
            "OPTIMIZATION_EXPORT_STUDY_NOT_FOUND",
            "无法找到优化步骤声明的 Study。",
        )
    if study.status != "succeeded":
        raise AgentToolAdapterError(
            "OPTIMIZATION_EXPORT_STUDY_NOT_SUCCEEDED",
            "优化步骤声明的 Study 尚未成功完成。",
        )
    if study.best_trial_number is None:
        raise AgentToolAdapterError(
            "OPTIMIZATION_EXPORT_BEST_TRIAL_MISSING",
            "成功的优化 Study 缺少 Best Trial。",
        )
    if (
        study.dataset_id != execution.dataset_id
        or study.version_id != source_version_id
        or study.optimized_model_id != optimized_model_id
    ):
        raise AgentToolAdapterError(
            "OPTIMIZATION_EXPORT_PROVENANCE_MISMATCH",
            "优化 Study 与当前执行、来源版本或优化模型不一致。",
        )

    best_trial = await session.scalar(
        select(OptimizationTrialRecord).where(
            OptimizationTrialRecord.study_id == study.id,
            OptimizationTrialRecord.trial_number == study.best_trial_number,
        )
    )
    if best_trial is None or best_trial.state != "complete":
        raise AgentToolAdapterError(
            "OPTIMIZATION_EXPORT_BEST_TRIAL_INVALID",
            "优化 Study 的 Best Trial 记录不存在或未完成。",
        )

    try:
        saved = load_saved_arx_model(model_id=optimized_model_id, artifact_root=artifact_root)
    except ModelingDomainError as error:
        raise AgentToolAdapterError(
            "OPTIMIZATION_EXPORT_MODEL_ARTIFACT_INVALID",
            "无法从优化模型 artifact 恢复 Best Trial 优选样本。",
        ) from error
    if saved.dataset_id != execution.dataset_id or saved.source_version_id != source_version_id:
        raise AgentToolAdapterError(
            "OPTIMIZATION_EXPORT_MODEL_LINEAGE_MISMATCH",
            "优化模型 artifact 与当前执行的数据集或来源版本不一致。",
        )

    sample_indices = list(saved.payload.training_sample_indices)
    if not sample_indices:
        raise AgentToolAdapterError(
            "OPTIMIZATION_EXPORT_SELECTION_MISSING",
            "优化模型 artifact 未保存 Best Trial 的训练样本下标。",
        )
    if len(sample_indices) != len(set(sample_indices)):
        raise AgentToolAdapterError(
            "OPTIMIZATION_BEST_SELECTION_INVALID",
            "Optuna Best Trial 的训练样本下标包含重复值。",
        )

    try:
        series = await load_version_series(
            session,
            version_id=source_version_id,
            dataset_id=execution.dataset_id,
            artifact_root=artifact_root,
        )
    except VersionDataError:
        raise
    invalid_indices = [
        index for index in sample_indices if index < 0 or index >= series.n_samples
    ]
    if invalid_indices:
        raise AgentToolAdapterError(
            "OPTIMIZATION_BEST_SELECTION_INVALID",
            "Optuna Best Trial 的训练样本下标超出来源数据范围。",
        )
    train_end = int(series.n_samples * saved.payload.train_ratio)
    if any(index >= train_end for index in sample_indices):
        raise AgentToolAdapterError(
            "OPTIMIZATION_BEST_SELECTION_TEST_LEAKAGE",
            "Optuna Best Trial 的导出选择包含 Validation/Test 样本。",
        )

    model_run: ProcessingRun | None = None
    for raw_run_id in optimization.processing_run_ids:
        try:
            run_id = UUID(raw_run_id)
        except (TypeError, ValueError):
            continue
        candidate = await session.get(ProcessingRun, run_id)
        if (
            candidate is not None
            and candidate.run_type == "modeling.arx"
            and candidate.status == "succeeded"
            and (candidate.result or {}).get("model_id") == str(optimized_model_id)
        ):
            model_run = candidate
            break
    if (
        model_run is None
        or model_run.dataset_id != execution.dataset_id
        or model_run.source_version_id != source_version_id
        or list((model_run.parameters or {}).get("training_sample_indices", []))
        != sample_indices
    ):
        raise AgentToolAdapterError(
            "OPTIMIZATION_EXPORT_MODEL_RUN_MISMATCH",
            "优化模型 ProcessingRun 与 Best Trial 模型 artifact 不一致。",
        )

    return (
        source_version_id,
        sample_indices,
        ExportSelectionProvenance(
            study_id=study.id,
            best_trial_number=study.best_trial_number,
            optimized_model_id=optimized_model_id,
        ),
    )


async def _estimate_delays(
    session: AsyncSession,
    *,
    execution: AgentExecutionSession,
    parameters: dict[str, Any],
    artifact_root: Path,
) -> AgentToolResult:
    try:
        series = await load_version_series(
            session,
            version_id=execution.current_version_id,
            dataset_id=execution.dataset_id,
            artifact_root=artifact_root,
        )
        input_columns, output_column = series.resolve_columns(
            input_columns=None, output_column=None
        )
    except VersionDataError:
        raise

    try:
        payload = DelayRequest(
            version_id=execution.current_version_id,
            dataset_id=execution.dataset_id,
            input_columns=input_columns,
            output_column=output_column,
            **_validated_parameters(
                parameters,
                allowed=_DELAY_PARAMETER_NAMES,
                tool_name="estimate_delays",
            ),
        )
    except ValidationError as error:
        raise AgentToolAdapterError("INVALID_AGENT_TOOL_PARAMETERS", str(error)) from error

    data = await run_delay_estimation(session, payload=payload, artifact_root=artifact_root)
    rendered = ", ".join(f"{column}={delay}" for column, delay in data.best_delays.items())
    return AgentToolResult(
        summary=f"正式时滞分析服务已完成：{rendered}。",
        source_version_id=data.source_version_id,
        result_version_id=None,
        processing_run_ids=[str(data.processing_run_id)] if data.processing_run_id else [],
        result_payload=data.model_dump(mode="json"),
    )

async def _apply_lag_compensation(
    session: AsyncSession,
    *,
    execution: AgentExecutionSession,
    parameters: dict[str, Any],
    artifact_root: Path,
) -> AgentToolResult:
    """Apply the validated, human-confirmed lag map through the formal versioned service."""

    try:
        payload = LagCompensationRequest(
            version_id=execution.current_version_id,
            dataset_id=execution.dataset_id,
            **_validated_parameters(
                parameters,
                allowed=_LAG_PARAMETER_NAMES,
                tool_name="apply_lag_compensation",
            ),
        )
    except ValidationError as error:
        raise AgentToolAdapterError("INVALID_AGENT_TOOL_PARAMETERS", str(error)) from error

    data = await apply_lag_compensation(session, payload=payload, artifact_root=artifact_root)
    return AgentToolResult(
        summary=f"正式时滞补偿服务已生成不可变版本 {data.result_version_id}。",
        source_version_id=data.source_version_id,
        result_version_id=data.result_version_id,
        processing_run_ids=[str(data.processing_run_id)],
        result_payload=data.model_dump(mode="json"),
    )

async def _analyze_collinearity(
    session: AsyncSession,
    *,
    execution: AgentExecutionSession,
    parameters: dict[str, Any],
    artifact_root: Path,
) -> AgentToolResult:
    series = await load_version_series(
        session,
        version_id=execution.current_version_id,
        dataset_id=execution.dataset_id,
        artifact_root=artifact_root,
    )
    input_columns, output_column = series.resolve_columns(
        input_columns=None, output_column=None
    )
    try:
        payload = CollinearityRequest(
            version_id=execution.current_version_id,
            dataset_id=execution.dataset_id,
            input_columns=input_columns,
            output_column=output_column,
            **_validated_parameters(
                parameters,
                allowed=_COLLINEARITY_PARAMETER_NAMES,
                tool_name="analyze_collinearity",
            ),
        )
    except ValidationError as error:
        raise AgentToolAdapterError("INVALID_AGENT_TOOL_PARAMETERS", str(error)) from error

    data = await run_collinearity_analysis(
        session, payload=payload, artifact_root=artifact_root
    )
    drops = [item.variable for item in data.recommendations if item.action == "drop"]
    return AgentToolResult(
        summary=(
            f"正式共线性分析已完成，建议剔除 {', '.join(drops)}。"
            if drops
            else "正式共线性分析已完成，当前没有建议剔除的输入变量。"
        ),
        source_version_id=data.source_version_id,
        result_version_id=None,
        processing_run_ids=[str(data.processing_run_id)],
        result_payload=data.model_dump(mode="json"),
    )


async def _apply_feature_selection(
    session: AsyncSession,
    *,
    execution: AgentExecutionSession,
    parameters: dict[str, Any],
    artifact_root: Path,
) -> AgentToolResult:
    try:
        payload = FeatureSelectionApplyRequest(
            version_id=execution.current_version_id,
            dataset_id=execution.dataset_id,
            **_validated_parameters(
                parameters,
                allowed=_FEATURE_PARAMETER_NAMES,
                tool_name="select_variables",
            ),
        )
    except ValidationError as error:
        raise AgentToolAdapterError("INVALID_AGENT_TOOL_PARAMETERS", str(error)) from error

    data = await apply_feature_selection(session, payload=payload, artifact_root=artifact_root)
    return AgentToolResult(
        summary=f"正式变量筛选服务已生成不可变版本 {data.result_version_id}。",
        source_version_id=data.source_version_id,
        result_version_id=data.result_version_id,
        processing_run_ids=[str(data.processing_run_id)],
        result_payload=data.model_dump(mode="json"),
    )

_EVALUATION_MODEL_PRODUCER_TOOLS = frozenset({"fit_arx", "optimize_pipeline"})


def _model_producing_predecessor(
    execution: AgentExecutionSession, step: AgentStepRun
) -> tuple[UUID, UUID]:
    """Resolve exactly one declared successful model producer for saved-model evaluation."""

    dependency_ids = step.input_payload.get("depends_on")
    if not isinstance(dependency_ids, list):
        raise AgentToolAdapterError(
            "EVALUATION_MODEL_PRODUCER_DEPENDENCY_REQUIRED",
            "模型评价步骤缺少已声明的模型生产者依赖。",
        )
    candidates = [
        item
        for item in execution.step_runs
        if item.step_id in dependency_ids and item.tool_name in _EVALUATION_MODEL_PRODUCER_TOOLS
    ]
    if len(candidates) != 1:
        raise AgentToolAdapterError(
            "EVALUATION_MODEL_PRODUCER_DEPENDENCY_REQUIRED",
            "模型评价必须且只能直接依赖一个允许的模型生产步骤。",
        )
    predecessor = candidates[0]
    producer = "FIT" if predecessor.tool_name == "fit_arx" else "OPTIMIZATION"
    if predecessor.status != "SUCCEEDED":
        raise AgentToolAdapterError(
            f"EVALUATION_{producer}_NOT_SUCCEEDED",
            "模型评价依赖的模型生产步骤尚未成功完成。",
        )
    if predecessor.source_version_id is None:
        raise AgentToolAdapterError(
            f"EVALUATION_{producer}_SOURCE_VERSION_MISSING",
            "已完成的模型生产步骤缺少来源数据版本。",
        )
    raw_model_id = predecessor.result_payload.get("model_id")
    if not isinstance(raw_model_id, str):
        raise AgentToolAdapterError(
            f"EVALUATION_{producer}_MODEL_ID_MISSING",
            "已完成的模型生产步骤缺少真实 model_id。",
        )
    try:
        model_id = UUID(raw_model_id)
    except ValueError as error:
        raise AgentToolAdapterError(
            f"EVALUATION_{producer}_MODEL_ID_INVALID",
            "已完成的模型生产步骤含有无效 model_id。",
        ) from error

    if predecessor.tool_name == "optimize_pipeline":
        raw_source_version_id = predecessor.result_payload.get("source_version_id")
        raw_optimized_model_id = predecessor.result_payload.get("optimized_model_id")
        if not isinstance(raw_source_version_id, str):
            raise AgentToolAdapterError(
                "EVALUATION_OPTIMIZATION_SOURCE_VERSION_MISSING",
                "优化步骤结果缺少来源数据版本。",
            )
        try:
            payload_source_version_id = UUID(raw_source_version_id)
        except ValueError as error:
            raise AgentToolAdapterError(
                "EVALUATION_OPTIMIZATION_SOURCE_VERSION_INVALID",
                "优化步骤结果含有无效来源数据版本。",
            ) from error
        if payload_source_version_id != predecessor.source_version_id:
            raise AgentToolAdapterError(
                "EVALUATION_OPTIMIZATION_SOURCE_VERSION_MISMATCH",
                "优化步骤结果与持久化来源版本不一致。",
            )
        if raw_optimized_model_id != raw_model_id:
            raise AgentToolAdapterError(
                "EVALUATION_OPTIMIZATION_MODEL_ID_MISMATCH",
                "优化步骤结果未声明与 model_id 一致的优化模型。",
            )
    return model_id, predecessor.source_version_id

_OPTIMIZATION_PARAMETER_NAMES = frozenset(
    {"max_trials", "timeout_seconds", "random_seed", "search_space", "optimization_policy", "diagnose_feedback"}
)


def _optimization_fit_predecessor(
    execution: AgentExecutionSession, step: AgentStepRun
) -> tuple[UUID, UUID]:
    """Resolve the declared completed fit step used as optimization baseline lineage."""

    dependency_ids = step.input_payload.get("depends_on")
    candidates = [
        item
        for item in execution.step_runs
        if isinstance(dependency_ids, list)
        and item.step_id in dependency_ids
        and item.tool_name == "fit_arx"
    ]
    if len(candidates) != 1:
        raise AgentToolAdapterError(
            "OPTIMIZATION_FIT_DEPENDENCY_REQUIRED",
            "模型寻优必须且只能直接依赖当前工作流中的一个 ARX 拟合步骤。",
        )
    predecessor = candidates[0]
    if predecessor.status != "SUCCEEDED":
        raise AgentToolAdapterError(
            "OPTIMIZATION_FIT_NOT_SUCCEEDED", "模型寻优依赖的 ARX 拟合步骤尚未成功完成。"
        )
    if predecessor.source_version_id is None:
        raise AgentToolAdapterError(
            "OPTIMIZATION_FIT_SOURCE_VERSION_MISSING", "ARX 拟合步骤缺少来源数据版本。"
        )
    raw_model_id = predecessor.result_payload.get("model_id")
    if not isinstance(raw_model_id, str):
        raise AgentToolAdapterError(
            "OPTIMIZATION_FIT_MODEL_ID_MISSING", "ARX 拟合步骤缺少真实 model_id。"
        )
    try:
        return UUID(raw_model_id), predecessor.source_version_id
    except ValueError as error:
        raise AgentToolAdapterError(
            "OPTIMIZATION_FIT_MODEL_ID_INVALID", "ARX 拟合步骤含有无效 model_id。"
        ) from error


async def _optimize_pipeline(
    session: AsyncSession,
    *,
    execution: AgentExecutionSession,
    step: AgentStepRun,
    parameters: dict[str, Any],
    artifact_root: Path,
) -> AgentToolResult:
    """Optimize exactly the saved baseline model's immutable source version."""

    baseline_model_id, source_version_id = _optimization_fit_predecessor(execution, step)
    saved = load_saved_arx_model(model_id=baseline_model_id, artifact_root=artifact_root)
    if saved.source_version_id != source_version_id:
        raise AgentToolAdapterError(
            "OPTIMIZATION_FIT_SOURCE_VERSION_MISMATCH", "ARX 模型 artifact 与声明来源版本不一致。"
        )
    if saved.dataset_id != execution.dataset_id:
        raise AgentToolAdapterError(
            "OPTIMIZATION_FIT_DATASET_MISMATCH", "ARX 模型 artifact 与当前执行数据集不一致。"
        )
    requested = _validated_parameters(
        parameters, allowed=_OPTIMIZATION_PARAMETER_NAMES, tool_name="optimize_pipeline"
    )
    search_space = dict(requested.pop("search_space", {}))
    search_space["nk"] = [0, 0]
    try:
        payload = OptimizationStartRequest(
            version_id=source_version_id,
            input_columns=list(saved.payload.input_columns),
            output_column=saved.payload.output_column,
            search_space=search_space,
            **requested,
        )
    except ValidationError as error:
        raise AgentToolAdapterError("INVALID_AGENT_TOOL_PARAMETERS", str(error)) from error

    result = await execute_agent_optimization_study(
        session,
        payload=payload,
        baseline_model_id=baseline_model_id,
        artifact_root=artifact_root,
        study_id=_optimization_study_id(step),
    )
    return AgentToolResult(
        summary=f"正式模型寻优已生成优化模型 {result.optimized_model_id}。",
        source_version_id=result.source_version_id,
        result_version_id=None,
        processing_run_ids=result.processing_run_ids,
        result_payload={
            "study_id": str(result.study_id),
            "baseline_model_id": str(result.baseline_model_id),
            "model_id": str(result.optimized_model_id),
            "optimized_model_id": str(result.optimized_model_id),
            "source_version_id": str(result.source_version_id),
            "best_params": result.best_params,
            "best_value": result.best_value,
            "objective_semantics": result.objective_semantics,
            "best_validation_feedback": result.best_validation_feedback,
            "best_selection_summary": result.best_selection_summary,
            "best_objective_components": result.best_objective_components,
            "best_diagnosis": result.best_diagnosis,
            "best_bookkeeping": result.best_bookkeeping,
            "convergence": result.convergence,
            "stop_reason": result.stop_reason,
        },
    )


def _optimization_study_id(step: AgentStepRun) -> UUID:
    raw_study_id = step.input_payload.get("optimization_study_id")
    if not isinstance(raw_study_id, str):
        raise AgentToolAdapterError(
            "OPTIMIZATION_STUDY_CLAIM_REQUIRED", "模型寻优步骤缺少已持久化的执行 claim。"
        )
    try:
        return UUID(raw_study_id)
    except ValueError as error:
        raise AgentToolAdapterError(
            "OPTIMIZATION_STUDY_CLAIM_INVALID", "模型寻优步骤含有无效的 Study claim。"
        ) from error

async def _evaluate_model(
    session: AsyncSession,
    *,
    execution: AgentExecutionSession,
    step: AgentStepRun,
    parameters: dict[str, Any],
    artifact_root: Path,
) -> AgentToolResult:
    """Evaluate exactly the saved model from this step's declared model producer."""

    _validated_parameters(parameters, allowed=frozenset(), tool_name="evaluate_model")
    model_id, source_version_id = _model_producing_predecessor(execution, step)
    data = await evaluate_saved_arx_model(
        session,
        model_id=model_id,
        artifact_root=artifact_root,
        expected_source_version_id=source_version_id,
    )
    return AgentToolResult(
        summary=f"已完成模型 {data.model_id} 的 held-out Test 评价。",
        source_version_id=data.source_version_id,
        result_version_id=None,
        processing_run_ids=[str(data.processing_run_id)],
        result_payload=data.model_dump(mode="json"),
    )

async def _fit_arx(
    session: AsyncSession,
    *,
    execution: AgentExecutionSession,
    step: AgentStepRun,
    parameters: dict[str, Any],
    artifact_root: Path,
) -> AgentToolResult:
    """Fit the validated structure once through the formal Modeling Service."""

    try:
        payload = ArxFitRequest(
            version_id=execution.current_version_id,
            dataset_id=execution.dataset_id,
            evaluate_test=False,
            **_validated_parameters(
                parameters,
                allowed=_ARX_PARAMETER_NAMES,
                tool_name="fit_arx",
            ),
        )
    except ValidationError as error:
        raise AgentToolAdapterError("INVALID_AGENT_TOOL_PARAMETERS", str(error)) from error

    from app.services.agent_arx_modeling_service import resolve_agent_arx_lag_provenance

    series = await load_version_series(
        session,
        version_id=execution.current_version_id,
        dataset_id=execution.dataset_id,
        artifact_root=artifact_root,
    )
    input_columns, _ = series.resolve_columns(
        input_columns=payload.input_columns or None,
        output_column=payload.output_column,
    )
    await resolve_agent_arx_lag_provenance(
        session,
        execution=execution,
        fit_step=step,
        input_columns=input_columns,
    )
    data = await fit_arx_on_version(session, payload=payload, artifact_root=artifact_root)
    if data.version_id is None:
        raise AgentToolAdapterError(
            "ARX_MODEL_SOURCE_VERSION_MISSING",
            "正式 ARX Service 未返回模型来源版本。",
        )
    return AgentToolResult(
        summary=f"正式 ARX Service 已生成模型 {data.model_id}。",
        source_version_id=data.version_id,
        result_version_id=None,
        processing_run_ids=[str(data.processing_run_id)],
        result_payload=data.model_dump(mode="json"),
    )
