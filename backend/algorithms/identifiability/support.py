"""Describe whether known forecast inputs were supported by the Train experiments."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from algorithms.identifiability.regressor import FloatArray


def training_input_support(
    inputs: Mapping[str, FloatArray], sample_indices: np.ndarray,
    *, input_lags: Mapping[str, tuple[int, int]],
) -> dict[str, dict[str, Any]]:
    """Capture only input values actually used by positive-weight Train rows.

    Unmodelled context controls are monitored at the selected row indices. They
    cannot acquire an estimated gain merely by appearing in this diagnostic.
    """
    support = {}
    for column, signal in inputs.items():
        minimum_lag, maximum_lag = input_lags.get(column, (0, 0))
        indices = np.unique(np.concatenate([
            sample_indices-lag for lag in range(minimum_lag, maximum_lag+1)
        ]))
        values = np.asarray(signal, dtype=float)[indices]
        reference: dict[str, Any] = {
            "lag_minimum": minimum_lag, "lag_maximum": maximum_lag,
            "modelled": column in input_lags, "samples": int(values.size),
        }
        if not values.size or not np.all(np.isfinite(values)):
            reference.update({"status": "unavailable", "minimum": None, "maximum": None})
        else:
            low, high = float(np.min(values)), float(np.max(values))
            reference.update({"status": "available", "minimum": low, "maximum": high,
                "std": float(np.std(values)),
                "constant": bool(high-low <= 8*np.finfo(float).eps*max(1., abs(low), abs(high)))})
        support[column] = reference
    return support


def assess_input_support(
    training_support: Mapping[str, Mapping[str, Any]], inputs: Mapping[str, FloatArray],
    *, start: int, stop: int,
) -> dict[str, Any]:
    """An unexcited control that changes cannot acquire an identified gain by inference.

    Only the known input trajectory over the supplied interval is inspected. No
    outputs, coefficient adaptation or automatic extrapolation is involved. Range
    coverage is a warning, not proof of process similarity or causal identification.
    """
    if start < 0 or stop <= start:
        raise ValueError("Invalid forecast interval")
    unsupported: list[str] = []
    extrapolated: list[str] = []
    unavailable: list[str] = []
    evidence = {}
    for column, reference in training_support.items():
        first = start-int(reference.get("lag_maximum", 0))
        last = stop-int(reference.get("lag_minimum", 0))
        if (column not in inputs or len(inputs[column]) < last or first < 0
                or reference.get("minimum") is None or reference.get("maximum") is None):
            unavailable.append(column)
            continue
        values = np.asarray(inputs[column][first:last], dtype=float)
        low, high = float(reference["minimum"]), float(reference["maximum"])
        if not np.all(np.isfinite(values)) or not np.isfinite(low+high) or high < low:
            unavailable.append(column)
            continue
        tolerance = 8*np.finfo(float).eps*max(1., abs(low), abs(high))
        outside = (values < low-tolerance) | (values > high+tolerance)
        constant = bool(reference.get("constant", high-low <= tolerance))
        if np.any(outside):
            (unsupported if constant else extrapolated).append(column)
        evidence[column] = {"constant_in_train": constant, "outside_train_range_fraction": float(np.mean(outside))}
    return {"policy_version": "known_input_support_v1", "start": start, "stop": stop,
            "status": "unsupported" if unsupported else "unavailable" if unavailable or not training_support
                else "extrapolation" if extrapolated else "within_observed_input_ranges",
            "unsupported_constant_inputs": unsupported, "extrapolated_inputs": extrapolated,
            "unavailable_inputs": unavailable, "evidence": evidence, "coefficient_updates": False,
            "deployment_ready": False}
