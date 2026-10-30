"""Experimental shared-denominator MISO OE identification on contiguous Train data.

The loss uses simulated output, with measured history only before the simulation
start. Schur reflection coefficients constrain the denominator to be stable at
every solver iterate. This is an offline experiment, not an ARX API estimator.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.optimize import least_squares
from scipy.signal import lfilter, lfiltic

from algorithms.identifiability.regressor import (
    ArxStructure,
    FloatArray,
    IdentifiabilityError,
    build_regressor,
)
from algorithms.identifiability.validation import is_stable


def reflection_to_denominator(reflection: FloatArray) -> FloatArray:
    """Schur step-up recursion for a monic real stable denominator."""
    values = np.asarray(reflection, dtype=float)
    if values.ndim != 1 or not np.all(np.isfinite(values)) or np.any(abs(values) >= 1):
        raise IdentifiabilityError("PARAMETER_OUT_OF_RANGE", "反射系数必须有限且位于 (-1, 1)")
    polynomial = np.empty(0)
    for coefficient in values:
        polynomial = np.r_[polynomial + coefficient * polynomial[::-1], coefficient]
    return polynomial


def _denominator_to_reflection(polynomial: FloatArray) -> FloatArray:
    current = np.asarray(polynomial, dtype=float).copy()
    reflection = np.zeros(len(current))
    for order in range(len(current), 0, -1):
        coefficient = current[-1]
        if not np.isfinite(coefficient) or abs(coefficient) >= .995:
            return np.zeros(len(polynomial))
        reflection[order - 1] = coefficient
        current = (current[:-1] - coefficient * current[:-1][::-1]) / (1 - coefficient**2)
    return reflection


@dataclass(frozen=True)
class OutputErrorEstimate:
    theta: FloatArray
    intercept: float
    diagnostics: dict[str, Any]


def fit_output_error(
    *, inputs: Mapping[str, FloatArray], output: FloatArray, structure: ArxStructure,
    train_stop: int, start: int | None = None, ridge_alpha: float = .01,
    max_nfev: int = 100,
) -> OutputErrorEstimate:
    """Fit y=sum(B/F*u)+offset+e using Train-only affine scaling and two starts.

    ``na`` stores the shared process denominator order ``nf``. No measured output
    is fed back inside the fitted horizon. Gapped selection is deliberately not
    supported: concatenating disconnected windows would change the dynamics.
    Regularization is alpha*||[F_without_leading_1,B]||² plus mean squared
    normalized simulation error; the equation intercept is unpenalized.
    """
    first = structure.max_history if start is None else start
    if not 1 <= structure.na <= 4 or first < structure.max_history:
        raise IdentifiabilityError("PARAMETER_OUT_OF_RANGE", "实验 OE 分母阶数应为 1–4，起点需包含历史")
    if (not isinstance(train_stop, int) or train_stop > len(output)
            or train_stop - first < max(16, 2 * structure.parameter_count + 1)):
        raise IdentifiabilityError("INSUFFICIENT_ROWS", "OE 连续训练区间不足")
    if not np.isfinite(ridge_alpha) or ridge_alpha < 0 or max_nfev < 1:
        raise IdentifiabilityError("PARAMETER_OUT_OF_RANGE", "OE 正则化或迭代预算无效")
    y = np.asarray(output[:train_stop], dtype=float)
    u = {c: np.asarray(inputs[c][:train_stop], dtype=float) for c in structure.input_columns}
    if any(v.ndim != 1 or len(v) != train_stop or not np.all(np.isfinite(v))
           for v in [y, *u.values()]):
        raise IdentifiabilityError("INVALID_DATASET_SCHEMA", "OE 训练前缀必须连续且有限")
    y_center, y_scale = float(np.mean(y[first:])), float(np.std(y[first:]))
    if y_scale <= np.finfo(float).eps * max(1., abs(y_center)):
        raise IdentifiabilityError("FIT_UNDEFINED", "OE 训练输出恒定")
    centers = {c: float(np.mean(v[first:])) for c, v in u.items()}
    scales = {c: float(np.std(v[first:])) or 1. for c, v in u.items()}
    normalized_y = (y - y_center) / y_scale
    normalized_u = {c: (v - centers[c]) / scales[c] for c, v in u.items()}
    regressor = build_regressor(inputs=normalized_u, output=normalized_y, structure=structure,
                                start=first, stop=train_stop)
    n = train_stop - first
    design = np.column_stack((regressor.features, np.ones(n)))
    penalty = np.diag(np.r_[np.full(structure.parameter_count, np.sqrt(ridge_alpha * n)), 0.])
    seed = np.linalg.lstsq(np.vstack((design, penalty)),
                           np.r_[regressor.targets, np.zeros(design.shape[1])], rcond=None)[0]
    input_features = regressor.features[:, structure.na:]

    def decoded(parameters: FloatArray) -> FloatArray:
        return np.r_[reflection_to_denominator(parameters[:structure.na]), parameters[structure.na:]]

    def simulate(parameters: FloatArray) -> FloatArray:
        coefficients = decoded(parameters)
        denominator = np.r_[1., coefficients[:structure.na]]
        contribution = input_features @ coefficients[structure.na:-1] + coefficients[-1]
        initial = lfiltic([1.], denominator, normalized_y[first-structure.na:first][::-1])
        return lfilter([1.], denominator, contribution, zi=initial)[0]

    residual_calls = 0

    def residual(parameters: FloatArray) -> FloatArray:
        nonlocal residual_calls
        residual_calls += 1
        coefficients = decoded(parameters)
        return np.r_[(simulate(parameters) - normalized_y[first:]) / np.sqrt(n),
                     np.sqrt(ridge_alpha) * coefficients[:-1]]

    seeds = [np.r_[_denominator_to_reflection(seed[:structure.na]), seed[structure.na:]],
             np.r_[np.zeros(structure.na), seed[structure.na:]]]
    lower = np.r_[np.full(structure.na, -.995), np.full(len(seed)-structure.na, -np.inf)]
    upper = np.r_[np.full(structure.na, .995), np.full(len(seed)-structure.na, np.inf)]
    runs = [least_squares(residual, initial, bounds=(lower, upper), max_nfev=max_nfev)
            for initial in seeds]
    successful = [run for run in runs if run.success and np.all(np.isfinite(run.x))]
    if not successful:
        raise IdentifiabilityError("OE_NOT_CONVERGED", "OE 在预设预算内未收敛",
                                   {"starts": [{"nfev": r.nfev, "status": r.status} for r in runs]})
    best = min(successful, key=lambda run: float(np.dot(run.fun, run.fun)))
    coefficients = decoded(best.x)
    theta = coefficients[:-1].copy()
    position = structure.na
    for c in structure.input_columns:
        theta[position:position+structure.nb[c]] *= y_scale / scales[c]
        position += structure.nb[c]
    intercept = y_center * (1 + np.sum(theta[:structure.na])) + y_scale * coefficients[-1]
    position = structure.na
    for c in structure.input_columns:
        intercept -= centers[c] * np.sum(theta[position:position+structure.nb[c]])
        position += structure.nb[c]
    stable, pole = is_stable(theta[:structure.na])
    if not stable:
        raise IdentifiabilityError("NUMERICAL_INSTABILITY", "OE 稳定参数转换失败")
    return OutputErrorEstimate(theta, float(intercept), {
        "model_type": "OE", "denominator": "shared", "estimation_loss": "train_free_run_mse",
        "train_start": first, "train_stop": train_stop, "training_rows": n,
        "ridge_alpha": ridge_alpha, "max_nfev_per_start": max_nfev,
        "residual_evaluations_including_jacobian": residual_calls,
        "solver_starts": [{"nfev": r.nfev, "status": r.status, "cost": float(r.cost)} for r in runs],
        "reflection_coefficients": best.x[:structure.na].tolist(), "max_pole_modulus": pole,
        "train_simulation_rmse": float(np.sqrt(np.mean((simulate(best.x) - normalized_y[first:])**2)) * y_scale),
        "input_center": centers, "input_scale": scales, "output_center": y_center, "output_scale": y_scale,
        "initialization_policy": "fixed_measured_history_before_start", "forecast_updates": False,
    })
