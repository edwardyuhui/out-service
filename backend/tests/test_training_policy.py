"""Paired training policies, coverage constraints and undefined constant-output FIT."""
from dataclasses import replace

import numpy as np
import pytest
from algorithms.identifiability.regressor import ArxStructure, IdentifiabilityError, build_regressor
from algorithms.identifiability.selection import build_window_grid, select_informative_windows
from algorithms.identifiability.validation import fit_percentage
from app.schemas.optimization import OptimizationStartRequest
from app.services import optimization_service as optimizer
from app.services.modeling_service import _free_run_scores, _scores
from app.services.segment_service import SegmentDomainError

from test_optimization import make_series


def test_temporal_coverage_respects_gated_grid_and_unique_row_budget():
    rng = np.random.default_rng(19)
    u = rng.normal(size=601)
    u[:200] *= 50  # information-only selection concentrates at the beginning
    y = np.roll(u, 1) + rng.normal(size=601)
    regressor = build_regressor(inputs={"u": u}, output=y,
        structure=ArxStructure.create(na=1, nb=1, nk=1, input_columns=["u"]))
    grid = build_window_grid(regressor, window_size=40, stride=40)
    chosen = select_informative_windows(regressor, grid, budget_rows=120,
        temporal_coverage_bins=3)
    assert {min(2, (w.start_index - 1) // 200) for w in chosen.selected} == {0, 1, 2}
    assert len(chosen.row_positions) <= 120
    gated = grid.subset([i for i, rows in enumerate(grid.positions) if rows[-1] < 400])
    restricted = select_informative_windows(regressor, gated, budget_windows=3,
        temporal_coverage_bins=3)
    assert all(w.end_index < 401 for w in restricted.selected)
    assert len(restricted.selected) <= 3


@pytest.mark.parametrize("constant", [0., 104.15, 1e6])
def test_constant_output_has_undefined_fit_but_preserves_absolute_errors(constant):
    actual = np.full(148, constant)
    predicted = actual + 1.5
    with pytest.raises(IdentifiabilityError) as caught:
        fit_percentage(actual, predicted)
    assert caught.value.code == "FIT_UNDEFINED"
    scores = _scores(actual, predicted)
    assert scores["fit"] is None and scores["r2"] is None
    assert scores["rmse"] == pytest.approx(1.5)
    structure = ArxStructure.create(na=0, nb=1, nk=0, input_columns=["u"])
    free = _free_run_scores(np.array([0.]), structure, inputs={"u": np.ones(148)},
        output=actual, start=1, stop=148, intercept=constant + 1.5)
    assert free["fit"] is None
    assert free["rmse"] == pytest.approx(1.5)


def test_full_train_survives_selection_failure_and_ignores_test(monkeypatch):
    def reject(*args, **kwargs):
        raise SegmentDomainError("NO_DYNAMIC_SEGMENT_FOUND", "No gated window")
    monkeypatch.setattr(optimizer, "run_segment_selection", reject)
    monkeypatch.setattr(optimizer, "_delay_options", lambda *args: {"u1": [3], "u2": [6]})
    monkeypatch.setattr(optimizer, "_structure_grid", lambda _: [
        {"na": 2, "nb": 2, "estimator": "ridge", "ridge_alpha": .01}])
    source = make_series(n_samples=1500)
    request = OptimizationStartRequest(version_id=source.version_id,
        input_columns=["u1", "u2"], output_column="y", max_trials=2,
        search_space={"nk": [3, 6]}, history_guard=10)
    first = optimizer.run_study(source, request, input_columns=request.input_columns, output_column="y")
    altered = {c: values.copy() for c, values in source.values.items()}
    for values in altered.values():
        values[1200:] = np.random.default_rng(71).normal(size=300) * 1e6
    second = optimizer.run_study(replace(source, values=altered), request,
        input_columns=request.input_columns, output_column="y")
    assert first.best_params["training_policy"] == "full_train"
    assert first.best_params == second.best_params
    assert first.best_value == second.best_value
    selection = optimizer.replay_training_selection(source, first.best_params,
        request.input_columns, "y", train_ratio=.6)
    assert len(selection.selected_sample_indices) == first.best_metrics["training_rows"]
    assert max(selection.selected_sample_indices) < 900 - 10
    assert first.best_metrics["selection_provenance"]["criterion"] == "all_finite_train_rows"
    assert first.best_metrics["validation_acceptance"]["deployment_ready"] is False


def test_quality_check_distinguishes_search_completion_from_model_accuracy():
    bad = optimizer._validation_acceptance([{"free_run_fit": -50., "skill_vs_persistence": -.2}])
    assert bad["status"] == "insufficient"
    assert set(bad["reasons"]) == {"NONPOSITIVE_FREE_RUN_FIT", "NOT_BETTER_THAN_PERSISTENCE"}
    assert optimizer._validation_acceptance([{"free_run_fit": 80., "skill_vs_persistence": None}])["status"] == "inconclusive"
    assert optimizer._validation_acceptance([{"free_run_fit": 80., "skill_vs_persistence": .4}])["status"] == "passed"


def test_experimental_search_is_explicitly_opt_in():
    source = make_series(n_samples=500)
    request = OptimizationStartRequest(version_id=source.version_id,
        input_columns=["u1", "u2"], output_column="y")
    assert request.optimization_policy == "established"
    assert request.model_copy(update={"optimization_policy": "paired_coverage"}).optimization_policy == "paired_coverage"
