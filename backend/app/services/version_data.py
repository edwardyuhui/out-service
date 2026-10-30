"""Uniform numeric access to any dataset version, uploaded or simulated.

Every stage from segment selection onwards needs the same thing: the numeric arrays of
one immutable version, plus which columns are inputs and which is the output. Uploaded
CSVs carry that in PostgreSQL (``DatasetVersion`` + ``DatasetColumn``); the S1-S6
benchmarks carry it in a local artifact manifest. This module hides the difference so the
closed loop never has to care which kind of data it is running on.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from statistics import median
from uuid import UUID

import numpy as np
from numpy.typing import NDArray
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset import Dataset, DatasetColumn, DatasetVersion
from app.services.dataset_version_io import DatasetVersionArtifactError, load_version_csv
from app.services.simulation_service import (
    SimulationArtifactNotFoundError,
    load_simulation_by_version,
)

FloatArray = NDArray[np.float64]

MISSING_TOKENS = {"", "na", "n/a", "null", "none", "nan"}
# The vocabulary `dataset_csv._infer_type` emits for modellable columns.
NUMERIC_COLUMN_TYPES = frozenset({"integer", "float", "numeric"})


class VersionDataError(Exception):
    """A client-safe failure to resolve a version into modelling-ready arrays."""

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
class VersionSeries:
    """Numeric view of one immutable dataset version."""

    dataset_id: UUID
    version_id: UUID
    dataset_name: str
    origin: str
    timestamps: list[datetime]
    values: dict[str, FloatArray]
    declared_inputs: tuple[str, ...]
    declared_output: str | None
    sample_period_seconds: float | None
    available_columns: tuple[str, ...] = ()
    monitored_inputs: tuple[str, ...] = ()
    input_context_versions: dict[str, str] = field(default_factory=dict)

    @property
    def n_samples(self) -> int:
        return len(self.timestamps) if self.timestamps else _first_length(self.values)

    def numeric_columns(self) -> list[str]:
        return sorted(self.values)

    def resolve_columns(
        self,
        *,
        input_columns: list[str] | None,
        output_column: str | None,
    ) -> tuple[list[str], str]:
        """Pick the modelling roles, preferring the request then the stored schema."""

        resolved_output = output_column or self.declared_output
        if resolved_output is None:
            raise VersionDataError(
                "INVALID_DATASET_SCHEMA",
                "未指定输出变量，且数据版本没有已确认的输出列。",
                details={"available_columns": self.numeric_columns()},
            )
        if resolved_output not in self.values:
            raise VersionDataError(
                "INVALID_DATASET_SCHEMA",
                "请求的输出变量不存在或不是数值列。",
                details={
                    "output_column": resolved_output,
                    "available_columns": self.numeric_columns(),
                },
            )
        candidates = list(input_columns or self.declared_inputs)
        if not candidates:
            candidates = [column for column in self.numeric_columns() if column != resolved_output]
        invalid = sorted(set(candidates) - set(self.values))
        if invalid:
            raise VersionDataError(
                "INVALID_DATASET_SCHEMA",
                "请求的输入变量不存在或不是数值列。",
                details={"invalid_columns": invalid, "available_columns": self.numeric_columns()},
            )
        if resolved_output in candidates:
            raise VersionDataError(
                "INVALID_DATASET_SCHEMA",
                "同一列不能同时作为输入和输出。",
                details={"column": resolved_output},
            )
        if not candidates:
            raise VersionDataError(
                "INVALID_DATASET_SCHEMA",
                "数据版本不包含可用的输入变量。",
                details={"available_columns": self.numeric_columns()},
            )
        return candidates, resolved_output


def model_input_arrays(series: VersionSeries, input_columns: list[str]) -> dict[str, FloatArray]:
    """Model features keep their roles; removed controls are context monitors only."""
    return {c: series.values[c] for c in sorted(set(input_columns) | set(series.declared_inputs)
                                               | set(series.monitored_inputs))}


async def attach_model_input_context(
    session: AsyncSession, series: VersionSeries, *, artifact_root: Path,
) -> VersionSeries:
    """Recover dropped controls through row-preserving feature-selection lineage.

    Walk only that operation. Resampling, row deletion and lag changes cannot be
    joined by row number. Ancestor values are never added to the model features.
    """
    values, sources = dict(series.values), dict(series.input_context_versions)
    monitors = set(series.monitored_inputs)
    version_id, visited = series.version_id, set()
    while True:
        if version_id in visited:
            raise VersionDataError("MODEL_INPUT_CONTEXT_UNALIGNED", "控制量来源版本存在循环血缘")
        visited.add(version_id)
        version = await session.get(DatasetVersion, version_id)
        if version is None or version.operation_name != "preprocessing.feature_selection":
            break
        if version.parent_version_id is None:
            raise VersionDataError("MODEL_INPUT_CONTEXT_UNALIGNED", "被剔除控制量缺少来源版本")
        parent = await load_version_series(session, version_id=version.parent_version_id,
            dataset_id=series.dataset_id, artifact_root=artifact_root)
        output = series.declared_output
        if (parent.n_samples != series.n_samples or parent.timestamps != series.timestamps
                or not output or output not in parent.values
                or not np.array_equal(series.values[output], parent.values[output], equal_nan=True)):
            raise VersionDataError("MODEL_INPUT_CONTEXT_UNALIGNED", "被剔除控制量的来源与当前建模数据无法逐行对齐")
        for column in parent.declared_inputs:
            if column not in values:
                values[column] = parent.values[column]
                sources[column] = str(parent.version_id)
                monitors.add(column)
        version_id = parent.version_id
    return replace(series, values=values, monitored_inputs=tuple(sorted(monitors)), input_context_versions=sources)


async def load_version_series(
    session: AsyncSession,
    *,
    version_id: UUID,
    artifact_root: Path,
    dataset_id: UUID | None = None,
) -> VersionSeries:
    """Resolve a version id to numeric arrays, trying the database then local artifacts."""

    version = await session.get(DatasetVersion, version_id)
    if version is not None:
        return await _load_persisted_version(
            session,
            version=version,
            artifact_root=artifact_root,
            dataset_id=dataset_id,
        )
    return _load_simulation_version(
        version_id=version_id,
        artifact_root=artifact_root,
        dataset_id=dataset_id,
    )


async def _load_persisted_version(
    session: AsyncSession,
    *,
    version: DatasetVersion,
    artifact_root: Path,
    dataset_id: UUID | None,
) -> VersionSeries:
    dataset = await session.get(Dataset, version.dataset_id)
    if dataset is None:
        raise VersionDataError("DATASET_NOT_FOUND", "数据版本所属数据集不存在。", status_code=404)
    if dataset_id is not None and dataset_id != dataset.id:
        raise VersionDataError(
            "DATASET_VERSION_MISMATCH",
            "数据集 ID 与数据版本不匹配。",
            details={"dataset_id": str(dataset_id), "version_id": str(version.id)},
        )
    try:
        parsed = load_version_csv(dataset=dataset, version=version, artifact_root=artifact_root)
    except DatasetVersionArtifactError as error:
        raise VersionDataError(
            error.code, error.message, status_code=404, details=error.details
        ) from error

    columns = list(
        (
            await session.scalars(
                select(DatasetColumn)
                .where(DatasetColumn.version_id == version.id)
                .order_by(DatasetColumn.position)
            )
        ).all()
    )
    # The CSV parser labels columns "integer"/"float", not "numeric"; matching the wrong
    # token silently rejected every uploaded dataset as having no modellable signal.
    declared_input_names = {column.name for column in columns if column.role == "input"}
    numeric_names = [
        name
        for name in parsed.headers
        if name != parsed.timestamp_column
        and (
            parsed.inferred_types.get(name) in NUMERIC_COLUMN_TYPES
            # A formal 0/1 engineering input can be inferred as boolean even when it is
            # intended for numeric diagnostics. Keep it available so the analysis stage
            # can classify a constant signal instead of reporting it as a missing column.
            or (
                name in declared_input_names
                and parsed.inferred_types.get(name) == "boolean"
            )
        )
    ]
    values = {name: _column_array(parsed.rows, name) for name in numeric_names}
    if not values:
        raise VersionDataError(
            "NO_NUMERIC_SIGNAL",
            "数据版本不包含可用于建模的数值列。",
            details={"headers": list(parsed.headers)},
        )
    declared_inputs = tuple(
        column.name for column in columns if column.role == "input" and column.name in values
    )
    declared_output = next(
        (column.name for column in columns if column.role == "output" and column.name in values),
        None,
    )
    return VersionSeries(
        dataset_id=dataset.id,
        version_id=version.id,
        dataset_name=dataset.name,
        origin="dataset",
        timestamps=list(parsed.timestamps),
        values=values,
        declared_inputs=declared_inputs,
        declared_output=declared_output,
        sample_period_seconds=_median_period(parsed.timestamps),
        available_columns=tuple(parsed.headers),
    )


def _load_simulation_version(
    *,
    version_id: UUID,
    artifact_root: Path,
    dataset_id: UUID | None,
) -> VersionSeries:
    try:
        simulated = load_simulation_by_version(version_id, artifact_root=artifact_root)
    except SimulationArtifactNotFoundError as error:
        raise VersionDataError(
            "DATASET_VERSION_NOT_FOUND",
            "数据版本不存在，且不是本地仿真产物。",
            status_code=404,
            details={"version_id": str(version_id)},
        ) from error
    if dataset_id is not None and dataset_id != simulated.dataset_id:
        raise VersionDataError(
            "DATASET_VERSION_MISMATCH",
            "数据集 ID 与数据版本不匹配。",
            details={"dataset_id": str(dataset_id), "version_id": str(version_id)},
        )
    values = {name: np.asarray(array, dtype=float) for name, array in simulated.values.items()}
    inputs = tuple(sorted(name for name in values if name.startswith("u")))
    output = "y" if "y" in values else None
    return VersionSeries(
        dataset_id=simulated.dataset_id,
        version_id=simulated.version_id,
        dataset_name=simulated.dataset_name,
        origin="simulation",
        timestamps=[],
        values=values,
        declared_inputs=inputs,
        declared_output=output,
        sample_period_seconds=None,
        available_columns=tuple(values),
    )


def _column_array(rows: list[dict[str, str]], column: str) -> FloatArray:
    """Missing tokens become NaN rather than zero; downstream tools drop, never impute."""

    values = np.empty(len(rows), dtype=float)
    for index, row in enumerate(rows):
        raw = row.get(column)
        if raw is None or raw.strip().lower() in MISSING_TOKENS:
            values[index] = np.nan
            continue
        try:
            values[index] = float(raw)
        except ValueError:
            values[index] = np.nan
    return values


def _median_period(timestamps: list[datetime]) -> float | None:
    if len(timestamps) < 2:
        return None
    deltas = [
        (later - earlier).total_seconds()
        for earlier, later in zip(timestamps, timestamps[1:], strict=False)
        if (later - earlier).total_seconds() > 0
    ]
    return float(median(deltas)) if deltas else None


def _first_length(values: dict[str, FloatArray]) -> int:
    for array in values.values():
        return int(array.shape[0])
    return 0
