"""Database-backed dataset asset management and quality-profile orchestration."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from algorithms.cleaning.quality import build_quality_profile, enrich_freeze_diagnostics
from fastapi import UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset import (
    Dataset as DatasetModel,
)
from app.models.dataset import (
    DatasetColumn as DatasetColumnModel,
)
from app.models.dataset import (
    DatasetProfileRecord,
    ProcessingRun,
)
from app.models.dataset import (
    DatasetVersion as DatasetVersionModel,
)
from app.schemas.common import PageInfo
from app.schemas.datasets import (
    DatasetColumn,
    DatasetColumnConfig,
    DatasetConfigData,
    DatasetConfigRequest,
    DatasetDetail,
    DatasetListData,
    DatasetProfile,
    DatasetSummary,
    DatasetVersionPreviewData,
    DatasetVersionPreviewPage,
    DatasetVersionsData,
    VersionEdge,
    VersionNode,
)
from app.schemas.simulation import SimulationGenerateData, SimulationGenerateRequest
from app.services.cleaning_service import replay_cleaning_audit
from app.services.dataset_csv import (
    DatasetCsvError,
    ParsedCsv,
    discard_staged_upload,
    load_parsed_csv,
    move_to_immutable_storage,
    parse_csv,
    stage_upload,
)
from app.services.dataset_version_io import (
    DatasetVersionArtifactError,
    load_version_csv,
    load_version_csv_page,
)


class DatasetDomainError(Exception):
    """Domain error that maps directly to the project-standard API envelope."""

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


@dataclass(frozen=True)
class UploadedDataset:
    summary: DatasetSummary
    deduplicated: bool


async def upload_csv_dataset(
    session: AsyncSession,
    *,
    upload: UploadFile,
    display_name: str | None,
    artifact_root: Path,
) -> UploadedDataset:
    """Persist a validated raw upload and its first immutable V0/profile records."""

    try:
        staged = await stage_upload(upload, artifact_root=artifact_root)
        parsed = parse_csv(staged)
    except DatasetCsvError as error:
        raise DatasetDomainError(error.code, error.message, details=error.details) from error

    try:
        existing = await session.scalar(
            select(DatasetModel).where(DatasetModel.raw_sha256 == staged.sha256)
        )
        if existing is not None:
            discard_staged_upload(staged)
            return UploadedDataset(
                summary=await _dataset_summary(session, existing), deduplicated=True
            )

        dataset_id = uuid4()
        raw_path = move_to_immutable_storage(
            staged,
            artifact_root=artifact_root,
            dataset_id=str(dataset_id),
        )
        created_at = datetime.now(UTC)
        dataset = DatasetModel(
            id=dataset_id,
            name=_display_name(display_name, staged.filename),
            source="upload",
            status="ready",
            raw_sha256=staged.sha256,
            raw_path=raw_path,
            byte_size=staged.byte_size,
            encoding=staged.encoding,
            delimiter=staged.delimiter,
            created_at=created_at,
            updated_at=created_at,
        )
        version = DatasetVersionModel(
            id=uuid4(),
            dataset_id=dataset.id,
            version_index=0,
            name="V0 · 原始上传",
            operation_name="raw_upload",
            parameters={
                "encoding": staged.encoding,
                "delimiter": _delimiter_label(staged.delimiter),
                "original_filename": staged.filename,
            },
            artifact_path=raw_path,
            sha256=staged.sha256,
            row_count=len(parsed.rows),
            column_count=len(parsed.headers),
            time_range_start=min(parsed.timestamps),
            time_range_end=max(parsed.timestamps),
            created_at=created_at,
        )
        dataset.active_version_id = version.id
        columns = [
            DatasetColumnModel(
                id=uuid4(),
                dataset_id=dataset.id,
                version_id=version.id,
                position=position,
                name=header,
                inferred_type=parsed.inferred_types[header],
                role="timestamp" if header == parsed.timestamp_column else "ignore",
                nullable=parsed.nullable[header],
            )
            for position, header in enumerate(parsed.headers)
        ]
        profile = _build_profile(dataset.id, version.id, parsed)
        profile_record = DatasetProfileRecord(
            id=uuid4(),
            dataset_id=dataset.id,
            version_id=version.id,
            quality_score=float(profile["quality_score"]),
            profile=profile,
            created_at=created_at,
            updated_at=created_at,
        )
        # The ORM models intentionally avoid mutable relationships. Flush V0
        # before dependent metadata so PostgreSQL can enforce every FK.
        session.add_all([dataset, version])
        await session.flush()
        session.add_all([*columns, profile_record])
        await session.commit()
        await session.refresh(dataset)
        return UploadedDataset(summary=await _dataset_summary(session, dataset), deduplicated=False)
    except IntegrityError:
        # Two uploads of byte-identical content raced the "already exists" check above:
        # this request's own INSERT is the one that loses, and hits the raw_sha256 unique
        # constraint at commit rather than ever seeing `existing is not None`. Recover the
        # same way that check would have — return the winner's summary as a normal
        # duplicate — instead of surfacing this as an unmapped 500 to the client.
        await session.rollback()
        if "raw_path" in locals():
            (artifact_root / raw_path).unlink(missing_ok=True)
        winner = await session.scalar(
            select(DatasetModel).where(DatasetModel.raw_sha256 == staged.sha256)
        )
        if winner is None:
            # Unreachable in principle (the constraint only fires because a matching row
            # exists) — if it ever happens, surface the original failure rather than
            # fabricate a summary.
            raise
        return UploadedDataset(summary=await _dataset_summary(session, winner), deduplicated=True)
    except Exception:
        await session.rollback()
        # A transaction failure after the move must not leave a mutable orphan in uploads/.
        if "raw_path" in locals():
            (artifact_root / raw_path).unlink(missing_ok=True)
        raise
    finally:
        # No-op after a successful move; removes a temporary file for early failures.
        if "staged" in locals():
            discard_staged_upload(staged)


async def register_simulation_dataset(
    session: AsyncSession,
    *,
    generated: SimulationGenerateData,
    request: SimulationGenerateRequest,
    artifact_root: Path,
) -> SimulationGenerateData:
    """Register a generated CSV through the same Dataset/V0/Profile lifecycle as uploads."""

    csv_path = artifact_root / generated.file_path
    try:
        parsed = load_parsed_csv(
            artifact_root=artifact_root,
            relative_path=generated.file_path,
            encoding="utf-8",
            delimiter=",",
        )
    except DatasetCsvError as error:
        raise DatasetDomainError(error.code, error.message, details=error.details) from error

    digest = _file_sha256(csv_path)
    existing = await session.scalar(select(DatasetModel).where(DatasetModel.raw_sha256 == digest))
    if existing is not None:
        version = await _active_version_or_error(session, existing)
        parameters = dict(version.parameters or {})
        return generated.model_copy(
            update={
                "dataset_id": existing.id,
                "dataset_name": existing.name,
                "version_id": version.id,
                "file_path": existing.raw_path,
                "ground_truth_path": str(parameters.get("ground_truth_path") or ""),
                "manifest_path": str(parameters.get("manifest_path") or ""),
                "download_url": f"/api/v1/datasets/{existing.id}/download",
            }
        )
    created_at = datetime.now(UTC)
    dataset = DatasetModel(
        id=generated.dataset_id,
        name=generated.dataset_name,
        source="simulation",
        status="ready",
        raw_sha256=digest,
        raw_path=generated.file_path,
        byte_size=csv_path.stat().st_size,
        encoding="utf-8",
        delimiter=",",
        created_at=created_at,
        updated_at=created_at,
    )
    version = DatasetVersionModel(
        id=generated.version_id,
        dataset_id=dataset.id,
        version_index=0,
        name="V0 · 仿真原始数据",
        operation_name="simulation_generate",
        parameters={
            "csv_encoding": "utf-8",
            "csv_delimiter": ",",
            "scenario": generated.scenario,
            "system_type": "MISO ARX",
            "simulation_request": request.model_dump(mode="json"),
            "ground_truth_path": generated.ground_truth_path,
            "manifest_path": generated.manifest_path,
            "ground_truth_summary": {
                "true_na": generated.ground_truth.true_na,
                "true_delays_by_input": generated.ground_truth.true_delays_by_input,
                "seed": generated.ground_truth.seed,
            },
            "resolved_scenario_parameters": _resolved_scenario_parameters(
                generated.ground_truth.model_dump(mode="json"), len(parsed.rows)
            ),
        },
        artifact_path=generated.file_path,
        sha256=digest,
        row_count=len(parsed.rows),
        column_count=len(parsed.headers),
        time_range_start=min(parsed.timestamps),
        time_range_end=max(parsed.timestamps),
        created_at=created_at,
    )
    dataset.active_version_id = version.id
    columns = [
        DatasetColumnModel(
            id=uuid4(),
            dataset_id=dataset.id,
            version_id=version.id,
            position=position,
            name=header,
            inferred_type=parsed.inferred_types[header],
            role=(
                "timestamp"
                if header == parsed.timestamp_column
                else "input"
                if header.startswith("u")
                else "output"
                if header == "y"
                else "ignore"
            ),
            nullable=parsed.nullable[header],
        )
        for position, header in enumerate(parsed.headers)
    ]
    profile = _build_profile(dataset.id, version.id, parsed)
    profile_record = DatasetProfileRecord(
        id=uuid4(),
        dataset_id=dataset.id,
        version_id=version.id,
        quality_score=float(profile["quality_score"]),
        profile=profile,
        created_at=created_at,
        updated_at=created_at,
    )
    try:
        session.add_all([dataset, version])
        await session.flush()
        session.add_all([*columns, profile_record])
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return generated.model_copy(
        update={"download_url": f"/api/v1/datasets/{dataset.id}/download"}
    )


async def list_dataset_summaries(
    session: AsyncSession, *, page: int, page_size: int
) -> DatasetListData:
    total = int(await session.scalar(select(func.count()).select_from(DatasetModel)) or 0)
    records = list(
        (
            await session.scalars(
                select(DatasetModel)
                .order_by(DatasetModel.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return DatasetListData(
        items=await _dataset_summaries_batch(session, records),
        page=PageInfo(page=page, page_size=page_size, total=total),
    )


async def get_dataset_detail(
    session: AsyncSession, *, dataset_id: UUID, artifact_root: Path
) -> DatasetDetail:
    dataset = await _dataset_or_404(session, dataset_id)
    version = await _active_version_or_error(session, dataset)
    columns = await _version_columns(session, version.id)
    profile = await _profile_or_error(session, dataset.id, version.id)
    parsed = _load_version_csv(dataset, version, artifact_root)
    missing_counts = cast(dict[str, int], profile.profile.get("column_missing_counts", {}))
    simulation = (
        await _simulation_dataset_detail(session, dataset=dataset, artifact_root=artifact_root)
        if dataset.source == "simulation"
        else None
    )
    return DatasetDetail(
        **(await _dataset_summary(session, dataset, columns=columns)).model_dump(),
        columns=[
            DatasetColumn(
                name=column.name,
                inferred_type=column.inferred_type,
                role=column.role,
                unit=column.unit,
                nullable=column.nullable,
                data_type=column.inferred_type,
                missing_count=int(missing_counts.get(column.name, 0)),
            )
            for column in columns
        ],
        time_range_start=version.time_range_start,
        time_range_end=version.time_range_end,
        preview={
            "columns": parsed.headers,
            "rows": parsed.preview_rows,
            "truncated": len(parsed.rows) > len(parsed.preview_rows),
            "recommended_downsample_factor": max(1, int((len(parsed.rows) + 9_999) / 10_000)),
        },
        simulation=simulation,
    )


async def get_dataset_version_preview(
    session: AsyncSession,
    *,
    dataset_id: UUID,
    version_id: UUID,
    page: int,
    page_size: int,
    artifact_root: Path,
) -> DatasetVersionPreviewData:
    dataset = await _dataset_or_404(session, dataset_id)
    version = await session.get(DatasetVersionModel, version_id)
    if version is None or version.dataset_id != dataset.id:
        raise DatasetDomainError(
            "DATASET_VERSION_NOT_FOUND",
            "请求的数据版本不存在。",
            status_code=404,
            details={"dataset_id": str(dataset_id), "version_id": str(version_id)},
        )
    columns = await _version_columns(session, version.id)
    inferred_types = {column.name: column.inferred_type for column in columns}
    try:
        csv_page = load_version_csv_page(
            dataset=dataset,
            version=version,
            artifact_root=artifact_root,
            inferred_types=inferred_types,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
    except DatasetVersionArtifactError as error:
        raise DatasetDomainError(
            error.code, error.message, status_code=404, details=error.details
        ) from error
    total = version.row_count
    return DatasetVersionPreviewData(
        dataset_id=dataset.id,
        version_id=version.id,
        columns=csv_page.headers,
        rows=csv_page.rows,
        page=DatasetVersionPreviewPage(
            page=page,
            page_size=page_size,
            total=total,
            total_pages=(total + page_size - 1) // page_size,
        ),
    )


async def get_dataset_download(
    session: AsyncSession, *, dataset_id: UUID, artifact_root: Path, version_id: UUID | None = None
) -> tuple[Path, str]:
    """Return the active or explicitly requested immutable version artifact."""

    dataset = await _dataset_or_404(session, dataset_id)
    version = await _active_version_or_error(session, dataset)
    if version_id is not None:
        requested = await session.get(DatasetVersionModel, version_id)
        if requested is None or requested.dataset_id != dataset.id:
            raise DatasetDomainError("DATASET_VERSION_NOT_FOUND", "请求下载的数据版本不存在。", status_code=404)
        version = requested
    path = artifact_root / version.artifact_path
    if not path.is_file():
        raise DatasetDomainError(
            "DATASET_ARTIFACT_MISSING",
            "数据集 CSV 产物不存在。",
            status_code=404,
            details={"artifact_path": version.artifact_path},
        )
    suffix = Path(dataset.name).suffix or ".csv"
    filename = f"{Path(dataset.name).stem}-v{version.version_index}{suffix}"
    return path, filename


async def delete_dataset_asset(session: AsyncSession, *, dataset_id: UUID) -> None:
    """Cascade-delete database metadata while deliberately retaining immutable raw evidence."""

    await _dataset_or_404(session, dataset_id)
    version_ids = select(DatasetVersionModel.id).where(DatasetVersionModel.dataset_id == dataset_id)
    await session.execute(
        delete(DatasetProfileRecord).where(DatasetProfileRecord.dataset_id == dataset_id)
    )
    await session.execute(
        delete(DatasetColumnModel).where(DatasetColumnModel.dataset_id == dataset_id)
    )
    await session.execute(delete(ProcessingRun).where(ProcessingRun.dataset_id == dataset_id))
    await session.execute(
        delete(DatasetVersionModel).where(DatasetVersionModel.id.in_(version_ids))
    )
    await session.execute(delete(DatasetModel).where(DatasetModel.id == dataset_id))
    await session.commit()


async def get_dataset_profile(
    session: AsyncSession, *, dataset_id: UUID, version_id: UUID | None = None
) -> DatasetProfile:
    dataset = await _dataset_or_404(session, dataset_id)
    version = await _active_version_or_error(session, dataset)
    if version_id is not None:
        requested = await session.get(DatasetVersionModel, version_id)
        if requested is None or requested.dataset_id != dataset.id:
            raise DatasetDomainError("DATASET_VERSION_NOT_FOUND", "请求的数据版本不存在。", status_code=404)
        version = requested
    record = await _profile_or_error(session, dataset.id, version.id)
    return _profile_schema(record.profile)


async def get_dataset_versions(
    session: AsyncSession, *, dataset_id: UUID, artifact_root: Path | None = None
) -> DatasetVersionsData:
    dataset = await _dataset_or_404(session, dataset_id)
    versions = list(
        (
            await session.scalars(
                select(DatasetVersionModel)
                .where(DatasetVersionModel.dataset_id == dataset.id)
                .order_by(DatasetVersionModel.version_index, DatasetVersionModel.created_at)
            )
        ).all()
    )
    nodes: list[VersionNode] = []
    for version in versions:
        columns = await _version_columns(session, version.id)
        nodes.append(VersionNode(
            id=version.id,
            name=version.name,
            tool=version.operation_name,
            created_at=version.created_at,
            parent_version_id=version.parent_version_id,
            parameters=version.parameters,
            row_count=version.row_count,
            column_count=version.column_count,
            artifact_path=version.artifact_path,
            processing_run_id=await _result_run_id(session, version.id),
            audit_summary=await _version_audit_summary(
                session,
                dataset=dataset,
                version=version,
                artifact_root=artifact_root,
            ),
            provenance=_version_provenance(version, artifact_root=artifact_root),
            time_column=next(
                (column.name for column in columns if column.role == "timestamp"), None
            ),
            input_columns=[column.name for column in columns if column.role == "input"],
            output_column=next(
                (column.name for column in columns if column.role == "output"), None
            ),
        ))
    edges = [
        VersionEdge(
            source=version.parent_version_id, target=version.id, operation=version.operation_name
        )
        for version in versions
        if version.parent_version_id is not None
    ]
    return DatasetVersionsData(
        dataset_id=dataset.id,
        active_version_id=dataset.active_version_id,
        nodes=nodes,
        edges=edges,
    )


async def _version_audit_summary(
    session: AsyncSession,
    *,
    dataset: DatasetModel,
    version: DatasetVersionModel,
    artifact_root: Path | None,
) -> dict[str, Any]:
    parameters = version.parameters if isinstance(version.parameters, dict) else {}
    profile_record = await session.scalar(
        select(DatasetProfileRecord).where(DatasetProfileRecord.version_id == version.id)
    )
    profile_payload = (
        enrich_freeze_diagnostics(profile_record.profile)
        if profile_record is not None and isinstance(profile_record.profile, dict)
        else {}
    )
    candidates = profile_payload.get("candidate_frozen_segments")
    candidate_count = len(candidates) if isinstance(candidates, list) else 0
    freeze: dict[str, Any] = {
        "candidate_frozen_segment_count": candidate_count,
        "candidate_frozen_segments": candidates if isinstance(candidates, list) else [],
    }
    if "constant_value_segment_count" in parameters:
        freeze["constant_value_segment_count"] = parameters["constant_value_segment_count"]
    elif "frozen_segment_count" in parameters:
        freeze["historical_constant_value_segment_count"] = parameters["frozen_segment_count"]

    processing = parameters.get("change_summary")
    if not isinstance(processing, dict) and version.operation_name == "preprocessing.clean":
        processing = await _replay_legacy_cleaning_summary(
            session,
            dataset=dataset,
            version=version,
            artifact_root=artifact_root,
        )
    if not isinstance(processing, dict):
        processing = {}
    return {
        "freeze": freeze,
        "processing": processing,
        "warnings": _display_warnings(parameters, freeze),
    }


def _display_warnings(
    parameters: Mapping[str, Any], freeze: Mapping[str, Any]
) -> list[str]:
    raw = parameters.get("warnings")
    warnings = [item for item in raw if isinstance(item, str)] if isinstance(raw, list) else []
    historical = freeze.get("historical_constant_value_segment_count")
    if not isinstance(historical, int):
        return warnings
    warnings = [warning for warning in warnings if "冻结段" not in warning]
    candidates = freeze.get("candidate_frozen_segment_count")
    warnings.append(
        f"历史版本记录了 {historical} 个恒值区段审计项；"
        f"按当前统一口径识别出 {candidates if isinstance(candidates, int) else 0} 个候选异常冻结段。"
    )
    return warnings


async def _replay_legacy_cleaning_summary(
    session: AsyncSession,
    *,
    dataset: DatasetModel,
    version: DatasetVersionModel,
    artifact_root: Path | None,
) -> dict[str, Any]:
    parameters = version.parameters if isinstance(version.parameters, dict) else {}
    resolved = parameters.get("resolved_parameters")
    source_id = version.parent_version_id or parameters.get("source_version_id")
    if artifact_root is None or not isinstance(resolved, Mapping) or source_id is None:
        return _legacy_total_only(parameters)
    try:
        source_uuid = source_id if isinstance(source_id, UUID) else UUID(str(source_id))
        source = await session.get(DatasetVersionModel, source_uuid)
        if source is None or source.dataset_id != dataset.id:
            return _legacy_total_only(parameters)
        replayed = replay_cleaning_audit(
            dataset=dataset,
            source_version=source,
            resolved_parameters=resolved,
            artifact_root=artifact_root,
        )
        summary = replayed.get("change_summary")
        return dict(summary) if isinstance(summary, dict) else _legacy_total_only(parameters)
    except (TypeError, ValueError, DatasetVersionArtifactError):
        return _legacy_total_only(parameters)


def _legacy_total_only(parameters: Mapping[str, Any]) -> dict[str, Any]:
    total = parameters.get("total_cleaned_points")
    return {
        "count_unit": "cell",
        "unique_changed_cells": total if isinstance(total, int) else None,
        "breakdown_status": "not_recorded",
    }


def _version_provenance(
    version: DatasetVersionModel, *, artifact_root: Path | None
) -> dict[str, Any]:
    parameters = version.parameters if isinstance(version.parameters, dict) else {}
    if version.operation_name != "simulation_generate":
        return {}
    user_request = parameters.get("simulation_request")
    stored = parameters.get("resolved_scenario_parameters")
    ground_truth = _read_json_artifact(artifact_root, parameters.get("ground_truth_path"))
    resolved = dict(stored) if isinstance(stored, dict) else {}
    if isinstance(ground_truth, dict):
        artifact_values = _resolved_scenario_parameters(ground_truth, version.row_count)
        resolved = {**artifact_values, **resolved}
        evidence_source = (
            "ground_truth_and_stored_parameters"
            if isinstance(stored, dict)
            else "ground_truth"
        )
    elif isinstance(stored, dict):
        evidence_source = "stored_resolved_scenario_parameters"
    else:
        evidence_source = "not_recorded"
    if "system_type" in parameters:
        resolved.setdefault("system_type", parameters["system_type"])
    if "scenario" in parameters:
        resolved.setdefault("scenario", parameters["scenario"])
    return {
        "user_request": user_request if isinstance(user_request, dict) else {},
        "resolved_scenario_parameters": resolved,
        "evidence_source": evidence_source,
    }


async def _simulation_dataset_detail(
    session: AsyncSession,
    *,
    dataset: DatasetModel,
    artifact_root: Path,
) -> dict[str, Any] | None:
    """Project the immutable simulation root without guessing from a later version."""

    root = await session.scalar(
        select(DatasetVersionModel)
        .where(
            DatasetVersionModel.dataset_id == dataset.id,
            DatasetVersionModel.parent_version_id.is_(None),
            DatasetVersionModel.operation_name == "simulation_generate",
        )
        .order_by(DatasetVersionModel.created_at)
        .limit(1)
    )
    if root is None:
        return None
    columns = await _version_columns(session, root.id)
    provenance = _version_provenance(root, artifact_root=artifact_root)
    resolved = provenance.get("resolved_scenario_parameters")
    resolved_record = resolved if isinstance(resolved, dict) else {}
    return {
        "root_version_id": str(root.id),
        "original_row_count": root.row_count,
        "physical_columns": [
            column.name for column in columns if column.role != "timestamp"
        ],
        "time_column": next(
            (column.name for column in columns if column.role == "timestamp"), None
        ),
        "scenario": resolved_record.get("scenario"),
        "system_type": resolved_record.get("system_type"),
        "true_na": resolved_record.get("true_na"),
        "true_nb": resolved_record.get("true_nb"),
        "true_delays": resolved_record.get("true_delays"),
        "true_delays_by_input": resolved_record.get("true_delays_by_input"),
        "noise_level": resolved_record.get("noise_level"),
        "provenance": provenance,
    }


def _read_json_artifact(artifact_root: Path | None, relative_path: object) -> dict[str, Any] | None:
    if artifact_root is None or not isinstance(relative_path, str) or not relative_path:
        return None
    root = artifact_root.resolve()
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    try:
        value = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _resolved_scenario_parameters(
    ground_truth: Mapping[str, Any], row_count: int
) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    direct_keys = (
        "system_type",
        "true_na",
        "true_nb",
        "true_delays",
        "true_delays_by_input",
        "true_parameters",
        "ar_coefficients",
        "input_coefficients",
        "dynamic_segments",
        "freeze_segments",
        "drift_segments",
        "redundant_variables",
        "variable_dependencies",
        "noise_level",
        "seed",
    )
    for key in direct_keys:
        if key in ground_truth:
            resolved[key] = ground_truth[key]
    if "anomaly_indices" in ground_truth:
        anomaly_counts = _index_counts(ground_truth["anomaly_indices"])
        resolved["anomaly_count_by_column"] = anomaly_counts
        resolved["anomaly_rate_by_column"] = _rates(anomaly_counts, row_count)
    if "missing_indices" in ground_truth:
        missing_counts = _index_counts(ground_truth["missing_indices"])
        resolved["missing_count_by_column"] = missing_counts
        resolved["missing_rate_by_column"] = _rates(missing_counts, row_count)
    if "irregular_timestamp_indices" in ground_truth:
        resolved["irregular_timestamp_count"] = _sequence_length(
            ground_truth["irregular_timestamp_indices"]
        )
    if "duplicate_timestamp_indices" in ground_truth:
        resolved["duplicate_timestamp_count"] = _sequence_length(
            ground_truth["duplicate_timestamp_indices"]
        )
    return resolved


def _index_counts(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(column): _sequence_length(indices)
        for column, indices in value.items()
    }


def _sequence_length(value: object) -> int:
    return len(value) if isinstance(value, Sequence) and not isinstance(value, str | bytes) else 0


def _rates(counts: Mapping[str, int], row_count: int) -> dict[str, float]:
    if row_count <= 0:
        return {column: 0.0 for column in counts}
    return {column: round(count / row_count, 8) for column, count in counts.items()}


async def _result_run_id(session: AsyncSession, version_id: UUID) -> UUID | None:
    runs = list(
        (
            await session.scalars(
                select(ProcessingRun)
                .order_by(ProcessingRun.created_at.desc())
            )
        ).all()
    )
    for run in runs:
        value = run.result.get("result_version_id") if isinstance(run.result, dict) else None
        if value == str(version_id):
            return run.id
    return None


async def configure_dataset_columns(
    session: AsyncSession,
    *,
    dataset_id: UUID,
    payload: DatasetConfigRequest,
    artifact_root: Path,
) -> DatasetConfigData:
    dataset = await _dataset_or_404(session, dataset_id)
    version = await _active_version_or_error(session, dataset)
    columns = await _version_columns(session, version.id)
    roles, units = _resolve_column_configuration(columns, payload)
    timestamp_columns = [name for name, role in roles.items() if role == "timestamp"]
    output_columns = [name for name, role in roles.items() if role == "output"]
    input_columns = [name for name, role in roles.items() if role == "input"]
    if len(timestamp_columns) != 1:
        raise DatasetDomainError("INVALID_DATASET_SCHEMA", "必须配置且只能配置一个时间戳列。")
    if len(output_columns) != 1:
        raise DatasetDomainError("INVALID_DATASET_SCHEMA", "MISO 配置必须且只能配置一个输出列。")
    if not input_columns:
        raise DatasetDomainError("INVALID_DATASET_SCHEMA", "至少需要配置一个输入列。")
    by_name = {column.name: column for column in columns}
    timestamp = timestamp_columns[0]
    if by_name[timestamp].inferred_type != "datetime":
        raise DatasetDomainError(
            "TIMESTAMP_PARSE_FAILED", "指定的时间列不是可解析的 datetime 字段。"
        )
    for column in columns:
        column.role = roles[column.name]
        if column.name in units:
            column.unit = units[column.name]

    parsed = _load_version_csv(dataset, version, artifact_root)
    profile_payload = _build_profile(dataset.id, version.id, parsed)
    profile_record = await _profile_or_error(session, dataset.id, version.id)
    profile_record.profile = profile_payload
    profile_record.quality_score = float(profile_payload["quality_score"])
    profile_record.updated_at = datetime.now(UTC)
    dataset.updated_at = datetime.now(UTC)
    await session.commit()
    return DatasetConfigData(
        dataset=await get_dataset_detail(
            session, dataset_id=dataset.id, artifact_root=artifact_root
        ),
        profile=_profile_schema(profile_payload),
    )


async def _dataset_summary(
    session: AsyncSession,
    dataset: DatasetModel,
    *,
    columns: Sequence[DatasetColumnModel] | None = None,
) -> DatasetSummary:
    active_version = await _active_version_or_error(session, dataset)
    resolved_columns = (
        list(columns) if columns is not None else await _version_columns(session, active_version.id)
    )
    return _build_dataset_summary(dataset, active_version, resolved_columns)


def _build_dataset_summary(
    dataset: DatasetModel,
    active_version: DatasetVersionModel,
    columns: Sequence[DatasetColumnModel],
) -> DatasetSummary:
    """Pure field mapping, shared by the single-record and batch-list code paths so the
    two can never drift apart on which columns feed which summary field."""

    time_column = next((column.name for column in columns if column.role == "timestamp"), None)
    input_columns = [column.name for column in columns if column.role == "input"]
    output_column = next((column.name for column in columns if column.role == "output"), None)
    return DatasetSummary(
        id=dataset.id,
        name=dataset.name,
        source=dataset.source,
        status=dataset.status,
        row_count=active_version.row_count,
        column_count=active_version.column_count,
        latest_version_id=active_version.id,
        created_at=dataset.created_at,
        updated_at=dataset.updated_at,
        version_id=active_version.id,
        file_size_bytes=dataset.byte_size,
        col_count=active_version.column_count,
        time_column=time_column,
        input_columns=input_columns,
        output_column=output_column,
    )


async def _dataset_summaries_batch(
    session: AsyncSession, records: Sequence[DatasetModel]
) -> list[DatasetSummary]:
    """Same result as awaiting ``_dataset_summary`` once per record, without the N+1: one
    query for every active version in the page and one for every version's columns,
    instead of two round trips per dataset (this is what makes a 100-item page of
    /datasets do ~200 sequential database round trips today)."""

    if not records:
        return []
    for record in records:
        if record.active_version_id is None:
            raise DatasetDomainError(
                "DATASET_VERSION_NOT_FOUND", "数据集没有激活版本。", status_code=404
            )
    version_ids = [record.active_version_id for record in records]
    versions_by_id = {
        version.id: version
        for version in (
            await session.scalars(
                select(DatasetVersionModel).where(DatasetVersionModel.id.in_(version_ids))
            )
        ).all()
    }
    columns_by_version: dict[UUID, list[DatasetColumnModel]] = defaultdict(list)
    for column in (
        await session.scalars(
            select(DatasetColumnModel)
            .where(DatasetColumnModel.version_id.in_(version_ids))
            .order_by(DatasetColumnModel.position)
        )
    ).all():
        columns_by_version[column.version_id].append(column)

    summaries: list[DatasetSummary] = []
    for record in records:
        active_version_id = record.active_version_id
        version = versions_by_id.get(active_version_id) if active_version_id is not None else None
        if version is None or version.dataset_id != record.id:
            raise DatasetDomainError(
                "DATASET_VERSION_NOT_FOUND", "数据集激活版本不存在。", status_code=404
            )
        summaries.append(
            _build_dataset_summary(record, version, columns_by_version.get(version.id, []))
        )
    return summaries


async def _dataset_or_404(session: AsyncSession, dataset_id: UUID) -> DatasetModel:
    record = await session.get(DatasetModel, dataset_id)
    if record is None:
        raise DatasetDomainError(
            "DATASET_NOT_FOUND",
            "数据集不存在或已删除。",
            status_code=404,
            details={"dataset_id": str(dataset_id)},
        )
    return record


async def _active_version_or_error(
    session: AsyncSession, dataset: DatasetModel
) -> DatasetVersionModel:
    if dataset.active_version_id is None:
        raise DatasetDomainError(
            "DATASET_VERSION_NOT_FOUND", "数据集没有激活版本。", status_code=404
        )
    version = await session.get(DatasetVersionModel, dataset.active_version_id)
    if version is None or version.dataset_id != dataset.id:
        raise DatasetDomainError(
            "DATASET_VERSION_NOT_FOUND", "数据集激活版本不存在。", status_code=404
        )
    return version


async def _version_columns(session: AsyncSession, version_id: UUID) -> list[DatasetColumnModel]:
    return list(
        (
            await session.scalars(
                select(DatasetColumnModel)
                .where(DatasetColumnModel.version_id == version_id)
                .order_by(DatasetColumnModel.position)
            )
        ).all()
    )


async def _profile_or_error(
    session: AsyncSession, dataset_id: UUID, version_id: UUID
) -> DatasetProfileRecord:
    record = await session.scalar(
        select(DatasetProfileRecord).where(
            DatasetProfileRecord.dataset_id == dataset_id,
            DatasetProfileRecord.version_id == version_id,
        )
    )
    if record is None:
        raise DatasetDomainError(
            "DATASET_PROFILE_NOT_FOUND", "数据集质量画像尚未生成。", status_code=404
        )
    return record


def _build_profile(dataset_id: UUID, version_id: UUID, parsed: ParsedCsv) -> dict[str, Any]:
    return build_quality_profile(
        dataset_id=str(dataset_id),
        version_id=str(version_id),
        headers=parsed.headers,
        rows=parsed.rows,
        inferred_types=parsed.inferred_types,
        timestamps=parsed.timestamps,
    ).payload


def _profile_schema(payload: dict[str, Any]) -> DatasetProfile:
    enriched = enrich_freeze_diagnostics(payload)
    external = {key: value for key, value in enriched.items() if key != "column_missing_counts"}
    return DatasetProfile.model_validate(external)


def _load_version_csv(
    dataset: DatasetModel, version: DatasetVersionModel, artifact_root: Path
) -> ParsedCsv:
    try:
        return load_version_csv(dataset=dataset, version=version, artifact_root=artifact_root)
    except DatasetVersionArtifactError as error:
        raise DatasetDomainError(
            error.code, error.message, status_code=404, details=error.details
        ) from error


def _resolve_column_configuration(
    columns: Sequence[DatasetColumnModel], payload: DatasetConfigRequest
) -> tuple[dict[str, str], dict[str, str | None]]:
    known_names = {column.name for column in columns}
    current_roles = {column.name: column.role for column in columns}
    units: dict[str, str | None] = {}
    if payload.columns is not None:
        roles = {name: "ignore" for name in known_names}
        _apply_explicit_columns(roles, units, payload.columns, known_names)
        return roles, units

    if payload.time_column is None and payload.output_column is None and not payload.input_columns:
        raise DatasetDomainError("INVALID_DATASET_SCHEMA", "请提供 columns 或紧凑列映射字段。")
    roles = current_roles.copy()
    if payload.time_column is not None:
        _ensure_known_column(payload.time_column, known_names)
        for name in roles:
            if roles[name] == "timestamp":
                roles[name] = "ignore"
        roles[payload.time_column] = "timestamp"
    if payload.output_column is not None:
        _ensure_known_column(payload.output_column, known_names)
        for name in roles:
            if roles[name] == "output":
                roles[name] = "ignore"
        roles[payload.output_column] = "output"
    for name in payload.input_columns:
        _ensure_known_column(name, known_names)
        roles[name] = "input"
    for name in payload.ignored_columns:
        _ensure_known_column(name, known_names)
        roles[name] = "ignore"
    return roles, units


def _apply_explicit_columns(
    roles: dict[str, str],
    units: dict[str, str | None],
    entries: Sequence[DatasetColumnConfig],
    known_names: set[str],
) -> None:
    seen: set[str] = set()
    for entry in entries:
        _ensure_known_column(entry.name, known_names)
        if entry.name in seen:
            raise DatasetDomainError("INVALID_DATASET_SCHEMA", "列配置中存在重复字段。")
        seen.add(entry.name)
        roles[entry.name] = _normalise_role(entry.role)
        units[entry.name] = entry.unit


def _ensure_known_column(name: str, known_names: set[str]) -> None:
    if name not in known_names:
        raise DatasetDomainError(
            "INVALID_DATASET_SCHEMA", "列配置引用了不存在的字段。", details={"column": name}
        )


def _normalise_role(role: str) -> str:
    return {"time": "timestamp", "ignored": "ignore"}.get(role, role)


def _display_name(display_name: str | None, filename: str) -> str:
    candidate = (display_name or filename).strip()
    return candidate[:120] or "uploaded.csv"


def _delimiter_label(delimiter: str) -> str:
    return {",": "comma", ";": "semicolon", "\t": "tab"}.get(delimiter, delimiter)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
