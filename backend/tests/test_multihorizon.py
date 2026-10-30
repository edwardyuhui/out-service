import numpy as np
import pytest
from algorithms.identifiability.experiments import TrainingExperiment
from algorithms.identifiability.multihorizon import fit_multihorizon
from algorithms.identifiability.regressor import ArxStructure, IdentifiabilityError
from algorithms.identifiability.validation import free_run_simulate


def example(name="run", seed=71):
    rng = np.random.default_rng(seed)
    u = rng.normal(size=220)+5
    y = np.full(220, 10.)
    for t in range(1, len(y)):
        y[t] = .7*y[t-1] + .8*u[t-1] + 2
    return TrainingExperiment(name, {"u": u}, y, 10, 150)


STRUCTURE = ArxStructure.create(na=1, nb=1, nk=1, input_columns=["u"])


def test_recovers_dynamics_across_runs_and_forecasts_without_future_outputs():
    runs = [example(), example("other", 17)]
    fit = fit_multihorizon(runs, structure=STRUCTURE, ridge_alpha=0)
    np.testing.assert_allclose(fit.theta, [-.7, .8], atol=1e-7)
    assert fit.intercept == pytest.approx(2, abs=1e-7)
    target = example("new", 82)
    actual, predicted = free_run_simulate(fit.theta, STRUCTURE, inputs=target.inputs,
        output=target.output, start=50, stop=220, intercept=fit.intercept)
    hidden = target.output.copy()
    hidden[50:] = np.nan
    np.testing.assert_array_equal(predicted, free_run_simulate(fit.theta, STRUCTURE,
        inputs=target.inputs, output=hidden, start=50, stop=220, intercept=fit.intercept)[1])
    np.testing.assert_allclose(predicted, actual, atol=1e-6)


def test_unused_tails_and_prefixes_cannot_change_fit():
    e = example()
    fit = fit_multihorizon([e], structure=STRUCTURE)
    y, u = e.output.copy(), e.inputs["u"].copy()
    y[:9] = u[:9] = np.nan
    y[150:] = u[150:] = np.nan
    changed = fit_multihorizon([TrainingExperiment(e.name, {"u": u}, y, 10, 150)], structure=STRUCTURE)
    np.testing.assert_array_equal(changed.theta, fit.theta)
    assert changed.intercept == fit.intercept


def test_affine_units_do_not_change_predictions():
    e = example()
    fit = fit_multihorizon([e], structure=STRUCTURE)
    shifted = TrainingExperiment("shifted", {"u": 10*e.inputs["u"]-8}, 3*e.output+273, 10, 150)
    other = fit_multihorizon([shifted], structure=STRUCTURE)
    def predict(f, run):
        return free_run_simulate(f.theta, STRUCTURE, inputs=run.inputs, output=run.output,
            start=160, stop=220, intercept=f.intercept)[1]
    np.testing.assert_allclose(predict(other, shifted), 3*predict(fit, e)+273, atol=1e-4)


def test_run_order_and_duplicating_a_run_do_not_change_its_weight():
    a, b = example(), example("b", 18)
    first = fit_multihorizon([a, b], structure=STRUCTURE)
    second = fit_multihorizon([b, a], structure=STRUCTURE)
    np.testing.assert_allclose(first.theta, second.theta, atol=1e-6)
    duplicate = TrainingExperiment("copy", a.inputs, a.output, a.start, a.stop)
    single = fit_multihorizon([a], structure=STRUCTURE)
    twice = fit_multihorizon([a, duplicate], structure=STRUCTURE)
    np.testing.assert_allclose(single.theta, twice.theta, atol=1e-6)


@pytest.mark.parametrize("kwargs", [{"horizons": ()}, {"horizons": (1, 1)},
    {"horizons": (-1,)}, {"ridge_alpha": float("nan")}, {"max_nfev": 0}])
def test_rejects_invalid_options(kwargs):
    with pytest.raises(IdentifiabilityError):
        fit_multihorizon([example()], structure=STRUCTURE, **kwargs)


def test_discontinuous_or_missing_history_is_rejected():
    e = example()
    e.output[9] = np.nan
    with pytest.raises(IdentifiabilityError):
        fit_multihorizon([e], structure=STRUCTURE)


def test_nonconvergence_is_not_silently_accepted():
    with pytest.raises(IdentifiabilityError, match="未收敛"):
        fit_multihorizon([example()], structure=STRUCTURE, max_nfev=1)
