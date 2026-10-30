from uuid import UUID, uuid4

from app.core.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


def test_liveness_uses_the_standard_success_envelope() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["error"] is None
    assert payload["data"]["status"] == "ok"
    assert UUID(payload["request_id"]).version == 4
    assert response.headers["x-request-id"] == payload["request_id"]


def test_validation_errors_use_the_standard_error_envelope() -> None:
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/simulation/generate", json={"scenario": "S9"})

    assert response.status_code == 422
    payload = response.json()
    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == "REQUEST_VALIDATION_FAILED"
    assert UUID(payload["request_id"]).version == 4


def test_simulation_contract_returns_truth_fields(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import asyncio
    from collections.abc import AsyncIterator

    from app.core.db import get_session
    from app.models import Base
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'simulation-contract.db'}")
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
        response = client.post(
            "/api/v1/simulation/generate",
            json={"scenario": "S2", "input_count": 2, "seed": 7},
        )
    asyncio.run(engine.dispose())

    assert response.status_code == 201
    payload = response.json()["data"]
    assert payload["scenario"] == "S2"
    assert payload["ground_truth"]["seed"] == 7
    assert {
        "ar_coefficients",
        "input_coefficients",
        "true_delays",
        "dynamic_segments",
        "seed",
    }.issubset(payload["ground_truth"])


def test_ready_contract_accepts_connected_dependencies(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    async def ready() -> bool:
        return True

    monkeypatch.setattr("app.api.routes.database_is_ready", ready)
    monkeypatch.setattr("app.api.routes.redis_is_ready", ready)
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "status": "ready",
        "database": "connected",
        "queue": "connected",
    }


def test_openapi_contains_all_phase_one_paths() -> None:
    schema = create_app().openapi()
    expected_paths = {
        "/api/v1/health/live",
        "/api/v1/health/ready",
        "/api/v1/system/info",
        "/api/v1/simulation/generate",
        "/api/v1/datasets/upload",
        "/api/v1/datasets",
        "/api/v1/datasets/{dataset_id}",
        "/api/v1/datasets/{dataset_id}/profile",
        "/api/v1/datasets/{dataset_id}/versions",
        "/api/v1/preprocessing/clean",
        "/api/v1/preprocessing/segment",
        "/api/v1/preprocessing/delay",
        "/api/v1/preprocessing/collinearity",
        "/api/v1/modeling/arx/fit",
        "/api/v1/optimization/optuna/start",
        "/api/v1/optimization/optuna/{study_id}/status",
        "/api/v1/tasks/{task_id}/cancel",
        "/api/v1/copilot/chat",
        "/api/v1/copilot/confirm",
    }
    assert expected_paths.issubset(schema["paths"])
    assert schema["openapi"] == "3.1.0"


def test_optimization_status_exposes_phase_2c2b1_lifecycle_contract() -> None:
    from datetime import UTC, datetime

    from app.schemas.optimization import (
        OptimizationJobObservation,
        OptimizationStatusData,
        OptimizationTerminalReason,
        OptimizationTerminalReasonV1,
        OptimizationTerminalReasonV2,
    )
    from pydantic import TypeAdapter

    status_schema = OptimizationStatusData.model_json_schema()
    job_schema = OptimizationJobObservation.model_json_schema()
    terminal_v1_schema = OptimizationTerminalReasonV1.model_json_schema()
    terminal_v2_schema = OptimizationTerminalReasonV2.model_json_schema()

    assert status_schema["properties"]["study_status"]["enum"] == [
        "queued",
        "running",
        "succeeded",
        "failed",
    ]
    assert terminal_v1_schema["properties"]["code"]["enum"] == [
        "COMPLETED",
        "NO_VALID_CANDIDATE",
        "FAILED",
    ]
    assert terminal_v1_schema["properties"]["phase"]["enum"] == [
        "preparation",
        "baseline",
        "search",
        "winner_persistence",
        "study_persistence",
    ]
    assert terminal_v2_schema["properties"]["code"]["enum"] == [
        "COMPLETED",
        "NO_VALID_CANDIDATE",
        "FAILED",
        "RQ_TIMEOUT",
        "WORKER_CRASH",
    ]
    assert terminal_v2_schema["properties"]["phase"]["enum"] == [
        "preparation",
        "baseline",
        "search",
        "winner_persistence",
        "study_persistence",
        "queue_submission",
        "rq_execution",
    ]
    terminal_union = status_schema["properties"]["terminal_reason"]["anyOf"][0]
    assert terminal_union["discriminator"] == {
        "mapping": {
            "optimization_terminal_reason_v1": "#/$defs/OptimizationTerminalReasonV1",
            "optimization_terminal_reason_v2": "#/$defs/OptimizationTerminalReasonV2",
        },
        "propertyName": "policy_version",
    }
    historical = TypeAdapter(OptimizationTerminalReason).validate_python(
        {
            "policy_version": "optimization_terminal_reason_v1",
            "code": "FAILED",
            "category": "SYSTEM_FAILURE",
            "phase": "search",
            "error_code": "STUDY_EXECUTION_FAILED",
            "recorded_at": datetime.now(UTC),
        }
    )
    assert isinstance(historical, OptimizationTerminalReasonV1)
    assert "job" in status_schema["properties"]
    assert job_schema["properties"]["availability"]["enum"] == [
        "AVAILABLE",
        "NOT_FOUND",
        "UNAVAILABLE",
        "IDENTITY_MISMATCH",
        "NOT_APPLICABLE",
        "LEGACY",
    ]


def test_copilot_contract_has_a_whitelisted_plan(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # The agent persists its plan, proof and step records, so it needs a session.
    import asyncio
    from collections.abc import AsyncIterator

    from app.core.db import get_session
    from app.models import Base
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'copilot.db'}")
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
        response = client.post(
            "/api/v1/copilot/chat",
            json={"message": "先做数据质量诊断", "dataset_id": str(uuid4())},
        )

    assert response.status_code == 200
    body = response.json()["data"]
    plan = body["plan"]
    assert plan["steps"][0]["tool"] == "profile_dataset"
    assert body["compliance"]["passed"] is True
    asyncio.run(engine.dispose())


def test_api_runs_real_simulation_and_arx_baseline(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # The ARX route persists a ProcessingRun for report lineage, so it needs a session.
    import asyncio
    from collections.abc import AsyncIterator

    from app.core.db import get_session
    from app.models import Base
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'contract.db'}")
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
        simulation = client.post(
            "/api/v1/simulation/generate",
            json={
                "scenario": "S1",
                "dataset_name": "api_noiseless_s1",
                "num_samples": 1_500,
                "noise_level": 0.0,
                "seed": 5,
            },
        )
        assert simulation.status_code == 201
        generated = simulation.json()["data"]
        lagged = client.post(
            "/api/v1/preprocessing/delay/apply",
            json={
                "dataset_id": generated["dataset_id"],
                "version_id": generated["version_id"],
                "lag_map": {"u1": 3},
                "user_confirmed": True,
                "recommendation_source": "manual",
                "evidence_summary": {"fixture": "known_simulation_lag"},
            },
        )
        assert lagged.status_code == 201, lagged.text
        lagged_version_id = lagged.json()["data"]["result_version_id"]
        fitted = client.post(
            "/api/v1/modeling/arx/fit",
            json={
                "dataset_id": generated["dataset_id"],
                "version_id": lagged_version_id,
                "na": 2,
                "nb": [2],
                "delays": [0],
                "estimation_method": "ols",
                "evaluate_test": True,
            },
        )

    assert fitted.status_code == 200
    result = fitted.json()["data"]
    assert result["task"]["status"] == "succeeded"
    assert result["metrics"]["test_fit"] > 99.99
    assert len(result["plot_data"]["y_true"]) > 1_000
    assert (tmp_path / generated["file_path"]).is_file()
    assert (tmp_path / result["artifact_uri"]).is_file()
