"""Route-level tests for the real cleaning pipeline and its derived version lineage."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import UUID

import pytest
from algorithms.cleaning.pipeline import CleaningPipeline
from app.core.config import Settings
from app.core.db import get_session
from app.main import create_app
from app.models import Base, DatasetVersion, ProcessingRun
from app.models.operation_log import OperationLog
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'cleaning.db'}")
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
    app.state.session_factory = session_factory
    app.dependency_overrides[get_session] = session_override
    with TestClient(app) as client:
        yield client
    asyncio.run(engine.dispose())


def build_csv(*, rows: int = 400, spike_at: int = 120, gap: tuple[int, int] = (200, 205)) -> bytes:
    """Regular 1 Hz series with one obvious spike and one short gap."""

    start = datetime(2026, 1, 1, tzinfo=UTC)
    lines = ["timestamp,u1,y"]
    for index in range(rows):
        stamp = (start + timedelta(seconds=index)).isoformat()
        u1 = 1.0 if index % 80 < 40 else -1.0
        y = 0.5 * u1 + 0.01 * index
        if index == spike_at:
            y += 50.0
        if gap[0] <= index < gap[1]:
            lines.append(f"{stamp},{u1},")
            continue
        lines.append(f"{stamp},{u1:.6f},{y:.6f}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def upload(client: TestClient, content: bytes) -> str:
    response = client.post(
        "/api/v1/datasets/upload",
        files={"file": ("plant.csv", content, "text/csv")},
        data={"name": "清洗测试"},
    )
    assert response.status_code == 202, response.text
    return response.json()["data"]["dataset"]["latest_version_id"]


class TestCleaningRoute:
    def test_canonical_default_cleaning_contract_creates_a_derived_version(
        self, client: TestClient
    ) -> None:
        version_id = upload(client, build_csv())

        response = client.post(
            "/api/v1/preprocessing/clean",
            json={
                "version_id": version_id,
                "target_sample_period_seconds": 1.0,
                "interpolation": "linear",
                "anomaly_detector": "hampel",
                "hampel_window": 5,
            },
        )

        assert response.status_code == 202, response.text
        assert response.json()["data"]["source_version_id"] == version_id

    def test_validation_failure_exposes_field_details_without_calling_cleaning_service(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source_version_id = upload(client, build_csv())
        dataset_id = client.get("/api/v1/datasets").json()["data"]["items"][0]["id"]
        before = client.get(f"/api/v1/datasets/{dataset_id}/versions").json()["data"]
        called = False

        async def cleaning_service_must_not_run(*args: object, **kwargs: object) -> None:
            nonlocal called
            called = True
            raise AssertionError("Pydantic validation must reject this request before service execution")

        monkeypatch.setattr(
            "app.api.routes.clean_dataset_version", cleaning_service_must_not_run
        )
        response = client.post(
            "/api/v1/preprocessing/clean",
            json={
                "dataset_id": dataset_id,
                "version_id": "V0_Original",
                "target_sample_period_seconds": 1.0,
                "interpolation": "linear",
                "anomaly_detector": "hampel",
                "hampel_window": 5,
            },
        )

        assert response.status_code == 422
        issues = response.json()["error"]["details"]["issues"]
        assert issues == [
            {
                "type": "uuid_parsing",
                "loc": ["body", "version_id"],
                "msg": "Input should be a valid UUID, invalid character: found `V` at 1",
                "input": "V0_Original",
                "ctx": {"error": "invalid character: found `V` at 1"},
            }
        ]
        assert called is False
        after = client.get(f"/api/v1/datasets/{dataset_id}/versions").json()["data"]
        assert after["active_version_id"] == source_version_id
        assert after["nodes"] == before["nodes"]

    def test_clean_creates_a_derived_version_and_reports_changes(self, client: TestClient) -> None:
        version_id = upload(client, build_csv())

        response = client.post(
            "/api/v1/preprocessing/clean",
            json={
                "version_id": version_id,
                "resample_period_s": 1.0,
                "interpolation": "linear",
                "anomaly_detector": "hampel",
                "anomaly_strategy": "local_median",
            },
        )
        assert response.status_code == 202, response.text
        data = response.json()["data"]

        assert data["source_version_id"] == version_id
        assert data["derived_version_id"] != version_id
        assert data["series"], "the response must carry the before/after series"

    def test_clean_series_projects_classified_indices_on_the_same_grid(
        self, client: TestClient
    ) -> None:
        version_id = upload(client, build_csv())
        response = client.post(
            "/api/v1/preprocessing/clean",
            json={
                "version_id": version_id,
                "target_sample_period_seconds": 1.0,
                "interpolation": "linear",
                "anomaly_detector": "hampel",
                "anomaly_strategy": "local_median",
                "hampel_window": 5,
                "smoothing": "moving_average",
                "smoothing_window": 5,
            },
        )
        assert response.status_code == 202, response.text
        data = response.json()["data"]
        assert any(item["column"] == data["primary_column"] for item in data["series"])
        primary = next(item for item in data["series"] if item["column"] == "y")

        assert primary["interpolation_changed_indices"]
        assert primary["outlier_replacement_indices"]
        assert primary["smoothing_changed_indices"]
        assert set(primary["interpolation_changed_indices"]) & set(primary["smoothing_changed_indices"])

        projected_length = len(primary["timestamps"])
        assert projected_length == len(primary["raw_series"]) == len(primary["cleaned_series"])
        classified = (
            primary["interpolation_changed_indices"]
            + primary["outlier_replacement_indices"]
            + primary["smoothing_changed_indices"]
        )
        assert all(0 <= index < projected_length for index in classified)
        assert set(classified).issubset(set(primary["replaced_indices"]))

    def test_first_zero_change_clean_certifies_stage_but_repeat_converges(
        self, client: TestClient
    ) -> None:
        raw_version_id = upload(
            client,
            build_csv(rows=120, spike_at=999, gap=(999, 999)),
        )
        request = {"anomaly_strategy": "keep", "smoothing": "none"}

        first = client.post(
            "/api/v1/preprocessing/clean",
            json={"version_id": raw_version_id, **request},
        )
        assert first.status_code == 202, first.text
        first_data = first.json()["data"]
        cleaning_version_id = first_data["effective_version_id"]
        assert first_data["created_new_version"] is True
        assert first_data["derived_version_id"] == cleaning_version_id
        assert first_data["new_version_id"] == cleaning_version_id
        assert first_data["no_op"] is True
        assert first_data["converged"] is True
        assert first_data["reused_existing_version"] is False
        assert first_data["total_cleaned_points"] == 0

        dataset_id = first_data["dataset_id"]
        before = client.get(f"/api/v1/datasets/{dataset_id}/versions").json()["data"]
        repeated = client.post(
            "/api/v1/preprocessing/clean",
            json={"version_id": cleaning_version_id, **request},
        )
        assert repeated.status_code == 202, repeated.text
        repeated_data = repeated.json()["data"]
        after = client.get(f"/api/v1/datasets/{dataset_id}/versions").json()["data"]

        assert repeated_data["created_new_version"] is False
        assert repeated_data["derived_version_id"] is None
        assert repeated_data["new_version_id"] is None
        assert repeated_data["effective_version_id"] == cleaning_version_id
        assert repeated_data["no_op"] is True
        assert repeated_data["converged"] is True
        assert repeated_data["reused_existing_version"] is False
        assert repeated_data["total_cleaned_points"] == 0
        assert len(after["nodes"]) == len(before["nodes"])
        assert after["nodes"] == before["nodes"]

        async def load_run() -> ProcessingRun:
            async with client.app.state.session_factory() as session:
                run = await session.get(
                    ProcessingRun,
                    UUID(repeated_data["processing_run_id"]),
                )
                assert run is not None
                return run

        run = asyncio.run(load_run())
        assert run.status == "succeeded"
        assert str(run.source_version_id) == cleaning_version_id
        assert run.result["created_new_version"] is False
        assert run.result["effective_version_id"] == cleaning_version_id
        assert run.result["no_op"] is True
        assert run.result["converged"] is True
        assert run.result["reused_existing_version"] is False

    def test_repeated_clean_with_real_value_changes_still_creates_version(
        self, client: TestClient
    ) -> None:
        raw_version_id = upload(
            client,
            build_csv(rows=120, spike_at=999, gap=(999, 999)),
        )
        first = client.post(
            "/api/v1/preprocessing/clean",
            json={
                "version_id": raw_version_id,
                "anomaly_strategy": "keep",
                "smoothing": "none",
            },
        )
        assert first.status_code == 202, first.text
        cleaning_version_id = first.json()["data"]["effective_version_id"]

        repeated = client.post(
            "/api/v1/preprocessing/clean",
            json={
                "version_id": cleaning_version_id,
                "anomaly_strategy": "keep",
                "smoothing": "moving_average",
                "smoothing_window": 5,
            },
        )
        assert repeated.status_code == 202, repeated.text
        data = repeated.json()["data"]

        assert data["created_new_version"] is True
        assert data["derived_version_id"] == data["effective_version_id"]
        assert data["effective_version_id"] != cleaning_version_id
        assert data["no_op"] is False
        assert data["summary"]["changes"]["smoothing_changes"] > 0

    def test_duplicate_timestamp_change_is_not_misclassified_as_no_op(
        self, client: TestClient
    ) -> None:
        content = build_csv(rows=120, spike_at=999, gap=(999, 999)).decode("utf-8")
        lines = content.splitlines()
        lines.insert(2, lines[1])
        source_version_id = upload(client, ("\n".join(lines) + "\n").encode("utf-8"))

        async def mark_source_as_cleaning() -> None:
            async with client.app.state.session_factory() as session:
                version = await session.get(DatasetVersion, UUID(source_version_id))
                assert version is not None
                version.operation_name = "preprocessing.clean"
                await session.commit()

        asyncio.run(mark_source_as_cleaning())
        response = client.post(
            "/api/v1/preprocessing/clean",
            json={"version_id": source_version_id, "anomaly_strategy": "keep"},
        )
        assert response.status_code == 202, response.text
        data = response.json()["data"]

        assert data["total_cleaned_points"] == 0
        assert data["summary"]["changes"]["duplicate_timestamps_processed"] == 1
        assert data["created_new_version"] is True
        assert data["no_op"] is False

    def test_derived_version_appears_in_the_lineage_dag(self, client: TestClient) -> None:
        version_id = upload(client, build_csv())
        cleaned = client.post(
            "/api/v1/preprocessing/clean",
            json={"version_id": version_id, "anomaly_strategy": "local_median"},
        )
        assert cleaned.status_code == 202, cleaned.text
        derived_id = cleaned.json()["data"]["derived_version_id"]
        dataset_id = cleaned.json()["data"]["dataset_id"]
        assert dataset_id is not None

        versions = client.get(f"/api/v1/datasets/{dataset_id}/versions")
        assert versions.status_code == 200, versions.text
        payload = versions.json()["data"]
        by_id = {node["id"]: node for node in payload["nodes"]}
        assert derived_id in by_id
        assert by_id[derived_id]["parent_version_id"] == version_id
        assert by_id[derived_id]["tool"] == "preprocessing.clean"
        parameters = by_id[derived_id]["parameters"]
        assert "constant_value_segment_count" in parameters
        assert "candidate_frozen_segment_count" in parameters
        assert "change_summary" in parameters
        assert "frozen_segment_count" not in parameters
        assert by_id[derived_id]["audit_summary"]["processing"]["count_unit"] == "cell"
        assert {"source": version_id, "target": derived_id} in [
            {"source": edge["source"], "target": edge["target"]} for edge in payload["edges"]
        ]

    def test_change_summary_separates_missing_outlier_and_other_operations(
        self, client: TestClient
    ) -> None:
        version_id = upload(client, build_csv())
        response = client.post(
            "/api/v1/preprocessing/clean",
            json={
                "version_id": version_id,
                "target_sample_period_seconds": 1.0,
                "interpolation": "linear",
                "anomaly_detector": "hampel",
                "hampel_window": 5,
            },
        )
        assert response.status_code == 202, response.text
        data = response.json()["data"]
        changes = data["summary"]["changes"]

        assert changes["count_unit"] == "cell"
        assert changes["unique_changed_cells"] == data["total_cleaned_points"]
        assert changes["missing_value_fills"] >= 5
        assert changes["outlier_replacements"] >= 1
        assert changes["smoothing_changes"] == 0
        assert changes["duplicate_timestamps_processed"] == 0
        assert changes["category_counts_may_overlap"] is True
        assert data["summary"]["outliers"]["repaired"] == changes["outlier_replacements"]

    def test_regular_holds_are_not_reported_as_many_candidate_freezes(
        self, client: TestClient
    ) -> None:
        version_id = upload(client, build_csv(rows=480, gap=(450, 450)))
        response = client.post(
            "/api/v1/preprocessing/clean",
            json={"version_id": version_id, "anomaly_strategy": "keep"},
        )
        assert response.status_code == 202, response.text
        data = response.json()["data"]
        assert all("冻结段" not in warning for warning in data["warnings"])

    def test_legacy_cleaning_metadata_is_enriched_for_display_without_rewrite(
        self, client: TestClient
    ) -> None:
        source_version_id = upload(client, build_csv())
        cleaned = client.post(
            "/api/v1/preprocessing/clean",
            json={"version_id": source_version_id, "anomaly_strategy": "keep"},
        )
        assert cleaned.status_code == 202, cleaned.text
        derived_id = cleaned.json()["data"]["derived_version_id"]
        dataset_id = cleaned.json()["data"]["dataset_id"]

        async def make_metadata_legacy() -> dict[str, object]:
            async with client.app.state.session_factory() as session:
                version = await session.get(DatasetVersion, UUID(derived_id))
                assert version is not None
                parameters = dict(version.parameters)
                old_count = int(parameters.pop("constant_value_segment_count"))
                parameters.pop("constant_value_segments")
                parameters.pop("candidate_frozen_segment_count")
                parameters.pop("candidate_frozen_segments")
                parameters.pop("change_summary")
                parameters["frozen_segment_count"] = old_count
                version.parameters = parameters
                await session.commit()
                return parameters

        stored_parameters = asyncio.run(make_metadata_legacy())
        lineage = client.get(f"/api/v1/datasets/{dataset_id}/versions")
        assert lineage.status_code == 200, lineage.text
        node = next(item for item in lineage.json()["data"]["nodes"] if item["id"] == derived_id)

        assert node["parameters"] == stored_parameters
        assert node["audit_summary"]["freeze"]["historical_constant_value_segment_count"] >= 1
        assert node["audit_summary"]["processing"]["count_unit"] == "cell"
        assert "change_summary" not in node["parameters"]

    def test_same_source_parameters_and_output_reuse_existing_child(
        self, client: TestClient
    ) -> None:
        version_id = upload(client, build_csv())
        request = {"version_id": version_id, "anomaly_strategy": "set_null"}
        first = client.post("/api/v1/preprocessing/clean", json=request)
        assert first.status_code == 202, first.text
        first_data = first.json()["data"]
        dataset_id = first_data["dataset_id"]
        existing_version_id = first_data["effective_version_id"]
        before = client.get(f"/api/v1/datasets/{dataset_id}/versions").json()["data"]
        derived_directory = client.app.state.session_factory.kw["bind"].url.database
        assert derived_directory is not None
        artifact_root = Path(derived_directory).parent
        artifacts_before = sorted(
            (artifact_root / "derived" / dataset_id).glob("*.csv")
        )

        repeated = client.post("/api/v1/preprocessing/clean", json=request)
        assert repeated.status_code == 202, repeated.text
        repeated_data = repeated.json()["data"]
        after = client.get(f"/api/v1/datasets/{dataset_id}/versions").json()["data"]
        artifacts_after = sorted((artifact_root / "derived" / dataset_id).glob("*.csv"))

        assert repeated_data["source_version_id"] == version_id
        assert repeated_data["effective_version_id"] == existing_version_id
        assert repeated_data["derived_version_id"] is None
        assert repeated_data["new_version_id"] is None
        assert repeated_data["created_new_version"] is False
        assert repeated_data["no_op"] is False
        assert repeated_data["converged"] is False
        assert repeated_data["reused_existing_version"] is True
        assert after["nodes"] == before["nodes"]
        assert artifacts_after == artifacts_before

        async def load_runs() -> list[ProcessingRun]:
            async with client.app.state.session_factory() as session:
                return list(
                    (
                        await session.scalars(
                            select(ProcessingRun)
                            .where(
                                ProcessingRun.source_version_id == UUID(version_id),
                                ProcessingRun.run_type == "preprocessing.clean",
                            )
                            .order_by(ProcessingRun.created_at)
                        )
                    ).all()
                )

        runs = asyncio.run(load_runs())
        assert len(runs) == 2
        assert runs[-1].status == "succeeded"
        assert runs[-1].result["effective_version_id"] == existing_version_id
        assert runs[-1].result["reused_existing_version"] is True

        async def load_latest_audit() -> dict[str, object]:
            async with client.app.state.session_factory() as session:
                audit = await session.scalar(
                    select(OperationLog)
                    .where(
                        OperationLog.event_type == "preprocessing.clean.completed",
                        OperationLog.subject_id == dataset_id,
                    )
                    .order_by(OperationLog.created_at.desc(), OperationLog.id.desc())
                )
                assert audit is not None
                return json.loads(audit.payload_json)

        audit_payload = asyncio.run(load_latest_audit())
        assert audit_payload["effective_version_id"] == existing_version_id
        assert audit_payload["created_new_version"] is False
        assert audit_payload["reused_existing_version"] is True

    def test_concurrent_identical_requests_share_one_effective_version(
        self, client: TestClient
    ) -> None:
        version_id = upload(client, build_csv())
        dataset_id = client.get("/api/v1/datasets").json()["data"]["items"][0]["id"]
        request = {"version_id": version_id, "anomaly_strategy": "set_null"}
        barrier = Barrier(2)

        def submit() -> Response:
            barrier.wait()
            return client.post("/api/v1/preprocessing/clean", json=request)

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda _: submit(), range(2)))

        assert all(response.status_code == 202 for response in responses)
        payloads = [response.json()["data"] for response in responses]
        effective_ids = {payload["effective_version_id"] for payload in payloads}
        assert len(effective_ids) == 1
        assert sorted(payload["created_new_version"] for payload in payloads) == [False, True]
        reused = next(payload for payload in payloads if payload["reused_existing_version"])
        assert reused["no_op"] is False
        assert reused["converged"] is False

        lineage = client.get(f"/api/v1/datasets/{dataset_id}/versions").json()["data"]
        cleaning_nodes = [
            node
            for node in lineage["nodes"]
            if node["parent_version_id"] == version_id
            and node["tool"] == "preprocessing.clean"
        ]
        assert len(cleaning_nodes) == 1

        async def count_runs() -> int:
            async with client.app.state.session_factory() as session:
                count = await session.scalar(
                    select(func.count())
                    .select_from(ProcessingRun)
                    .where(
                        ProcessingRun.source_version_id == UUID(version_id),
                        ProcessingRun.run_type == "preprocessing.clean",
                    )
                )
                return int(count or 0)

        assert asyncio.run(count_runs()) == 2

    def test_same_output_with_different_normalized_parameters_is_not_reused(
        self, client: TestClient
    ) -> None:
        version_id = upload(
            client,
            build_csv(rows=120, spike_at=999, gap=(999, 999)),
        )
        first = client.post(
            "/api/v1/preprocessing/clean",
            json={
                "version_id": version_id,
                "anomaly_strategy": "keep",
                "smoothing": "none",
                "hampel_window": 5,
            },
        )
        second = client.post(
            "/api/v1/preprocessing/clean",
            json={
                "version_id": version_id,
                "anomaly_strategy": "keep",
                "smoothing": "none",
                "hampel_window": 7,
            },
        )

        assert first.status_code == 202, first.text
        assert second.status_code == 202, second.text
        assert second.json()["data"]["created_new_version"] is True
        assert second.json()["data"]["reused_existing_version"] is False
        assert (
            second.json()["data"]["effective_version_id"]
            != first.json()["data"]["effective_version_id"]
        )

    def test_alias_requests_with_same_normalized_parameters_reuse_existing_child(
        self, client: TestClient
    ) -> None:
        version_id = upload(
            client,
            build_csv(rows=120, spike_at=999, gap=(999, 999)),
        )
        first = client.post(
            "/api/v1/preprocessing/clean",
            json={
                "version_id": version_id,
                "target_sample_period_seconds": 1.0,
                "interpolation": "forward_fill",
                "anomaly_detector": "z_score",
                "anomaly_strategy": "keep",
            },
        )
        second = client.post(
            "/api/v1/preprocessing/clean",
            json={
                "version_id": version_id,
                "resample_period_s": 1.0,
                "interpolation_method": "ffill",
                "outlier_method": "zscore",
                "anomaly_strategy": "keep",
            },
        )

        assert first.status_code == 202, first.text
        assert second.status_code == 202, second.text
        assert second.json()["data"]["reused_existing_version"] is True
        assert (
            second.json()["data"]["effective_version_id"]
            == first.json()["data"]["effective_version_id"]
        )

    def test_same_source_and_parameters_with_different_output_is_not_reused(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        version_id = upload(client, build_csv())
        request = {"version_id": version_id, "anomaly_strategy": "set_null"}
        first = client.post("/api/v1/preprocessing/clean", json=request)
        assert first.status_code == 202, first.text

        original_execute = CleaningPipeline.execute

        def execute_with_distinct_output(self: CleaningPipeline, context: object, parameters: object):
            result = original_execute(self, context, parameters)  # type: ignore[arg-type]
            column = next(iter(result.cleaned_numeric))
            values = {name: list(items) for name, items in result.values.items()}
            cleaned_numeric = {
                name: list(items) for name, items in result.cleaned_numeric.items()
            }
            current = cleaned_numeric[column][0]
            replacement = 0.125 if current is None else current + 0.125
            values[column][0] = replacement
            cleaned_numeric[column][0] = replacement
            return replace(result, values=values, cleaned_numeric=cleaned_numeric)

        monkeypatch.setattr(CleaningPipeline, "execute", execute_with_distinct_output)
        second = client.post("/api/v1/preprocessing/clean", json=request)

        assert second.status_code == 202, second.text
        data = second.json()["data"]
        assert data["created_new_version"] is True
        assert data["reused_existing_version"] is False
        assert data["effective_version_id"] != first.json()["data"]["effective_version_id"]

    def test_unknown_version_returns_404(self, client: TestClient) -> None:
        from uuid import uuid4

        response = client.post(
            "/api/v1/preprocessing/clean",
            json={"version_id": str(uuid4())},
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "DATASET_VERSION_NOT_FOUND"
