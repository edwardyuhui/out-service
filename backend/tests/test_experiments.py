"""Independent run boundaries, Train-only fitting and known input support."""
import numpy as np
import pytest
from algorithms.identifiability.experiments import TrainingExperiment, fit_arx_experiments
from algorithms.identifiability.regressor import ArxStructure, IdentifiabilityError


def experiments():
    rng = np.random.default_rng(2)
    runs = []
    for name, size, level in [("cold", 500, 0.), ("hot", 100, 10.)]:
        u = rng.normal(size=size) + level
        y = np.full(size, -100. if name == "cold" else 400.)
        for t in range(1, size):
            y[t] = .7*y[t-1] + .4*u[t-1] + 3
        runs.append(TrainingExperiment(name, {"u": u}, y, 10, int(size*.6)))
    return runs, ArxStructure.create(na=1, nb=1, nk=1, input_columns=["u"])


def test_independent_histories_recover_shared_dynamics_without_a_fake_jump():
    runs, structure = experiments()
    result = fit_arx_experiments(runs, structure=structure, ridge_alpha=0.)
    np.testing.assert_allclose(result.parameters.theta, [-.7, .4], atol=1e-10)
    assert result.parameters.intercept == pytest.approx(3)
    assert result.lineage[0]["original_indices"][0] == 10
    assert result.lineage[1]["original_indices"][0] == 10
    assert result.lineage[0]["total_weight"] == pytest.approx(result.lineage[1]["total_weight"])


def test_run_tails_cannot_change_coefficients_scaling_or_support():
    runs, structure = experiments()
    original = fit_arx_experiments(runs, structure=structure, ridge_alpha=.1)
    changed = []
    for e in runs:
        y, u = e.output.copy(), e.inputs["u"].copy()
        y[e.stop:] = np.nan
        u[e.stop:] = 1e12
        changed.append(TrainingExperiment(e.name, {"u": u}, y, e.start, e.stop))
    hidden = fit_arx_experiments(changed, structure=structure, ridge_alpha=.1)
    np.testing.assert_array_equal(original.parameters.theta, hidden.parameters.theta)
    assert original.parameters.intercept == hidden.parameters.intercept
    assert original.input_support == hidden.input_support


def test_unchanged_actuator_is_explicit_in_support_and_duplicate_runs_fail():
    runs, structure = experiments()
    constants = [TrainingExperiment(e.name, {"u": np.full(len(e.output), 125.)}, e.output, e.start, e.stop) for e in runs]
    result = fit_arx_experiments(constants, structure=structure, ridge_alpha=.1)
    assert result.input_support["u"]["constant"]
    with pytest.raises(IdentifiabilityError):
        fit_arx_experiments([runs[0], runs[0]], structure=structure, ridge_alpha=.1)


def test_between_run_levels_are_reported_separately_and_support_is_json_serializable():
    import json

    runs, structure = experiments()
    constants = [TrainingExperiment(e.name, {"u": np.full(len(e.output), level)},
        e.output, e.start, e.stop) for e, level in zip(runs, [100.1, 200.2], strict=True)]
    result = fit_arx_experiments(constants, structure=structure, ridge_alpha=.1)
    support = result.input_support["u"]
    assert not support["constant"]
    assert support["between_run_only"]
    assert not support["within_run_variation"]
    assert len(support["run_references"]) == 2
    assert json.loads(json.dumps(result.input_support))["u"]["between_run_only"] is True


def test_input_support_includes_used_lag_history_and_excludes_unused_tail():
    rng = np.random.default_rng(54)
    u, y = rng.normal(size=100), rng.normal(size=100)
    u[5], u[50] = -999., 999.
    structure = ArxStructure.create(na=1, nb=2, nk=3, input_columns=["u"])
    e = TrainingExperiment("run", {"u": u}, y, 9, 50)
    result = fit_arx_experiments([e], structure=structure, ridge_alpha=.1)
    assert result.input_support["u"]["minimum"] == -999.
    assert result.input_support["u"]["maximum"] < 999.
    assert result.input_support["u"]["lag_maximum"] == 4
