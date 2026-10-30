"""Support is fitted from reliable Train histories and frozen with the model."""
from dataclasses import replace
from unittest.mock import patch
from uuid import uuid4

import numpy as np
from app.schemas.modeling import ArxFitRequest
from app.services.modeling_service import (
    SavedArxModel,
    fit_arx_core,
    replay_saved_arx_core,
    to_validation_data,
)
from app.services.optimization_service import _feedback_actions, _validation_acceptance

from test_modeling import make_inputs, simulate


def fixture_model():
    inputs = make_inputs(1000)
    output = simulate(inputs, noise=.01)
    # Retain an engineering context variable without including it in the model.
    inputs["heater"] = np.r_[np.full(600, 135.), np.full(400, 125.)]
    payload = ArxFitRequest(version_id=uuid4(), input_columns=["u1", "u2"], na=2,
        nb={"u1": 2, "u2": 2}, delays={"u1": 3, "u2": 8}, history_guard=10)
    return inputs, output, payload


def test_unmodelled_context_control_is_preserved_and_warned():
    inputs, output, payload = fixture_model()
    result = fit_arx_core(inputs=inputs, output=output, payload=payload, input_columns=payload.input_columns)
    assert result.validation.input_support["unsupported_constant_inputs"] == ["heater"]
    assert result.preprocessing["training_input_support"]["heater"]["modelled"] is False
    assert to_validation_data(result.validation).input_support["status"] == "unsupported"
    # Inspecting context controls must not affect estimated coefficients.
    other = fit_arx_core(inputs={c: inputs[c] for c in payload.input_columns}, output=output,
                         payload=payload, input_columns=payload.input_columns)
    np.testing.assert_array_equal(result.theta, other.theta)
    assert result.intercept == other.intercept
    assert "UNEXCITED_CONTROL_CHANGED" in _validation_acceptance([
        {"free_run_fit": 95., "skill_vs_persistence": .8, "input_support": result.validation.input_support}])["reasons"]


def test_zero_weight_and_unselected_rows_do_not_inflate_supported_ranges():
    inputs, output, payload = fixture_model()
    inputs["heater"][100:130] = 10000.
    payload = payload.model_copy(update={"training_sample_indices": list(range(100, 130))+list(range(200, 300)),
        "sample_weights": {i: 0. for i in range(100, 140)}})
    result = fit_arx_core(inputs=inputs, output=output, payload=payload, input_columns=payload.input_columns)
    assert result.preprocessing["training_input_support"]["heater"]["maximum"] == 135.


def test_saved_replay_keeps_support_and_coefficients_frozen():
    inputs, output, payload = fixture_model()
    result = fit_arx_core(inputs=inputs, output=output, payload=payload, input_columns=payload.input_columns)
    saved = SavedArxModel(model_id=uuid4(), dataset_id=uuid4(), source_version_id=payload.version_id,
        payload=payload, structure=result.structure, theta=result.theta, artifact_uri="unused",
        intercept=result.intercept, preprocessing=result.preprocessing)
    changed = {c: v.copy() for c, v in inputs.items()}
    changed["heater"][:580] = 10000.
    with patch("app.services.modeling_service.estimate_parameters", side_effect=AssertionError("refit")):
        replay = replay_saved_arx_core(saved=saved, inputs=changed, output=output)
    assert replay.preprocessing["training_input_support"] == result.preprocessing["training_input_support"]
    assert replay.validation.input_support == result.validation.input_support
    np.testing.assert_array_equal(replay.theta, result.theta)


def test_future_outputs_cannot_alter_support_or_validation_feedback():
    inputs, output, payload = fixture_model()
    first = fit_arx_core(inputs=inputs, output=output, payload=payload, input_columns=payload.input_columns)
    changed = output.copy()
    changed[800:] = np.nan
    second = fit_arx_core(inputs=inputs, output=changed, payload=payload, input_columns=payload.input_columns)
    assert first.preprocessing == second.preprocessing
    assert first.validation.input_support == second.validation.input_support


def test_advanced_feedback_has_bounded_distinct_actions_and_real_data_request():
    inputs, output, payload = fixture_model()
    result = fit_arx_core(inputs=inputs, output=output, payload=payload, input_columns=payload.input_columns)
    result = replace(result, validation=replace(result.validation, fit_gap=20.,
        input_residual_test={"rejected_channels": ["u1"]}))
    from types import SimpleNamespace
    selection = SimpleNamespace(selection=SimpleNamespace(excitation=SimpleNamespace(excitation_satisfied=False)))
    parameters = {"window_size": 190, "max_segments": 20, "selection_mode": "single",
        "adaptive_windows": False, "temporal_coverage_bins": 0, "delays": {"u1": 3, "u2": 8}}
    feedback = _feedback_actions(result, selection, parameters, {}, advanced=True)
    assert feedback["parameters"]["window_size"] == 200
    assert feedback["parameters"]["temporal_coverage_bins"] == 3
    assert "max_segments" not in [a["parameter"] for a in feedback["actions"]]
    assert feedback["recommendations"][0]["channels"] == ["heater"]
    assert feedback["recommendations"][0]["automatic"] is False
    assert feedback["test_partition_used"] is False
