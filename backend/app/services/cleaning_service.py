"""Persisted preprocessing orchestration for immutable dataset-version derivation."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from math import ceil
from pathlib import Path
from uuid import UUID, uuid4

from algorithms.cleaning.pipeline import (
    CleaningContext,
    CleaningParameters,
    CleaningPipeline,
    CleaningResult,
)
from algorithms.cleaning.quality import build_quality_profile
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset import (
    Dataset,
    DatasetColumn,
    DatasetProfileRecord,
    DatasetVersion,
    ProcessingRun,
)
from app.models.operation_log import OperationLog
from app.schemas.preprocessing import CleanData, CleanRequest, CleanSeries
from app.services.contract_stubs import completed_task
from app.services.dataset_csv import ParsedCsv
from app.services.dataset_version_io import (
    DatasetVersionArtifactError,
    artifact_matches_sha256,
    load_version_csv,
    remove_derived_artifact,
    write_derived_csv,
)

MAX_RESPONSE_POINTS = 10_000


class CleaningDomainError(Exception):
    """A client-safe preprocessing error for the standard API error envelope."""

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


async def clean_dataset_version(
    session: AsyncSession,
    *,
    payload: CleanRequest,
    artifact_root: Path,
) -> CleanData:
    """Run the pure pipeline and atomically register a new immutable derived version."""

    await _begin_sqlite_serialized_write(session)
    source_version = await session.get(DatasetVersion, payload.version_id)
    if source_version is None:
        raise CleaningDomainError(
            "DATASET_VERSION_NOT_FOUND", "待清洗的数据版本不存在。", status_code=404
        )
    dataset = await session.get(Dataset, source_version.dataset_id)
    if dataset is None:
        raise CleaningDomainError(
            "DATASET_NOT_FOUND", "数据版本所属数据集不存在。", status_code=404
        )
    if payload.dataset_id is not None and payload.dataset_id != dataset.id:
        raise CleaningDomainError(
            "DATASET_VERSION_MISMATCH",
            "请求的数据集 ID 不属于给定版本。",
            details={"dataset_id": str(payload.dataset_id), "version_id": str(payload.version_id)},
        )
    source_columns = await _version_columns(session, source_version.id)
    if not source_columns:
        raise CleaningDomainError("INVALID_DATASET_SCHEMA", "数据版本缺少列元数据。")
    try:
        parsed = load_version_csv(
            dataset=dataset, version=source_version, artifact_root=artifact_root
        )
    except DatasetVersionArtifactError as error:
        raise CleaningDomainError(
            error.code, error.message, status_code=404, details=error.details
        ) from error

    parameters = _resolve_parameters(payload)
    context = CleaningContext(
        headers=parsed.headers,
        timestamp_column=parsed.timestamp_column,
        timestamps=parsed.timestamps,
        rows=parsed.rows,
        inferred_types=parsed.inferred_types,
    )
    result = CleaningPipeline().execute(context, parameters)
    if not result.cleaned_numeric:
        raise CleaningDomainError("INVALID_DATASET_SCHEMA", "数据版本不包含可清洗的数值列。")

    candidate_version_id = uuid4()
    processing_run_id = uuid4()
    artifact_path: str | None = None
    try:
        artifact_path, checksum = write_derived_csv(
            artifact_root=artifact_root,
            dataset_id=dataset.id,
            version_id=candidate_version_id,
            headers=parsed.headers,
            timestamp_column=parsed.timestamp_column,
            timestamps=result.timestamps,
            values=result.values,
        )
        source_version = await _lock_source_version(session, source_version.id)
        no_op = checksum == source_version.sha256 or _is_semantic_no_op(parsed, result)
        converged_without_version = (
            source_version.operation_name == "preprocessing.clean" and no_op
        )
        now = datetime.now(UTC)

        if converged_without_version:
            run_result = _processing_run_result(
                derived_version_id=None,
                effective_version_id=source_version.id,
                created_new_version=False,
                no_op=True,
                converged=True,
                reused_existing_version=False,
                result=result,
            )
            remove_derived_artifact(
                artifact_root=artifact_root,
                relative_path=artifact_path,
            )
            artifact_path = None
            run = ProcessingRun(
                id=processing_run_id,
                dataset_id=dataset.id,
                source_version_id=source_version.id,
                run_type="preprocessing.clean",
                status="succeeded",
                parameters=_jsonable_parameters(parameters),
                result=run_result,
                created_at=now,
                finished_at=now,
            )
            audit = OperationLog(
                id=uuid4(),
                event_type="preprocessing.clean.completed",
                subject_id=str(dataset.id),
                payload_json=json.dumps(
                    _operation_log_payload(
                        source_version_id=source_version.id,
                        derived_version_id=None,
                        effective_version_id=source_version.id,
                        created_new_version=False,
                        no_op=True,
                        converged=True,
                        reused_existing_version=False,
                        parameters=parameters,
                        result=result,
                        executed_at=now,
                    ),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                created_at=now,
            )
            session.add_all([run, audit])
            await session.commit()
            return _clean_data(
                dataset_id=dataset.id,
                source_version_id=source_version.id,
                derived_version_id=None,
                effective_version_id=source_version.id,
                created_new_version=False,
                no_op=True,
                converged=True,
                reused_existing_version=False,
                source_columns=source_columns,
                source_row_count=source_version.row_count,
                processing_run_id=processing_run_id,
                parameters=parameters,
                result=result,
            )

        existing_version = await _find_equivalent_cleaning_version(
            session,
            source_version_id=source_version.id,
            normalized_parameters=_jsonable_parameters(parameters),
            checksum=checksum,
            artifact_root=artifact_root,
        )
        if existing_version is not None:
            remove_derived_artifact(
                artifact_root=artifact_root,
                relative_path=artifact_path,
            )
            artifact_path = None
            run_result = _processing_run_result(
                derived_version_id=None,
                effective_version_id=existing_version.id,
                created_new_version=False,
                no_op=False,
                converged=False,
                reused_existing_version=True,
                result=result,
            )
            run = ProcessingRun(
                id=processing_run_id,
                dataset_id=dataset.id,
                source_version_id=source_version.id,
                run_type="preprocessing.clean",
                status="succeeded",
                parameters=_jsonable_parameters(parameters),
                result=run_result,
                created_at=now,
                finished_at=now,
            )
            audit = OperationLog(
                id=uuid4(),
                event_type="preprocessing.clean.completed",
                subject_id=str(dataset.id),
                payload_json=json.dumps(
                    _operation_log_payload(
                        source_version_id=source_version.id,
                        derived_version_id=None,
                        effective_version_id=existing_version.id,
                        created_new_version=False,
                        no_op=False,
                        converged=False,
                        reused_existing_version=True,
                        parameters=parameters,
                        result=result,
                        executed_at=now,
                    ),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                created_at=now,
            )
            dataset.active_version_id = existing_version.id
            dataset.updated_at = now
            session.add_all([run, audit])
            await session.commit()
            return _clean_data(
                dataset_id=dataset.id,
                source_version_id=source_version.id,
                derived_version_id=None,
                effective_version_id=existing_version.id,
                created_new_version=False,
                no_op=False,
                converged=False,
                reused_existing_version=True,
                source_columns=source_columns,
                source_row_count=source_version.row_count,
                processing_run_id=processing_run_id,
                parameters=parameters,
                result=result,
            )

        effective_version_id = candidate_version_id
        derived_version_id = candidate_version_id
        run_result = _processing_run_result(
            derived_version_id=derived_version_id,
            effective_version_id=effective_version_id,
            created_new_version=True,
            no_op=no_op,
            converged=no_op,
            reused_existing_version=False,
            result=result,
        )

        derived_version = DatasetVersion(
            id=candidate_version_id,
            dataset_id=dataset.id,
            parent_version_id=source_version.id,
            version_index=await _next_version_index(session, dataset.id),
            name="",
            operation_name="preprocessing.clean",
            parameters=_version_parameters(payload, parameters, result, source_version.id),
            artifact_path=artifact_path,
            sha256=checksum,
            row_count=len(result.timestamps),
            column_count=len(parsed.headers),
            time_range_start=min(result.timestamps),
            time_range_end=max(result.timestamps),
            created_at=now,
        )
        derived_version.name = f"V{derived_version.version_index} · 清洗规整"
        derived_parsed = load_version_csv(
            dataset=dataset,
            version=derived_version,
            artifact_root=artifact_root,
        )
        profile_payload = build_quality_profile(
            dataset_id=str(dataset.id),
            version_id=str(derived_version.id),
            headers=derived_parsed.headers,
            rows=derived_parsed.rows,
            inferred_types=derived_parsed.inferred_types,
            timestamps=derived_parsed.timestamps,
        ).payload
        copied_columns = _clone_columns(
            source_columns,
            dataset_id=dataset.id,
            version_id=derived_version.id,
            nullable=derived_parsed.nullable,
        )
        profile = DatasetProfileRecord(
            id=uuid4(),
            dataset_id=dataset.id,
            version_id=derived_version.id,
            quality_score=float(profile_payload["quality_score"]),
            profile=profile_payload,
            created_at=now,
            updated_at=now,
        )
        run = ProcessingRun(
            id=processing_run_id,
            dataset_id=dataset.id,
            source_version_id=source_version.id,
            run_type="preprocessing.clean",
            status="succeeded",
            parameters=_jsonable_parameters(parameters),
            result=run_result,
            created_at=now,
            finished_at=now,
        )
        audit = OperationLog(
            id=uuid4(),
            event_type="preprocessing.clean.completed",
            subject_id=str(dataset.id),
            payload_json=json.dumps(
                _operation_log_payload(
                    source_version_id=source_version.id,
                    derived_version_id=derived_version.id,
                    effective_version_id=derived_version.id,
                    created_new_version=True,
                    no_op=no_op,
                    converged=no_op,
                    reused_existing_version=False,
                    parameters=parameters,
                    result=result,
                    executed_at=now,
                ),
                ensure_ascii=False,
                sort_keys=True,
            ),
            created_at=now,
        )
        dataset.active_version_id = derived_version.id
        dataset.updated_at = now
        session.add(derived_version)
        await session.flush()
        session.add_all([*copied_columns, profile, run, audit])
        await session.commit()
    except Exception:
        await session.rollback()
        if artifact_path is not None:
            remove_derived_artifact(artifact_root=artifact_root, relative_path=artifact_path)
        raise

    return _clean_data(
        dataset_id=dataset.id,
        source_version_id=source_version.id,
        derived_version_id=derived_version_id,
        effective_version_id=effective_version_id,
        created_new_version=True,
        no_op=no_op,
        converged=no_op,
        reused_existing_version=False,
        source_columns=source_columns,
        source_row_count=source_version.row_count,
        processing_run_id=processing_run_id,
        parameters=parameters,
        result=result,
    )


def _is_semantic_no_op(parsed: ParsedCsv, result: CleaningResult) -> bool:
    """Confirm that the pipeline preserved cells, shape, and the complete time grid."""

    data_columns = [
        column for column in parsed.headers if column != parsed.timestamp_column
    ]
    return (
        result.total_changed_points == 0
        and result.duplicate_timestamp_count == 0
        and result.resampling_empty_row_count == 0
        and result.timestamps == parsed.timestamps
        and set(result.values) == set(data_columns)
        and all(len(result.values[column]) == len(parsed.rows) for column in data_columns)
    )


def _processing_run_result(
    *,
    derived_version_id: UUID | None,
    effective_version_id: UUID,
    created_new_version: bool,
    no_op: bool,
    converged: bool,
    reused_existing_version: bool,
    result: CleaningResult,
) -> dict[str, object]:
    return {
        "derived_version_id": (
            str(derived_version_id) if derived_version_id is not None else None
        ),
        "effective_version_id": str(effective_version_id),
        "created_new_version": created_new_version,
        "no_op": no_op,
        "converged": converged,
        "reused_existing_version": reused_existing_version,
        "total_cleaned_points": result.total_changed_points,
        "change_summary": result.change_summary,
        "outlier_counts": {
            column: len(indices)
            for column, indices in result.detected_outlier_indices.items()
        },
        "constant_value_segment_count": len(result.constant_value_segments),
        "candidate_frozen_segment_count": len(result.candidate_frozen_segments),
        "warnings": result.warnings,
    }


def _operation_log_payload(
    *,
    source_version_id: UUID,
    derived_version_id: UUID | None,
    effective_version_id: UUID,
    created_new_version: bool,
    no_op: bool,
    converged: bool,
    reused_existing_version: bool,
    parameters: CleaningParameters,
    result: CleaningResult,
    executed_at: datetime,
) -> dict[str, object]:
    return {
        "source_version_id": str(source_version_id),
        "derived_version_id": (
            str(derived_version_id) if derived_version_id is not None else None
        ),
        "effective_version_id": str(effective_version_id),
        "created_new_version": created_new_version,
        "no_op": no_op,
        "converged": converged,
        "reused_existing_version": reused_existing_version,
        "algorithm": CleaningPipeline.name,
        "parameters": _jsonable_parameters(parameters),
        "total_cleaned_points": result.total_changed_points,
        "change_summary": result.change_summary,
        "replaced_indices": result.changed_indices,
        "executed_at": executed_at.isoformat(),
    }


async def _version_columns(session: AsyncSession, version_id: UUID) -> list[DatasetColumn]:
    return list(
        (
            await session.scalars(
                select(DatasetColumn)
                .where(DatasetColumn.version_id == version_id)
                .order_by(DatasetColumn.position)
            )
        ).all()
    )


async def _begin_sqlite_serialized_write(session: AsyncSession) -> None:
    """Use SQLite's database write lock where row-level ``FOR UPDATE`` is unavailable."""

    if session.get_bind().dialect.name == "sqlite" and not session.in_transaction():
        await session.execute(text("BEGIN IMMEDIATE"))


async def _lock_source_version(session: AsyncSession, version_id: UUID) -> DatasetVersion:
    source = await session.scalar(
        select(DatasetVersion)
        .where(DatasetVersion.id == version_id)
        .with_for_update()
    )
    if source is None:
        raise CleaningDomainError(
            "DATASET_VERSION_NOT_FOUND", "待清洗的数据版本不存在。", status_code=404
        )
    return source


async def _find_equivalent_cleaning_version(
    session: AsyncSession,
    *,
    source_version_id: UUID,
    normalized_parameters: Mapping[str, object],
    checksum: str,
    artifact_root: Path,
) -> DatasetVersion | None:
    candidates = (
        await session.scalars(
            select(DatasetVersion)
            .where(
                DatasetVersion.parent_version_id == source_version_id,
                DatasetVersion.operation_name == "preprocessing.clean",
                DatasetVersion.sha256 == checksum,
            )
            .order_by(DatasetVersion.version_index, DatasetVersion.created_at)
        )
    ).all()
    for candidate in candidates:
        if candidate.parameters.get("resolved_parameters") != normalized_parameters:
            continue
        if artifact_matches_sha256(
            artifact_root=artifact_root,
            relative_path=candidate.artifact_path,
            expected_sha256=candidate.sha256,
        ):
            return candidate
    return None


async def _next_version_index(session: AsyncSession, dataset_id: UUID) -> int:
    current = await session.scalar(
        select(func.max(DatasetVersion.version_index)).where(
            DatasetVersion.dataset_id == dataset_id
        )
    )
    return int(current or 0) + 1


def _resolve_parameters(payload: CleanRequest) -> CleaningParameters:
    interpolation_value = payload.interpolation_method or payload.interpolation
    interpolation = {
        "forward_fill": "ffill",
        "backward_fill": "bfill",
    }.get(interpolation_value, interpolation_value)
    outlier_value = payload.outlier_method or payload.anomaly_detector
    detector = {"zscore": "z_score"}.get(outlier_value, outlier_value)
    return CleaningParameters(
        resample_period_seconds=(
            payload.resample_period_s
            if payload.resample_period_s is not None
            else payload.target_sample_period_seconds
        ),
        interpolation=interpolation,  # type: ignore[arg-type]
        max_consecutive_missing=payload.max_consecutive_missing,
        duplicate_strategy=payload.duplicate_strategy,
        outlier_detector=detector,  # type: ignore[arg-type]
        outlier_strategy=payload.anomaly_strategy,
        hampel_window=payload.hampel_window,
        hampel_threshold=(
            payload.hampel_n_sigmas
            if payload.hampel_n_sigmas is not None
            else payload.hampel_threshold
        ),
        z_score_threshold=payload.z_score_threshold,
        smoothing=payload.smoothing,
        smoothing_window=payload.smoothing_window,
    )


def _clone_columns(
    source_columns: Sequence[DatasetColumn],
    *,
    dataset_id: UUID,
    version_id: UUID,
    nullable: dict[str, bool],
) -> list[DatasetColumn]:
    return [
        DatasetColumn(
            id=uuid4(),
            dataset_id=dataset_id,
            version_id=version_id,
            position=column.position,
            name=column.name,
            inferred_type=column.inferred_type,
            role=column.role,
            unit=column.unit,
            nullable=nullable.get(column.name, column.nullable),
        )
        for column in source_columns
    ]


def _version_parameters(
    payload: CleanRequest,
    parameters: CleaningParameters,
    result: CleaningResult,
    source_version_id: UUID,
) -> dict[str, object]:
    return {
        "algorithm": CleaningPipeline.name,
        "source_version_id": str(source_version_id),
        "request": payload.model_dump(mode="json", exclude_none=True),
        "resolved_parameters": _jsonable_parameters(parameters),
        "total_cleaned_points": result.total_changed_points,
        "change_summary": result.change_summary,
        "detected_outlier_counts": {
            column: len(indices) for column, indices in result.detected_outlier_indices.items()
        },
        "constant_value_segment_count": len(result.constant_value_segments),
        "constant_value_segments": result.constant_value_segments,
        "candidate_frozen_segment_count": len(result.candidate_frozen_segments),
        "candidate_frozen_segments": result.candidate_frozen_segments,
        "warnings": result.warnings,
        "csv_encoding": "utf-8",
        "csv_delimiter": ",",
    }


def _jsonable_parameters(parameters: CleaningParameters) -> dict[str, object]:
    return asdict(parameters)


def replay_cleaning_audit(
    *,
    dataset: Dataset,
    source_version: DatasetVersion,
    resolved_parameters: Mapping[str, object],
    artifact_root: Path,
) -> dict[str, object]:
    """Rebuild read-only audit counts for a legacy immutable Cleaning version.

    The function only reads the parent CSV and runs the deterministic pure pipeline. It
    never persists a version, profile, processing run, or artifact.
    """

    parameters = CleaningParameters(**dict(resolved_parameters))  # type: ignore[arg-type]
    parsed = load_version_csv(
        dataset=dataset,
        version=source_version,
        artifact_root=artifact_root,
    )
    result = CleaningPipeline().execute(
        CleaningContext(
            headers=parsed.headers,
            timestamp_column=parsed.timestamp_column,
            timestamps=parsed.timestamps,
            rows=parsed.rows,
            inferred_types=parsed.inferred_types,
        ),
        parameters,
    )
    return {
        "change_summary": result.change_summary,
        "constant_value_segment_count": len(result.constant_value_segments),
        "candidate_frozen_segment_count": len(result.candidate_frozen_segments),
    }


def _clean_data(
    *,
    dataset_id: UUID,
    source_version_id: UUID,
    derived_version_id: UUID | None,
    effective_version_id: UUID,
    created_new_version: bool,
    no_op: bool,
    converged: bool,
    reused_existing_version: bool,
    source_columns: Sequence[DatasetColumn],
    source_row_count: int,
    processing_run_id: UUID,
    parameters: CleaningParameters,
    result: CleaningResult,
) -> CleanData:
    series, downsample_factor = _series_projection(result)
    output_column = next(
        (column.name for column in source_columns if column.role == "output"),
        next(iter(result.cleaned_numeric)),
    )
    selected = next(item for item in series if item.column == output_column)
    return CleanData(
        source_version_id=source_version_id,
        effective_version_id=effective_version_id,
        derived_version_id=derived_version_id,
        created_new_version=created_new_version,
        no_op=no_op,
        converged=converged,
        reused_existing_version=reused_existing_version,
        task=completed_task(stage="preprocessing.clean", message="时间规整与数据清洗已完成。"),
        series=series,
        dataset_id=dataset_id,
        new_version_id=derived_version_id,
        primary_column=output_column,
        processing_run_id=processing_run_id,
        raw_series=selected.raw_series,
        cleaned_series=selected.cleaned_series,
        replaced_indices=selected.replaced_indices,
        total_cleaned_points=result.total_changed_points,
        warnings=result.warnings,
        recommended_downsample_factor=downsample_factor,
        summary={
            "effective_version_id": str(effective_version_id),
            "created_new_version": created_new_version,
            "no_op": no_op,
            "converged": converged,
            "reused_existing_version": reused_existing_version,
            "rows_before": source_row_count,
            "rows_after": len(result.timestamps),
            "columns_before": len(source_columns),
            "columns_after": len(source_columns),
            "changes": result.change_summary,
            "missing": {
                "method": _jsonable_parameters(parameters).get("interpolation"),
                "filled_cells": result.change_summary["missing_value_fills"],
            },
            "outliers": {
                "method": _jsonable_parameters(parameters).get("outlier_detector"),
                "detected": sum(len(indices) for indices in result.detected_outlier_indices.values()),
                "repaired": result.change_summary["outlier_replacements"],
            },
            "smoothing": {
                "method": _jsonable_parameters(parameters).get("smoothing"),
                "window": _jsonable_parameters(parameters).get("smoothing_window"),
                "changed_cells": result.change_summary["smoothing_changes"],
            },
            "constant_value_segments": {
                "audit_count": len(result.constant_value_segments),
                "candidate_abnormal_count": len(result.candidate_frozen_segments),
            },
        },
    )


def _series_projection(result: CleaningResult) -> tuple[list[CleanSeries], int]:
    total = len(result.timestamps)
    factor = max(1, ceil(total / MAX_RESPONSE_POINTS))
    indices = list(range(0, total, factor))
    if indices and indices[-1] != total - 1:
        indices.append(total - 1)

    def project_indices(source_indices: Sequence[int]) -> list[int]:
        changed = set(source_indices)
        return [
            projected_index
            for projected_index, source_index in enumerate(indices)
            if source_index in changed
        ]

    series: list[CleanSeries] = []
    for column, cleaned in result.cleaned_numeric.items():
        series.append(
            CleanSeries(
                column=column,
                timestamps=[result.timestamps[index] for index in indices],
                raw_series=[result.raw_numeric[column][index] for index in indices],
                cleaned_series=[cleaned[index] for index in indices],
                replaced_indices=project_indices(result.changed_indices[column]),
                interpolation_changed_indices=project_indices(
                    result.interpolation_changed_indices[column]
                ),
                outlier_replacement_indices=project_indices(
                    result.outlier_replacement_indices[column]
                ),
                smoothing_changed_indices=project_indices(
                    result.smoothing_changed_indices[column]
                ),
            )
        )
    return series, factor
