"""MISO ARX identification with control-relevant acceptance (phase 7).

The core here is pure: arrays in, coefficients and metrics out. ``identification_service``
reuses it for the simulation path, the route uses the async wrapper for any version, and
the closed-loop optimiser calls it directly thousands of times, so it must not touch the
database or the filesystem.

Two things differ from a textbook least-squares fit:

* **Free-run simulation is the primary metric.** One-step-ahead prediction is fed the
  measured ``y(k-1)``, so on an autocorrelated process a badly identified model still
  scores above 95% by copying the previous sample. The closed loop optimises the free-run
  number; the one-step number is kept as a diagnostic, and their gap is itself a warning.
* **Engineering priors are hard constraints.** A steady-state gain with the wrong sign is
  not a slightly worse model, it is a wrong one, and reporting it as a success would cost
  the engineer more time than returning nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import numpy as np
from algorithms.identifiability.estimation import (
    Estimator,
    estimate_parameters,
    tc_prior_covariance,
)
from algorithms.identifiability.excitation import (
    profile_excitation,
)
from algorithms.identifiability.experiments import TrainingExperiment
from algorithms.identifiability.multihorizon import fit_multihorizon
from algorithms.identifiability.regressor import (
    ArxStructure,
    FloatArray,
    IdentifiabilityError,
    RegressorMatrix,
    build_regressor,
)
from algorithms.identifiability.support import assess_input_support, training_input_support
from algorithms.identifiability.validation import (
    ModelValidation,
    fit_percentage,
    free_run_simulate,
    is_stable,
    one_step_predict,
    residual_whiteness_ratio,
    steady_state_gains,
    validate_model,
)
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset import ProcessingRun
from app.models.operation_log import OperationLog
from app.schemas.modeling import (
    ArxEvaluationResidualDiagnostics,
    ArxEvaluationSeries,
    ArxFitData,
    ArxFitRequest,
    ArxMetrics,
    ArxModelHealth,
    ArxModelStructureData,
    ArxPlotData,
    ArxResidualDiagnostics,
    ArxSavedModelEvaluationData,
    ArxTestEvaluationData,
    ModelValidationData,
    PredictionMetrics,
    PriorViolation,
    SplitIndices,
)
from app.services.contract_stubs import completed_task
from app.services.version_data import (
    VersionDataError,
    VersionSeries,
    attach_model_input_context,
    load_version_series,
    model_input_arrays,
)
from app.services.version_provenance_service import (
    VersionProvenanceError,
    resolve_arx_lag_provenance,
)

MAX_PLOT_POINTS = 6_000


class ModelingDomainError(Exception):
    """A client-safe identification failure for the standard error envelope."""

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
class ArxCoreResult:
    """Everything one identification run produces, before persistence."""

    structure: ArxStructure
    theta: FloatArray
    coefficients: dict[str, float]
    a_coefficients: list[float]
    b_coefficients: dict[str, list[float]]
    metrics: ArxMetrics
    plot_data: ArxPlotData
    residual_diagnostics: ArxResidualDiagnostics
    validation: ModelValidation
    prior_violations: tuple[PriorViolation, ...]
    training_rows: int
    free_run_series: list[float]
    input_columns: list[str]
    output_column: str
    estimator: Estimator
    # Channels whose persistent-excitation order falls short of na+nb. Reported, never
    # enforced — see the comment at the check itself for the measurement behind that.
    excitation_shortfall: dict[str, dict[str, int]] = field(default_factory=dict)
    intercept: float = 0.0
    training_output_scale: float = 1.0
    preprocessing: dict[str, object] = field(default_factory=dict)

    @property
    def objective_fit(self) -> float:
        """The number the closed loop maximises: validation free-run FIT."""

        value = self.metrics.val_free_run_fit
        return float(value) if value is not None and np.isfinite(value) else float("-inf")


def fit_arx_core(
    *,
    inputs: dict[str, FloatArray],
    output: FloatArray,
    payload: ArxFitRequest,
    input_columns: list[str],
) -> ArxCoreResult:
    """Fit an affine ARX/FIR model and translate numerical failures to domain errors."""
    try:
        return _fit_arx_core(inputs=inputs, output=output, payload=payload, input_columns=input_columns)
    except IdentifiabilityError as error:
        raise ModelingDomainError(error.code, error.message, details=error.details) from error


def _fit_arx_core(
    *, inputs: dict[str, FloatArray], output: FloatArray,
    payload: ArxFitRequest, input_columns: list[str],
    fixed_parameters: tuple[FloatArray, float, dict[str, object]] | None = None,
) -> ArxCoreResult:
    """Fit on Train only; Test is opened only by explicit evaluation."""

    structure = _structure(payload, input_columns)
    n_samples = int(np.asarray(output, dtype=float).shape[0])
    splits = _split_indices(n_samples, payload)
    train_end = splits.train_end
    val_end = splits.val_end

    try:
        full = build_regressor(inputs=inputs, output=output, structure=structure)
    except IdentifiabilityError as error:
        raise ModelingDomainError(error.code, error.message, details=error.details) from error

    guard = max(structure.max_history, payload.history_guard or 0)
    train_rows = _partition_rows(full, 0, train_end - guard)
    if payload.training_sample_indices:
        allowed = set(int(value) for value in payload.training_sample_indices)
        train_rows = np.asarray(
            [row for row in train_rows if int(full.time_indices[row]) in allowed], dtype=int
        )
    regularized = payload.resolved_estimator() != "ols" and (payload.ridge_alpha or 0) > 0
    minimum_rows = 8 if regularized else full.n_parameters * 2 + 1
    if train_rows.size < minimum_rows:
        raise ModelingDomainError(
            "INSUFFICIENT_ROWS",
            "训练样本不足以稳定估计 ARX 参数。",
            details={"required": minimum_rows, "actual": int(train_rows.size)},
        )

    train_features = full.features[train_rows]
    train_targets = full.targets[train_rows]
    estimator = payload.resolved_estimator()

    # Persistent excitation is reported, not enforced. ALG-0.2 §3 originally specified it as
    # a blocking precondition; measurement says it cannot carry that weight.
    #
    # The finite-sample PE-order estimate does not separate usable data from unusable data
    # here. Measured on multi-level inputs at the calibrated tolerance 1e-3, an input with
    # 8 distinct levels reports order 1 while its model reaches 95.8% free-run FIT; at 1e-4
    # a 3-level input reports order 4 — clearing the na+nb requirement — while its model
    # collapses to 0.2% free-run FIT. No tolerance separated the two, and 1e-4 also breaks
    # the textbook calibration a single step must satisfy. Blocking on this would reject
    # good models and admit bad ones, so it stays a diagnostic and the shortfall is surfaced
    # on the response. What does block is rank deficiency below, which is the failure mode
    # actually measured in EXP-1.1 and EXP-3.0.
    excitation = profile_excitation(
        full.take(train_rows),
        inputs={column: inputs[column][full.time_indices[train_rows]] for column in structure.input_columns},
    )
    excitation_shortfall = {
        column: {
            "actual": excitation.persistent_excitation_order.get(column, 0),
            "required": excitation.required_excitation_order[column],
        }
        for column in structure.input_columns
        if excitation.persistent_excitation_order.get(column, 0)
        < excitation.required_excitation_order[column]
    }

    reliability = np.asarray([
        min(payload.sample_weights.get(int(t - lag), 1.0) for lag in range(structure.max_history + 1))
        for t in full.time_indices[train_rows]
    ], dtype=float)
    if fixed_parameters is None and payload.model_type == "OE":
        times = full.time_indices[train_rows][reliability > 0]
        if times.size == 0:
            raise ModelingDomainError("INSUFFICIENT_ROWS", "OE 缺少正权重连续训练区间")
        intervals = np.split(times, np.flatnonzero(np.diff(times) != 1)+1)
        experiments = [TrainingExperiment(f"selected_interval_{i}", inputs, output,
            int(interval[0]), int(interval[-1])+1) for i, interval in enumerate(intervals)]
        simulated = fit_multihorizon(experiments, structure=structure,
            horizons=tuple(payload.simulation_horizons), ridge_alpha=payload.ridge_alpha or 0.,
            max_nfev=payload.simulation_max_nfev)
        theta, intercept = simulated.theta, simulated.intercept
        preprocessing = {**simulated.diagnostics, "policy_version": "stable_multihorizon_v1",
            "regularization_kernel": "identity", "solver": "bounded_nonlinear_least_squares",
            "estimator_role": "ridge_initialization_then_simulation_loss",
            "interval_weighting": "equal_total_weight_per_selected_contiguous_interval"}
    elif fixed_parameters is None:
        try:
            estimate = estimate_parameters(
                train_features, train_targets, estimator=estimator,
                ridge_alpha=payload.ridge_alpha or 0.0,
                fit_intercept=payload.fit_intercept, standardize=payload.standardize,
                sample_weights=reliability, huber_delta=payload.huber_delta,
                prior_covariance=tc_prior_covariance(structure, payload.kernel_decay) if payload.regularization_kernel == "tc" else None,
            )
        except IdentifiabilityError as error:
            raise ModelingDomainError(error.code, error.message, details=error.details) from error
        theta, intercept = estimate.theta, estimate.intercept
        preprocessing = {**estimate.preprocessing(), "regularization_kernel": payload.regularization_kernel, "kernel_decay": payload.kernel_decay}
    else:
        theta, intercept, preprocessing = fixed_parameters
    if fixed_parameters is None:
        preprocessing = {**preprocessing, "training_input_support": training_input_support(
            inputs, full.time_indices[train_rows][reliability > 0],
            input_lags={c: (structure.nk[c], structure.nk[c]+structure.nb[c]-1)
                        for c in structure.input_columns}),
            "input_support_provenance": "positive_weight_train_regressor_inputs"}
    # Rank is assessed in normalized coordinates, including the fitted intercept.
    # Physical units and zero-reliability rows must not alter identifiability.
    active = reliability > 0
    rank_features = train_features[active]
    center = np.mean(rank_features, axis=0) if payload.fit_intercept else np.zeros(full.n_parameters)
    scale = np.std(rank_features, axis=0)
    rank_design = (rank_features - center) / np.where(scale > 0, scale, 1.0)
    if payload.fit_intercept:
        rank_design = np.column_stack((rank_design, np.ones(rank_design.shape[0])))
    rank = int(np.linalg.matrix_rank(rank_design))
    if estimator == "ols" and rank < rank_design.shape[1]:
        raise ModelingDomainError(
            "DESIGN_MATRIX_RANK_DEFICIENT", "ARX 设计矩阵秩不足，请减少共线变量或改用 Ridge。",
            details={"rank": rank, "features": int(rank_design.shape[1])},
        )

    predicted = one_step_predict(full, theta, intercept=intercept, output=output,
        initialization_policy=payload.initialization_policy, initialization_window=payload.initialization_window)
    residuals = full.targets - predicted
    metrics = _metrics(
        full,
        theta=theta,
        structure=structure,
        inputs=inputs,
        output=output,
        train_end=train_end,
        val_end=val_end,
        n_samples=n_samples,
        train_rows=train_rows,
        evaluate_test=payload.evaluate_test,
        intercept=intercept,
        history_guard=guard,
        fit_intercept=payload.fit_intercept,
        initialization_policy=payload.initialization_policy, initialization_window=payload.initialization_window,
    )
    validation = validate_model(
        theta,
        structure,
        inputs=inputs,
        output=output,
        start=train_end + guard,
        stop=val_end - guard,
        intercept=intercept,
        initialization_policy=payload.initialization_policy, initialization_window=payload.initialization_window,
    )
    if val_end-guard > train_end+guard:
        validation = replace(validation, input_support=assess_input_support(
            preprocessing.get("training_input_support", {}), inputs,
            start=train_end+guard, stop=val_end-guard))
    violations = _check_priors(theta, structure, payload, validation)
    evaluation_end = n_samples if payload.evaluate_test else val_end
    try:
        _, free_run = free_run_simulate(
            theta, structure, inputs=inputs, output=output, start=0, stop=evaluation_end,
            intercept=intercept,
            initialization_policy=payload.initialization_policy, initialization_window=payload.initialization_window,
        )
        preprocessing = {**preprocessing, "free_run_series_status": "succeeded"}
    except IdentifiabilityError as error:
        if error.code != "SIMULATION_DIVERGED":
            raise
        free_run = np.empty(0)
        preprocessing = {**preprocessing, "free_run_series_status": "diverged", "free_run_series_error_code": error.code}

    names = structure.feature_names()
    coefficients = {name: float(value) for name, value in zip(names, theta, strict=True)}
    visible_rows = np.nonzero(full.time_indices < evaluation_end)[0]
    stride = max(1, visible_rows.size // MAX_PLOT_POINTS)
    visible_rows = visible_rows[::stride]
    return ArxCoreResult(
        structure=structure,
        theta=theta,
        coefficients=coefficients,
        a_coefficients=[coefficients[f"a{i}"] for i in range(1, structure.na + 1)],
        b_coefficients={
            column: [coefficients[f"b_{column}_{lag}"] for lag in range(structure.nb[column])]
            for column in input_columns
        },
        metrics=metrics,
        plot_data=ArxPlotData(
            indices=[int(full.time_indices[row]) for row in visible_rows],
            y_true=[float(full.targets[row]) for row in visible_rows],
            y_pred=[float(predicted[row]) for row in visible_rows],
            residuals=[float(residuals[row]) for row in visible_rows],
            splits=splits,
            split_indices=splits,
        ),
        residual_diagnostics=_acf(residuals[train_rows]),
        validation=validation,
        prior_violations=violations,
        training_rows=int(train_rows.size),
        free_run_series=[float(v) for v in free_run[::stride]],
        input_columns=list(input_columns),
        output_column=payload.output_column,
        estimator=estimator,
        excitation_shortfall=excitation_shortfall,
        intercept=intercept,
        training_output_scale=float(np.std(np.asarray(output)[:train_end - guard][np.isfinite(np.asarray(output)[:train_end - guard])])),
        preprocessing={**preprocessing, "initialization_policy": payload.initialization_policy,
            "initialization_window": payload.initialization_window,
            "initialization_parameters": int(payload.model_type == "ARX" and payload.initialization_policy == "past_residual")},
    )


async def fit_arx_on_version(
    session: AsyncSession,
    *,
    payload: ArxFitRequest,
    artifact_root: Path,
    require_lag_provenance: bool = False,
) -> ArxFitData:
    """Load one version, optionally enforce Lag provenance, fit, and persist the run."""

    try:
        series = await load_version_series(
            session,
            version_id=payload.version_id,
            artifact_root=artifact_root,
            dataset_id=payload.dataset_id,
        )
        input_columns, output_column = series.resolve_columns(
            input_columns=payload.input_columns or None,
            output_column=payload.output_column,
        )
        series = await attach_model_input_context(session, series, artifact_root=artifact_root)
    except VersionDataError as error:
        raise ModelingDomainError(
            error.code, error.message, status_code=error.status_code, details=error.details
        ) from error

    if require_lag_provenance:
        try:
            await resolve_arx_lag_provenance(
                session,
                version_id=series.version_id,
                input_columns=input_columns,
            )
        except VersionProvenanceError as error:
            raise ModelingDomainError(
                error.code,
                error.message,
                status_code=error.status_code,
                details=error.details,
            ) from error

    resolved = payload.model_copy(update={"input_columns": input_columns, "output_column": output_column})
    result = fit_arx_core(
        inputs=model_input_arrays(series, input_columns),
        output=series.values[output_column],
        payload=resolved,
        input_columns=input_columns,
    )
    result.preprocessing["input_support_sources"] = {
        c: series.input_context_versions.get(c, str(series.version_id))
        for c in cast(dict[str, object], result.preprocessing["training_input_support"])}
    if result.prior_violations:
        raise ModelingDomainError(
            "PRIOR_CONSTRAINT_VIOLATED",
            "辨识结果与工程先验冲突，模型未入库。",
            details={
                "violations": [
                    violation.model_dump(mode="json") for violation in result.prior_violations
                ]
            },
        )
    if payload.require_stable and not result.validation.stable:
        raise ModelingDomainError(
            "MODEL_UNSTABLE",
            "A(q) 存在单位圆外极点，模型不稳定，未入库。",
            details={"max_pole_modulus": result.validation.max_pole_modulus},
        )

    model_id = uuid4()
    artifact_uri = _persist_artifact(
        artifact_root, model_id=model_id, series=series, payload=resolved, result=result
    )
    processing_run_id = await _persist_run(
        session, model_id=model_id, series=series, payload=resolved, result=result
    )

    return ArxFitData(
        model_id=model_id,
        processing_run_id=processing_run_id,
        task=completed_task(
            stage="fit_arx",
            message="ARX 辨识、自由仿真评价与先验校验已完成。",
        ),
        estimator=result.estimator,
        intercept=result.intercept,
        preprocessing=result.preprocessing,
        model_structure=to_model_structure_data(resolved, result.structure),
        dataset_id=series.dataset_id,
        version_id=series.version_id,
        coefficients=result.coefficients,
        a_coefficients=result.a_coefficients,
        b_coefficients=result.b_coefficients,
        metrics=result.metrics,
        plot_data=result.plot_data,
        residual_diagnostics=result.residual_diagnostics,
        artifact_uri=artifact_uri,
        validation=to_validation_data(result.validation, result.excitation_shortfall),
        prior_violations=list(result.prior_violations),
        training_rows=result.training_rows,
        free_run_series=result.free_run_series,
    )


@dataclass(frozen=True)
class SavedArxModel:
    """A persisted ARX artifact reconstructed without estimating any parameters."""

    model_id: UUID
    dataset_id: UUID
    source_version_id: UUID
    payload: ArxFitRequest
    structure: ArxStructure
    theta: FloatArray
    artifact_uri: str
    intercept: float = 0.0
    preprocessing: dict[str, object] = field(default_factory=dict)


def replay_saved_arx_core(
    *, saved: SavedArxModel, inputs: dict[str, FloatArray], output: FloatArray,
) -> ArxCoreResult:
    """Compute full partition diagnostics with immutable saved parameters, without fitting."""
    try:
        return _fit_arx_core(inputs=inputs, output=output,
            payload=saved.payload.model_copy(update={"evaluate_test": True}),
            input_columns=list(saved.structure.input_columns),
            fixed_parameters=(saved.theta, saved.intercept, saved.preprocessing))
    except IdentifiabilityError as error:
        raise ModelingDomainError(error.code, error.message, details=error.details) from error


def load_saved_arx_model(*, model_id: UUID, artifact_root: Path) -> SavedArxModel:
    """Load one persisted ARX artifact and reconstruct its fixed structure and parameters."""

    artifact_uri = (Path("models") / f"{model_id}.json").as_posix()
    path = artifact_root / artifact_uri
    if not path.is_file():
        raise ModelingDomainError(
            "MODEL_ARTIFACT_NOT_FOUND",
            "未找到指定的 ARX 模型 artifact。",
            status_code=404,
            details={"model_id": str(model_id)},
        )
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise TypeError("artifact root must be an object")
        stored_model_id = UUID(str(document["model_id"]))
        source_version_id = UUID(str(document["version_id"]))
        dataset_id = UUID(str(document["dataset_id"]))
        configuration = dict(document["configuration"])
        configuration.setdefault("fit_intercept", False)
        configuration.setdefault("standardize", False)
        payload = ArxFitRequest.model_validate(configuration)
        preprocessing = document.get("preprocessing", {})
        if not isinstance(preprocessing, dict):
            raise TypeError("preprocessing must be an object")
        coefficients = document["coefficients"]
        if not isinstance(coefficients, dict):
            raise TypeError("coefficients must be an object")
    except (KeyError, TypeError, ValueError, ValidationError, json.JSONDecodeError, OSError) as error:
        raise ModelingDomainError(
            "MODEL_ARTIFACT_INVALID",
            "ARX 模型 artifact 缺少可验证的重放信息。",
            status_code=422,
            details={"model_id": str(model_id)},
        ) from error
    if stored_model_id != model_id or payload.version_id != source_version_id:
        raise ModelingDomainError(
            "MODEL_ARTIFACT_INVALID",
            "ARX 模型 artifact 的标识或来源版本不一致。",
            status_code=422,
            details={"model_id": str(model_id)},
        )
    input_columns = list(payload.input_columns)
    if not input_columns:
        raise ModelingDomainError(
            "MODEL_ARTIFACT_INVALID",
            "ARX 模型 artifact 未保存输入变量顺序。",
            status_code=422,
            details={"model_id": str(model_id)},
        )
    structure = _structure(payload, input_columns)
    theta = _theta_from_coefficients(structure, coefficients)
    try:
        intercept = float(document.get("intercept", 0.0))
        if not np.isfinite(intercept):
            raise ValueError("nonfinite intercept")
    except (TypeError, ValueError) as error:
        raise ModelingDomainError("MODEL_ARTIFACT_INVALID", "模型偏置无效", status_code=422) from error
    return SavedArxModel(
        model_id=model_id,
        dataset_id=dataset_id,
        source_version_id=source_version_id,
        payload=payload,
        structure=structure,
        theta=theta,
        artifact_uri=artifact_uri,
        intercept=intercept,
        preprocessing=dict(preprocessing),
    )


async def evaluate_saved_arx_model(
    session: AsyncSession,
    *,
    model_id: UUID,
    artifact_root: Path,
    expected_source_version_id: UUID | None = None,
) -> ArxSavedModelEvaluationData:
    """Evaluate only the held-out Test partition of one already-trained ARX model."""

    saved = load_saved_arx_model(model_id=model_id, artifact_root=artifact_root)
    if (
        expected_source_version_id is not None
        and expected_source_version_id != saved.source_version_id
    ):
        raise ModelingDomainError(
            "MODEL_SOURCE_VERSION_MISMATCH",
            "请求的来源版本与已保存 ARX 模型不一致。",
            status_code=409,
            details={
                "model_id": str(model_id),
                "expected_source_version_id": str(expected_source_version_id),
                "artifact_source_version_id": str(saved.source_version_id),
            },
        )
    try:
        series = await load_version_series(
            session,
            version_id=saved.source_version_id,
            dataset_id=saved.dataset_id,
            artifact_root=artifact_root,
        )
        input_columns, output_column = series.resolve_columns(
            input_columns=list(saved.payload.input_columns),
            output_column=saved.payload.output_column,
        )
        series = await attach_model_input_context(session, series, artifact_root=artifact_root)
    except VersionDataError as error:
        raise ModelingDomainError(
            error.code, error.message, status_code=error.status_code, details=error.details
        ) from error
    if input_columns != saved.payload.input_columns or output_column != saved.payload.output_column:
        raise ModelingDomainError(
            "MODEL_ARTIFACT_INVALID",
            "ARX 模型 artifact 的变量定义与来源版本不一致。",
            status_code=422,
            details={"model_id": str(model_id)},
        )

    run = ProcessingRun(
        id=uuid4(),
        dataset_id=series.dataset_id if series.origin == "dataset" else None,
        source_version_id=saved.source_version_id if series.origin == "dataset" else None,
        run_type="modeling.arx_evaluation",
        status="running",
        parameters={"model_id": str(model_id), "evaluation_scope": "test"},
        result={},
        created_at=datetime.now(UTC),
    )
    session.add(run)
    try:
        inputs = model_input_arrays(series, input_columns)
        output = series.values[output_column]
        splits = _split_indices(int(np.asarray(output, dtype=float).shape[0]), saved.payload)
        regressor = build_regressor(inputs=inputs, output=output, structure=saved.structure)
        guard = max(saved.structure.max_history, saved.payload.history_guard or 0)
        test_rows = _partition_rows(
            regressor,
            splits.val_end + guard,
            splits.test_end,
        )
        if test_rows.size == 0:
            raise ModelingDomainError(
                "INSUFFICIENT_ROWS",
                "Test 分区没有可评价的 ARX 样本。",
                details={"model_id": str(model_id)},
            )
        test_start = splits.val_end + guard
        sample_indices_array = regressor.time_indices[test_rows]
        y_true_array = regressor.targets[test_rows]
        one_step_prediction_array = one_step_predict(regressor, saved.theta, intercept=saved.intercept, output=output,
            initialization_policy=saved.payload.initialization_policy, initialization_window=saved.payload.initialization_window)[test_rows]
        _, full_free_run_prediction = free_run_simulate(
            saved.theta,
            saved.structure,
            inputs=inputs,
            output=output,
            start=test_start,
            stop=splits.test_end,
            intercept=saved.intercept,
            initialization_policy=saved.payload.initialization_policy, initialization_window=saved.payload.initialization_window,
        )
        free_run_offsets = sample_indices_array - test_start
        if (
            np.any(free_run_offsets < 0)
            or np.any(free_run_offsets >= full_free_run_prediction.size)
        ):
            raise ModelingDomainError(
                "MODEL_EVALUATION_ALIGNMENT_FAILED",
                "Test 自由仿真结果无法与来源数据行确定性对齐。",
                details={"model_id": str(model_id)},
            )
        free_run_prediction_array = full_free_run_prediction[free_run_offsets]
        one_step_residual_array = y_true_array - one_step_prediction_array
        free_run_residual_array = y_true_array - free_run_prediction_array

        one_step = _to_prediction_metrics(_scores(y_true_array, one_step_prediction_array))
        free_run_scores = _scores(y_true_array, free_run_prediction_array)
        free_run = _to_prediction_metrics(free_run_scores)
        sample_indices = [int(value) for value in sample_indices_array]
        timestamps = (
            [series.timestamps[index] for index in sample_indices]
            if series.timestamps and max(sample_indices, default=-1) < len(series.timestamps)
            else []
        )
        test = ArxTestEvaluationData(
            one_step=one_step,
            free_run=free_run,
            n_samples=len(sample_indices),
        )
        acf = _acf(one_step_residual_array)
        stable, max_pole_modulus = is_stable(saved.theta[: saved.structure.na])
        evaluation = ArxSavedModelEvaluationData(
            model_id=model_id,
            source_version_id=saved.source_version_id,
            processing_run_id=run.id,
            evaluation_scope="test",
            model_structure=to_model_structure_data(saved.payload, saved.structure),
            model_health=ArxModelHealth(
                stable=stable,
                max_pole_modulus=_finite(max_pole_modulus),
                input_support=assess_input_support(cast(dict[str, dict[str, Any]], saved.preprocessing.get("training_input_support", {})),
                    inputs, start=test_start, stop=splits.test_end),
            ),
            test=test,
            series=ArxEvaluationSeries(
                sample_indices=sample_indices,
                timestamps=timestamps,
                y_true=[float(value) for value in y_true_array],
                one_step_prediction=[float(value) for value in one_step_prediction_array],
                free_run_prediction=[float(value) for value in free_run_prediction_array],
                one_step_residual=[float(value) for value in one_step_residual_array],
                free_run_residual=[float(value) for value in free_run_residual_array],
            ),
            residual_diagnostics=ArxEvaluationResidualDiagnostics(
                partition="test",
                residual_type="one_step",
                residual_whiteness_ratio=_finite(
                    residual_whiteness_ratio(one_step_residual_array)
                ),
                acf_values=acf.acf_values,
                confidence_interval=acf.confidence_interval,
            ),
        )
        run.status = "succeeded"
        run.result = evaluation.model_dump(mode="json")
        run.finished_at = datetime.now(UTC)
        await session.commit()
    except Exception as error:
        run.status = "failed"
        run.result = {
            "model_id": str(model_id),
            "error_code": error.code if isinstance(error, ModelingDomainError) else "MODEL_EVALUATION_FAILED",
            "error_message": error.message if isinstance(error, ModelingDomainError) else str(error),
        }
        run.finished_at = datetime.now(UTC)
        await session.commit()
        raise
    return evaluation


def to_model_structure_data(
    payload: ArxFitRequest,
    structure: ArxStructure,
) -> ArxModelStructureData:
    """Expose the persisted configuration without leaking internal request details."""

    return ArxModelStructureData(
        model_type=payload.model_type,
        simulation_horizons=payload.simulation_horizons,
        simulation_max_nfev=payload.simulation_max_nfev,
        regularization_kernel=payload.regularization_kernel,
        kernel_decay=payload.kernel_decay,
        initialization_policy=payload.initialization_policy,
        initialization_window=payload.initialization_window,
        input_columns=list(payload.input_columns),
        output_column=payload.output_column,
        na=payload.na,
        nb=dict(structure.nb),
        delays=dict(structure.nk),
        estimator=payload.resolved_estimator(),
        ridge_alpha=payload.ridge_alpha,
        parameter_count=structure.parameter_count,
        fit_intercept=payload.fit_intercept,
        standardize=payload.standardize,
        history_guard=payload.history_guard,
    )


def to_validation_data(
    validation: ModelValidation,
    excitation_shortfall: dict[str, dict[str, int]] | None = None,
) -> ModelValidationData:
    return ModelValidationData(
        one_step_fit=_finite(validation.one_step_fit),
        free_run_fit=_finite(validation.free_run_fit),
        free_run_rmse=_finite(validation.free_run_rmse),
        fit_gap=_finite(validation.fit_gap),
        stable=validation.stable,
        max_pole_modulus=_finite(validation.max_pole_modulus),
        steady_state_gains={
            column: value
            for column, value in validation.steady_state_gains.items()
            if np.isfinite(value)
        },
        residual_whiteness_ratio=_finite(validation.residual_whiteness_ratio),
        n_samples=validation.n_samples,
        input_residual_correlations=validation.input_residual_correlations,
        input_residual_test=validation.input_residual_test,
        simulation_status=validation.simulation_status,
        simulation_error_code=validation.simulation_error_code,
        initialization=validation.initialization,
        reference_baselines=validation.reference_baselines,
        input_support=validation.input_support,
        excitation_shortfall=dict(excitation_shortfall or {}),
    )


def _structure(payload: ArxFitRequest, input_columns: list[str]) -> ArxStructure:
    try:
        return ArxStructure.create(
            na=payload.na,
            nb=_orders(payload.nb, input_columns, "nb", 1),
            nk=_orders(payload.delays, input_columns, "delays", 0),
            input_columns=tuple(input_columns),
        )
    except IdentifiabilityError as error:
        raise ModelingDomainError(error.code, error.message, details=error.details) from error


def _split_indices(n_samples: int, payload: ArxFitRequest) -> SplitIndices:
    """Resolve the canonical Train/Validation/Test boundaries for one ARX request."""

    train_end = int(n_samples * payload.train_ratio)
    val_end = int(n_samples * (payload.train_ratio + payload.validation_ratio))
    if val_end >= n_samples:
        raise ModelingDomainError(
            "PARAMETER_OUT_OF_RANGE",
            "训练集与验证集比例之和必须小于 1。",
            details={
                "train_ratio": payload.train_ratio,
                "validation_ratio": payload.validation_ratio,
            },
        )
    return SplitIndices(train_end=train_end, val_end=val_end, test_end=n_samples)


def _theta_from_coefficients(
    structure: ArxStructure, coefficients: dict[str, object]
) -> FloatArray:
    """Restore theta in the single canonical regressor feature-name order."""

    names = structure.feature_names()
    missing = [name for name in names if name not in coefficients]
    unexpected = sorted(set(coefficients) - set(names))
    if missing or unexpected:
        raise ModelingDomainError(
            "MODEL_ARTIFACT_INVALID",
            "ARX 模型 artifact 的系数与模型结构不一致。",
            status_code=422,
            details={"missing": missing, "unexpected": unexpected},
        )
    try:
        theta: FloatArray = np.asarray([float(cast(Any, coefficients[name])) for name in names], dtype=np.float64)
    except (TypeError, ValueError) as error:
        raise ModelingDomainError(
            "MODEL_ARTIFACT_INVALID",
            "ARX 模型 artifact 含有无效系数。",
            status_code=422,
        ) from error
    if not np.all(np.isfinite(theta)):
        raise ModelingDomainError(
            "MODEL_ARTIFACT_INVALID",
            "ARX 模型 artifact 含有非有限系数。",
            status_code=422,
        )
    return theta

def _orders(
    value: dict[str, int] | list[int],
    columns: list[str],
    name: str,
    minimum: int,
) -> dict[str, int]:
    if isinstance(value, list):
        if len(value) != len(columns):
            raise ModelingDomainError(
                "PARAMETER_OUT_OF_RANGE",
                f"{name} 数组长度必须与输入变量数量一致。",
                details={"parameter": name, "expected": len(columns), "actual": len(value)},
            )
        return dict(zip(columns, value, strict=True))
    missing = sorted(set(columns) - set(value))
    if missing:
        raise ModelingDomainError(
            "PARAMETER_OUT_OF_RANGE",
            f"{name} 必须覆盖全部输入变量。",
            details={"parameter": name, "missing": missing},
        )
    return {column: int(value[column]) for column in columns}


def _partition_rows(regressor: RegressorMatrix, start: int, stop: int) -> np.ndarray:
    times = regressor.time_indices
    return np.nonzero((times >= start) & (times < stop))[0]


def _metrics(
    regressor: RegressorMatrix,
    *,
    theta: FloatArray,
    structure: ArxStructure,
    inputs: dict[str, FloatArray],
    output: FloatArray,
    train_end: int,
    val_end: int,
    n_samples: int,
    train_rows: np.ndarray,
    evaluate_test: bool,
    intercept: float = 0.0,
    history_guard: int | None = None,
    fit_intercept: bool = False,
    initialization_policy: str = "fixed",
    initialization_window: int = 32,
) -> ArxMetrics:
    predicted = one_step_predict(regressor, theta, intercept=intercept, output=output,
        initialization_policy=initialization_policy, initialization_window=initialization_window)
    guard = max(structure.max_history, history_guard or 0)
    windows = {
        "train": (0, max(train_end - guard, 0)),
        "validation": (train_end + guard, max(val_end - guard, train_end + guard)),
    }
    if evaluate_test:
        windows["test"] = (val_end + guard, n_samples)
    one_step: dict[str, dict[str, float | None]] = {}
    free_run: dict[str, dict[str, float | None]] = {}
    for label, (start, stop) in windows.items():
        rows = _partition_rows(regressor, start, stop)
        one_step[label] = _scores(regressor.targets[rows], predicted[rows])
        free_run[label] = _free_run_scores(
            theta, structure, inputs=inputs, output=output, start=start, stop=stop,
            intercept=intercept,
            initialization_policy=initialization_policy, initialization_window=initialization_window,
        )

    residual = regressor.targets[train_rows] - predicted[train_rows]
    rss = float(np.dot(residual, residual))
    n_train = int(train_rows.size)
    parameters = int(regressor.n_parameters) + int(fit_intercept)
    aic: float | None = None
    bic: float | None = None
    if rss > 0 and n_train > 0:
        aic = n_train * float(np.log(rss / n_train)) + 2 * parameters
        bic = n_train * float(np.log(rss / n_train)) + parameters * float(np.log(n_train))

    test = one_step.get("test", _empty_scores())
    return ArxMetrics(
        one_step={label: _to_prediction_metrics(scores) for label, scores in one_step.items()},
        free_run={label: _to_prediction_metrics(scores) for label, scores in free_run.items()},
        train_r2=one_step["train"]["r2"],
        train_fit=one_step["train"]["fit"],
        train_rmse=one_step["train"]["rmse"],
        val_r2=one_step["validation"]["r2"],
        val_fit=one_step["validation"]["fit"],
        val_rmse=one_step["validation"]["rmse"],
        test_r2=test["r2"],
        test_fit=test["fit"],
        test_rmse=test["rmse"],
        rmse=test["rmse"],
        mae=test["mae"],
        nrmse=test["nrmse"],
        train_free_run_fit=free_run["train"]["fit"],
        val_free_run_fit=free_run["validation"]["fit"],
        test_free_run_fit=free_run.get("test", _empty_scores())["fit"],
        aic=aic,
        bic=bic,
    )


def _free_run_scores(
    theta: FloatArray,
    structure: ArxStructure,
    *,
    inputs: dict[str, FloatArray],
    output: FloatArray,
    start: int,
    stop: int,
    intercept: float = 0.0,
    initialization_policy: str = "fixed",
    initialization_window: int = 32,
) -> dict[str, float | None]:
    try:
        measured, simulated = free_run_simulate(
            theta, structure, inputs=inputs, output=output, start=start, stop=stop,
            intercept=intercept,
            initialization_policy=initialization_policy, initialization_window=initialization_window,
        )
        return _scores(measured, simulated)
    except IdentifiabilityError:
        return _empty_scores()


def _scores(actual: FloatArray, predicted: FloatArray) -> dict[str, float | None]:
    finite = np.isfinite(actual) & np.isfinite(predicted)
    actual, predicted = actual[finite], predicted[finite]
    if actual.size == 0:
        return {"rmse": None, "mae": None, "r2": None, "fit": None, "nrmse": None}
    residual = actual - predicted
    rmse = float(np.sqrt(np.mean(np.square(residual))))
    offset = actual - actual[0]
    centered = offset - float(np.mean(offset))
    denominator = float(np.dot(centered, centered))
    spread = float(np.percentile(actual, 95) - np.percentile(actual, 5))
    try:
        fit = fit_percentage(actual, predicted)
    except IdentifiabilityError as error:
        if error.code != "FIT_UNDEFINED":
            raise
        fit = None
    return {
        "rmse": rmse,
        "mae": float(np.mean(np.abs(residual))),
        "r2": None if fit is None else float(1 - np.dot(residual, residual) / denominator),
        "fit": fit,
        "nrmse": None if spread == 0 or fit is None else float(rmse / spread),
    }


def _empty_scores() -> dict[str, float | None]:
    return {"rmse": None, "mae": None, "r2": None, "fit": None, "nrmse": None}


def _to_prediction_metrics(scores: dict[str, float | None]) -> PredictionMetrics:
    return PredictionMetrics(**scores)


def _acf(residuals: FloatArray) -> ArxResidualDiagnostics:
    centered = residuals - float(np.mean(residuals))
    denominator = float(np.dot(centered, centered))
    max_lag = min(40, max(0, centered.size - 1))
    if denominator == 0:
        values = [1.0] + [0.0] * max_lag
    else:
        values = [1.0]
        values.extend(
            float(np.dot(centered[:-lag], centered[lag:]) / denominator)
            for lag in range(1, max_lag + 1)
        )
    confidence = None if residuals.size == 0 else float(1.96 / np.sqrt(residuals.size))
    return ArxResidualDiagnostics(acf_values=values, confidence_interval=confidence)


def _check_priors(
    theta: FloatArray,
    structure: ArxStructure,
    payload: ArxFitRequest,
    validation: ModelValidation,
) -> tuple[PriorViolation, ...]:
    """Compare the identified model against what the engineer already knows."""

    violations: list[PriorViolation] = []
    gains = steady_state_gains(theta, structure)
    for column, sign in payload.gain_sign.items():
        gain = gains.get(column)
        if gain is None or not np.isfinite(gain):
            continue
        if (sign == "positive" and gain <= 0) or (sign == "negative" and gain >= 0):
            violations.append(
                PriorViolation(variable=column, kind="gain_sign", expected=sign, actual=float(gain))
            )
    for column, bounds in payload.gain_bounds.items():
        gain = gains.get(column)
        if gain is None or not np.isfinite(gain):
            continue
        low, high = float(bounds[0]), float(bounds[1])
        if not low <= gain <= high:
            violations.append(
                PriorViolation(
                    variable=column,
                    kind="gain_bounds",
                    expected=f"[{low}, {high}]",
                    actual=float(gain),
                )
            )
    if payload.require_stable and not validation.stable:
        violations.append(
            PriorViolation(
                variable="__model__",
                kind="stability",
                expected="all poles inside the unit circle",
                actual=validation.max_pole_modulus,
            )
        )
    return tuple(violations)


def _persist_artifact(
    artifact_root: Path,
    *,
    model_id: UUID,
    series: VersionSeries,
    payload: ArxFitRequest,
    result: ArxCoreResult,
) -> str:
    root = artifact_root / "models"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{model_id}.json"
    document = {
        "model_id": str(model_id),
        "dataset_id": str(series.dataset_id),
        "version_id": str(series.version_id),
        "origin": series.origin,
        "estimator": result.estimator,
        "configuration": payload.model_dump(mode="json"),
        "coefficients": result.coefficients,
        "intercept": result.intercept,
        "preprocessing": result.preprocessing,
        "metrics": result.metrics.model_dump(mode="json"),
        "validation": to_validation_data(result.validation).model_dump(mode="json"),
        "training_rows": result.training_rows,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path.relative_to(artifact_root).as_posix()


async def _persist_run(
    session: AsyncSession,
    *,
    model_id: UUID,
    series: VersionSeries,
    payload: ArxFitRequest,
    result: ArxCoreResult,
) -> UUID:
    now = datetime.now(UTC)
    processing_run_id = uuid4()
    session.add(
        ProcessingRun(
            id=processing_run_id,
            dataset_id=series.dataset_id if series.origin == "dataset" else None,
            source_version_id=series.version_id if series.origin == "dataset" else None,
            run_type="modeling.arx",
            status="succeeded",
            parameters=payload.model_dump(mode="json"),
            result={
                "model_id": str(model_id),
                "metrics": result.metrics.model_dump(mode="json"),
                "validation": to_validation_data(result.validation).model_dump(mode="json"),
                "coefficients": result.coefficients,
                "intercept": result.intercept,
                "preprocessing": result.preprocessing,
                "training_rows": result.training_rows,
            },
            created_at=now,
            finished_at=now,
        )
    )
    session.add(
        OperationLog(
            id=uuid4(),
            event_type="modeling.arx.completed",
            subject_id=str(series.dataset_id),
            payload_json=json.dumps(
                {
                    "model_id": str(model_id),
                    "version_id": str(series.version_id),
                    "val_free_run_fit": result.metrics.val_free_run_fit,
                    "val_one_step_fit": result.metrics.val_fit,
                    "executed_at": now.isoformat(),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            created_at=now,
        )
    )
    await session.commit()
    return processing_run_id


def _finite(value: float | None) -> float | None:
    if value is None:
        return None
    return float(value) if np.isfinite(value) else None


__all__ = [
    "ArxCoreResult",
    "ModelingDomainError",
    "SavedArxModel",
    "evaluate_saved_arx_model",
    "fit_arx_core",
    "fit_arx_on_version",
    "is_stable",
    "load_saved_arx_model",
    "residual_whiteness_ratio",
    "to_validation_data",
]
