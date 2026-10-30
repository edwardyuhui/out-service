import numpy as np
from algorithms.identifiability.support import assess_input_support


def test_changed_previously_constant_actuator_is_unsupported():
    reference = {"heater": {"minimum": 135., "maximum": 135., "constant": True}}
    result = assess_input_support(reference, {"heater": np.full(80, 125.)}, start=43, stop=80)
    assert result["status"] == "unsupported"
    assert result["unsupported_constant_inputs"] == ["heater"]
    assert not result["coefficient_updates"] and not result["deployment_ready"]


def test_known_input_interval_and_engineering_unit_conversion_preserve_decision():
    reference = {"u": {"minimum": 0., "maximum": 10., "constant": False}}
    values = np.r_[np.zeros(10), np.arange(20.), np.full(10, 1e6)]
    result = assess_input_support(reference, {"u": values}, start=10, stop=30)
    changed = assess_input_support({"u": {"minimum": 273., "maximum": 373., "constant": False}},
                                   {"u": 10*values+273}, start=10, stop=30)
    assert result["status"] == changed["status"] == "extrapolation"
    assert result["evidence"] == changed["evidence"]
    assert result["evidence"]["u"]["outside_train_range_fraction"] == .45


def test_missing_or_nonfinite_input_metadata_cannot_be_certified():
    reference = {"u": {"minimum": 0., "maximum": 1.}}
    for values in ({}, {"u": np.full(50, np.nan)}):
        assert assess_input_support(reference, values, start=10, stop=50)["status"] == "unavailable"
    assert assess_input_support({}, {}, start=10, stop=50)["status"] == "unavailable"
