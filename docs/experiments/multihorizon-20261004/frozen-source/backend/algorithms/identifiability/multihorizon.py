"""Stable linear dynamics fitted to several simulation horizons on separate runs.

This is an output-error estimator: observations initialize each training block,
then the block is simulated without measured-output feedback. Zero denotes the
entire supplied interval. Intervals may be selected disjoint segments; their
histories stay in their original runs and are never concatenated.
"""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from scipy.optimize import least_squares
from scipy.signal import lfilter, lfiltic

from algorithms.identifiability.experiments import TrainingExperiment
from algorithms.identifiability.output_error import (
    OutputErrorEstimate,
    _denominator_to_reflection,
    reflection_to_denominator,
)
from algorithms.identifiability.regressor import ArxStructure, IdentifiabilityError, build_regressor
from algorithms.identifiability.validation import is_stable


def fit_multihorizon(
    experiments: Sequence[TrainingExperiment], *, structure: ArxStructure,
    horizons: tuple[int, ...] = (1, 16, 64, 0), ridge_alpha: float = .001,
    max_nfev: int = 150,
) -> OutputErrorEstimate:
    """Minimize equally weighted per-run/per-horizon normalized simulation MSE.

    Each run has equal scaling and loss weight, regardless of length. All stats,
    initialization histories, seeds and residuals use Train intervals only.
    No operating-point offsets are inferred from future outputs. The returned
    affine coefficients use the existing ARX equation and frozen simulator.
    """
    if (not experiments or len({e.name for e in experiments}) != len(experiments)
            or not 1 <= structure.na <= 4):
        raise IdentifiabilityError("PARAMETER_OUT_OF_RANGE", "训练区间名称必须唯一，分母阶数须为 1–4")
    if (not horizons or any(type(h) is not int or h < 0 for h in horizons)
            or len(set(horizons)) != len(horizons)
            or not np.isfinite(ridge_alpha) or ridge_alpha < 0
            or type(max_nfev) is not int or max_nfev < 1):
        raise IdentifiabilityError("PARAMETER_OUT_OF_RANGE", "多步时域、正则化或迭代预算无效")
    # Slice before reading values: even NaN/Inf in Validation/Test is irrelevant.
    runs = []
    for e in experiments:
        if (type(e.start) is not int or type(e.stop) is not int
                or e.start < structure.max_history or e.stop > len(e.output)
                or e.stop - e.start < max(16, structure.parameter_count + 1)):
            raise IdentifiabilityError("INSUFFICIENT_ROWS", "连续训练区间不足或缺少历史")
        left = e.start - structure.max_history
        if any(c not in e.inputs or len(e.inputs[c]) < e.stop for c in structure.input_columns):
            raise IdentifiabilityError("INVALID_DATASET_SCHEMA", "训练输入缺失或长度不足")
        y = np.asarray(e.output[left:e.stop], dtype=float)
        u = {c: np.asarray(e.inputs[c][left:e.stop], dtype=float) for c in structure.input_columns}
        if any(v.ndim != 1 or not np.all(np.isfinite(v)) for v in [y, *u.values()]):
            raise IdentifiabilityError("INVALID_DATASET_SCHEMA", "训练区间及历史必须连续且有限")
        runs.append((u, y, structure.max_history))

    def moments(arrays):
        center = float(np.mean([np.mean(a) for a in arrays]))
        scale = float(np.sqrt(np.mean([np.mean((a-center)**2) for a in arrays])))
        return center, scale if scale > np.finfo(float).eps * max(1., abs(center)) else 0.

    yc, ys = moments([y[first:] for _, y, first in runs])
    if ys == 0:
        raise IdentifiabilityError("FIT_UNDEFINED", "训练输出恒定")
    centers, scales = {}, {}
    for c in structure.input_columns:
        lo = structure.nk[c]
        hi = lo + structure.nb[c] - 1
        centers[c], scale = moments([u[c][first-hi:len(y)-lo] for u, y, first in runs])
        scales[c] = scale or 1.
    normalized = []
    design, targets, weights = [], [], []
    for u, y, first in runs:
        yn = (y-yc)/ys
        un = {c: (u[c]-centers[c])/scales[c] for c in structure.input_columns}
        reg = build_regressor(inputs=un, output=yn, structure=structure, start=first, stop=len(y))
        normalized.append((yn, first, reg.features[:, structure.na:]))
        design.append(np.column_stack((reg.features, np.ones(reg.n_rows))))
        targets.append(reg.targets)
        weights.append(np.full(reg.n_rows, 1/(len(runs)*reg.n_rows)))
    x, target, root = np.vstack(design), np.concatenate(targets), np.sqrt(np.concatenate(weights))
    penalty = np.diag(np.r_[np.full(structure.parameter_count, np.sqrt(ridge_alpha)), 0.])
    seed = np.linalg.lstsq(np.vstack((x*root[:, None], penalty)),
                          np.r_[target*root, np.zeros(x.shape[1])], rcond=None)[0]
    calls = 0

    def decode(p):
        return np.r_[reflection_to_denominator(p[:structure.na]), p[structure.na:]]

    def residual(p):
        nonlocal calls
        calls += 1
        coefficient = decode(p)
        denominator = np.r_[1., coefficient[:structure.na]]
        errors = []
        for yn, first, features in normalized:
            n = len(yn)-first
            contribution = features @ coefficient[structure.na:-1] + coefficient[-1]
            factor = np.sqrt(len(runs)*len(horizons)*n)
            for horizon in horizons:
                if horizon == 1:
                    prediction = contribution.copy()
                    for lag in range(1, structure.na+1):
                        prediction -= coefficient[lag-1]*yn[first-lag:len(yn)-lag]
                    errors.append((prediction-yn[first:])/factor)
                    continue
                width = horizon or n
                for offset in range(0, n, width):
                    stop = min(n, offset+width)
                    history = yn[first+offset-structure.na:first+offset][::-1]
                    initial = lfiltic([1.], denominator, history)
                    prediction = lfilter([1.], denominator, contribution[offset:stop], zi=initial)[0]
                    errors.append((prediction-yn[first+offset:first+stop])/factor)
        return np.r_[np.concatenate(errors), np.sqrt(ridge_alpha)*coefficient[:-1]]

    seeds = [np.r_[_denominator_to_reflection(seed[:structure.na]), seed[structure.na:]],
             np.r_[np.zeros(structure.na), seed[structure.na:]]]
    lower = np.r_[np.full(structure.na, -.995), np.full(len(seed)-structure.na, -np.inf)]
    upper = np.r_[np.full(structure.na, .995), np.full(len(seed)-structure.na, np.inf)]
    solutions = [least_squares(residual, p, bounds=(lower, upper), max_nfev=max_nfev)
                 for p in seeds]
    good = [s for s in solutions if s.success and np.all(np.isfinite(s.fun))]
    if not good:
        raise IdentifiabilityError("OE_NOT_CONVERGED", "多步模拟估计在预设预算内未收敛")
    best = min(good, key=lambda s: float(s.fun @ s.fun))
    coefficient = decode(best.x)
    theta = coefficient[:-1].copy()
    intercept = yc*(1+theta[:structure.na].sum()) + ys*coefficient[-1]
    offset = structure.na
    for c in structure.input_columns:
        width = structure.nb[c]
        theta[offset:offset+width] *= ys/scales[c]
        intercept -= centers[c]*theta[offset:offset+width].sum()
        offset += width
    stable, pole = is_stable(theta[:structure.na])
    if not stable:
        raise IdentifiabilityError("NUMERICAL_INSTABILITY", "稳定参数转换失败")
    return OutputErrorEstimate(theta, float(intercept), {
        "model_type": "OE", "estimation_loss": "balanced_multihorizon_simulation_mse",
        "horizons": list(horizons), "ridge_alpha": ridge_alpha,
        "training_rows": sum(e.stop-e.start for e in experiments),
        "lineage": [{"name": e.name, "start": e.start, "stop": e.stop,
                     "history_start": e.start-structure.max_history} for e in experiments],
        "output_center": yc, "output_scale": ys, "input_center": centers, "input_scale": scales,
        "effective_parameters": structure.parameter_count+1,
        "max_pole_modulus": pole, "forecast_updates": False,
        "residual_evaluations_including_jacobian": calls,
        "solver_starts": [{"status": s.status, "nfev": s.nfev, "cost": float(s.cost)} for s in solutions],
        "objective": float(best.fun @ best.fun),
    })
