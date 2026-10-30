"""End-to-end guards for immutable preprocessing version chains."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from app.core.config import Settings
from app.core.db import get_session
from app.main import create_app
from app.models import Base
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'versions.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(prepare())

    async def override() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    monkeypatch.setattr("app.api.routes.get_settings", lambda: Settings(artifact_root=tmp_path))
    app = create_app()
    app.dependency_overrides[get_session] = override
    with TestClient(app) as test_client:
        yield test_client
    asyncio.run(engine.dispose())


def test_immutable_clean_lag_feature_chain_is_downloadable_and_modelable(client: TestClient) -> None:
    generated = client.post(
        "/api/v1/simulation/generate",
        json={"scenario": "S5", "n_steps": 1200, "seed": 31, "input_count": 2},
    )
    assert generated.status_code == 201, generated.text
    v1 = generated.json()["data"]["version_id"]
    dataset_id = generated.json()["data"]["dataset_id"]

    cleaned = client.post(
        "/api/v1/preprocessing/clean",
        json={"version_id": v1, "anomaly_detector": "hampel", "smoothing": "moving_average"},
    )
    assert cleaned.status_code == 202, cleaned.text
    v2 = cleaned.json()["data"]["derived_version_id"]
    assert v2 != v1
    assert cleaned.json()["data"]["processing_run_id"]

    analyzed = client.post(
        "/api/v1/preprocessing/delay",
        json={"version_id": v2, "input_columns": ["u1", "u2"], "output_column": "y", "max_lag": 12},
    )
    assert analyzed.status_code == 202, analyzed.text
    # Analysis only persists an audit run; it must not replace the active data version.
    assert client.get(f"/api/v1/datasets/{dataset_id}/versions").json()["data"]["active_version_id"] == v2

    lagged = client.post(
        "/api/v1/preprocessing/delay/apply",
        json={
            "version_id": v2,
            "lag_map": {"u1": 3, "u2": 8},
            "user_confirmed": True,
            "recommendation_source": "manual",
        },
    )
    assert lagged.status_code == 201, lagged.text
    v3 = lagged.json()["data"]["result_version_id"]
    assert lagged.json()["data"]["summary"]["removed_boundary_rows"] == 8

    features = client.post(
        "/api/v1/preprocessing/features/apply",
        json={
            "version_id": v3,
            "drop_columns": ["u2"],
            "user_confirmed": True,
            "recommendation_source": "manual",
            "evidence": {"u2": {"reason": "test-confirmed redundant variable"}},
        },
    )
    assert features.status_code == 201, features.text
    v4 = features.json()["data"]["result_version_id"]

    versions = client.get(f"/api/v1/datasets/{dataset_id}/versions").json()["data"]
    by_id = {item["id"]: item for item in versions["nodes"]}
    assert [by_id[version]["parent_version_id"] for version in (v2, v3, v4)] == [v1, v2, v3]
    assert by_id[v3]["row_count"] == by_id[v2]["row_count"] - 8
    assert by_id[v4]["column_count"] == by_id[v3]["column_count"] - 1
    assert versions["active_version_id"] == v4
    for version in (v1, v2, v3, v4):
        profile = client.get(f"/api/v1/datasets/{dataset_id}/profile?version_id={version}")
        assert profile.status_code == 200, profile.text
        assert profile.json()["data"]["total_rows"] == by_id[version]["row_count"]
        assert profile.json()["data"]["total_cols"] == by_id[version]["column_count"]
    for version in (v1, v2, v3, v4):
        assert client.get(f"/api/v1/datasets/{dataset_id}/download?version_id={version}").status_code == 200

    modeled = client.post(
        "/api/v1/modeling/arx/fit",
        json={"version_id": v4, "input_columns": ["u1"], "output_column": "y", "na": 2, "nb": [2], "delays": [0]},
    )
    assert modeled.status_code == 200, modeled.text
    optimized = client.post(
        "/api/v1/optimization/optuna/start",
        json={
            "version_id": v4,
            "input_columns": ["u1"],
            "output_column": "y",
            "max_trials": 2,
            "random_seed": 17,
        },
    )
    assert optimized.status_code == 202, optimized.text
    status = client.get(
        f"/api/v1/optimization/optuna/{optimized.json()['data']['study_id']}/status"
    )
    assert status.status_code == 200, status.text
    assert len(status.json()["data"]["trials"]) == 2


def test_feature_apply_refuses_target_or_all_inputs(client: TestClient) -> None:
    generated = client.post(
        "/api/v1/simulation/generate", json={"scenario": "S2", "n_steps": 800, "seed": 44}
    ).json()["data"]
    target = client.post(
        "/api/v1/preprocessing/features/apply",
        json={"version_id": generated["version_id"], "drop_columns": ["y"], "user_confirmed": True},
    )
    assert target.status_code == 400
    all_inputs = client.post(
        "/api/v1/preprocessing/features/apply",
        json={"version_id": generated["version_id"], "drop_columns": ["u1", "u2"], "user_confirmed": True},
    )
    assert all_inputs.status_code == 400


def test_lag_apply_requires_every_source_input_and_creates_a_version_in_postgres_safe_order(
    client: TestClient,
) -> None:
    generated = client.post(
        "/api/v1/simulation/generate",
        json={"scenario": "S6", "n_steps": 1200, "seed": 20260903, "input_count": 4},
    )
    assert generated.status_code == 201, generated.text
    data = generated.json()["data"]

    incomplete = client.post(
        "/api/v1/preprocessing/delay/apply",
        json={
            "dataset_id": data["dataset_id"],
            "version_id": data["version_id"],
            "lag_map": {"u1": 3, "u2": 8, "u3": 5},
            "user_confirmed": True,
            "recommendation_source": "manual",
        },
    )
    assert incomplete.status_code == 400, incomplete.text
    assert incomplete.json()["error"]["code"] == "INCOMPLETE_LAG_MAP"
    assert incomplete.json()["error"]["details"] == {"missing": ["u4"]}

    complete = client.post(
        "/api/v1/preprocessing/delay/apply",
        json={
            "dataset_id": data["dataset_id"],
            "version_id": data["version_id"],
            "lag_map": {"u1": 3, "u2": 8, "u3": 5, "u4": 11},
            "user_confirmed": True,
            "recommendation_source": "manual",
            "evidence_summary": {"u4": "human specified without Delay Analyze recommendation"},
        },
    )
    assert complete.status_code == 201, complete.text
    assert complete.json()["data"]["summary"]["lag_map"] == {"u1": 3, "u2": 8, "u3": 5, "u4": 11}
