"""Pool independent ARX Train experiments without creating artificial boundaries."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from algorithms.identifiability.estimation import ParameterEstimate, estimate_parameters
from algorithms.identifiability.regressor import (
    ArxStructure,
    FloatArray,
    IdentifiabilityError,
    build_regressor,
)
from algorithms.identifiability.support import training_input_support


@dataclass(frozen=True)
class TrainingExperiment:
    name: str
    inputs: Mapping[str, FloatArray]
    output: FloatArray
    start: int
    stop: int


@dataclass(frozen=True)
class ExperimentEstimate:
    parameters: ParameterEstimate
    lineage: list[dict[str, object]]
    input_support: dict[str, dict[str, object]]


def fit_arx_experiments(
    experiments: Sequence[TrainingExperiment], *, structure: ArxStructure,
    ridge_alpha: float, balance_runs: bool = True,
) -> ExperimentEstimate:
    """Share coefficients across physical runs, preserving each run's lag history.

    Each supplied start/stop is a Train interval. Validation and Test tails do not
    participate in features, scaling, weights or input-support diagnostics. Equal
    total weight per run prevents the longest steady run from dominating the fit.
    Pooling estimates associations; diverse runs alone do not establish causality.
    """
    if not experiments or len({e.name for e in experiments}) != len(experiments):
        raise IdentifiabilityError("INVALID_DATASET_SCHEMA", "训练运行不能为空，且名称必须唯一")
    regressors = []
    for experiment in experiments:
        if experiment.start < structure.max_history or experiment.stop > len(experiment.output):
            raise IdentifiabilityError("PARAMETER_OUT_OF_RANGE", "运行训练边界不足以包含模型历史")
        regressors.append(build_regressor(inputs=experiment.inputs, output=experiment.output,
            structure=structure, start=experiment.start, stop=experiment.stop))
    total = sum(reg.n_rows for reg in regressors)
    weights = np.concatenate([np.full(reg.n_rows, total/(len(regressors)*reg.n_rows) if balance_runs else 1.)
                              for reg in regressors])
    parameters = estimate_parameters(np.vstack([r.features for r in regressors]),
        np.concatenate([r.targets for r in regressors]), estimator="ridge", ridge_alpha=ridge_alpha,
        fit_intercept=True, standardize=True, sample_weights=weights)
    support = {}
    lags = {c: (structure.nk[c], structure.nk[c]+structure.nb[c]-1)
        for c in structure.input_columns}
    references = [training_input_support(e.inputs, r.time_indices, input_lags=lags)
        for e, r in zip(experiments, regressors, strict=True)]
    for column in structure.input_columns:
        indices = [np.unique(np.concatenate([r.time_indices-lag
            for lag in range(lags[column][0], lags[column][1]+1)])) for r in regressors]
        values = np.concatenate([np.asarray(e.inputs[column])[i]
            for e, i in zip(experiments, indices, strict=True)])
        low, high = float(np.min(values)), float(np.max(values))
        constant = bool(high-low <= 8*np.finfo(float).eps*max(1., abs(low), abs(high)))
        within = any(not ref[column]["constant"] for ref in references)
        support[column] = {"minimum": low, "maximum": high, "std": float(np.std(values)),
            "constant": constant, "lag_minimum": lags[column][0], "lag_maximum": lags[column][1],
            "modelled": True, "within_run_variation": within,
            "between_run_only": bool(not within and not constant),
            "run_references": {e.name: ref[column]
                for e, ref in zip(experiments, references, strict=True)}}
    lineage = [{"name": e.name, "train_start": e.start, "train_stop": e.stop,
                "training_rows": r.n_rows, "original_indices": r.time_indices.tolist(),
                "total_weight": float(np.sum(weights[sum(x.n_rows for x in regressors[:i]):sum(x.n_rows for x in regressors[:i+1])]))}
               for i, (e, r) in enumerate(zip(experiments, regressors, strict=True))]
    return ExperimentEstimate(parameters, lineage, support)
