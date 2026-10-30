"""Tests for control-relevant ARX identification and acceptance (phase 7)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
from app.core.config import Settings
from app.core.db import get_session
from app.main import create_app
from app.models import Base
from app.schemas.modeling import ArxFitRequest
from app.services.modeling_service import ModelingDomainError, _scores, fit_arx_core
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

AR = [-1.4, 0.48]
B = {"u1": [0.36, 0.12], "u2": [0.18, 0.06]}
NK = {"u1": 3, "u2": 8}


def make_inputs(n_samples: int, seed: int = 5) -> dict[str, np.ndarray]:
    generator = np.random.default_rng(seed)
    signals = {}
    for offset, column in enumerate(B):
        values = np.empty(n_samples, dtype=float)
        hold = 11 + offset * 7
        for start in range(0, n_samples, hold):
            values[start : start + hold] = generator.uniform(-1.5, 1.5)
        signals[column] = values
    return signals


def simulate(inputs: dict[str, np.ndarray], *, noise: float, seed: int = 9) -> np.ndarray:
    generator = np.random.default_rng(seed)
    n_samples = len(next(iter(inputs.values())))
    output = np.zeros(n_samples, dtype=float)
    history = max(len(AR), max(NK[c] + len(B[c]) - 1 for c in inputs))
    for index in range(history, n_samples):
        value = -sum(AR[lag - 1] * output[index - lag] for lag in range(1, len(AR) + 1))
        for column, signal in inputs.items():
            for lag, coefficient in enumerate(B[column]):
                value += coefficient * signal[index - NK[column] - lag]
        output[index] = value + (generator.normal(0.0, noise) if noise else 0.0)
    return output


def request(**overrides: object) -> ArxFitRequest:
    base: dict[str, object] = {
        "version_id": uuid4(),
        "input_columns": list(B),
        "output_column": "y",
        "na": len(AR),
        "nb": {c: len(v) for c, v in B.items()},
        "delays": dict(NK),
        "estimator": "ols",
    }
    base.update(overrides)
    return ArxFitRequest(**base)  # type: ignore[arg-type]


def fit(inputs: dict[str, np.ndarray], output: np.ndarray, **overrides: object):  # type: ignore[no-untyped-def]
    return fit_arx_core(
        inputs=inputs,
        output=output,
        payload=request(**overrides),
        input_columns=list(B),
    )


class TestIdentification:
    def test_recovers_parameters_from_noiseless_data(self) -> None:
        inputs = make_inputs(3000)
        result = fit(inputs, simulate(inputs, noise=0.0))
        assert result.a_coefficients[0] == pytest.approx(AR[0], abs=1e-6)
        assert result.a_coefficients[1] == pytest.approx(AR[1], abs=1e-6)
        for column, truth in B.items():
            assert result.b_coefficients[column] == pytest.approx(truth, abs=1e-6)

    def test_free_run_is_perfect_on_noiseless_data(self) -> None:
        inputs = make_inputs(3000)
        result = fit(inputs, simulate(inputs, noise=0.0))
        assert result.metrics.val_free_run_fit is not None
        assert result.metrics.val_free_run_fit > 99.99
        assert result.validation.fit_gap == pytest.approx(0.0, abs=0.01)

    def test_reports_both_one_step_and_free_run_per_partition(self) -> None:
        inputs = make_inputs(3000)
        result = fit(inputs, simulate(inputs, noise=0.03), evaluate_test=True)
        for value in (
            result.metrics.train_fit,
            result.metrics.val_fit,
            result.metrics.test_fit,
            result.metrics.train_free_run_fit,
            result.metrics.val_free_run_fit,
            result.metrics.test_free_run_fit,
        ):
            assert value is not None
        assert result.metrics.one_step["test"].r2 == result.metrics.test_r2
        assert result.metrics.one_step["test"].rmse == result.metrics.test_rmse
        assert result.metrics.free_run["test"].fit == result.metrics.test_free_run_fit

    def test_fit_and_r2_are_mathematically_consistent_for_one_aligned_series(self) -> None:
        actual = np.array([0.2, 0.5, 0.7, 1.2, 1.5], dtype=float)
        predicted = np.array([0.1, 0.45, 0.8, 1.0, 1.4], dtype=float)

        scores = _scores(actual, predicted)
        assert scores["r2"] is not None
        assert scores["fit"] is not None
        assert scores["fit"] == pytest.approx(
            100.0 * (1.0 - np.sqrt(1.0 - scores["r2"])), abs=1e-12
        )

    def test_validation_only_fit_does_not_evaluate_held_out_test_partition(self) -> None:
        inputs = make_inputs(3000)
        result = fit(inputs, simulate(inputs, noise=0.03), evaluate_test=False)
        assert result.metrics.val_free_run_fit is not None
        assert result.metrics.test_fit is None
        assert result.metrics.test_free_run_fit is None
        assert 0 < result.plot_data.splits.train_end < result.plot_data.splits.val_end
        assert result.plot_data.splits.val_end < result.plot_data.splits.test_end
        assert max(result.plot_data.indices) < result.plot_data.splits.val_end

    def test_one_step_fit_hides_a_degraded_model_that_free_run_exposes(self) -> None:
        """The whole reason free-run is the primary metric, asserted on real numbers."""

        inputs = make_inputs(4000)
        output = simulate(inputs, noise=0.03)
        good = fit(inputs, output)
        # Starve the fit: identify using only a short, weakly informative slice.
        starved = fit(
            inputs,
            output,
            training_sample_indices=list(range(20, 220)),
        )

        one_step_gap = abs((good.metrics.val_fit or 0) - (starved.metrics.val_fit or 0))
        free_run_gap = abs(
            (good.metrics.val_free_run_fit or 0) - (starved.metrics.val_free_run_fit or 0)
        )
        assert free_run_gap > one_step_gap, (
            f"free-run gap {free_run_gap:.2f} should exceed one-step gap {one_step_gap:.2f}"
        )

    def test_aic_and_bic_are_reported(self) -> None:
        inputs = make_inputs(2500)
        result = fit(inputs, simulate(inputs, noise=0.03))
        assert result.metrics.aic is not None
        assert result.metrics.bic is not None
        assert result.metrics.bic > result.metrics.aic  # more parameters penalised harder

    def test_restricting_training_rows_changes_the_fit(self) -> None:
        inputs = make_inputs(3000)
        output = simulate(inputs, noise=0.03)
        full = fit(inputs, output)
        subset = fit(inputs, output, training_sample_indices=list(range(100, 900)))
        assert subset.training_rows < full.training_rows
        assert subset.coefficients != full.coefficients

    def test_rejects_too_few_training_rows(self) -> None:
        inputs = make_inputs(2000)
        with pytest.raises(ModelingDomainError) as error:
            fit(inputs, simulate(inputs, noise=0.02), training_sample_indices=[100, 101, 102])
        assert error.value.code == "INSUFFICIENT_ROWS"

    def test_ridge_runs_when_ols_would_be_rank_deficient(self) -> None:
        inputs = make_inputs(2500)
        inputs["u2"] = inputs["u1"].copy()
        output = simulate(inputs, noise=0.02)
        # Identical signals only make identical regressor columns when they also share a
        # delay; with different nk they are shifted copies and the matrix stays full rank.
        same_delay = {"u1": 3, "u2": 3}
        with pytest.raises(ModelingDomainError) as error:
            fit(inputs, output, estimator="ols", delays=same_delay)
        assert error.value.code == "DESIGN_MATRIX_RANK_DEFICIENT"

        ridge = fit(inputs, output, estimator="ridge", ridge_alpha=1e-3, delays=same_delay)
        assert ridge.metrics.val_free_run_fit is not None


class TestPriors:
    def test_correct_gain_sign_passes(self) -> None:
        inputs = make_inputs(3000)
        result = fit(inputs, simulate(inputs, noise=0.02), gain_sign={"u1": "positive"})
        assert result.prior_violations == ()

    def test_wrong_gain_sign_is_flagged(self) -> None:
        inputs = make_inputs(3000)
        result = fit(inputs, simulate(inputs, noise=0.02), gain_sign={"u1": "negative"})
        assert [v.kind for v in result.prior_violations] == ["gain_sign"]
        assert result.prior_violations[0].variable == "u1"

    def test_gain_bounds_are_checked_against_the_analytic_gain(self) -> None:
        inputs = make_inputs(3000)
        truth = sum(B["u1"]) / (1.0 + sum(AR))
        inside = fit(
            inputs,
            simulate(inputs, noise=0.02),
            gain_bounds={"u1": (truth * 0.8, truth * 1.2)},
        )
        assert inside.prior_violations == ()

        outside = fit(
            inputs,
            simulate(inputs, noise=0.02),
            gain_bounds={"u1": (truth * 5, truth * 10)},
        )
        assert [v.kind for v in outside.prior_violations] == ["gain_bounds"]

    def test_stability_is_reported(self) -> None:
        inputs = make_inputs(3000)
        result = fit(inputs, simulate(inputs, noise=0.02))
        assert result.validation.stable
        assert result.validation.max_pole_modulus < 1.0


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'modeling.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(prepare())

    async def session_override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    monkeypatch.setattr("app.api.routes.get_settings", lambda: Settings(artifact_root=tmp_path))
    app = create_app()
    app.dependency_overrides[get_session] = session_override
    with TestClient(app) as client:
        yield client
    asyncio.run(engine.dispose())


class TestModelingApi:
    def _raw_version(self, client: TestClient) -> str:
        response = client.post(
            "/api/v1/simulation/generate",
            json={"scenario": "S2", "n_steps": 3000, "seed": 11, "input_count": 2},
        )
        assert response.status_code == 201, response.text
        return response.json()["data"]["version_id"]

    def _lag_version(self, client: TestClient) -> str:
        raw_version_id = self._raw_version(client)
        response = client.post(
            "/api/v1/preprocessing/delay/apply",
            json={
                "version_id": raw_version_id,
                "lag_map": {"u1": 3, "u2": 8},
                "user_confirmed": True,
                "recommendation_source": "manual",
            },
        )
        assert response.status_code == 201, response.text
        return response.json()["data"]["result_version_id"]

    def test_fit_returns_free_run_metrics_and_validation(self, client: TestClient) -> None:
        version_id = self._lag_version(client)
        response = client.post(
            "/api/v1/modeling/arx/fit",
            json={
                "version_id": version_id,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "na": 2,
                "nb": [2, 2],
                "delays": [0, 0],
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]

        assert data["model_structure"] == {
            "model_type": "ARX",
            "simulation_horizons": [1, 16, 64, 0],
            "simulation_max_nfev": 150,
            "regularization_kernel": "identity",
            "kernel_decay": 0.9,
            "initialization_policy": "fixed",
            "initialization_window": 32,
            "input_columns": ["u1", "u2"],
            "output_column": "y",
            "na": 2,
            "nb": {"u1": 2, "u2": 2},
            "delays": {"u1": 0, "u2": 0},
            "estimator": "ols",
            "ridge_alpha": None,
            "parameter_count": 6,
            "fit_intercept": True,
            "standardize": True,
            "history_guard": None,
        }
        assert data["metrics"]["val_free_run_fit"] is not None
        assert data["validation"]["free_run_fit"] is not None
        assert data["validation"]["one_step_fit"] is not None
        assert data["validation"]["stable"] is True
        assert data["validation"]["steady_state_gains"]
        assert data["training_rows"] > 0
        assert data["free_run_series"]
        assert data["metrics"]["test_fit"] is None
        assert data["metrics"]["test_free_run_fit"] is None
        assert "test" not in data["metrics"]["one_step"]
        assert "test" not in data["metrics"]["free_run"]
        assert "evaluation_scope" not in data
        assert "series" not in data
        assert "model_health" not in data
        assert max(data["plot_data"]["indices"]) < data["plot_data"]["splits"]["val_end"]
        assert len(data["free_run_series"]) == len(data["plot_data"]["indices"])

    def test_violating_a_prior_blocks_the_model(self, client: TestClient) -> None:
        version_id = self._lag_version(client)
        response = client.post(
            "/api/v1/modeling/arx/fit",
            json={
                "version_id": version_id,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "na": 2,
                "nb": [2, 2],
                "delays": [0, 0],
                "gain_sign": {"u1": "negative"},
            },
        )
        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == "PRIOR_CONSTRAINT_VIOLATED"
        assert body["error"]["details"]["violations"][0]["variable"] == "u1"

    def test_feature_descendant_of_lag_is_allowed(self, client: TestClient) -> None:
        lag_version_id = self._lag_version(client)
        feature = client.post(
            "/api/v1/preprocessing/features/apply",
            json={
                "version_id": lag_version_id,
                "drop_columns": ["u2"],
                "user_confirmed": True,
                "recommendation_source": "manual",
            },
        )
        assert feature.status_code == 201, feature.text

        response = client.post(
            "/api/v1/modeling/arx/fit",
            json={
                "version_id": feature.json()["data"]["result_version_id"],
                "input_columns": ["u1"],
                "output_column": "y",
                "na": 2,
                "nb": [2],
                "delays": [0],
            },
        )

        assert response.status_code == 200, response.text

        body = response.json()["data"]
        assert body["preprocessing"]["training_input_support"]["u2"]["modelled"] is False
        assert body["preprocessing"]["input_support_sources"]["u2"] == lag_version_id

    def test_raw_source_is_rejected_before_core_fitting(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def fail_if_called(*args: object, **kwargs: object) -> None:
            raise AssertionError("fit_arx_core must not run for an invalid source lineage")

        monkeypatch.setattr("app.services.modeling_service.fit_arx_core", fail_if_called)
        response = client.post(
            "/api/v1/modeling/arx/fit",
            json={
                "version_id": self._raw_version(client),
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "na": 2,
                "nb": [2, 2],
                "delays": [3, 8],
            },
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "ARX_LAG_COMPENSATED_VERSION_REQUIRED"

    def test_cleaning_source_is_rejected(self, client: TestClient) -> None:
        cleaned = client.post(
            "/api/v1/preprocessing/clean",
            json={
                "version_id": self._raw_version(client),
                "anomaly_detector": "hampel",
                "smoothing": "moving_average",
            },
        )
        assert cleaned.status_code == 202, cleaned.text

        response = client.post(
            "/api/v1/modeling/arx/fit",
            json={
                "version_id": cleaned.json()["data"]["derived_version_id"],
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "na": 2,
                "nb": [2, 2],
                "delays": [3, 8],
            },
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "ARX_LAG_COMPENSATED_VERSION_REQUIRED"

    def test_feature_without_lag_ancestor_is_rejected(self, client: TestClient) -> None:
        feature = client.post(
            "/api/v1/preprocessing/features/apply",
            json={
                "version_id": self._raw_version(client),
                "drop_columns": ["u2"],
                "user_confirmed": True,
                "recommendation_source": "manual",
            },
        )
        assert feature.status_code == 201, feature.text

        response = client.post(
            "/api/v1/modeling/arx/fit",
            json={
                "version_id": feature.json()["data"]["result_version_id"],
                "input_columns": ["u1"],
                "output_column": "y",
                "na": 2,
                "nb": [2],
                "delays": [3],
            },
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "ARX_LAG_COMPENSATED_VERSION_REQUIRED"

    def test_unknown_version_returns_404(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/modeling/arx/fit",
            json={
                "version_id": str(uuid4()),
                "input_columns": ["u1"],
                "output_column": "y",
                "na": 2,
                "nb": [2],
                "delays": [3],
            },
        )
        assert response.status_code == 404


class TestExcitationIsReportedNotEnforced:
    """`ALG-0.2` §3 originally specified persistent excitation as a blocking precondition.

    Implementing it that way and measuring the result showed the criterion cannot carry
    that weight: at the calibrated tolerance an 8-level input reports PE order 1 while its
    model reaches 95.8% free-run FIT, and at a looser tolerance a 3-level input clears the
    na+nb requirement while its model collapses to 0.2%. No tolerance separated the two.

    These tests pin the resulting decision in place so it is not quietly reverted into a
    gate that rejects good models and admits bad ones.
    """

    def test_a_richly_excited_record_reports_no_shortfall_or_a_harmless_one(self) -> None:
        inputs = make_inputs(3000)
        output = simulate(inputs, noise=0.02)
        result = fit(inputs, output)
        # Whatever the estimator says, a model this good must not have been blocked.
        assert result.validation.free_run_fit is not None
        assert result.validation.free_run_fit > 80.0

    def test_an_under_excited_record_still_returns_a_model_plus_the_shortfall(self) -> None:
        """Two constant-ish levels: genuinely poor excitation, and it must not raise."""

        n = 3000
        inputs = {}
        for offset, column in enumerate(B):
            values = np.zeros(n, dtype=float)
            values[n // 2 :] = 1.0 + 0.25 * offset
            inputs[column] = values
        output = simulate(inputs, noise=0.02)

        result = fit(inputs, output)  # must not raise
        assert result.validation is not None
        # The shortfall is reported so the engineer can see why the model may be poor.
        assert result.excitation_shortfall, "欠激励必须被上报，否则工程师无从判断"
        for channel, orders in result.excitation_shortfall.items():
            assert orders["actual"] < orders["required"], channel

    def test_the_shortfall_reaches_the_response_schema(self) -> None:
        from app.services.modeling_service import to_validation_data

        n = 3000
        inputs = {c: np.concatenate([np.zeros(n // 2), np.ones(n - n // 2)]) for c in B}
        output = simulate(inputs, noise=0.02)
        result = fit(inputs, output)
        payload = to_validation_data(result.validation, result.excitation_shortfall)
        assert payload.excitation_shortfall == result.excitation_shortfall

    def test_rank_deficiency_is_what_actually_blocks(self) -> None:
        """The hard gate is the design matrix, not the PE-order estimate."""

        n = 2000
        base = np.zeros(n, dtype=float)
        base[n // 3 :] = 1.0
        # Identical inputs *and* identical delays make the two regressor blocks exact
        # duplicates, so OLS cannot separate their contributions. (Different delays would
        # only make them shifted copies, which stays numerically full rank.)
        inputs = {column: base.copy() for column in B}
        output = simulate(inputs, noise=0.01)
        with pytest.raises(ModelingDomainError) as error:
            fit(inputs, output, estimator="ols", delays=dict.fromkeys(B, 3))
        assert error.value.code == "DESIGN_MATRIX_RANK_DEFICIENT"
