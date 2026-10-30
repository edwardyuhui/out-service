"""Algorithm regressions: unit invariance, overlap accounting, isolation and robustness."""

from dataclasses import replace
from uuid import uuid4

import numpy as np
import pytest
from algorithms.identifiability.estimation import estimate_parameters
from algorithms.identifiability.excitation import log_det_information
from algorithms.identifiability.regressor import ArxStructure, build_regressor
from algorithms.identifiability.selection import build_window_grid, select_informative_windows
from app.schemas.modeling import ArxFitRequest
from app.schemas.optimization import OptimizationStartRequest
from app.schemas.preprocessing import SegmentRequest
from app.services.modeling_service import fit_arx_core
from app.services.optimization_service import _delay_options, objective_value
from app.services.segment_service import run_segment_selection
from app.services.version_data import VersionSeries


def process() -> tuple[dict[str, np.ndarray], np.ndarray]:
    rng = np.random.default_rng(81)
    inputs = {"u1": rng.normal(size=900) + 20, "u2": rng.normal(size=900) - 7}
    y = np.full(900, 60.0)
    for t in range(6, y.size):
        y[t] = 0.6 * y[t-1] + 0.3 * inputs["u1"][t-2] - 0.2 * inputs["u2"][t-5] + 17 + rng.normal(scale=0.03)
    return inputs, y


def series(inputs: dict[str, np.ndarray], y: np.ndarray) -> VersionSeries:
    return VersionSeries(dataset_id=uuid4(), version_id=uuid4(), dataset_name="process", origin="dataset",
                         timestamps=[], values={**inputs, "y": y}, declared_inputs=tuple(inputs),
                         declared_output="y", sample_period_seconds=10)


def fit(inputs: dict[str, np.ndarray], y: np.ndarray):
    return fit_arx_core(inputs=inputs, output=y, input_columns=list(inputs), payload=ArxFitRequest(
        version_id=uuid4(), input_columns=list(inputs), na=1, nb={k: 1 for k in inputs},
        delays={"u1": 2, "u2": 5}, estimator="ridge", ridge_alpha=0.01, history_guard=12))


def test_huber_recovers_slopes_despite_large_target_outliers() -> None:
    rng = np.random.default_rng(43)
    x = rng.normal(size=(500, 3))
    truth = np.array([2., -1., .5])
    y = x @ truth + 12 + rng.normal(scale=.02, size=500)
    y[::15] += rng.normal(loc=20, scale=10, size=y[::15].size)
    ols = estimate_parameters(x, y, estimator="ols")
    robust = estimate_parameters(x, y, estimator="huber")
    assert np.linalg.norm(robust.theta - truth) < .03
    assert np.linalg.norm(robust.theta - truth) < np.linalg.norm(ols.theta - truth) / 5
    assert robust.intercept == pytest.approx(12, abs=.03)
    assert robust.downweighted_rows > 0


def test_fitting_and_objective_are_invariant_to_engineering_units() -> None:
    inputs, y = process()
    first = fit(inputs, y)
    changed = {"u1": inputs["u1"] * 1000, "u2": inputs["u2"] / 100}
    second = fit(changed, y * 100)
    assert first.metrics.val_free_run_fit == pytest.approx(second.metrics.val_free_run_fit, abs=1e-6)
    assert objective_value(first)[0] == pytest.approx(objective_value(second)[0], abs=1e-8)
    assert first.validation.free_run_fit == pytest.approx(first.metrics.val_free_run_fit)
    assert first.validation.free_run_rmse == pytest.approx(first.metrics.free_run["validation"].rmse)


def test_overlapping_windows_count_each_information_row_once() -> None:
    inputs, y = process()
    structure = ArxStructure.create(na=1, nb=1, nk=1, input_columns=list(inputs))
    regressor = build_regressor(inputs=inputs, output=y, structure=structure)
    grid = build_window_grid(regressor, window_size=80, stride=20)
    result = select_informative_windows(regressor, grid, budget_rows=180, ridge=.01)
    features = regressor.features[result.row_positions]
    expected = log_det_information(features.T @ features + .01 * np.eye(features.shape[1]))
    assert result.selected_log_det == pytest.approx(expected, abs=1e-7)
    assert result.selected[-1].cumulative_log_det == pytest.approx(expected, abs=1e-7)
    assert result.row_positions.size <= 180
    assert 0 <= result.information_retention <= 1.000001


def test_windows_do_not_join_across_missing_time_rows() -> None:
    inputs, y = process()
    y[100:110] = np.nan
    regressor = build_regressor(inputs=inputs, output=y, structure=ArxStructure.create(na=1, nb=1, nk=1, input_columns=list(inputs)))
    grid = build_window_grid(regressor, window_size=40, stride=10)
    assert all(np.all(np.diff(regressor.time_indices[p]) == 1) for p in grid.positions)


def test_future_data_cannot_change_selection_quality_weights_or_delay_candidates() -> None:
    inputs, y = process()
    original = series(inputs, y)
    request = SegmentRequest(version_id=original.version_id, input_columns=list(inputs), output_column="y",
                             train_ratio=.6, history_guard=20, window_size=30, max_rows=120)
    outcome = run_segment_selection(original, request)
    changed_values = {k: v.copy() for k, v in original.values.items()}
    for signal in changed_values.values():
        signal[540:] = np.random.default_rng(2).normal(size=360) * 10000
    changed = replace(original, values=changed_values)
    other = run_segment_selection(changed, request)
    assert outcome.selected_sample_indices == other.selected_sample_indices
    assert outcome.gating.noise_sigma == other.gating.noise_sigma
    assert outcome.sample_weights == other.sample_weights
    assert max(outcome.selected_sample_indices) < 540 - 20
    optimization = OptimizationStartRequest(version_id=original.version_id, input_columns=list(inputs), output_column="y", history_guard=20)
    assert _delay_options(original, optimization, list(inputs), "y") == _delay_options(changed, optimization, list(inputs), "y")


def test_ensemble_selection_and_unit_changes_preserve_the_selected_rows() -> None:
    inputs, y = process()
    original = series(inputs, y)
    request = SegmentRequest(version_id=original.version_id, input_columns=list(inputs), output_column="y",
                             window_size=30, max_rows=150, history_guard=20)
    outcome = run_segment_selection(original, request)
    changed = replace(original, values={"u1": inputs["u1"] * 1000, "u2": inputs["u2"] / 100, "y": y * 10})
    other = run_segment_selection(changed, request)
    assert outcome.selection.model_count == 3
    assert outcome.selected_sample_indices == other.selected_sample_indices


def test_input_quality_preserves_binary_excitation_and_flags_extreme_spikes() -> None:
    from algorithms.identifiability.gating import input_anomaly_mask
    rng = np.random.default_rng(14)
    signal = rng.choice([-1., 1.], size=2000) + rng.normal(scale=.02, size=2000)
    signal[[200, 900, 1800]] = 20
    mask = input_anomaly_mask(signal)
    assert mask[[200, 900, 1800]].all()
    assert mask.sum() == 3
    assert np.array_equal(mask, input_anomaly_mask(signal * 1000 + 70))


def test_simulation_is_independent_of_future_outputs_and_has_no_amplitude_clipping() -> None:
    from algorithms.identifiability.validation import free_run_simulate
    structure = ArxStructure.create(na=1, nb=1, nk=0, input_columns=["u"])
    measured = np.ones(200)
    changed = measured.copy()
    changed[120:] = 1e9
    predictions = [free_run_simulate(np.array([-.5, 1.]), structure,
                   inputs={"u": np.full(200, 1e6)}, output=y, start=80, stop=120)[1]
                   for y in (measured, changed)]
    np.testing.assert_array_equal(*predictions)
    assert predictions[0][0] == pytest.approx(1e6 + .5)


def test_raw_fit_and_numerical_divergence_are_reported() -> None:
    from algorithms.identifiability.regressor import IdentifiabilityError
    from algorithms.identifiability.validation import fit_percentage, free_run_simulate
    actual = np.arange(100, dtype=float)
    assert fit_percentage(actual, actual + 1000) < -100
    structure = ArxStructure.create(na=1, nb=1, nk=0, input_columns=["u"])
    with pytest.raises(IdentifiabilityError, match="固定数值"):
        free_run_simulate(np.array([-10., 0.]), structure, inputs={"u": np.ones(200)},
                          output=np.ones(200), start=1, stop=200)


def test_joint_diagnostic_controls_null_false_alarms_and_detects_input_error() -> None:
    from algorithms.identifiability.validation import input_residual_test
    rng = np.random.default_rng(20261003)
    flagged = 0
    for _ in range(200):
        inputs = {f"u{i}": rng.normal(size=220) for i in range(3)}
        result = input_residual_test(rng.normal(size=200), np.arange(20, 220), inputs=inputs)
        flagged += bool(result["rejected_channels"])
        assert result["family_size"] == 63
    assert flagged <= 16  # fixed-seed calibration, conservative approximate 5% family error
    u = rng.normal(size=500)
    residual = u[30:490] + rng.normal(scale=.05, size=460)
    result = input_residual_test(residual, np.arange(30, 490), inputs={"u": u})
    assert result["rejected_channels"] == ["u"]
    assert input_residual_test(residual[::2], np.arange(30, 490, 2), inputs={"u": u})["status"] == "inconclusive"


def test_tc_fir_fits_long_impulse_response_and_is_unit_invariant() -> None:
    rng = np.random.default_rng(29)
    u = rng.normal(size=1000)
    impulse = .5 * .85 ** np.arange(24)
    y = 20 + np.convolve(u, impulse)[:u.size] + rng.normal(scale=.01, size=u.size)
    def fitted(input_scale: float, output_scale: float):
        return fit_arx_core(inputs={"u": u * input_scale}, output=y * output_scale,
            input_columns=["u"], payload=ArxFitRequest(version_id=uuid4(), input_columns=["u"],
                model_type="FIR", na=0, nb={"u": 24}, delays={"u": 0}, estimator="ridge",
                ridge_alpha=.1, regularization_kernel="tc", kernel_decay=.9, history_guard=32))
    first, second = fitted(1, 1), fitted(1000, 100)
    assert first.validation.free_run_fit > 98
    assert first.validation.free_run_fit == pytest.approx(first.validation.one_step_fit)
    assert second.validation.free_run_fit == pytest.approx(first.validation.free_run_fit, abs=1e-8)
    assert first.preprocessing["effective_parameters"] < 25
    assert first.a_coefficients == []
    assert first.validation.stable
    np.testing.assert_allclose(first.theta, second.theta * 10, atol=1e-10)


def test_rolling_search_is_invariant_to_test_tail_changes() -> None:
    from app.services.optimization_service import run_study
    inputs, y = process()
    original = series(inputs, y)
    request = OptimizationStartRequest(version_id=original.version_id, input_columns=list(inputs),
        output_column="y", max_trials=1, random_seed=42, history_guard=20)
    first = run_study(original, request, input_columns=list(inputs), output_column="y")
    altered = {k: v.copy() for k, v in original.values.items()}
    for values in altered.values():
        values[int(y.size * .8):] = np.nan
    second = run_study(replace(original, values=altered), request, input_columns=list(inputs), output_column="y")
    assert first.best_params == second.best_params
    assert first.best_value == pytest.approx(second.best_value, abs=1e-10)
    assert first.best_metrics["rolling_validation"] == second.best_metrics["rolling_validation"]
    evidence = first.best_metrics["rolling_validation"]
    assert evidence["effective_folds"] == 3
    assert [fold["train_end"] for fold in evidence["folds"]] == [360, 450, 540]
    assert max(fold["validation_stop"] for fold in evidence["folds"]) < 720
    assert first.best_metrics["objective_semantics"]["version"] == "v4"


def test_diverged_validation_retains_one_step_evidence_without_fabricating_fit() -> None:
    from algorithms.identifiability.validation import validate_model
    structure = ArxStructure.create(na=1, nb=1, nk=0, input_columns=["u"])
    rng = np.random.default_rng(99)
    result = validate_model(np.array([-10., 0.]), structure, inputs={"u": rng.normal(size=400)},
                            output=rng.normal(size=400), start=40, stop=340)
    assert result.simulation_status == "diverged"
    assert result.simulation_error_code == "SIMULATION_DIVERGED"
    assert np.isnan(result.free_run_fit)
    assert np.isfinite(result.one_step_fit)
    from app.services.modeling_service import to_validation_data
    data = to_validation_data(result).model_dump(mode="json")
    assert data["free_run_fit"] is None
    assert data["simulation_error_code"] == "SIMULATION_DIVERGED"


def test_initial_disturbance_estimate_uses_only_past_and_is_frozen_during_simulation() -> None:
    from algorithms.identifiability.validation import (
        free_run_simulate,
        initial_output_offset,
        one_step_predict,
    )
    rng = np.random.default_rng(62)
    u = rng.normal(size=400)
    structure = ArxStructure.create(na=0, nb=2, nk=0, input_columns=["u"])
    theta = np.array([.7, .2])
    y = .7 * u + .2 * np.roll(u, 1) + 20
    y[180:] += 8
    kwargs = dict(theta=theta, structure=structure, inputs={"u": u}, start=240, stop=340,
                  intercept=20, initialization_policy="past_residual", initialization_window=32)
    actual, predicted = free_run_simulate(output=y, **kwargs)
    np.testing.assert_allclose(predicted, actual, atol=1e-10)
    changed = y.copy()
    changed[240:] += 10000
    np.testing.assert_array_equal(predicted, free_run_simulate(output=changed, **kwargs)[1])
    offset, evidence = initial_output_offset(theta, structure, inputs={"u": u}, output=y,
                                            start=240, intercept=20, window=32)
    assert offset == pytest.approx(8)
    assert evidence["context_stop"] == 240
    assert evidence["forecast_updates"] is False
    regressor = build_regressor(inputs={"u": u}, output=y, structure=structure)
    one_step = one_step_predict(regressor, theta, intercept=20, output=y, initialization_policy="past_residual")
    other = build_regressor(inputs={"u": u}, output=changed, structure=structure)
    changed_one = one_step_predict(other, theta, intercept=20, output=changed, initialization_policy="past_residual")
    index = np.flatnonzero(regressor.time_indices == 240)[0]
    assert changed_one[index] == pytest.approx(one_step[index])
    assert changed_one[index + 20] != pytest.approx(one_step[index + 20])


def test_initialized_fir_recovers_shift_without_changing_parameters() -> None:
    rng = np.random.default_rng(37)
    u = rng.normal(size=1000)
    impulse = .3 * .8 ** np.arange(16)
    y = 20 + np.convolve(u, impulse)[:1000]
    y[600:] += 10
    request = ArxFitRequest(version_id=uuid4(), input_columns=["u"], model_type="FIR", na=0,
        nb={"u": 16}, delays={"u": 0}, estimator="ridge", regularization_kernel="tc",
        ridge_alpha=.1, kernel_decay=.9, history_guard=43)
    plain = fit_arx_core(inputs={"u": u}, output=y, payload=request, input_columns=["u"])
    initialized = fit_arx_core(inputs={"u": u}, output=y, input_columns=["u"],
        payload=request.model_copy(update={"initialization_policy": "past_residual"}))
    np.testing.assert_array_equal(initialized.theta, plain.theta)
    assert initialized.intercept == plain.intercept
    assert initialized.validation.free_run_fit > 99
    assert initialized.validation.reference_baselines["skill_vs_persistence"] > .95
    assert initialized.validation.initialization["context_stop"] == 643
    assert initialized.validation.free_run_fit == pytest.approx(initialized.metrics.val_free_run_fit)
    assert initialized.validation.one_step_fit == pytest.approx(initialized.metrics.val_fit)
    assert plain.validation.free_run_fit < -100
