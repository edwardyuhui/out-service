from datetime import datetime
from enum import IntEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.schemas.common import PageInfo, Schema, TaskResource

DatasetSource = Literal["upload", "simulation"]
DatasetState = Literal["parsing", "ready", "failed", "deleted"]
ColumnRole = Literal["timestamp", "input", "output", "ignore"]
ColumnType = Literal["datetime", "float", "integer", "string", "boolean"]


class DatasetSummary(Schema):
    id: UUID
    name: str
    source: DatasetSource
    status: DatasetState
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)
    latest_version_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    # Compatibility projections for the existing Dataset Hub client.  They are
    # additive; the frozen phase-1 fields above remain the canonical fields.
    version_id: UUID | None = None
    file_size_bytes: int | None = Field(default=None, ge=0)
    col_count: int | None = Field(default=None, ge=0)
    time_column: str | None = None
    input_columns: list[str] = Field(default_factory=list)
    output_column: str | None = None


class DatasetColumn(Schema):
    name: str
    inferred_type: ColumnType
    role: ColumnRole
    unit: str | None = None
    nullable: bool
    data_type: ColumnType | None = None
    missing_count: int = Field(default=0, ge=0)


class DatasetPreview(Schema):
    columns: list[str]
    rows: list[dict[str, str | float | int | bool | None]]
    truncated: bool
    recommended_downsample_factor: int = Field(ge=1)


class DatasetVersionPreviewPageSize(IntEnum):
    ROWS_50 = 50
    ROWS_100 = 100
    ROWS_200 = 200


class DatasetVersionPreviewPage(PageInfo):
    page_size: DatasetVersionPreviewPageSize = DatasetVersionPreviewPageSize.ROWS_100
    total_pages: int = Field(ge=0)


class DatasetVersionPreviewData(Schema):
    dataset_id: UUID
    version_id: UUID
    columns: list[str]
    rows: list[dict[str, str | float | int | bool | None]]
    page: DatasetVersionPreviewPage


class DatasetDetail(DatasetSummary):
    columns: list[DatasetColumn]
    time_range_start: datetime | None = None
    time_range_end: datetime | None = None
    preview: DatasetPreview | None = None
    simulation: dict[str, Any] | None = None


class DatasetListData(Schema):
    items: list[DatasetSummary]
    page: PageInfo


class DatasetUploadData(Schema):
    dataset: DatasetSummary
    parse_task: TaskResource
    deduplicated: bool = False


class DatasetDeleteData(Schema):
    dataset_id: UUID
    status: Literal["deleted"] = "deleted"


class IntervalHistogramBin(Schema):
    bin: float
    count: int = Field(ge=0)


class QualityIssue(Schema):
    code: str
    severity: Literal["info", "warning", "error"]
    message: str
    affected_columns: list[str] = Field(default_factory=list)


class ColumnStatistics(Schema):
    count: int = Field(ge=0)
    mean: float | None = None
    std: float | None = Field(default=None, ge=0)
    min: float | None = None
    max: float | None = None
    q25: float | None = None
    q50: float | None = None
    q75: float | None = None


class FrozenSegment(Schema):
    column: str
    start_index: int = Field(ge=0)
    end_index: int = Field(ge=0)
    length: int = Field(ge=1)


class FreezeDetectionSummary(Schema):
    candidate_count: int = Field(ge=0)
    affected_column_count: int = Field(ge=0)
    longest_segment: FrozenSegment | None = None


class DatasetProfile(Schema):
    dataset_id: UUID
    version_id: UUID
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)
    missing_rates: dict[str, float] = Field(description="0-1 的每列缺失率。")
    anomaly_counts: dict[str, int]
    interval_histogram: list[IntervalHistogramBin]
    duplicate_timestamp_count: int = Field(ge=0)
    irregular_sampling_rate: float = Field(ge=0, le=1)
    constant_columns: list[str]
    frozen_segments: list[FrozenSegment]
    candidate_frozen_segments: list[FrozenSegment] = Field(default_factory=list)
    freeze_detection_summary: FreezeDetectionSummary | None = None
    recommended_downsample_factor: int = Field(ge=1)
    quality_issues: list[QualityIssue]
    total_rows: int = Field(ge=0)
    total_cols: int = Field(ge=0)
    missing_rate: float = Field(ge=0, le=1)
    time_range_start: datetime | None = None
    time_range_end: datetime | None = None
    sample_period_seconds: float | None = Field(default=None, ge=0)
    max_consecutive_missing: dict[str, int] = Field(default_factory=dict)
    column_statistics: dict[str, ColumnStatistics] = Field(default_factory=dict)
    quality_score: float = Field(ge=0, le=100)
    recommendations: list[str] = Field(default_factory=list)


class VersionNode(Schema):
    id: UUID
    name: str
    tool: str
    created_at: datetime
    parent_version_id: UUID | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)
    artifact_path: str
    processing_run_id: UUID | None = None
    audit_summary: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    time_column: str | None = None
    input_columns: list[str] = Field(default_factory=list)
    output_column: str | None = None


class VersionEdge(Schema):
    source: UUID
    target: UUID
    operation: str


class DatasetVersionsData(Schema):
    dataset_id: UUID
    active_version_id: UUID | None = None
    nodes: list[VersionNode]
    edges: list[VersionEdge]


DelaySourceStatus = Literal["complete", "not_analyzed", "unrehydratable"]


class DelaySourceVersion(Schema):
    """One Cleaning version eligible as a Delay-analysis source."""

    version_id: UUID
    version_index: int = Field(ge=0)
    name: str
    operation_name: str
    parent_version_id: UUID | None = None
    created_at: datetime
    input_columns: list[str] = Field(default_factory=list)
    delay_status: DelaySourceStatus
    latest_complete_delay_run_id: UUID | None = None


class DelaySourceVersionsData(Schema):
    """Selector-ready Cleaning-version history for one dataset."""

    dataset_id: UUID
    default_source_version_id: UUID | None = None
    sources: list[DelaySourceVersion]


CollinearitySourceStatus = Literal["complete", "not_analyzed", "unrehydratable"]


class CollinearitySourceVersion(Schema):
    """One Lag Compensation version eligible as a Collinearity-analysis source."""

    version_id: UUID
    version_index: int = Field(ge=0)
    name: str
    operation_name: str
    parent_version_id: UUID | None = None
    created_at: datetime
    input_columns: list[str] = Field(default_factory=list)
    collinearity_status: CollinearitySourceStatus
    latest_complete_collinearity_run_id: UUID | None = None


class CollinearitySourceVersionsData(Schema):
    """Selector-ready Lag Compensation-version history for one dataset."""

    dataset_id: UUID
    default_source_version_id: UUID | None = None
    sources: list[CollinearitySourceVersion]


ColumnConfigRole = Literal["timestamp", "time", "input", "output", "ignore", "ignored"]


class DatasetColumnConfig(Schema):
    name: str = Field(min_length=1, max_length=255)
    role: ColumnConfigRole
    unit: str | None = Field(default=None, max_length=64)


class DatasetConfigRequest(Schema):
    """Accept an explicit column mapping or the compact form used by simple clients."""

    columns: list[DatasetColumnConfig] | None = None
    time_column: str | None = Field(default=None, min_length=1, max_length=255)
    input_columns: list[str] = Field(default_factory=list)
    output_column: str | None = Field(default=None, min_length=1, max_length=255)
    ignored_columns: list[str] = Field(default_factory=list)


class DatasetConfigData(Schema):
    dataset: DatasetDetail
    profile: DatasetProfile
