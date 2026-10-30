"""Causal constant-disturbance initialization for stable ARX models."""
from uuid import uuid4

import numpy as np
import pytest
from algorithms.identifiability.regressor import ArxStructure, IdentifiabilityError, build_regressor
from algorithms.identifiability.validation import (
    free_run_simulate,
    initial_output_offset,
    one_step_predict,
)
from app.schemas.modeling import ArxFitRequest
from app.services import modeling_service as modeling
from app.services.modeling_service import fit_arx_core
from app.services.optimization_service import _structure_grid, objective_value


def shifted_process():
    u = np.random.default_rng(3).normal(size=1000)
    y = np.zeros(1000)
    for t in range(1, 1000):
        y[t] = .8 * y[t-1] + .4 * u[t-1] + 4 + (2 if t >= 600 else 0)
    structure = ArxStructure.create(na=1, nb=1, nk=1, input_columns=["u"])
    return u, y, structure, np.array([-.8, .4])


def test_arx_disturbance_enters_equation_and_never_reads_future_outputs():
    u, y, structure, theta = shifted_process()
    kwargs = dict(theta=theta, structure=structure, inputs={"u": u}, start=643, stop=800,
                  intercept=4, initialization_policy="past_residual")
    actual, predicted = free_run_simulate(output=y, **kwargs)
    np.testing.assert_allclose(actual, predicted, atol=1e-12)
    changed = y.copy()
    changed[643:] = np.nan
    np.testing.assert_array_equal(predicted, free_run_simulate(output=changed, **kwargs)[1])
    offset, evidence = initial_output_offset(theta, structure, inputs={"u": u}, output=y,
                                            start=643, intercept=4, window=32)
    assert offset == pytest.approx(2)  # equilibrium shift is 10, not the equation offset
    assert evidence["offset_kind"] == "equation_disturbance"
    assert evidence["context_stop"] == 643 and not evidence["forecast_updates"]
    regressor = build_regressor(inputs={"u": u}, output=y, structure=structure)
    estimate = one_step_predict(regressor, theta, intercept=4, output=y,
                               initialization_policy="past_residual")
    assert estimate[642] == pytest.approx(y[643])


def test_arx_compensation_changes_state_without_refitting_coefficients():
    u, y, _, _ = shifted_process()
    request = ArxFitRequest(version_id=uuid4(), input_columns=["u"], na=1,
        nb={"u": 1}, delays={"u": 1}, estimator="ols", history_guard=43)
    fixed = fit_arx_core(inputs={"u": u}, output=y, payload=request, input_columns=["u"])
    adjusted = fit_arx_core(inputs={"u": u}, output=y, input_columns=["u"],
        payload=request.model_copy(update={"initialization_policy": "past_residual"}))
    np.testing.assert_array_equal(fixed.theta, adjusted.theta)
    assert adjusted.intercept == fixed.intercept
    assert objective_value(adjusted)[1]["complexity"] == pytest.approx(objective_value(fixed)[1]["complexity"] + 1/40)
    assert adjusted.validation.free_run_fit > 99.99
    assert fixed.validation.free_run_fit < 0


def test_short_history_and_outliers_have_explicit_behavior():
    u, y, structure, theta = shifted_process()
    y[625] += 1000
    offset, _ = initial_output_offset(theta, structure, inputs={"u": u}, output=y,
                                     start=643, intercept=4, window=32)
    assert offset == pytest.approx(2)
    offset, evidence = initial_output_offset(theta, structure, inputs={"u": u}, output=y,
                                            start=6, intercept=4, window=32)
    assert offset == 0 and evidence["status"] == "insufficient_history"


def test_compensated_simulation_is_invariant_to_affine_engineering_units():
    u, y, structure, theta = shifted_process()
    kwargs = dict(start=643, stop=800, initialization_policy="past_residual")
    predicted = free_run_simulate(theta, structure, inputs={"u": u}, output=y, intercept=4, **kwargs)[1]
    transformed = free_run_simulate(np.array([-.8, .04]), structure, inputs={"u": 1000*u},
        output=100*y + 273, intercept=400 + .2*273, **kwargs)[1]
    np.testing.assert_allclose(transformed, 100*predicted + 273, atol=1e-9)


def test_saved_initialized_arx_replays_test_without_fitting(monkeypatch):
    u, y, _, _ = shifted_process()
    request = ArxFitRequest(version_id=uuid4(), input_columns=["u"], na=1,
        nb={"u": 1}, delays={"u": 1}, estimator="ols", history_guard=43,
        initialization_policy="past_residual")
    fitted = fit_arx_core(inputs={"u": u}, output=y, payload=request, input_columns=["u"])
    serialized = ArxFitRequest.model_validate_json(request.model_dump_json())
    saved = modeling.SavedArxModel(model_id=uuid4(), dataset_id=uuid4(), source_version_id=request.version_id,
        payload=serialized, structure=fitted.structure, theta=fitted.theta.copy(), intercept=fitted.intercept,
        preprocessing=fitted.preprocessing, artifact_uri="test.json")
    def reject(*args, **kwargs):
        raise AssertionError("Frozen model must not fit Test")
    monkeypatch.setattr(modeling, "estimate_parameters", reject)
    replay = modeling.replay_saved_arx_core(saved=saved, inputs={"u": u}, output=y)
    np.testing.assert_array_equal(replay.theta, fitted.theta)
    assert replay.metrics.free_run["test"].fit > 99.99
    assert replay.preprocessing["initialization_parameters"] == 1


@pytest.mark.parametrize("policy", ["past_residual", "unknown"])
def test_invalid_initialization_is_rejected(policy):
    u, y, structure, _ = shifted_process()
    with pytest.raises(IdentifiabilityError) as caught:
        free_run_simulate(np.array([-1.1, .4]), structure, inputs={"u": u}, output=y,
                          start=643, stop=800, intercept=4, initialization_policy=policy)
    assert caught.value.code == ("UNSTABLE_MODEL" if policy == "past_residual" else "PARAMETER_OUT_OF_RANGE")


def test_extra_arx_candidates_are_opt_in_and_paired():
    established = _structure_grid({})
    experimental = _structure_grid({"arx_disturbance": True})
    assert len(established) == 102 and len(experimental) == 120
    assert experimental[:102] == established
    assert all(c["initialization_policy"] == "past_residual" for c in experimental[102:])
    for candidate in experimental[102:]:
        fixed = {k: v for k, v in candidate.items() if not k.startswith("initialization_")}
        assert fixed in established
