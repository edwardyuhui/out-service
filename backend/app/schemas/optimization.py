from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.common import Schema, TaskResource
from app.schemas.modeling import ModelValidationData, PredictionMetrics


class OptimizationStartRequest(Schema):
    version_id: UUID
    input_columns: list[str] = Field(min_length=1)
    output_column: str = Field(min_length=1)
    max_trials: int = Field(default=50, ge=1, le=10_000)
    timeout_seconds: int | None = Field(default=None, ge=1, le=86_400)
    search_space: dict[str, Any] = Field(default_factory=dict)
    random_seed: int = Field(default=42, ge=0, le=2_147_483_647)
    train_ratio: float = Field(default=0.6, gt=0, lt=1)
    validation_ratio: float = Field(default=0.2, gt=0, lt=1)
    history_guard: int = Field(default=32, ge=0)
    diagnose_feedback: bool = True
    rolling_folds: int = Field(default=3, ge=1, le=5)
    structure_shortlist: int = Field(default=6, ge=1, le=20)
    optimization_policy: Literal["established", "paired_coverage", "disturbance_aware", "validation_guarded"] = "established"

    @model_validator(mode="after")
    def validate_time_split(self) -> "OptimizationStartRequest":
        if self.train_ratio + self.validation_ratio >= 1:
            raise ValueError("train_ratio 与 validation_ratio 之和必须小于 1。")
        return self


class OptimizationStartData(Schema):
    study_id: UUID
    task: TaskResource


class OptimizationObjectiveSemantics(Schema):
    """Authoritative meaning of the score stored in ``value``/``best_value``."""

    name: Literal["composite_identification_score"] = "composite_identification_score"
    version: Literal["v1", "v2", "v3", "v4"] = "v1"
    direction: Literal["maximize"] = "maximize"


class OptimizationObjectiveComponents(Schema):
    """Raw inputs and weighted terms from the existing composite objective."""

    validation_free_run_fit: float | None = None
    validation_free_run_fit_component: float | None = None
    normalized_error: float | None = None
    normalized_error_component: float | None = None
    residual_whiteness_ratio: float | None = None
    residual_whiteness_component: float | None = None
    parameter_count: int | None = Field(default=None, ge=1)
    complexity: float | None = None
    complexity_component: float | None = None
    stability_gate: bool
    final_score: float | None = None
    latest_validation_score: float | None = None
    rolling_mean_score: float | None = None
    rolling_adjustment_component: float | None = None
    temporal_variability_component: float | None = None


class OptimizationSelectionProvenance(Schema):
    """Compact, replayable evidence for the rows selected by one trial."""

    candidate_count: int = Field(ge=0)
    gated_count: int = Field(ge=0)
    selected_segment_count: int = Field(ge=0)
    selected_sample_count: int = Field(ge=0)
    selected_indices_hash: str = Field(min_length=64, max_length=64)
    coverage_ratio: float | None = None
    gating_rejection_counts: dict[str, int] = Field(default_factory=dict)
    excitation_satisfied: bool | None = None
    persistent_excitation_order: dict[str, int] = Field(default_factory=dict)
    required_excitation_order: dict[str, int] = Field(default_factory=dict)
    condition_number: float | None = None
    model_count: int = 1
    criterion: str = "regularized_logdet"
    training_policy: Literal["selected", "full_train"] = "selected"
    temporal_coverage_bins: int = 0
    covered_temporal_bins: int = 0


class OptimizationValidationFeedback(Schema):
    """Validation-only evidence already computed while evaluating one candidate."""

    partition: Literal["validation"] = "validation"
    one_step: PredictionMetrics
    free_run: PredictionMetrics
    summary: ModelValidationData


OptimizationDiagnosisCode = Literal[
    "UNSTABLE_MODEL",
    "FREE_RUN_UNDEFINED",
    "INSUFFICIENT_EXCITATION",
]


class OptimizationDiagnosis(Schema):
    policy_version: str
    codes: list[OptimizationDiagnosisCode] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)


class OptimizationRejectionProvenance(Schema):
    rejected_structure_count: int = Field(ge=1)
    reason_counts: dict[OptimizationDiagnosisCode, int] = Field(default_factory=dict)
    examples: list[dict[str, Any]] = Field(default_factory=list)


OptimizationTrialDecision = Literal[
    "CANDIDATE_VALID_NEW_BEST",
    "CANDIDATE_VALID_NOT_BEST",
]


class OptimizationTrialBookkeeping(Schema):
    previous_best: float | None = None
    absolute_improvement: float | None = None
    best_so_far: float | None = None
    decision: OptimizationTrialDecision | None = None


OptimizationConvergenceStatus = Literal[
    "INSUFFICIENT_EVIDENCE",
    "NOT_CONVERGED",
    "CONVERGED",
]


class OptimizationConvergence(Schema):
    policy_version: Literal["optimization_convergence_v1"]
    mode: Literal["observed_only"]
    status: OptimizationConvergenceStatus
    no_improvement_streak: int = Field(ge=0)
    patience: Literal[16]
    min_meaningful_improvement: Literal[0.001]
    min_valid_trials: Literal[17]
    valid_trial_count: int = Field(ge=0)
    last_meaningful_improvement_trial: int | None = Field(default=None, ge=0)
    best_trial_number: int | None = Field(default=None, ge=0)
    observed_at_trial_count: int = Field(ge=0)


OptimizationStopReasonCode = Literal[
    "TRIAL_BUDGET_EXHAUSTED",
    "TIMEOUT_REACHED",
]

OptimizationStopReasonOutcome = Literal[
    "WINNER_SELECTED",
    "NO_VALID_CANDIDATE",
]


class OptimizationStopReason(Schema):
    policy_version: Literal["optimization_stop_reason_v1"]
    code: OptimizationStopReasonCode
    category: Literal["NORMAL_LIMIT"]
    outcome: OptimizationStopReasonOutcome
    observed_trial_count: int = Field(ge=0)
    target_trial_count: int = Field(ge=1)
    timeout_seconds: int | None = Field(default=None, ge=1)


OptimizationStudyStatus = Literal["queued", "running", "succeeded", "failed"]
OptimizationExecutionMode = Literal["rq", "inline_http", "inline_agent", "legacy_unknown"]
OptimizationJobAvailability = Literal[
    "AVAILABLE",
    "NOT_FOUND",
    "UNAVAILABLE",
    "IDENTITY_MISMATCH",
    "NOT_APPLICABLE",
    "LEGACY",
]
OptimizationRqJobStatus = Literal[
    "created",
    "queued",
    "finished",
    "failed",
    "started",
    "deferred",
    "scheduled",
    "stopped",
    "canceled",
]
OptimizationTerminalReasonCodeV1 = Literal["COMPLETED", "NO_VALID_CANDIDATE", "FAILED"]
OptimizationTerminalReasonCategoryV1 = Literal[
    "SUCCESS",
    "BUSINESS_FAILURE",
    "SYSTEM_FAILURE",
]
OptimizationTerminalPhaseV1 = Literal[
    "preparation",
    "baseline",
    "search",
    "winner_persistence",
    "study_persistence",
]


class OptimizationTerminalReasonV1(Schema):
    """Historical terminal contract retained verbatim for persisted v1 studies."""

    policy_version: Literal["optimization_terminal_reason_v1"]
    code: OptimizationTerminalReasonCodeV1
    category: OptimizationTerminalReasonCategoryV1
    phase: OptimizationTerminalPhaseV1
    error_code: str | None = None
    recorded_at: datetime


OptimizationTerminalReasonCodeV2 = Literal[
    "COMPLETED",
    "NO_VALID_CANDIDATE",
    "FAILED",
    "RQ_TIMEOUT",
    "WORKER_CRASH",
]
OptimizationTerminalReasonCategoryV2 = Literal[
    "SUCCESS",
    "BUSINESS_FAILURE",
    "SYSTEM_FAILURE",
    "INFRASTRUCTURE_FAILURE",
]
OptimizationTerminalPhaseV2 = Literal[
    "preparation",
    "baseline",
    "search",
    "winner_persistence",
    "study_persistence",
    "queue_submission",
    "rq_execution",
]


class OptimizationTerminalReasonV2(Schema):
    """Authoritative terminal outcome, including proven RQ infrastructure loss."""

    policy_version: Literal["optimization_terminal_reason_v2"]
    code: OptimizationTerminalReasonCodeV2
    category: OptimizationTerminalReasonCategoryV2
    phase: OptimizationTerminalPhaseV2
    error_code: str | None = None
    recorded_at: datetime


OptimizationTerminalReason = Annotated[
    OptimizationTerminalReasonV1 | OptimizationTerminalReasonV2,
    Field(discriminator="policy_version"),
]

# New writers use v2 names. The v1 aliases above remain explicit so historical payloads
# continue to validate without reinterpretation.
OptimizationTerminalReasonCode = OptimizationTerminalReasonCodeV2
OptimizationTerminalReasonCategory = OptimizationTerminalReasonCategoryV2
OptimizationTerminalPhase = OptimizationTerminalPhaseV2


class OptimizationJobObservation(Schema):
    """Read-only projection of the RQ execution associated with one study."""

    execution_mode: OptimizationExecutionMode
    availability: OptimizationJobAvailability
    rq_job_id: str | None = None
    queue_name: str | None = None
    raw_status: OptimizationRqJobStatus | None = None
    observed_at: datetime
    created_at: datetime | None = None
    enqueued_at: datetime | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    error_code: str | None = None


class OptimizationTrial(Schema):
    trial_id: int = Field(ge=0)
    state: Literal["queued", "running", "complete", "pruned", "failed"]
    value: float | None = None
    params: dict[str, Any]
    metrics: dict[str, Any] = Field(default_factory=dict)
    selection_provenance: OptimizationSelectionProvenance | None = None
    validation_feedback: OptimizationValidationFeedback | None = None
    objective_semantics: OptimizationObjectiveSemantics | None = None
    objective_components: OptimizationObjectiveComponents | None = None
    diagnosis_policy_version: str | None = None
    diagnosis_codes: list[OptimizationDiagnosisCode] | None = None
    diagnosis_evidence: dict[str, Any] | None = None
    rejection_provenance: OptimizationRejectionProvenance | None = None
    bookkeeping: OptimizationTrialBookkeeping | None = None
    created_at: datetime
    finished_at: datetime | None = None
    error_code: str | None = None


class BaselineEvaluation(Schema):
    status: Literal["succeeded", "failed"]
    parameters: dict[str, Any] = Field(default_factory=dict)
    validation_free_run_fit: float | None = None
    test_free_run_fit: float | None = None
    test_mae: float | None = None
    test_rmse: float | None = None
    test_r2: float | None = None
    # Deprecated aliases above are one-step diagnostics. Use explicit fields below.
    test_one_step_fit: float | None = None
    test_one_step_mae: float | None = None
    test_one_step_rmse: float | None = None
    test_one_step_r2: float | None = None
    test_free_run_mae: float | None = None
    test_free_run_rmse: float | None = None
    test_free_run_r2: float | None = None
    generalization_gap: float | None = None
    duration_ms: float | None = None
    processing_run_id: UUID | None = None
    error_code: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class FinalTestEvaluation(Schema):
    status: Literal["succeeded", "failed"]
    best_trial_number: int | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    validation_free_run_fit: float | None = None
    test_free_run_fit: float | None = None
    test_mae: float | None = None
    test_rmse: float | None = None
    test_r2: float | None = None
    # Deprecated aliases above are one-step diagnostics. Use explicit fields below.
    test_one_step_fit: float | None = None
    test_one_step_mae: float | None = None
    test_one_step_rmse: float | None = None
    test_one_step_r2: float | None = None
    test_free_run_mae: float | None = None
    test_free_run_rmse: float | None = None
    test_free_run_r2: float | None = None
    generalization_gap: float | None = None
    duration_ms: float | None = None
    processing_run_id: UUID | None = None
    error_code: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class OptimizationStatusData(Schema):
    study_id: UUID
    study_status: OptimizationStudyStatus
    task: TaskResource
    trials: list[OptimizationTrial]
    best_trial_id: int | None = None
    best_value: float | None = None
    best_curve: list[float | None]
    param_importances: dict[str, float]
    # Cache-hit rate, trial counts and timings — the phase-8 acceptance evidence.
    statistics: dict[str, Any] = Field(default_factory=dict)
    best_params: dict[str, Any] = Field(default_factory=dict)
    baseline_model_id: UUID | None = None
    optimized_model_id: UUID | None = None
    # Set when this study reused parameters learned from a different dataset.
    warm_started_from: UUID | None = None
    baseline: BaselineEvaluation | None = None
    final_test_evaluation: FinalTestEvaluation | None = None
    objective_semantics: OptimizationObjectiveSemantics | None = None
    best_validation_feedback: OptimizationValidationFeedback | None = None
    best_selection_summary: OptimizationSelectionProvenance | None = None
    best_objective_components: OptimizationObjectiveComponents | None = None
    convergence: OptimizationConvergence | None = None
    stop_reason: OptimizationStopReason | None = None
    terminal_reason: OptimizationTerminalReason | None = None
    job: OptimizationJobObservation | None = None
