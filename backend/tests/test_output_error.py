"""OE recovery, engineering units, stable constraints and causal forecast checks."""
import numpy as np
import pytest
from algorithms.identifiability.output_error import fit_output_error, reflection_to_denominator
from algorithms.identifiability.regressor import ArxStructure, IdentifiabilityError
from algorithms.identifiability.validation import free_run_simulate, is_stable


def process(noise=0.):
    rng = np.random.default_rng(91)
    u = rng.normal(size=700) + 20
    v = rng.normal(size=700) - 3
    y = np.full(700, 50.)
    for t in range(2, 700):
        y[t] = .75*y[t-1] + .1*y[t-2] + .4*u[t-1] - .2*v[t-2] + 1
    y += rng.normal(scale=noise, size=700)
    return {"u": u, "v": v}, y, ArxStructure.create(na=2, nb=1, nk={"u": 1, "v": 2}, input_columns=["u", "v"])


def test_oe_recovers_process_and_frozen_forecast_ignores_future_outputs():
    inputs, y, structure = process()
    fitted = fit_output_error(inputs=inputs, output=y, structure=structure, train_stop=400,
                              start=43, ridge_alpha=0.)
    np.testing.assert_allclose(fitted.theta, [-.75, -.1, .4, -.2], atol=1e-7)
    assert fitted.intercept == pytest.approx(1, abs=1e-7)
    args = dict(theta=fitted.theta, structure=structure, inputs=inputs, start=443, stop=700,
                intercept=fitted.intercept)
    actual, predicted = free_run_simulate(output=y, **args)
    np.testing.assert_allclose(predicted, actual, atol=1e-7)
    hidden = y.copy()
    hidden[443:] = np.nan
    np.testing.assert_array_equal(predicted, free_run_simulate(output=hidden, **args)[1])
    assert not fitted.diagnostics["forecast_updates"]


def test_estimator_never_reads_validation_or_test_for_scaling_or_fitting():
    inputs, y, structure = process(.05)
    original = fit_output_error(inputs=inputs, output=y, structure=structure, train_stop=400, start=43)
    hidden = y.copy()
    hidden[400:] = np.nan
    changed_inputs = {c: v.copy() for c, v in inputs.items()}
    for v in changed_inputs.values():
        v[400:] = np.nan
    changed = fit_output_error(inputs=changed_inputs, output=hidden, structure=structure,
                               train_stop=400, start=43)
    np.testing.assert_array_equal(original.theta, changed.theta)
    assert original.intercept == changed.intercept


def test_oe_is_invariant_to_affine_unit_changes():
    inputs, y, structure = process(.01)
    fitted = fit_output_error(inputs=inputs, output=y, structure=structure, train_stop=400, start=43)
    shifted_inputs = {"u": 10*inputs["u"] + 17, "v": .1*inputs["v"] - 4}
    transformed = fit_output_error(inputs=shifted_inputs, output=100*y+273, structure=structure,
                                   train_stop=400, start=43)
    args = dict(structure=structure, start=443, stop=700)
    forecast = free_run_simulate(fitted.theta, inputs=inputs, output=y,
                                 intercept=fitted.intercept, **args)[1]
    shifted = free_run_simulate(transformed.theta, inputs=shifted_inputs, output=100*y+273,
                                intercept=transformed.intercept, **args)[1]
    np.testing.assert_allclose(shifted, 100*forecast+273, rtol=1e-6, atol=1e-4)


def test_schur_parameterization_remains_stable_throughout_search_domain():
    rng = np.random.default_rng(17)
    for order in range(1, 5):
        for reflection in [np.full(order, .995), np.full(order, -.995),
                           *rng.uniform(-.995, .995, size=(50, order))]:
            assert is_stable(reflection_to_denominator(reflection))[0]
    with pytest.raises(IdentifiabilityError, match="反射系数"):
        reflection_to_denominator(np.array([1.]))


@pytest.mark.parametrize("kind", ["missing", "constant", "short", "budget"])
def test_invalid_training_or_nonconvergence_has_explicit_failure(kind):
    inputs, y, structure = process(.1)
    options = dict(train_stop=400, start=43)
    if kind == "missing":
        y[90] = np.nan
    elif kind == "constant":
        y[:] = 1
    elif kind == "short":
        options["train_stop"] = 45
    else:
        options["max_nfev"] = 1
    with pytest.raises(IdentifiabilityError):
        fit_output_error(inputs=inputs, output=y, structure=structure, **options)
