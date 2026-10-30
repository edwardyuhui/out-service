"""Guard weak validation evidence, causal initialization pairs and Train timestamps."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from app.schemas.optimization import OptimizationStartRequest
from app.services import optimization_service as optimizer

from test_optimization import make_series


@pytest.mark.parametrize("folds", [[], [{"free_run_fit": np.nan, "skill_vs_persistence": .3}],
                                  [{"free_run_fit": 90., "skill_vs_persistence": np.inf}],
                                  [{"skill_vs_persistence": .3}]])
def test_missing_nonfinite_or_empty_evidence_cannot_pass(folds):
    acceptance = optimizer._validation_acceptance(folds)
    assert acceptance["status"] == "inconclusive"
    assert "INCOMPLETE_VALIDATION_EVIDENCE" in acceptance["reasons"]


def test_low_order_arx_compensation_is_paired_and_old_grids_preserved():
    default = optimizer._structure_grid({})
    previous = optimizer._structure_grid({"arx_disturbance": True})
    guarded = optimizer._structure_grid({"all_arx_disturbance": True})
    assert len(default) == 102 and len(previous) == 120 and len(guarded) == 180
    assert guarded[:102] == default
    for paired in guarded[102:]:
        counterpart = {k: v for k, v in paired.items() if k not in {"initialization_policy", "initialization_window"}}
        assert counterpart in default
        assert paired["initialization_policy"] == "past_residual"
    assert any(p["na"] == 1 for p in guarded[102:])


def test_timestamp_check_rejects_gaps_and_duplicates():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    times = [start + timedelta(seconds=30*i) for i in range(30)]
    optimizer._require_uniform_train_timestamps(times)
    for bad in [times[:10] + times[11:], times[:10] + [times[9]] + times[11:]]:
        with pytest.raises(optimizer.OptimizationDomainError) as caught:
            optimizer._require_uniform_train_timestamps(bad)
        assert caught.value.code == "NONUNIFORM_SAMPLING"
        assert caught.value.details["partition"] == "train"


def test_sampling_guard_reads_train_metadata_only(monkeypatch):
    source = make_series(n_samples=500)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    source = replace(source, timestamps=[start+timedelta(seconds=i) for i in range(500)])
    bad_test_times = source.timestamps[:400] + [source.timestamps[399]]*100
    request = OptimizationStartRequest(version_id=source.version_id, input_columns=["u1", "u2"],
        output_column="y", max_trials=1, history_guard=10, optimization_policy="validation_guarded")
    monkeypatch.setattr(optimizer, "_structure_grid", lambda _: [{"na": 2, "nb": 2, "estimator": "ridge", "ridge_alpha": .01}])
    monkeypatch.setattr(optimizer, "_delay_options", lambda *args: {"u1": [3], "u2": [6]})
    original = optimizer.run_study(source, request, input_columns=request.input_columns, output_column="y")
    changed = optimizer.run_study(replace(source, timestamps=bad_test_times), request,
                                  input_columns=request.input_columns, output_column="y")
    assert original.best_params == changed.best_params
    assert original.best_value == changed.best_value
    assert original.best_metrics["sampling_validation"]["status"] == "passed"
    assert original.best_metrics["validation_acceptance"]["status"] == "passed"
    damaged = source.timestamps.copy()
    damaged[30] = damaged[29]
    with pytest.raises(optimizer.OptimizationDomainError, match="采样缺口"):
        optimizer.run_study(replace(source, timestamps=damaged), request,
                            input_columns=request.input_columns, output_column="y")


def test_failing_a_validation_fold_produces_no_formal_winner(monkeypatch):
    source = make_series(n_samples=500)
    request = OptimizationStartRequest(version_id=source.version_id, input_columns=["u1", "u2"],
        output_column="y", max_trials=1, history_guard=10, optimization_policy="validation_guarded")
    monkeypatch.setattr(optimizer, "_structure_grid", lambda _: [{"na": 2, "nb": 2, "estimator": "ridge", "ridge_alpha": .01}])
    monkeypatch.setattr(optimizer, "_delay_options", lambda *args: {"u1": [3], "u2": [6]})
    original = optimizer._fold_evidence
    def failed_early(result, train_end, val_end, guard, selection):
        evidence = original(result, train_end, val_end, guard, selection)
        if train_end < 300:
            evidence["skill_vs_persistence"] = -.1
        return evidence
    monkeypatch.setattr(optimizer, "_fold_evidence", failed_early)
    outcome = optimizer.run_study(source, request, input_columns=request.input_columns, output_column="y")
    assert outcome.best_number is None
    assert outcome.trials[0].error_code == "VALIDATION_QUALITY_REJECTED"
    assert outcome.trials[0].metrics["validation_rejections"]["reason_counts"]["NOT_BETTER_THAN_PERSISTENCE"] > 0


def test_short_circuit_preserves_exhaustive_winner_and_score(monkeypatch):
    source = make_series(n_samples=500)
    payload = OptimizationStartRequest(version_id=source.version_id, input_columns=["u1", "u2"],
        output_column="y", max_trials=1, history_guard=10, optimization_policy="validation_guarded")
    monkeypatch.setattr(optimizer, "_structure_grid", lambda _: [
        {"na": na, "nb": 2, "estimator": "ridge", "ridge_alpha": .01} for na in (1, 2)])
    monkeypatch.setattr(optimizer, "_delay_options", lambda *args: {"u1": [3], "u2": [6]})
    evidence = optimizer._fold_evidence
    def reject_first_order(result, *args):
        row = evidence(result, *args)
        if result.structure.na == 1:
            row["free_run_fit"] = -1.
        return row
    monkeypatch.setattr(optimizer, "_fold_evidence", reject_first_order)
    pruned = optimizer.run_study(source, payload, input_columns=payload.input_columns, output_column="y")
    acceptance = optimizer._validation_acceptance
    # Skip partial-evidence rejection to reproduce exhaustive fold evaluation.
    monkeypatch.setattr(optimizer, "_validation_acceptance", lambda folds:
        acceptance(folds) if len(folds) == 3 else {"status": "passed"})
    exhaustive = optimizer.run_study(source, payload, input_columns=payload.input_columns, output_column="y")
    assert pruned.best_number is not None
    assert pruned.best_params == exhaustive.best_params
    assert pruned.best_value == exhaustive.best_value
    assert pruned.statistics["structure_evaluations"] < exhaustive.statistics["structure_evaluations"]


def test_feedback_cannot_consume_a_two_trial_search(monkeypatch):
    source = make_series(n_samples=500)
    monkeypatch.setattr(optimizer, "_structure_grid", lambda _: [{"na": 2, "nb": 2, "estimator": "ridge", "ridge_alpha": .01}])
    monkeypatch.setattr(optimizer, "_delay_options", lambda *args: {"u1": [3], "u2": [6]})
    monkeypatch.setattr(optimizer, "_feedback_actions", lambda *args, **kwargs: {"parameters": {"window_size": 200}})
    payload = OptimizationStartRequest(version_id=source.version_id, input_columns=["u1", "u2"],
        output_column="y", max_trials=2, history_guard=10, optimization_policy="validation_guarded")
    enabled = optimizer.run_study(source, payload, input_columns=payload.input_columns, output_column="y")
    disabled = optimizer.run_study(source, payload.model_copy(update={"diagnose_feedback": False}),
                                  input_columns=payload.input_columns, output_column="y")
    assert enabled.best_params == disabled.best_params
    assert enabled.best_value == disabled.best_value
    assert [t.params for t in enabled.trials] == [t.params for t in disabled.trials]
    assert enabled.statistics["feedback_scheduling"]["scheduled_proposals"] == 0


def test_feedback_waits_for_three_search_trials_and_uses_reserved_quota(monkeypatch):
    source = make_series(n_samples=500)
    monkeypatch.setattr(optimizer, "_structure_grid", lambda _: [{"na": 2, "nb": 2, "estimator": "ridge", "ridge_alpha": .01}])
    monkeypatch.setattr(optimizer, "_delay_options", lambda *args: {"u1": [3], "u2": [6]})
    monkeypatch.setattr(optimizer, "_feedback_actions", lambda *args, **kwargs: {"parameters": {"window_size": 200}})
    payload = OptimizationStartRequest(version_id=source.version_id, input_columns=["u1", "u2"],
        output_column="y", max_trials=4, history_guard=10, optimization_policy="validation_guarded")
    outcome = optimizer.run_study(source, payload, input_columns=payload.input_columns, output_column="y")
    statuses = [t.metrics["adaptive_feedback"]["scheduling"]["status"] for t in outcome.trials]
    assert statuses[:3] == ["reserve_search_budget", "reserve_search_budget", "scheduled"]
    assert statuses[3] == "budget_exhausted"
    assert outcome.trials[3].params["window_size"] == 200
    assert outcome.statistics["feedback_scheduling"]["scheduled_proposals"] == 1
