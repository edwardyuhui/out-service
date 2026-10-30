"""Initial Git estimator fidelity and chronology of the real transfer records."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from benchmark_initial_and_oe import initial_functions
from benchmark_oe_transfer import time_audit


def test_original_grid_and_verbatim_estimators_are_replayed():
    estimate, grid, snapshot = initial_functions()
    assert len(grid) == 24
    assert {c["na"] for c in grid} == {1, 2, 3, 4}
    assert {c["nb"] for c in grid} == {1, 2, 3}
    assert snapshot["commit"].startswith("f832237")
    assert all(c.get("ridge_alpha", .1) == .1 for c in grid)
    x = np.array([[1., 3.], [2., -1.], [4., 2.], [-1., 5.]])
    y = np.array([4., 1., 8., -3.])
    np.testing.assert_array_equal(estimate(x, y, "ols", None), np.linalg.lstsq(x, y, rcond=None)[0])
    np.testing.assert_array_equal(estimate(x, y, "ridge", .1), np.linalg.solve(x.T@x + .1*np.eye(2), x.T@y))


@pytest.mark.parametrize("times", [
    ["23:59:30", "00:00:00", "00:00:30"],
    ["16/08/2023 23:59:30", "17/08/2023 00:00:00", "17/08/2023 00:00:30"],
])
def test_raw_time_parser_handles_real_formats_and_midnight(times):
    audit = time_audit([{"Time": t} for t in times])
    assert audit["status"] == "monotonic"
    assert audit["median_interval_seconds"] == 30
    assert audit["non_30_second_intervals"] == 0


def test_time_audit_rejects_reordering_and_duplicates_and_records_gaps():
    assert time_audit([{"Time": "12:01:00"}, {"Time": "12:00:30"}])["status"] == "nonmonotonic_time"
    assert time_audit([{"Time": "12:01:00"}, {"Time": "12:01:00"}])["status"] == "duplicate_time"
    audit = time_audit([{"Time": "12:01:00"}, {"Time": "12:02:00"}])
    assert audit["max_interval_seconds"] == 60 and audit["non_30_second_intervals"] == 1
