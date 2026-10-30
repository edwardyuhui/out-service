"""Read-only dashboard projections backed only by completed optimisation records."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset import Dataset
from app.models.optimization import OptimizationStudy, OptimizationTrialRecord
from app.schemas.dashboard import DashboardLeaderboardData, LeaderboardEntry
from app.services.evaluation_policy import generalization_risk


async def get_dashboard_leaderboard(session: AsyncSession) -> DashboardLeaderboardData:
    """Return completed studies ranked by the common validation free-run FIT metric."""

    studies = list(
        (
            await session.scalars(
                select(OptimizationStudy)
                .where(
                    OptimizationStudy.status == "succeeded",
                    OptimizationStudy.dataset_id.is_not(None),
                    OptimizationStudy.best_trial_number.is_not(None),
                )
                .order_by(OptimizationStudy.finished_at.desc())
            )
        ).all()
    )
    entries: list[LeaderboardEntry] = []
    for study in studies:
        dataset = await session.get(Dataset, study.dataset_id)
        if dataset is None:
            continue
        trials = list(
            (
                await session.scalars(
                    select(OptimizationTrialRecord)
                    .where(
                        OptimizationTrialRecord.study_id == study.id,
                        OptimizationTrialRecord.state == "complete",
                    )
                    .order_by(OptimizationTrialRecord.trial_number)
                )
            ).all()
        )
        if not trials:
            continue
        best = next(
            (trial for trial in trials if trial.trial_number == study.best_trial_number),
            None,
        )
        optimized = _validation_fit(best.metrics if best is not None else {})
        if optimized is None:
            continue
        baseline = _evaluation_metric(study.statistics, "baseline", "validation_free_run_fit")
        test_fit = _evaluation_metric(study.statistics, "final_test", "test_free_run_fit")
        test_one_step_fit = _evaluation_metric(study.statistics, "final_test", "test_one_step_fit")
        test_one_step_r2 = _evaluation_metric(study.statistics, "final_test", "test_one_step_r2")
        test_free_run_r2 = _evaluation_metric(study.statistics, "final_test", "test_free_run_r2")
        gap = _evaluation_metric(study.statistics, "final_test", "generalization_gap")
        baseline_available = baseline is not None
        test_available = test_fit is not None and gap is not None
        risk, risk_message = generalization_risk(gap if test_available else None)
        params = dict(study.best_params or {})
        entries.append(
            LeaderboardEntry(
                dataset_id=dataset.id,
                dataset_name=dataset.name,
                version_id=study.version_id,
                study_id=study.id,
                status=study.status,
                baseline_validation_fit=baseline,
                optimized_validation_fit=optimized,
                optimized_test_fit=test_fit,
                optimized_test_one_step_fit=test_one_step_fit,
                optimized_test_one_step_r2=test_one_step_r2,
                optimized_test_free_run_r2=test_free_run_r2,
                improvement=optimized - baseline if baseline is not None else None,
                generalization_gap=gap,
                baseline_available=baseline_available,
                test_available=test_available,
                generalization_risk=risk,
                risk_message=risk_message,
                contribution_summary=_summary(params),
            )
        )
    entries.sort(key=lambda item: item.optimized_validation_fit or float("-inf"), reverse=True)
    return DashboardLeaderboardData(items=entries)


def _validation_fit(metrics: dict[str, object]) -> float | None:
    value = metrics.get("val_free_run_fit")
    return float(value) if isinstance(value, int | float) else None


def _evaluation_metric(
    statistics: dict[str, object], kind: str, key: str
) -> float | None:
    evaluations = statistics.get("evaluations")
    if not isinstance(evaluations, dict):
        return None
    evaluation = evaluations.get(kind)
    if not isinstance(evaluation, dict):
        return None
    value = evaluation.get(key)
    return float(value) if isinstance(value, int | float) else None


def _summary(params: dict[str, object]) -> str | None:
    selected = [
        f"窗口={params['window_size']}" for _ in [None] if "window_size" in params
    ] + [
        f"预算={params['max_segments']}" for _ in [None] if "max_segments" in params
    ] + [f"nk={params['nk']}" for _ in [None] if "nk" in params]
    return "；".join(selected) or None
