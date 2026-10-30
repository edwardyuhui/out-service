"""Train-only affine ARX estimation with scale-invariant regularisation and Huber IRLS."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from algorithms.identifiability.regressor import ArxStructure, FloatArray, IdentifiabilityError

Estimator = Literal["ols", "ridge", "huber"]


@dataclass(frozen=True)
class ParameterEstimate:
    theta: FloatArray
    intercept: float
    feature_center: FloatArray
    feature_scale: FloatArray
    output_center: float
    output_scale: float
    iterations: int
    effective_parameters: float
    downweighted_rows: int

    def preprocessing(self) -> dict[str, object]:
        return {
            "policy_version": "train_affine_v1",
            "feature_center": self.feature_center.tolist(),
            "feature_scale": self.feature_scale.tolist(),
            "output_center": self.output_center,
            "output_scale": self.output_scale,
            "iterations": self.iterations,
            "effective_parameters": self.effective_parameters,
            "downweighted_rows": self.downweighted_rows,
        }


def estimate_parameters(
    features: FloatArray,
    targets: FloatArray,
    *,
    estimator: Estimator,
    ridge_alpha: float = 0.0,
    fit_intercept: bool = True,
    standardize: bool = True,
    sample_weights: FloatArray | None = None,
    huber_delta: float = 1.345,
    max_iterations: int = 50,
    prior_covariance: FloatArray | None = None,
) -> ParameterEstimate:
    """Fit only the supplied training rows; return coefficients in original units.

    Huber suppresses large residuals, but does not correct errors-in-variables or
    closed-loop identification bias. Reliability weights are fixed by the caller.
    """
    x = np.asarray(features, dtype=float)
    y = np.asarray(targets, dtype=float)
    weights = np.ones(y.size) if sample_weights is None else np.asarray(sample_weights, dtype=float)
    if weights.shape != y.shape or np.any(~np.isfinite(weights)) or np.any(weights < 0):
        raise IdentifiabilityError("PARAMETER_OUT_OF_RANGE", "样本可靠性权重无效")
    minimum = 8 if estimator != "ols" and ridge_alpha > 0 else x.shape[1] + 1
    if np.count_nonzero(weights) < minimum:
        raise IdentifiabilityError("INSUFFICIENT_ROWS", "正权重训练样本不足")
    center = np.average(x, axis=0, weights=weights) if fit_intercept else np.zeros(x.shape[1])
    y_center = float(np.average(y, weights=weights)) if fit_intercept else 0.0
    scale = np.sqrt(np.average((x - center) ** 2, axis=0, weights=weights))
    scale = np.where(scale > np.finfo(float).eps * np.maximum(1.0, np.abs(center)), scale, 1.0)
    if not standardize:
        scale = np.ones(x.shape[1])
    train_output_scale = float(np.sqrt(np.average((y - np.average(y, weights=weights)) ** 2, weights=weights)))
    y_scale = train_output_scale if standardize and train_output_scale > 0 else 1.0
    z = (x - center) / scale
    target = (y - y_center) / y_scale
    design = np.column_stack((z, np.ones(y.size))) if fit_intercept else z
    alpha = 0.0 if estimator == "ols" else max(0.0, ridge_alpha)
    covariance = np.eye(x.shape[1]) if prior_covariance is None else np.asarray(prior_covariance, dtype=float)
    if covariance.shape != (x.shape[1], x.shape[1]) or not np.all(np.isfinite(covariance)):
        raise IdentifiabilityError("PARAMETER_OUT_OF_RANGE", "正则核维度或数值无效")
    try:
        # Penalise standardized slopes, independently for each input channel. The
        # intercept has a flat prior and is never regularized.
        root_precision = np.eye(x.shape[1]) if prior_covariance is None else np.linalg.solve(
            np.linalg.cholesky(covariance), np.eye(x.shape[1]))
    except np.linalg.LinAlgError as error:
        raise IdentifiabilityError("NUMERICAL_INSTABILITY", "正则核必须正定") from error
    penalty_root = np.sqrt(alpha) * root_precision
    if fit_intercept:
        penalty_root = np.column_stack((penalty_root, np.zeros(x.shape[1])))

    def solve(w: FloatArray) -> FloatArray:
        root = np.sqrt(w)
        augmented_x = np.vstack((design * root[:, None], penalty_root))
        augmented_y = np.concatenate((target * root, np.zeros(x.shape[1])))
        return np.asarray(np.linalg.lstsq(augmented_x, augmented_y, rcond=None)[0], dtype=float)

    coefficient = solve(weights)
    robust_weights = np.ones(y.size)
    iterations = 1
    if estimator == "huber":
        for iteration in range(1, max_iterations + 1):
            iterations = iteration
            residual = target - design @ coefficient
            active_residual = residual[weights > 0]
            sigma = 1.4826 * float(np.median(np.abs(active_residual - np.median(active_residual))))
            if sigma <= 1e-12:
                break
            robust_weights = np.minimum(1.0, huber_delta * sigma / np.maximum(np.abs(residual), 1e-15))
            updated = solve(weights * robust_weights)
            converged = np.linalg.norm(updated - coefficient) <= 1e-7 * (1.0 + np.linalg.norm(coefficient))
            coefficient = updated
            if converged:
                break
    weighted_design = design * np.sqrt(weights * robust_weights)[:, None]
    gram = weighted_design.T @ weighted_design
    effective_parameters = float(np.trace(np.linalg.solve(
        gram + penalty_root.T @ penalty_root, gram))) if alpha > 0 else float(np.linalg.matrix_rank(weighted_design))
    slopes = coefficient[:x.shape[1]] * y_scale / scale
    bias = y_center - float(center @ slopes)
    if fit_intercept:
        bias += float(coefficient[-1] * y_scale)
    return ParameterEstimate(
        theta=slopes,
        intercept=bias,
        feature_center=center,
        feature_scale=scale,
        output_center=y_center,
        output_scale=train_output_scale,
        iterations=iterations,
        effective_parameters=effective_parameters,
        downweighted_rows=int(np.count_nonzero((robust_weights < 0.99) & (weights > 0))),
    )


def tc_prior_covariance(structure: ArxStructure, decay: float) -> FloatArray:
    """Tuned-correlated FIR kernel K(i,j)=beta**max(i,j), per input channel.

    Indices begin at one; each block is divided by its first diagonal entry so
    ridge alpha has a comparable scale across candidate decay values.
    """
    if structure.na != 0 or not 0 < decay < 1:
        raise IdentifiabilityError("PARAMETER_OUT_OF_RANGE", "TC 核仅适用于 FIR 且 0<beta<1")
    covariance = np.zeros((structure.parameter_count, structure.parameter_count))
    offset = 0
    for column in structure.input_columns:
        width = structure.nb[column]
        lags = np.arange(width)
        block = decay ** np.maximum.outer(lags, lags)
        covariance[offset:offset + width, offset:offset + width] = block
        offset += width
    return covariance
