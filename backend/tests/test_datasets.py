import asyncio
import csv
from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from app.core.config import Settings
from app.core.db import get_session
from app.main import create_app
from app.models import Base, Dataset, DatasetVersion, ProcessingRun
from app.services.dataset_csv import load_csv_page
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
def dataset_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Use SQLite only for route tests; Alembic remains the production PostgreSQL path."""

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'datasets.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(prepare())

    async def session_override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    monkeypatch.setattr(
        "app.api.routes.get_settings",
        lambda: Settings(
            artifact_root=tmp_path, database_url=f"sqlite+aiosqlite:///{tmp_path / 'datasets.db'}"
        ),
    )
    app = create_app()
    app.state.dataset_test_session_factory = session_factory
    app.dependency_overrides[get_session] = session_override
    with TestClient(app) as client:
        yield client
    asyncio.run(engine.dispose())


def _upload(client: TestClient, content: bytes, name: str = "industrial.csv") -> dict[str, object]:
    response = client.post(
        "/api/v1/datasets/upload",
        files={"file": (name, content, "text/csv")},
        data={"name": "锅炉时序"},
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["success"] is True
    return body["data"]


def _preview_csv(total: int, *, value_offset: int = 0) -> bytes:
    lines = ["timestamp,u1,y"]
    started_at = datetime(2026, 1, 1)
    for index in range(total):
        timestamp = (started_at + timedelta(seconds=index)).isoformat(sep=" ")
        value = value_offset + index
        lines.append(f"{timestamp},{value},{value * 2}")
    return ("\n".join(lines) + "\n").encode()


def _persistence_counts(client: TestClient) -> tuple[int, int]:
    async def read_counts() -> tuple[int, int]:
        session_factory = client.app.state.dataset_test_session_factory
        async with session_factory() as session:
            versions = int(await session.scalar(select(func.count()).select_from(DatasetVersion)) or 0)
            runs = int(await session.scalar(select(func.count()).select_from(ProcessingRun)) or 0)
            return versions, runs

    return asyncio.run(read_counts())


@pytest.mark.parametrize(
    ("content", "expected_code"),
    [
        (b"u1,y\n1,2\n2,3\n", "INVALID_DATASET_SCHEMA"),
        (b"timestamp,u1,y\nnot-a-time,1,2\n", "TIMESTAMP_PARSE_FAILED"),
        (b"timestamp,u1,y\n2026-01-01 00:00:00,,1\n", "INVALID_DATASET_SCHEMA"),
        (b"timestamp,u1,u1\n2026-01-01 00:00:00,1,2\n", "INVALID_DATASET_SCHEMA"),
    ],
)
def test_upload_rejects_malformed_csvs(
    dataset_client: TestClient, content: bytes, expected_code: str
) -> None:
    response = dataset_client.post(
        "/api/v1/datasets/upload",
        files={"file": ("invalid.csv", content, "text/csv")},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == expected_code


def test_upload_profile_config_lineage_and_delete(dataset_client: TestClient) -> None:
    content = b"""timestamp,u1,y,note
2026-01-01 00:00:00,0,10,normal
2026-01-01 00:00:01,0,11,normal
2026-01-01 00:00:02,,12,missing
2026-01-01 00:00:02,0,13,duplicate
2026-01-01 00:00:04,0,100,outlier
2026-01-01 00:00:05,0,15,normal
"""
    uploaded = _upload(dataset_client, content)
    dataset = uploaded["dataset"]
    assert isinstance(dataset, dict)
    dataset_id = dataset["id"]
    assert dataset["status"] == "ready"
    assert uploaded["deduplicated"] is False

    listing = dataset_client.get("/api/v1/datasets")
    assert listing.status_code == 200
    items = listing.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["row_count"] == 6
    assert items[0]["time_column"] == "timestamp"

    detail = dataset_client.get(f"/api/v1/datasets/{dataset_id}")
    assert detail.status_code == 200
    assert detail.json()["data"]["preview"]["rows"][0]["u1"] == 0

    profile = dataset_client.get(f"/api/v1/datasets/{dataset_id}/profile")
    assert profile.status_code == 200
    profile_data = profile.json()["data"]
    assert profile_data["total_rows"] == 6
    assert profile_data["total_cols"] == 4
    assert profile_data["missing_rates"]["u1"] == pytest.approx(1 / 6)
    assert profile_data["duplicate_timestamp_count"] == 1
    assert profile_data["max_consecutive_missing"]["u1"] == 1
    assert profile_data["quality_score"] < 100
    assert profile_data["column_statistics"]["y"]["q50"] is not None

    configured = dataset_client.post(
        f"/api/v1/datasets/{dataset_id}/config",
        json={
            "columns": [
                {"name": "timestamp", "role": "time"},
                {"name": "u1", "role": "input", "unit": "MW"},
                {"name": "y", "role": "output", "unit": "bar"},
                {"name": "note", "role": "ignored"},
            ]
        },
    )
    assert configured.status_code == 200, configured.text
    configured_data = configured.json()["data"]
    assert configured_data["dataset"]["input_columns"] == ["u1"]
    assert configured_data["dataset"]["output_column"] == "y"

    lineage = dataset_client.get(f"/api/v1/datasets/{dataset_id}/versions")
    assert lineage.status_code == 200
    assert len(lineage.json()["data"]["nodes"]) == 1
    assert lineage.json()["data"]["nodes"][0]["tool"] == "raw_upload"

    duplicate = _upload(dataset_client, content)
    assert duplicate["deduplicated"] is True
    assert duplicate["dataset"]["id"] == dataset_id

    deleted = dataset_client.delete(f"/api/v1/datasets/{dataset_id}")
    assert deleted.status_code == 200
    assert deleted.json()["data"]["status"] == "deleted"
    assert dataset_client.get("/api/v1/datasets").json()["data"]["page"]["total"] == 0
    assert dataset_client.get(f"/api/v1/datasets/{dataset_id}/profile").status_code == 404


def test_upload_detects_gbk_and_semicolon_delimiter(dataset_client: TestClient) -> None:
    content = "时间;u1;y\n2026-01-01 00:00:00;1;2\n2026-01-01 00:00:01;2;3\n".encode("gbk")
    uploaded = _upload(dataset_client, content, name="gbk.csv")
    dataset = uploaded["dataset"]
    assert isinstance(dataset, dict)
    assert dataset["column_count"] == 3
    detail = dataset_client.get(f"/api/v1/datasets/{dataset['id']}")
    assert detail.status_code == 200
    assert detail.json()["data"]["preview"]["columns"] == ["时间", "u1", "y"]


def test_detail_preview_is_bounded_real_data_and_get_does_not_change_lineage(
    dataset_client: TestClient,
) -> None:
    lines = ["timestamp,u1,y"]
    for index in range(150):
        minute, second = divmod(index, 60)
        lines.append(f"2026-01-01 00:{minute:02d}:{second:02d},{index},{index * 2}")
    uploaded = _upload(dataset_client, ("\n".join(lines) + "\n").encode())
    dataset = uploaded["dataset"]
    assert isinstance(dataset, dict)
    dataset_id = dataset["id"]
    before = dataset_client.get(f"/api/v1/datasets/{dataset_id}/versions").json()["data"]

    response = dataset_client.get(f"/api/v1/datasets/{dataset_id}")

    assert response.status_code == 200
    preview = response.json()["data"]["preview"]
    assert preview["columns"] == ["timestamp", "u1", "y"]
    assert len(preview["rows"]) == 100
    assert preview["rows"][0]["u1"] == 0
    assert preview["rows"][99]["y"] == 198
    assert preview["truncated"] is True
    after = dataset_client.get(f"/api/v1/datasets/{dataset_id}/versions").json()["data"]
    assert after == before


def test_version_preview_paginates_without_mutating_lineage(dataset_client: TestClient) -> None:
    uploaded = _upload(dataset_client, _preview_csv(250))
    dataset = uploaded["dataset"]
    assert isinstance(dataset, dict)
    dataset_id = dataset["id"]
    version_id = dataset["version_id"]
    endpoint = f"/api/v1/datasets/{dataset_id}/versions/{version_id}/preview"
    lineage_before = dataset_client.get(f"/api/v1/datasets/{dataset_id}/versions").json()["data"]
    counts_before = _persistence_counts(dataset_client)

    first = dataset_client.get(endpoint, params={"page": 1, "page_size": 100})
    second = dataset_client.get(endpoint, params={"page": 2, "page_size": 100})
    last = dataset_client.get(endpoint, params={"page": 3, "page_size": 100})
    fifty = dataset_client.get(endpoint, params={"page": 2, "page_size": 50})
    two_hundred = dataset_client.get(endpoint, params={"page": 1, "page_size": 200})
    past_end = dataset_client.get(endpoint, params={"page": 99, "page_size": 100})

    assert first.status_code == 200, first.text
    assert first.json()["data"]["dataset_id"] == dataset_id
    assert first.json()["data"]["version_id"] == version_id
    assert first.json()["data"]["columns"] == ["timestamp", "u1", "y"]
    assert first.json()["data"]["rows"][0]["u1"] == 0
    assert first.json()["data"]["rows"][-1]["u1"] == 99
    assert first.json()["data"]["page"] == {
        "page": 1,
        "page_size": 100,
        "total": 250,
        "total_pages": 3,
    }
    assert second.json()["data"]["rows"][0]["u1"] == 100
    assert second.json()["data"]["rows"][-1]["u1"] == 199
    assert len(last.json()["data"]["rows"]) == 50
    assert last.json()["data"]["rows"][0]["u1"] == 200
    assert len(fifty.json()["data"]["rows"]) == 50
    assert fifty.json()["data"]["rows"][0]["u1"] == 50
    assert len(two_hundred.json()["data"]["rows"]) == 200
    assert past_end.status_code == 200
    assert past_end.json()["data"]["rows"] == []
    assert dataset_client.get(endpoint, params={"page": 0, "page_size": 100}).status_code == 422
    assert dataset_client.get(endpoint, params={"page": 1, "page_size": 51}).status_code == 422

    lineage_after = dataset_client.get(f"/api/v1/datasets/{dataset_id}/versions").json()["data"]
    assert lineage_after == lineage_before
    assert _persistence_counts(dataset_client) == counts_before


def test_version_preview_is_bound_to_the_requested_immutable_version(
    dataset_client: TestClient, tmp_path: Path
) -> None:
    uploaded = _upload(dataset_client, _preview_csv(120))
    dataset = uploaded["dataset"]
    assert isinstance(dataset, dict)
    dataset_id = UUID(str(dataset["id"]))
    source_version_id = UUID(str(dataset["version_id"]))
    active_version_id = uuid4()
    active_relative_path = Path("derived") / str(dataset_id) / f"{active_version_id}.csv"
    active_path = tmp_path / active_relative_path
    active_path.parent.mkdir(parents=True, exist_ok=True)
    active_path.write_bytes(_preview_csv(120, value_offset=10_000))

    async def install_new_active_version() -> None:
        session_factory = dataset_client.app.state.dataset_test_session_factory
        async with session_factory() as session:
            dataset_record = await session.get(Dataset, dataset_id)
            source_version = await session.get(DatasetVersion, source_version_id)
            assert dataset_record is not None
            assert source_version is not None
            session.add(DatasetVersion(
                id=active_version_id,
                dataset_id=dataset_id,
                parent_version_id=source_version_id,
                version_index=source_version.version_index + 1,
                name="V1 · active isolation fixture",
                operation_name="test.preview_isolation",
                parameters=source_version.parameters,
                artifact_path=active_relative_path.as_posix(),
                sha256="0" * 64,
                row_count=120,
                column_count=3,
                time_range_start=source_version.time_range_start,
                time_range_end=source_version.time_range_end,
            ))
            dataset_record.active_version_id = active_version_id
            await session.commit()

    asyncio.run(install_new_active_version())
    lineage = dataset_client.get(f"/api/v1/datasets/{dataset_id}/versions").json()["data"]
    assert lineage["active_version_id"] == str(active_version_id)
    counts_before = _persistence_counts(dataset_client)

    response = dataset_client.get(
        f"/api/v1/datasets/{dataset_id}/versions/{source_version_id}/preview",
        params={"page": 1, "page_size": 50},
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["version_id"] == str(source_version_id)
    assert response.json()["data"]["rows"][0]["u1"] == 0
    assert dataset_client.get(f"/api/v1/datasets/{dataset_id}/versions").json()["data"] == lineage
    assert _persistence_counts(dataset_client) == counts_before


def test_version_preview_rejects_missing_and_cross_dataset_versions(
    dataset_client: TestClient,
) -> None:
    first = _upload(dataset_client, _preview_csv(3), name="first.csv")["dataset"]
    second = _upload(dataset_client, _preview_csv(4, value_offset=50), name="second.csv")["dataset"]
    assert isinstance(first, dict)
    assert isinstance(second, dict)

    mismatch = dataset_client.get(
        f"/api/v1/datasets/{first['id']}/versions/{second['version_id']}/preview"
    )
    missing_dataset = dataset_client.get(
        f"/api/v1/datasets/{uuid4()}/versions/{first['version_id']}/preview"
    )
    missing_version = dataset_client.get(
        f"/api/v1/datasets/{first['id']}/versions/{uuid4()}/preview"
    )

    assert mismatch.status_code == 404
    assert mismatch.json()["error"]["code"] == "DATASET_VERSION_NOT_FOUND"
    assert missing_dataset.status_code == 404
    assert missing_dataset.json()["error"]["code"] == "DATASET_NOT_FOUND"
    assert missing_version.status_code == 404
    assert missing_version.json()["error"]["code"] == "DATASET_VERSION_NOT_FOUND"


def test_streaming_csv_page_uses_logical_records(tmp_path: Path) -> None:
    path = tmp_path / "quoted.csv"
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.writer(target)
        writer.writerow(["timestamp", "note", "value"])
        writer.writerow(["2026-01-01 00:00:00", "first, quoted", "1"])
        writer.writerow(["2026-01-01 00:00:01", "second\nlogical record", "2"])
        writer.writerow(["2026-01-01 00:00:02", "third", "3"])

    page = load_csv_page(
        artifact_root=tmp_path,
        relative_path="quoted.csv",
        encoding="utf-8",
        delimiter=",",
        inferred_types={"timestamp": "datetime", "note": "string", "value": "integer"},
        offset=1,
        limit=1,
    )

    assert page.headers == ["timestamp", "note", "value"]
    assert page.rows == [{
        "timestamp": "2026-01-01T00:00:01+00:00",
        "note": "second\nlogical record",
        "value": 2,
    }]
