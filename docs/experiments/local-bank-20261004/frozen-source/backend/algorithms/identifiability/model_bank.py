"""Route among frozen local ARX models using strictly preceding observations.

Output ensembles simulate each stable member independently. Coefficients are
never averaged or refitted, and routing remains fixed for the forecast horizon.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np

from algorithms.identifiability.regressor import ArxStructure, FloatArray, IdentifiabilityError
from algorithms.identifiability.validation import free_run_simulate, is_stable

RoutingPolicy = Literal["past_block", "nearest_input", "uniform"]


@dataclass(frozen=True)
class FrozenLocalModel:
    name: str
    structure: ArxStructure
    theta: FloatArray
    intercept: float
    initialization_policy: str
    input_center: Mapping[str, float]


def route_local_models(
    models: Sequence[FrozenLocalModel], *, inputs: Mapping[str, FloatArray],
    output: FloatArray, start: int, policy: RoutingPolicy,
    input_scale: Mapping[str, float], context_window: int = 32, block_length: int = 16,
) -> dict[str, object]:
    """Choose a frozen member without reading output or input values at/after start."""
    if not models or len({m.name for m in models}) != len(models):
        raise IdentifiabilityError("INVALID_DATASET_SCHEMA", "局部模型不能为空，且名称必须唯一")
    if policy not in {"past_block", "nearest_input", "uniform"} or context_window < 8 or block_length < 8:
        raise IdentifiabilityError("PARAMETER_OUT_OF_RANGE", "局部模型路由参数无效")
    if start > len(output) or start < max(m.structure.max_history for m in models)+8:
        raise IdentifiabilityError("INSUFFICIENT_ROWS", "预测前历史不足")
    if any(not is_stable(m.theta[:m.structure.na])[0] for m in models):
        raise IdentifiabilityError("UNSTABLE_MODEL", "局部模型必须分别稳定")
    context_start = max(0, start-context_window)
    weights = np.full(len(models), 1/len(models))
    scores = []
    if policy == "past_block":
        first = max(max(m.structure.max_history for m in models), start-block_length)
        for model in models:
            try:
                actual, prediction = free_run_simulate(model.theta, model.structure,
                    inputs=inputs, output=output, start=first, stop=start,
                    intercept=model.intercept, initialization_policy=model.initialization_policy)
                score = float(np.sqrt(np.mean((actual-prediction)**2)))
                scores.append(score if np.isfinite(score) else float("inf"))
            except IdentifiabilityError:
                scores.append(float("inf"))
        context_start = 0  # Initialization may use earlier history within the prefix.
    elif policy == "nearest_input":
        for model in models:
            distances = []
            for c in model.structure.input_columns:
                scale = input_scale.get(c)
                values = np.asarray(inputs[c][context_start:start], dtype=float)
                if scale is None or not np.isfinite(scale) or scale <= 0 or not values.size or not np.all(np.isfinite(values)):
                    raise IdentifiabilityError("INVALID_DATASET_SCHEMA", "工况距离缺少冻结训练尺度或有效历史")
                distances.append(((float(values.mean())-model.input_center[c])/scale)**2)
            scores.append(float(np.mean(distances)))
    if scores:
        if not np.any(np.isfinite(scores)):
            raise IdentifiabilityError("MODEL_ROUTING_UNAVAILABLE", "预测前历史无法选择局部模型")
        weights = np.zeros(len(models))
        weights[int(np.argmin(scores))] = 1.
    return {"policy_version": "frozen_local_routing_v1", "policy": policy,
        "context_start": context_start, "context_stop": start,
        "models": [m.name for m in models], "weights": weights.tolist(),
        "scores": [v if np.isfinite(v) else None for v in scores],
        "forecast_updates": False, "coefficient_refit": False,
        "routing_uses_target_past": policy == "past_block", "deployment_ready": False}


def simulate_local_bank(
    models: Sequence[FrozenLocalModel], *, inputs: Mapping[str, FloatArray],
    output: FloatArray, start: int, stop: int, policy: RoutingPolicy,
    input_scale: Mapping[str, float],
) -> tuple[FloatArray, FloatArray, dict[str, object]]:
    routing = route_local_models(models, inputs=inputs, output=output, start=start,
        policy=policy, input_scale=input_scale)
    predictions, actual = [], None
    for model, weight in zip(models, routing["weights"], strict=True):
        if weight == 0:
            continue
        measured, prediction = free_run_simulate(model.theta, model.structure, inputs=inputs,
            output=output, start=start, stop=stop, intercept=model.intercept,
            initialization_policy=model.initialization_policy)
        if actual is not None and measured.shape != actual.shape:
            raise IdentifiabilityError("INVALID_DATASET_SCHEMA", "模型预测区间未对齐")
        actual = measured
        predictions.append(weight*prediction)
    return actual, np.sum(predictions, axis=0), routing
