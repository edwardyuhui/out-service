"""Persisted orchestration for delay estimation and collinearity analysis (phase 6)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import numpy as np
from algorithms.identifiability.collinearity import analyze_collinearity
from algorithms.identifiability.delay import estimate_delays
from algorithms.identifiability.regressor import IdentifiabilityError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset import Dataset, DatasetColumn, DatasetVersion, ProcessingRun
from app.models.operation_log import OperationLog
from app.schemas.datasets import (
    CollinearitySourceVersion,
    CollinearitySourceVersionsData,
    DelaySourceVersion,
    DelaySourceVersionsData,
)
from app.schemas.preprocessing import (
    CollinearityData,
    CollinearityRequest,
    DelayData,
    DelayPeak,
    DelayRequest,
    InputDiagnostic,
    VariableRecommendation,
)
from app.services.contract_stubs import completed_task
from app.services.version_data import VersionDataError, VersionSeries, load_version_series


class AnalysisDomainError(Exception):
    """A client-safe delay/collinearity failure for the standard error envelope."""

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


async def run_delay_estimation(
    session: AsyncSession,
    *,
    payload: DelayRequest,
    artifact_root: Path,
) -> DelayData:
    """Prewhitened cross-correlation candidates refined on the validation split."""

    series = await _load(session, payload.version_id, artifact_root, payload.dataset_id)
    input_columns, output_column = _resolve(series, payload.input_columns, payload.output_column)

    try:
        result = estimate_delays(
            inputs={column: series.values[column] for column in input_columns},
            output=series.values[output_column],
            max_lag=payload.max_lag,
            top_k=payload.top_k,
        )
    except IdentifiabilityError as error:
        raise AnalysisDomainError(error.code, error.message, details=error.details) from error

    estimates = {estimate.column: estimate for estimate in result.estimates}
    persisted_result = result.to_payload()
    persisted_result["correlations"] = {
        column: list(estimates[column].correlations) for column in input_columns
    }
    processing_run_id = await _persist(
        session,
        series=series,
        run_type="preprocessing.delay",
        parameters=payload.model_dump(mode="json"),
        result=persisted_result,
        event="preprocessing.delay.completed",
    )

    return DelayData(
        source_version_id=series.version_id,
        processing_run_id=processing_run_id,
        task=completed_task(
            stage="estimate_delays",
            message="预白化互相关候选与验证集复核已完成。",
        ),
        delays=[result.refined_delays[column] for column in input_columns],
        correlations={column: list(estimates[column].correlations) for column in input_columns},
        best_delays=dict(result.refined_delays),
        candidate_peaks={
            column: [
                DelayPeak(
                    lag=candidate.lag,
                    correlation=float(np.clip(candidate.correlation, -1.0, 1.0)),
                    confidence=candidate.confidence,
                )
                for candidate in estimates[column].candidates
            ]
            for column in input_columns
        },
        dataset_id=series.dataset_id,
        validation_fit=_finite(result.validation_fit),
        refinement_rounds=result.refinement_rounds,
        uncertain_columns=list(result.uncertain_columns),
        prewhitening_orders={
            column: estimates[column].prewhitening_order for column in input_columns
        },
    )


async def get_latest_delay_result(
    session: AsyncSession,
    *,
    version_id: UUID,
    dataset_id: UUID | None = None,
) -> DelayData:
    """Load the newest complete persisted delay analysis without re-running it."""

    statement = (
        select(ProcessingRun)
        .where(
            ProcessingRun.source_version_id == version_id,
            ProcessingRun.run_type == "preprocessing.delay",
            ProcessingRun.status == "succeeded",
        )
        .order_by(ProcessingRun.created_at.desc())
    )
    if dataset_id is not None:
        statement = statement.where(ProcessingRun.dataset_id == dataset_id)
    runs = list((await session.scalars(statement)).all())

    rehydrated = _latest_rehydrated_delay_result(runs)
    if rehydrated is not None:
        return rehydrated

    if runs:
        raise AnalysisDomainError(
            "DELAY_RESULT_UNAVAILABLE",
            "未找到包含完整 correlation spectrum 的可恢复时滞分析结果。",
            status_code=404,
            details={"source_version_id": str(version_id)},
        )
    raise AnalysisDomainError(
        "DELAY_RESULT_NOT_FOUND",
        "未找到该数据版本的成功时滞分析记录。",
        status_code=404,
        details={"source_version_id": str(version_id)},
    )


async def get_latest_collinearity_result(
    session: AsyncSession,
    *,
    version_id: UUID,
    dataset_id: UUID | None = None,
) -> CollinearityData:
    """Load the newest complete persisted collinearity analysis without recomputing it."""

    statement = (
        select(ProcessingRun)
        .where(
            ProcessingRun.source_version_id == version_id,
            ProcessingRun.run_type == "preprocessing.collinearity",
            ProcessingRun.status == "succeeded",
        )
        .order_by(ProcessingRun.created_at.desc())
    )
    if dataset_id is not None:
        statement = statement.where(ProcessingRun.dataset_id == dataset_id)
    runs = list((await session.scalars(statement)).all())

    rehydrated = _latest_rehydrated_collinearity_result(runs)
    if rehydrated is not None:
        return rehydrated

    if runs:
        raise AnalysisDomainError(
            "COLLINEARITY_RESULT_UNAVAILABLE",
            "未找到包含完整 VIF 与相关性诊断的可恢复共线性分析结果。",
            status_code=404,
            details={"source_version_id": str(version_id)},
        )
    raise AnalysisDomainError(
        "COLLINEARITY_RESULT_NOT_FOUND",
        "未找到该数据版本的成功共线性分析记录。",
        status_code=404,
        details={"source_version_id": str(version_id)},
    )


async def get_delay_source_versions(
    session: AsyncSession,
    *,
    dataset_id: UUID,
) -> DelaySourceVersionsData:
    """Return every Cleaning version with its rehydratable Delay-analysis state."""

    dataset = await session.get(Dataset, dataset_id)
    if dataset is None:
        raise AnalysisDomainError(
            "DATASET_NOT_FOUND", "数据集不存在。", status_code=404,
            details={"dataset_id": str(dataset_id)},
        )

    versions = list(
        (
            await session.scalars(
                select(DatasetVersion)
                .where(
                    DatasetVersion.dataset_id == dataset.id,
                    DatasetVersion.operation_name == "preprocessing.clean",
                )
                .order_by(DatasetVersion.version_index.desc(), DatasetVersion.created_at.desc())
            )
        ).all()
    )
    if not versions:
        return DelaySourceVersionsData(
            dataset_id=dataset.id,
            default_source_version_id=None,
            sources=[],
        )

    version_ids = [version.id for version in versions]
    source_inputs: dict[UUID, list[str]] = {version.id: [] for version in versions}
    source_columns = list(
        (
            await session.scalars(
                select(DatasetColumn)
                .where(
                    DatasetColumn.version_id.in_(version_ids),
                    DatasetColumn.role == "input",
                )
                .order_by(DatasetColumn.version_id, DatasetColumn.position)
            )
        ).all()
    )
    for column in source_columns:
        source_inputs[column.version_id].append(column.name)

    runs = list(
        (
            await session.scalars(
                select(ProcessingRun)
                .where(
                    ProcessingRun.dataset_id == dataset.id,
                    ProcessingRun.source_version_id.in_(version_ids),
                    ProcessingRun.run_type == "preprocessing.delay",
                    ProcessingRun.status == "succeeded",
                )
                .order_by(ProcessingRun.created_at.desc())
            )
        ).all()
    )
    runs_by_source: dict[UUID, list[ProcessingRun]] = {version.id: [] for version in versions}
    for run in runs:
        if run.source_version_id in runs_by_source:
            runs_by_source[run.source_version_id].append(run)

    sources: list[DelaySourceVersion] = []
    for version in versions:
        rehydrated = _latest_rehydrated_delay_result(runs_by_source[version.id])
        sources.append(
            DelaySourceVersion(
                version_id=version.id,
                version_index=version.version_index,
                name=version.name,
                operation_name=version.operation_name,
                parent_version_id=version.parent_version_id,
                created_at=version.created_at,
                input_columns=source_inputs[version.id],
                delay_status=("complete" if rehydrated is not None else "unrehydratable" if runs_by_source[version.id] else "not_analyzed"),
                latest_complete_delay_run_id=(rehydrated.processing_run_id if rehydrated is not None else None),
            )
        )

    default = next(
        (source.version_id for source in sources if source.delay_status == "complete"),
        sources[0].version_id,
    )
    return DelaySourceVersionsData(
        dataset_id=dataset.id,
        default_source_version_id=default,
        sources=sources,
    )


async def get_collinearity_source_versions(
    session: AsyncSession,
    *,
    dataset_id: UUID,
) -> CollinearitySourceVersionsData:
    """Return every Lag Compensation version with its rehydratable analysis state."""

    dataset = await session.get(Dataset, dataset_id)
    if dataset is None:
        raise AnalysisDomainError(
            "DATASET_NOT_FOUND",
            "数据集不存在。",
            status_code=404,
            details={"dataset_id": str(dataset_id)},
        )

    versions = list(
        (
            await session.scalars(
                select(DatasetVersion)
                .where(
                    DatasetVersion.dataset_id == dataset.id,
                    DatasetVersion.operation_name == "preprocessing.lag_compensation",
                )
                .order_by(DatasetVersion.version_index.desc(), DatasetVersion.created_at.desc())
            )
        ).all()
    )
    if not versions:
        return CollinearitySourceVersionsData(
            dataset_id=dataset.id,
            default_source_version_id=None,
            sources=[],
        )

    version_ids = [version.id for version in versions]
    source_inputs: dict[UUID, list[str]] = {version.id: [] for version in versions}
    source_columns = list(
        (
            await session.scalars(
                select(DatasetColumn)
                .where(
                    DatasetColumn.version_id.in_(version_ids),
                    DatasetColumn.role == "input",
                )
                .order_by(DatasetColumn.version_id, DatasetColumn.position)
            )
        ).all()
    )
    for column in source_columns:
        source_inputs[column.version_id].append(column.name)
    runs = list(
        (
            await session.scalars(
                select(ProcessingRun)
                .where(
                    ProcessingRun.dataset_id == dataset.id,
                    ProcessingRun.source_version_id.in_(version_ids),
                    ProcessingRun.run_type == "preprocessing.collinearity",
                    ProcessingRun.status == "succeeded",
                )
                .order_by(ProcessingRun.created_at.desc())
            )
        ).all()
    )
    runs_by_source: dict[UUID, list[ProcessingRun]] = {version.id: [] for version in versions}
    for run in runs:
        if run.source_version_id in runs_by_source:
            runs_by_source[run.source_version_id].append(run)

    sources: list[CollinearitySourceVersion] = []
    for version in versions:
        source_runs = runs_by_source[version.id]
        rehydrated = _latest_rehydrated_collinearity_result(source_runs)
        sources.append(
            CollinearitySourceVersion(
                version_id=version.id,
                version_index=version.version_index,
                name=version.name,
                operation_name=version.operation_name,
                parent_version_id=version.parent_version_id,
                created_at=version.created_at,
                input_columns=source_inputs[version.id],
                collinearity_status=(
                    "complete"
                    if rehydrated is not None
                    else "unrehydratable"
                    if source_runs
                    else "not_analyzed"
                ),
                latest_complete_collinearity_run_id=(
                    rehydrated.processing_run_id if rehydrated is not None else None
                ),
            )
        )

    default = next(
        (source.version_id for source in sources if source.collinearity_status == "complete"),
        sources[0].version_id,
    )
    return CollinearitySourceVersionsData(
        dataset_id=dataset.id,
        default_source_version_id=default,
        sources=sources,
    )


def _latest_rehydrated_delay_result(runs: list[ProcessingRun]) -> DelayData | None:
    """Use the one persistence-completeness rule for all Delay result readers."""

    for run in runs:
        rehydrated = _rehydrate_delay_data(run)
        if rehydrated is not None:
            return rehydrated
    return None


def _latest_rehydrated_collinearity_result(
    runs: list[ProcessingRun],
) -> CollinearityData | None:
    """Use the one persistence-completeness rule for all Collinearity result readers."""

    for run in runs:
        rehydrated = _rehydrate_collinearity_data(run)
        if rehydrated is not None:
            return rehydrated
    return None


def _rehydrate_delay_data(run: ProcessingRun) -> DelayData | None:
    """Return the existing persisted result only when its full spectrum is present."""

    if run.source_version_id is None:
        return None
    parameters = run.parameters
    result = run.result
    if not isinstance(parameters, Mapping) or not isinstance(result, Mapping):
        return None

    input_columns = parameters.get("input_columns")
    correlations = result.get("correlations")
    refined_delays = result.get("refined_delays")
    estimates = result.get("estimates")
    uncertain_columns = result.get("uncertain_columns")
    validation_fit = result.get("validation_fit")
    refinement_rounds = result.get("refinement_rounds")
    if (
        not isinstance(input_columns, list)
        or not input_columns
        or not isinstance(correlations, Mapping)
        or not isinstance(refined_delays, Mapping)
        or not isinstance(estimates, list)
        or not isinstance(uncertain_columns, list)
        or not isinstance(refinement_rounds, int)
        or (validation_fit is not None and not isinstance(validation_fit, int | float))
    ):
        return None

    estimates_by_column: dict[str, Mapping[str, object]] = {}
    for estimate in estimates:
        if not isinstance(estimate, Mapping):
            return None
        column = estimate.get("column")
        if not isinstance(column, str):
            return None
        estimates_by_column[column] = estimate

    normalized_columns = [column for column in input_columns if isinstance(column, str)]
    if len(normalized_columns) != len(input_columns):
        return None

    candidate_peaks: dict[str, list[DelayPeak]] = {}
    prewhitening_orders: dict[str, int] = {}
    spectrum: dict[str, list[float]] = {}
    best_delays: dict[str, int] = {}
    for column in normalized_columns:
        curve = correlations.get(column)
        delay = refined_delays.get(column)
        estimate = estimates_by_column.get(column)
        if (
            not isinstance(curve, list)
            or not all(isinstance(value, int | float) for value in curve)
            or not isinstance(delay, int)
            or estimate is None
            or not isinstance(estimate.get("candidates"), list)
            or not isinstance(estimate.get("prewhitening_order"), int)
        ):
            return None
        try:
            candidate_peaks[column] = [
                DelayPeak.model_validate(candidate) for candidate in estimate["candidates"]
            ]
        except (TypeError, ValueError):
            return None
        spectrum[column] = list(curve)
        best_delays[column] = delay
        prewhitening_orders[column] = estimate["prewhitening_order"]

    if not all(isinstance(column, str) for column in uncertain_columns):
        return None
    return DelayData(
        source_version_id=run.source_version_id,
        processing_run_id=run.id,
        task=completed_task(
            stage="estimate_delays",
            message="已读取持久化的预白化互相关与验证集精修结果。",
        ),
        delays=[best_delays[column] for column in normalized_columns],
        correlations=spectrum,
        best_delays=best_delays,
        candidate_peaks=candidate_peaks,
        dataset_id=run.dataset_id,
        validation_fit=float(validation_fit) if validation_fit is not None else None,
        refinement_rounds=refinement_rounds,
        uncertain_columns=list(uncertain_columns),
        prewhitening_orders=prewhitening_orders,
    )


async def run_collinearity_analysis(
    session: AsyncSession,
    *,
    payload: CollinearityRequest,
    artifact_root: Path,
) -> CollinearityData:
    """Pearson, Spearman, VIF and condition number, with advisory recommendations."""

    series = await _load(session, payload.version_id, artifact_root, payload.dataset_id)
    input_columns = _resolve_collinearity_input_columns(
        series, payload.input_columns, payload.output_column
    )
    diagnostics, analyzable_columns = _qualify_collinearity_inputs(series, input_columns)

    try:
        result = analyze_collinearity(
            inputs={column: series.values[column] for column in analyzable_columns},
            correlation_threshold=payload.correlation_threshold,
            vif_threshold=payload.vif_threshold,
        )
    except IdentifiabilityError as error:
        raise AnalysisDomainError(error.code, error.message, details=error.details) from error

    persisted_result = _normalize_collinearity_payload(
        _expand_collinearity_payload(
            result.to_payload(),
            input_columns=input_columns,
            diagnostics=diagnostics,
        )
    )
    if not _is_complete_collinearity_payload(persisted_result):
        raise AnalysisDomainError(
            "COLLINEARITY_RESULT_UNAVAILABLE",
            "共线性诊断结果包含不可恢复的相关性矩阵数据。",
        )

    processing_run_id = await _persist(
        session,
        series=series,
        run_type="preprocessing.collinearity",
        parameters=payload.model_dump(mode="json"),
        result=persisted_result,
        event="preprocessing.collinearity.completed",
    )
    response = _collinearity_data_from_payload(
        source_version_id=series.version_id,
        processing_run_id=processing_run_id,
        dataset_id=series.dataset_id,
        result=persisted_result,
        message="相关性、VIF 与条件数诊断已完成。",
    )
    assert response is not None
    return response


def _rehydrate_collinearity_data(run: ProcessingRun) -> CollinearityData | None:
    """Return a persisted Collinearity result only when every response field is usable."""

    if run.source_version_id is None or not isinstance(run.result, Mapping):
        return None
    return _collinearity_data_from_payload(
        source_version_id=run.source_version_id,
        processing_run_id=run.id,
        dataset_id=run.dataset_id,
        result=run.result,
        message="已读取持久化的相关性、VIF 与条件数诊断结果。",
    )


def _normalize_collinearity_payload(payload: Mapping[str, object]) -> dict[str, object]:
    """Make Collinearity persistence JSON-safe without inventing numeric diagnostics."""

    return _normalize_json_numbers(payload)


def _qualify_collinearity_inputs(
    series: VersionSeries,
    input_columns: list[str],
) -> tuple[list[InputDiagnostic], list[str]]:
    """Classify requested inputs before numerical diagnostics.

    Formal input-role boolean columns may reach this function as numeric 0/1 arrays.
    They are retained in the response, but a constant or near-constant column is never
    sent to the correlation/VIF algorithm, which would otherwise manufacture a number
    without statistical meaning.
    """

    available = set(series.available_columns) or set(series.values)
    missing = [column for column in input_columns if column not in available]
    if missing:
        raise AnalysisDomainError(
            "MISSING_INPUT",
            "请求的输入变量不存在。",
            details={"missing_columns": missing, "available_columns": sorted(available)},
        )

    non_numeric = [column for column in input_columns if column not in series.values]
    if non_numeric:
        raise AnalysisDomainError(
            "NON_NUMERIC_INPUT",
            "请求的输入变量不是可用于数值诊断的列。",
            details={"non_numeric_columns": non_numeric},
        )

    diagnostics: list[InputDiagnostic] = []
    analyzable_columns: list[str] = []
    for column in input_columns:
        values = np.asarray(series.values[column], dtype=float)
        finite_values = values[np.isfinite(values)]
        if finite_values.size < 3:
            raise AnalysisDomainError(
                "MISSING_INPUT",
                "输入变量缺少足够的有效数值样本。",
                details={"missing_columns": [column], "finite_samples": int(finite_values.size)},
            )

        variance = float(np.var(finite_values))
        scale = max(float(np.max(np.abs(finite_values))), 1.0)
        near_constant_limit = (64.0 * np.finfo(float).eps * scale) ** 2
        if variance <= near_constant_limit:
            diagnostics.append(
                InputDiagnostic(
                    column=column,
                    status="constant_or_near_constant",
                    reason="常量或近常量特征，方差不足，无法提供可靠的相关性与 VIF 诊断。",
                    variance=variance,
                )
            )
            continue

        diagnostics.append(
            InputDiagnostic(
                column=column,
                status="analyzable",
                reason="数值方差充足，可参与相关性、VIF 与条件数诊断。",
                variance=variance,
            )
        )
        analyzable_columns.append(column)

    if len(analyzable_columns) < 2:
        raise AnalysisDomainError(
            "INSUFFICIENT_ANALYZABLE_INPUTS",
            "共线性诊断至少需要两个方差充足的输入变量。",
            details={"input_diagnostics": [item.model_dump(mode="json") for item in diagnostics]},
        )
    return diagnostics, analyzable_columns


def _resolve_collinearity_input_columns(
    series: VersionSeries,
    requested_inputs: list[str] | None,
    output_column: str | None,
) -> list[str]:
    """Resolve only roles Collinearity actually consumes.

    Unlike modelling stages, this diagnostic has no numerical dependency on an output.
    Keeping input validation here lets the caller distinguish a missing column from a
    present-but-non-numeric one instead of collapsing both into the generic resolver.
    """

    columns = list(requested_inputs or series.declared_inputs)
    if output_column is not None and output_column in columns:
        raise AnalysisDomainError(
            "INVALID_DATASET_SCHEMA",
            "同一列不能同时作为输入和输出。",
            details={"column": output_column},
        )
    if not columns:
        raise AnalysisDomainError(
            "INVALID_DATASET_SCHEMA",
            "数据版本不包含可用的输入变量。",
            details={"available_columns": list(series.available_columns or tuple(series.values))},
        )
    return columns


def _expand_collinearity_payload(
    payload: Mapping[str, object],
    *,
    input_columns: list[str],
    diagnostics: list[InputDiagnostic],
) -> dict[str, object]:
    """Restore every formal input to the response without inventing a coefficient.

    ``analyze_collinearity`` only receives analyzable columns.  This adapter expands
    that mathematically valid result back to the formal input list, using JSON null for
    every unavailable matrix/VIF value and an explicit low-variance recommendation.
    """

    result = dict(payload)
    analyzed_columns = result.get("variables")
    pearson = result.get("pearson")
    spearman = result.get("spearman")
    vif = result.get("vif")
    if (
        not isinstance(analyzed_columns, list)
        or not all(isinstance(column, str) for column in analyzed_columns)
        or not isinstance(pearson, list)
        or not isinstance(spearman, list)
        or not isinstance(vif, Mapping)
    ):
        return result

    position = {column: index for index, column in enumerate(analyzed_columns)}

    def expand_matrix(matrix: list[object]) -> list[list[float | None]]:
        expanded = [[None for _ in input_columns] for _ in input_columns]
        for row_index, row_name in enumerate(input_columns):
            source_row = position.get(row_name)
            if source_row is None or source_row >= len(matrix) or not isinstance(matrix[source_row], list):
                continue
            row = matrix[source_row]
            for column_index, column_name in enumerate(input_columns):
                source_column = position.get(column_name)
                if source_column is None or source_column >= len(row):
                    continue
                value = row[source_column]
                expanded[row_index][column_index] = (
                    float(value) if _is_finite_number(value) else None
                )
        return expanded

    advice = list(result.get("advice", [])) if isinstance(result.get("advice"), list) else []
    for diagnostic in diagnostics:
        if diagnostic.status == "constant_or_near_constant":
            advice.append(
                {
                    "variable": diagnostic.column,
                    "action": "drop",
                    "reason": (
                        "常量/近常量特征，信息量不足；相关系数与 VIF 不可可靠计算，"
                        "建议在人工确认后从后续建模特征集中剔除。"
                    ),
                    "related_variables": [],
                }
            )

    result["variables"] = list(input_columns)
    result["pearson"] = expand_matrix(pearson)
    result["spearman"] = expand_matrix(spearman)
    result["vif"] = {
        column: (_nullable_finite(vif.get(column)) if column in position else None)
        for column in input_columns
    }
    result["advice"] = advice
    result["input_diagnostics"] = [item.model_dump(mode="json") for item in diagnostics]
    return result


def _normalize_json_numbers(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _normalize_json_numbers(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_normalize_json_numbers(item) for item in value]
    if isinstance(value, bool) or not isinstance(value, int | float):
        return value
    return float(value) if np.isfinite(value) else None


def _is_complete_collinearity_payload(result: Mapping[str, object]) -> bool:
    variables = result.get("variables")
    vif = result.get("vif")
    pearson = _nullable_matrix(result.get("pearson"))
    spearman = _nullable_matrix(result.get("spearman"))
    groups = result.get("groups")
    advice = result.get("advice")
    if (
        not isinstance(variables, list)
        or not variables
        or not all(isinstance(column, str) for column in variables)
        or not isinstance(vif, Mapping)
        or set(vif) != set(variables)
        or "condition_number" not in result
        or not _is_nullable_finite(result.get("condition_number"))
        or pearson is None
        or spearman is None
        or len(pearson) != len(variables)
        or any(len(row) != len(variables) for row in pearson)
        or len(spearman) != len(variables)
        or any(len(row) != len(variables) for row in spearman)
        or not isinstance(groups, list)
        or not all(isinstance(group, list) and all(isinstance(item, str) for item in group) for group in groups)
        or not isinstance(advice, list)
    ):
        return False
    diagnostics = result.get("input_diagnostics", [])
    return (
        all(_is_nullable_finite(value) for value in vif.values())
        and _advice_is_valid(advice)
        and _input_diagnostics_are_valid(diagnostics, variables)
    )


def _collinearity_data_from_payload(
    *,
    source_version_id: UUID,
    processing_run_id: UUID,
    dataset_id: UUID | None,
    result: Mapping[str, object],
    message: str,
) -> CollinearityData | None:
    if not _is_complete_collinearity_payload(result):
        return None

    variables = result["variables"]
    vif = result["vif"]
    pearson = _nullable_matrix(result["pearson"])
    spearman = _nullable_matrix(result["spearman"])
    groups = result["groups"]
    advice = result["advice"]
    assert isinstance(variables, list)
    assert isinstance(vif, Mapping)
    assert pearson is not None
    assert spearman is not None
    assert isinstance(groups, list)
    assert isinstance(advice, list)

    raw_diagnostics = result.get("input_diagnostics", [])
    try:
        diagnostics = [InputDiagnostic.model_validate(item) for item in raw_diagnostics]
    except (TypeError, ValueError):
        return None

    try:
        recommendations = [VariableRecommendation.model_validate(item) for item in advice]
    except (TypeError, ValueError):
        return None
    return CollinearityData(
        source_version_id=source_version_id,
        processing_run_id=processing_run_id,
        task=completed_task(stage="analyze_collinearity", message=message),
        variables=list(variables),
        matrix=pearson,
        vif_scores={column: _nullable_finite(value) for column, value in vif.items()},
        condition_number=_nullable_finite(result.get("condition_number")),
        recommendations=recommendations,
        dataset_id=dataset_id,
        spearman_matrix=spearman,
        correlated_groups=[list(group) for group in groups],
        input_diagnostics=diagnostics,
    )


def _nullable_matrix(value: object) -> list[list[float | None]] | None:
    if not isinstance(value, list):
        return None
    matrix: list[list[float | None]] = []
    for row in value:
        if not isinstance(row, list) or not all(_is_nullable_finite(item) for item in row):
            return None
        matrix.append([_nullable_finite(item) for item in row])
    return matrix


def _is_finite_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and bool(np.isfinite(value))


def _is_nullable_finite(value: object) -> bool:
    return value is None or _is_finite_number(value)


def _nullable_finite(value: object) -> float | None:
    return float(value) if _is_finite_number(value) else None


def _advice_is_valid(advice: list[object]) -> bool:
    try:
        [VariableRecommendation.model_validate(item) for item in advice]
    except (TypeError, ValueError):
        return False
    return True


def _input_diagnostics_are_valid(value: object, variables: object) -> bool:
    if not isinstance(value, list) or not isinstance(variables, list):
        return False
    try:
        diagnostics = [InputDiagnostic.model_validate(item) for item in value]
    except (TypeError, ValueError):
        return False
    return [item.column for item in diagnostics] in ([], variables)


async def _load(
    session: AsyncSession,
    version_id: UUID,
    artifact_root: Path,
    dataset_id: UUID | None,
) -> VersionSeries:
    try:
        return await load_version_series(
            session,
            version_id=version_id,
            artifact_root=artifact_root,
            dataset_id=dataset_id,
        )
    except VersionDataError as error:
        raise AnalysisDomainError(
            error.code, error.message, status_code=error.status_code, details=error.details
        ) from error


def _resolve(
    series: VersionSeries,
    input_columns: list[str] | None,
    output_column: str | None,
) -> tuple[list[str], str]:
    try:
        return series.resolve_columns(input_columns=input_columns, output_column=output_column)
    except VersionDataError as error:
        raise AnalysisDomainError(
            error.code, error.message, status_code=error.status_code, details=error.details
        ) from error


async def _persist(
    session: AsyncSession,
    *,
    series: VersionSeries,
    run_type: str,
    parameters: dict[str, object],
    result: dict[str, object],
    event: str,
) -> UUID:
    now = datetime.now(UTC)
    run_id = uuid4()
    session.add(
        ProcessingRun(
            id=run_id,
            dataset_id=series.dataset_id if series.origin == "dataset" else None,
            source_version_id=series.version_id if series.origin == "dataset" else None,
            run_type=run_type,
            status="succeeded",
            parameters=parameters,
            result=result,
            created_at=now,
            finished_at=now,
        )
    )
    session.add(
        OperationLog(
            id=uuid4(),
            event_type=event,
            subject_id=str(series.dataset_id),
            payload_json=json.dumps(
                {
                    "run_id": str(run_id),
                    "version_id": str(series.version_id),
                    "result": result,
                    "executed_at": now.isoformat(),
                },
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ),
            created_at=now,
        )
    )
    await session.commit()
    return run_id


def _finite(value: float, *, fallback: float | None = 0.0) -> float | None:
    return float(value) if np.isfinite(value) else fallback
