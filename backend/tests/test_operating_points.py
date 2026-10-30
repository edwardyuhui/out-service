"""Working-point changes must not masquerade as within-run dynamic excitation."""
import numpy as np
import pytest
from algorithms.identifiability.experiments import TrainingExperiment, fit_arx_experiments
from algorithms.identifiability.operating_points import fit_within_run_arx
from algorithms.identifiability.regressor import ArxStructure, IdentifiabilityError
from algorithms.identifiability.validation import free_run_simulate


def make_runs():
    rng = np.random.default_rng(93)
    runs = []
    for name, size, level, intercept in [("cold", 400, 0., 3.), ("hot", 150, 10., -20.)]:
        u = rng.normal(size=size)+level
        y = np.zeros(size)
        for t in range(1, size):
            y[t] = .6*y[t-1]+.4*u[t-1]+intercept
        runs.append(TrainingExperiment(name, {"u": u}, y, 12, int(size*.6)))
    return runs, ArxStructure.create(na=1, nb=1, nk=1, input_columns=["u"])


def test_separate_offsets_recover_dynamic_coefficients():
    runs, structure = make_runs()
    estimate = fit_within_run_arx(runs, structure=structure, ridge_alpha=0.)
    np.testing.assert_allclose(estimate.parameters.theta, [-.6, .4], atol=1e-10)
    assert estimate.run_intercepts == pytest.approx({"cold": 3., "hot": -20.})
    pooled = fit_arx_experiments(runs, structure=structure, ridge_alpha=0.)
    assert np.linalg.norm(pooled.parameters.theta-[-.6, .4]) > .05
    assert estimate.lineage[0]["total_weight"] == pytest.approx(estimate.lineage[1]["total_weight"])


def test_between_run_only_control_does_not_acquire_a_gain():
    runs, _ = make_runs()
    modified = [TrainingExperiment(e.name, {**e.inputs, "heater": np.full(len(e.output), level)},
        e.output, e.start, e.stop) for e, level in zip(runs, [100.1, 200.2], strict=True)]
    structure = ArxStructure.create(na=1, nb=1, nk=1, input_columns=["u", "heater"])
    fit = fit_within_run_arx(modified, structure=structure, ridge_alpha=.1)
    assert fit.parameters.theta[-1] == pytest.approx(0., abs=1e-12)
    assert fit.excitation["heater"]["between_run_only"]
    assert not fit.excitation["heater"]["dynamic_gain_identified"]
    assert not fit.input_support["heater"]["constant"]


def test_train_tails_cannot_change_estimate_or_evidence():
    runs, structure = make_runs()
    original = fit_within_run_arx(runs, structure=structure, ridge_alpha=.1)
    changed = []
    for e in runs:
        u, y = e.inputs["u"].copy(), e.output.copy()
        u[e.stop:], y[e.stop:] = 1e20, np.nan
        changed.append(TrainingExperiment(e.name, {"u": u}, y, e.start, e.stop))
    hidden = fit_within_run_arx(changed, structure=structure, ridge_alpha=.1)
    np.testing.assert_array_equal(original.parameters.theta, hidden.parameters.theta)
    assert original.run_intercepts == hidden.run_intercepts
    assert original.input_support == hidden.input_support
    assert original.lineage == hidden.lineage


def test_new_run_offset_uses_only_past_and_freezes_coefficients():
    runs, structure = make_runs()
    fit = fit_within_run_arx(runs, structure=structure, ridge_alpha=.1)
    e = runs[1]
    theta = fit.parameters.theta.copy()
    kwargs = dict(inputs=e.inputs, start=100, stop=len(e.output),
        intercept=fit.parameters.intercept, initialization_policy="past_residual")
    predicted = free_run_simulate(theta, structure, output=e.output, **kwargs)[1]
    hidden = e.output.copy()
    hidden[100:] = np.nan
    np.testing.assert_array_equal(predicted, free_run_simulate(theta, structure, output=hidden, **kwargs)[1])
    np.testing.assert_array_equal(theta, fit.parameters.theta)


def test_invalid_or_duplicate_training_runs_are_rejected():
    runs, structure = make_runs()
    with pytest.raises(IdentifiabilityError):
        fit_within_run_arx([runs[0], runs[0]], structure=structure, ridge_alpha=.1)
    short = TrainingExperiment("short", runs[0].inputs, runs[0].output, 12, 15)
    with pytest.raises(IdentifiabilityError):
        fit_within_run_arx([short], structure=structure, ridge_alpha=.1)


def test_benchmark_serializes_numpy_scalar_evidence(monkeypatch, tmp_path):
    import json
    from pathlib import Path

    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]/"scripts"))
    from benchmark_operating_points import write

    target = tmp_path/"evidence.json"
    write(target, {"constant": np.bool_(True), "rows": np.int64(12),
        "nested": [{"score": np.float64(1.2)}]})
    assert json.loads(target.read_text()) == {"constant": True, "rows": 12, "nested": [{"score": 1.2}]}
