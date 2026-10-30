"""Deterministic, validation-only diagnosis for optimization candidates."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

DIAGNOSIS_POLICY_VERSION = "validation_diagnosis_v1"
CONVERGENCE_POLICY_VERSION = "optimization_convergence_v1"
CONVERGENCE_MODE = "observed_only"
STOP_REASON_POLICY_VERSION = "optimization_stop_reason_v1"
MIN_MEANINGFUL_IMPROVEMENT = 0.001
CONVERGENCE_PATIENCE = 16
CONVERGENCE_MIN_VALID_TRIALS = 17


class DiagnosisCode(StrEnum):
    UNSTABLE_MODEL = "UNSTABLE_MODEL"
    FREE_RUN_UNDEFINED = "FREE_RUN_UNDEFINED"
    INSUFFICIENT_EXCITATION = "INSUFFICIENT_EXCITATION"


class CandidateDecision(StrEnum):
    CANDIDATE_VALID_NEW_BEST = "CANDIDATE_VALID_NEW_BEST"
    CANDIDATE_VALID_NOT_BEST = "CANDIDATE_VALID_NOT_BEST"


class ConvergenceStatus(StrEnum):
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NOT_CONVERGED = "NOT_CONVERGED"
    CONVERGED = "CONVERGED"


class NormalStopReasonCode(StrEnum):
    TRIAL_BUDGET_EXHAUSTED = "TRIAL_BUDGET_EXHAUSTED"
    TIMEOUT_REACHED = "TIMEOUT_REACHED"


class NormalStopReasonOutcome(StrEnum):
    WINNER_SELECTED = "WINNER_SELECTED"
    NO_VALID_CANDIDATE = "NO_VALID_CANDIDATE"


@dataclass(frozen=True)
class BestSoFarState:
    best_value: float | None = None
    winner_trial_number: int | None = None


@dataclass(frozen=True)
class TrialBookkeepingResult:
    previous_best: float | None
    absolute_improvement: float | None
    best_so_far: float | None
    decision: CandidateDecision | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "previous_best": self.previous_best,
            "absolute_improvement": self.absolute_improvement,
            "best_so_far": self.best_so_far,
            "decision": self.decision.value if self.decision is not None else None,
        }


@dataclass(frozen=True)
class ObservedConvergenceResult:
    policy_version: str
    mode: str
    status: ConvergenceStatus
    no_improvement_streak: int
    patience: int
    min_meaningful_improvement: float
    min_valid_trials: int
    valid_trial_count: int
    last_meaningful_improvement_trial: int | None
    best_trial_number: int | None
    observed_at_trial_count: int

    def to_payload(self) -> dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "mode": self.mode,
            "status": self.status.value,
            "no_improvement_streak": self.no_improvement_streak,
            "patience": self.patience,
            "min_meaningful_improvement": self.min_meaningful_improvement,
            "min_valid_trials": self.min_valid_trials,
            "valid_trial_count": self.valid_trial_count,
            "last_meaningful_improvement_trial": (
                self.last_meaningful_improvement_trial
            ),
            "best_trial_number": self.best_trial_number,
            "observed_at_trial_count": self.observed_at_trial_count,
        }


@dataclass(frozen=True)
class NormalStopReasonResult:
    policy_version: str
    code: NormalStopReasonCode
    category: str
    outcome: NormalStopReasonOutcome
    observed_trial_count: int
    target_trial_count: int
    timeout_seconds: int | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "code": self.code.value,
            "category": self.category,
            "outcome": self.outcome.value,
            "observed_trial_count": self.observed_trial_count,
            "target_trial_count": self.target_trial_count,
            "timeout_seconds": self.timeout_seconds,
        }


def determine_normal_stop_reason(
    *,
    observed_trial_count: int,
    target_trial_count: int,
    timeout_seconds: int | None,
    best_trial_number: int | None,
) -> NormalStopReasonResult:
    """Describe only a normal ``study.optimize`` return, without inferring failures."""

    if observed_trial_count < 0:
        raise ValueError("observed_trial_count must be non-negative.")
    if target_trial_count < 1:
        raise ValueError("target_trial_count must be positive.")
    if timeout_seconds is not None and timeout_seconds < 1:
        raise ValueError("timeout_seconds must be positive when provided.")

    if observed_trial_count >= target_trial_count:
        code = NormalStopReasonCode.TRIAL_BUDGET_EXHAUSTED
    elif timeout_seconds is not None:
        code = NormalStopReasonCode.TIMEOUT_REACHED
    else:
        raise ValueError(
            "A normal study return below its trial budget requires a configured timeout."
        )

    outcome = (
        NormalStopReasonOutcome.WINNER_SELECTED
        if best_trial_number is not None
        else NormalStopReasonOutcome.NO_VALID_CANDIDATE
    )
    return NormalStopReasonResult(
        policy_version=STOP_REASON_POLICY_VERSION,
        code=code,
        category="NORMAL_LIMIT",
        outcome=outcome,
        observed_trial_count=observed_trial_count,
        target_trial_count=target_trial_count,
        timeout_seconds=timeout_seconds,
    )


def observe_convergence(
    observations: Sequence[tuple[int, Mapping[str, Any]]],
    *,
    best_trial_number: int | None,
) -> ObservedConvergenceResult:
    """Observe the completed Phase 2B history without changing search behavior."""

    valid_trial_count = 0
    no_improvement_streak = 0
    last_meaningful_best: float | None = None
    last_meaningful_improvement_trial: int | None = None

    for trial_number, bookkeeping in observations:
        decision = bookkeeping.get("decision")
        if decision is None:
            continue

        best_so_far = bookkeeping.get("best_so_far")
        if not _is_finite(best_so_far):
            raise ValueError("Business-valid bookkeeping must contain a finite best_so_far.")
        current_best = float(best_so_far)
        valid_trial_count += 1

        if last_meaningful_best is None:
            last_meaningful_best = current_best
            last_meaningful_improvement_trial = trial_number
            no_improvement_streak = 0
            continue

        meaningful_delta = current_best - last_meaningful_best
        if (
            decision == CandidateDecision.CANDIDATE_VALID_NEW_BEST
            and meaningful_delta >= MIN_MEANINGFUL_IMPROVEMENT
        ):
            last_meaningful_best = current_best
            last_meaningful_improvement_trial = trial_number
            no_improvement_streak = 0
        else:
            no_improvement_streak += 1

    if valid_trial_count < CONVERGENCE_MIN_VALID_TRIALS:
        status = ConvergenceStatus.INSUFFICIENT_EVIDENCE
    elif no_improvement_streak >= CONVERGENCE_PATIENCE:
        status = ConvergenceStatus.CONVERGED
    else:
        status = ConvergenceStatus.NOT_CONVERGED

    return ObservedConvergenceResult(
        policy_version=CONVERGENCE_POLICY_VERSION,
        mode=CONVERGENCE_MODE,
        status=status,
        no_improvement_streak=no_improvement_streak,
        patience=CONVERGENCE_PATIENCE,
        min_meaningful_improvement=MIN_MEANINGFUL_IMPROVEMENT,
        min_valid_trials=CONVERGENCE_MIN_VALID_TRIALS,
        valid_trial_count=valid_trial_count,
        last_meaningful_improvement_trial=last_meaningful_improvement_trial,
        best_trial_number=best_trial_number,
        observed_at_trial_count=len(observations),
    )


def advance_trial_bookkeeping(
    state: BestSoFarState,
    *,
    trial_number: int,
    trial_state: str,
    objective_score: float | None,
) -> tuple[BestSoFarState, TrialBookkeepingResult]:
    """Record objective progress without applying Phase 2C significance or stop policy."""

    previous_best = state.best_value
    if trial_state != "complete" or not _is_finite(objective_score):
        return state, TrialBookkeepingResult(
            previous_best=previous_best,
            absolute_improvement=None,
            best_so_far=previous_best,
            decision=None,
        )

    current_score = float(objective_score)
    absolute_improvement = (
        None if previous_best is None else current_score - previous_best
    )
    if previous_best is None or current_score > previous_best:
        updated = BestSoFarState(
            best_value=current_score,
            winner_trial_number=trial_number,
        )
        return updated, TrialBookkeepingResult(
            previous_best=previous_best,
            absolute_improvement=absolute_improvement,
            best_so_far=current_score,
            decision=CandidateDecision.CANDIDATE_VALID_NEW_BEST,
        )

    return state, TrialBookkeepingResult(
        previous_best=previous_best,
        absolute_improvement=absolute_improvement,
        best_so_far=previous_best,
        decision=CandidateDecision.CANDIDATE_VALID_NOT_BEST,
    )


@dataclass(frozen=True)
class CandidateRejectionEvidence:
    """Compact evidence for one structure rejected by an existing hard gate."""

    code: DiagnosisCode
    structure: dict[str, Any]
    stable: bool | None = None
    max_pole_modulus: float | None = None
    free_run_metric_finite: bool | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "structure": dict(self.structure),
            "stable": self.stable,
            "max_pole_modulus": self.max_pole_modulus,
            "free_run_metric_finite": self.free_run_metric_finite,
        }


@dataclass(frozen=True)
class ValidationDiagnosis:
    policy_version: str
    codes: tuple[DiagnosisCode, ...]
    evidence: dict[str, Any]

    def to_metrics(self) -> dict[str, Any]:
        return {
            "diagnosis_policy_version": self.policy_version,
            "diagnosis_codes": [code.value for code in self.codes],
            "diagnosis_evidence": dict(self.evidence),
        }

    def to_payload(self) -> dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "codes": [code.value for code in self.codes],
            "evidence": dict(self.evidence),
        }


def rejection_from_objective(
    *,
    reason: object,
    structure: Mapping[str, Any],
    stable: bool,
    max_pole_modulus: float | None,
    free_run_fit: float | None,
) -> CandidateRejectionEvidence | None:
    """Translate only the two existing objective hard gates into stable evidence."""

    if reason == "unstable":
        code = DiagnosisCode.UNSTABLE_MODEL
    elif reason == "free_run_undefined":
        code = DiagnosisCode.FREE_RUN_UNDEFINED
    else:
        return None
    return CandidateRejectionEvidence(
        code=code,
        structure=dict(structure),
        stable=False if code is DiagnosisCode.UNSTABLE_MODEL else stable,
        max_pole_modulus=_finite_or_none(max_pole_modulus),
        free_run_metric_finite=(
            False if code is DiagnosisCode.FREE_RUN_UNDEFINED else _is_finite(free_run_fit)
        ),
    )


def rejection_provenance(
    rejections: Sequence[CandidateRejectionEvidence],
) -> dict[str, Any] | None:
    """Aggregate structure rejections without storing repetitive per-fit payloads."""

    if not rejections:
        return None
    counts = Counter(item.code.value for item in rejections)
    examples: dict[str, dict[str, Any]] = {}
    for item in rejections:
        examples.setdefault(item.code.value, item.to_payload())
    return {
        "rejected_structure_count": len(rejections),
        "reason_counts": dict(counts),
        "examples": list(examples.values()),
    }


def diagnose_validation_candidate(
    *,
    validation_feedback: Mapping[str, Any] | None,
    selection_provenance: Mapping[str, Any] | None,
    objective_components: Mapping[str, Any] | None,
    candidate_rejections: Sequence[CandidateRejectionEvidence] = (),
) -> ValidationDiagnosis:
    """Return stable codes from validation evidence; Test data is not an accepted input."""

    codes: set[DiagnosisCode] = {item.code for item in candidate_rejections}
    evidence: dict[str, Any] = {}
    summary = _mapping(validation_feedback, "summary")
    free_run = _mapping(validation_feedback, "free_run")

    stable = summary.get("stable")
    stability_gate = (objective_components or {}).get("stability_gate")
    if stable is False or stability_gate is False or DiagnosisCode.UNSTABLE_MODEL in codes:
        codes.add(DiagnosisCode.UNSTABLE_MODEL)
        evidence[DiagnosisCode.UNSTABLE_MODEL.value] = {
            "stable": False,
            "max_pole_modulus": _finite_or_none(summary.get("max_pole_modulus")),
            "rejected_structure_count": sum(
                item.code is DiagnosisCode.UNSTABLE_MODEL for item in candidate_rejections
            ),
        }

    if "fit" in free_run and not _is_finite(free_run.get("fit")):
        codes.add(DiagnosisCode.FREE_RUN_UNDEFINED)
    if DiagnosisCode.FREE_RUN_UNDEFINED in codes:
        evidence[DiagnosisCode.FREE_RUN_UNDEFINED.value] = {
            "free_run_metric_finite": False,
            "rejected_structure_count": sum(
                item.code is DiagnosisCode.FREE_RUN_UNDEFINED for item in candidate_rejections
            ),
        }

    shortfall = summary.get("excitation_shortfall")
    excitation_satisfied = (selection_provenance or {}).get("excitation_satisfied")
    if excitation_satisfied is False or (
        isinstance(shortfall, Mapping) and bool(shortfall)
    ):
        codes.add(DiagnosisCode.INSUFFICIENT_EXCITATION)
        evidence[DiagnosisCode.INSUFFICIENT_EXCITATION.value] = {
            "excitation_satisfied": excitation_satisfied,
            "excitation_shortfall": dict(shortfall) if isinstance(shortfall, Mapping) else {},
            "persistent_excitation_order": dict(
                (selection_provenance or {}).get("persistent_excitation_order", {})
            ),
            "required_excitation_order": dict(
                (selection_provenance or {}).get("required_excitation_order", {})
            ),
        }

    ordered = tuple(code for code in DiagnosisCode if code in codes)
    return ValidationDiagnosis(
        policy_version=DIAGNOSIS_POLICY_VERSION,
        codes=ordered,
        evidence=evidence,
    )


def _mapping(parent: Mapping[str, Any] | None, key: str) -> Mapping[str, Any]:
    value = (parent or {}).get(key)
    return value if isinstance(value, Mapping) else {}


def _is_finite(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _finite_or_none(value: object) -> float | None:
    return float(value) if _is_finite(value) else None
