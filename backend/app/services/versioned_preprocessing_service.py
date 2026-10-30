"""Explicit, immutable data-changing preprocessing operations.

Analysis endpoints are intentionally elsewhere and read-only.  This module contains only
the confirmed apply operations that write a new CSV, DatasetVersion, Profile and
ProcessingRun as one transaction.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from algorithms.cleaning.quality import build_quality_profile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset import (
    Dataset,
    DatasetColumn,
    DatasetProfileRecord,
    DatasetVersion,
    ProcessingRun,
)
from app.models.operation_log import OperationLog
from app.schemas.preprocessing import (
    FeatureSelectionApplyRequest,
    LagCompensationRequest,
    VersionApplyData,
)
from app.services.contract_stubs import completed_task
from app.services.dataset_csv import ParsedCsv
from app.services.dataset_version_io import (
    DatasetVersionArtifactError,
    load_version_csv,
    remove_derived_artifact,
    write_derived_csv,
)


class VersionedPreprocessingError(Exception):
    def __init__(
        self, code: str, message: str, *, status_code: int = 400, details: dict[str, object] | None = None
    ) -> None:
        super().__init__(message)
        self.code, self.message, self.status_code = code, message, status_code
        self.details = details or {}


async def apply_lag_compensation(
    session: AsyncSession, *, payload: LagCompensationRequest, artifact_root: Path
) -> VersionApplyData:
    """Align inputs as ``u_aligned(t)=u_source(t-nk)`` while keeping ``y(t)`` fixed."""

    if not payload.user_confirmed:
        raise VersionedPreprocessingError("CONFIRMATION_REQUIRED", "时滞补偿必须经用户确认后才会创建新版本。")
    source, dataset, columns, parsed = await _source(session, payload.version_id, payload.dataset_id, artifact_root)
    inputs = {column.name for column in columns if column.role == "input"}
    invalid = sorted(set(payload.lag_map) - inputs)
    if invalid:
        raise VersionedPreprocessingError(
            "INVALID_LAG_COLUMNS", "lag_map 只能包含当前版本的输入变量。", details={"invalid": invalid}
        )
    missing = sorted(inputs - set(payload.lag_map))
    if missing:
        raise VersionedPreprocessingError(
            "INCOMPLETE_LAG_MAP",
            "lag_map 必须覆盖当前版本的全部输入变量。",
            details={"missing": missing},
        )
    if any(value < 0 for value in payload.lag_map.values()):
        raise VersionedPreprocessingError("INVALID_LAG", "当前 ARX nk 语义只支持非负时滞补偿。")
    trim = max(payload.lag_map.values(), default=0)
    if trim == 0:
        raise VersionedPreprocessingError("LAG_NOT_APPLIED", "所有确认时滞均为 0，无需创建补偿版本。")
    if len(parsed.rows) <= trim:
        raise VersionedPreprocessingError("INSUFFICIENT_ROWS", "边界裁剪后没有可保留的数据行。")

    values = {
        header: [row[header] for row in parsed.rows[trim:]]
        for header in parsed.headers
        if header != parsed.timestamp_column
    }
    for column, delay in payload.lag_map.items():
        values[column] = [row[column] for row in parsed.rows[trim - delay : len(parsed.rows) - delay]]
    summary = {
        "lag_map": dict(payload.lag_map),
        "alignment": "u_aligned(t)=u_source(t-nk); y(t) and timestamps remain on the output time axis",
        "rows_before": len(parsed.rows),
        "rows_after": len(parsed.rows) - trim,
        "removed_boundary_rows": trim,
        "effective_time_range": {
            "start": parsed.timestamps[trim].isoformat(),
            "end": parsed.timestamps[-1].isoformat(),
        },
        "recommendation_source": payload.recommendation_source,
        "evidence_summary": payload.evidence_summary,
    }
    return await _create_derived_version(
        session,
        dataset=dataset,
        source=source,
        source_columns=columns,
        headers=parsed.headers,
        timestamp_column=parsed.timestamp_column,
        timestamps=parsed.timestamps[trim:],
        values=values,
        artifact_root=artifact_root,
        operation="preprocessing.lag_compensation",
        label="时滞补偿",
        parameters=summary,
        summary=summary,
    )


async def apply_feature_selection(
    session: AsyncSession, *, payload: FeatureSelectionApplyRequest, artifact_root: Path
) -> VersionApplyData:
    """Drop only confirmed redundant input columns; timestamps and target are protected."""

    if not payload.user_confirmed:
        raise VersionedPreprocessingError("CONFIRMATION_REQUIRED", "变量剔除必须经用户确认后才会创建新版本。")
    source, dataset, columns, parsed = await _source(session, payload.version_id, payload.dataset_id, artifact_root)
    by_name = {column.name: column for column in columns}
    drop = set(payload.drop_columns)
    unknown = sorted(drop - set(by_name))
    if unknown:
        raise VersionedPreprocessingError("UNKNOWN_COLUMNS", "待删除列不存在于源版本。", details={"unknown": unknown})
    protected = sorted(
        column.name for column in columns if column.name in drop and column.role in {"timestamp", "output"}
    )
    if protected:
        raise VersionedPreprocessingError(
            "PROTECTED_COLUMN", "时间列和目标列不能被变量筛选删除。", details={"columns": protected}
        )
    remaining_inputs = [column.name for column in columns if column.role == "input" and column.name not in drop]
    if not remaining_inputs:
        raise VersionedPreprocessingError("NO_INPUT_COLUMNS", "变量筛选后至少必须保留一个输入变量。")
    headers = [header for header in parsed.headers if header not in drop]
    values = {
        header: [row[header] for row in parsed.rows]
        for header in headers
        if header != parsed.timestamp_column
    }
    summary = {
        "dropped_columns": sorted(drop),
        "kept_input_columns": remaining_inputs,
        "rows_before": len(parsed.rows),
        "rows_after": len(parsed.rows),
        "columns_before": len(parsed.headers),
        "columns_after": len(headers),
        "recommendation_source": payload.recommendation_source,
        "evidence": payload.evidence,
        "user_confirmed": True,
    }
    return await _create_derived_version(
        session,
        dataset=dataset,
        source=source,
        source_columns=[column for column in columns if column.name not in drop],
        headers=headers,
        timestamp_column=parsed.timestamp_column,
        timestamps=parsed.timestamps,
        values=values,
        artifact_root=artifact_root,
        operation="preprocessing.feature_selection",
        label="冗余变量剔除",
        parameters=summary,
        summary=summary,
    )


async def _source(
    session: AsyncSession, version_id: UUID, dataset_id: UUID | None, artifact_root: Path
) -> tuple[DatasetVersion, Dataset, list[DatasetColumn], ParsedCsv]:
    source = await session.get(DatasetVersion, version_id)
    if source is None:
        raise VersionedPreprocessingError("DATASET_VERSION_NOT_FOUND", "源数据版本不存在。", status_code=404)
    dataset = await session.get(Dataset, source.dataset_id)
    if dataset is None:
        raise VersionedPreprocessingError("DATASET_NOT_FOUND", "源数据集不存在。", status_code=404)
    if dataset_id is not None and dataset_id != dataset.id:
        raise VersionedPreprocessingError("DATASET_VERSION_MISMATCH", "数据集与源版本不匹配。")
    columns = list(
        (await session.scalars(select(DatasetColumn).where(DatasetColumn.version_id == source.id).order_by(DatasetColumn.position))).all()
    )
    try:
        parsed = load_version_csv(dataset=dataset, version=source, artifact_root=artifact_root)
    except DatasetVersionArtifactError as error:
        raise VersionedPreprocessingError(error.code, error.message, status_code=404, details=error.details) from error
    return source, dataset, columns, parsed


async def _create_derived_version(
    session: AsyncSession,
    *,
    dataset: Dataset,
    source: DatasetVersion,
    source_columns: list[DatasetColumn],
    headers: list[str],
    timestamp_column: str,
    timestamps: list[datetime],
    values: dict[str, list[str]],
    artifact_root: Path,
    operation: str,
    label: str,
    parameters: dict[str, object],
    summary: dict[str, object],
) -> VersionApplyData:
    version_id, run_id = uuid4(), uuid4()
    artifact_path: str | None = None
    now = datetime.now(UTC)
    try:
        artifact_path, checksum = write_derived_csv(
            artifact_root=artifact_root, dataset_id=dataset.id, version_id=version_id,
            headers=headers, timestamp_column=timestamp_column, timestamps=timestamps, values=values,
        )
        index = int(
            (
                await session.scalar(
                    select(func.max(DatasetVersion.version_index)).where(
                        DatasetVersion.dataset_id == dataset.id
                    )
                )
            )
            or 0
        ) + 1
        parameters = {**parameters, "source_version_id": str(source.id), "csv_encoding": "utf-8", "csv_delimiter": ","}
        version = DatasetVersion(
            id=version_id, dataset_id=dataset.id, parent_version_id=source.id, version_index=index,
            name=f"V{index} · {label}", operation_name=operation, parameters=parameters,
            artifact_path=artifact_path, sha256=checksum, row_count=len(timestamps), column_count=len(headers),
            time_range_start=min(timestamps), time_range_end=max(timestamps), created_at=now,
        )
        # PostgreSQL enforces the DatasetColumn.version_id foreign key immediately.
        # Flush the immutable version before staging its dependent columns and profile.
        session.add(version)
        await session.flush()
        parsed = load_version_csv(dataset=dataset, version=version, artifact_root=artifact_root)
        profile_payload = build_quality_profile(
            dataset_id=str(dataset.id), version_id=str(version_id), headers=parsed.headers, rows=parsed.rows,
            inferred_types=parsed.inferred_types, timestamps=parsed.timestamps,
        ).payload
        copied_columns = [
            DatasetColumn(
                id=uuid4(), dataset_id=dataset.id, version_id=version_id, position=position,
                name=column.name, inferred_type=parsed.inferred_types[column.name], role=column.role,
                unit=column.unit, nullable=parsed.nullable[column.name],
            ) for position, column in enumerate(source_columns)
        ]
        run = ProcessingRun(
            id=run_id, dataset_id=dataset.id, source_version_id=source.id, run_type=operation,
            status="succeeded", parameters=parameters, result={"result_version_id": str(version_id), **summary},
            created_at=now, finished_at=now,
        )
        profile = DatasetProfileRecord(
            id=uuid4(), dataset_id=dataset.id, version_id=version_id,
            quality_score=float(profile_payload["quality_score"]), profile=profile_payload,
            created_at=now, updated_at=now,
        )
        session.add_all([*copied_columns, profile, run])
        dataset.active_version_id, dataset.updated_at = version_id, now
        session.add(OperationLog(
            id=uuid4(), event_type=f"{operation}.completed", subject_id=str(dataset.id),
            payload_json=json.dumps({"source_version_id": str(source.id), "result_version_id": str(version_id), "run_id": str(run_id), "summary": summary, "executed_at": now.isoformat()}, ensure_ascii=False, sort_keys=True), created_at=now,
        ))
        await session.commit()
    except Exception:
        await session.rollback()
        if artifact_path:
            remove_derived_artifact(artifact_root=artifact_root, relative_path=artifact_path)
        raise
    return VersionApplyData(
        source_version_id=source.id, result_version_id=version_id, dataset_id=dataset.id,
        processing_run_id=run_id, operation=operation, summary=summary,
        task=completed_task(stage=operation, message=f"{label}已创建不可变数据版本。"),
    )
