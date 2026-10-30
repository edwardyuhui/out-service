"""Control-relevant ARX validation: free-run simulation, stability and steady-state gain.

An APC controller predicts many steps ahead over its horizon, so the metric that decides
whether a model is deployable is the free-run (infinite-step) simulation error, not the
one-step-ahead prediction error. One-step FIT is flattering on any strongly autocorrelated
process output: feeding the *measured* ``y(k-1)`` back into the regressor lets a badly
identified model coast on persistence and still score above 99%.

This module therefore drives the model from the inputs alone after a short warm start,
and adds the two checks an engineer applies before trusting a model at all: is ``A(q)``
stable, and does each steady-state gain have the sign and magnitude the process is known
to have.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from math import erfc, sqrt
from typing import Any, Literal

import numpy as np

from algorithms.identifiability.regressor import (
    ArxStructure,
    FloatArray,
    IdentifiabilityError,
    RegressorMatrix,
    build_regressor,
)

# Fixed numerical safety limit, independent of all measured output amplitudes.
SIMULATION_NUMERICAL_LIMIT = 1e100


@dataclass(frozen=True)
class ModelValidation:
    """Everything needed to accept or reject an identified model."""

    one_step_fit: float
    free_run_fit: float
    free_run_rmse: float
    fit_gap: float
    stable: bool
    max_pole_modulus: float
    steady_state_gains: dict[str, float]
    residual_whiteness_ratio: float
    n_samples: int
    input_residual_correlations: dict[str, list[float]] = field(default_factory=dict)

    input_residual_test: dict[str, Any] = field(default_factory=dict)
    simulation_status: Literal["succeeded", "diverged"] = "succeeded"
    simulation_error_code: str | None = None
    initialization: dict[str, Any] = field(default_factory=dict)
    reference_baselines: dict[str, float | None] = field(default_factory=dict)
    input_support: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "one_step_fit": self.one_step_fit,
            "free_run_fit": self.free_run_fit,
            "free_run_rmse": self.free_run_rmse,
            "fit_gap": self.fit_gap,
            "stable": self.stable,
            "max_pole_modulus": self.max_pole_modulus,
            "steady_state_gains": dict(self.steady_state_gains),
            "residual_whiteness_ratio": self.residual_whiteness_ratio,
            "n_samples": self.n_samples,
            "input_residual_correlations": self.input_residual_correlations,
            "input_residual_test": self.input_residual_test,
            "simulation_status": self.simulation_status,
            "simulation_error_code": self.simulation_error_code,
            "initialization": self.initialization,
            "reference_baselines": self.reference_baselines,
            "input_support": self.input_support,
        }


def unpack_parameters(
    theta: FloatArray,
    structure: ArxStructure,
) -> tuple[FloatArray, dict[str, FloatArray]]:
    """Split a parameter vector into the ``a`` vector and per-input ``b`` vectors."""

    values = np.asarray(theta, dtype=float).ravel()
    if values.size != structure.parameter_count:
        raise IdentifiabilityError(
            "INVALID_DATASET_SCHEMA",
            "参数向量长度与 ARX 结构不一致",
            {"expected": structure.parameter_count, "actual": int(values.size)},
        )
    a_values = values[: structure.na]
    b_values: dict[str, FloatArray] = {}
    offset = structure.na
    for column in structure.input_columns:
        width = structure.nb[column]
        b_values[column] = values[offset : offset + width]
        offset += width
    return a_values, b_values


def is_stable(a_coefficients: FloatArray) -> tuple[bool, float]:
    """Return whether ``A(q) = 1 + a_1 q^-1 + ... `` has all poles inside the unit circle."""

    values = np.asarray(a_coefficients, dtype=float).ravel()
    if values.size == 0:
        return True, 0.0
    polynomial = np.concatenate(([1.0], values))
    roots = np.roots(polynomial)
    if roots.size == 0:
        return True, 0.0
    modulus = float(np.max(np.abs(roots)))
    return bool(modulus < 1.0), modulus


def steady_state_gains(
    theta: FloatArray,
    structure: ArxStructure,
) -> dict[str, float]:
    """Return ``K_j = sum(b_j) / (1 + sum(a))`` for every input.

    This is the number a process engineer can sanity-check directly ("opening the valve
    must raise the temperature"), which is why the closed loop can constrain it from prior
    knowledge instead of hoping the fit gets the sign right.
    """

    a_values, b_values = unpack_parameters(theta, structure)
    denominator = 1.0 + float(np.sum(a_values))
    if abs(denominator) < 1e-12:
        return dict.fromkeys(structure.input_columns, float("inf"))
    return {
        column: float(np.sum(b_values[column]) / denominator) for column in structure.input_columns
    }


def initial_output_offset(
    theta: FloatArray, structure: ArxStructure, *, inputs: Mapping[str, FloatArray],
    output: FloatArray, start: int, intercept: float, window: int,
) -> tuple[float, dict[str, Any]]:
    """Estimate a frozen additive disturbance in the model equation from past residuals.

    For ARX this enters A(q)y = B(q)u + c + d, so its equilibrium output effect
    is d/A(1), not d. FIR has A(1)=1. This assumes a locally constant disturbance;
    it neither refits process coefficients nor updates inside the forecast horizon.
    """
    if structure.na and not is_stable(unpack_parameters(theta, structure)[0])[0]:
        raise IdentifiabilityError("UNSTABLE_MODEL", "历史扰动补偿要求 ARX 模型稳定")
    first = max(structure.max_history, start - window)
    evidence: dict[str, Any] = {"policy": "past_residual", "window": window,
                              "context_start": first, "context_stop": start, "forecast_updates": False,
                              "offset_kind": "equation_disturbance" if structure.na else "output_offset",
                              "assumption": "constant_disturbance_over_forecast"}
    if first >= start:
        return 0.0, {**evidence, "status": "insufficient_history", "samples": 0, "offset": 0.0}
    try:
        context = build_regressor(inputs=dict(inputs), output=output, structure=structure, start=first, stop=start)
    except IdentifiabilityError as error:
        if error.code != "INSUFFICIENT_ROWS":
            raise
        return 0.0, {**evidence, "status": "insufficient_history", "samples": 0, "offset": 0.0}
    residuals = context.targets - context.features @ theta - intercept
    finite = residuals[np.isfinite(residuals)]
    enough = finite.size >= 8
    offset = float(np.median(finite)) if enough else 0.0
    return offset, {**evidence, "status": "initialized" if enough else "insufficient_history",
                    "samples": int(finite.size), "offset": offset}


def one_step_predict(
    regressor: RegressorMatrix, theta: FloatArray, *, intercept: float,
    output: FloatArray, initialization_policy: str = "fixed", initialization_window: int = 32,
) -> FloatArray:
    """One-step observer updates use preceding outputs only; fixed models are unchanged."""
    predicted = regressor.features @ theta + intercept
    if initialization_policy == "fixed":
        return predicted
    if initialization_policy != "past_residual":
        raise IdentifiabilityError("PARAMETER_OUT_OF_RANGE", "未知初始化策略")
    if regressor.structure.na and not is_stable(unpack_parameters(theta, regressor.structure)[0])[0]:
        raise IdentifiabilityError("UNSTABLE_MODEL", "历史扰动补偿要求 ARX 模型稳定")
    residuals = np.full(len(output), np.nan)
    residuals[regressor.time_indices] = regressor.targets - predicted
    padded = np.pad(residuals, (initialization_window, 0), constant_values=np.nan)
    windows = np.lib.stride_tricks.sliding_window_view(padded, initialization_window)[:-1]
    counts = np.sum(np.isfinite(windows), axis=1)
    offsets = np.zeros(len(output))
    active = counts >= 8
    offsets[active] = np.nanmedian(windows[active], axis=1)
    return predicted + offsets[regressor.time_indices]


def free_run_simulate(
    theta: FloatArray,
    structure: ArxStructure,
    *,
    inputs: Mapping[str, FloatArray],
    output: FloatArray,
    start: int,
    stop: int,
    intercept: float = 0.0,
    initialization_policy: str = "fixed",
    initialization_window: int = 32,
) -> tuple[FloatArray, FloatArray]:
    """Simulate the output from the inputs alone over ``[start, stop)``.

    Only output history strictly before ``start`` seeds the recursion. Every scored
    sample uses the model's predictions; optional disturbance estimation also uses
    preceding history only. Returns aligned measured and simulated slices.
    """

    if initialization_policy not in {"fixed", "past_residual"}:
        raise IdentifiabilityError("PARAMETER_OUT_OF_RANGE", "未知初始化策略")
    a_values, b_values = unpack_parameters(theta, structure)
    measured = np.asarray(output, dtype=float)
    n_samples = int(measured.shape[0])
    first = max(start, structure.max_history)
    last = min(stop, n_samples)
    if last - first <= structure.na:
        raise IdentifiabilityError(
            "INSUFFICIENT_ROWS",
            "自由仿真区间长度不足",
            {"start": first, "stop": last, "na": structure.na},
        )
    signals = {
        column: np.asarray(inputs[column], dtype=float) for column in structure.input_columns
    }

    # The input contribution does not depend on the simulated output, so it is computed
    # for the whole horizon at once. Only the output feedback has to stay sequential,
    # which turns the inner loop from O(horizon * inputs * nb) Python operations into
    # O(horizon * na) — the closed-loop optimiser runs this thousands of times.
    offset = 0.0
    if initialization_policy == "past_residual":
        offset, _ = initial_output_offset(theta, structure, inputs=inputs, output=measured,
            start=first, intercept=intercept, window=initialization_window)
    contribution = np.full(n_samples, intercept + offset, dtype=float)
    index = np.arange(first, last, dtype=int)
    for column in structure.input_columns:
        signal = signals[column]
        delay = structure.nk[column]
        coefficients = b_values[column]
        for lag in range(structure.nb[column]):
            contribution[index] += coefficients[lag] * signal[index - delay - lag]

    simulated = measured.copy()
    for time_index in range(first, last):
        value = float(contribution[time_index])
        for lag in range(1, structure.na + 1):
            value -= a_values[lag - 1] * simulated[time_index - lag]
        if not np.isfinite(value) or abs(value) > SIMULATION_NUMERICAL_LIMIT:
            raise IdentifiabilityError(
                "SIMULATION_DIVERGED", "自由仿真超过固定数值安全界限",
                {"sample_index": time_index, "limit": SIMULATION_NUMERICAL_LIMIT},
            )
        simulated[time_index] = value

    return measured[first:last], simulated[first:last]


def fit_percentage(actual: FloatArray, predicted: FloatArray) -> float:
    """Return raw identification FIT; arbitrarily poor predictions remain distinguishable."""

    measured = np.asarray(actual, dtype=float)
    estimate = np.asarray(predicted, dtype=float)
    if measured.size == 0:
        raise IdentifiabilityError("FIT_UNDEFINED", "输出为空，FIT 无定义")
    # Subtract the first value before averaging to avoid cancellation at a large
    # engineering offset. Numerically constant outputs have no meaningful FIT.
    offset = measured - measured[0]
    centered = offset - float(np.mean(offset))
    denominator = float(np.linalg.norm(centered))
    tolerance = 8 * np.finfo(float).eps * max(1.0, float(np.max(np.abs(measured))))
    if denominator == 0 or float(np.ptp(measured)) <= tolerance:
        raise IdentifiabilityError(
            "FIT_UNDEFINED",
            "输出恒定，FIT 无定义",
        )
    residual = float(np.linalg.norm(measured - estimate))
    return float(100.0 * (1.0 - residual / denominator))


def residual_whiteness_ratio(residuals: FloatArray, *, max_lag: int = 20) -> float:
    """Fraction of residual autocorrelation lags inside the 95% white-noise band.

    This is descriptive evidence. Colored measurement noise can remain in FIR residuals;
    autocorrelation alone does not establish missing deterministic dynamics.
    """

    values = np.asarray(residuals, dtype=float).ravel()
    values = values[np.isfinite(values)]
    if values.size < 8:
        return float("nan")
    centered = values - float(np.mean(values))
    denominator = float(np.dot(centered, centered))
    if denominator == 0:
        return 1.0
    lags = min(max_lag, values.size - 1)
    bound = 1.96 / np.sqrt(values.size)
    inside = 0
    for lag in range(1, lags + 1):
        correlation = float(np.dot(centered[:-lag], centered[lag:]) / denominator)
        if abs(correlation) <= bound:
            inside += 1
    return inside / lags if lags else float("nan")


def input_residual_correlations(
    residuals: FloatArray,
    time_indices: np.ndarray,
    *,
    inputs: Mapping[str, FloatArray],
    max_lag: int = 20,
) -> dict[str, list[float]]:
    """Correlate one-step residuals with past inputs on the same evaluation rows.

    These are diagnostic associations; they do not identify a unique failure cause.
    """
    result: dict[str, list[float]] = {}
    for column, signal in inputs.items():
        correlations: list[float] = []
        for lag in range(min(max_lag, max(0, residuals.size - 2)) + 1):
            valid = time_indices - lag >= 0
            r = residuals[valid]
            u = np.asarray(signal, dtype=float)[time_indices[valid] - lag]
            finite = np.isfinite(r) & np.isfinite(u)
            r, u = r[finite], u[finite]
            if r.size < 3:
                correlations.append(0.0)
                continue
            r, u = r - np.mean(r), u - np.mean(u)
            norm = float(np.linalg.norm(r) * np.linalg.norm(u))
            correlations.append(float(r @ u / norm) if norm > 0 else 0.0)
        result[column] = correlations
    return result


def input_residual_test(
    residuals: FloatArray,
    time_indices: np.ndarray,
    *,
    inputs: Mapping[str, FloatArray],
    max_lag: int = 20,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Holm family-wise correction with conservative Bartlett variance inflation.

    This is an approximate stationary-series diagnostic, not a causal test. Positive
    absolute ACF products prevent anti-correlations from understating uncertainty.
    Gapped or short samples are explicitly inconclusive rather than concatenated.
    """
    tests: list[dict[str, Any]] = []
    if residuals.size < 30 or np.any(np.diff(time_indices) != 1):
        return {"method": "holm_bartlett_v1", "status": "inconclusive",
                "alpha": alpha, "rejected_channels": [], "tests": []}

    def acf(values: FloatArray) -> FloatArray:
        centered = values - np.mean(values)
        norm = float(centered @ centered)
        if norm <= 0:
            return np.zeros(min(max_lag, values.size // 4))
        return np.asarray([centered[:-k] @ centered[k:] / norm
                           for k in range(1, min(max_lag, values.size // 4) + 1)])

    for column, signal in inputs.items():
        for lag in range(min(max_lag, residuals.size - 2) + 1):
            valid = time_indices >= lag
            r = np.asarray(residuals[valid], dtype=float)
            u = np.asarray(signal, dtype=float)[time_indices[valid] - lag]
            if r.size < 30 or not np.all(np.isfinite(r) & np.isfinite(u)):
                continue
            left, right = r - np.mean(r), u - np.mean(u)
            norm = float(np.linalg.norm(left) * np.linalg.norm(right))
            correlation = float(left @ right / norm) if norm > 0 else 0.0
            inflation = 1.0 + 2.0 * float(np.sum(np.abs(acf(r) * acf(u))))
            effective_n = max(3.0, r.size / inflation)
            # Bartlett's asymptotic normal approximation; Holm covers all inputs/lags.
            p_value = erfc(abs(correlation) * sqrt(effective_n / 2.0))
            tests.append({"channel": column, "lag": lag, "correlation": correlation,
                          "n_samples": int(r.size), "effective_n": effective_n,
                          "p_value": p_value})
    previous = 0.0
    for rank, item in enumerate(sorted(tests, key=lambda item: item["p_value"])):
        previous = max(previous, min(1.0, (len(tests) - rank) * item["p_value"]))
        item["adjusted_p_value"] = previous
        item["rejected"] = previous <= alpha
    return {"method": "holm_bartlett_v1", "status": "evaluated", "alpha": alpha,
            "assumption": "approximate stationary covariance; association only",
            "family_size": len(tests),
            "rejected_channels": sorted({item["channel"] for item in tests if item["rejected"]}),
            "tests": tests}


def validate_model(
    theta: FloatArray,
    structure: ArxStructure,
    *,
    inputs: Mapping[str, FloatArray],
    output: FloatArray,
    start: int,
    stop: int,
    intercept: float = 0.0,
    initialization_policy: str = "fixed",
    initialization_window: int = 32,
) -> ModelValidation:
    """Score a model the way an APC engineer would before deploying it."""

    simulation_error_code = None
    try:
        measured, simulated = free_run_simulate(
            theta, structure, inputs=inputs, output=output,
            start=start, stop=stop, intercept=intercept,
            initialization_policy=initialization_policy, initialization_window=initialization_window,
        )
        free_run_rmse = float(np.sqrt(np.mean(np.square(measured - simulated))))
        try:
            free_run = fit_percentage(measured, simulated)
        except IdentifiabilityError as error:
            if error.code != "FIT_UNDEFINED":
                raise
            free_run = float("nan")
    except IdentifiabilityError as error:
        if error.code != "SIMULATION_DIVERGED":
            raise
        # Preserve one-step diagnostics and coefficients; no fabricated trajectory or
        # finite FIT is substituted for a failed simulation. The optimizer rejects it.
        measured = np.asarray(output[max(start, structure.max_history):stop])
        free_run = free_run_rmse = float("nan")
        simulation_error_code = error.code

    regressor = build_regressor(
        inputs=dict(inputs),
        output=np.asarray(output, dtype=float),
        structure=structure,
        start=start,
        stop=stop,
    )
    prediction_regressor = regressor
    if initialization_policy == "past_residual":
        prediction_regressor = build_regressor(inputs=dict(inputs), output=np.asarray(output, dtype=float),
                                               structure=structure, stop=stop)
    predicted_all = one_step_predict(prediction_regressor, np.asarray(theta, dtype=float).ravel(), intercept=intercept,
        output=output, initialization_policy=initialization_policy, initialization_window=initialization_window)
    predicted = predicted_all[np.searchsorted(prediction_regressor.time_indices, regressor.time_indices)]
    try:
        one_step = fit_percentage(regressor.targets, predicted)
    except IdentifiabilityError as error:
        if error.code != "FIT_UNDEFINED":
            raise
        one_step = float("nan")
    residuals = regressor.targets - predicted

    a_values, _ = unpack_parameters(theta, structure)
    stable, modulus = is_stable(a_values)
    initialization: dict[str, Any] = {"policy": "fixed"}
    if initialization_policy == "past_residual":
        _, initialization = initial_output_offset(theta, structure, inputs=inputs, output=output,
            start=max(start, structure.max_history), intercept=intercept, window=initialization_window)
    first = max(start, structure.max_history)
    persistence_rmse = None
    if first > 0 and np.isfinite(output[first - 1]) and np.all(np.isfinite(measured)):
        persistence_rmse = float(np.sqrt(np.mean((measured - output[first - 1]) ** 2)))
    reference_baselines = {"persistence_rmse": persistence_rmse,
        "skill_vs_persistence": float(1 - free_run_rmse / persistence_rmse) if persistence_rmse and np.isfinite(free_run_rmse) else None}
    return ModelValidation(
        initialization=initialization, reference_baselines=reference_baselines,
        one_step_fit=one_step,
        simulation_status="diverged" if simulation_error_code else "succeeded",
        simulation_error_code=simulation_error_code,
        free_run_fit=free_run,
        free_run_rmse=free_run_rmse,
        fit_gap=one_step - free_run,
        input_residual_correlations=input_residual_correlations(
            residuals, regressor.time_indices, inputs=inputs
        ),
        input_residual_test=input_residual_test(residuals, regressor.time_indices, inputs=inputs),
        stable=stable,
        max_pole_modulus=modulus,
        steady_state_gains=steady_state_gains(theta, structure),
        residual_whiteness_ratio=residual_whiteness_ratio(residuals),
        n_samples=int(measured.size),
    )
