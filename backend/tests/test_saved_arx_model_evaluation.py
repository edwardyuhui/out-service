"""Saved ARX model Test-evaluation contracts."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import numpy as np
import pytest
from app.core.config import Settings
from app.core.db import get_session
from app.main import create_app
from app.models import Base, Dataset, DatasetVersion, ProcessingRun
from app.services import modeling_service
from app.services.modeling_service import ModelingDomainError
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@dataclass(frozen=True)
class EvaluationHarness:
    client: TestClient
    session_factory: async_sessionmaker[AsyncSession]
    artifact_root: Path


@pytest.fixture
def evaluation_harness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[EvaluationHarness]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'saved-model.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def session_override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    asyncio.run(prepare())
    monkeypatch.setattr("app.api.routes.get_settings", lambda: Settings(artifact_root=tmp_path))
    app = create_app()
    app.dependency_overrides[get_session] = session_override
    with TestClient(app) as client:
        yield EvaluationHarness(
            client=client,
            session_factory=session_factory,
            artifact_root=tmp_path,
        )
    asyncio.run(engine.dispose())


def _fit_saved_model(harness: EvaluationHarness, *, family: str = "ARX") -> tuple[UUID, UUID, UUID, dict[str, object]]:
    generated = harness.client.post(
        "/api/v1/simulation/generate",
        json={"scenario": "S2", "n_steps": 1_200, "seed": 37, "input_count": 2},
    )
    assert generated.status_code == 201, generated.text
    data = generated.json()["data"]
    dataset_id = UUID(data["dataset_id"])
    lagged = harness.client.post(
        "/api/v1/preprocessing/delay/apply",
        json={
            "version_id": data["version_id"],
            "lag_map": {"u1": 3, "u2": 8},
            "user_confirmed": True,
            "recommendation_source": "manual",
        },
    )
    assert lagged.status_code == 201, lagged.text
    version_id = UUID(lagged.json()["data"]["result_version_id"])
    fitted = harness.client.post(
        "/api/v1/modeling/arx/fit",
        json={
            "version_id": str(version_id),
            "input_columns": ["u1", "u2"],
            "output_column": "y",
            "na": 2,
            "nb": [2, 2],
            "delays": [0, 0],
            "model_type": family,
            **({"estimator": "ridge", "ridge_alpha": .001} if family == "OE" else {}),
        },
    )
    assert fitted.status_code == 200, fitted.text
    data = fitted.json()["data"]
    model_id = UUID(data["model_id"])
    artifact = json.loads((harness.artifact_root / data["artifact_uri"]).read_text(encoding="utf-8"))
    return dataset_id, version_id, model_id, artifact


def test_oe_api_artifact_replays_without_fitting(evaluation_harness, monkeypatch):
    _, version_id, model_id, artifact = _fit_saved_model(evaluation_harness, family="OE")
    assert artifact["configuration"]["simulation_horizons"] == [1, 16, 64, 0]
    def forbidden(*args, **kwargs):
        raise AssertionError("Saved OE Test evaluation must not fit")
    monkeypatch.setattr(modeling_service, "fit_multihorizon", forbidden)
    result = asyncio.run(_evaluate(evaluation_harness, model_id=model_id, expected_source_version_id=version_id))
    assert result.model_structure.model_type == "OE"
    assert result.model_health.stable
    assert result.test.free_run.rmse is not None


async def _evaluate(
    harness: EvaluationHarness,
    *,
    model_id: UUID,
    expected_source_version_id: UUID | None = None,
):
    async with harness.session_factory() as session:
        return await modeling_service.evaluate_saved_arx_model(
            session,
            model_id=model_id,
            artifact_root=harness.artifact_root,
            expected_source_version_id=expected_source_version_id,
        )


def test_load_saved_model_reconstructs_canonical_structure_and_theta(
    evaluation_harness: EvaluationHarness,
) -> None:
    _, version_id, model_id, artifact = _fit_saved_model(evaluation_harness)

    saved = modeling_service.load_saved_arx_model(
        model_id=model_id,
        artifact_root=evaluation_harness.artifact_root,
    )

    assert saved.source_version_id == version_id
    configuration = artifact["configuration"]
    assert isinstance(configuration, dict)
    assert saved.structure.na == configuration["na"]
    assert saved.structure.nb == modeling_service._orders(
        configuration["nb"], configuration["input_columns"], "nb", 1
    )
    assert saved.structure.nk == modeling_service._orders(
        configuration["delays"], configuration["input_columns"], "delays", 0
    )
    expected = np.asarray(
        [artifact["coefficients"][name] for name in saved.structure.feature_names()], dtype=float
    )
    assert saved.theta == pytest.approx(expected)


def test_evaluate_saved_model_uses_fixed_theta_and_persists_test_metrics(
    evaluation_harness: EvaluationHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_id, version_id, model_id, artifact = _fit_saved_model(evaluation_harness)
    saved = modeling_service.load_saved_arx_model(
        model_id=model_id,
        artifact_root=evaluation_harness.artifact_root,
    )

    async def load_source_series():  # type: ignore[no-untyped-def]
        async with evaluation_harness.session_factory() as session:
            return await modeling_service.load_version_series(
                session,
                version_id=version_id,
                dataset_id=dataset_id,
                artifact_root=evaluation_harness.artifact_root,
            )

    source_series = asyncio.run(load_source_series())
    n_source_samples = source_series.n_samples

    async def before() -> tuple[int, UUID | None]:
        async with evaluation_harness.session_factory() as session:
            version_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(DatasetVersion)
                    .where(DatasetVersion.dataset_id == dataset_id)
                )
                or 0
            )
            dataset = await session.get(Dataset, dataset_id)
            assert dataset is not None
            return version_count, dataset.active_version_id

    before_versions, before_active = asyncio.run(before())

    def fail_if_refit(*args: object, **kwargs: object) -> None:
        raise AssertionError("saved-model evaluation must not enter an ARX fitting path")

    monkeypatch.setattr(modeling_service, "fit_arx_core", fail_if_refit)
    monkeypatch.setattr(modeling_service, "fit_arx_on_version", fail_if_refit)
    captured_whiteness_residuals: list[np.ndarray] = []
    captured_acf_residuals: list[np.ndarray] = []
    formal_whiteness = modeling_service.residual_whiteness_ratio
    formal_acf = modeling_service._acf

    def capture_whiteness(residuals: np.ndarray, *, max_lag: int = 20) -> float:
        captured_whiteness_residuals.append(np.asarray(residuals, dtype=float).copy())
        return formal_whiteness(residuals, max_lag=max_lag)

    def capture_acf(residuals: np.ndarray):  # type: ignore[no-untyped-def]
        captured_acf_residuals.append(np.asarray(residuals, dtype=float).copy())
        return formal_acf(residuals)

    monkeypatch.setattr(modeling_service, "residual_whiteness_ratio", capture_whiteness)
    monkeypatch.setattr(modeling_service, "_acf", capture_acf)
    result = asyncio.run(
        _evaluate(
            evaluation_harness,
            model_id=model_id,
            expected_source_version_id=version_id,
        )
    )

    assert result.source_version_id == version_id
    assert result.evaluation_scope == "test"
    assert result.model_structure.model_type == "ARX"
    assert result.model_structure.input_columns == ["u1", "u2"]
    assert result.model_structure.output_column == "y"
    assert result.model_structure.na == 2
    assert result.model_structure.nb == {"u1": 2, "u2": 2}
    assert result.model_structure.delays == {"u1": 0, "u2": 0}
    assert result.model_structure.estimator == "ols"
    assert result.model_structure.ridge_alpha is None
    assert result.model_structure.parameter_count == saved.structure.parameter_count
    expected_stable, expected_modulus = modeling_service.is_stable(
        saved.theta[: saved.structure.na]
    )
    assert result.model_health.stable is expected_stable
    assert result.model_health.max_pole_modulus == pytest.approx(expected_modulus)
    assert result.test.one_step.mae is not None
    assert result.test.one_step.rmse is not None
    assert result.test.one_step.r2 is not None
    assert result.test.one_step.fit is not None
    assert result.test.one_step.nrmse is not None
    assert result.test.free_run.mae is not None
    assert result.test.free_run.rmse is not None
    assert result.test.free_run.r2 is not None
    assert result.test.free_run.fit is not None
    assert result.test.free_run.nrmse is not None
    expected_test_start = int(
        n_source_samples * (saved.payload.train_ratio + saved.payload.validation_ratio)
    ) + saved.structure.max_history
    assert result.series.sample_indices == list(range(expected_test_start, n_source_samples))
    assert result.series.timestamps == [
        source_series.timestamps[index] for index in result.series.sample_indices
    ]
    aligned_lengths = {
        len(result.series.sample_indices),
        len(result.series.y_true),
        len(result.series.one_step_prediction),
        len(result.series.free_run_prediction),
        len(result.series.one_step_residual),
        len(result.series.free_run_residual),
    }
    assert aligned_lengths == {result.test.n_samples}
    assert result.series.one_step_residual == pytest.approx(
        np.asarray(result.series.y_true) - np.asarray(result.series.one_step_prediction)
    )
    assert result.series.free_run_residual == pytest.approx(
        np.asarray(result.series.y_true) - np.asarray(result.series.free_run_prediction)
    )
    assert result.residual_diagnostics.partition == "test"
    assert result.residual_diagnostics.residual_type == "one_step"
    assert len(captured_whiteness_residuals) == 1
    assert len(captured_acf_residuals) == 1
    np.testing.assert_allclose(
        captured_whiteness_residuals[0], result.series.one_step_residual
    )
    np.testing.assert_allclose(captured_acf_residuals[0], result.series.one_step_residual)
    assert result.residual_diagnostics.residual_whiteness_ratio == pytest.approx(
        formal_whiteness(np.asarray(result.series.one_step_residual))
    )
    expected_acf = formal_acf(np.asarray(result.series.one_step_residual))
    assert result.residual_diagnostics.acf_values == pytest.approx(expected_acf.acf_values)
    assert result.residual_diagnostics.confidence_interval == pytest.approx(
        expected_acf.confidence_interval
    )
    assert artifact["configuration"]["evaluate_test"] is False

    async def after() -> None:
        async with evaluation_harness.session_factory() as session:
            run = await session.get(ProcessingRun, result.processing_run_id)
            assert run is not None
            assert run.run_type == "modeling.arx_evaluation"
            assert run.status == "succeeded"
            assert run.source_version_id == version_id
            assert run.parameters == {"model_id": str(model_id), "evaluation_scope": "test"}
            assert run.result == result.model_dump(mode="json")
            assert run.result["test"]["one_step"]["rmse"] == pytest.approx(result.test.one_step.rmse)
            version_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(DatasetVersion)
                    .where(DatasetVersion.dataset_id == dataset_id)
                )
                or 0
            )
            dataset = await session.get(Dataset, dataset_id)
            assert dataset is not None
            assert version_count == before_versions
            assert dataset.active_version_id == before_active

    asyncio.run(after())


def test_saved_model_evaluation_rejects_source_version_mismatch(
    evaluation_harness: EvaluationHarness,
) -> None:
    _, _, model_id, _ = _fit_saved_model(evaluation_harness)

    with pytest.raises(ModelingDomainError, match="来源版本") as error:
        asyncio.run(
            _evaluate(
                evaluation_harness,
                model_id=model_id,
                expected_source_version_id=uuid4(),
            )
        )

    assert error.value.code == "MODEL_SOURCE_VERSION_MISMATCH"


def test_saved_model_evaluation_persists_failed_processing_run(
    evaluation_harness: EvaluationHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, version_id, model_id, _ = _fit_saved_model(evaluation_harness)

    def fail_scores(*args: object, **kwargs: object) -> dict[str, float | None]:
        raise RuntimeError("forced evaluation failure")

    monkeypatch.setattr(modeling_service, "_scores", fail_scores)
    with pytest.raises(RuntimeError, match="forced evaluation failure"):
        asyncio.run(
            _evaluate(
                evaluation_harness,
                model_id=model_id,
                expected_source_version_id=version_id,
            )
        )

    async def check_failed_run() -> None:
        async with evaluation_harness.session_factory() as session:
            run = await session.scalar(
                select(ProcessingRun)
                .where(ProcessingRun.run_type == "modeling.arx_evaluation")
                .order_by(ProcessingRun.created_at.desc())
            )
            assert run is not None
            assert run.status == "failed"
            assert run.source_version_id == version_id
            assert run.result["model_id"] == str(model_id)
            assert run.result["error_code"] == "MODEL_EVALUATION_FAILED"

    asyncio.run(check_failed_run())
