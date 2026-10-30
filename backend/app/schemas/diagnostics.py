"""Read-only evidence for explaining held-out generalisation outcomes."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.common import Schema
from app.schemas.modeling import PredictionMetrics


class SignalSummary(Schema):
    mean: float | None = None
    std: float | None = None
    minimum: float | None = None
    maximum: float | None = None


class ExcitationDiagnostics(Schema):
    rank: int | None = None
    n_parameters: int | None = None
    condition_number: float | None = None
    persistent_excitation_order: dict[str, int] = Field(default_factory=dict)
    required_excitation_order: dict[str, int] = Field(default_factory=dict)


class PartitionDiagnostics(Schema):
    start_index: int = Field(ge=0)
    end_index: int = Field(ge=0)
    sample_count: int = Field(ge=0)
    signals: dict[str, SignalSummary] = Field(default_factory=dict)
    input_activity: dict[str, float | None] = Field(default_factory=dict)
    output_activity: float | None = None
    excitation: ExcitationDiagnostics | None = None
    one_step: PredictionMetrics | None = None
    free_run: PredictionMetrics | None = None
    residual_whiteness_ratio: float | None = None


class DelayPartitionDiagnostics(Schema):
    peak_lag: int | None = Field(default=None, ge=0)
    peak_correlation: float | None = None
    prewhitening_order: int | None = Field(default=None, ge=0)


class SelectionCoverageDiagnostics(Schema):
    train_end_index: int = Field(ge=0)
    selected_sample_count: int = Field(ge=0)
    first_selected_index: int | None = Field(default=None, ge=0)
    last_selected_index: int | None = Field(default=None, ge=0)
    selected_span_ratio: float | None = None


class StabilityDiagnostics(Schema):
    stable: bool
    max_pole_modulus: float | None = None


class GeneralizationDiagnosticsData(Schema):
    """A replay of the fixed winner; it never creates trials or changes a study."""

    study_id: UUID
    dataset_id: UUID | None = None
    version_id: UUID
    metric_semantics: dict[str, str] = Field(default_factory=dict)
    partitions: dict[str, PartitionDiagnostics] = Field(default_factory=dict)
    delay_peaks: dict[str, dict[str, DelayPartitionDiagnostics]] = Field(default_factory=dict)
    selection_coverage: SelectionCoverageDiagnostics
    stability: StabilityDiagnostics
    generalization_risk: Literal["unavailable", "normal", "attention", "high"]
    diagnostic_messages: list[str] = Field(default_factory=list)
