"""Tests for the closed loop: cache, fingerprints, objective and strategy memory."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import UUID, uuid4

import numpy as np
import pytest
from algorithms.pipeline.cache import LineageCache, canonical_json, stage_key
from algorithms.pipeline.fingerprint import build_fingerprint, fingerprint_distance
from app.core.config import Settings
from app.core.db import get_session
from app.main import create_app
from app.models import Base
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class TestCanonicalKeys:
    def test_key_ignores_dict_ordering(self) -> None:
        assert canonical_json({"a": 1, "b": 2}) == canonical_json({"b": 2, "a": 1})

    def test_key_ignores_float_noise_below_precision(self) -> None:
        left = stage_key(parent_key="p", tool_name="t", tool_version="1", parameters={"x": 0.1})
        right = stage_key(
            parent_key="p", tool_name="t", tool_version="1", parameters={"x": 0.1 + 1e-15}
        )
        assert left == right

    def test_key_changes_with_a_meaningful_parameter_change(self) -> None:
        left = stage_key(parent_key="p", tool_name="t", tool_version="1", parameters={"x": 0.1})
        right = stage_key(parent_key="p", tool_name="t", tool_version="1", parameters={"x": 0.2})
        assert left != right

    def test_key_changes_with_tool_version(self) -> None:
        left = stage_key(parent_key="p", tool_name="t", tool_version="1", parameters={})
        right = stage_key(parent_key="p", tool_name="t", tool_version="2", parameters={})
        assert left != right

    def test_key_changes_with_parent(self) -> None:
        left = stage_key(parent_key="a", tool_name="t", tool_version="1", parameters={})
        right = stage_key(parent_key="b", tool_name="t", tool_version="1", parameters={})
        assert left != right


class TestLineageCache:
    def test_second_lookup_is_a_hit_and_does_not_recompute(self) -> None:
        cache = LineageCache()
        calls = {"count": 0}

        def compute() -> int:
            calls["count"] += 1
            return 42

        first, cached_first = cache.get_or_compute("k", compute)
        second, cached_second = cache.get_or_compute("k", compute)

        assert (first, second) == (42, 42)
        assert cached_first is False
        assert cached_second is True
        assert calls["count"] == 1
        assert cache.hit_rate == 0.5

    def test_eviction_keeps_the_table_bounded(self) -> None:
        cache = LineageCache(max_entries=2)
        for index in range(5):
            cache.get_or_compute(f"k{index}", lambda index=index: index)
        assert cache.statistics()["entries"] == 2

    def test_statistics_report_hits_and_misses(self) -> None:
        cache = LineageCache()
        cache.get_or_compute("a", lambda: 1)
        cache.get_or_compute("a", lambda: 1)
        cache.get_or_compute("b", lambda: 2)
        stats = cache.statistics()
        assert stats["hits"] == 1
        assert stats["misses"] == 2
        assert stats["lookups"] == 3


def make_series(*, n_samples: int = 3000, noise: float = 0.02, seed: int = 3):  # type: ignore[no-untyped-def]
    from app.services.version_data import VersionSeries

    generator = np.random.default_rng(seed)
    inputs = {}
    for offset, name in enumerate(("u1", "u2")):
        values = np.zeros(n_samples, dtype=float)
        hold = 13 + offset * 6
        for start in range(0, n_samples, hold):
            values[start : start + hold] = generator.uniform(-1.5, 1.5)
        inputs[name] = values

    ar = [-1.35, 0.45]
    b = {"u1": [0.4, 0.14], "u2": [0.2, 0.07]}
    nk = {"u1": 3, "u2": 6}
    output = np.zeros(n_samples, dtype=float)
    history = max(len(ar), max(nk[c] + len(b[c]) - 1 for c in inputs))
    for index in range(history, n_samples):
        value = -sum(ar[lag - 1] * output[index - lag] for lag in range(1, len(ar) + 1))
        for column, signal in inputs.items():
            for lag, coefficient in enumerate(b[column]):
                value += coefficient * signal[index - nk[column] - lag]
        output[index] = value + generator.normal(0.0, noise)

    return VersionSeries(
        dataset_id=uuid4(),
        version_id=uuid4(),
        dataset_name="opt-test",
        origin="simulation",
        timestamps=[],
        values={**inputs, "y": output},
        declared_inputs=tuple(inputs),
        declared_output="y",
        sample_period_seconds=1.0,
    )


class TestFingerprint:
    def test_similar_datasets_are_close(self) -> None:
        left = build_fingerprint(
            inputs={k: v for k, v in make_series(seed=1).values.items() if k != "y"},
            output=make_series(seed=1).values["y"],
        )
        right = build_fingerprint(
            inputs={k: v for k, v in make_series(seed=2).values.items() if k != "y"},
            output=make_series(seed=2).values["y"],
        )
        assert fingerprint_distance(left.vector, right.vector) < 0.35

    def test_a_much_noisier_dataset_is_further_away(self) -> None:
        clean = make_series(noise=0.01, seed=5)
        noisy = make_series(noise=3.0, seed=5)
        left = build_fingerprint(
            inputs={k: v for k, v in clean.values.items() if k != "y"},
            output=clean.values["y"],
        )
        right = build_fingerprint(
            inputs={k: v for k, v in noisy.values.items() if k != "y"},
            output=noisy.values["y"],
        )
        assert fingerprint_distance(left.vector, right.vector) > 0.1

    def test_vector_length_is_stable(self) -> None:
        from algorithms.pipeline.fingerprint import FINGERPRINT_FIELDS

        series = make_series()
        fingerprint = build_fingerprint(
            inputs={k: v for k, v in series.values.items() if k != "y"},
            output=series.values["y"],
        )
        assert len(fingerprint.vector) == len(FINGERPRINT_FIELDS)

    def test_mismatched_vectors_are_infinitely_far(self) -> None:
        assert fingerprint_distance([1.0, 2.0], [1.0]) == float("inf")


class TestObjective:
    def _result(self, **overrides: object):  # type: ignore[no-untyped-def]
        from app.schemas.modeling import ArxFitRequest
        from app.services.modeling_service import fit_arx_core

        series = make_series()
        payload = ArxFitRequest(
            version_id=series.version_id,
            input_columns=["u1", "u2"],
            output_column="y",
            na=2,
            nb={"u1": 2, "u2": 2},
            delays={"u1": 3, "u2": 6},
            **overrides,  # type: ignore[arg-type]
        )
        return fit_arx_core(
            inputs={k: v for k, v in series.values.items() if k != "y"},
            output=series.values["y"],
            payload=payload,
            input_columns=["u1", "u2"],
        )

    def test_a_good_model_scores_positively(self) -> None:
        from app.services.optimization_service import objective_value

        value, breakdown = objective_value(self._result())
        assert value > 0
        assert breakdown["val_free_run_fit"] > 80
        assert breakdown["objective_semantics"] == {
            "name": "composite_identification_score",
            "version": "v4",
            "direction": "maximize",
        }
        components = breakdown["objective_components"]
        assert components["final_score"] == pytest.approx(value)
        assert value == pytest.approx(
            components["validation_free_run_fit_component"]
            + components["normalized_error_component"]
            + components["residual_whiteness_component"]
            + components["complexity_component"]
        )

    def test_objective_is_driven_by_free_run_not_one_step(self) -> None:
        from app.services.optimization_service import objective_value

        good = self._result()
        starved = self._result(training_sample_indices=list(range(20, 260)))
        good_value, good_breakdown = objective_value(good)
        starved_value, starved_breakdown = objective_value(starved)

        assert good_value > starved_value
        free_run_gap = good_breakdown["val_free_run_fit"] - starved_breakdown["val_free_run_fit"]
        one_step_gap = abs(
            (good_breakdown["val_one_step_fit"] or 0) - (starved_breakdown["val_one_step_fit"] or 0)
        )
        assert free_run_gap > one_step_gap


class TestValidationDiagnosisPolicy:
    def test_maps_only_supported_validation_evidence_to_stable_codes(self) -> None:
        import inspect

        from app.services.optimization_feedback_policy import (
            DIAGNOSIS_POLICY_VERSION,
            diagnose_validation_candidate,
        )

        assert set(inspect.signature(diagnose_validation_candidate).parameters) == {
            "validation_feedback",
            "selection_provenance",
            "objective_components",
            "candidate_rejections",
        }
        diagnosis = diagnose_validation_candidate(
            validation_feedback={
                "free_run": {"fit": float("nan")},
                "summary": {"stable": False, "max_pole_modulus": 1.02},
            },
            selection_provenance={
                "excitation_satisfied": False,
                "persistent_excitation_order": {"u1": 1},
                "required_excitation_order": {"u1": 2},
            },
            objective_components={"stability_gate": False, "final_score": None},
        )

        assert diagnosis.policy_version == DIAGNOSIS_POLICY_VERSION
        assert [code.value for code in diagnosis.codes] == [
            "UNSTABLE_MODEL",
            "FREE_RUN_UNDEFINED",
            "INSUFFICIENT_EXCITATION",
        ]
        assert diagnosis.evidence["UNSTABLE_MODEL"]["max_pole_modulus"] == pytest.approx(
            1.02
        )
        assert diagnosis.evidence["FREE_RUN_UNDEFINED"]["free_run_metric_finite"] is False
        assert diagnosis.evidence["INSUFFICIENT_EXCITATION"][
            "excitation_satisfied"
        ] is False

    @pytest.mark.parametrize(
        ("reason", "expected_code"),
        [
            ("unstable", "UNSTABLE_MODEL"),
            ("free_run_undefined", "FREE_RUN_UNDEFINED"),
        ],
    )
    def test_all_hard_rejected_structures_preserve_the_original_reason(
        self,
        monkeypatch: pytest.MonkeyPatch,
        reason: str,
        expected_code: str,
    ) -> None:
        from app.schemas.optimization import OptimizationStartRequest
        from app.services import optimization_service

        series = make_series(n_samples=1200)
        monkeypatch.setattr(
            optimization_service,
            "_structure_grid",
            lambda params: [{"na": 2, "nb": 2, "estimator": "ridge", "ridge_alpha": 0.1}],
        )

        def reject_candidate(result: object) -> tuple[float, dict[str, object]]:
            return float("-inf"), {
                "reason": reason,
                "objective_semantics": dict(optimization_service.OBJECTIVE_SEMANTICS),
                "objective_components": {
                    "stability_gate": reason != "unstable",
                    "final_score": None,
                },
            }

        monkeypatch.setattr(optimization_service, "objective_value", reject_candidate)
        outcome = optimization_service.run_study(
            series,
            OptimizationStartRequest(
                version_id=series.version_id,
                input_columns=["u1", "u2"],
                output_column="y",
                max_trials=1,
            ),
            input_columns=["u1", "u2"],
            output_column="y",
        )

        assert outcome.best_number is None
        assert len(outcome.trials) == 1
        trial = outcome.trials[0]
        assert trial.state == "failed"
        assert trial.error_code == expected_code
        assert trial.metrics["diagnosis_policy_version"] == "validation_diagnosis_v1"
        assert trial.metrics["diagnosis_codes"] == [expected_code]
        assert trial.metrics["rejection_provenance"]["reason_counts"] == {
            expected_code: 1
        }
        assert trial.metrics["bookkeeping"] == {
            "previous_best": None,
            "absolute_improvement": None,
            "best_so_far": None,
            "decision": None,
        }

    def test_solver_error_is_not_mapped_to_a_hard_gate_diagnosis(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.schemas.optimization import OptimizationStartRequest
        from app.services import optimization_service
        from app.services.modeling_service import ModelingDomainError

        series = make_series(n_samples=1200)
        monkeypatch.setattr(
            optimization_service,
            "_structure_grid",
            lambda params: [{"na": 2, "nb": 2, "estimator": "ridge", "ridge_alpha": 0.1}],
        )

        def fail_solver(*args: object, **kwargs: object) -> None:
            raise ModelingDomainError("SOLVER_FAILURE", "solver failed")

        monkeypatch.setattr(optimization_service, "fit_arx_core", fail_solver)
        outcome = optimization_service.run_study(
            series,
            OptimizationStartRequest(
                version_id=series.version_id,
                input_columns=["u1", "u2"],
                output_column="y",
                max_trials=1,
            ),
            input_columns=["u1", "u2"],
            output_column="y",
        )

        trial = outcome.trials[0]
        assert trial.state == "failed"
        assert trial.error_code == "SOLVER_FAILURE"
        assert trial.metrics["diagnosis_codes"] == []
        assert "rejection_provenance" not in trial.metrics

    def test_segmentation_error_is_not_mapped_to_a_hard_gate_diagnosis(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.schemas.optimization import OptimizationStartRequest
        from app.services import optimization_service
        from app.services.segment_service import SegmentDomainError

        series = make_series(n_samples=1200)

        def fail_selection(*args: object, **kwargs: object) -> None:
            raise SegmentDomainError("SEGMENT_FAILURE", "selection failed")

        monkeypatch.setattr(optimization_service, "run_segment_selection", fail_selection)
        outcome = optimization_service.run_study(
            series,
            OptimizationStartRequest(
                version_id=series.version_id,
                input_columns=["u1", "u2"],
                output_column="y",
                max_trials=1,
            ),
            input_columns=["u1", "u2"],
            output_column="y",
        )

        trial = outcome.trials[0]
        assert trial.state == "complete"
        assert trial.params["training_policy"] == "full_train"
        assert trial.metrics["selection_failure"]["code"] == "SEGMENT_FAILURE"
        assert trial.metrics["diagnosis_codes"] == []

    def test_insufficient_excitation_is_diagnostic_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.schemas.optimization import OptimizationStartRequest
        from app.services import optimization_service

        series = make_series(n_samples=1200)
        original_provenance = optimization_service._selection_provenance
        monkeypatch.setattr(
            optimization_service,
            "_structure_grid",
            lambda params: [{"na": 2, "nb": 2, "estimator": "ridge", "ridge_alpha": 0.1}],
        )

        def insufficient_excitation(outcome: object) -> dict[str, object]:
            provenance = original_provenance(outcome)  # type: ignore[arg-type]
            provenance["excitation_satisfied"] = False
            return provenance

        monkeypatch.setattr(
            optimization_service, "_selection_provenance", insufficient_excitation
        )
        outcome = optimization_service.run_study(
            series,
            OptimizationStartRequest(
                version_id=series.version_id,
                input_columns=["u1", "u2"],
                output_column="y",
                max_trials=1,
            ),
            input_columns=["u1", "u2"],
            output_column="y",
        )

        trial = outcome.trials[0]
        assert trial.state == "complete"
        assert outcome.best_number == trial.number == 0
        assert outcome.best_value == pytest.approx(trial.value)
        assert trial.metrics["diagnosis_codes"] == ["INSUFFICIENT_EXCITATION"]
        assert trial.value == pytest.approx(
            trial.metrics["objective_components"]["final_score"]
        )
        assert trial.metrics["bookkeeping"]["decision"] == "CANDIDATE_VALID_NEW_BEST"


class TestTrialBestSoFarBookkeeping:
    def test_reducer_records_numeric_progress_and_ignores_invalid_trials(self) -> None:
        from app.services.optimization_feedback_policy import (
            BestSoFarState,
            advance_trial_bookkeeping,
        )

        state = BestSoFarState()
        results = []
        for number, trial_state, score in [
            (0, "failed", None),
            (1, "complete", -0.5),
            (2, "pruned", None),
            (3, "complete", -0.2),
            (4, "complete", -0.2),
            (5, "complete", 0.0),
            (6, "complete", -0.4),
            (7, "complete", float("inf")),
        ]:
            state, result = advance_trial_bookkeeping(
                state,
                trial_number=number,
                trial_state=trial_state,
                objective_score=score,
            )
            results.append(result.to_payload())

        assert results[0] == {
            "previous_best": None,
            "absolute_improvement": None,
            "best_so_far": None,
            "decision": None,
        }
        assert results[1] == {
            "previous_best": None,
            "absolute_improvement": None,
            "best_so_far": -0.5,
            "decision": "CANDIDATE_VALID_NEW_BEST",
        }
        assert results[2]["best_so_far"] == pytest.approx(-0.5)
        assert results[2]["decision"] is None
        assert results[3]["previous_best"] == pytest.approx(-0.5)
        assert results[3]["absolute_improvement"] == pytest.approx(0.3)
        assert results[3]["best_so_far"] == pytest.approx(-0.2)
        assert results[3]["decision"] == "CANDIDATE_VALID_NEW_BEST"
        assert results[4]["absolute_improvement"] == pytest.approx(0.0)
        assert results[4]["decision"] == "CANDIDATE_VALID_NOT_BEST"
        assert results[5]["absolute_improvement"] == pytest.approx(0.2)
        assert results[5]["best_so_far"] == pytest.approx(0.0)
        assert results[5]["decision"] == "CANDIDATE_VALID_NEW_BEST"
        assert results[6]["absolute_improvement"] == pytest.approx(-0.4)
        assert results[6]["best_so_far"] == pytest.approx(0.0)
        assert results[6]["decision"] == "CANDIDATE_VALID_NOT_BEST"
        assert results[7]["absolute_improvement"] is None
        assert results[7]["best_so_far"] == pytest.approx(0.0)
        assert results[7]["decision"] is None
        assert state.best_value == pytest.approx(0.0)
        assert state.winner_trial_number == 5

    def test_study_winner_uses_the_same_reducer_and_keeps_the_earlier_tie(self) -> None:
        from app.services.optimization_service import (
            TrialOutcome,
            _annotate_trial_bookkeeping,
        )

        trials = [
            TrialOutcome(0, "complete", -0.5, {}, {}, False, 1.0),
            TrialOutcome(1, "complete", 0.0, {}, {}, False, 1.0),
            TrialOutcome(2, "complete", 0.0, {}, {}, False, 1.0),
            TrialOutcome(3, "failed", None, {}, {}, False, 1.0, "SOLVER_FAILURE"),
            TrialOutcome(4, "pruned", None, {}, {}, False, 1.0),
            TrialOutcome(5, "complete", float("nan"), {}, {}, False, 1.0),
        ]

        winner = _annotate_trial_bookkeeping(trials)

        assert winner is trials[1]
        assert trials[0].metrics["bookkeeping"]["decision"] == "CANDIDATE_VALID_NEW_BEST"
        assert trials[1].metrics["bookkeeping"]["decision"] == "CANDIDATE_VALID_NEW_BEST"
        assert trials[2].metrics["bookkeeping"]["decision"] == "CANDIDATE_VALID_NOT_BEST"
        assert trials[2].metrics["bookkeeping"]["absolute_improvement"] == pytest.approx(0.0)
        assert trials[3].metrics["bookkeeping"]["best_so_far"] == pytest.approx(0.0)
        assert trials[3].metrics["bookkeeping"]["decision"] is None
        assert trials[4].metrics["bookkeeping"]["decision"] is None
        assert trials[5].metrics["bookkeeping"]["decision"] is None


class TestObservedConvergencePolicy:
    @staticmethod
    def _bookkeeping(
        *,
        decision: str | None,
        best_so_far: float | None,
    ) -> dict[str, object]:
        return {
            "previous_best": None,
            "absolute_improvement": None,
            "best_so_far": best_so_far,
            "decision": decision,
        }

    def test_meaningful_anchor_accumulates_small_new_bests_and_ignores_invalid_trials(
        self,
    ) -> None:
        from app.services.optimization_feedback_policy import observe_convergence

        new_best = "CANDIDATE_VALID_NEW_BEST"
        not_best = "CANDIDATE_VALID_NOT_BEST"
        observations = [
            (0, self._bookkeeping(decision=new_best, best_so_far=0.2000)),
            (1, self._bookkeeping(decision=not_best, best_so_far=0.2000)),
            (2, self._bookkeeping(decision=None, best_so_far=0.2000)),
            (3, self._bookkeeping(decision=new_best, best_so_far=0.2004)),
            (4, self._bookkeeping(decision=None, best_so_far=0.2004)),
            (5, self._bookkeeping(decision=new_best, best_so_far=0.2008)),
            (6, self._bookkeeping(decision=new_best, best_so_far=0.2011)),
            (7, self._bookkeeping(decision=not_best, best_so_far=0.2011)),
        ]

        result = observe_convergence(observations, best_trial_number=6)

        assert result.valid_trial_count == 6
        assert result.observed_at_trial_count == 8
        assert result.no_improvement_streak == 1
        assert result.last_meaningful_improvement_trial == 6
        assert result.best_trial_number == 6

    @pytest.mark.parametrize(
        ("valid_trial_count", "tail_streak", "expected_status"),
        [
            (16, 15, "INSUFFICIENT_EVIDENCE"),
            (17, 15, "NOT_CONVERGED"),
            (17, 16, "CONVERGED"),
        ],
    )
    def test_status_requires_fixed_minimum_valid_trials_and_patience(
        self,
        valid_trial_count: int,
        tail_streak: int,
        expected_status: str,
    ) -> None:
        from app.services.optimization_feedback_policy import observe_convergence

        observations = [
            (
                0,
                self._bookkeeping(
                    decision="CANDIDATE_VALID_NEW_BEST",
                    best_so_far=0.2,
                ),
            )
        ]
        prefix_count = valid_trial_count - tail_streak - 1
        for offset in range(prefix_count):
            index = len(observations)
            observations.append(
                (
                    index,
                    self._bookkeeping(
                        decision="CANDIDATE_VALID_NEW_BEST",
                        best_so_far=0.202 + offset * 0.002,
                    ),
                )
            )
        tail_best = float(observations[-1][1]["best_so_far"])
        for _ in range(tail_streak):
            observations.append(
                (
                    len(observations),
                    self._bookkeeping(
                        decision="CANDIDATE_VALID_NOT_BEST",
                        best_so_far=tail_best,
                    ),
                )
            )

        result = observe_convergence(observations, best_trial_number=0)

        assert result.status.value == expected_status
        assert result.valid_trial_count == valid_trial_count
        assert result.no_improvement_streak == tail_streak
        assert result.best_trial_number == 0

    def test_contract_exposes_fixed_observed_only_policy(self) -> None:
        from app.services.optimization_feedback_policy import observe_convergence

        result = observe_convergence([], best_trial_number=None)

        assert result.to_payload() == {
            "policy_version": "optimization_convergence_v1",
            "mode": "observed_only",
            "status": "INSUFFICIENT_EVIDENCE",
            "no_improvement_streak": 0,
            "patience": 16,
            "min_meaningful_improvement": 0.001,
            "min_valid_trials": 17,
            "valid_trial_count": 0,
            "last_meaningful_improvement_trial": None,
            "best_trial_number": None,
            "observed_at_trial_count": 0,
        }


class TestNormalStopReasonPolicy:
    @pytest.mark.parametrize(
        (
            "observed_trial_count",
            "target_trial_count",
            "timeout_seconds",
            "best_trial_number",
            "expected_code",
            "expected_outcome",
        ),
        [
            (50, 50, None, 7, "TRIAL_BUDGET_EXHAUSTED", "WINNER_SELECTED"),
            (50, 50, 300, 7, "TRIAL_BUDGET_EXHAUSTED", "WINNER_SELECTED"),
            (32, 50, 300, 7, "TIMEOUT_REACHED", "WINNER_SELECTED"),
            (50, 50, None, None, "TRIAL_BUDGET_EXHAUSTED", "NO_VALID_CANDIDATE"),
        ],
    )
    def test_reducer_uses_budget_first_and_phase_2b_winner_for_outcome(
        self,
        observed_trial_count: int,
        target_trial_count: int,
        timeout_seconds: int | None,
        best_trial_number: int | None,
        expected_code: str,
        expected_outcome: str,
    ) -> None:
        from app.services.optimization_feedback_policy import determine_normal_stop_reason

        result = determine_normal_stop_reason(
            observed_trial_count=observed_trial_count,
            target_trial_count=target_trial_count,
            timeout_seconds=timeout_seconds,
            best_trial_number=best_trial_number,
        )

        assert result.to_payload() == {
            "policy_version": "optimization_stop_reason_v1",
            "code": expected_code,
            "category": "NORMAL_LIMIT",
            "outcome": expected_outcome,
            "observed_trial_count": observed_trial_count,
            "target_trial_count": target_trial_count,
            "timeout_seconds": timeout_seconds,
        }

    def test_observed_convergence_does_not_change_budget_stop_reason(self) -> None:
        from app.services.optimization_feedback_policy import (
            determine_normal_stop_reason,
            observe_convergence,
        )

        observations = [
            (
                0,
                {
                    "previous_best": None,
                    "absolute_improvement": None,
                    "best_so_far": 0.2,
                    "decision": "CANDIDATE_VALID_NEW_BEST",
                },
            ),
            *[
                (
                    index,
                    {
                        "previous_best": 0.2,
                        "absolute_improvement": 0.0,
                        "best_so_far": 0.2,
                        "decision": "CANDIDATE_VALID_NOT_BEST",
                    },
                )
                for index in range(1, 17)
            ],
        ]

        convergence = observe_convergence(observations, best_trial_number=0)
        stop_reason = determine_normal_stop_reason(
            observed_trial_count=17,
            target_trial_count=17,
            timeout_seconds=None,
            best_trial_number=0,
        )

        assert convergence.status.value == "CONVERGED"
        assert stop_reason.code.value == "TRIAL_BUDGET_EXHAUSTED"


class TestFormalEvaluation:
    def test_baseline_is_test_free_and_ignores_the_held_out_tail(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.schemas.optimization import OptimizationStartRequest
        from app.services import optimization_service

        clean = make_series()
        changed_test = make_series()
        payload = OptimizationStartRequest(
            version_id=clean.version_id,
            input_columns=["u1", "u2"],
            output_column="y",
            max_trials=2,
        )
        test_start = int(clean.n_samples * (payload.train_ratio + payload.validation_ratio))
        changed_test.values["y"][test_start:] += 10_000.0

        observed_evaluate_test: list[bool] = []
        formal_fit = optimization_service.fit_arx_core

        def spy_fit_arx_core(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            observed_evaluate_test.append(kwargs["payload"].evaluate_test)  # type: ignore[index,union-attr]
            return formal_fit(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(optimization_service, "fit_arx_core", spy_fit_arx_core)
        first = optimization_service.run_baseline(
            clean, payload, input_columns=["u1", "u2"], output_column="y"
        )
        second = optimization_service.run_baseline(
            changed_test,
            payload.model_copy(update={"version_id": changed_test.version_id}),
            input_columns=["u1", "u2"],
            output_column="y",
        )

        assert first.status == second.status == "succeeded"
        assert first.parameters == second.parameters
        assert first.validation_free_run_fit == pytest.approx(second.validation_free_run_fit)
        assert observed_evaluate_test and all(value is False for value in observed_evaluate_test)
        assert first.test_free_run_fit is None
        assert first.test_mae is None
        assert first.test_rmse is None
        assert first.test_r2 is None
        assert second.test_free_run_fit is None
        assert first.parameters["window_size"] == 60
        assert first.parameters["train_ratio"] == 0.6
        assert first.parameters["validation_ratio"] == 0.2
        assert first.parameters["test_ratio"] == pytest.approx(0.2)

    def test_s6_rank_deficient_baseline_falls_back_to_ridge(self, tmp_path: Path) -> None:
        from app.schemas.optimization import OptimizationStartRequest
        from app.schemas.simulation import SimulationGenerateRequest
        from app.services.optimization_service import run_baseline
        from app.services.simulation_service import generate_simulation, load_simulation_by_version
        from app.services.version_data import VersionSeries

        generated = generate_simulation(
            SimulationGenerateRequest(
                scenario="S6",
                num_samples=1200,
                input_count=2,
                seed=9006,
                noise_level=0.0,
            ),
            artifact_root=tmp_path,
        )
        stored = load_simulation_by_version(generated.version_id, artifact_root=tmp_path)
        series = VersionSeries(
            dataset_id=stored.dataset_id,
            version_id=stored.version_id,
            dataset_name=stored.dataset_name,
            origin="simulation",
            timestamps=[],
            values={key: value for key, value in stored.values.items() if key != "timestamp"},
            declared_inputs=("u1", "u2"),
            declared_output="y",
            sample_period_seconds=1.0,
        )
        # Make rank deficiency explicit; adaptive windows can cover S6 transitions.
        series.values["u2"][:] = series.values["u1"]
        payload = OptimizationStartRequest(
            version_id=series.version_id,
            input_columns=["u1", "u2"],
            output_column="y",
            max_trials=5,
            random_seed=42,
        )

        baseline = run_baseline(
            series, payload, input_columns=["u1", "u2"], output_column="y"
        )

        assert baseline.status == "succeeded"
        assert baseline.parameters["estimator"] == "ridge"
        assert baseline.parameters["ridge_alpha"] == pytest.approx(0.1)
        assert baseline.parameters["fallback_reason"] == "DESIGN_MATRIX_RANK_DEFICIENT"
        assert baseline.validation_free_run_fit is not None
        assert baseline.test_free_run_fit is None

    def test_optuna_trials_do_not_evaluate_the_test_partition(self) -> None:
        from app.schemas.optimization import OptimizationStartRequest
        from app.services.optimization_service import run_study

        series = make_series()
        outcome = run_study(
            series,
            OptimizationStartRequest(
                version_id=series.version_id,
                input_columns=["u1", "u2"],
                output_column="y",
                max_trials=3,
                random_seed=5,
            ),
            input_columns=["u1", "u2"],
            output_column="y",
        )

        changed_test = make_series()
        test_start = int(changed_test.n_samples * 0.8)
        changed_test.values["y"][test_start:] += 10_000.0
        changed = run_study(
            changed_test,
            OptimizationStartRequest(
                version_id=changed_test.version_id,
                input_columns=["u1", "u2"],
                output_column="y",
                max_trials=3,
                random_seed=5,
            ),
            input_columns=["u1", "u2"],
            output_column="y",
        )

        completed = [trial for trial in outcome.trials if trial.state == "complete"]
        assert completed
        assert all("test_free_run_fit" not in trial.metrics for trial in completed)
        assert all("test_rmse" not in trial.metrics for trial in completed)
        for trial in completed:
            feedback = trial.metrics["validation_feedback"]
            assert feedback["partition"] == "validation"
            assert feedback["summary"]["partition"] == "validation"
            assert set(feedback["one_step"]) == {"mae", "rmse", "r2", "fit", "nrmse"}
            assert set(feedback["free_run"]) == {"mae", "rmse", "r2", "fit", "nrmse"}
            assert "test" not in feedback

            selection = trial.metrics["selection_provenance"]
            assert selection["candidate_count"] >= selection["gated_count"]
            assert selection["gated_count"] >= selection["selected_segment_count"]
            assert selection["selected_sample_count"] > 0
            assert len(selection["selected_indices_hash"]) == 64
            assert "selected_sample_indices" not in selection

            semantics = trial.metrics["objective_semantics"]
            assert semantics["name"] == "composite_identification_score"
            assert semantics["version"] == "v4"
            assert semantics["direction"] == "maximize"
            components = trial.metrics["objective_components"]
            assert components["final_score"] == pytest.approx(trial.value)
            assert trial.value == pytest.approx(
                components["validation_free_run_fit_component"]
                + components["normalized_error_component"]
                + components["residual_whiteness_component"]
                + components["complexity_component"]
                + components["rolling_adjustment_component"]
                + components["temporal_variability_component"]
            )
        assert all(
            trial.params.get("estimator") in {"ridge", "huber"} or "ridge_alpha" not in trial.params
            for trial in completed
        )
        assert changed.best_number == outcome.best_number
        assert changed.best_value == pytest.approx(outcome.best_value)
        assert changed.best_params == outcome.best_params


def test_legacy_optimization_contract_without_feedback_fields_remains_readable() -> None:
    from datetime import UTC, datetime

    from app.schemas.optimization import OptimizationStatusData, OptimizationTrial
    from app.services.contract_stubs import completed_task

    trial = OptimizationTrial.model_validate(
        {
            "trial_id": 0,
            "state": "complete",
            "value": 0.25,
            "params": {"window_size": 60},
            "created_at": datetime.now(UTC),
        }
    )
    assert trial.metrics == {}
    assert trial.selection_provenance is None
    assert trial.validation_feedback is None
    assert trial.objective_semantics is None
    assert trial.objective_components is None
    assert trial.diagnosis_policy_version is None
    assert trial.diagnosis_codes is None
    assert trial.diagnosis_evidence is None
    assert trial.rejection_provenance is None
    assert trial.bookkeeping is None

    status = OptimizationStatusData(
        study_id=uuid4(),
        study_status="succeeded",
        task=completed_task(stage="optimize_pipeline", message="legacy"),
        trials=[trial],
        best_trial_id=0,
        best_value=0.25,
        best_curve=[0.25],
        param_importances={},
    )
    assert status.objective_semantics is None
    assert status.best_validation_feedback is None
    assert status.best_selection_summary is None
    assert status.best_objective_components is None
    assert status.convergence is None
    assert status.stop_reason is None
    assert status.terminal_reason is None


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'optimize.db'}"
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(prepare())

    async def session_override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    settings = Settings(
        artifact_root=tmp_path,
        database_url=database_url,
        background_optimization=False,
    )
    monkeypatch.setattr("app.api.routes.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.job_queue.get_settings", lambda: settings)
    app = create_app()
    app.dependency_overrides[get_session] = session_override
    with TestClient(app) as client:
        yield client
    asyncio.run(engine.dispose())


def generate(client: TestClient, *, seed: int = 4, scenario: str = "S2") -> str:
    response = client.post(
        "/api/v1/simulation/generate",
        json={"scenario": scenario, "n_steps": 2000, "seed": seed, "input_count": 2},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["version_id"]


async def _dataset_version_count(database_path: Path, version_id: UUID) -> int:
    from app.models.dataset import DatasetVersion

    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            version = await session.get(DatasetVersion, version_id)
            assert version is not None
            count = await session.scalar(
                select(func.count())
                .select_from(DatasetVersion)
                .where(DatasetVersion.dataset_id == version.dataset_id)
            )
            return int(count or 0)
    finally:
        await engine.dispose()


async def _optimization_snapshot(
    database_path: Path, *, study_id: UUID, processing_run_id: UUID | None = None
) -> dict[str, object]:
    from app.models.dataset import ProcessingRun
    from app.models.optimization import OptimizationStudy

    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            study = await session.get(OptimizationStudy, study_id)
            assert study is not None
            final_test_runs = await session.scalar(
                select(func.count())
                .select_from(ProcessingRun)
                .where(
                    ProcessingRun.source_version_id == study.version_id,
                    ProcessingRun.run_type == "optimization.final_test",
                )
            )
            run = (
                await session.get(ProcessingRun, processing_run_id)
                if processing_run_id is not None
                else None
            )
            return {
                "study_status": study.status,
                "baseline_model_id": study.baseline_model_id,
                "optimized_model_id": study.optimized_model_id,
                "error_code": study.statistics.get("error_code"),
                "stop_reason": study.statistics.get("stop_reason"),
                "terminal_reason": study.statistics.get("terminal_reason"),
                "terminal_reason_history": study.statistics.get("terminal_reason_history"),
                "job": study.statistics.get("job"),
                "finished_at": study.finished_at,
                "final_test_run_count": int(final_test_runs or 0),
                "processing_run_type": run.run_type if run is not None else None,
                "processing_run_status": run.status if run is not None else None,
                "processing_run_source_version_id": run.source_version_id if run is not None else None,
            }
    finally:
        await engine.dispose()


async def _insert_legacy_optimization_study(database_path: Path) -> UUID:
    from app.models.optimization import OptimizationStudy

    study_id = uuid4()
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(
                OptimizationStudy(
                    id=study_id,
                    version_id=uuid4(),
                    status="succeeded",
                    objective="val_free_run_fit",
                    parameters={},
                    best_params={},
                    fingerprint={},
                    statistics={},
                )
            )
            await session.commit()
        return study_id
    finally:
        await engine.dispose()


async def _insert_rq_optimization_study(
    database_path: Path,
    *,
    status: str = "running",
    terminal_reason: dict[str, object] | None = None,
) -> UUID:
    from datetime import UTC, datetime

    from app.models.optimization import OptimizationStudy

    study_id = uuid4()
    statistics: dict[str, object] = {
        "job": {
            "contract_version": "optimization_job_v1",
            "execution_mode": "rq",
            "rq_job_id": str(study_id),
            "queue_name": "indusopt",
            "job_timeout_seconds": 3600,
            "submission_state": "SUBMITTED",
        }
    }
    if terminal_reason is not None:
        statistics["terminal_reason"] = terminal_reason
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with session_factory() as session:
            session.add(
                OptimizationStudy(
                    id=study_id,
                    version_id=uuid4(),
                    status=status,
                    objective="val_free_run_fit",
                    parameters={},
                    best_params={},
                    fingerprint={},
                    statistics=statistics,
                    created_at=datetime.now(UTC),
                    finished_at=(
                        datetime.now(UTC) if status in {"succeeded", "failed"} else None
                    ),
                )
            )
            await session.commit()
        return study_id
    finally:
        await engine.dispose()


async def _persist_rq_evidence(
    database_path: Path, *, study_id: UUID, evidence: object
) -> bool:
    from app.services.optimization_service import persist_rq_terminal_evidence

    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            return await persist_rq_terminal_evidence(
                session,
                study_id=study_id,
                evidence=evidence,  # type: ignore[arg-type]
            )
    finally:
        await engine.dispose()


async def _agent_optimization_snapshot(
    database_path: Path, *, study_id: UUID, processing_run_ids: list[str]
) -> dict[str, object]:
    from app.models.dataset import ProcessingRun
    from app.models.optimization import OptimizationStudy, OptimizationTrialRecord

    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            study = await session.get(OptimizationStudy, study_id)
            assert study is not None
            runs = [await session.get(ProcessingRun, UUID(run_id)) for run_id in processing_run_ids]
            final_test_runs = await session.scalar(
                select(func.count())
                .select_from(ProcessingRun)
                .where(
                    ProcessingRun.source_version_id == study.version_id,
                    ProcessingRun.run_type == "optimization.final_test",
                )
            )
            completed_params = list(
                (
                    await session.scalars(
                        select(OptimizationTrialRecord.params)
                        .where(
                            OptimizationTrialRecord.study_id == study_id,
                            OptimizationTrialRecord.state == "complete",
                        )
                        .order_by(OptimizationTrialRecord.trial_number)
                    )
                ).all()
            )
            return {
                "study_status": study.status,
                "baseline_model_id": study.baseline_model_id,
                "optimized_model_id": study.optimized_model_id,
                "stop_reason": study.statistics.get("stop_reason"),
                "terminal_reason": study.statistics.get("terminal_reason"),
                "job": study.statistics.get("job"),
                "processing_run_types": [run.run_type for run in runs if run is not None],
                "completed_trial_nks": [params.get("nk") for params in completed_params],
                "final_test_run_count": int(final_test_runs or 0),
            }
    finally:
        await engine.dispose()


class TestAgentSafeOptimizationEntry:
    def test_forces_inline_without_warm_start_and_returns_real_provenance(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from app.services import optimization_service
        from app.services.optimization_service import execute_agent_optimization_study

        def fail_if_enqueued(*args: object, **kwargs: object) -> None:
            raise AssertionError("Agent-safe optimization must not submit an RQ job")

        async def fail_if_warm_started(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            raise AssertionError("Agent-safe optimization must not read StrategyMemory")

        monkeypatch.setattr(optimization_service, "submit_optimization", fail_if_enqueued)
        monkeypatch.setattr(optimization_service, "_retrieve_warm_start", fail_if_warm_started)
        assert "baseline_model_id" not in optimization_service.OptimizationStartRequest.model_fields
        version_id = UUID(generate(client, seed=151))
        baseline_model_id = uuid4()
        before_versions = asyncio.run(_dataset_version_count(tmp_path / "optimize.db", version_id))

        async def execute() -> object:
            engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'optimize.db'}")
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                    return await execute_agent_optimization_study(
                        session,
                        payload=optimization_service.OptimizationStartRequest(
                            version_id=version_id,
                            input_columns=["u1", "u2"],
                            output_column="y",
                            max_trials=3,
                            random_seed=151,
                            search_space={"nk": [0, 0]},
                        ),
                        baseline_model_id=baseline_model_id,
                        artifact_root=tmp_path,
                    )
            finally:
                await engine.dispose()

        result = asyncio.run(execute())
        assert result.status == "succeeded"
        assert result.source_version_id == version_id
        assert result.baseline_model_id == baseline_model_id
        assert result.optimized_model_id
        assert len(result.processing_run_ids) == 2
        assert result.objective_semantics == {
            "name": "composite_identification_score",
            "version": "v4",
            "direction": "maximize",
        }
        assert result.best_validation_feedback["partition"] == "validation"
        assert result.best_validation_feedback["summary"]["partition"] == "validation"
        assert "test" not in result.best_validation_feedback
        assert result.best_selection_summary["selected_sample_count"] > 0
        assert len(result.best_selection_summary["selected_indices_hash"]) == 64
        assert result.best_objective_components["final_score"] == pytest.approx(
            result.best_value
        )
        assert result.stop_reason == {
            "policy_version": "optimization_stop_reason_v1",
            "code": "TRIAL_BUDGET_EXHAUSTED",
            "category": "NORMAL_LIMIT",
            "outcome": "WINNER_SELECTED",
            "observed_trial_count": 3,
            "target_trial_count": 3,
            "timeout_seconds": None,
        }
        assert (tmp_path / "models" / f"{result.optimized_model_id}.json").is_file()

        snapshot = asyncio.run(
            _agent_optimization_snapshot(
                tmp_path / "optimize.db",
                study_id=result.study_id,
                processing_run_ids=result.processing_run_ids,
            )
        )
        assert snapshot["study_status"] == "succeeded"
        assert snapshot["baseline_model_id"] == baseline_model_id
        assert snapshot["optimized_model_id"] == result.optimized_model_id
        assert snapshot["stop_reason"] == result.stop_reason
        assert snapshot["terminal_reason"]["code"] == "COMPLETED"  # type: ignore[index]
        assert snapshot["terminal_reason"]["category"] == "SUCCESS"  # type: ignore[index]
        assert snapshot["terminal_reason"]["phase"] == "study_persistence"  # type: ignore[index]
        assert snapshot["terminal_reason"]["error_code"] is None  # type: ignore[index]
        assert snapshot["job"]["execution_mode"] == "inline_agent"  # type: ignore[index]
        assert snapshot["job"]["rq_job_id"] is None  # type: ignore[index]
        assert snapshot["processing_run_types"] == ["optimization.baseline", "modeling.arx"]
        completed_nks = snapshot["completed_trial_nks"]
        assert completed_nks and all(value == 0 for value in completed_nks)
        assert snapshot["final_test_run_count"] == 0
        assert asyncio.run(_dataset_version_count(tmp_path / "optimize.db", version_id)) == before_versions

    def test_rejects_succeeded_study_without_persisted_optimized_model(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from app.services import optimization_service
        from app.services.optimization_service import (
            OptimizationDomainError,
            execute_agent_optimization_study,
        )

        reserved_study_ids: list[UUID] = []
        reserve = optimization_service._reserve_study
        persist_study = optimization_service._persist_study

        async def spy_reserve_study(*args: object, **kwargs: object) -> None:
            reserved_study_ids.append(kwargs["study_id"])  # type: ignore[index]
            await reserve(*args, **kwargs)  # type: ignore[arg-type]

        async def erase_optimized_model(*args: object, **kwargs: object) -> None:
            await persist_study(*args, **kwargs)  # type: ignore[arg-type]
            if kwargs["optimized_model_id"] is not None:  # type: ignore[index]
                study = await args[0].get(  # type: ignore[index]
                    optimization_service.OptimizationStudy, kwargs["outcome"].study_id  # type: ignore[index]
                )
                assert study is not None
                study.optimized_model_id = None
                study.status = "succeeded"
                await args[0].commit()  # type: ignore[index]

        monkeypatch.setattr(optimization_service, "_reserve_study", spy_reserve_study)
        monkeypatch.setattr(optimization_service, "_persist_study", erase_optimized_model)
        version_id = UUID(generate(client, seed=152))

        async def execute() -> None:
            engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'optimize.db'}")
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                    await execute_agent_optimization_study(
                        session,
                        payload=optimization_service.OptimizationStartRequest(
                            version_id=version_id,
                            input_columns=["u1", "u2"],
                            output_column="y",
                            max_trials=2,
                            random_seed=152,
                            search_space={"nk": [0, 0]},
                        ),
                        baseline_model_id=uuid4(),
                        artifact_root=tmp_path,
                    )
            finally:
                await engine.dispose()

        with pytest.raises(OptimizationDomainError) as raised:
            asyncio.run(execute())
        assert raised.value.code == "OPTIMIZED_MODEL_REQUIRED"
        assert len(reserved_study_ids) == 1
        snapshot = asyncio.run(
            _optimization_snapshot(tmp_path / "optimize.db", study_id=reserved_study_ids[0])
        )
        assert snapshot["study_status"] == "succeeded"
        assert snapshot["optimized_model_id"] is None
        assert snapshot["final_test_run_count"] == 0

class TestOptimizationApi:
    def test_full_train_fallback_persists_and_exports_without_selection(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import csv

        from app.services import modeling_service, optimization_service
        from app.services.segment_service import SegmentDomainError

        def reject_selection(*args: object, **kwargs: object) -> None:
            raise SegmentDomainError("NO_DYNAMIC_SEGMENT_FOUND", "All windows rejected")

        monkeypatch.setattr(optimization_service, "run_segment_selection", reject_selection)
        monkeypatch.setattr(optimization_service, "_structure_grid", lambda _: [
            {"na": 2, "nb": 2, "estimator": "ridge", "ridge_alpha": .1},
            {"na": 0, "nb": 8, "model_type": "FIR", "estimator": "ridge", "ridge_alpha": .1}])
        version_id = generate(client, seed=71)
        response = client.post("/api/v1/optimization/optuna/start", json={
            "version_id": version_id, "input_columns": ["u1", "u2"],
            "output_column": "y", "max_trials": 2})
        assert response.status_code == 202, response.text
        study_id = response.json()["data"]["study_id"]
        status = client.get(f"/api/v1/optimization/optuna/{study_id}/status").json()["data"]
        assert status["best_params"]["training_policy"] == "full_train"
        assert status["statistics"]["baseline_status"] == "failed"
        saved = modeling_service.load_saved_arx_model(
            model_id=UUID(status["optimized_model_id"]), artifact_root=tmp_path)
        indices = saved.payload.training_sample_indices
        assert indices and max(indices) < 1200 - saved.payload.history_guard
        assert saved.payload.sample_weights == {}
        export = client.post("/api/v1/delivery/export", json={
            "dataset_id": str(saved.dataset_id), "version_id": version_id,
            "input_columns": ["u1", "u2"], "output_column": "y",
            "mode": "optimization_best", "study_id": study_id})
        assert export.status_code == 200, export.text
        delivered = export.json()["data"]
        with (tmp_path / delivered["csv_uri"]).open() as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == len(indices) == delivered["exported_rows"]

    def test_legacy_study_without_convergence_returns_null(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        study_id = asyncio.run(
            _insert_legacy_optimization_study(tmp_path / "optimize.db")
        )

        response = client.get(f"/api/v1/optimization/optuna/{study_id}/status")

        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["study_status"] == "succeeded"
        assert data["convergence"] is None
        assert data["stop_reason"] is None
        assert data["terminal_reason"] is None

    @pytest.mark.parametrize(
        ("failure_target", "expected_phase", "expected_error_code"),
        [
            ("build_fingerprint", "preparation", "STUDY_PREPARATION_FAILED"),
            ("run_baseline", "baseline", "BASELINE_EXECUTION_FAILED"),
            ("run_study", "search", "STUDY_EXECUTION_FAILED"),
        ],
    )
    def test_application_exception_persists_failed_terminal_reason(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        failure_target: str,
        expected_phase: str,
        expected_error_code: str,
    ) -> None:
        from app.services import optimization_service

        reserved_study_ids: list[UUID] = []
        reserve = optimization_service._reserve_study

        async def spy_reserve_study(*args: object, **kwargs: object) -> None:
            reserved_study_ids.append(kwargs["study_id"])  # type: ignore[index]
            await reserve(*args, **kwargs)  # type: ignore[arg-type]

        def fail_lifecycle_phase(*args: object, **kwargs: object) -> None:
            raise RuntimeError(f"forced {failure_target} failure")

        monkeypatch.setattr(optimization_service, "_reserve_study", spy_reserve_study)
        monkeypatch.setattr(optimization_service, failure_target, fail_lifecycle_phase)
        version_id = generate(client, seed=201)

        with pytest.raises(RuntimeError, match=f"forced {failure_target} failure"):
            client.post(
                "/api/v1/optimization/optuna/start",
                json={
                    "version_id": version_id,
                    "input_columns": ["u1", "u2"],
                    "output_column": "y",
                    "max_trials": 1,
                    "random_seed": 201,
                },
            )

        assert len(reserved_study_ids) == 1
        snapshot = asyncio.run(
            _optimization_snapshot(tmp_path / "optimize.db", study_id=reserved_study_ids[0])
        )
        terminal_reason = snapshot["terminal_reason"]
        assert snapshot["study_status"] == "failed"
        assert snapshot["error_code"] == expected_error_code
        assert snapshot["finished_at"] is not None
        assert terminal_reason["policy_version"] == "optimization_terminal_reason_v2"  # type: ignore[index]
        assert terminal_reason["code"] == "FAILED"  # type: ignore[index]
        assert terminal_reason["category"] == "SYSTEM_FAILURE"  # type: ignore[index]
        assert terminal_reason["phase"] == expected_phase  # type: ignore[index]
        assert terminal_reason["error_code"] == expected_error_code  # type: ignore[index]

    def test_study_persistence_exception_uses_study_persistence_phase(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from app.services import optimization_service

        reserved_study_ids: list[UUID] = []
        reserve = optimization_service._reserve_study

        async def spy_reserve_study(*args: object, **kwargs: object) -> None:
            reserved_study_ids.append(kwargs["study_id"])  # type: ignore[index]
            await reserve(*args, **kwargs)  # type: ignore[arg-type]

        async def fail_study_persistence(*args: object, **kwargs: object) -> None:
            raise RuntimeError("forced study persistence failure")

        monkeypatch.setattr(optimization_service, "_reserve_study", spy_reserve_study)
        monkeypatch.setattr(optimization_service, "_persist_study", fail_study_persistence)
        version_id = generate(client, seed=202)

        with pytest.raises(RuntimeError, match="forced study persistence failure"):
            client.post(
                "/api/v1/optimization/optuna/start",
                json={
                    "version_id": version_id,
                    "input_columns": ["u1", "u2"],
                    "output_column": "y",
                    "max_trials": 1,
                    "random_seed": 202,
                },
            )

        assert len(reserved_study_ids) == 1
        snapshot = asyncio.run(
            _optimization_snapshot(tmp_path / "optimize.db", study_id=reserved_study_ids[0])
        )
        terminal_reason = snapshot["terminal_reason"]
        assert snapshot["study_status"] == "failed"
        assert snapshot["error_code"] == "STUDY_PERSISTENCE_FAILED"
        assert terminal_reason["code"] == "FAILED"  # type: ignore[index]
        assert terminal_reason["phase"] == "study_persistence"  # type: ignore[index]

    def test_no_valid_candidate_preserves_normal_budget_stop_reason(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from app.services import optimization_service

        formal_objective = optimization_service.objective_value
        objective_calls = 0

        def reject_candidate(result: object) -> tuple[float, dict[str, object]]:
            nonlocal objective_calls
            objective_calls += 1
            if objective_calls == 1:
                return formal_objective(result)  # type: ignore[arg-type]
            return float("-inf"), {
                "reason": "unstable",
                "objective_semantics": dict(optimization_service.OBJECTIVE_SEMANTICS),
                "objective_components": {
                    "stability_gate": False,
                    "final_score": None,
                },
            }

        monkeypatch.setattr(optimization_service, "objective_value", reject_candidate)
        version_id = generate(client, seed=153)
        started = client.post(
            "/api/v1/optimization/optuna/start",
            json={
                "version_id": version_id,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "max_trials": 1,
                "random_seed": 153,
            },
        )

        assert started.status_code == 202, started.text
        study_id = UUID(started.json()["data"]["study_id"])
        status = client.get(f"/api/v1/optimization/optuna/{study_id}/status")
        assert status.status_code == 200, status.text
        data = status.json()["data"]
        assert data["best_trial_id"] is None
        assert data["stop_reason"] == {
            "policy_version": "optimization_stop_reason_v1",
            "code": "TRIAL_BUDGET_EXHAUSTED",
            "category": "NORMAL_LIMIT",
            "outcome": "NO_VALID_CANDIDATE",
            "observed_trial_count": 1,
            "target_trial_count": 1,
            "timeout_seconds": None,
        }
        snapshot = asyncio.run(
            _optimization_snapshot(tmp_path / "optimize.db", study_id=study_id)
        )
        assert snapshot["study_status"] == "failed"
        assert snapshot["stop_reason"] == data["stop_reason"]
        assert data["study_status"] == "failed"
        assert data["terminal_reason"]["code"] == "NO_VALID_CANDIDATE"
        assert data["terminal_reason"]["category"] == "BUSINESS_FAILURE"
        assert data["terminal_reason"]["phase"] == "search"
        assert data["terminal_reason"]["error_code"] is None
        assert data["terminal_reason"] == data["statistics"]["terminal_reason"]
        assert snapshot["terminal_reason"] == data["terminal_reason"]

    def test_persists_optimized_model_without_opening_test(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from app.services import optimization_service

        def fail_if_final_test_replayed(*args: object, **kwargs: object) -> None:
            raise AssertionError("execute_study must not replay the held-out Test partition")

        formal_fit = optimization_service.fit_arx_on_version
        formal_selection = optimization_service.run_segment_selection
        persisted_fits = []
        selections: list[list[int]] = []

        async def spy_fit_arx_on_version(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            data = await formal_fit(*args, **kwargs)  # type: ignore[arg-type]
            persisted_fits.append((kwargs["payload"], data))  # type: ignore[index]
            return data

        def spy_segment_selection(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            selection = formal_selection(*args, **kwargs)  # type: ignore[arg-type]
            selections.append(list(selection.selected_sample_indices))
            return selection

        monkeypatch.setattr(optimization_service, "evaluate_best_trial", fail_if_final_test_replayed)
        monkeypatch.setattr(optimization_service, "fit_arx_on_version", spy_fit_arx_on_version)
        monkeypatch.setattr(optimization_service, "run_segment_selection", spy_segment_selection)
        version_id = generate(client, seed=52)
        before_versions = asyncio.run(_dataset_version_count(tmp_path / "optimize.db", UUID(version_id)))
        started = client.post(
            "/api/v1/optimization/optuna/start",
            json={
                "version_id": version_id,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "max_trials": 4,
                "random_seed": 19,
            },
        )
        assert started.status_code == 202, started.text
        study_id = UUID(started.json()["data"]["study_id"])
        data = client.get(f"/api/v1/optimization/optuna/{study_id}/status").json()["data"]

        baseline = data["baseline"]
        assert baseline["status"] == "succeeded"
        assert baseline["processing_run_id"]
        assert baseline["parameters"]["window_size"] == 60
        assert baseline["validation_free_run_fit"] is not None
        assert baseline["test_free_run_fit"] is None
        assert baseline["test_mae"] is None
        assert baseline["test_rmse"] is None
        assert baseline["test_r2"] is None
        assert len(data["trials"]) == 4, "Baseline must not become an Optuna trial."

        complete = [trial for trial in data["trials"] if trial["state"] == "complete"]
        selected = max(complete, key=lambda trial: trial["value"])
        assert data["best_trial_id"] == selected["trial_id"]
        assert data["objective_semantics"] == {
            "name": "composite_identification_score",
            "version": "v4",
            "direction": "maximize",
        }
        assert data["best_validation_feedback"] == selected["validation_feedback"]
        assert data["best_selection_summary"] == selected["selection_provenance"]
        assert data["best_objective_components"] == selected["objective_components"]
        assert selected["bookkeeping"]["decision"] == "CANDIDATE_VALID_NEW_BEST"
        assert data["best_curve"] == [
            trial["bookkeeping"]["best_so_far"] for trial in data["trials"]
        ]
        assert data["convergence"] == data["statistics"]["convergence"]
        assert data["convergence"] == {
            "policy_version": "optimization_convergence_v1",
            "mode": "observed_only",
            "status": "INSUFFICIENT_EVIDENCE",
            "no_improvement_streak": data["convergence"]["no_improvement_streak"],
            "patience": 16,
            "min_meaningful_improvement": 0.001,
            "min_valid_trials": 17,
            "valid_trial_count": len(complete),
            "last_meaningful_improvement_trial": data["convergence"][
                "last_meaningful_improvement_trial"
            ],
            "best_trial_number": data["best_trial_id"],
            "observed_at_trial_count": len(data["trials"]),
        }
        assert data["stop_reason"] == data["statistics"]["stop_reason"]
        assert data["stop_reason"] == {
            "policy_version": "optimization_stop_reason_v1",
            "code": "TRIAL_BUDGET_EXHAUSTED",
            "category": "NORMAL_LIMIT",
            "outcome": "WINNER_SELECTED",
            "observed_trial_count": 4,
            "target_trial_count": 4,
            "timeout_seconds": None,
        }
        assert selected["metrics"]["validation_feedback"] == selected["validation_feedback"]
        assert selected["validation_feedback"]["partition"] == "validation"
        assert selected["validation_feedback"]["summary"]["partition"] == "validation"
        assert selected["selection_provenance"]["selected_sample_count"] > 0
        assert len(selected["selection_provenance"]["selected_indices_hash"]) == 64
        assert selected["objective_components"]["final_score"] == pytest.approx(
            selected["value"]
        )
        assert data["final_test_evaluation"] is None
        assert data["baseline_model_id"] is None
        assert data["optimized_model_id"]
        assert len(persisted_fits) == 1

        fitted_payload, fitted = persisted_fits[0]
        assert fitted_payload.evaluate_test is False
        assert fitted.model_id == UUID(data["optimized_model_id"])
        assert fitted.metrics.one_step.get("test") is None
        assert fitted.metrics.free_run.get("test") is None
        assert fitted_payload.training_sample_indices == selections[-1]

        artifact = tmp_path / "models" / f"{fitted.model_id}.json"
        document = json.loads(artifact.read_text(encoding="utf-8"))
        assert document["model_id"] == str(fitted.model_id)
        assert document["version_id"] == version_id
        assert document["configuration"]["evaluate_test"] is False
        assert document["configuration"]["training_sample_indices"] == fitted_payload.training_sample_indices

        snapshot = asyncio.run(
            _optimization_snapshot(
                tmp_path / "optimize.db",
                study_id=study_id,
                processing_run_id=fitted.processing_run_id,
            )
        )
        assert snapshot["study_status"] == "succeeded"
        assert data["study_status"] == "succeeded"
        assert data["terminal_reason"]["code"] == "COMPLETED"
        assert data["terminal_reason"]["category"] == "SUCCESS"
        assert data["terminal_reason"]["phase"] == "study_persistence"
        assert data["terminal_reason"]["error_code"] is None
        assert data["terminal_reason"] == data["statistics"]["terminal_reason"]
        assert snapshot["baseline_model_id"] is None
        assert snapshot["optimized_model_id"] == fitted.model_id
        assert snapshot["processing_run_type"] == "modeling.arx"
        assert snapshot["processing_run_status"] == "succeeded"
        assert snapshot["processing_run_source_version_id"] == UUID(version_id)
        assert snapshot["final_test_run_count"] == 0
        assert asyncio.run(_dataset_version_count(tmp_path / "optimize.db", UUID(version_id))) == before_versions

    def test_optimized_model_persistence_failure_marks_study_failed(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from app.services import optimization_service
        from app.services.modeling_service import ModelingDomainError

        reserved_study_ids: list[UUID] = []
        reserve = optimization_service._reserve_study

        async def spy_reserve_study(*args: object, **kwargs: object) -> None:
            reserved_study_ids.append(kwargs["study_id"])  # type: ignore[index]
            await reserve(*args, **kwargs)  # type: ignore[arg-type]

        async def fail_formal_fit(*args: object, **kwargs: object) -> None:
            raise ModelingDomainError("OPTIMIZED_MODEL_PERSISTENCE_FAILED", "formal fit failed")

        monkeypatch.setattr(optimization_service, "_reserve_study", spy_reserve_study)
        monkeypatch.setattr(optimization_service, "fit_arx_on_version", fail_formal_fit)
        version_id = generate(client, seed=79)
        response = client.post(
            "/api/v1/optimization/optuna/start",
            json={
                "version_id": version_id,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "max_trials": 2,
                "random_seed": 29,
            },
        )

        assert response.status_code == 400, response.text
        assert len(reserved_study_ids) == 1
        snapshot = asyncio.run(
            _optimization_snapshot(tmp_path / "optimize.db", study_id=reserved_study_ids[0])
        )
        assert snapshot["study_status"] == "failed"
        assert snapshot["error_code"] == "OPTIMIZED_MODEL_PERSISTENCE_FAILED"
        assert snapshot["terminal_reason"]["code"] == "FAILED"  # type: ignore[index]
        assert snapshot["terminal_reason"]["category"] == "SYSTEM_FAILURE"  # type: ignore[index]
        assert snapshot["terminal_reason"]["phase"] == "winner_persistence"  # type: ignore[index]
        assert snapshot["terminal_reason"]["error_code"] == (  # type: ignore[index]
            "OPTIMIZED_MODEL_PERSISTENCE_FAILED"
        )
        assert snapshot["finished_at"] is not None
        assert snapshot["optimized_model_id"] is None
        assert snapshot["final_test_run_count"] == 0

    def test_diagnostics_replay_fixed_winner_without_changing_study(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        version_id = generate(client, seed=73)
        started = client.post(
            "/api/v1/optimization/optuna/start",
            json={
                "version_id": version_id,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "max_trials": 2,
                "random_seed": 23,
            },
        )
        assert started.status_code == 202, started.text
        study_id = started.json()["data"]["study_id"]
        before = client.get(f"/api/v1/optimization/optuna/{study_id}/status").json()["data"]

        from app.services import modeling_service
        def fail_if_refitted(*args: object, **kwargs: object) -> None:
            raise AssertionError("Diagnostics must replay the frozen model")
        monkeypatch.setattr(modeling_service, "estimate_parameters", fail_if_refitted)
        response = client.get(f"/api/v1/optimization/optuna/{study_id}/diagnostics")
        assert response.status_code == 200, response.text
        diagnostics = response.json()["data"]
        assert set(diagnostics["partitions"]) == {"train", "validation", "test"}
        assert diagnostics["partitions"]["test"]["one_step"]["r2"] is not None
        assert diagnostics["partitions"]["test"]["free_run"]["fit"] is not None
        assert diagnostics["metric_semantics"]["one_step"]

        after = client.get(f"/api/v1/optimization/optuna/{study_id}/status").json()["data"]
        assert after["best_trial_id"] == before["best_trial_id"]
        assert len(after["trials"]) == len(before["trials"])

    def test_closed_loop_runs_and_reports_cache_statistics(self, client: TestClient) -> None:
        version_id = generate(client)
        started = client.post(
            "/api/v1/optimization/optuna/start",
            json={
                "version_id": version_id,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "max_trials": 12,
                "random_seed": 7,
            },
        )
        assert started.status_code == 202, started.text
        study_id = started.json()["data"]["study_id"]

        status = client.get(f"/api/v1/optimization/optuna/{study_id}/status")
        assert status.status_code == 200, status.text
        data = status.json()["data"]

        assert len(data["trials"]) == 12
        assert data["best_value"] is not None
        assert data["best_params"]
        assert data["statistics"]["total_trials"] == 12
        assert data["statistics"]["lookups"] > 0

    def test_the_expensive_stage_is_amortised_across_the_structure_sweep(
        self, client: TestClient
    ) -> None:
        """Selection is the expensive stage; every trial must reuse one across many fits.

        This is where the closed-loop saving actually comes from. Measured separately, the
        content-addressed cache hits only ~1.7% of the time in a flat TPE search because a
        five-dimensional head almost never repeats, so the staged design carries the win
        and the assertion is written against that, not against the cache.
        """

        version_id = generate(client)
        started = client.post(
            "/api/v1/optimization/optuna/start",
            json={
                "version_id": version_id,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "max_trials": 6,
                "random_seed": 17,
            },
        )
        study_id = started.json()["data"]["study_id"]
        stats = client.get(f"/api/v1/optimization/optuna/{study_id}/status").json()["data"][
            "statistics"
        ]

        assert stats["structure_evaluations"] > stats["selection_computations"]
        assert stats["evaluations_per_selection"] > 5.0

    def test_convergence_curve_is_monotone_non_decreasing(self, client: TestClient) -> None:
        version_id = generate(client)
        started = client.post(
            "/api/v1/optimization/optuna/start",
            json={
                "version_id": version_id,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "max_trials": 10,
                "random_seed": 3,
            },
        )
        study_id = started.json()["data"]["study_id"]
        curve = client.get(f"/api/v1/optimization/optuna/{study_id}/status").json()["data"][
            "best_curve"
        ]
        seen = [value for value in curve if value is not None]
        assert seen == sorted(seen), "the best-so-far curve can never go down"

    def test_failed_trials_are_persisted_not_hidden(self, client: TestClient) -> None:
        version_id = generate(client)
        started = client.post(
            "/api/v1/optimization/optuna/start",
            json={
                "version_id": version_id,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "max_trials": 14,
                "random_seed": 11,
            },
        )
        study_id = started.json()["data"]["study_id"]
        data = client.get(f"/api/v1/optimization/optuna/{study_id}/status").json()["data"]
        states = {trial["state"] for trial in data["trials"]}
        assert states <= {"complete", "pruned", "failed"}
        assert data["statistics"]["total_trials"] == len(data["trials"])

    def test_second_study_on_a_different_dataset_is_warm_started(self, client: TestClient) -> None:
        """The self-evolving path: a finished study leaves a reusable prior behind."""

        first_version = generate(client, seed=4)
        first = client.post(
            "/api/v1/optimization/optuna/start",
            json={
                "version_id": first_version,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "max_trials": 10,
                "random_seed": 5,
            },
        )
        assert first.status_code == 202, first.text

        second_version = generate(client, seed=9)
        second = client.post(
            "/api/v1/optimization/optuna/start",
            json={
                "version_id": second_version,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "max_trials": 10,
                "random_seed": 5,
            },
        )
        assert second.status_code == 202, second.text
        second_id = second.json()["data"]["study_id"]
        data = client.get(f"/api/v1/optimization/optuna/{second_id}/status").json()["data"]

        assert data["warm_started_from"] is not None, (
            "a similar previous study should supply a warm start"
        )
        assert data["statistics"]["warm_start_trials"] > 0

    def test_status_of_an_unknown_study_returns_404(self, client: TestClient) -> None:
        response = client.get(f"/api/v1/optimization/optuna/{uuid4()}/status")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "OPTIMIZATION_STUDY_NOT_FOUND"

    def test_unknown_version_returns_404(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/optimization/optuna/start",
            json={
                "version_id": str(uuid4()),
                "input_columns": ["u1"],
                "output_column": "y",
                "max_trials": 2,
            },
        )
        assert response.status_code == 404


class TestJobQueueFallback:
    """Queueing is an optimisation, not a dependency.

    The venue may have no Redis and no worker process. The same reasoning that keeps the
    system usable without an LLM applies here: when the queue cannot be reached the study
    runs inline and the response says so. What must never happen is a request that reports
    success while the work was silently dropped.
    """

    def test_disabled_by_default_so_a_deployment_without_a_worker_still_works(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.services import job_queue

        monkeypatch.setattr(
            job_queue,
            "get_settings",
            lambda: Settings(background_optimization=False),
        )

        submission = job_queue.submit_optimization(uuid4(), {"version_id": str(uuid4())})
        assert submission.queued is False
        assert submission.job_id is None
        assert submission.reason  # the caller has to be able to say why

    def test_an_unreachable_redis_falls_back_instead_of_raising(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.services import job_queue

        monkeypatch.setattr(
            job_queue,
            "get_settings",
            lambda: Settings(
                background_optimization=True,
                # Port 1 is reserved and never listening.
                redis_url="redis://127.0.0.1:1/0",
            ),
        )
        submission = job_queue.submit_optimization(uuid4(), {})
        assert submission.queued is False
        assert "队列不可用" in (submission.reason or "")

    def test_the_study_runs_inline_when_the_queue_is_unavailable(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.services import optimization_service
        from app.services.job_queue import Submission

        monkeypatch.setattr(
            optimization_service,
            "background_optimization_enabled",
            lambda: True,
        )
        monkeypatch.setattr(
            optimization_service,
            "submit_optimization",
            lambda study_id, payload: Submission(
                outcome="CONFIRMED_NOT_ENQUEUED",
                job_id=None,
                reason="队列不可用（test fixture）",
            ),
        )

        version_id = generate(client, seed=21)
        started = client.post(
            "/api/v1/optimization/optuna/start",
            json={
                "version_id": version_id,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "max_trials": 3,
            },
        )
        assert started.status_code == 202, started.text
        payload = started.json()["data"]
        assert payload["task"]["status"] == "succeeded"
        assert payload["task"]["id"] == payload["study_id"]

        def fail_if_redis_is_queried(*args: object, **kwargs: object) -> None:
            raise AssertionError("inline HTTP status must not query Redis")

        monkeypatch.setattr(
            optimization_service,
            "observe_optimization_job",
            fail_if_redis_is_queried,
        )

        status = client.get(f"/api/v1/optimization/optuna/{payload['study_id']}/status")
        status_payload = status.json()["data"]
        assert len(status_payload["trials"]) == 3
        assert status_payload["task"]["id"] == payload["study_id"]
        assert status_payload["job"]["execution_mode"] == "inline_http"
        assert status_payload["job"]["availability"] == "NOT_APPLICABLE"

    def test_a_bad_version_never_leaves_an_orphan_queued_study(self, client: TestClient) -> None:
        """Reserving the row before validating would strand studies no worker can finish."""

        missing = str(uuid4())
        response = client.post(
            "/api/v1/optimization/optuna/start",
            json={
                "version_id": missing,
                "input_columns": ["u1"],
                "output_column": "y",
                "max_trials": 2,
            },
        )
        assert response.status_code == 404
        # The id the client would have polled must not exist either.
        assert client.get(f"/api/v1/optimization/optuna/{missing}/status").status_code == 404


class TestRqIdentityAndTruthfulStatus:
    @staticmethod
    def _fake_job(study_id: UUID, *, status: str = "queued") -> object:
        from datetime import UTC, datetime
        from types import SimpleNamespace

        timestamp = datetime.now(UTC)

        class FakeJob:
            id = str(study_id)
            meta = {"study_id": str(study_id), "job_kind": "optimization"}
            func_name = "app.worker.run_optimization_job"
            origin = "indusopt"
            timeout = 3600
            created_at = timestamp
            enqueued_at = timestamp
            started_at = timestamp if status == "started" else None
            ended_at = (
                timestamp if status in {"finished", "failed", "stopped", "canceled"} else None
            )

            def get_status(self, *, refresh: bool = True) -> object:
                assert refresh is True
                return SimpleNamespace(value=status)

        return FakeJob()

    def test_enqueue_uses_study_id_unique_identity_and_metadata(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import rq
        from app.services import job_queue
        from redis import Redis

        study_id = uuid4()
        captured: dict[str, object] = {}

        class Connection:
            def ping(self) -> bool:
                return True

        class Queue:
            def __init__(self, *args: object, **kwargs: object) -> None:
                captured["queue_init"] = (args, kwargs)

            def enqueue(self, *args: object, **kwargs: object) -> object:
                captured["enqueue"] = (args, kwargs)
                return TestRqIdentityAndTruthfulStatus._fake_job(study_id)

        monkeypatch.setattr(
            job_queue,
            "get_settings",
            lambda: Settings(background_optimization=True),
        )
        monkeypatch.setattr(Redis, "from_url", lambda *args, **kwargs: Connection())
        monkeypatch.setattr(rq, "Queue", Queue)

        submission = job_queue.submit_optimization(study_id, {"max_trials": 3})

        assert submission.outcome == "SUBMITTED"
        assert submission.job_id == str(study_id)
        args, kwargs = captured["enqueue"]  # type: ignore[misc]
        assert args == (
            "app.worker.run_optimization_job",
            str(study_id),
            {"max_trials": 3},
        )
        assert kwargs["job_id"] == str(study_id)  # type: ignore[index]
        assert kwargs["unique"] is True  # type: ignore[index]
        assert kwargs["meta"] == {  # type: ignore[index]
            "study_id": str(study_id),
            "job_kind": "optimization",
        }
        callback = kwargs["on_failure"]  # type: ignore[index]
        assert callback.name == "app.worker.handle_optimization_job_failure"
        assert callback.timeout == 30

    def test_duplicate_enqueue_recovers_matching_existing_job(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import rq
        from app.services import job_queue
        from redis import Redis
        from rq.exceptions import DuplicateJobError
        from rq.job import Job

        study_id = uuid4()
        existing = self._fake_job(study_id, status="started")

        class Connection:
            def ping(self) -> bool:
                return True

        class Queue:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            def enqueue(self, *args: object, **kwargs: object) -> object:
                raise DuplicateJobError("duplicate")

        monkeypatch.setattr(
            job_queue,
            "get_settings",
            lambda: Settings(background_optimization=True),
        )
        monkeypatch.setattr(Redis, "from_url", lambda *args, **kwargs: Connection())
        monkeypatch.setattr(rq, "Queue", Queue)
        monkeypatch.setattr(Job, "fetch", classmethod(lambda cls, *args, **kwargs: existing))

        submission = job_queue.submit_optimization(study_id, {})

        assert submission.outcome == "SUBMITTED"
        assert submission.observation is not None
        assert submission.observation.raw_status == "started"

    @pytest.mark.parametrize(
        ("fetch_error", "expected_outcome", "allows_inline"),
        [
            ("missing", "CONFIRMED_NOT_ENQUEUED", True),
            ("unavailable", "SUBMISSION_UNKNOWN", False),
        ],
    )
    def test_enqueue_error_only_allows_inline_after_confirmed_absence(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fetch_error: str,
        expected_outcome: str,
        allows_inline: bool,
    ) -> None:
        import rq
        from app.services import job_queue
        from redis import Redis
        from rq.exceptions import NoSuchJobError
        from rq.job import Job

        study_id = uuid4()

        class Connection:
            def ping(self) -> bool:
                return True

        class Queue:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            def enqueue(self, *args: object, **kwargs: object) -> object:
                raise RuntimeError("enqueue acknowledgement lost")

        def fetch(*args: object, **kwargs: object) -> object:
            if fetch_error == "missing":
                raise NoSuchJobError("missing")
            raise ConnectionError("redis unavailable")

        monkeypatch.setattr(
            job_queue,
            "get_settings",
            lambda: Settings(background_optimization=True),
        )
        monkeypatch.setattr(Redis, "from_url", lambda *args, **kwargs: Connection())
        monkeypatch.setattr(rq, "Queue", Queue)
        monkeypatch.setattr(Job, "fetch", classmethod(lambda cls, *args, **kwargs: fetch()))

        submission = job_queue.submit_optimization(study_id, {})

        assert submission.outcome == expected_outcome
        assert submission.allows_inline is allows_inline
        if not allows_inline:
            assert submission.job_id == str(study_id)

    @pytest.mark.parametrize(
        ("raw_status", "task_status"),
        [
            ("created", "queued"),
            ("deferred", "queued"),
            ("scheduled", "queued"),
            ("queued", "queued"),
            ("started", "running"),
            ("finished", "succeeded"),
            ("failed", "failed"),
            ("stopped", "cancelled"),
            ("canceled", "cancelled"),
        ],
    )
    def test_task_projection_uses_real_rq_status(
        self, raw_status: str, task_status: str
    ) -> None:
        from datetime import UTC, datetime

        from app.models.optimization import OptimizationStudy
        from app.schemas.optimization import OptimizationJobObservation
        from app.services.optimization_service import _optimization_task

        study_id = uuid4()
        timestamp = datetime.now(UTC)
        study = OptimizationStudy(
            id=study_id,
            version_id=uuid4(),
            status="failed" if raw_status == "finished" else "queued",
            statistics={},
            parameters={},
            best_params={},
            fingerprint={},
            created_at=timestamp,
        )
        job = OptimizationJobObservation(
            execution_mode="rq",
            availability="AVAILABLE",
            rq_job_id=str(study_id),
            queue_name="indusopt",
            raw_status=raw_status,
            observed_at=timestamp,
            created_at=timestamp,
            started_at=timestamp if raw_status == "started" else None,
            ended_at=(
                timestamp
                if raw_status in {"finished", "failed", "stopped", "canceled"}
                else None
            ),
        )

        task = _optimization_task(study=study, job=job, message="status")

        assert task.id == study_id
        assert task.status == task_status
        if raw_status == "finished":
            assert study.status == "failed"
            assert task.status == "succeeded"

    @pytest.mark.parametrize(
        ("availability", "study_status", "expected_status", "expected_error"),
        [
            ("UNAVAILABLE", "queued", "queued", "RQ_RECONCILIATION_UNAVAILABLE"),
            ("NOT_FOUND", "running", "running", "RQ_JOB_NOT_FOUND"),
            ("NOT_FOUND", "succeeded", "succeeded", None),
        ],
    )
    def test_unavailable_or_missing_job_uses_db_without_guessing_a_terminal_reason(
        self,
        availability: str,
        study_status: str,
        expected_status: str,
        expected_error: str | None,
    ) -> None:
        from datetime import UTC, datetime

        from app.models.optimization import OptimizationStudy
        from app.schemas.optimization import OptimizationJobObservation
        from app.services.optimization_service import _optimization_task

        study_id = uuid4()
        timestamp = datetime.now(UTC)
        study = OptimizationStudy(
            id=study_id,
            version_id=uuid4(),
            status=study_status,
            statistics={"job": {"execution_mode": "rq"}},
            parameters={},
            best_params={},
            fingerprint={},
            created_at=timestamp,
            finished_at=timestamp if study_status in {"succeeded", "failed"} else None,
        )
        job = OptimizationJobObservation(
            execution_mode="rq",
            availability=availability,
            rq_job_id=str(study_id),
            queue_name="indusopt",
            observed_at=timestamp,
            error_code=(
                "RQ_RECONCILIATION_UNAVAILABLE"
                if availability == "UNAVAILABLE"
                else "RQ_JOB_NOT_FOUND"
            ),
        )

        task = _optimization_task(study=study, job=job, message="status")

        assert task.status == expected_status
        assert (task.error.code if task.error else None) == expected_error
        assert study.status == study_status
        assert "terminal_reason" not in study.statistics

    def test_start_and_status_keep_stable_id_without_writing_observation(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        from datetime import UTC, datetime

        from app.services import optimization_service
        from app.services.job_queue import JobObservation, Submission

        timestamp = datetime.now(UTC)
        observed_study_ids: list[UUID] = []

        def submit(study_id: UUID, payload: dict[str, object]) -> Submission:
            del payload
            return Submission(
                outcome="SUBMITTED",
                job_id=str(study_id),
                reason=None,
                observation=JobObservation(
                    availability="AVAILABLE",
                    job_id=str(study_id),
                    queue_name="indusopt",
                    raw_status="queued",
                    created_at=timestamp,
                    enqueued_at=timestamp,
                ),
            )

        def observe(
            *,
            study_id: UUID,
            job_id: str,
            queue_name: str,
            expected_timeout_seconds: int,
        ) -> JobObservation:
            observed_study_ids.append(study_id)
            assert job_id == str(study_id)
            assert queue_name == "indusopt"
            assert expected_timeout_seconds == 3600
            return JobObservation(
                availability="AVAILABLE",
                job_id=job_id,
                queue_name=queue_name,
                raw_status="started",
                created_at=timestamp,
                enqueued_at=timestamp,
                started_at=timestamp,
            )

        monkeypatch.setattr(optimization_service, "background_optimization_enabled", lambda: True)
        monkeypatch.setattr(optimization_service, "submit_optimization", submit)
        monkeypatch.setattr(optimization_service, "reconcile_optimization_job", observe)
        version_id = generate(client, seed=301)

        started = client.post(
            "/api/v1/optimization/optuna/start",
            json={
                "version_id": version_id,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "max_trials": 3,
            },
        ).json()["data"]
        study_id = UUID(started["study_id"])
        before = asyncio.run(
            _optimization_snapshot(tmp_path / "optimize.db", study_id=study_id)
        )

        status = client.get(f"/api/v1/optimization/optuna/{study_id}/status").json()["data"]
        after = asyncio.run(_optimization_snapshot(tmp_path / "optimize.db", study_id=study_id))

        assert started["task"]["id"] == str(study_id)
        assert status["task"]["id"] == str(study_id)
        assert status["task"]["status"] == "running"
        assert status["study_status"] == "queued"
        assert status["job"]["raw_status"] == "started"
        assert before["job"]["contract_version"] == "optimization_job_v1"  # type: ignore[index]
        assert before["job"]["execution_mode"] == "rq"  # type: ignore[index]
        assert before["job"]["rq_job_id"] == str(study_id)  # type: ignore[index]
        assert before["job"]["queue_name"] == "indusopt"  # type: ignore[index]
        assert before["job"]["job_timeout_seconds"] == 3600  # type: ignore[index]
        assert before["job"]["submission_state"] == "SUBMISSION_REQUESTED"  # type: ignore[index]
        assert before == after
        assert observed_study_ids == [study_id]

    def test_unknown_enqueue_outcome_never_runs_inline(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from app.services import optimization_service
        from app.services.job_queue import JobObservation, Submission

        def submit(study_id: UUID, payload: dict[str, object]) -> Submission:
            del payload
            return Submission(
                outcome="SUBMISSION_UNKNOWN",
                job_id=str(study_id),
                reason="unknown",
                observation=JobObservation(
                    availability="UNAVAILABLE",
                    job_id=str(study_id),
                    queue_name="indusopt",
                    error_code="RQ_RECONCILIATION_UNAVAILABLE",
                ),
            )

        async def fail_if_inline(*args: object, **kwargs: object) -> None:
            raise AssertionError("ambiguous enqueue outcome must not execute inline")

        monkeypatch.setattr(optimization_service, "background_optimization_enabled", lambda: True)
        monkeypatch.setattr(optimization_service, "submit_optimization", submit)
        monkeypatch.setattr(optimization_service, "execute_study", fail_if_inline)
        version_id = generate(client, seed=302)

        started = client.post(
            "/api/v1/optimization/optuna/start",
            json={
                "version_id": version_id,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "max_trials": 3,
            },
        )

        assert started.status_code == 202, started.text
        payload = started.json()["data"]
        snapshot = asyncio.run(
            _optimization_snapshot(
                tmp_path / "optimize.db", study_id=UUID(payload["study_id"])
            )
        )
        assert payload["task"]["id"] == payload["study_id"]
        assert payload["task"]["status"] == "queued"
        assert payload["task"]["error"]["code"] == "RQ_RECONCILIATION_UNAVAILABLE"
        assert snapshot["study_status"] == "queued"
        assert snapshot["job"]["submission_state"] == "SUBMISSION_UNKNOWN"  # type: ignore[index]

    def test_historical_study_uses_stable_legacy_projection_without_backfill(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        study_id = asyncio.run(_insert_legacy_optimization_study(tmp_path / "optimize.db"))
        before = asyncio.run(_optimization_snapshot(tmp_path / "optimize.db", study_id=study_id))

        first = client.get(f"/api/v1/optimization/optuna/{study_id}/status").json()["data"]
        second = client.get(f"/api/v1/optimization/optuna/{study_id}/status").json()["data"]
        after = asyncio.run(_optimization_snapshot(tmp_path / "optimize.db", study_id=study_id))

        assert first["task"]["id"] == str(study_id)
        assert second["task"]["id"] == str(study_id)
        assert first["job"]["availability"] == "LEGACY"
        assert first["terminal_reason"] is None
        assert first["stop_reason"] is None
        assert before == after


class TestRqFailureCallbackAndEvidence:
    @staticmethod
    def _callback_job(study_id: UUID, *, valid: bool = True) -> object:
        from types import SimpleNamespace

        class FakeJob:
            id = str(study_id)
            meta = {
                "study_id": str(study_id) if valid else str(uuid4()),
                "job_kind": "optimization",
            }
            func_name = "app.worker.run_optimization_job"
            origin = "indusopt"
            timeout = 3600
            _status = SimpleNamespace(value="started")

            def save_meta(self) -> None:
                return None

        return FakeJob()

    @pytest.mark.parametrize(
        ("exception_type", "expected_kind", "expected_error"),
        [
            ("timeout", "job_timeout", "RQ_JOB_TIMEOUT"),
            ("abandoned", "abandoned_execution", "RQ_ABANDONED_EXECUTION"),
            ("ordinary", "ordinary_exception", "RQ_JOB_EXECUTION_FAILED"),
        ],
    )
    def test_callback_classifies_typed_job_body_exception(
        self, exception_type: str, expected_kind: str, expected_error: str
    ) -> None:
        from app.services.job_queue import callback_terminal_evidence
        from rq.exceptions import AbandonedJobError
        from rq.timeouts import JobTimeoutException

        study_id = uuid4()
        exc_type = {
            "timeout": JobTimeoutException,
            "abandoned": AbandonedJobError,
            "ordinary": RuntimeError,
        }[exception_type]

        evidence = callback_terminal_evidence(
            self._callback_job(study_id),
            exc_type=exc_type,
        )

        assert evidence is not None
        assert evidence.kind == expected_kind
        assert evidence.error_code == expected_error
        assert evidence.rq_job_id == str(study_id)

    def test_callback_rejects_identity_mismatch(self) -> None:
        from app.services.job_queue import callback_terminal_evidence

        assert (
            callback_terminal_evidence(
                self._callback_job(uuid4(), valid=False),
                exc_type=RuntimeError,
            )
            is None
        )

    def test_worker_callback_identity_mismatch_never_reaches_database(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app import worker

        async def fail_if_called(*args: object, **kwargs: object) -> None:
            raise AssertionError("identity mismatch must not reach persistence")

        monkeypatch.setattr(worker, "_persist_failure_evidence", fail_if_called)

        worker.handle_optimization_job_failure(
            self._callback_job(uuid4(), valid=False),
            object(),
            RuntimeError,
            RuntimeError("original job failure"),
            None,
        )

    @pytest.mark.parametrize("failure_target", ["database", "job_meta"])
    def test_failure_callback_never_reraises_its_own_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
        failure_target: str,
    ) -> None:
        from app import worker
        from app.services import job_queue

        study_id = uuid4()
        job = self._callback_job(study_id)
        persisted: list[str] = []

        async def persist(*args: object, **kwargs: object) -> None:
            if failure_target == "database":
                raise RuntimeError("database unavailable")
            persisted.append("database")

        def persist_meta(*args: object, **kwargs: object) -> None:
            if failure_target == "job_meta":
                raise RuntimeError("redis unavailable")
            persisted.append("job_meta")

        monkeypatch.setattr(worker, "_persist_failure_evidence", persist)
        monkeypatch.setattr(
            job_queue,
            "persist_job_terminal_evidence_best_effort",
            persist_meta,
        )

        worker.handle_optimization_job_failure(
            job,
            object(),
            RuntimeError,
            RuntimeError("original job failure"),
            None,
        )

        assert persisted == (["job_meta"] if failure_target == "database" else ["database"])

    @pytest.mark.parametrize(
        ("exc_string", "expected_kind"),
        [
            (
                "Traceback (most recent call last):\n"
                "rq.timeouts.JobTimeoutException: Task exceeded maximum timeout value "
                "(3600 seconds)",
                "job_timeout",
            ),
            (
                "Work-horse terminated unexpectedly; waitpid returned 9 (signal 9); ",
                "work_horse_terminated",
            ),
            (
                "Moved to FailedJobRegistry, due to AbandonedJobError, at "
                "2026-09-15 12:00:00+00:00",
                "abandoned_execution",
            ),
            ("builtins.RuntimeError: ordinary failure", None),
        ],
    )
    def test_failed_registry_uses_only_strict_persisted_failure_evidence(
        self,
        monkeypatch: pytest.MonkeyPatch,
        exc_string: str,
        expected_kind: str | None,
    ) -> None:
        from types import SimpleNamespace

        from app.services.job_queue import _failed_registry_evidence
        from rq import registry

        class FailedRegistry:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            def __contains__(self, job_id: str) -> bool:
                return True

        job = SimpleNamespace(
            id=str(uuid4()),
            connection=object(),
            timeout=3600,
            latest_result=lambda timeout=0: SimpleNamespace(exc_string=exc_string),
        )
        monkeypatch.setattr(registry, "FailedJobRegistry", FailedRegistry)

        evidence = _failed_registry_evidence(
            job,
            queue_name="indusopt",
            expected_timeout_seconds=3600,
            source="failed_registry",
        )

        assert (evidence.kind if evidence is not None else None) == expected_kind

    def test_started_registry_cleanup_refetches_abandoned_job_evidence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from types import SimpleNamespace

        from app.services import job_queue
        from redis import Redis
        from rq import registry
        from rq.job import Job

        study_id = uuid4()
        state = {"status": "started", "cleaned": False}

        class Connection:
            def ping(self) -> bool:
                return True

        connection = Connection()

        class FakeJob:
            id = str(study_id)
            meta = {"study_id": str(study_id), "job_kind": "optimization"}
            func_name = "app.worker.run_optimization_job"
            origin = "indusopt"
            timeout = 3600
            created_at = None
            enqueued_at = None
            started_at = None
            ended_at = None

            def __init__(self) -> None:
                self.connection = connection

            def get_status(self, *, refresh: bool = True) -> object:
                return SimpleNamespace(value=state["status"])

            def latest_result(self, timeout: int = 0) -> object:
                return SimpleNamespace(
                    exc_string=(
                        "Moved to FailedJobRegistry, due to AbandonedJobError, at "
                        "2026-09-15 12:00:00+00:00"
                    )
                )

        job = FakeJob()

        class StartedRegistry:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            def cleanup(self) -> None:
                state["status"] = "failed"
                state["cleaned"] = True

        class FailedRegistry:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            def __contains__(self, job_id: str) -> bool:
                return state["cleaned"] and job_id == str(study_id)

        monkeypatch.setattr(Redis, "from_url", lambda *args, **kwargs: connection)
        monkeypatch.setattr(Job, "fetch", classmethod(lambda cls, *args, **kwargs: job))
        monkeypatch.setattr(registry, "StartedJobRegistry", StartedRegistry)
        monkeypatch.setattr(registry, "FailedJobRegistry", FailedRegistry)

        observation = job_queue.reconcile_optimization_job(
            study_id=study_id,
            job_id=str(study_id),
            queue_name="indusopt",
            expected_timeout_seconds=3600,
        )

        assert state["cleaned"] is True
        assert observation.raw_status == "failed"
        assert observation.terminal_evidence is not None
        assert observation.terminal_evidence.kind == "abandoned_execution"
        assert observation.terminal_evidence.source == "started_registry_cleanup"


class TestRqFailureReconciliation:
    @staticmethod
    def _evidence(
        study_id: UUID,
        *,
        kind: str,
        source: str = "failure_callback",
    ) -> object:
        from datetime import UTC, datetime

        from app.services.job_queue import RqTerminalEvidence

        facts = {
            "job_timeout": (
                "HIGH",
                "rq.timeouts.JobTimeoutException",
                "RQ_JOB_TIMEOUT",
            ),
            "work_horse_terminated": (
                "HIGH",
                "rq.worker.WorkHorseTerminated",
                "RQ_WORK_HORSE_TERMINATED",
            ),
            "abandoned_execution": (
                "HIGH",
                "rq.exceptions.AbandonedJobError",
                "RQ_ABANDONED_EXECUTION",
            ),
            "ordinary_exception": (
                "GENERIC",
                "builtins.RuntimeError",
                "RQ_JOB_EXECUTION_FAILED",
            ),
        }
        confidence, exception_type, error_code = facts[kind]
        return RqTerminalEvidence(
            source=source,
            kind=kind,
            confidence=confidence,
            rq_job_id=str(study_id),
            rq_status="failed" if source != "failure_callback" else "started",
            exception_type=exception_type,
            observed_at=datetime.now(UTC),
            error_code=error_code,
            job_timeout_seconds=3600,
        )

    @pytest.mark.parametrize("initial_status", ["queued", "running"])
    @pytest.mark.parametrize(
        ("kind", "source", "expected_code", "expected_error"),
        [
            ("ordinary_exception", "failure_callback", "FAILED", "RQ_JOB_EXECUTION_FAILED"),
            ("job_timeout", "failure_callback", "RQ_TIMEOUT", "RQ_JOB_TIMEOUT"),
            (
                "work_horse_terminated",
                "failed_registry",
                "WORKER_CRASH",
                "RQ_WORK_HORSE_TERMINATED",
            ),
            (
                "abandoned_execution",
                "started_registry_cleanup",
                "WORKER_CRASH",
                "RQ_ABANDONED_EXECUTION",
            ),
        ],
    )
    def test_nonterminal_study_accepts_only_typed_rq_terminal_evidence(
        self,
        tmp_path: Path,
        initial_status: str,
        kind: str,
        source: str,
        expected_code: str,
        expected_error: str,
    ) -> None:
        database_path = tmp_path / f"{initial_status}-{kind}.db"
        study_id = asyncio.run(
            _insert_rq_optimization_study(database_path, status=initial_status)
        )

        changed = asyncio.run(
            _persist_rq_evidence(
                database_path,
                study_id=study_id,
                evidence=self._evidence(study_id, kind=kind, source=source),
            )
        )
        snapshot = asyncio.run(_optimization_snapshot(database_path, study_id=study_id))

        assert changed is True
        terminal = snapshot["terminal_reason"]
        assert terminal["policy_version"] == "optimization_terminal_reason_v2"  # type: ignore[index]
        assert terminal["code"] == expected_code  # type: ignore[index]
        assert terminal["phase"] == "rq_execution"  # type: ignore[index]
        assert terminal["error_code"] == expected_error  # type: ignore[index]
        assert snapshot["job"]["terminal_evidence"]["kind"] == kind  # type: ignore[index]

    @pytest.mark.parametrize(
        ("kind", "source", "expected_code"),
        [
            ("job_timeout", "failure_callback", "RQ_TIMEOUT"),
            ("work_horse_terminated", "failed_registry", "WORKER_CRASH"),
        ],
    )
    def test_generic_rq_failure_can_be_refined_with_history(
        self, tmp_path: Path, kind: str, source: str, expected_code: str
    ) -> None:
        from datetime import UTC, datetime

        database_path = tmp_path / f"refine-{kind}.db"
        generic = {
            "policy_version": "optimization_terminal_reason_v2",
            "code": "FAILED",
            "category": "SYSTEM_FAILURE",
            "phase": "rq_execution",
            "error_code": "RQ_JOB_EXECUTION_FAILED",
            "recorded_at": datetime.now(UTC).isoformat(),
        }
        study_id = asyncio.run(
            _insert_rq_optimization_study(
                database_path,
                status="failed",
                terminal_reason=generic,
            )
        )

        changed = asyncio.run(
            _persist_rq_evidence(
                database_path,
                study_id=study_id,
                evidence=self._evidence(study_id, kind=kind, source=source),
            )
        )
        snapshot = asyncio.run(_optimization_snapshot(database_path, study_id=study_id))

        assert changed is True
        assert snapshot["terminal_reason"]["code"] == expected_code  # type: ignore[index]
        assert snapshot["terminal_reason_history"] == [generic]

    def test_application_failed_cannot_be_reclassified_as_worker_crash(
        self, tmp_path: Path
    ) -> None:
        from datetime import UTC, datetime

        database_path = tmp_path / "application-failed.db"
        application_failure = {
            "policy_version": "optimization_terminal_reason_v2",
            "code": "FAILED",
            "category": "SYSTEM_FAILURE",
            "phase": "search",
            "error_code": "STUDY_EXECUTION_FAILED",
            "recorded_at": datetime.now(UTC).isoformat(),
        }
        study_id = asyncio.run(
            _insert_rq_optimization_study(
                database_path,
                status="failed",
                terminal_reason=application_failure,
            )
        )

        changed = asyncio.run(
            _persist_rq_evidence(
                database_path,
                study_id=study_id,
                evidence=self._evidence(
                    study_id,
                    kind="work_horse_terminated",
                    source="failed_registry",
                ),
            )
        )
        snapshot = asyncio.run(_optimization_snapshot(database_path, study_id=study_id))

        assert changed is False
        assert snapshot["terminal_reason"] == application_failure
        assert snapshot["terminal_reason_history"] is None

    @pytest.mark.parametrize(
        "immutable_code",
        ["COMPLETED", "NO_VALID_CANDIDATE", "RQ_TIMEOUT", "WORKER_CRASH"],
    )
    def test_immutable_terminal_reason_cannot_be_overwritten(
        self, tmp_path: Path, immutable_code: str
    ) -> None:
        from datetime import UTC, datetime

        database_path = tmp_path / f"immutable-{immutable_code}.db"
        existing = {
            "policy_version": "optimization_terminal_reason_v2",
            "code": immutable_code,
            "category": (
                "SUCCESS"
                if immutable_code == "COMPLETED"
                else "BUSINESS_FAILURE"
                if immutable_code == "NO_VALID_CANDIDATE"
                else "INFRASTRUCTURE_FAILURE"
            ),
            "phase": "search" if immutable_code == "NO_VALID_CANDIDATE" else "rq_execution",
            "error_code": None,
            "recorded_at": datetime.now(UTC).isoformat(),
        }
        study_id = asyncio.run(
            _insert_rq_optimization_study(
                database_path,
                status="succeeded" if immutable_code == "COMPLETED" else "failed",
                terminal_reason=existing,
            )
        )

        changed = asyncio.run(
            _persist_rq_evidence(
                database_path,
                study_id=study_id,
                evidence=self._evidence(study_id, kind="job_timeout"),
            )
        )
        snapshot = asyncio.run(_optimization_snapshot(database_path, study_id=study_id))

        assert changed is False
        assert snapshot["terminal_reason"] == existing

    def test_same_terminal_evidence_is_idempotent(self, tmp_path: Path) -> None:
        database_path = tmp_path / "idempotent.db"
        study_id = asyncio.run(_insert_rq_optimization_study(database_path))
        evidence = self._evidence(study_id, kind="job_timeout")

        first = asyncio.run(
            _persist_rq_evidence(database_path, study_id=study_id, evidence=evidence)
        )
        second = asyncio.run(
            _persist_rq_evidence(database_path, study_id=study_id, evidence=evidence)
        )

        assert first is True
        assert second is False
        snapshot = asyncio.run(_optimization_snapshot(database_path, study_id=study_id))
        assert snapshot["terminal_reason_history"] is None

    @pytest.mark.parametrize(
        ("kind", "source", "expected_code"),
        [
            ("job_timeout", "failed_registry", "RQ_TIMEOUT"),
            ("work_horse_terminated", "failed_registry", "WORKER_CRASH"),
        ],
    )
    def test_status_get_lazily_persists_strict_rq_evidence(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        kind: str,
        source: str,
        expected_code: str,
    ) -> None:
        from datetime import UTC, datetime

        from app.services import optimization_service
        from app.services.job_queue import JobObservation

        database_path = tmp_path / "optimize.db"
        study_id = asyncio.run(_insert_rq_optimization_study(database_path))
        evidence = self._evidence(
            study_id,
            kind=kind,
            source=source,
        )

        def reconcile(**kwargs: object) -> JobObservation:
            assert kwargs["study_id"] == study_id
            assert kwargs["expected_timeout_seconds"] == 3600
            return JobObservation(
                availability="AVAILABLE",
                job_id=str(study_id),
                queue_name="indusopt",
                raw_status="failed",
                ended_at=datetime.now(UTC),
                terminal_evidence=evidence,  # type: ignore[arg-type]
            )

        monkeypatch.setattr(optimization_service, "reconcile_optimization_job", reconcile)

        response = client.get(f"/api/v1/optimization/optuna/{study_id}/status")

        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["task"]["status"] == "failed"
        assert data["study_status"] == "failed"
        assert data["terminal_reason"]["code"] == expected_code
        assert data["statistics"]["job"]["terminal_evidence"]["kind"] == kind

    @pytest.mark.parametrize(
        ("availability", "error_code"),
        [
            ("UNAVAILABLE", "RQ_RECONCILIATION_UNAVAILABLE"),
            ("NOT_FOUND", "RQ_JOB_NOT_FOUND"),
        ],
    )
    def test_status_does_not_infer_terminal_from_unavailable_or_missing_job(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        availability: str,
        error_code: str,
    ) -> None:
        from app.services import optimization_service
        from app.services.job_queue import JobObservation

        database_path = tmp_path / "optimize.db"
        study_id = asyncio.run(_insert_rq_optimization_study(database_path))

        monkeypatch.setattr(
            optimization_service,
            "reconcile_optimization_job",
            lambda **kwargs: JobObservation(
                availability=availability,
                job_id=str(study_id),
                queue_name="indusopt",
                error_code=error_code,
            ),
        )

        response = client.get(f"/api/v1/optimization/optuna/{study_id}/status")
        snapshot = asyncio.run(_optimization_snapshot(database_path, study_id=study_id))

        assert response.status_code == 200
        assert response.json()["data"]["terminal_reason"] is None
        assert snapshot["study_status"] == "running"
        assert snapshot["terminal_reason"] is None


class TestStudyReservation:
    def test_status_answers_before_the_search_finishes(self, client: TestClient) -> None:
        """The whole point of the background path: a pollable id, immediately.

        Driven here through the service rather than the queue so the invariant is checked
        without requiring Redis — the row must exist and carry the trial target the moment
        the study is reserved.
        """

        version_id = generate(client, seed=31)
        started = client.post(
            "/api/v1/optimization/optuna/start",
            json={
                "version_id": version_id,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "max_trials": 2,
            },
        )
        study_id = started.json()["data"]["study_id"]
        status = client.get(f"/api/v1/optimization/optuna/{study_id}/status")
        assert status.status_code == 200
        assert status.json()["data"]["statistics"]["target_trials"] == 2

    def test_rerunning_the_same_study_id_replaces_rather_than_duplicates(
        self, client: TestClient
    ) -> None:
        """RQ retries after a worker crash must not leave two records for one request."""

        version_id = generate(client, seed=33)
        started = client.post(
            "/api/v1/optimization/optuna/start",
            json={
                "version_id": version_id,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "max_trials": 3,
            },
        )
        study_id = started.json()["data"]["study_id"]
        first = client.get(f"/api/v1/optimization/optuna/{study_id}/status").json()["data"]
        assert len(first["trials"]) == 3
