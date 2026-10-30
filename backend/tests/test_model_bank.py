"""Frozen local routing, past-only decisions and independent stable simulations."""
import numpy as np
import pytest
from algorithms.identifiability.model_bank import (
    FrozenLocalModel,
    route_local_models,
    simulate_local_bank,
)
from algorithms.identifiability.regressor import ArxStructure, IdentifiabilityError


def bank():
    structure = ArxStructure.create(na=1, nb=1, nk=1, input_columns=["u"])
    return [FrozenLocalModel("cold", structure, np.array([-.5, .8]), 1., "fixed", {"u": 0.}),
        FrozenLocalModel("hot", structure, np.array([-.8, .2]), 4., "fixed", {"u": 10.})]


def signals():
    u = np.random.default_rng(34).normal(size=100)
    y = np.zeros(100)
    for t in range(1, 100):
        y[t] = .5*y[t-1]+.8*u[t-1]+1.
    return {"u": u}, y


@pytest.mark.parametrize("policy", ["past_block", "nearest_input", "uniform"])
def test_future_outputs_cannot_change_routing_or_predictions(policy):
    models = bank()
    inputs, output = signals()
    kwargs = dict(inputs=inputs, start=43, stop=100, policy=policy, input_scale={"u": 3.})
    _, prediction, routing = simulate_local_bank(models, output=output, **kwargs)
    hidden = output.copy()
    hidden[43:] = np.nan
    _, replay, decision = simulate_local_bank(models, output=hidden, **kwargs)
    np.testing.assert_array_equal(prediction, replay)
    assert routing == decision
    assert routing["context_stop"] == 43 and not routing["forecast_updates"]
    if policy == "past_block":
        assert routing["weights"] == [1., 0.]


def test_future_inputs_do_not_change_model_choice():
    inputs, output = signals()
    original = route_local_models(bank(), inputs=inputs, output=output, start=43,
        policy="nearest_input", input_scale={"u": 3.})
    inputs["u"][43:] = 1e9
    assert original == route_local_models(bank(), inputs=inputs, output=output, start=43,
        policy="nearest_input", input_scale={"u": 3.})


def test_uniform_ensemble_combines_outputs_without_combining_parameters():
    models = bank()
    inputs, output = signals()
    theta = [m.theta.copy() for m in models]
    kwargs = dict(inputs=inputs, output=output, start=43, stop=100, policy="uniform", input_scale={"u": 3.})
    mixture = simulate_local_bank(models, **kwargs)[1]
    members = [simulate_local_bank([m], **kwargs)[1] for m in models]
    np.testing.assert_allclose(mixture, (members[0]+members[1])/2)
    for m, saved in zip(models, theta, strict=True):
        np.testing.assert_array_equal(m.theta, saved)


def test_unstable_or_empty_bank_is_rejected():
    inputs, output = signals()
    with pytest.raises(IdentifiabilityError):
        simulate_local_bank([], inputs=inputs, output=output, start=43, stop=100,
            policy="uniform", input_scale={"u": 3.})
    model = bank()[0]
    unstable = FrozenLocalModel("bad", model.structure, np.array([-1.1, .8]), 1., "fixed", {"u": 0.})
    with pytest.raises(IdentifiabilityError):
        simulate_local_bank([unstable], inputs=inputs, output=output, start=43, stop=100,
            policy="uniform", input_scale={"u": 3.})
