"""Read-only comparison of immutable Cleaning-eligible dataset versions."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from math import isfinite
from pathlib import Path
from typing import Literal, TypeVar
from uuid import UUID

from algorithms.cleaning.quality import is_missing
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset import Dataset, DatasetColumn, DatasetVersion, ProcessingRun
from app.schemas.preprocessing import (
    CleaningVersionCompareChannelOption,
    CleaningVersionCompareChannelsData,
    CleaningVersionCompareData,
    ConvergenceEvidence,
    DirectCleaningDerivationSummary,
    GenericDiffSummary,
    VersionCompareChannel,
    VersionComparePoint,
    VersionCompareProjection,
    VersionCompareRef,
    VersionCompareSeries,
    VersionConvergenceEvidence,
    VersionDifferencePoint,
)
from app.services.cleaning_service import replay_cleaning_audit
from app.services.dataset_csv import ParsedCsv
from app.services.dataset_version_io import (
    DatasetVersionArtifactError,
    artifact_matches_sha256,
    load_version_csv,
)

ELIGIBLE_OPERATIONS = frozenset(
    {"simulation_generate", "raw_upload", "preprocessing.clean"}
)
FULL_CHANGE_SUMMARY_FIELDS = frozenset(
    {
        "unique_changed_cells",
        "missing_value_fills",
        "outlier_replacements",
        "smoothing_changes",
        "duplicate_timestamps_processed",
        "resampling_empty_rows_created",
    }
)
ItemT = TypeVar("ItemT")
NumericInferredType = Literal["float", "integer"]


class CleaningVersionCompareError(Exception):
    """A client-safe validation or artifact error for Cleaning Version Compare."""

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


async def get_cleaning_version_compare_channels(
    session: AsyncSession,
    *,
    dataset_id: UUID,
    baseline_version_id: UUID,
    compare_version_id: UUID,
    artifact_root: Path,
) -> CleaningVersionCompareChannelsData:
    """Return common numeric channels in immutable Baseline column order."""

    dataset, baseline, compare, baseline_parsed, compare_parsed, _ = (
        await _load_compare_inputs(
            session,
            dataset_id=dataset_id,
            baseline_version_id=baseline_version_id,
            compare_version_id=compare_version_id,
            artifact_root=artifact_root,
        )
    )
    candidates: list[
        tuple[str, NumericInferredType, NumericInferredType]
    ] = []
    for name in baseline_parsed.headers:
        baseline_type = _numeric_inferred_type(
            baseline_parsed.inferred_types.get(name)
        )
        compare_type = _numeric_inferred_type(compare_parsed.inferred_types.get(name))
        if (
            baseline_type is None
            or compare_type is None
            or name == baseline_parsed.timestamp_column
            or name == compare_parsed.timestamp_column
        ):
            continue
        candidates.append((name, baseline_type, compare_type))

    units = await _channel_units(
        session,
        baseline_version_id=baseline.id,
        compare_version_id=compare.id,
        channels=[name for name, _, _ in candidates],
    )
    warnings: list[str] = []
    channels: list[CleaningVersionCompareChannelOption] = []
    for name, baseline_type, compare_type in candidates:
        unit, mismatch = units[name]
        if mismatch:
            warnings.append(f"通道 {name} 的两侧版本单位不一致，unit 已置空。")
        channels.append(
            CleaningVersionCompareChannelOption(
                name=name,
                baseline_inferred_type=baseline_type,
                compare_inferred_type=compare_type,
                unit=unit,
            )
        )

    return CleaningVersionCompareChannelsData(
        dataset_id=dataset.id,
        baseline_version_id=baseline.id,
        compare_version_id=compare.id,
        channels=channels,
        warnings=warnings,
    )


async def compare_cleaning_versions(
    session: AsyncSession,
    *,
    dataset_id: UUID,
    baseline_version_id: UUID,
    compare_version_id: UUID,
    channel: str,
    max_points: int,
    artifact_root: Path,
) -> CleaningVersionCompareData:
    """Compare full immutable artifacts, then project only the visualization payload.

    ``added_points`` and ``removed_points`` count source occurrences. Ambiguity counts
    timestamp groups, while ``*_duplicate_occurrences`` counts occurrences beyond the
    first occurrence in each duplicate group.
    """

    dataset, baseline, compare, baseline_parsed, compare_parsed, versions_by_id = (
        await _load_compare_inputs(
            session,
            dataset_id=dataset_id,
            baseline_version_id=baseline_version_id,
            compare_version_id=compare_version_id,
            artifact_root=artifact_root,
        )
    )
    inferred_type = _validate_channel(
        channel=channel,
        baseline=baseline_parsed,
        compare=compare_parsed,
    )

    warnings: list[str] = []
    unit, unit_mismatch = await _channel_unit(
        session,
        baseline_version_id=baseline.id,
        compare_version_id=compare.id,
        channel=channel,
    )
    if unit_mismatch:
        warnings.append("两侧版本记录的通道单位不一致，response.channel.unit 已置空。")

    baseline_groups = _timestamp_groups(baseline_parsed, channel)
    compare_groups = (
        baseline_groups
        if compare.id == baseline.id
        else _timestamp_groups(compare_parsed, channel)
    )
    baseline_points = _ordered_points(baseline_groups)
    compare_points = (
        list(baseline_points) if compare.id == baseline.id else _ordered_points(compare_groups)
    )

    if compare.id == baseline.id:
        differences: list[VersionDifferencePoint] = []
        generic_summary = _same_version_summary(baseline_groups, len(baseline_points))
    else:
        differences, generic_summary = _generic_diff(baseline_groups, compare_groups)

    if generic_summary.ambiguous_timestamp_groups:
        warnings.append(
            f"存在 {generic_summary.ambiguous_timestamp_groups} 个重复时间戳对齐歧义组；"
            "未执行人为 occurrence 配对。"
        )

    direct_summary = _direct_derivation_summary(
        dataset=dataset,
        baseline=baseline,
        compare=compare,
        artifact_root=artifact_root,
        warnings=warnings,
    )
    baseline_convergence = await _latest_convergence_evidence(session, baseline)
    compare_convergence = (
        baseline_convergence
        if compare.id == baseline.id
        else await _latest_convergence_evidence(session, compare)
    )

    returned_baseline = _project(baseline_points, max_points)
    returned_compare = _project(compare_points, max_points)
    returned_differences = _project(differences, max_points)
    projection_applied = (
        len(returned_baseline) < len(baseline_points)
        or len(returned_compare) < len(compare_points)
        or len(returned_differences) < len(differences)
    )
    if projection_applied:
        warnings.append(
            "可视化 payload 已按 max_points 确定性投影；generic_diff_summary 仍基于完整数据。"
        )

    relation, direction = _lineage_relation(baseline, compare, versions_by_id)
    artifacts_identical = baseline.sha256 == compare.sha256
    return CleaningVersionCompareData(
        dataset_id=dataset.id,
        baseline=_version_ref(baseline),
        compare=_version_ref(compare),
        relation=relation,
        direction=direction,
        channel=VersionCompareChannel(name=channel, inferred_type=inferred_type, unit=unit),
        baseline_series=VersionCompareSeries(
            input_point_count=len(baseline_points),
            returned_point_count=len(returned_baseline),
            projected=len(returned_baseline) < len(baseline_points),
            points=returned_baseline,
        ),
        compare_series=VersionCompareSeries(
            input_point_count=len(compare_points),
            returned_point_count=len(returned_compare),
            projected=len(returned_compare) < len(compare_points),
            points=returned_compare,
        ),
        difference_points=returned_differences,
        difference_points_truncated=len(returned_differences) < len(differences),
        generic_diff_summary=generic_summary,
        direct_derivation_summary=direct_summary,
        convergence_evidence=VersionConvergenceEvidence(
            baseline=baseline_convergence,
            compare=compare_convergence,
        ),
        artifacts_identical=artifacts_identical,
        projection=VersionCompareProjection(
            applied=projection_applied,
            max_points=max_points,
            strategy=("evenly_spaced_index_with_endpoints" if projection_applied else "none"),
        ),
        warnings=warnings,
    )


async def _load_compare_inputs(
    session: AsyncSession,
    *,
    dataset_id: UUID,
    baseline_version_id: UUID,
    compare_version_id: UUID,
    artifact_root: Path,
) -> tuple[
    Dataset,
    DatasetVersion,
    DatasetVersion,
    ParsedCsv,
    ParsedCsv,
    dict[UUID, DatasetVersion],
]:
    dataset = await session.get(Dataset, dataset_id)
    if dataset is None:
        raise CleaningVersionCompareError(
            "DATASET_NOT_FOUND",
            "数据集不存在或已删除。",
            status_code=404,
            details={"dataset_id": str(dataset_id)},
        )

    versions = list(
        (
            await session.scalars(
                select(DatasetVersion).where(DatasetVersion.dataset_id == dataset.id)
            )
        ).all()
    )
    versions_by_id = {version.id: version for version in versions}
    baseline = _version_or_error(
        versions_by_id, baseline_version_id, dataset_id=dataset.id, side="baseline"
    )
    compare = _version_or_error(
        versions_by_id, compare_version_id, dataset_id=dataset.id, side="compare"
    )
    _ensure_eligible(baseline, side="baseline")
    _ensure_eligible(compare, side="compare")

    baseline_parsed = _load_verified_artifact(
        dataset=dataset,
        version=baseline,
        artifact_root=artifact_root,
        side="baseline",
    )
    compare_parsed = (
        baseline_parsed
        if compare.id == baseline.id
        else _load_verified_artifact(
            dataset=dataset,
            version=compare,
            artifact_root=artifact_root,
            side="compare",
        )
    )
    return (
        dataset,
        baseline,
        compare,
        baseline_parsed,
        compare_parsed,
        versions_by_id,
    )


def _version_or_error(
    versions: Mapping[UUID, DatasetVersion],
    version_id: UUID,
    *,
    dataset_id: UUID,
    side: str,
) -> DatasetVersion:
    version = versions.get(version_id)
    if version is None:
        raise CleaningVersionCompareError(
            "DATASET_VERSION_NOT_FOUND",
            "请求的数据版本不存在。",
            status_code=404,
            details={
                "dataset_id": str(dataset_id),
                "version_id": str(version_id),
                "side": side,
            },
        )
    return version


def _ensure_eligible(version: DatasetVersion, *, side: str) -> None:
    if version.operation_name in ELIGIBLE_OPERATIONS:
        return
    raise CleaningVersionCompareError(
        "CLEANING_COMPARE_VERSION_INELIGIBLE",
        "数据版本不属于 Cleaning Compare 允许的处理阶段。",
        status_code=422,
        details={
            "version_id": str(version.id),
            "operation_name": version.operation_name,
            "side": side,
        },
    )


def _load_verified_artifact(
    *,
    dataset: Dataset,
    version: DatasetVersion,
    artifact_root: Path,
    side: str,
) -> ParsedCsv:
    try:
        parsed = load_version_csv(
            dataset=dataset,
            version=version,
            artifact_root=artifact_root,
        )
    except DatasetVersionArtifactError as error:
        raise CleaningVersionCompareError(
            error.code,
            error.message,
            status_code=404,
            details={**error.details, "version_id": str(version.id), "side": side},
        ) from error
    if not artifact_matches_sha256(
        artifact_root=artifact_root,
        relative_path=version.artifact_path,
        expected_sha256=version.sha256,
    ):
        raise CleaningVersionCompareError(
            "DATASET_ARTIFACT_INTEGRITY_FAILED",
            "数据版本 CSV 产物与登记摘要不一致。",
            status_code=409,
            details={"version_id": str(version.id), "side": side},
        )
    return parsed


def _validate_channel(
    *, channel: str, baseline: ParsedCsv, compare: ParsedCsv
) -> NumericInferredType:
    baseline_type = baseline.inferred_types.get(channel)
    compare_type = compare.inferred_types.get(channel)
    baseline_numeric_type = _numeric_inferred_type(baseline_type)
    compare_numeric_type = _numeric_inferred_type(compare_type)
    if (
        channel in {baseline.timestamp_column, compare.timestamp_column}
        or baseline_numeric_type is None
        or compare_numeric_type is None
    ):
        raise CleaningVersionCompareError(
            "CLEANING_COMPARE_CHANNEL_INVALID",
            "观察通道必须同时存在于两个版本中且两侧均为数值列。",
            status_code=422,
            details={
                "channel": channel,
                "baseline_type": baseline_type,
                "compare_type": compare_type,
                "baseline_timestamp_column": baseline.timestamp_column,
                "compare_timestamp_column": compare.timestamp_column,
            },
        )
    return (
        "float"
        if "float" in {baseline_numeric_type, compare_numeric_type}
        else "integer"
    )


def _numeric_inferred_type(value: str | None) -> NumericInferredType | None:
    if value == "float" or value == "integer":
        return value
    return None


async def _channel_unit(
    session: AsyncSession,
    *,
    baseline_version_id: UUID,
    compare_version_id: UUID,
    channel: str,
) -> tuple[str | None, bool]:
    return (
        await _channel_units(
            session,
            baseline_version_id=baseline_version_id,
            compare_version_id=compare_version_id,
            channels=[channel],
        )
    )[channel]


async def _channel_units(
    session: AsyncSession,
    *,
    baseline_version_id: UUID,
    compare_version_id: UUID,
    channels: Sequence[str],
) -> dict[str, tuple[str | None, bool]]:
    if not channels:
        return {}
    columns = list(
        (
            await session.scalars(
                select(DatasetColumn).where(
                    DatasetColumn.version_id.in_(
                        {baseline_version_id, compare_version_id}
                    ),
                    DatasetColumn.name.in_(channels),
                )
            )
        ).all()
    )
    units_by_key = {
        (column.version_id, column.name): column.unit for column in columns
    }
    result: dict[str, tuple[str | None, bool]] = {}
    for channel in channels:
        baseline_unit = units_by_key.get((baseline_version_id, channel))
        compare_unit = units_by_key.get((compare_version_id, channel))
        result[channel] = (
            (baseline_unit, False)
            if baseline_unit == compare_unit
            else (None, True)
        )
    return result


def _timestamp_groups(
    parsed: ParsedCsv, channel: str
) -> dict[datetime, list[VersionComparePoint]]:
    groups: defaultdict[datetime, list[VersionComparePoint]] = defaultdict(list)
    for timestamp, row in zip(parsed.timestamps, parsed.rows, strict=True):
        raw = row.get(channel)
        value: float | None
        if raw is None or is_missing(raw):
            value = None
        else:
            try:
                value = float(raw)
            except ValueError as error:
                raise CleaningVersionCompareError(
                    "CLEANING_COMPARE_CHANNEL_INVALID",
                    "观察通道包含无法解析的数值。",
                    status_code=422,
                    details={"channel": channel},
                ) from error
            if not isfinite(value):
                raise CleaningVersionCompareError(
                    "CLEANING_COMPARE_CHANNEL_INVALID",
                    "观察通道包含非有限数值。",
                    status_code=422,
                    details={"channel": channel},
                )
        occurrences = groups[timestamp]
        occurrences.append(
            VersionComparePoint(
                timestamp=timestamp,
                occurrence_index=len(occurrences),
                value=value,
            )
        )
    return dict(groups)


def _ordered_points(
    groups: Mapping[datetime, Sequence[VersionComparePoint]],
) -> list[VersionComparePoint]:
    return [point for timestamp in sorted(groups) for point in groups[timestamp]]


def _same_version_summary(
    groups: Mapping[datetime, Sequence[VersionComparePoint]], point_count: int
) -> GenericDiffSummary:
    duplicate_occurrences = sum(max(0, len(points) - 1) for points in groups.values())
    unique_timestamps = sum(len(points) == 1 for points in groups.values())
    return GenericDiffSummary(
        baseline_point_count=point_count,
        compare_point_count=point_count,
        unique_matched_timestamps=unique_timestamps,
        unchanged_values=unique_timestamps,
        changed_values=0,
        added_points=0,
        removed_points=0,
        ambiguous_timestamp_groups=0,
        baseline_duplicate_occurrences=duplicate_occurrences,
        compare_duplicate_occurrences=duplicate_occurrences,
        contains_null_transitions=False,
    )


def _generic_diff(
    baseline: Mapping[datetime, Sequence[VersionComparePoint]],
    compare: Mapping[datetime, Sequence[VersionComparePoint]],
) -> tuple[list[VersionDifferencePoint], GenericDiffSummary]:
    differences: list[VersionDifferencePoint] = []
    unique_matched = 0
    unchanged = 0
    changed = 0
    added = 0
    removed = 0
    ambiguous = 0
    contains_null_transitions = False

    for timestamp in sorted(set(baseline) | set(compare)):
        baseline_occurrences = list(baseline.get(timestamp, ()))
        compare_occurrences = list(compare.get(timestamp, ()))
        if baseline_occurrences and compare_occurrences:
            if len(baseline_occurrences) > 1 or len(compare_occurrences) > 1:
                ambiguous += 1
                differences.append(
                    VersionDifferencePoint(
                        timestamp=timestamp,
                        difference_kind="AMBIGUOUS_ALIGNMENT",
                        baseline_occurrences=baseline_occurrences,
                        compare_occurrences=compare_occurrences,
                    )
                )
                continue

            unique_matched += 1
            baseline_value = baseline_occurrences[0].value
            compare_value = compare_occurrences[0].value
            if baseline_value == compare_value:
                unchanged += 1
                continue
            changed += 1
            null_transition = baseline_value is None or compare_value is None
            contains_null_transitions = contains_null_transitions or null_transition
            differences.append(
                VersionDifferencePoint(
                    timestamp=timestamp,
                    difference_kind="VALUE_CHANGED",
                    baseline_value=baseline_value,
                    compare_value=compare_value,
                    absolute_delta=(
                        None
                        if null_transition
                        else abs(compare_value - baseline_value)  # type: ignore[operator]
                    ),
                    baseline_occurrences=baseline_occurrences,
                    compare_occurrences=compare_occurrences,
                )
            )
            continue

        if baseline_occurrences:
            removed += len(baseline_occurrences)
            differences.append(
                VersionDifferencePoint(
                    timestamp=timestamp,
                    difference_kind="POINT_REMOVED",
                    baseline_value=(
                        baseline_occurrences[0].value
                        if len(baseline_occurrences) == 1
                        else None
                    ),
                    baseline_occurrences=baseline_occurrences,
                )
            )
            continue

        added += len(compare_occurrences)
        differences.append(
            VersionDifferencePoint(
                timestamp=timestamp,
                difference_kind="POINT_ADDED",
                compare_value=(
                    compare_occurrences[0].value if len(compare_occurrences) == 1 else None
                ),
                compare_occurrences=compare_occurrences,
            )
        )

    summary = GenericDiffSummary(
        baseline_point_count=sum(len(points) for points in baseline.values()),
        compare_point_count=sum(len(points) for points in compare.values()),
        unique_matched_timestamps=unique_matched,
        unchanged_values=unchanged,
        changed_values=changed,
        added_points=added,
        removed_points=removed,
        ambiguous_timestamp_groups=ambiguous,
        baseline_duplicate_occurrences=sum(
            max(0, len(points) - 1) for points in baseline.values()
        ),
        compare_duplicate_occurrences=sum(
            max(0, len(points) - 1) for points in compare.values()
        ),
        contains_null_transitions=contains_null_transitions,
    )
    return differences, summary


def _direct_derivation_summary(
    *,
    dataset: Dataset,
    baseline: DatasetVersion,
    compare: DatasetVersion,
    artifact_root: Path,
    warnings: list[str],
) -> DirectCleaningDerivationSummary | None:
    if compare.parent_version_id != baseline.id or compare.operation_name != "preprocessing.clean":
        return None

    parameters = compare.parameters if isinstance(compare.parameters, dict) else {}
    persisted = parameters.get("change_summary")
    if isinstance(persisted, dict) and FULL_CHANGE_SUMMARY_FIELDS.issubset(persisted):
        return DirectCleaningDerivationSummary(
            from_version_id=baseline.id,
            to_version_id=compare.id,
            evidence_source="persisted",
            changes=dict(persisted),
        )

    resolved = parameters.get("resolved_parameters")
    if isinstance(resolved, Mapping):
        try:
            replayed = replay_cleaning_audit(
                dataset=dataset,
                source_version=baseline,
                resolved_parameters=resolved,
                artifact_root=artifact_root,
            ).get("change_summary")
        except (DatasetVersionArtifactError, TypeError, ValueError):
            replayed = None
        if isinstance(replayed, dict) and FULL_CHANGE_SUMMARY_FIELDS.issubset(replayed):
            return DirectCleaningDerivationSummary(
                from_version_id=baseline.id,
                to_version_id=compare.id,
                evidence_source="replayed",
                changes=dict(replayed),
            )

    total = parameters.get("total_cleaned_points")
    if isinstance(total, int) and not isinstance(total, bool) and total >= 0:
        warnings.append("Direct Cleaning summary 仅保留历史总数，分类 breakdown 未记录。")
        return DirectCleaningDerivationSummary(
            from_version_id=baseline.id,
            to_version_id=compare.id,
            evidence_source="legacy_total_only",
            changes={
                "count_unit": "cell",
                "unique_changed_cells": total,
                "breakdown_status": "not_recorded",
            },
        )

    warnings.append("Direct Cleaning derivation 的历史 change summary 不完整，无法可靠恢复。")
    return None


async def _latest_convergence_evidence(
    session: AsyncSession, version: DatasetVersion
) -> ConvergenceEvidence | None:
    runs = list(
        (
            await session.scalars(
                select(ProcessingRun)
                .where(
                    ProcessingRun.source_version_id == version.id,
                    ProcessingRun.run_type == "preprocessing.clean",
                    ProcessingRun.status == "succeeded",
                )
                .order_by(ProcessingRun.created_at.desc(), ProcessingRun.id.desc())
            )
        ).all()
    )
    for run in runs:
        result = run.result if isinstance(run.result, dict) else {}
        changes = result.get("change_summary")
        if not isinstance(changes, Mapping):
            continue
        unique_changed_cells = changes.get("unique_changed_cells")
        if (
            result.get("converged") is not True
            or result.get("no_op") is not True
            or str(result.get("effective_version_id")) != str(version.id)
            or isinstance(unique_changed_cells, bool)
            or unique_changed_cells != 0
        ):
            continue
        return ConvergenceEvidence(
            version_id=version.id,
            processing_run_id=run.id,
            occurred_at=run.finished_at or run.created_at,
            effective_version_id=version.id,
            parameters=(dict(run.parameters) if isinstance(run.parameters, Mapping) else {}),
        )
    return None


def _lineage_relation(
    baseline: DatasetVersion,
    compare: DatasetVersion,
    versions: Mapping[UUID, DatasetVersion],
) -> tuple[str, str]:
    if baseline.id == compare.id:
        return "SAME_VERSION", "NONE"
    if compare.parent_version_id == baseline.id:
        return "DIRECT_PARENT", "BASELINE_TO_COMPARE"
    if baseline.parent_version_id == compare.id:
        return "DIRECT_PARENT", "COMPARE_TO_BASELINE"
    if _is_ancestor(baseline.id, compare, versions):
        return "ANCESTOR_DESCENDANT", "BASELINE_TO_COMPARE"
    if _is_ancestor(compare.id, baseline, versions):
        return "ANCESTOR_DESCENDANT", "COMPARE_TO_BASELINE"
    if (
        baseline.parent_version_id is not None
        and baseline.parent_version_id == compare.parent_version_id
    ):
        return "SIBLING", "NONE"
    return "UNRELATED_WITHIN_DATASET", "NONE"


def _is_ancestor(
    ancestor_id: UUID,
    descendant: DatasetVersion,
    versions: Mapping[UUID, DatasetVersion],
) -> bool:
    current_id = descendant.parent_version_id
    visited: set[UUID] = set()
    while current_id is not None:
        if current_id in visited:
            raise CleaningVersionCompareError(
                "DATASET_VERSION_LINEAGE_INVALID",
                "数据版本血缘存在循环引用。",
                status_code=409,
                details={"version_id": str(descendant.id)},
            )
        visited.add(current_id)
        if current_id == ancestor_id:
            return True
        current = versions.get(current_id)
        if current is None:
            return False
        current_id = current.parent_version_id
    return False


def _version_ref(version: DatasetVersion) -> VersionCompareRef:
    return VersionCompareRef(
        version_id=version.id,
        name=version.name,
        operation_name=version.operation_name,
        parent_version_id=version.parent_version_id,
        created_at=version.created_at,
        row_count=version.row_count,
        column_count=version.column_count,
        sha256=version.sha256,
    )


def _project(items: Sequence[ItemT], max_points: int) -> list[ItemT]:
    if len(items) <= max_points:
        return list(items)
    last_index = len(items) - 1
    return [items[index * last_index // (max_points - 1)] for index in range(max_points)]


__all__ = [
    "CleaningVersionCompareError",
    "compare_cleaning_versions",
    "get_cleaning_version_compare_channels",
]
