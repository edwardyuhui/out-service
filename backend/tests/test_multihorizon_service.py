from uuid import uuid4

import numpy as np
import pytest
from app.schemas.modeling import ArxFitRequest
from app.services.modeling_service import (
    ModelingDomainError,
    _fit_arx_core,
    fit_arx_core,
    to_model_structure_data,
)
from pydantic import ValidationError


def data():
    rng = np.random.default_rng(29)
    u = {"u1": rng.normal(size=400), "u2": rng.normal(size=400)}
    y = np.full(400, 10.)
    for t in range(2, len(y)):
        y[t] = .7*y[t-1] + .8*u["u1"][t-1] - .3*u["u2"][t-2] + 3
    return u, y


def request(**kwargs):
    return ArxFitRequest(**{**dict(version_id=uuid4(), model_type="OE", na=1,
        nb=[1, 1], delays=[1, 2], input_columns=["u1", "u2"], estimator="ridge",
        ridge_alpha=0, history_guard=10), **kwargs})


def test_service_recovers_miso_and_preserves_training_intervals():
    u, y = data()
    payload = request(training_sample_indices=[*range(20, 100), *range(150, 220)])
    result = fit_arx_core(inputs=u, output=y, payload=payload, input_columns=list(u))
    np.testing.assert_allclose(result.theta, [-.7, .8, -.3], atol=1e-6)
    assert result.intercept == pytest.approx(3, abs=1e-6)
    assert "test" not in result.metrics.free_run
    assert [(r["start"], r["stop"]) for r in result.preprocessing["lineage"]] == [(20, 100), (150, 220)]
    assert to_model_structure_data(payload, result.structure).model_type == "OE"


def test_saved_parameters_replay_never_calls_estimator(monkeypatch):
    u, y = data()
    p = request()
    fitted = fit_arx_core(inputs=u, output=y, payload=p, input_columns=list(u))
    def forbidden(*args, **kwargs):
        raise AssertionError("Frozen Test must not fit")
    monkeypatch.setattr("app.services.modeling_service.fit_multihorizon", forbidden)
    result = _fit_arx_core(inputs=u, output=y, payload=p.model_copy(update={"evaluate_test": True}),
        input_columns=list(u), fixed_parameters=(fitted.theta, fitted.intercept, fitted.preprocessing))
    assert result.metrics.free_run["test"].rmse < 1e-6


def test_validation_test_outputs_do_not_change_service_coefficients():
    u, y = data()
    fit = fit_arx_core(inputs=u, output=y, payload=request(), input_columns=list(u))
    y[240:] += np.arange(160)*100
    changed = fit_arx_core(inputs=u, output=y, payload=request(), input_columns=list(u))
    np.testing.assert_array_equal(fit.theta, changed.theta)
    assert fit.intercept == changed.intercept


@pytest.mark.parametrize("kwargs", [{"na": 5}, {"estimator": "ols"},
    {"fit_intercept": False}, {"standardize": False}, {"initialization_policy": "past_residual"},
    {"sample_weights": {12: .5}}, {"simulation_horizons": [1, 1]}, {"regularization_kernel": "tc"}])
def test_schema_rejects_unsupported_oe_options(kwargs):
    with pytest.raises(ValidationError):
        request(**kwargs)


def test_short_selected_intervals_fail_explicitly():
    u, y = data()
    with pytest.raises(ModelingDomainError, match="连续训练区间不足"):
        fit_arx_core(inputs=u, output=y, payload=request(training_sample_indices=[*range(20, 25), *range(80, 120)]), input_columns=list(u))
