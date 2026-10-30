"""Schemas for provenance-bound reports and optimised-dataset delivery."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.common import Schema, TaskResource


class ReportRequest(Schema):
    execution_id: UUID | None = None
    dataset_id: UUID | None = None
    version_id: UUID | None = None
    study_id: UUID | None = None
    title: str = Field(default="IndusOpt 建模数据优选与辨识报告", min_length=1, max_length=200)


class ReportSection(Schema):
    key: str
    title: str
    body: str


class ReportBinding(Schema):
    """One bound report value and the typed evidence record it was read from."""

    placeholder: str
    kind: str
    run_id: str
    path: str
    value: str
    resolved: bool


class ReportChart(Schema):
    """One self-contained SVG chart backed by a single persisted run."""

    key: str
    title: str
    svg: str
    source_run_id: str
    source_path: str
    description: str


class ReportData(Schema):
    report_id: UUID
    execution_id: UUID | None = None
    dataset_id: UUID | None = None
    task: TaskResource
    title: str
    markdown: str
    html: str
    sections: list[ReportSection]
    charts: list[ReportChart] = Field(default_factory=list)
    # Every rendered numeric binding appears here with its source kind, handle and field path.
    bindings: list[ReportBinding] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    fully_resolved: bool = True
    artifact_uri: str | None = None
    html_artifact_uri: str | None = None
    cited_runs: list[str] = Field(default_factory=list)
    # "llm" means a model wrote the closing commentary and it passed the numeral check;
    # "template" means it was unavailable, or its draft was rejected for writing digits.
    narration_source: str = "template"
    llm_provider: str = "none"
    llm_model: str = "none"
    llm_fallback_reason: str | None = None
    llm_rejected_attempts: int = Field(default=0, ge=0)


class ExportDatasetRequest(Schema):
    version_id: UUID
    dataset_id: UUID | None = None
    input_columns: list[str] = Field(default_factory=list)
    output_column: str | None = None
    # Explicit rows to export. When empty the latest selection run's rows are used.
    sample_indices: list[int] = Field(default_factory=list)
    mode: Literal["standard", "optimization_best"] = "standard"
    study_id: UUID | None = None


class ExportSelectionProvenance(Schema):
    """Server-verified lineage for an Optuna Best Trial dataset export."""

    selection_source: Literal["optimization_best_trial"] = "optimization_best_trial"
    study_id: UUID
    best_trial_number: int = Field(ge=0)
    best_trial_id: UUID | None = None
    optimized_model_id: UUID
    model_processing_run_id: UUID | None = None
    study_finished_at: datetime | None = None


class DeliveryStudyOption(Schema):
    """A successful Study whose Best result is safe for strict delivery."""

    study_id: UUID
    dataset_id: UUID
    version_id: UUID
    finished_at: datetime
    best_trial_number: int = Field(ge=0)
    best_value: float
    optimized_model_id: UUID
    input_columns: list[str]
    output_column: str


class DeliveryStudyListData(Schema):
    dataset_id: UUID
    version_id: UUID
    items: list[DeliveryStudyOption] = Field(default_factory=list)


class ExportDatasetData(Schema):
    export_id: UUID
    dataset_id: UUID | None = None
    version_id: UUID
    task: TaskResource
    csv_uri: str
    manifest_uri: str
    exported_rows: int = Field(ge=0)
    source_rows: int = Field(ge=0)
    coverage_ratio: float
    columns: list[str] = Field(default_factory=list)
