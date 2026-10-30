"""Regression coverage for the read-only Collinearity source-version selector."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from app.core.config import Settings
from app.core.db import get_session
from app.main import create_app
from app.models import Base, Dataset, DatasetColumn, DatasetVersion, ProcessingRun
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'collinearity-sources.db'}")
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
    app.state.collinearity_sources_session_factory = session_factory
    app.dependency_overrides[get_session] = session_override
    with TestClient(app) as client:
        yield client
    asyncio.run(engine.dispose())


def _complete_result() -> dict[str, object]:
    return {
        "variables": ["u1", "u2"],
        "pearson": [[1.0, 0.92], [0.92, 1.0]],
        "spearman": [[1.0, 0.9], [0.9, 1.0]],
        "vif": {"u1": 6.1, "u2": 6.1},
        "condition_number": 4.2,
        "groups": [["u1", "u2"]],
        "advice": [
            {
                "variable": "u2",
                "action": "review",
                "reason": "high correlation",
                "related_variables": ["u1"],
            }
        ],
    }


async def _create_dataset(session: AsyncSession, *, suffix: str, now: datetime) -> Dataset:
    dataset = Dataset(
        id=uuid4(),
        name=f"dataset-{suffix}",
        source="simulation",
        status="ready",
        raw_sha256=(suffix * 64)[:64],
        raw_path=f"datasets/{suffix}/raw.csv",
        byte_size=1,
        encoding="utf-8",
        delimiter=",",
        created_at=now,
        updated_at=now,
    )
    session.add(dataset)
    return dataset


async def _create_version(
    session: AsyncSession,
    *,
    dataset: Dataset,
    index: int,
    operation: str,
    created_at: datetime,
    parent_version_id: UUID | None = None,
) -> DatasetVersion:
    version = DatasetVersion(
        id=uuid4(),
        dataset_id=dataset.id,
        parent_version_id=parent_version_id,
        version_index=index,
        name=f"V{index} · {operation}",
        operation_name=operation,
        parameters={},
        artifact_path=f"datasets/{dataset.id}/versions/{index}-{uuid4()}.csv",
        sha256="a" * 64,
        row_count=10,
        column_count=3,
        created_at=created_at,
    )
    session.add(version)
    return version


async def _create_input_columns(session: AsyncSession, version: DatasetVersion) -> None:
    for position, name in enumerate(("u1", "u2", "u3", "u4")):
        session.add(
            DatasetColumn(
                id=uuid4(),
                dataset_id=version.dataset_id,
                version_id=version.id,
                name=name,
                role="input",
                position=position,
                inferred_type="float",
            )
        )


async def _create_collinearity_run(
    session: AsyncSession,
    *,
    dataset: Dataset,
    source: DatasetVersion,
    status: str,
    created_at: datetime,
    complete: bool,
) -> ProcessingRun:
    run = ProcessingRun(
        id=uuid4(),
        dataset_id=dataset.id,
        source_version_id=source.id,
        run_type="preprocessing.collinearity",
        status=status,
        parameters={"input_columns": ["u1", "u2"]},
        result=_complete_result() if complete else {"variables": ["u1", "u2"]},
        created_at=created_at,
        finished_at=created_at,
    )
    session.add(run)
    return run


class TestCollinearitySourceSelectorApi:
    def test_returns_only_lag_versions_with_statuses_default_and_no_writes(
        self, api_client: TestClient
    ) -> None:
        async def seed() -> dict[str, UUID]:
            now = datetime.now(UTC)
            async with api_client.app.state.collinearity_sources_session_factory() as session:
                dataset = await _create_dataset(session, suffix="col-a", now=now)
                clean = await _create_version(
                    session,
                    dataset=dataset,
                    index=1,
                    operation="preprocessing.clean",
                    created_at=now,
                )
                complete_lag = await _create_version(
                    session,
                    dataset=dataset,
                    index=10,
                    operation="preprocessing.lag_compensation",
                    created_at=now + timedelta(seconds=5),
                    parent_version_id=clean.id,
                )
                latest_lag = await _create_version(
                    session,
                    dataset=dataset,
                    index=10,
                    operation="preprocessing.lag_compensation",
                    created_at=now + timedelta(seconds=10),
                    parent_version_id=complete_lag.id,
                )
                incomplete_lag = await _create_version(
                    session,
                    dataset=dataset,
                    index=8,
                    operation="preprocessing.lag_compensation",
                    created_at=now + timedelta(seconds=8),
                    parent_version_id=clean.id,
                )
                for lag_version in (complete_lag, latest_lag, incomplete_lag):
                    await _create_input_columns(session, lag_version)
                await _create_version(
                    session,
                    dataset=dataset,
                    index=11,
                    operation="preprocessing.feature_selection",
                    created_at=now + timedelta(seconds=11),
                    parent_version_id=latest_lag.id,
                )
                latest_complete = await _create_collinearity_run(
                    session,
                    dataset=dataset,
                    source=complete_lag,
                    status="succeeded",
                    created_at=now + timedelta(seconds=20),
                    complete=True,
                )
                await _create_collinearity_run(
                    session,
                    dataset=dataset,
                    source=complete_lag,
                    status="succeeded",
                    created_at=now + timedelta(seconds=21),
                    complete=False,
                )
                await _create_collinearity_run(
                    session,
                    dataset=dataset,
                    source=incomplete_lag,
                    status="succeeded",
                    created_at=now + timedelta(seconds=22),
                    complete=False,
                )
                await _create_collinearity_run(
                    session,
                    dataset=dataset,
                    source=latest_lag,
                    status="failed",
                    created_at=now + timedelta(seconds=23),
                    complete=False,
                )
                await _create_collinearity_run(
                    session,
                    dataset=dataset,
                    source=latest_lag,
                    status="running",
                    created_at=now + timedelta(seconds=24),
                    complete=True,
                )
                await _create_collinearity_run(
                    session,
                    dataset=dataset,
                    source=latest_lag,
                    status="pending",
                    created_at=now + timedelta(seconds=25),
                    complete=True,
                )
                dataset.active_version_id = latest_lag.id

                other = await _create_dataset(session, suffix="col-b", now=now)
                other_lag = await _create_version(
                    session,
                    dataset=other,
                    index=99,
                    operation="preprocessing.lag_compensation",
                    created_at=now + timedelta(seconds=30),
                )
                await _create_collinearity_run(
                    session,
                    dataset=other,
                    source=other_lag,
                    status="succeeded",
                    created_at=now + timedelta(seconds=31),
                    complete=True,
                )
                await _create_collinearity_run(
                    session,
                    dataset=other,
                    source=latest_lag,
                    status="succeeded",
                    created_at=now + timedelta(seconds=32),
                    complete=True,
                )
                await session.commit()
                return {
                    "dataset_id": dataset.id,
                    "latest_lag": latest_lag.id,
                    "complete_lag": complete_lag.id,
                    "incomplete_lag": incomplete_lag.id,
                    "latest_complete_run": latest_complete.id,
                }

        ids = asyncio.run(seed())

        async def snapshot() -> tuple[int, int, UUID | None]:
            async with api_client.app.state.collinearity_sources_session_factory() as session:
                runs = int(await session.scalar(select(func.count()).select_from(ProcessingRun)) or 0)
                versions = int(
                    await session.scalar(select(func.count()).select_from(DatasetVersion)) or 0
                )
                dataset = await session.get(Dataset, ids["dataset_id"])
                assert dataset is not None
                return runs, versions, dataset.active_version_id

        before = asyncio.run(snapshot())
        response = api_client.get(
            f"/api/v1/datasets/{ids['dataset_id']}/collinearity-sources"
        )
        assert response.status_code == 200, response.text
        assert asyncio.run(snapshot()) == before

        data = response.json()["data"]
        assert data["dataset_id"] == str(ids["dataset_id"])
        assert data["default_source_version_id"] == str(ids["complete_lag"])
        assert [source["version_id"] for source in data["sources"]] == [
            str(ids["latest_lag"]),
            str(ids["complete_lag"]),
            str(ids["incomplete_lag"]),
        ]
        assert all(
            source["operation_name"] == "preprocessing.lag_compensation"
            for source in data["sources"]
        )
        by_id = {source["version_id"]: source for source in data["sources"]}
        assert set(by_id[str(ids["complete_lag"])]) == {
            "version_id",
            "version_index",
            "name",
            "operation_name",
            "parent_version_id",
            "created_at",
            "input_columns",
            "collinearity_status",
            "latest_complete_collinearity_run_id",
        }
        assert by_id[str(ids["complete_lag"])]["input_columns"] == ["u1", "u2", "u3", "u4"]
        assert by_id[str(ids["latest_lag"])]["collinearity_status"] == "not_analyzed"
        assert by_id[str(ids["complete_lag"])]["collinearity_status"] == "complete"
        assert by_id[str(ids["complete_lag"])][
            "latest_complete_collinearity_run_id"
        ] == str(ids["latest_complete_run"])
        assert by_id[str(ids["incomplete_lag"])][
            "collinearity_status"
        ] == "unrehydratable"
        assert by_id[str(ids["incomplete_lag"])][
            "latest_complete_collinearity_run_id"
        ] is None

    def test_falls_back_to_latest_lag_version_when_none_are_complete(
        self, api_client: TestClient
    ) -> None:
        async def seed() -> tuple[UUID, UUID, UUID]:
            now = datetime.now(UTC)
            async with api_client.app.state.collinearity_sources_session_factory() as session:
                dataset = await _create_dataset(session, suffix="col-c", now=now)
                older = await _create_version(
                    session,
                    dataset=dataset,
                    index=1,
                    operation="preprocessing.lag_compensation",
                    created_at=now,
                )
                latest = await _create_version(
                    session,
                    dataset=dataset,
                    index=2,
                    operation="preprocessing.lag_compensation",
                    created_at=now + timedelta(seconds=1),
                    parent_version_id=older.id,
                )
                await _create_collinearity_run(
                    session,
                    dataset=dataset,
                    source=older,
                    status="succeeded",
                    created_at=now + timedelta(seconds=2),
                    complete=False,
                )
                await session.commit()
                return dataset.id, older.id, latest.id

        dataset_id, older_id, latest_id = asyncio.run(seed())
        response = api_client.get(f"/api/v1/datasets/{dataset_id}/collinearity-sources")
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["default_source_version_id"] == str(latest_id)
        by_id = {source["version_id"]: source for source in data["sources"]}
        assert by_id[str(older_id)]["collinearity_status"] == "unrehydratable"
        assert by_id[str(latest_id)]["collinearity_status"] == "not_analyzed"

    def test_returns_empty_sources_when_dataset_has_no_lag_version(
        self, api_client: TestClient
    ) -> None:
        async def seed() -> UUID:
            now = datetime.now(UTC)
            async with api_client.app.state.collinearity_sources_session_factory() as session:
                dataset = await _create_dataset(session, suffix="col-d", now=now)
                await _create_version(
                    session,
                    dataset=dataset,
                    index=0,
                    operation="preprocessing.clean",
                    created_at=now,
                )
                await session.commit()
                return dataset.id

        dataset_id = asyncio.run(seed())
        response = api_client.get(f"/api/v1/datasets/{dataset_id}/collinearity-sources")
        assert response.status_code == 200, response.text
        assert response.json()["data"] == {
            "dataset_id": str(dataset_id),
            "default_source_version_id": None,
            "sources": [],
        }
