"""Closed-loop preprocessing and structure search (phase 8).

The loop the brief asks for: pick preprocessing parameters, run the real pipeline, identify
a model, feed the identification metric back, and repeat until the best strategy is found.

Three things make it practical rather than merely correct:

* **The objective is a composite identification score** led by validation free-run FIT,
  with bounded validation-error, residual-whiteness and complexity terms plus a stability
  gate. Test data never contributes to the score.
* **Lineage-as-cache.** Consecutive trials usually change only model orders while the
  gating and selection parameters stay put; those stages are memoised by content-addressed
  key, so the expensive part runs once per distinct head configuration.
* **Strategy memory.** A finished study is stored against a profile fingerprint, and a new
  study on similar data enqueues those parameters as its first trials.

Test data never enters the objective. The best configuration is frozen first and persisted as
a formal model without opening the held-out Test split.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import numpy as np
import optuna
from algorithms.identifiability.delay import prewhitened_cross_correlation, rank_candidates
from algorithms.identifiability.regressor import ArxStructure, IdentifiabilityError, build_regressor
from algorithms.pipeline.cache import LineageCache, canonical_json, stage_key
from algorithms.pipeline.fingerprint import (
    ProfileFingerprint,
    build_fingerprint,
    fingerprint_distance,
)
from optuna.samplers import TPESampler
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.models.dataset import ProcessingRun
from app.models.operation_log import OperationLog
from app.models.optimization import OptimizationStudy, OptimizationTrialRecord, StrategyMemory
from app.schemas.common import ErrorDetail, TaskProgress, TaskResource
from app.schemas.modeling import ArxFitData, ArxFitRequest
from app.schemas.optimization import (
    BaselineEvaluation,
    FinalTestEvaluation,
    OptimizationJobObservation,
    OptimizationStartData,
    OptimizationStartRequest,
    OptimizationStatusData,
    OptimizationTerminalPhase,
    OptimizationTerminalReasonCategory,
    OptimizationTerminalReasonCode,
    OptimizationTerminalReasonV2,
    OptimizationTrial,
)
from app.schemas.preprocessing import SegmentRequest
from app.services.evaluation_policy import DEFAULT_BASELINE_CONFIG
from app.services.job_queue import (
    JOB_TIMEOUT_SECONDS,
    QUEUE_NAME,
    JobObservation,
    RqTerminalEvidence,
    background_optimization_enabled,
    observe_optimization_job,
    reconcile_optimization_job,
    submit_optimization,
)
from app.services.modeling_service import (
    ArxCoreResult,
    ModelingDomainError,
    fit_arx_core,
    fit_arx_on_version,
    to_validation_data,
)
from app.services.optimization_feedback_policy import (
    DIAGNOSIS_POLICY_VERSION,
    BestSoFarState,
    CandidateRejectionEvidence,
    advance_trial_bookkeeping,
    determine_normal_stop_reason,
    diagnose_validation_candidate,
    observe_convergence,
    rejection_from_objective,
    rejection_provenance,
)
from app.services.segment_service import (
    SegmentDomainError,
    SegmentSelectionOutcome,
    run_segment_selection,
)
from app.services.version_data import (
    VersionDataError,
    VersionSeries,
    attach_model_input_context,
    load_version_series,
    model_input_arrays,
)

TOOL_VERSION = "4.4.1"
# A study is only warm-started from memory entries at least this similar. Beyond it the
# stored parameters describe a different kind of process and would waste trials.
WARM_START_MAX_DISTANCE = 0.35
WARM_START_LIMIT = 3
# Quantisation of the gating thresholds in the search space. See _suggest() for why.
THRESHOLD_STEP = 0.02
OBJECTIVE_SEMANTICS = {
    "name": "composite_identification_score",
    "version": "v4",
    "direction": "maximize",
}
TERMINAL_REASON_POLICY_VERSION = "optimization_terminal_reason_v2"
_TERMINAL_REASON_CATEGORY: dict[
    OptimizationTerminalReasonCode, OptimizationTerminalReasonCategory
] = {
    "COMPLETED": "SUCCESS",
    "NO_VALID_CANDIDATE": "BUSINESS_FAILURE",
    "FAILED": "SYSTEM_FAILURE",
    "RQ_TIMEOUT": "INFRASTRUCTURE_FAILURE",
    "WORKER_CRASH": "INFRASTRUCTURE_FAILURE",
}
_TERMINAL_REASON_STATUS = {
    "COMPLETED": "succeeded",
    "NO_VALID_CANDIDATE": "failed",
    "FAILED": "failed",
    "RQ_TIMEOUT": "failed",
    "WORKER_CRASH": "failed",
}
# The formal baseline remains OLS when the selected design is identifiable.  Sparse,
# heterogeneous excitation can make that exact selected matrix rank deficient even though
# the closed-loop search still has viable Ridge candidates.  Use the same conservative
# Ridge value already present in the structure grid, and record the fallback in provenance.
BASELINE_RIDGE_FALLBACK_ALPHA = 0.1
# Bounds the gating ranges so that low/high are both multiples of THRESHOLD_STEP.
_GATING_BOUNDS = {
    "max_anomaly_ratio": (0.02, 0.30),
    "max_missing_ratio": (0.02, 0.40),
    "min_input_activity_ratio": (0.02, 0.30),
}

optuna.logging.set_verbosity(optuna.logging.WARNING)


class OptimizationDomainError(Exception):
    """A client-safe optimisation failure for the standard error envelope."""

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


@dataclass
class TrialOutcome:
    """One evaluated configuration and everything worth persisting about it."""

    number: int
    state: str
    value: float | None
    params: dict[str, Any]
    metrics: dict[str, Any]
    cache_hit: bool
    duration_ms: float
    error_code: str | None = None


@dataclass
class StudyOutcome:
    """The finished search: trials, winner, and how much work the cache saved."""

    study_id: UUID
    trials: list[TrialOutcome]
    best_number: int | None
    best_value: float | None
    best_params: dict[str, Any]
    best_metrics: dict[str, Any]
    fingerprint: ProfileFingerprint
    statistics: dict[str, Any]
    warm_started_from: UUID | None = None
    warm_start_params: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class EvaluationOutcome:
    """One persisted non-Optuna evaluation run."""

    status: str
    parameters: dict[str, Any]
    validation_free_run_fit: float | None
    test_free_run_fit: float | None
    test_mae: float | None
    test_rmse: float | None
    test_r2: float | None
    test_one_step_fit: float | None
    test_free_run_mae: float | None
    test_free_run_rmse: float | None
    test_free_run_r2: float | None
    generalization_gap: float | None
    duration_ms: float
    started_at: datetime
    finished_at: datetime
    error_code: str | None = None
    best_trial_number: int | None = None


@dataclass(frozen=True)
class OptimizationStudyExecution:
    """One completed formal study, including the runs needed by an Agent step."""

    study_id: UUID
    source_version_id: UUID
    statistics: dict[str, Any]
    best_params: dict[str, Any]
    best_value: float | None
    best_metrics: dict[str, Any]
    baseline_processing_run_id: UUID
    optimized_model_id: UUID | None
    optimized_model_processing_run_id: UUID | None


@dataclass(frozen=True)
class AgentOptimizationStudyResult:
    """The compact, provenance-complete result of the Agent-only inline entry."""

    study_id: UUID
    status: str
    source_version_id: UUID
    baseline_model_id: UUID
    optimized_model_id: UUID
    best_params: dict[str, Any]
    best_value: float | None
    objective_semantics: dict[str, Any]
    best_validation_feedback: dict[str, Any]
    best_selection_summary: dict[str, Any]
    best_objective_components: dict[str, Any]
    best_bookkeeping: dict[str, Any]
    convergence: dict[str, Any]
    stop_reason: dict[str, Any]
    processing_run_ids: list[str]
    best_diagnosis: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None


def objective_value(result: ArxCoreResult) -> tuple[float, dict[str, Any]]:
    """Score a candidate model the way an APC engineer would rank it.

    Weights follow ALG-0.2 §7.1. Every term is bounded so a single pathological trial
    cannot dominate the search, and an unstable model is rejected outright rather than
    ranked, because no amount of fit makes an unstable model deployable.
    """

    free_run = result.metrics.val_free_run_fit
    if free_run is None or not np.isfinite(free_run):
        return float("-inf"), {
            "reason": "free_run_undefined",
            "objective_semantics": dict(OBJECTIVE_SEMANTICS),
            "objective_components": {
                "stability_gate": result.validation.stable,
                "final_score": None,
            },
        }
    if not result.validation.stable:
        return float("-inf"), {
            "reason": "unstable",
            "objective_semantics": dict(OBJECTIVE_SEMANTICS),
            "objective_components": {
                "validation_free_run_fit": float(free_run),
                "stability_gate": False,
                "final_score": None,
            },
        }

    nrmse = result.validation.free_run_rmse
    spread = result.training_output_scale
    if not np.isfinite(nrmse) or not np.isfinite(spread) or spread <= 0:
        return float("-inf"), {"reason": "output_scale_undefined", "objective_semantics": dict(OBJECTIVE_SEMANTICS)}
    normalised_error = nrmse / spread
    whiteness = result.validation.residual_whiteness_ratio
    whiteness = 0.0 if whiteness is None or not np.isfinite(whiteness) else whiteness
    effective_parameters = result.preprocessing.get("effective_parameters", result.structure.parameter_count)
    initialization_parameters = result.preprocessing.get("initialization_parameters", 0)
    complexity = (float(effective_parameters if isinstance(effective_parameters, (int, float)) else result.structure.parameter_count)
        + float(initialization_parameters if isinstance(initialization_parameters, (int, float)) else 0)) / 40.0

    free_run_component = 0.45 * float(np.clip(free_run / 100.0, -1.0, 1.0))
    normalized_error_component = -0.20 * float(max(normalised_error, 0.0))
    whiteness_component = -0.10 * (1.0 - float(np.clip(whiteness, 0.0, 1.0))) if result.structure.na > 0 else 0.0
    complexity_component = -0.10 * float(np.clip(complexity, 0.0, 1.0))
    value = (
        free_run_component
        + normalized_error_component
        + whiteness_component
        + complexity_component
    )
    breakdown = {
        "val_free_run_fit": float(free_run),
        "val_one_step_fit": result.metrics.val_fit,
        "residual_whiteness_ratio": whiteness,
        "complexity": complexity,
        "stable": result.validation.stable,
        "max_pole_modulus": result.validation.max_pole_modulus,
        "training_rows": result.training_rows,
        "objective_semantics": dict(OBJECTIVE_SEMANTICS),
        "objective_components": {
            "validation_free_run_fit": float(free_run),
            "validation_free_run_fit_component": free_run_component,
            "normalized_error": float(normalised_error),
            "normalized_error_component": normalized_error_component,
            "residual_whiteness_ratio": float(whiteness),
            "residual_whiteness_component": whiteness_component,
            "parameter_count": result.structure.parameter_count,
            "complexity": float(complexity),
            "complexity_component": complexity_component,
            "stability_gate": True,
            "final_score": float(value),
        },
    }
    return float(value), breakdown


@dataclass(frozen=True)
class FullTrainSelection:
    """Actual finite regressor rows used by the all-Train companion; no quality gate."""

    selected_sample_indices: list[int]
    sample_weights: dict[int, float] = field(default_factory=dict)


def replay_training_selection(
    series: VersionSeries, parameters: dict[str, Any], input_columns: list[str],
    output_column: str, *, train_ratio: float,
) -> SegmentSelectionOutcome | FullTrainSelection:
    """Resolve the winning data policy identically for search, persistence and export."""
    if parameters.get("training_policy", "selected") != "full_train":
        return run_segment_selection(series, SegmentRequest(version_id=series.version_id,
            **_selection_params(parameters, input_columns, output_column, train_ratio=train_ratio)))
    structure = ArxStructure.create(na=int(parameters["na"]), nb=int(parameters["nb"]),
        nk=_trial_delays(parameters, input_columns), input_columns=input_columns)
    guard = max(structure.max_history, int(parameters.get("history_guard", 32)))
    try:
        regressor = build_regressor(inputs={c: series.values[c] for c in input_columns},
            output=series.values[output_column], structure=structure,
            stop=int(series.n_samples * train_ratio) - guard)
    except IdentifiabilityError as error:
        raise ModelingDomainError(error.code, error.message, details=error.details) from error
    return FullTrainSelection([int(i) for i in regressor.time_indices])


def _selection_provenance(outcome: SegmentSelectionOutcome | FullTrainSelection) -> dict[str, Any]:
    selected_indices = list(outcome.selected_sample_indices)
    indices_hash = hashlib.sha256(canonical_json(selected_indices).encode("utf-8")).hexdigest()
    if isinstance(outcome, FullTrainSelection):
        return {"training_policy": "full_train", "candidate_count": 0, "gated_count": 0,
            "selected_segment_count": 0, "selected_sample_count": len(selected_indices),
            "selected_indices_hash": indices_hash, "coverage_ratio": 1.0,
            "gating_rejection_counts": {}, "excitation_satisfied": None,
            "persistent_excitation_order": {}, "required_excitation_order": {},
            "condition_number": None, "model_count": 1, "criterion": "all_finite_train_rows"}
    excitation = outcome.selection.excitation
    condition_number = excitation.condition_number
    coverage = outcome.selection.coverage_ratio
    return {
        "candidate_count": len(outcome.gating.windows),
        "gated_count": outcome.gating.accepted_count,
        "selected_segment_count": len(outcome.selection.selected),
        "selected_sample_count": len(selected_indices),
        "selected_indices_hash": indices_hash,
        "training_policy": "selected",
        "temporal_coverage_bins": outcome.temporal_coverage_bins,
        "covered_temporal_bins": len({min(outcome.temporal_coverage_bins - 1,
            int((i - outcome.regressor.time_indices[0]) * outcome.temporal_coverage_bins /
                max(1, outcome.regressor.time_indices[-1] - outcome.regressor.time_indices[0] + 1)))
            for i in selected_indices}) if outcome.temporal_coverage_bins else 0,
        "coverage_ratio": float(coverage) if np.isfinite(coverage) else None,
        "gating_rejection_counts": dict(outcome.gating.rejection_counts),
        "excitation_satisfied": excitation.excitation_satisfied,
        "persistent_excitation_order": dict(excitation.persistent_excitation_order),
        "required_excitation_order": dict(excitation.required_excitation_order),
        "condition_number": (
            float(condition_number) if np.isfinite(condition_number) else None
        ),
        "model_count": outcome.selection.model_count,
        "criterion": outcome.selection.criterion,
    }


def _validation_feedback(result: ArxCoreResult) -> dict[str, Any]:
    return {
        "partition": "validation",
        "one_step": result.metrics.one_step["validation"].model_dump(mode="json"),
        "free_run": result.metrics.free_run["validation"].model_dump(mode="json"),
        "summary": to_validation_data(
            result.validation, result.excitation_shortfall
        ).model_dump(mode="json"),
    }


def _annotate_trial_bookkeeping(trials: list[TrialOutcome]) -> TrialOutcome | None:
    state = BestSoFarState()
    trials_by_number: dict[int, TrialOutcome] = {}
    for trial in sorted(trials, key=lambda item: item.number):
        state, bookkeeping = advance_trial_bookkeeping(
            state,
            trial_number=trial.number,
            trial_state=trial.state,
            objective_score=trial.value,
        )
        trial.metrics["bookkeeping"] = bookkeeping.to_payload()
        trials_by_number[trial.number] = trial
    if state.winner_trial_number is None:
        return None
    return trials_by_number[state.winner_trial_number]


def run_baseline(
    series: VersionSeries,
    payload: OptimizationStartRequest,
    *,
    input_columns: list[str],
    output_column: str,
) -> EvaluationOutcome:
    """Run the deterministic pre-Optuna baseline through the formal pipeline."""

    started_at = datetime.now(UTC)
    started = time.perf_counter()
    parameters = DEFAULT_BASELINE_CONFIG.to_payload(
        input_columns=input_columns,
        train_ratio=payload.train_ratio,
        validation_ratio=payload.validation_ratio,
    )
    try:
        selection = run_segment_selection(
            series,
            SegmentRequest(
                version_id=series.version_id,
                input_columns=input_columns,
                output_column=output_column,
                window_size=DEFAULT_BASELINE_CONFIG.window_size,
                max_segments=DEFAULT_BASELINE_CONFIG.max_segments,
                min_segment_length=DEFAULT_BASELINE_CONFIG.min_segment_length,
                max_missing_ratio=DEFAULT_BASELINE_CONFIG.max_missing_ratio,
                max_anomaly_ratio=DEFAULT_BASELINE_CONFIG.max_anomaly_ratio,
                min_input_activity_ratio=DEFAULT_BASELINE_CONFIG.min_input_activity_ratio,
                na=DEFAULT_BASELINE_CONFIG.selection_na,
                nb=DEFAULT_BASELINE_CONFIG.selection_nb,
                nk=DEFAULT_BASELINE_CONFIG.selection_nk,
                train_ratio=payload.train_ratio,
                history_guard=payload.history_guard,
            ),
        )
        def fit(*, estimator: str, ridge_alpha: float | None) -> ArxCoreResult:
            return fit_arx_core(
                inputs={column: series.values[column] for column in input_columns},
                output=series.values[output_column],
                payload=ArxFitRequest(
                    version_id=series.version_id,
                    input_columns=input_columns,
                    output_column=output_column,
                    na=DEFAULT_BASELINE_CONFIG.na,
                    nb={column: DEFAULT_BASELINE_CONFIG.nb for column in input_columns},
                    delays={column: DEFAULT_BASELINE_CONFIG.nk for column in input_columns},
                    estimator=estimator,
                    ridge_alpha=ridge_alpha,
                    train_ratio=payload.train_ratio,
                    validation_ratio=payload.validation_ratio,
                    training_sample_indices=selection.selected_sample_indices,
                    sample_weights=selection.sample_weights,
                    history_guard=payload.history_guard,
                    evaluate_test=False,
                ),
                input_columns=input_columns,
            )

        try:
            result = fit(
                estimator=DEFAULT_BASELINE_CONFIG.estimator,
                ridge_alpha=DEFAULT_BASELINE_CONFIG.ridge_alpha,
            )
        except ModelingDomainError as error:
            if (
                error.code != "DESIGN_MATRIX_RANK_DEFICIENT"
                or DEFAULT_BASELINE_CONFIG.estimator != "ols"
            ):
                raise
            parameters.update(
                {
                    "estimator": "ridge",
                    "ridge_alpha": BASELINE_RIDGE_FALLBACK_ALPHA,
                    "fallback_reason": error.code,
                }
            )
            result = fit(estimator="ridge", ridge_alpha=BASELINE_RIDGE_FALLBACK_ALPHA)
        evaluation = _evaluation_from_result(
            result,
            parameters=parameters,
            started_at=started_at,
            started=started,
            require_test=False,
        )
        validation_objective, _ = objective_value(result)
        if not np.isfinite(validation_objective):
            evaluation.status = "failed"
            evaluation.error_code = "BASELINE_VALIDATION_REJECTED"
        return evaluation
    except (SegmentDomainError, ModelingDomainError) as error:
        return _failed_evaluation(
            parameters=parameters,
            started_at=started_at,
            started=started,
            error_code=error.code,
        )



async def _persist_optimized_model(
    session: AsyncSession,
    *,
    series: VersionSeries,
    payload: OptimizationStartRequest,
    outcome: StudyOutcome,
    input_columns: list[str],
    output_column: str,
    artifact_root: Path,
) -> ArxFitData:
    """Persist the validation-selected winner without evaluating the held-out Test split."""

    if outcome.best_number is None or not outcome.best_params:
        raise OptimizationDomainError(
            "BEST_TRIAL_UNAVAILABLE", "寻优未产生可持久化的 Best Trial。", status_code=409
        )

    parameters = dict(outcome.best_params)
    try:
        selection = replay_training_selection(series, parameters, input_columns,
            output_column, train_ratio=payload.train_ratio)
        formal_payload = ArxFitRequest(
            version_id=series.version_id,
            input_columns=input_columns,
            output_column=output_column,
            na=int(parameters["na"]),
            nb={column: int(parameters["nb"]) for column in input_columns},
            delays=_trial_delays(parameters, input_columns),
            model_type=parameters.get("model_type", "ARX"),
            regularization_kernel=parameters.get("regularization_kernel", "identity"),
            kernel_decay=parameters.get("kernel_decay", 0.9),
            initialization_policy=parameters.get("initialization_policy", "fixed"),
            initialization_window=parameters.get("initialization_window", 32),
            estimator=parameters["estimator"],
            ridge_alpha=parameters.get("ridge_alpha"),
            train_ratio=payload.train_ratio,
            validation_ratio=payload.validation_ratio,
            training_sample_indices=selection.selected_sample_indices,
            sample_weights=selection.sample_weights,
            history_guard=int(parameters.get("history_guard", payload.history_guard)),
            evaluate_test=False,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise OptimizationDomainError(
            "BEST_TRIAL_PERSISTENCE_FAILED", "Best Trial 参数无法重放为正式 ARX 模型。"
        ) from error
    except SegmentDomainError as error:
        raise OptimizationDomainError(
            error.code, error.message, status_code=error.status_code, details=error.details
        ) from error

    return await fit_arx_on_version(session, payload=formal_payload, artifact_root=artifact_root)

def evaluate_best_trial(
    series: VersionSeries,
    payload: OptimizationStartRequest,
    outcome: StudyOutcome,
    *,
    input_columns: list[str],
    output_column: str,
) -> EvaluationOutcome:
    """Evaluate the validation-selected winner once on the held-out test tail."""

    started_at = datetime.now(UTC)
    started = time.perf_counter()
    parameters = dict(outcome.best_params)
    try:
        selection = replay_training_selection(series, parameters, input_columns,
            output_column, train_ratio=payload.train_ratio)
        result = fit_arx_core(
            inputs={column: series.values[column] for column in input_columns},
            output=series.values[output_column],
            payload=ArxFitRequest(
                version_id=series.version_id,
                input_columns=input_columns,
                output_column=output_column,
                na=int(parameters["na"]),
                nb={column: int(parameters["nb"]) for column in input_columns},
                delays=_trial_delays(parameters, input_columns),
                model_type=parameters.get("model_type", "ARX"),
                regularization_kernel=parameters.get("regularization_kernel", "identity"),
                kernel_decay=parameters.get("kernel_decay", 0.9),
                initialization_policy=parameters.get("initialization_policy", "fixed"),
                initialization_window=parameters.get("initialization_window", 32),
                estimator=parameters["estimator"],
                ridge_alpha=parameters.get("ridge_alpha"),
                train_ratio=payload.train_ratio,
                validation_ratio=payload.validation_ratio,
                training_sample_indices=selection.selected_sample_indices,
                sample_weights=selection.sample_weights,
                history_guard=int(parameters.get("history_guard", payload.history_guard)),
                evaluate_test=True,
            ),
            input_columns=input_columns,
        )
        evaluation = _evaluation_from_result(
            result,
            parameters=parameters,
            started_at=started_at,
            started=started,
            best_trial_number=outcome.best_number,
        )
        validation_fit = outcome.best_metrics.get("val_free_run_fit")
        if isinstance(validation_fit, (int, float)) and evaluation.test_free_run_fit is not None:
            evaluation.validation_free_run_fit = float(validation_fit)
            evaluation.generalization_gap = float(validation_fit) - evaluation.test_free_run_fit
        return evaluation
    except (KeyError, SegmentDomainError, ModelingDomainError) as error:
        return _failed_evaluation(
            parameters=parameters,
            started_at=started_at,
            started=started,
            error_code=error.code if isinstance(error, (SegmentDomainError, ModelingDomainError)) else "BEST_TRIAL_REPLAY_FAILED",
            best_trial_number=outcome.best_number,
        )


def _evaluation_from_result(
    result: ArxCoreResult,
    *,
    parameters: dict[str, Any],
    started_at: datetime,
    started: float,
    best_trial_number: int | None = None,
    require_test: bool = True,
) -> EvaluationOutcome:
    one_step = result.metrics.one_step.get("test") if require_test else None
    free_run = result.metrics.free_run.get("test") if require_test else None
    test_fit = free_run.fit if free_run is not None else None
    validation_fit = result.metrics.val_free_run_fit
    error_code = None
    if validation_fit is None or (require_test and test_fit is None):
        error_code = "EVALUATION_METRIC_UNAVAILABLE"
    finished_at = datetime.now(UTC)
    return EvaluationOutcome(
        status="failed" if error_code else "succeeded",
        parameters=parameters,
        validation_free_run_fit=validation_fit,
        test_free_run_fit=test_fit,
        test_mae=one_step.mae if one_step is not None else None,
        test_rmse=one_step.rmse if one_step is not None else None,
        test_r2=one_step.r2 if one_step is not None else None,
        test_one_step_fit=one_step.fit if one_step is not None else None,
        test_free_run_mae=free_run.mae if free_run is not None else None,
        test_free_run_rmse=free_run.rmse if free_run is not None else None,
        test_free_run_r2=free_run.r2 if free_run is not None else None,
        generalization_gap=(validation_fit - test_fit)
        if validation_fit is not None and test_fit is not None
        else None,
        duration_ms=(time.perf_counter() - started) * 1000.0,
        started_at=started_at,
        finished_at=finished_at,
        error_code=error_code,
        best_trial_number=best_trial_number,
    )


def _failed_evaluation(
    *,
    parameters: dict[str, Any],
    started_at: datetime,
    started: float,
    error_code: str,
    best_trial_number: int | None = None,
) -> EvaluationOutcome:
    return EvaluationOutcome(
        status="failed",
        parameters=parameters,
        validation_free_run_fit=None,
        test_free_run_fit=None,
        test_mae=None,
        test_rmse=None,
        test_r2=None,
        test_one_step_fit=None,
        test_free_run_mae=None,
        test_free_run_rmse=None,
        test_free_run_r2=None,
        generalization_gap=None,
        duration_ms=(time.perf_counter() - started) * 1000.0,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        error_code=error_code,
        best_trial_number=best_trial_number,
    )


def run_study(
    series: VersionSeries,
    payload: OptimizationStartRequest,
    *,
    input_columns: list[str],
    output_column: str,
    warm_start: list[dict[str, Any]] | None = None,
    warm_start_source: UUID | None = None,
    study_id: UUID | None = None,
) -> StudyOutcome:
    """Execute the closed loop synchronously and return everything it learned.

    ``study_id`` is supplied when the caller already reserved a row for this study, which
    both the API and the worker do so that ``/status`` answers before the search finishes.
    Left unset it allocates its own, which is what the offline experiment scripts want.
    """

    guarded = payload.optimization_policy == "validation_guarded"
    structures = _structure_grid({"arx_disturbance": payload.optimization_policy == "disturbance_aware",
                                  "all_arx_disturbance": guarded})
    _, delay_high = _bounds_int(payload.search_space.get("nk", (0, 20)))
    common_history = max([payload.history_guard] + [max(item["na"], item["nb"] + delay_high - 1) for item in structures])
    payload = payload.model_copy(update={"history_guard": common_history})
    inputs = model_input_arrays(series, input_columns)
    output = series.values[output_column]
    train_stop = int(series.n_samples * payload.train_ratio) - payload.history_guard
    if guarded and series.timestamps:
        if len(series.timestamps) != series.n_samples:
            raise OptimizationDomainError("INVALID_DATASET_SCHEMA", "时间轴长度与样本数不一致")
        _require_uniform_train_timestamps(series.timestamps[:train_stop])
    fingerprint = build_fingerprint(inputs={c: v[:train_stop] for c, v in inputs.items()}, output=output[:train_stop])
    cache = LineageCache()
    trials: list[TrialOutcome] = []
    base_key = stage_key(
        parent_key=str(series.version_id),
        tool_name="load_version",
        tool_version=TOOL_VERSION,
        parameters={"inputs": sorted(input_columns), "output": output_column},
    )

    structure_evaluations = 0
    feedback_scheduled = 0
    feedback_budget = payload.max_trials // 4 if guarded else 0
    fold_specs = _rolling_fold_specs(series.n_samples, payload)
    # Data-dependent candidate generation sees only the earliest fold's Train.
    delay_payload = payload.model_copy(update={"train_ratio": fold_specs[0][0] / series.n_samples})
    delay_options = _delay_options(series, delay_payload, input_columns, output_column)

    def schedule_feedback(feedback: dict[str, Any], trial: optuna.Trial) -> None:
        nonlocal feedback_scheduled
        if not guarded:
            if payload.diagnose_feedback and feedback.get("parameters") and trial.number % 3 == 0:
                study.enqueue_trial(feedback["parameters"], skip_if_exists=True)
            return
        status = ("disabled" if not payload.diagnose_feedback else
                  "no_parameter_action" if not feedback.get("parameters") else
                  "budget_exhausted" if feedback_scheduled >= feedback_budget else
                  "reserve_search_budget" if trial.number % 4 != 2 or trial.number >= payload.max_trials-1 else
                  "scheduled")
        feedback["scheduling"] = {"policy_version": "reserved_feedback_budget_v1",
            "status": status, "max_feedback_trials": feedback_budget,
            "test_partition_used": False}
        if status == "scheduled":
            study.enqueue_trial(feedback["parameters"], skip_if_exists=True)
            feedback_scheduled += 1

    def evaluate(trial: optuna.Trial) -> float:
        nonlocal structure_evaluations
        started = time.perf_counter()
        sampled_params = _suggest(trial, payload.search_space)
        sampled_params["selection_mode"] = trial.suggest_categorical("selection_mode", ["single", "ensemble"])
        sampled_params["adaptive_windows"] = trial.suggest_categorical("adaptive_windows", [False, True])
        sampled_params["temporal_coverage_bins"] = (trial.suggest_categorical("temporal_coverage_bins", [0, 3])
            if payload.optimization_policy in {"paired_coverage", "validation_guarded"} else 0)
        sampled_params["history_guard"] = payload.history_guard
        sampled_params["delays"] = {c: trial.suggest_categorical(f"nk_{c}", options) for c, options in delay_options.items()}
        params = dict(sampled_params)
        metrics: dict[str, Any] = {
            "objective_semantics": dict(OBJECTIVE_SEMANTICS),
            "diagnosis_policy_version": DIAGNOSIS_POLICY_VERSION,
            "diagnosis_codes": [], "diagnosis_evidence": {},
        }
        if guarded:
            metrics["sampling_validation"] = {"partition": "train", "status": "passed" if series.timestamps else "unavailable",
                                               "automatic_resampling": False}
        cache_hit = False
        selection_outcome = None
        last_error: SegmentDomainError | ModelingDomainError | None = None
        rejections: list[CandidateRejectionEvidence] = []
        policy_winners: dict[str, tuple[float, ArxCoreResult, dict[str, Any], dict[str, Any],
            SegmentSelectionOutcome | FullTrainSelection]] = {}
        feedback_candidate: tuple[float, ArxCoreResult] | None = None

        def reject_quality(candidate_params: dict[str, Any], evidence: list[dict[str, Any]],
                           acceptance: dict[str, Any]) -> None:
            acceptance = _validation_acceptance(evidence)
            rejected = metrics.setdefault("validation_rejections", {"count": 0, "reason_counts": {}, "examples": []})
            rejected["count"] += 1
            for reason in acceptance["reasons"]:
                counts = rejected["reason_counts"]
                counts[reason] = counts.get(reason, 0) + 1
            skipped = len(fold_specs)-len(evidence)
            rejected["skipped_requested_fold_fits"] = rejected.get("skipped_requested_fold_fits", 0)+skipped
            if len(rejected["examples"]) < 3:
                rejected["examples"].append({"parameters": candidate_params, "acceptance": acceptance,
                    "folds": evidence, "requested_folds": len(fold_specs), "unevaluated_folds": skipped})

        def selected_data(source: VersionSeries, ratio: float, val_end: int | None = None) -> SegmentSelectionOutcome:
            sp = _selection_params(sampled_params, input_columns, output_column, train_ratio=ratio)
            key = stage_key(parent_key=base_key, tool_name="segment_selection", tool_version=TOOL_VERSION,
                parameters={**sp, "validation_end": val_end})
            def compute() -> SegmentSelectionOutcome:
                return run_segment_selection(source, SegmentRequest(version_id=series.version_id, **sp))
            nonlocal cache_hit
            selection, hit = cache.get_or_compute(key, compute)
            cache_hit = cache_hit or hit
            return selection

        try:
            selection_outcome = selected_data(series, payload.train_ratio)
        except SegmentDomainError as error:
            # A gate rejection must not prevent evaluating the all-Train companion.
            metrics["selection_failure"] = {"code": error.code, "details": error.details}
            last_error = error

        policies = (("full_train", "selected") if payload.optimization_policy in {"paired_coverage", "validation_guarded"}
            else ("selected",) if selection_outcome is not None else ("full_train",))
        for policy in policies:
            if policy == "selected" and selection_outcome is None:
                continue
            screened = []
            for structure in structures:
                candidate_params = {**sampled_params, **structure, "training_policy": policy}
                if candidate_params["estimator"] == "ols":
                    candidate_params.pop("ridge_alpha", None)
                try:
                    training = selection_outcome if policy == "selected" else replay_training_selection(
                        series, candidate_params, input_columns, output_column, train_ratio=payload.train_ratio)
                    assert training is not None
                    fit_request = ArxFitRequest(version_id=series.version_id,
                        input_columns=input_columns, output_column=output_column,
                        na=structure["na"], nb={c: structure["nb"] for c in input_columns},
                        delays=_trial_delays(candidate_params, input_columns),
                        model_type=structure.get("model_type", "ARX"),
                        regularization_kernel=structure.get("regularization_kernel", "identity"),
                        kernel_decay=structure.get("kernel_decay", .9),
                        initialization_policy=structure.get("initialization_policy", "fixed"),
                        initialization_window=structure.get("initialization_window", 32),
                        estimator=structure["estimator"], ridge_alpha=structure.get("ridge_alpha"),
                        train_ratio=payload.train_ratio, validation_ratio=payload.validation_ratio,
                        training_sample_indices=training.selected_sample_indices,
                        sample_weights=training.sample_weights, history_guard=payload.history_guard, evaluate_test=False)
                    candidate = fit_arx_core(inputs=inputs, output=output, payload=fit_request, input_columns=input_columns)
                except ModelingDomainError as error:
                    last_error = error
                    continue
                structure_evaluations += 1
                score, breakdown = objective_value(candidate)
                if not np.isfinite(score):
                    rejection = rejection_from_objective(reason=breakdown.get("reason"), structure=candidate_params,
                        stable=candidate.validation.stable, max_pole_modulus=candidate.validation.max_pole_modulus,
                        free_run_fit=candidate.metrics.val_free_run_fit)
                    if rejection is not None:
                        rejections.append(rejection)
                    continue
                if feedback_candidate is None or score > feedback_candidate[0]:
                    feedback_candidate = (score, candidate)
                if guarded:
                    latest_evidence = [_fold_evidence(candidate, *fold_specs[-1], payload.history_guard, training)]
                    acceptance = _validation_acceptance(latest_evidence)
                    if acceptance["status"] != "passed":
                        reject_quality(candidate_params, latest_evidence, acceptance)
                        continue
                screened.append((score, candidate, candidate_params, breakdown, fit_request, training))
            ranked = sorted(screened, key=lambda item: item[0], reverse=True)
            # Each data policy gets its own shortlist; good selected candidates cannot
            # screen every full-data structure out before rolling validation.
            shortlist = ranked if guarded else ranked[:payload.structure_shortlist]
            for family in ("ARX", "FIR"):
                representative = next((item for item in ranked if item[2].get("model_type", "ARX") == family), None)
                if representative is not None and all(item is not representative for item in shortlist):
                    shortlist.append(representative)
            for latest_score, candidate, candidate_params, breakdown, fit_request, training in shortlist:
                scores, evidence = [], []
                rejected_early = False
                for train_end, val_end in fold_specs[:-1]:
                    prefix = replace(series, timestamps=series.timestamps[:val_end + 1],
                        values={c: v[:val_end + 1] for c, v in series.values.items()})
                    ratio = (train_end + .25) / prefix.n_samples
                    try:
                        folded_training = selected_data(prefix, ratio, val_end) if policy == "selected" else replay_training_selection(
                            prefix, candidate_params, input_columns, output_column, train_ratio=ratio)
                        folded_request = fit_request.model_copy(update={"train_ratio": ratio,
                            "validation_ratio": (val_end - train_end) / prefix.n_samples,
                            "training_sample_indices": folded_training.selected_sample_indices,
                            "sample_weights": folded_training.sample_weights})
                        folded = fit_arx_core(inputs={c: prefix.values[c] for c in inputs},
                            output=prefix.values[output_column], payload=folded_request, input_columns=input_columns)
                        structure_evaluations += 1
                        score, _ = objective_value(folded)
                        if not np.isfinite(score):
                            break
                    except (SegmentDomainError, ModelingDomainError) as error:
                        last_error = error
                        break
                    scores.append(score)
                    evidence.append(_fold_evidence(folded, train_end, val_end, payload.history_guard, folded_training))
                    if guarded:
                        acceptance = _validation_acceptance(evidence[-1:])
                        if acceptance["status"] != "passed":
                            reject_quality(candidate_params,
                                [*evidence, _fold_evidence(candidate, *fold_specs[-1], payload.history_guard, training)],
                                acceptance)
                            rejected_early = True
                            break
                if rejected_early:
                    continue
                if len(scores) != len(fold_specs) - 1:
                    continue
                scores.append(latest_score)
                evidence.append(_fold_evidence(candidate, *fold_specs[-1], payload.history_guard, training))
                if guarded:
                    acceptance = _validation_acceptance(evidence)
                    if acceptance["status"] != "passed":
                        reject_quality(candidate_params, evidence, acceptance)
                        continue
                penalty = .25 * float(np.std(scores))
                rolling_score = float(np.mean(scores)) - penalty
                previous = policy_winners.get(policy)
                if previous is not None and rolling_score <= previous[0]:
                    continue
                breakdown = dict(breakdown)
                breakdown["objective_components"] = {**breakdown["objective_components"],
                    "latest_validation_score": latest_score, "rolling_mean_score": float(np.mean(scores)),
                    "rolling_adjustment_component": float(np.mean(scores)) - latest_score,
                    "temporal_variability_component": -penalty, "final_score": rolling_score}
                breakdown["rolling_validation"] = {"policy_version": "expanding_temporal_full_guard_v2" if guarded else "expanding_temporal_shortlist_v1",
                    "partition": "development", "requested_folds": payload.rolling_folds,
                    "effective_folds": len(scores), "screening_partition": "all_validation_folds" if guarded else "latest_validation",
                    "shortlist_size": len(shortlist), "folds_overlap": True, "independent_test": False,
                    "mean_score": float(np.mean(scores)), "score_std": float(np.std(scores)),
                    "variability_penalty": penalty, "final_score": rolling_score, "folds": evidence}
                policy_winners[policy] = (rolling_score, candidate, candidate_params, breakdown, training)

        rejected = rejection_provenance(rejections)
        if rejected is not None:
            metrics["rejection_provenance"] = rejected
        if not policy_winners:
            if guarded and feedback_candidate is not None and selection_outcome is not None:
                feedback = _feedback_actions(feedback_candidate[1], selection_outcome,
                    sampled_params, payload.search_space, advanced=True)
                feedback["candidate_accepted"] = False
                metrics["adaptive_feedback"] = feedback
                schedule_feedback(feedback, trial)
            metrics.update(diagnose_validation_candidate(validation_feedback=None,
                selection_provenance=None, objective_components=None,
                candidate_rejections=rejections).to_metrics())
            error_code = ("VALIDATION_QUALITY_REJECTED" if guarded and metrics.get("validation_rejections") else
                rejections[0].code.value if rejections else
                last_error.code if last_error is not None else "NUMERICAL_INSTABILITY")
            trials.append(TrialOutcome(number=trial.number, state="failed", value=None, params=params,
                metrics=metrics, cache_hit=cache_hit, duration_ms=(time.perf_counter() - started) * 1000,
                error_code=error_code))
            raise optuna.TrialPruned()

        # Exact score ties prefer full Train. The pairing holds delays, model grid and
        # fold boundaries fixed; Test contributes neither to ranking nor acceptance.
        value, result, params, breakdown, training = max(policy_winners.values(), key=lambda item: item[0])
        metrics.update(breakdown)
        metrics["selection_provenance"] = _selection_provenance(training)
        metrics["data_policy_comparison"] = {"policy_version": "paired_train_policy_v1",
            "search_policy": payload.optimization_policy,
            "partition": "validation", "selected_policy": params["training_policy"],
            "same_delays": True, "same_structure_grid": True, "same_fold_boundaries": True,
            "policies": {policy: {"rolling_score": item[0],
                "latest_rmse": item[1].validation.free_run_rmse,
                "training_rows": item[1].training_rows,
                "parameters": item[2]} for policy, item in policy_winners.items()}}
        metrics["validation_acceptance"] = _validation_acceptance(breakdown["rolling_validation"]["folds"])
        metrics["validation_feedback"] = _validation_feedback(result)
        metrics.update(diagnose_validation_candidate(validation_feedback=metrics["validation_feedback"],
            selection_provenance=metrics["selection_provenance"],
            objective_components=metrics.get("objective_components")).to_metrics())
        feedback: dict[str, Any] = _feedback_actions(result, selection_outcome, sampled_params, payload.search_space, advanced=guarded) if selection_outcome is not None else {
            "policy_version": "validation_actions_v2", "partition": "validation", "reasons": [], "parameters": {}}
        metrics["adaptive_feedback"] = feedback
        schedule_feedback(feedback, trial)
        trials.append(TrialOutcome(number=trial.number, state="complete", value=value, params=params,
            metrics=metrics, cache_hit=cache_hit, duration_ms=(time.perf_counter() - started) * 1000))
        return value

    study = optuna.create_study(
        direction="maximize",
        sampler=TPESampler(seed=payload.random_seed),
    )
    if payload.optimization_policy in {"paired_coverage", "validation_guarded"}:
        study.enqueue_trial({f"nk_{c}": options[len(options) // 2] for c, options in delay_options.items()})
    for candidate in (warm_start or [])[:WARM_START_LIMIT]:
        enqueued = _sanitise_warm_start(candidate)
        if enqueued:
            study.enqueue_trial(enqueued)
    study.optimize(
        evaluate,
        n_trials=payload.max_trials,
        timeout=payload.timeout_seconds,
        catch=(),
    )

    completed = [trial for trial in trials if trial.state == "complete"]
    best = _annotate_trial_bookkeeping(trials)
    convergence = observe_convergence(
        [
            (trial.number, trial.metrics["bookkeeping"])
            for trial in sorted(trials, key=lambda item: item.number)
        ],
        best_trial_number=best.number if best else None,
    )
    stop_reason = determine_normal_stop_reason(
        observed_trial_count=len(trials),
        target_trial_count=payload.max_trials,
        timeout_seconds=payload.timeout_seconds,
        best_trial_number=best.number if best else None,
    )
    selection_computations = cache.misses
    statistics = {
        **cache.statistics(),
        "total_trials": len(trials),
        "completed_trials": len(completed),
        "failed_trials": sum(1 for trial in trials if trial.state == "failed"),
        "pruned_trials": sum(1 for trial in trials if trial.state == "pruned"),
        "mean_trial_ms": float(np.mean([trial.duration_ms for trial in trials])) if trials else 0.0,
        "warm_start_trials": len(warm_start or []),
        "structure_evaluations": structure_evaluations,
        "selection_computations": selection_computations,
        # How many model fits each computed selection served. A flat search would run one
        # selection per fit, so this is the factor by which the staged design plus the
        # lineage cache reduce the expensive stage.
        "evaluations_per_selection": (
            structure_evaluations / selection_computations if selection_computations else 0.0
        ),
        "convergence": convergence.to_payload(),
        "stop_reason": stop_reason.to_payload(),
    }
    if guarded:
        statistics["feedback_scheduling"] = {"policy_version": "reserved_feedback_budget_v1",
            "max_feedback_trials": feedback_budget, "scheduled_proposals": feedback_scheduled,
            "minimum_search_trials_before_first_proposal": 3, "test_partition_used": False}
    return StudyOutcome(
        study_id=study_id or uuid4(),
        trials=trials,
        best_number=best.number if best else None,
        best_value=best.value if best else None,
        best_params=best.params if best else {},
        best_metrics=best.metrics if best else {},
        fingerprint=fingerprint,
        statistics=statistics,
        warm_started_from=warm_start_source,
        warm_start_params=list(warm_start or []),
    )


async def start_optimization_study(
    session: AsyncSession,
    *,
    payload: OptimizationStartRequest,
    artifact_root: Path,
) -> OptimizationStartData:
    """Allocate the study, then either hand it to a worker or run it here.

    The study row is written as ``queued`` *before* anything long starts, so ``/status``
    answers immediately in both paths and the client never holds a study id that the
    database has not heard of.

    Queueing is best-effort by design (see ``job_queue``): if Redis or the worker is not
    there, the study runs inline and the returned message says which path was taken. What
    it never does is report success for work that was dropped.
    """

    # Fail fast on a bad version before allocating anything, so a typo does not leave a
    # queued study behind that no worker can ever complete.
    try:
        await load_version_series(
            session, version_id=payload.version_id, artifact_root=artifact_root
        )
    except VersionDataError as error:
        raise OptimizationDomainError(
            error.code, error.message, status_code=error.status_code, details=error.details
        ) from error

    study_id = uuid4()
    rq_enabled = background_optimization_enabled()
    await _reserve_study(
        session,
        study_id=study_id,
        payload=payload,
        job=_study_job_contract(
            study_id=study_id,
            execution_mode="rq" if rq_enabled else "inline_http",
            submission_state=(
                "SUBMISSION_REQUESTED" if rq_enabled else "CONFIRMED_NOT_ENQUEUED"
            ),
        ),
    )

    submission = submit_optimization(study_id, payload.model_dump(mode="json"))
    if submission.queued:
        study = await session.get(OptimizationStudy, study_id)
        assert study is not None
        observation = _schema_job_observation(
            execution_mode="rq",
            observation=submission.observation,
        )
        return OptimizationStartData(
            study_id=study_id,
            task=_optimization_task(
                study=study,
                job=observation,
                message=(
                    f"闭环寻优已提交后台执行（作业 {submission.job_id}），请轮询研究状态。"
                ),
            ),
        )

    if not submission.allows_inline:
        await _update_study_job_contract(
            session,
            study_id=study_id,
            submission_state=submission.outcome,
        )
        study = await session.get(OptimizationStudy, study_id)
        assert study is not None
        observation = _schema_job_observation(
            execution_mode="rq",
            observation=submission.observation,
        )
        return OptimizationStartData(
            study_id=study_id,
            task=_optimization_task(
                study=study,
                job=observation,
                message=submission.reason or "RQ 作业提交结果暂不可确认。",
            ),
        )

    await _update_study_job_contract(
        session,
        study_id=study_id,
        execution_mode="inline_http",
        submission_state="INLINE_FALLBACK",
        clear_rq_identity=True,
    )

    statistics = await execute_study(
        session, study_id=study_id, payload=payload, artifact_root=artifact_root
    )
    suffix = f"（{submission.reason}，已同步执行）" if submission.reason else ""
    study = await session.get(OptimizationStudy, study_id)
    assert study is not None
    observation = _schema_job_observation(execution_mode="inline_http", observation=None)
    return OptimizationStartData(
        study_id=study_id,
        task=_optimization_task(
            study=study,
            job=observation,
            message=(
                f"闭环寻优完成：{statistics['completed_trials']} 个有效试验，"
                f"缓存命中率 {statistics['hit_rate']:.0%}。{suffix}"
            ),
        ),
    )


async def execute_agent_optimization_study(
    session: AsyncSession,
    *,
    payload: OptimizationStartRequest,
    baseline_model_id: UUID,
    artifact_root: Path,
    study_id: UUID | None = None,
) -> AgentOptimizationStudyResult:
    """Run one Agent-authorized study inline, without historical warm starts or RQ."""

    study_id = study_id or uuid4()
    try:
        await _reserve_study(
            session,
            study_id=study_id,
            payload=payload,
            baseline_model_id=baseline_model_id,
            job=_study_job_contract(
                study_id=study_id,
                execution_mode="inline_agent",
                submission_state="CONFIRMED_NOT_ENQUEUED",
            ),
        )
        execution = await _execute_study(
            session,
            study_id=study_id,
            payload=payload,
            artifact_root=artifact_root,
            use_warm_start=False,
        )
    except OptimizationDomainError:
        raise
    except Exception as error:
        raise OptimizationDomainError(
            getattr(error, "code", "AGENT_OPTIMIZATION_STUDY_FAILED"),
            getattr(error, "message", "Agent 优化研究执行失败。"),
        ) from error

    study = await session.get(OptimizationStudy, study_id)
    if study is None:
        raise OptimizationDomainError(
            "OPTIMIZATION_STUDY_NOT_FOUND", "Agent 优化研究未能持久化。", status_code=500
        )
    if study.status != "succeeded":
        raise OptimizationDomainError(
            str(study.statistics.get("error_code", "OPTIMIZATION_STUDY_FAILED")),
            "Agent 优化研究未成功完成。",
        )
    if study.baseline_model_id != baseline_model_id:
        raise OptimizationDomainError(
            "OPTIMIZATION_BASELINE_MODEL_MISMATCH",
            "Agent 优化研究的基线模型血缘不一致。",
            status_code=500,
        )
    if (
        study.optimized_model_id is None
        or execution.optimized_model_id is None
        or execution.optimized_model_processing_run_id is None
        or study.optimized_model_id != execution.optimized_model_id
    ):
        raise OptimizationDomainError(
            "OPTIMIZED_MODEL_REQUIRED", "Agent 优化研究未产生正式优化模型。", status_code=500
        )
    convergence = study.statistics.get("convergence")
    if not isinstance(convergence, dict):
        raise OptimizationDomainError(
            "OPTIMIZATION_CONVERGENCE_REQUIRED",
            "Agent 优化研究缺少正式 observed convergence contract。",
            status_code=500,
        )
    stop_reason = study.statistics.get("stop_reason")
    if not isinstance(stop_reason, dict):
        raise OptimizationDomainError(
            "OPTIMIZATION_STOP_REASON_REQUIRED",
            "Agent 优化研究缺少正式 normal stop reason contract。",
            status_code=500,
        )

    return AgentOptimizationStudyResult(
        study_id=study.id,
        status=study.status,
        source_version_id=study.version_id,
        baseline_model_id=study.baseline_model_id,
        optimized_model_id=study.optimized_model_id,
        best_params=dict(study.best_params),
        best_value=study.best_value,
        objective_semantics=dict(execution.best_metrics.get("objective_semantics", {})),
        best_validation_feedback=dict(
            execution.best_metrics.get("validation_feedback", {})
        ),
        best_selection_summary=dict(
            execution.best_metrics.get("selection_provenance", {})
        ),
        best_objective_components=dict(
            execution.best_metrics.get("objective_components", {})
        ),
        best_bookkeeping={
            "trial_number": study.best_trial_number,
            **dict(execution.best_metrics.get("bookkeeping", {})),
        },
        convergence=dict(convergence),
        stop_reason=dict(stop_reason),
        processing_run_ids=[
            str(execution.baseline_processing_run_id),
            str(execution.optimized_model_processing_run_id),
        ],
        best_diagnosis=_diagnosis_payload(execution.best_metrics),
    )

async def execute_study(
    session: AsyncSession,
    *,
    study_id: UUID,
    payload: OptimizationStartRequest,
    artifact_root: Path,
    use_warm_start: bool = True,
) -> dict[str, Any]:
    """Run one reserved study and keep the standalone/worker return contract stable."""

    execution = await _execute_study(
        session,
        study_id=study_id,
        payload=payload,
        artifact_root=artifact_root,
        use_warm_start=use_warm_start,
    )
    return dict(execution.statistics)


async def _execute_study(
    session: AsyncSession,
    *,
    study_id: UUID,
    payload: OptimizationStartRequest,
    artifact_root: Path,
    use_warm_start: bool,
) -> OptimizationStudyExecution:
    """Run one reserved study to completion and persist it. Shared by API and worker.

    Both callers go through this function on purpose. A worker that computed something
    subtly different from the synchronous path would be worse than having no worker.
    """

    current_phase: OptimizationTerminalPhase = "preparation"
    try:
        try:
            series = await load_version_series(
                session, version_id=payload.version_id, artifact_root=artifact_root
            )
            input_columns, output_column = series.resolve_columns(
                input_columns=payload.input_columns, output_column=payload.output_column
            )
            series = await attach_model_input_context(session, series, artifact_root=artifact_root)
        except VersionDataError as error:
            raise OptimizationDomainError(
                error.code, error.message, status_code=error.status_code, details=error.details
            ) from error

        await _mark_study_running(session, study_id=study_id)

        current_phase = "baseline"
        baseline = run_baseline(
            series,
            payload,
            input_columns=input_columns,
            output_column=output_column,
        )
        baseline_processing_run_id = await _persist_evaluation(
            session,
            study_id=study_id,
            series=series,
            evaluation=baseline,
            kind="baseline",
        )
        recoverable_baseline_errors = {"NO_DYNAMIC_SEGMENT_FOUND", "BASELINE_VALIDATION_REJECTED",
            "DESIGN_MATRIX_RANK_DEFICIENT", "INSUFFICIENT_ROWS", "NUMERICAL_INSTABILITY"}
        if baseline.status != "succeeded" and baseline.error_code not in recoverable_baseline_errors:
            raise OptimizationDomainError(
                baseline.error_code or "BASELINE_EVALUATION_FAILED",
                "默认基线流程失败，未开始 Optuna 寻优。",
                details={"baseline": _evaluation_payload(baseline)},
            )

        current_phase = "preparation"
        fingerprint = build_fingerprint(
            inputs={column: series.values[column][:int(series.n_samples * payload.train_ratio) - payload.history_guard] for column in input_columns},
            output=series.values[output_column][:int(series.n_samples * payload.train_ratio) - payload.history_guard],
        )
        warm_start, source = (
            await _retrieve_warm_start(session, series=series, fingerprint=fingerprint)
            if use_warm_start
            else ([], None)
        )

        current_phase = "search"
        # run_study is a synchronous, CPU-bound Optuna loop (it never touches the
        # AsyncSession — see its signature above). Calling it inline here would block the
        # whole ASGI event loop for the duration of the search, freezing every other
        # request this process is serving (including unrelated users' health checks).
        # Both callers of _execute_study reach this line synchronously today (the inline
        # fallback when no RQ worker is available, and the Agent's direct optimize_pipeline
        # tool), so the thread hand-off has to live here rather than in each caller.
        outcome = await run_in_threadpool(
            run_study,
            series,
            payload,
            input_columns=input_columns,
            output_column=output_column,
            warm_start=warm_start,
            warm_start_source=source,
            study_id=study_id,
        )
        outcome.statistics["baseline_status"] = baseline.status
        outcome.statistics["baseline_error_code"] = baseline.error_code

        if outcome.best_number is None:
            current_phase = "study_persistence"
            await _persist_study(
                session,
                series=series,
                payload=payload,
                outcome=outcome,
                optimized_model_id=None,
                terminal_code="NO_VALID_CANDIDATE",
                terminal_phase="search",
            )
            return OptimizationStudyExecution(
                study_id=study_id,
                source_version_id=series.version_id,
                statistics=dict(outcome.statistics),
                best_params=dict(outcome.best_params),
                best_value=outcome.best_value,
                best_metrics=dict(outcome.best_metrics),
                baseline_processing_run_id=baseline_processing_run_id,
                optimized_model_id=None,
                optimized_model_processing_run_id=None,
            )

        current_phase = "winner_persistence"
        try:
            optimized = await _persist_optimized_model(
                session,
                series=series,
                payload=payload,
                outcome=outcome,
                input_columns=input_columns,
                output_column=output_column,
                artifact_root=artifact_root,
            )
        except Exception as error:
            error_code = _study_failure_error_code(error, phase=current_phase)
            await _persist_failed_outcome_best_effort(
                session,
                series=series,
                payload=payload,
                outcome=outcome,
                error=error,
                error_code=error_code,
            )
            if isinstance(error, OptimizationDomainError):
                raise
            if isinstance(error, ModelingDomainError):
                raise OptimizationDomainError(
                    error.code,
                    error.message,
                    status_code=error.status_code,
                    details=error.details,
                ) from error
            raise

        current_phase = "study_persistence"
        await _persist_study(
            session,
            series=series,
            payload=payload,
            outcome=outcome,
            optimized_model_id=optimized.model_id,
            terminal_code="COMPLETED",
            terminal_phase="study_persistence",
        )
        return OptimizationStudyExecution(
            study_id=study_id,
            source_version_id=series.version_id,
            statistics=dict(outcome.statistics),
            best_params=dict(outcome.best_params),
            best_value=outcome.best_value,
            best_metrics=dict(outcome.best_metrics),
            baseline_processing_run_id=baseline_processing_run_id,
            optimized_model_id=optimized.model_id,
            optimized_model_processing_run_id=optimized.processing_run_id,
        )
    except Exception as error:
        await _persist_study_failure_best_effort(
            session,
            study_id=study_id,
            phase=current_phase,
            error=error,
        )
        raise


async def get_optimization_status(
    session: AsyncSession, *, study_id: UUID
) -> OptimizationStatusData:
    """Return trials, the best value and the convergence curve for one study."""

    study = await session.get(OptimizationStudy, study_id)
    if study is None:
        raise OptimizationDomainError(
            "OPTIMIZATION_STUDY_NOT_FOUND", "寻优任务不存在。", status_code=404
        )
    job_observation, terminal_evidence = await _observe_study_job(
        study,
        allow_reconciliation=_study_allows_rq_reconciliation(study),
    )
    if terminal_evidence is not None:
        await persist_rq_terminal_evidence(
            session,
            study_id=study_id,
            evidence=terminal_evidence,
        )
    # The failure callback may have committed while registry cleanup ran in the threadpool.
    # Refresh before projecting PostgreSQL's authoritative lifecycle fact.
    await session.refresh(study)
    records = list(
        (
            await session.scalars(
                select(OptimizationTrialRecord)
                .where(OptimizationTrialRecord.study_id == study_id)
                .order_by(OptimizationTrialRecord.trial_number)
            )
        ).all()
    )
    best_record = next(
        (record for record in records if record.trial_number == study.best_trial_number),
        None,
    )
    best_metrics = dict(best_record.metrics) if best_record is not None else {}
    curve: list[float | None] = []
    curve_state = BestSoFarState()
    for record in records:
        curve_state, bookkeeping = advance_trial_bookkeeping(
            curve_state,
            trial_number=record.trial_number,
            trial_state=record.state,
            objective_score=record.value,
        )
        curve.append(bookkeeping.best_so_far)

    return OptimizationStatusData(
        study_id=study_id,
        study_status=study.status,
        task=_optimization_task(
            study=study,
            job=job_observation,
            message=f"研究状态：{study.status}。",
        ),
        trials=[
            OptimizationTrial(
                trial_id=record.trial_number,
                state=_trial_state(record.state),
                value=record.value,
                params=record.params,
                metrics=dict(record.metrics),
                selection_provenance=record.metrics.get("selection_provenance"),
                validation_feedback=record.metrics.get("validation_feedback"),
                objective_semantics=record.metrics.get("objective_semantics"),
                objective_components=record.metrics.get("objective_components"),
                diagnosis_policy_version=record.metrics.get("diagnosis_policy_version"),
                diagnosis_codes=record.metrics.get("diagnosis_codes"),
                diagnosis_evidence=record.metrics.get("diagnosis_evidence"),
                rejection_provenance=record.metrics.get("rejection_provenance"),
                bookkeeping=record.metrics.get("bookkeeping"),
                created_at=record.created_at,
                finished_at=record.finished_at,
                error_code=record.error_code,
            )
            for record in records
        ],
        best_trial_id=study.best_trial_number,
        best_value=study.best_value,
        best_curve=curve,
        param_importances=_param_importances(records),
        statistics=dict(study.statistics),
        best_params=dict(study.best_params),
        baseline_model_id=study.baseline_model_id,
        optimized_model_id=study.optimized_model_id,
        warm_started_from=study.warm_started_from,
        baseline=_stored_baseline(study.statistics),
        final_test_evaluation=_stored_final_evaluation(study.statistics),
        objective_semantics=study.statistics.get("objective_semantics"),
        best_validation_feedback=best_metrics.get("validation_feedback"),
        best_selection_summary=best_metrics.get("selection_provenance"),
        best_objective_components=best_metrics.get("objective_components"),
        convergence=study.statistics.get("convergence"),
        stop_reason=study.statistics.get("stop_reason"),
        terminal_reason=study.statistics.get("terminal_reason"),
        job=job_observation,
    )


async def _observe_study_job(
    study: OptimizationStudy, *, allow_reconciliation: bool
) -> tuple[OptimizationJobObservation, RqTerminalEvidence | None]:
    contract = study.statistics.get("job")
    if not isinstance(contract, dict):
        return (
            _schema_job_observation(execution_mode="legacy_unknown", observation=None),
            None,
        )

    execution_mode = contract.get("execution_mode")
    if execution_mode in {"inline_http", "inline_agent"}:
        return _schema_job_observation(execution_mode=execution_mode, observation=None), None
    if execution_mode != "rq":
        return (
            OptimizationJobObservation(
                execution_mode="legacy_unknown",
                availability="LEGACY",
                observed_at=datetime.now(UTC),
                error_code="OPTIMIZATION_JOB_CONTRACT_INVALID",
            ),
            None,
        )

    job_id = contract.get("rq_job_id")
    queue_name = contract.get("queue_name")
    if not isinstance(job_id, str) or not isinstance(queue_name, str):
        return (
            OptimizationJobObservation(
                execution_mode="rq",
                availability="IDENTITY_MISMATCH",
                rq_job_id=job_id if isinstance(job_id, str) else None,
                queue_name=queue_name if isinstance(queue_name, str) else None,
                observed_at=datetime.now(UTC),
                error_code="RQ_JOB_IDENTITY_MISMATCH",
            ),
            None,
        )

    if allow_reconciliation:
        timeout = contract.get("job_timeout_seconds")
        if not isinstance(timeout, int) or timeout <= 0:
            return (
                OptimizationJobObservation(
                    execution_mode="rq",
                    availability="IDENTITY_MISMATCH",
                    rq_job_id=job_id,
                    queue_name=queue_name,
                    observed_at=datetime.now(UTC),
                    error_code="RQ_JOB_IDENTITY_MISMATCH",
                ),
                None,
            )
        observation = await run_in_threadpool(
            reconcile_optimization_job,
            study_id=study.id,
            job_id=job_id,
            queue_name=queue_name,
            expected_timeout_seconds=timeout,
        )
    else:
        observation = await run_in_threadpool(
            observe_optimization_job,
            study_id=study.id,
            job_id=job_id,
            queue_name=queue_name,
        )
    return (
        _schema_job_observation(execution_mode="rq", observation=observation),
        observation.terminal_evidence,
    )


def _study_allows_rq_reconciliation(study: OptimizationStudy) -> bool:
    contract = study.statistics.get("job")
    if not isinstance(contract, dict) or contract.get("execution_mode") != "rq":
        return False
    existing = study.statistics.get("terminal_reason")
    if not isinstance(existing, dict):
        return study.status not in {"succeeded", "failed"}
    if existing.get("policy_version") != TERMINAL_REASON_POLICY_VERSION:
        return False
    return existing.get("code") == "FAILED"


def _schema_job_observation(
    *,
    execution_mode: str,
    observation: JobObservation | None,
) -> OptimizationJobObservation:
    if observation is None:
        availability = "LEGACY" if execution_mode == "legacy_unknown" else "NOT_APPLICABLE"
        return OptimizationJobObservation(
            execution_mode=execution_mode,
            availability=availability,
            observed_at=datetime.now(UTC),
        )
    return OptimizationJobObservation(
        execution_mode=execution_mode,
        availability=observation.availability,
        rq_job_id=observation.job_id,
        queue_name=observation.queue_name,
        raw_status=observation.raw_status,
        observed_at=datetime.now(UTC),
        created_at=observation.created_at,
        enqueued_at=observation.enqueued_at,
        started_at=observation.started_at,
        ended_at=observation.ended_at,
        error_code=observation.error_code,
    )


def _optimization_task(
    *,
    study: OptimizationStudy,
    job: OptimizationJobObservation,
    message: str,
) -> TaskResource:
    rq_status_map = {
        "created": "queued",
        "deferred": "queued",
        "scheduled": "queued",
        "queued": "queued",
        "started": "running",
        "finished": "succeeded",
        "failed": "failed",
        "stopped": "cancelled",
        "canceled": "cancelled",
    }
    task_status = (
        rq_status_map[job.raw_status]
        if job.availability == "AVAILABLE" and job.raw_status is not None
        else study.status
    )
    is_terminal = task_status in {"succeeded", "failed", "cancelled"}
    task_error: ErrorDetail | None = None
    if job.availability == "AVAILABLE" and job.raw_status == "failed":
        task_error = ErrorDetail(
            code="RQ_JOB_FAILED",
            message="RQ 后台作业执行失败。",
            details={"rq_status": job.raw_status},
        )
    elif job.availability in {"UNAVAILABLE", "IDENTITY_MISMATCH"}:
        task_error = ErrorDetail(
            code=job.error_code or "RQ_RECONCILIATION_UNAVAILABLE",
            message="当前无法确认 RQ 后台作业状态。",
            details={"availability": job.availability},
        )
    elif job.availability == "NOT_FOUND" and study.status not in {"succeeded", "failed"}:
        task_error = ErrorDetail(
            code="RQ_JOB_NOT_FOUND",
            message="未找到该 OptimizationStudy 对应的 RQ 作业。",
            details={},
        )
    elif job.availability != "AVAILABLE" and study.status == "failed":
        terminal_reason = study.statistics.get("terminal_reason")
        terminal = terminal_reason if isinstance(terminal_reason, dict) else {}
        task_error = ErrorDetail(
            code=str(terminal.get("error_code") or terminal.get("code") or "OPTIMIZATION_STUDY_FAILED"),
            message="OptimizationStudy 未成功完成。",
            details={},
        )

    if task_status == "queued":
        stage_message = "等待 RQ Worker 执行。" if job.execution_mode == "rq" else message
    elif task_status == "running":
        stage_message = "RQ 正在执行；Trial 明细将在正式持久化后可用。"
    else:
        stage_message = message

    return TaskResource(
        id=study.id,
        status=task_status,
        progress=TaskProgress(
            current=1 if is_terminal else 0,
            total=1,
            percent=100 if is_terminal else 0,
            stage="optimize_pipeline",
            message=stage_message,
        ),
        created_at=job.created_at or job.enqueued_at or study.created_at,
        started_at=job.started_at,
        finished_at=job.ended_at if job.availability == "AVAILABLE" else study.finished_at,
        error=task_error,
    )


def _trial_state(value: str) -> str:
    return value if value in {"queued", "running", "complete", "pruned", "failed"} else "complete"


def _diagnosis_payload(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "policy_version": metrics.get("diagnosis_policy_version"),
        "codes": list(metrics.get("diagnosis_codes", [])),
        "evidence": dict(metrics.get("diagnosis_evidence", {})),
    }


def _suggest(trial: optuna.Trial, overrides: dict[str, Any]) -> dict[str, Any]:
    """Search space with engineering bounds; every range is finite by design."""

    space = {
        "window_size": (30, 200),
        "max_segments": (3, 20),
        **_GATING_BOUNDS,
        "na": (1, 5),
        "nb": (1, 4),
        "nk": (0, 20),
        "ridge_alpha": (1e-4, 10.0),
        **overrides,
    }
    # The gating thresholds are quantised on purpose. A continuous suggestion gives every
    # trial a unique threshold like 0.2016644..., which makes the selection cache key
    # unique too — measured hit rate was exactly 0% before this, so the cache paid its
    # overhead and returned nothing. The distinction between a 20% and a 20.17% anomaly
    # limit is not one the process can act on, so quantising costs no fidelity and lets
    # trials that differ only in model structure reuse the selection they share.
    params: dict[str, Any] = {
        "window_size": trial.suggest_int(
            "window_size", *_bounds_int(space["window_size"]), step=10
        ),
        "max_segments": trial.suggest_int("max_segments", *_bounds_int(space["max_segments"])),
        "max_anomaly_ratio": trial.suggest_float(
            "max_anomaly_ratio", *_bounds_float(space["max_anomaly_ratio"]), step=THRESHOLD_STEP
        ),
        "max_missing_ratio": trial.suggest_float(
            "max_missing_ratio", *_bounds_float(space["max_missing_ratio"]), step=THRESHOLD_STEP
        ),
        "min_input_activity_ratio": trial.suggest_float(
            "min_input_activity_ratio",
            *_bounds_float(space["min_input_activity_ratio"]),
            step=THRESHOLD_STEP,
        ),
        # nk stays with the sampler: the pure delay is process-specific, its useful range
        # is wide, and it changes the regressor, so it does not belong in a fixed grid.
        "nk": trial.suggest_int("nk", *_bounds_int(space["nk"])),
    }
    return params


def _structure_grid(params: dict[str, Any]) -> list[dict[str, Any]]:
    """Model structures swept inside one trial, against a single selection.

    Keep 60 low-order candidates, add 18 high-order regularized ARX and 24 TC FIR
    candidates (12 fixed baseline, 12 with a causal initial output disturbance). The latest Validation screens the grid; rolling folds rank the shortlist.
    """

    grid: list[dict[str, Any]] = []
    for na in (1, 2, 3, 4):
        for nb in (1, 2, 3):
            grid.append({"na": na, "nb": nb, "estimator": "ols"})
            for alpha in (0.01, 0.1, 1.0):
                grid.append({"na": na, "nb": nb, "estimator": "ridge", "ridge_alpha": alpha})
            grid.append({"na": na, "nb": nb, "estimator": "huber", "ridge_alpha": 0.1})
    grid.extend({"model_type": "ARX", "na": na, "nb": nb, "estimator": "ridge", "ridge_alpha": alpha}
                for na, nb in ((4, 4), (8, 4), (8, 8), (12, 4), (12, 8), (12, 12))
                for alpha in (0.1, 1.0, 10.0))
    grid.extend({"model_type": "FIR", "na": 0, "nb": nb, "estimator": "ridge",
                 "regularization_kernel": "tc", "kernel_decay": decay, "ridge_alpha": alpha}
                for nb in (8, 16, 24) for decay in (0.8, 0.95) for alpha in (0.1, 10.0))
    grid.extend({**item, "initialization_policy": "past_residual", "initialization_window": 32}
                for item in list(grid) if item.get("model_type") == "FIR")
    if params.get("arx_disturbance") and not params.get("all_arx_disturbance"):
        # Add paired versions of the 18 regularized high-order ARX models. Keep
        # established search and its RNG unchanged; compensation must earn its
        # place on the same chronological validation folds.
        grid.extend({**item, "initialization_policy": "past_residual", "initialization_window": 32}
                    for item in list(grid) if item.get("model_type") == "ARX")
    if params.get("all_arx_disturbance"):
        # Low-order affine ARX also returns toward the source operating level.
        # Pair every fixed ARX with its causal disturbance version; validation,
        # rather than a model-order label, decides whether compensation helps.
        grid.extend({**item, "initialization_policy": "past_residual", "initialization_window": 32}
                    for item in list(grid) if item.get("model_type", "ARX") == "ARX"
                    and item.get("initialization_policy", "fixed") == "fixed")
    return grid


def _rolling_fold_specs(n: int, payload: OptimizationStartRequest) -> list[tuple[int, int]]:
    """Expanding Train, fixed-width Validation; every fold ends before held-out Test.

    Earlier validation windows overlap. They are robustness checks, not independent
    observations. Tiny datasets reduce the number of folds explicitly in evidence.
    """
    train_end = int(n * payload.train_ratio)
    val_end = int(n * (payload.train_ratio + payload.validation_ratio))
    width = val_end - train_end
    stride = max(1, width // 2)
    minimum_train = max(2 * payload.history_guard + 32, 64)
    folds = [(train_end - i * stride, val_end - i * stride)
             for i in reversed(range(payload.rolling_folds)) if train_end - i * stride >= minimum_train]
    return folds or [(train_end, val_end)]


def _fold_evidence(result: ArxCoreResult, train_end: int, val_end: int, guard: int,
                   selection: SegmentSelectionOutcome | FullTrainSelection) -> dict[str, Any]:
    return {"train_end": train_end, "validation_start": train_end + guard,
            "validation_stop": val_end - guard, "training_rows": result.training_rows,
            "validation_samples": result.validation.n_samples,
            "free_run_fit": result.validation.free_run_fit, "free_run_rmse": result.validation.free_run_rmse,
            "training_output_scale": result.training_output_scale,
            "persistence_rmse": result.validation.reference_baselines.get("persistence_rmse"),
            "skill_vs_persistence": result.validation.reference_baselines.get("skill_vs_persistence"),
            "input_support": result.validation.input_support,
            "normalized_error": result.validation.free_run_rmse / result.training_output_scale,
            "selected_indices_hash": _selection_provenance(selection)["selected_indices_hash"]}


def _bounds_int(value: Any) -> tuple[int, int]:
    low, high = value
    return int(low), int(high)


def _validation_acceptance(folds: list[dict[str, Any]]) -> dict[str, Any]:
    """Validation evidence, not an APC deployment certificate or official FIT threshold."""
    reasons = []
    fits = [fold.get("free_run_fit") for fold in folds]
    if any(fit is not None and np.isfinite(fit) and fit <= 0 for fit in fits):
        reasons.append("NONPOSITIVE_FREE_RUN_FIT")
    skills = [fold.get("skill_vs_persistence") for fold in folds]
    if any(skill is not None and np.isfinite(skill) and skill <= 0 for skill in skills):
        reasons.append("NOT_BETTER_THAN_PERSISTENCE")
    if any(fold.get("input_support", {}).get("status") == "unsupported" for fold in folds):
        reasons.append("UNEXCITED_CONTROL_CHANGED")
    missing = not folds or any(value is None or not np.isfinite(value) for value in [*fits, *skills])
    if missing:
        reasons.append("INCOMPLETE_VALIDATION_EVIDENCE")
    return {"policy_version": "validation_quality_v2", "partition": "validation",
        "status": "insufficient" if any(r != "INCOMPLETE_VALIDATION_EVIDENCE" for r in reasons) else "inconclusive" if missing else "passed",
        "reasons": reasons, "folds_checked": len(folds), "folds_overlap": True,
        "independent_test": False, "deployment_ready": False}


def _require_uniform_train_timestamps(timestamps: list[datetime]) -> None:
    """Guard discrete-time identification using Train metadata only; no resampling."""
    if len(timestamps) < 3:
        raise OptimizationDomainError("INSUFFICIENT_ROWS", "训练时间轴不足以验证采样间隔")
    intervals = np.asarray([(b-a).total_seconds() for a, b in zip(timestamps[:-1], timestamps[1:], strict=True)])
    positive = intervals[intervals > 0]
    expected = float(np.median(positive)) if positive.size else 0.
    bad = np.flatnonzero((intervals <= 0) | (np.abs(intervals-expected) > max(.001, .05*expected)))
    if bad.size:
        raise OptimizationDomainError("NONUNIFORM_SAMPLING", "训练数据存在重复时间或采样缺口，请先处理时间轴再辨识模型",
            details={"partition": "train", "nominal_interval_seconds": expected,
                     "irregular_interval_count": int(bad.size), "first_irregular_row": int(bad[0]+1),
                     "automatic_resampling": False})


def _bounds_float(value: Any) -> tuple[float, float]:
    low, high = value
    return float(low), float(high)


def _selection_params(
    params: dict[str, Any],
    input_columns: list[str],
    output_column: str,
    *,
    train_ratio: float,
) -> dict[str, Any]:
    """Only the parameters that actually change the selected rows enter the cache key."""

    return {
        "input_columns": list(input_columns),
        "output_column": output_column,
        "window_size": params["window_size"],
        "max_segments": params["max_segments"],
        "max_anomaly_ratio": params["max_anomaly_ratio"],
        "max_missing_ratio": params["max_missing_ratio"],
        "min_input_activity_ratio": params["min_input_activity_ratio"],
        "train_ratio": train_ratio,
        "history_guard": params.get("history_guard", 32),
        "nk": params.get("delays", params.get("nk", 0)),
        "selection_mode": params.get("selection_mode", "ensemble"),
        "adaptive_windows": params.get("adaptive_windows", True),
        "temporal_coverage_bins": params.get("temporal_coverage_bins", 0),
    }


def _delay_options(
    series: VersionSeries,
    payload: OptimizationStartRequest,
    columns: list[str],
    output_column: str,
) -> dict[str, list[int]]:
    """Propose independent channel delays using training samples only."""
    low, high = _bounds_int(payload.search_space.get("nk", (0, 20)))
    stop = int(series.n_samples * payload.train_ratio) - payload.history_guard
    options: dict[str, list[int]] = {}
    for column in columns:
        try:
            correlations, _ = prewhitened_cross_correlation(
                series.values[column][:stop], series.values[output_column][:stop], max_lag=high,
            )
            peaks = rank_candidates(correlations, top_k=2, sample_count=stop)
            values = {lag for peak in peaks for lag in range(max(low, peak.lag - 2), min(high, peak.lag + 2) + 1)}
        except (IdentifiabilityError, ValueError, np.linalg.LinAlgError):
            values = set()
        options[column] = sorted(values) or list(range(low, high + 1))
    return options


def _trial_delays(parameters: dict[str, Any], columns: list[str]) -> dict[str, int]:
    delays = parameters.get("delays")
    return {column: int(delays[column]) if isinstance(delays, dict) else int(parameters["nk"]) for column in columns}


def _feedback_actions(
    result: ArxCoreResult,
    selection: SegmentSelectionOutcome,
    parameters: dict[str, Any],
    search_space: dict[str, Any],
    *, advanced: bool = False,
) -> dict[str, Any]:
    """Validation-only proposals with bounded actions, never using held-out Test."""
    proposed: dict[str, Any] = {}
    reasons: list[str] = []
    if not selection.selection.excitation.excitation_satisfied:
        low, high = _bounds_int(search_space.get("max_segments", (3, 20)))
        proposed["max_segments"] = int(np.clip(parameters["max_segments"] + 2, low, high))
        reasons.append("expand_information_coverage")
    summary = result.validation
    columns = list(summary.input_residual_test.get("rejected_channels", []))
    if columns:
        low, high = _bounds_int(search_space.get("max_segments", (3, 20)))
        proposed["max_segments"] = int(np.clip(parameters["max_segments"] + 1, low, high))
        reasons.append("check_unmodelled_input_dynamics")
    recommendations: list[dict[str, Any]] = []
    if advanced:
        support = summary.input_support
        if support.get("unsupported_constant_inputs"):
            recommendations.append({"action": "collect_excited_control_data",
                "channels": support["unsupported_constant_inputs"],
                "automatic": False, "reason": "unexcited_control_changed"})
        if support.get("status") == "extrapolation" or summary.fit_gap > 10:
            proposed.update({"temporal_coverage_bins": 3, "selection_mode": "ensemble", "adaptive_windows": True})
            reasons.append("balance_training_coverage")
        if columns:
            low, high = _bounds_int(search_space.get("window_size", (30, 200)))
            proposed["window_size"] = int(np.clip(parameters["window_size"]+20, low, high))
            reasons.append("expand_dynamic_window")
        # A bounded proposal at its limit is not a new search action.
        proposed = {key: value for key, value in proposed.items() if parameters.get(key) != value}
        base = {k: parameters[k] for k in ("window_size", "max_segments", "max_anomaly_ratio",
            "max_missing_ratio", "min_input_activity_ratio", "nk", "selection_mode",
            "adaptive_windows", "temporal_coverage_bins") if k in parameters}
        return {"policy_version": "validation_actions_v3", "partition": "validation",
            "test_partition_used": False, "reasons": reasons, "channels": columns,
            "recommendations": recommendations,
            "actions": [{"parameter": k, "before": parameters.get(k), "after": v} for k, v in proposed.items()],
            "parameters": {**base, **{f"nk_{c}": d for c, d in parameters.get("delays", {}).items()}, **proposed} if proposed else {}}
    return {"policy_version": "validation_actions_v2", "partition": "validation", "reasons": reasons, "channels": columns, "parameters": {**{k: parameters[k] for k in ("window_size", "max_segments", "max_anomaly_ratio", "max_missing_ratio", "min_input_activity_ratio", "nk", "selection_mode", "adaptive_windows", "temporal_coverage_bins") if k in parameters}, **{f"nk_{c}": delay for c, delay in parameters.get("delays", {}).items()}, **proposed} if proposed else {}}


def _sanitise_warm_start(candidate: dict[str, Any]) -> dict[str, Any]:
    """Keep only keys the current search space defines, so enqueue cannot fail."""

    allowed = {
        "window_size",
        "max_segments",
        "max_anomaly_ratio",
        "max_missing_ratio",
        "min_input_activity_ratio",
        "na",
        "nb",
        "nk",
        "estimator",
        "ridge_alpha",
    }
    cleaned = {key: value for key, value in candidate.items() if key in allowed}
    if cleaned.get("estimator") != "ridge":
        cleaned.pop("ridge_alpha", None)
    return cleaned


async def _retrieve_warm_start(
    session: AsyncSession,
    *,
    series: VersionSeries,
    fingerprint: ProfileFingerprint,
) -> tuple[list[dict[str, Any]], UUID | None]:
    """Find the closest past studies on *other* datasets and reuse their winners.

    Excluding the current dataset is not a formality: warm-starting a dataset from its own
    previous run would recycle a configuration that already saw this data, which is exactly
    the leakage the evaluation protocol forbids.
    """

    # Push the "not this dataset" exclusion into SQL instead of pulling the whole table
    # into Python to filter it there: strategy_memory grows with every study ever run, and
    # this function used to fetch all of it on every single warm-start lookup regardless of
    # how many rows it could actually use. `!=` alone would silently drop legitimate
    # dataset_id IS NULL rows under SQL's three-valued logic (NULL != x is NULL, not true),
    # so those are kept explicitly to match the original Python `==` comparison exactly.
    query = select(StrategyMemory)
    if series.dataset_id is not None:
        query = query.where(
            or_(StrategyMemory.dataset_id.is_(None), StrategyMemory.dataset_id != series.dataset_id)
        )
    entries = list((await session.scalars(query)).all())
    scored: list[tuple[float, StrategyMemory]] = []
    for entry in entries:
        distance = fingerprint_distance(fingerprint.vector, list(entry.fingerprint_vector))
        if distance <= WARM_START_MAX_DISTANCE:
            scored.append((distance, entry))
    if not scored:
        return [], None
    scored.sort(key=lambda item: item[0])
    chosen = scored[:WARM_START_LIMIT]
    return [dict(entry.best_params) for _, entry in chosen], chosen[0][1].study_id


async def _reserve_study(
    session: AsyncSession,
    *,
    study_id: UUID,
    payload: OptimizationStartRequest,
    baseline_model_id: UUID | None = None,
    job: dict[str, Any],
) -> None:
    """Write the study row before any long work starts.

    Without this the caller gets a study id that ``/status`` answers 404 for until the
    search finishes — which, once the search runs in a worker, is the entire useful window.
    """

    session.add(
        OptimizationStudy(
            id=study_id,
            dataset_id=None,
            version_id=payload.version_id,
            status="queued",
            objective="val_free_run_fit",
            parameters=payload.model_dump(mode="json"),
            baseline_model_id=baseline_model_id,
            best_params={},
            fingerprint={},
            statistics={
                "target_trials": payload.max_trials,
                "objective_semantics": dict(OBJECTIVE_SEMANTICS),
                "job": job,
            },
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()


def _study_job_contract(
    *,
    study_id: UUID,
    execution_mode: str,
    submission_state: str,
) -> dict[str, Any]:
    rq_mode = execution_mode == "rq"
    return {
        "contract_version": "optimization_job_v1",
        "execution_mode": execution_mode,
        "rq_job_id": str(study_id) if rq_mode else None,
        "queue_name": QUEUE_NAME if rq_mode else None,
        "job_timeout_seconds": JOB_TIMEOUT_SECONDS if rq_mode else None,
        "submission_state": submission_state,
        "submission_requested_at": datetime.now(UTC).isoformat() if rq_mode else None,
    }


async def _update_study_job_contract(
    session: AsyncSession,
    *,
    study_id: UUID,
    submission_state: str,
    execution_mode: str | None = None,
    clear_rq_identity: bool = False,
) -> None:
    study = await session.get(OptimizationStudy, study_id)
    if study is None:
        raise OptimizationDomainError(
            "OPTIMIZATION_STUDY_NOT_FOUND",
            "寻优研究不存在，无法更新作业提交事实。",
            status_code=404,
        )
    statistics = dict(study.statistics)
    job = dict(statistics.get("job", {}))
    job["submission_state"] = submission_state
    if execution_mode is not None:
        job["execution_mode"] = execution_mode
    if clear_rq_identity:
        job["rq_job_id"] = None
        job["queue_name"] = None
        job["job_timeout_seconds"] = None
        job["submission_requested_at"] = None
    statistics["job"] = job
    study.statistics = statistics
    await session.commit()


async def _mark_study_running(session: AsyncSession, *, study_id: UUID) -> None:
    study = await session.get(OptimizationStudy, study_id)
    if study is not None:
        study.status = "running"
        await session.commit()


def _study_failure_error_code(
    error: Exception, *, phase: OptimizationTerminalPhase
) -> str:
    code = getattr(error, "code", None)
    if isinstance(code, str) and code:
        return code
    return {
        "preparation": "STUDY_PREPARATION_FAILED",
        "baseline": "BASELINE_EXECUTION_FAILED",
        "search": "STUDY_EXECUTION_FAILED",
        "winner_persistence": "OPTIMIZED_MODEL_PERSISTENCE_FAILED",
        "study_persistence": "STUDY_PERSISTENCE_FAILED",
    }[phase]


async def _transition_study_terminal(
    session: AsyncSession,
    *,
    study_id: UUID,
    code: OptimizationTerminalReasonCode,
    phase: OptimizationTerminalPhase,
    error_code: str | None = None,
    study: OptimizationStudy | None = None,
    commit: bool = True,
) -> None:
    """Apply one typed, conflict-safe terminal transition to an optimization study."""

    if code in {"RQ_TIMEOUT", "WORKER_CRASH"}:
        raise OptimizationDomainError(
            "OPTIMIZATION_TERMINAL_EVIDENCE_REQUIRED",
            "基础设施终态只能由受控 RQ 证据入口写入。",
            status_code=409,
        )
    target = study or await session.get(OptimizationStudy, study_id)
    if target is None:
        return

    existing = target.statistics.get("terminal_reason")
    if target.status in {"succeeded", "failed"} and isinstance(existing, dict):
        if (
            existing.get("code") == code
            and existing.get("phase") == phase
            and existing.get("error_code") == error_code
        ):
            return
        raise OptimizationDomainError(
            "OPTIMIZATION_TERMINAL_TRANSITION_CONFLICT",
            "寻优研究已经进入不可覆盖的终态。",
            status_code=409,
            details={
                "study_id": str(study_id),
                "existing_terminal_reason": existing,
                "requested_terminal_code": code,
            },
        )

    recorded_at = datetime.now(UTC)
    terminal_reason = OptimizationTerminalReasonV2(
        policy_version=TERMINAL_REASON_POLICY_VERSION,
        code=code,
        category=_TERMINAL_REASON_CATEGORY[code],
        phase=phase,
        error_code=error_code,
        recorded_at=recorded_at,
    ).model_dump(mode="json")
    statistics = dict(target.statistics)
    if error_code is None:
        statistics.pop("error_code", None)
    else:
        statistics["error_code"] = error_code
    statistics["terminal_reason"] = terminal_reason
    target.status = _TERMINAL_REASON_STATUS[code]
    target.statistics = statistics
    target.finished_at = recorded_at
    if commit:
        await session.commit()


async def persist_rq_terminal_evidence(
    session: AsyncSession,
    *,
    study_id: UUID,
    evidence: RqTerminalEvidence,
) -> bool:
    """Atomically reconcile one typed RQ fact into the Study terminal contract."""

    await session.rollback()
    target = await session.scalar(
        select(OptimizationStudy)
        .where(OptimizationStudy.id == study_id)
        .with_for_update()
    )
    if target is None or not _rq_evidence_matches_study(target, evidence):
        return False

    requested = _terminal_from_rq_evidence(evidence)
    if requested is None:
        return False
    code, error_code = requested
    existing = target.statistics.get("terminal_reason")

    if isinstance(existing, dict):
        if existing.get("policy_version") != TERMINAL_REASON_POLICY_VERSION:
            return False
        existing_code = existing.get("code")
        if (
            existing_code == code
            and existing.get("phase") == "rq_execution"
            and existing.get("error_code") == error_code
        ):
            return False
        if existing_code in {
            "COMPLETED",
            "NO_VALID_CANDIDATE",
            "RQ_TIMEOUT",
            "WORKER_CRASH",
        }:
            return False
        if existing_code != "FAILED":
            return False
        if code == "FAILED":
            return False
        if code == "WORKER_CRASH" and not _is_provisional_rq_failure(existing):
            return False
        if code == "RQ_TIMEOUT" and existing.get("category") != "SYSTEM_FAILURE":
            return False
    elif target.status in {"succeeded", "failed"}:
        # Historical terminal rows without a typed reason are not reinterpreted from Redis.
        return False

    statistics = dict(target.statistics)
    job = dict(statistics.get("job", {}))
    job["terminal_evidence"] = evidence.to_payload()
    statistics["job"] = job
    if isinstance(existing, dict) and existing.get("code") == "FAILED":
        history = list(statistics.get("terminal_reason_history", []))
        history.append(dict(existing))
        statistics["terminal_reason_history"] = history

    recorded_at = datetime.now(UTC)
    terminal_reason = OptimizationTerminalReasonV2(
        policy_version=TERMINAL_REASON_POLICY_VERSION,
        code=code,
        category=_TERMINAL_REASON_CATEGORY[code],
        phase="rq_execution",
        error_code=error_code,
        recorded_at=recorded_at,
    ).model_dump(mode="json")
    statistics["error_code"] = error_code
    statistics["terminal_reason"] = terminal_reason
    target.statistics = statistics
    target.status = "failed"
    target.finished_at = recorded_at
    await session.commit()
    return True


def _rq_evidence_matches_study(
    study: OptimizationStudy, evidence: RqTerminalEvidence
) -> bool:
    contract = study.statistics.get("job")
    if not isinstance(contract, dict):
        return False
    if (
        contract.get("execution_mode") != "rq"
        or contract.get("rq_job_id") != str(study.id)
        or contract.get("rq_job_id") != evidence.rq_job_id
        or contract.get("queue_name") != QUEUE_NAME
    ):
        return False
    allowed_sources = {
        "job_timeout": {
            "failure_callback",
            "failed_registry",
            "started_registry_cleanup",
        },
        "work_horse_terminated": {"failed_registry", "started_registry_cleanup"},
        "abandoned_execution": {
            "failure_callback",
            "failed_registry",
            "started_registry_cleanup",
        },
        "ordinary_exception": {"failure_callback"},
    }
    sources = allowed_sources.get(evidence.kind)
    if sources is None or evidence.source not in sources:
        return False
    if evidence.source != "failure_callback" and evidence.rq_status != "failed":
        return False
    timeout = contract.get("job_timeout_seconds")
    if evidence.kind == "job_timeout":
        return (
            isinstance(timeout, int)
            and timeout == evidence.job_timeout_seconds
            and evidence.confidence == "HIGH"
        )
    return True


def _terminal_from_rq_evidence(
    evidence: RqTerminalEvidence,
) -> tuple[OptimizationTerminalReasonCode, str] | None:
    if evidence.kind == "job_timeout":
        if evidence.confidence != "HIGH" or evidence.error_code != "RQ_JOB_TIMEOUT":
            return None
        return "RQ_TIMEOUT", "RQ_JOB_TIMEOUT"
    if evidence.kind == "work_horse_terminated":
        if (
            evidence.confidence != "HIGH"
            or evidence.error_code != "RQ_WORK_HORSE_TERMINATED"
        ):
            return None
        return "WORKER_CRASH", "RQ_WORK_HORSE_TERMINATED"
    if evidence.kind == "abandoned_execution":
        if (
            evidence.confidence != "HIGH"
            or evidence.error_code != "RQ_ABANDONED_EXECUTION"
        ):
            return None
        return "WORKER_CRASH", "RQ_ABANDONED_EXECUTION"
    if (
        evidence.kind == "ordinary_exception"
        and evidence.confidence == "GENERIC"
        and evidence.error_code == "RQ_JOB_EXECUTION_FAILED"
    ):
        return "FAILED", "RQ_JOB_EXECUTION_FAILED"
    return None


def _is_provisional_rq_failure(existing: dict[str, Any]) -> bool:
    return (
        existing.get("category") == "SYSTEM_FAILURE"
        and existing.get("phase") == "rq_execution"
        and existing.get("error_code") == "RQ_JOB_EXECUTION_FAILED"
    )


async def _persist_study_failure_best_effort(
    session: AsyncSession,
    *,
    study_id: UUID,
    phase: OptimizationTerminalPhase,
    error: Exception,
) -> None:
    """Persist an application failure without replacing the exception that caused it."""

    error_code = _study_failure_error_code(error, phase=phase)
    try:
        await session.rollback()
        await _transition_study_terminal(
            session,
            study_id=study_id,
            code="FAILED",
            phase=phase,
            error_code=error_code,
        )
    except Exception as persistence_error:
        error.add_note(
            "OptimizationStudy failure persistence also failed: "
            f"{type(persistence_error).__name__}"
        )


async def _persist_failed_outcome_best_effort(
    session: AsyncSession,
    *,
    series: VersionSeries,
    payload: OptimizationStartRequest,
    outcome: StudyOutcome,
    error: Exception,
    error_code: str,
) -> None:
    """Keep completed trial evidence when winner persistence fails, if the DB permits."""

    try:
        await _persist_study(
            session,
            series=series,
            payload=payload,
            outcome=outcome,
            optimized_model_id=None,
            terminal_code="FAILED",
            terminal_phase="winner_persistence",
            terminal_error_code=error_code,
        )
    except Exception as persistence_error:
        await session.rollback()
        error.add_note(
            "OptimizationStudy trial-outcome persistence also failed: "
            f"{type(persistence_error).__name__}"
        )


async def _persist_evaluation(
    session: AsyncSession,
    *,
    study_id: UUID,
    series: VersionSeries,
    evaluation: EvaluationOutcome,
    kind: str,
) -> UUID:
    """Persist a baseline/final evaluation without introducing a new table."""

    study = await session.get(OptimizationStudy, study_id)
    if study is None:
        raise OptimizationDomainError(
            "OPTIMIZATION_STUDY_NOT_FOUND", "优化研究不存在，无法持久化评价运行。", status_code=404
        )
    run_id = uuid4()
    payload = _evaluation_payload(evaluation, processing_run_id=run_id)
    evaluations = dict(study.statistics.get("evaluations", {}))
    evaluations[kind] = payload
    study.statistics = {**dict(study.statistics), "evaluations": evaluations}
    session.add(
        ProcessingRun(
            id=run_id,
            dataset_id=series.dataset_id,
            source_version_id=series.version_id,
            run_type=f"optimization.{kind}",
            status=evaluation.status,
            parameters=evaluation.parameters,
            result=payload,
            created_at=evaluation.started_at,
            finished_at=evaluation.finished_at,
        )
    )
    await session.commit()
    return run_id


def _evaluation_payload(
    evaluation: EvaluationOutcome,
    *,
    processing_run_id: UUID | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": evaluation.status,
        "parameters": evaluation.parameters,
        "validation_free_run_fit": evaluation.validation_free_run_fit,
        "test_free_run_fit": evaluation.test_free_run_fit,
        "test_mae": evaluation.test_mae,
        "test_rmse": evaluation.test_rmse,
        "test_r2": evaluation.test_r2,
        "test_one_step_fit": evaluation.test_one_step_fit,
        "test_one_step_mae": evaluation.test_mae,
        "test_one_step_rmse": evaluation.test_rmse,
        "test_one_step_r2": evaluation.test_r2,
        "test_free_run_mae": evaluation.test_free_run_mae,
        "test_free_run_rmse": evaluation.test_free_run_rmse,
        "test_free_run_r2": evaluation.test_free_run_r2,
        "generalization_gap": evaluation.generalization_gap,
        "duration_ms": evaluation.duration_ms,
        "processing_run_id": str(processing_run_id) if processing_run_id else None,
        "error_code": evaluation.error_code,
        "started_at": evaluation.started_at.isoformat(),
        "finished_at": evaluation.finished_at.isoformat(),
    }
    if evaluation.best_trial_number is not None:
        payload["best_trial_number"] = evaluation.best_trial_number
    return payload


def _stored_baseline(statistics: dict[str, Any]) -> BaselineEvaluation | None:
    payload = _stored_evaluation(statistics, "baseline")
    return BaselineEvaluation.model_validate(payload) if payload else None


def _stored_final_evaluation(statistics: dict[str, Any]) -> FinalTestEvaluation | None:
    payload = _stored_evaluation(statistics, "final_test")
    return FinalTestEvaluation.model_validate(payload) if payload else None


def _stored_evaluation(statistics: dict[str, Any], kind: str) -> dict[str, Any] | None:
    evaluations = statistics.get("evaluations")
    if not isinstance(evaluations, dict):
        return None
    value = evaluations.get(kind)
    return dict(value) if isinstance(value, dict) else None


async def _persist_study(
    session: AsyncSession,
    *,
    series: VersionSeries,
    payload: OptimizationStartRequest,
    outcome: StudyOutcome,
    optimized_model_id: UUID | None,
    terminal_code: OptimizationTerminalReasonCode,
    terminal_phase: OptimizationTerminalPhase,
    terminal_error_code: str | None = None,
) -> None:
    now = datetime.now(UTC)
    # The row already exists when the API or the worker reserved it. Updating in place is
    # what makes a job retry idempotent: re-running the same study id cannot produce two
    # study records for one request.
    study = await session.get(OptimizationStudy, outcome.study_id)
    if study is None:
        study = OptimizationStudy(id=outcome.study_id, created_at=now)
        session.add(study)
    study.dataset_id = series.dataset_id
    study.version_id = series.version_id
    study.objective = "val_free_run_fit"
    study.parameters = payload.model_dump(mode="json")
    study.best_trial_number = outcome.best_number
    study.best_value = outcome.best_value
    study.best_params = outcome.best_params
    study.optimized_model_id = optimized_model_id
    study.fingerprint = outcome.fingerprint.to_payload()
    # Keep what was asked for alongside what happened: a study that requested 50 trials and
    # completed 12 is a different story from one that requested 12, and the final statistics
    # alone cannot tell them apart.
    study.statistics = {
        "target_trials": payload.max_trials,
        **dict(study.statistics),
        **outcome.statistics,
        "objective_semantics": dict(OBJECTIVE_SEMANTICS),
    }
    study.warm_started_from = outcome.warm_started_from
    await _transition_study_terminal(
        session,
        study_id=outcome.study_id,
        code=terminal_code,
        phase=terminal_phase,
        error_code=terminal_error_code,
        study=study,
        commit=False,
    )

    # Trials from an earlier attempt at the same study id would otherwise accumulate.
    await session.execute(
        delete(OptimizationTrialRecord).where(OptimizationTrialRecord.study_id == outcome.study_id)
    )
    for trial in outcome.trials:
        session.add(
            OptimizationTrialRecord(
                id=uuid4(),
                study_id=outcome.study_id,
                trial_number=trial.number,
                state=trial.state,
                value=trial.value,
                params=trial.params,
                metrics=trial.metrics,
                cache_hit=trial.cache_hit,
                duration_ms=trial.duration_ms,
                error_code=trial.error_code,
                created_at=now,
                finished_at=now,
            )
        )
    if outcome.best_number is not None and optimized_model_id is not None:
        session.add(
            StrategyMemory(
                id=uuid4(),
                dataset_id=series.dataset_id,
                version_id=series.version_id,
                study_id=outcome.study_id,
                fingerprint=outcome.fingerprint.to_payload(),
                fingerprint_vector=outcome.fingerprint.vector,
                best_params=outcome.best_params,
                achieved_metrics=outcome.best_metrics,
                objective_value=outcome.best_value,
                source="study",
                created_at=now,
            )
        )
    session.add(
        OperationLog(
            id=uuid4(),
            event_type=(
                "optimization.study.completed"
                if optimized_model_id is not None
                else "optimization.study.failed"
            ),
            subject_id=str(series.dataset_id),
            payload_json=json.dumps(
                {
                    "study_id": str(outcome.study_id),
                    "best_value": outcome.best_value,
                    "best_params": outcome.best_params,
                    "optimized_model_id": str(optimized_model_id)
                    if optimized_model_id is not None
                    else None,
                    "statistics": outcome.statistics,
                    "warm_started_from": str(outcome.warm_started_from)
                    if outcome.warm_started_from
                    else None,
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


def _param_importances(records: list[OptimizationTrialRecord]) -> dict[str, float]:
    """Correlation-based importance, which needs no extra dependency.

    Optuna's fANOVA importance requires a live Study object; the persisted trials are all
    that survive a restart, so importance is derived from them directly. It is reported as
    the absolute Spearman-style rank correlation between a parameter and the objective,
    normalised to sum to one.
    """

    completed = [record for record in records if record.value is not None]
    if len(completed) < 4:
        return {}
    values = np.asarray([record.value for record in completed], dtype=float)
    names = sorted({name for record in completed for name in record.params})
    importances: dict[str, float] = {}
    for name in names:
        column = []
        target = []
        for record, score in zip(completed, values, strict=True):
            raw = record.params.get(name)
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                continue
            column.append(float(raw))
            target.append(float(score))
        if len(column) < 4 or len(set(column)) < 2:
            continue
        ranked_x = _ranks(np.asarray(column))
        ranked_y = _ranks(np.asarray(target))
        left = ranked_x - ranked_x.mean()
        right = ranked_y - ranked_y.mean()
        denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
        if denominator <= 0:
            continue
        importances[name] = abs(float(np.dot(left, right) / denominator))
    total = sum(importances.values())
    if total <= 0:
        return {}
    return {name: value / total for name, value in sorted(importances.items())}


def _ranks(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(values.size, dtype=float)
    ranks[order] = np.arange(1, values.size + 1, dtype=float)
    return ranks
