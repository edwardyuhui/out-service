"""Estimate shared within-run dynamics with separate operating-point intercepts.

This experimental estimator removes each run's regressor/target means before
pooling. Between-run level differences therefore cannot identify dynamic gains.
New-run offsets still require strictly preceding measurements and independent
validation; they do not establish the equilibrium response to changed controls.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from algorithms.identifiability.estimation import ParameterEstimate, estimate_parameters
from algorithms.identifiability.experiments import TrainingExperiment
from algorithms.identifiability.regressor import ArxStructure, IdentifiabilityError, build_regressor
from algorithms.identifiability.support import training_input_support


@dataclass(frozen=True)
class OperatingPointEstimate:
    parameters: ParameterEstimate
    run_intercepts: dict[str, float]
    lineage: list[dict[str, object]]
    input_support: dict[str, dict[str, object]]
    excitation: dict[str, dict[str, object]]


def fit_within_run_arx(
    experiments: Sequence[TrainingExperiment], *, structure: ArxStructure,
    ridge_alpha: float, balance_runs: bool = True,
) -> OperatingPointEstimate:
    """Fit dynamics from within-run changes; no tail or cross-run lag is used."""
    if not experiments or len({e.name for e in experiments}) != len(experiments):
        raise IdentifiabilityError("INVALID_DATASET_SCHEMA", "训练运行不能为空，且名称必须唯一")
    regressors, supports = [], []
    for e in experiments:
        if e.start < structure.max_history or e.stop > len(e.output) or e.stop <= e.start:
            raise IdentifiabilityError("PARAMETER_OUT_OF_RANGE", "运行训练边界无效")
        reg = build_regressor(inputs=e.inputs, output=e.output, structure=structure,
            start=e.start, stop=e.stop)
        if reg.n_rows < 8:
            raise IdentifiabilityError("INSUFFICIENT_ROWS", "每条运行至少需要八个有效训练行")
        regressors.append(reg)
        lags = {c: (structure.nk[c], structure.nk[c]+structure.nb[c]-1)
            for c in structure.input_columns}
        supports.append(training_input_support(e.inputs, reg.time_indices, input_lags=lags))
    total = sum(r.n_rows for r in regressors)
    weights = [np.full(r.n_rows, total/(len(regressors)*r.n_rows) if balance_runs else 1.)
        for r in regressors]
    centers = [r.features.mean(axis=0) for r in regressors]
    levels = [float(r.targets.mean()) for r in regressors]
    centered_features = []
    for r, center in zip(regressors, centers, strict=True):
        values = r.features-center
        constant = np.ptp(r.features, axis=0) <= 8*np.finfo(float).eps*np.maximum(1., abs(center))
        values[:, constant] = 0.
        centered_features.append(values)
    estimate = estimate_parameters(
        np.vstack(centered_features),
        np.concatenate([r.targets-level for r, level in zip(regressors, levels, strict=True)]),
        estimator="ridge", ridge_alpha=ridge_alpha, fit_intercept=False,
        standardize=True, sample_weights=np.concatenate(weights))
    intercepts = {e.name: float(level-center @ estimate.theta)
        for e, level, center in zip(experiments, levels, centers, strict=True)}
    reference_intercept = float(np.average(list(intercepts.values()),
        weights=[float(w.sum()) for w in weights]))
    parameters = ParameterEstimate(theta=estimate.theta, intercept=reference_intercept,
        feature_center=estimate.feature_center, feature_scale=estimate.feature_scale,
        output_center=estimate.output_center, output_scale=estimate.output_scale,
        iterations=estimate.iterations, effective_parameters=estimate.effective_parameters,
        downweighted_rows=estimate.downweighted_rows)
    excitation, support = {}, {}
    for c in structure.input_columns:
        refs = [s[c] for s in supports]
        support[c] = {"minimum": min(r["minimum"] for r in refs),
            "maximum": max(r["maximum"] for r in refs),
            "constant": bool(all(r["constant"] for r in refs)
                and max(r["maximum"] for r in refs)-min(r["minimum"] for r in refs) <= 1e-10),
            "modelled": True, "lag_minimum": structure.nk[c],
            "lag_maximum": structure.nk[c]+structure.nb[c]-1}
        dynamic = any(not r["constant"] for r in refs)
        excitation[c] = {"within_run_variation": dynamic,
            "between_run_only": bool(not dynamic and not support[c]["constant"]),
            "dynamic_gain_identified": False,
            "interpretation": "within-run variation is necessary, not sufficient for identification",
            "run_references": {e.name: r for e, r in zip(experiments, refs, strict=True)}}
    lineage = [{"name": e.name, "train_start": e.start, "train_stop": e.stop,
        "original_indices": r.time_indices.tolist(), "training_rows": r.n_rows,
        "total_weight": float(w.sum()), "feature_mean": center.tolist(),
        "target_mean": level, "intercept": intercepts[e.name]}
        for e, r, w, center, level in zip(experiments, regressors, weights, centers, levels, strict=True)]
    return OperatingPointEstimate(parameters, intercepts, lineage, support, excitation)
