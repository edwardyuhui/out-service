"""Focused route tests for immutable Cleaning Version Compare."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from app.core.config import Settings
from app.core.db import get_session
from app.main import create_app
from app.models import Base, DatasetColumn, DatasetVersion
from app.services.dataset_csv import load_parsed_csv
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'compare.db'}")
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
    with TestClient(app) as test_client:
        yield test_client
    asyncio.run(engine.dispose())


def _csv(
    rows: list[tuple[str, str | None]],
    *,
    channel: str = "y",
    extra_header: str | None = None,
) -> bytes:
    headers = ["timestamp", channel]
    if extra_header is not None:
        headers.append(extra_header)
    lines = [",".join(headers)]
    for timestamp, value in rows:
        cells = [timestamp, "" if value is None else value]
        if extra_header is not None:
            cells.append("state")
        lines.append(",".join(cells))
    return ("\n".join(lines) + "\n").encode()


def _regular_csv(rows: int, *, offset: float = 0.0) -> bytes:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return _csv([
        ((start + timedelta(seconds=index)).isoformat(), str(index + offset))
        for index in range(rows)
    ])


def _upload(client: TestClient, content: bytes, *, name: str = "Compare") -> tuple[str, str]:
    response = client.post(
        "/api/v1/datasets/upload",
        files={"file": ("compare.csv", content, "text/csv")},
        data={"name": name},
    )
    assert response.status_code == 202, response.text
    dataset = response.json()["data"]["dataset"]
    return dataset["id"], dataset["latest_version_id"]


def _compare(
    client: TestClient,
    dataset_id: str,
    baseline_version_id: str,
    compare_version_id: str,
    *,
    channel: str = "y",
    max_points: int = 10_000,
):
    return client.get(
        f"/api/v1/datasets/{dataset_id}/cleaning-version-compare",
        params={
            "baseline_version_id": baseline_version_id,
            "compare_version_id": compare_version_id,
            "channel": channel,
            "max_points": max_points,
        },
    )


def _channels(
    client: TestClient,
    dataset_id: str,
    baseline_version_id: str,
    compare_version_id: str,
):
    return client.get(
        f"/api/v1/datasets/{dataset_id}/cleaning-version-compare/channels",
        params={
            "baseline_version_id": baseline_version_id,
            "compare_version_id": compare_version_id,
        },
    )


def _add_version(
    client: TestClient,
    artifact_root: Path,
    *,
    dataset_id: str,
    parent_version_id: str | None,
    content: bytes,
    operation_name: str = "preprocessing.clean",
    parameters: dict[str, object] | None = None,
) -> tuple[str, Path]:
    version_id = uuid4()
    relative_path = Path("derived") / dataset_id / f"{version_id}.csv"
    artifact_path = artifact_root / relative_path
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_bytes(content)
    parsed = load_parsed_csv(
        artifact_root=artifact_root,
        relative_path=relative_path.as_posix(),
        encoding="utf-8",
        delimiter=",",
    )

    async def persist() -> None:
        async with client.app.state.session_factory() as session:
            next_index = int(
                await session.scalar(
                    select(func.coalesce(func.max(DatasetVersion.version_index), -1)).where(
                        DatasetVersion.dataset_id == UUID(dataset_id)
                    )
                )
            ) + 1
            version = DatasetVersion(
                id=version_id,
                dataset_id=UUID(dataset_id),
                parent_version_id=(UUID(parent_version_id) if parent_version_id else None),
                version_index=next_index,
                name=f"V{next_index} · Fixture",
                operation_name=operation_name,
                parameters={
                    "csv_encoding": "utf-8",
                    "csv_delimiter": ",",
                    **(parameters or {}),
                },
                artifact_path=relative_path.as_posix(),
                sha256=hashlib.sha256(content).hexdigest(),
                row_count=len(parsed.rows),
                column_count=len(parsed.headers),
                time_range_start=min(parsed.timestamps),
                time_range_end=max(parsed.timestamps),
                created_at=datetime.now(UTC),
            )
            session.add(version)
            await session.flush()
            session.add_all([
                DatasetColumn(
                    id=uuid4(),
                    dataset_id=UUID(dataset_id),
                    version_id=version_id,
                    position=position,
                    name=header,
                    inferred_type=parsed.inferred_types[header],
                    role="timestamp" if header == parsed.timestamp_column else "output",
                    nullable=parsed.nullable[header],
                )
                for position, header in enumerate(parsed.headers)
            ])
            await session.commit()

    asyncio.run(persist())
    return str(version_id), artifact_path


def _clean(client: TestClient, version_id: str, **overrides: object) -> dict[str, object]:
    response = client.post(
        "/api/v1/preprocessing/clean",
        json={"version_id": version_id, "anomaly_strategy": "keep", **overrides},
    )
    assert response.status_code == 202, response.text
    return response.json()["data"]


def test_raw_to_direct_cleaning_returns_persisted_summary_and_version_metadata(
    client: TestClient,
) -> None:
    dataset_id, raw_id = _upload(client, _regular_csv(12))
    cleaned = _clean(client, raw_id)
    clean_id = str(cleaned["effective_version_id"])

    response = _compare(client, dataset_id, raw_id, clean_id)
    assert response.status_code == 200, response.text
    data = response.json()["data"]

    assert data["relation"] == "DIRECT_PARENT"
    assert data["direction"] == "BASELINE_TO_COMPARE"
    assert data["baseline"] == {
        **data["baseline"],
        "version_id": raw_id,
        "operation_name": "raw_upload",
    }
    assert data["compare"]["version_id"] == clean_id
    assert data["compare"]["operation_name"] == "preprocessing.clean"
    assert len(data["baseline"]["sha256"]) == 64
    assert data["direct_derivation_summary"]["evidence_source"] == "persisted"
    assert data["direct_derivation_summary"]["scope"] == "all_numeric_columns"
    assert data["generic_diff_summary"]["scope"] == "selected_channel"
    assert data["projection"]["diff_computed_before_projection"] is True


def test_cleaning_direct_child_and_multistep_ancestor_relations(client: TestClient) -> None:
    nonlinear = _csv([
        (f"2026-01-01T00:00:{index:02d}Z", str(index * index))
        for index in range(20)
    ])
    dataset_id, raw_id = _upload(client, nonlinear)
    first_id = str(_clean(client, raw_id)["effective_version_id"])
    second_id = str(
        _clean(
            client,
            first_id,
            smoothing="moving_average",
            smoothing_window=3,
        )["effective_version_id"]
    )

    direct = _compare(client, dataset_id, first_id, second_id).json()["data"]
    assert direct["relation"] == "DIRECT_PARENT"
    assert direct["direction"] == "BASELINE_TO_COMPARE"
    assert direct["direct_derivation_summary"]["evidence_source"] == "persisted"

    reverse = _compare(client, dataset_id, second_id, first_id).json()["data"]
    assert reverse["relation"] == "DIRECT_PARENT"
    assert reverse["direction"] == "COMPARE_TO_BASELINE"
    assert reverse["direct_derivation_summary"] is None

    ancestor = _compare(client, dataset_id, raw_id, second_id).json()["data"]
    assert ancestor["relation"] == "ANCESTOR_DESCENDANT"
    assert ancestor["direction"] == "BASELINE_TO_COMPARE"
    assert ancestor["direct_derivation_summary"] is None


def test_sibling_identical_artifacts_are_not_convergence(client: TestClient, tmp_path: Path) -> None:
    dataset_id, raw_id = _upload(client, _regular_csv(8))
    content = _regular_csv(8, offset=1)
    left_id, _ = _add_version(
        client, tmp_path, dataset_id=dataset_id, parent_version_id=raw_id, content=content
    )
    right_id, _ = _add_version(
        client, tmp_path, dataset_id=dataset_id, parent_version_id=raw_id, content=content
    )

    response = _compare(client, dataset_id, left_id, right_id)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["relation"] == "SIBLING"
    assert data["direction"] == "NONE"
    assert data["artifacts_identical"] is True
    assert data["generic_diff_summary"]["changed_values"] == 0
    assert data["generic_diff_summary"]["added_points"] == 0
    assert data["generic_diff_summary"]["removed_points"] == 0
    assert data["generic_diff_summary"]["ambiguous_timestamp_groups"] == 0
    assert data["direct_derivation_summary"] is None
    assert data["convergence_evidence"] == {"baseline": None, "compare": None}


def test_same_version_is_allowed_and_has_zero_generic_diff(client: TestClient) -> None:
    dataset_id, version_id = _upload(client, _regular_csv(7))
    data = _compare(client, dataset_id, version_id, version_id).json()["data"]

    assert data["relation"] == "SAME_VERSION"
    assert data["direction"] == "NONE"
    assert data["artifacts_identical"] is True
    assert data["difference_points"] == []
    assert data["generic_diff_summary"]["changed_values"] == 0
    assert data["generic_diff_summary"]["added_points"] == 0
    assert data["generic_diff_summary"]["removed_points"] == 0
    assert data["generic_diff_summary"]["ambiguous_timestamp_groups"] == 0
    assert data["direct_derivation_summary"] is None


def test_dataset_and_version_eligibility_hard_gates(client: TestClient, tmp_path: Path) -> None:
    dataset_id, raw_id = _upload(client, _regular_csv(5), name="first")
    other_dataset_id, other_id = _upload(
        client, _regular_csv(5, offset=0.25), name="second"
    )
    assert other_dataset_id != dataset_id

    wrong_dataset = _compare(client, dataset_id, raw_id, other_id)
    assert wrong_dataset.status_code == 404
    assert wrong_dataset.json()["error"]["code"] == "DATASET_VERSION_NOT_FOUND"

    missing = _compare(client, dataset_id, raw_id, str(uuid4()))
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "DATASET_VERSION_NOT_FOUND"

    missing_dataset = _compare(client, str(uuid4()), raw_id, raw_id)
    assert missing_dataset.status_code == 404
    assert missing_dataset.json()["error"]["code"] == "DATASET_NOT_FOUND"

    for operation in ("preprocessing.lag_compensation", "preprocessing.feature_selection"):
        ineligible_id, _ = _add_version(
            client,
            tmp_path,
            dataset_id=dataset_id,
            parent_version_id=raw_id,
            content=_regular_csv(5),
            operation_name=operation,
        )
        rejected = _compare(client, dataset_id, raw_id, ineligible_id)
        assert rejected.status_code == 422
        assert rejected.json()["error"]["code"] == "CLEANING_COMPARE_VERSION_INELIGIBLE"


def test_channel_must_exist_on_both_sides_and_be_numeric(client: TestClient, tmp_path: Path) -> None:
    dataset_id, raw_id = _upload(client, _regular_csv(4))
    x_only_id, _ = _add_version(
        client,
        tmp_path,
        dataset_id=dataset_id,
        parent_version_id=raw_id,
        content=_csv([("2026-01-01T00:00:00Z", "1")], channel="x"),
    )
    missing_compare = _compare(client, dataset_id, raw_id, x_only_id)
    assert missing_compare.status_code == 422
    assert missing_compare.json()["error"]["code"] == "CLEANING_COMPARE_CHANNEL_INVALID"

    x_dataset_id, x_raw_id = _upload(
        client,
        _csv([("2026-02-01T00:00:00Z", "1")], channel="x"),
        name="x-source",
    )
    y_only_id, _ = _add_version(
        client,
        tmp_path,
        dataset_id=x_dataset_id,
        parent_version_id=x_raw_id,
        content=_csv([("2026-02-01T00:00:00Z", "1")]),
    )
    missing_baseline = _compare(client, x_dataset_id, x_raw_id, y_only_id)
    assert missing_baseline.status_code == 422
    assert missing_baseline.json()["error"]["code"] == "CLEANING_COMPARE_CHANNEL_INVALID"

    string_content = (
        "timestamp,state\n2026-03-01T00:00:00Z,on\n2026-03-01T00:00:01Z,off\n"
    ).encode()
    string_dataset_id, string_id = _upload(client, string_content, name="string-source")
    non_numeric = _compare(
        client, string_dataset_id, string_id, string_id, channel="state"
    )
    assert non_numeric.status_code == 422
    assert non_numeric.json()["error"]["code"] == "CLEANING_COMPARE_CHANNEL_INVALID"

    timestamp = _compare(client, dataset_id, raw_id, raw_id, channel="timestamp")
    assert timestamp.status_code == 422
    assert timestamp.json()["error"]["code"] == "CLEANING_COMPARE_CHANNEL_INVALID"


@pytest.mark.parametrize(
    ("baseline_values", "compare_values", "baseline_duplicates", "compare_duplicates"),
    [
        (["1", "2"], ["1.5"], 1, 0),
        (["1"], ["1.5", "2"], 0, 1),
        (["1", "2"], ["1.5", "2.5"], 1, 1),
    ],
)
def test_duplicate_overlap_is_one_ambiguous_timestamp_group(
    client: TestClient,
    tmp_path: Path,
    baseline_values: list[str],
    compare_values: list[str],
    baseline_duplicates: int,
    compare_duplicates: int,
) -> None:
    timestamp = "2026-01-01T00:00:00Z"
    numeric_anchor = ("2026-01-01T00:00:01Z", "3")
    dataset_id, raw_id = _upload(
        client,
        _csv(
            [(timestamp, value) for value in baseline_values]
            + [numeric_anchor]
        ),
    )
    compare_id, _ = _add_version(
        client,
        tmp_path,
        dataset_id=dataset_id,
        parent_version_id=raw_id,
        content=_csv(
            [(timestamp, value) for value in compare_values]
            + [numeric_anchor]
        ),
    )

    data = _compare(client, dataset_id, raw_id, compare_id).json()["data"]
    summary = data["generic_diff_summary"]
    assert summary["ambiguous_timestamp_groups"] == 1
    assert summary["baseline_duplicate_occurrences"] == baseline_duplicates
    assert summary["compare_duplicate_occurrences"] == compare_duplicates
    assert summary["changed_values"] == 0
    assert summary["added_points"] == 0
    assert summary["removed_points"] == 0
    assert len(data["difference_points"]) == 1
    difference = data["difference_points"][0]
    assert difference["difference_kind"] == "AMBIGUOUS_ALIGNMENT"
    assert len(difference["baseline_occurrences"]) == len(baseline_values)
    assert len(difference["compare_occurrences"]) == len(compare_values)


def test_added_removed_and_duplicate_only_side_count_occurrences(
    client: TestClient, tmp_path: Path
) -> None:
    baseline_content = _csv([
        ("2026-01-01T00:00:00Z", "1"),
        ("2026-01-01T00:00:01Z", "2"),
        ("2026-01-01T00:00:01Z", "3"),
    ])
    compare_content = _csv([
        ("2026-01-01T00:00:00Z", "1"),
        ("2026-01-01T00:00:02Z", "4"),
        ("2026-01-01T00:00:02Z", "5"),
        ("2026-01-01T00:00:02Z", "6"),
    ])
    dataset_id, baseline_id = _upload(client, baseline_content)
    compare_id, _ = _add_version(
        client,
        tmp_path,
        dataset_id=dataset_id,
        parent_version_id=baseline_id,
        content=compare_content,
    )

    data = _compare(client, dataset_id, baseline_id, compare_id).json()["data"]
    summary = data["generic_diff_summary"]
    assert summary["unique_matched_timestamps"] == 1
    assert summary["unchanged_values"] == 1
    assert summary["removed_points"] == 2
    assert summary["added_points"] == 3
    assert summary["ambiguous_timestamp_groups"] == 0
    by_kind = {point["difference_kind"]: point for point in data["difference_points"]}
    assert len(by_kind["POINT_REMOVED"]["baseline_occurrences"]) == 2
    assert len(by_kind["POINT_ADDED"]["compare_occurrences"]) == 3


def test_exact_numeric_null_and_timezone_semantics(client: TestClient, tmp_path: Path) -> None:
    baseline_content = _csv([
        ("2026-01-01T00:00:00Z", "1"),
        ("2026-01-01T00:00:01Z", "1.0"),
        ("2026-01-01T00:00:02Z", None),
        ("2026-01-01T00:00:03Z", "3"),
        ("2026-01-01T00:00:04Z", None),
    ])
    compare_content = _csv([
        ("2026-01-01T08:00:00+08:00", "1.0"),
        ("2026-01-01T08:00:01+08:00", "1.00000001"),
        ("2026-01-01T08:00:02+08:00", "2"),
        ("2026-01-01T08:00:03+08:00", None),
        ("2026-01-01T08:00:04+08:00", None),
    ])
    dataset_id, baseline_id = _upload(client, baseline_content)
    compare_id, _ = _add_version(
        client,
        tmp_path,
        dataset_id=dataset_id,
        parent_version_id=baseline_id,
        content=compare_content,
    )

    data = _compare(client, dataset_id, baseline_id, compare_id).json()["data"]
    summary = data["generic_diff_summary"]
    assert summary["unique_matched_timestamps"] == 5
    assert summary["unchanged_values"] == 2
    assert summary["changed_values"] == 3
    assert summary["contains_null_transitions"] is True
    changed = [
        point for point in data["difference_points"]
        if point["difference_kind"] == "VALUE_CHANGED"
    ]
    assert len(changed) == 3
    tiny = next(point for point in changed if point["baseline_value"] == 1.0)
    assert tiny["compare_value"] == 1.00000001
    assert tiny["absolute_delta"] > 0
    null_transitions = [point for point in changed if point["absolute_delta"] is None]
    assert len(null_transitions) == 2


def test_direct_summary_replayed_then_falls_back_to_legacy_total(
    client: TestClient,
) -> None:
    dataset_id, raw_id = _upload(client, _regular_csv(10))
    clean_id = str(_clean(client, raw_id)["effective_version_id"])

    async def remove_summary(*, remove_resolved: bool) -> None:
        async with client.app.state.session_factory() as session:
            version = await session.get(DatasetVersion, UUID(clean_id))
            assert version is not None
            parameters = dict(version.parameters)
            parameters.pop("change_summary", None)
            if remove_resolved:
                parameters.pop("resolved_parameters", None)
            version.parameters = parameters
            await session.commit()

    asyncio.run(remove_summary(remove_resolved=False))
    replayed = _compare(client, dataset_id, raw_id, clean_id).json()["data"]
    assert replayed["direct_derivation_summary"]["evidence_source"] == "replayed"
    assert "missing_value_fills" in replayed["direct_derivation_summary"]["changes"]

    asyncio.run(remove_summary(remove_resolved=True))
    legacy = _compare(client, dataset_id, raw_id, clean_id).json()["data"]
    summary = legacy["direct_derivation_summary"]
    assert summary["evidence_source"] == "legacy_total_only"
    assert summary["changes"] == {
        "count_unit": "cell",
        "unique_changed_cells": 0,
        "breakdown_status": "not_recorded",
    }
    assert any("breakdown" in warning for warning in legacy["warnings"])


def test_convergence_evidence_requires_a_formal_zero_change_run(client: TestClient) -> None:
    dataset_id, raw_id = _upload(client, _regular_csv(10))
    clean_id = str(_clean(client, raw_id)["effective_version_id"])

    before = _compare(client, dataset_id, raw_id, clean_id).json()["data"]
    assert before["convergence_evidence"] == {"baseline": None, "compare": None}

    convergence = _clean(client, clean_id)
    assert convergence["converged"] is True
    assert convergence["created_new_version"] is False
    after = _compare(client, dataset_id, raw_id, clean_id).json()["data"]
    evidence = after["convergence_evidence"]["compare"]
    assert evidence["version_id"] == clean_id
    assert evidence["processing_run_id"] == convergence["processing_run_id"]
    assert evidence["no_op"] is True
    assert evidence["converged"] is True
    assert evidence["effective_version_id"] == clean_id
    assert evidence["unique_changed_cells"] == 0
    assert isinstance(evidence["parameters"], dict)


def test_full_diff_precedes_deterministic_visual_projection(
    client: TestClient, tmp_path: Path
) -> None:
    row_count = 1_500
    dataset_id, baseline_id = _upload(client, _regular_csv(row_count))
    compare_id, _ = _add_version(
        client,
        tmp_path,
        dataset_id=dataset_id,
        parent_version_id=baseline_id,
        content=_regular_csv(row_count, offset=0.5),
    )

    full = _compare(client, dataset_id, baseline_id, compare_id).json()["data"]
    assert full["baseline_series"]["projected"] is False
    assert full["baseline_series"]["returned_point_count"] == row_count
    assert full["projection"]["applied"] is False
    assert full["generic_diff_summary"]["changed_values"] == row_count

    projected = _compare(
        client,
        dataset_id,
        baseline_id,
        compare_id,
        max_points=25,
    ).json()["data"]
    assert projected["baseline_series"]["input_point_count"] == row_count
    assert projected["baseline_series"]["returned_point_count"] == 25
    assert projected["baseline_series"]["projected"] is True
    assert projected["compare_series"]["returned_point_count"] == 25
    assert len(projected["difference_points"]) == 25
    assert projected["difference_points_truncated"] is True
    assert projected["generic_diff_summary"]["changed_values"] == row_count
    assert projected["projection"] == {
        "applied": True,
        "max_points": 25,
        "strategy": "evenly_spaced_index_with_endpoints",
        "diff_computed_before_projection": True,
    }
    baseline_points = projected["baseline_series"]["points"]
    assert baseline_points[0]["occurrence_index"] == 0
    assert baseline_points[0]["timestamp"] < baseline_points[-1]["timestamp"]


def test_missing_and_tampered_artifacts_have_distinct_errors(
    client: TestClient, tmp_path: Path
) -> None:
    dataset_id, raw_id = _upload(client, _regular_csv(4))
    missing_id, missing_path = _add_version(
        client,
        tmp_path,
        dataset_id=dataset_id,
        parent_version_id=raw_id,
        content=_regular_csv(4, offset=1),
    )
    missing_path.unlink()
    missing = _compare(client, dataset_id, raw_id, missing_id)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "DATASET_ARTIFACT_MISSING"

    tampered_id, tampered_path = _add_version(
        client,
        tmp_path,
        dataset_id=dataset_id,
        parent_version_id=raw_id,
        content=_regular_csv(4, offset=2),
    )
    tampered_path.write_bytes(_regular_csv(4, offset=3))
    tampered = _compare(client, dataset_id, raw_id, tampered_id)
    assert tampered.status_code == 409
    assert tampered.json()["error"]["code"] == "DATASET_ARTIFACT_INTEGRITY_FAILED"


def test_channel_metadata_uses_artifacts_and_preserves_baseline_order(
    client: TestClient, tmp_path: Path
) -> None:
    baseline_content = (
        "timestamp,z,label,baseline_only,to_string,to_numeric,y\n"
        "2026-01-01T00:00:00Z,1,alpha,10,100,left,2.5\n"
        "2026-01-01T00:00:01Z,2,beta,11,101,right,3.5\n"
    ).encode()
    compare_content = (
        "timestamp,z,label,compare_only,to_string,to_numeric,y\n"
        "2026-01-01T00:00:00Z,1.5,alpha,20,left,100,2\n"
        "2026-01-01T00:00:01Z,2.5,beta,21,right,101,3\n"
    ).encode()
    dataset_id, baseline_id = _upload(client, baseline_content)
    compare_id, _ = _add_version(
        client,
        tmp_path,
        dataset_id=dataset_id,
        parent_version_id=baseline_id,
        content=compare_content,
    )

    response = _channels(client, dataset_id, baseline_id, compare_id)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["dataset_id"] == dataset_id
    assert data["baseline_version_id"] == baseline_id
    assert data["compare_version_id"] == compare_id
    assert data["channels"] == [
        {
            "name": "z",
            "baseline_inferred_type": "integer",
            "compare_inferred_type": "float",
            "unit": None,
        },
        {
            "name": "y",
            "baseline_inferred_type": "float",
            "compare_inferred_type": "integer",
            "unit": None,
        },
    ]
    assert data["warnings"] == []


def test_channel_metadata_supports_same_version_and_empty_intersection(
    client: TestClient, tmp_path: Path
) -> None:
    same_content = (
        "timestamp,state,pressure,count\n"
        "2026-01-01T00:00:00Z,on,1.5,2\n"
        "2026-01-01T00:00:01Z,off,2.5,3\n"
    ).encode()
    dataset_id, version_id = _upload(client, same_content)

    same = _channels(client, dataset_id, version_id, version_id)
    assert same.status_code == 200, same.text
    assert [channel["name"] for channel in same.json()["data"]["channels"]] == [
        "pressure",
        "count",
    ]

    compare_id, _ = _add_version(
        client,
        tmp_path,
        dataset_id=dataset_id,
        parent_version_id=version_id,
        content=(
            "timestamp,state,compare_only\n"
            "2026-01-01T00:00:00Z,on,10\n"
            "2026-01-01T00:00:01Z,off,11\n"
        ).encode(),
    )
    empty = _channels(client, dataset_id, version_id, compare_id)
    assert empty.status_code == 200, empty.text
    assert empty.json()["data"]["channels"] == []
    assert empty.json()["data"]["warnings"] == []


def test_channel_metadata_reuses_dataset_version_and_eligibility_gates(
    client: TestClient, tmp_path: Path
) -> None:
    dataset_id, raw_id = _upload(client, _regular_csv(4), name="channels-first")
    other_dataset_id, other_id = _upload(
        client, _regular_csv(4, offset=0.25), name="channels-second"
    )
    assert other_dataset_id != dataset_id

    wrong_dataset = _channels(client, dataset_id, raw_id, other_id)
    assert wrong_dataset.status_code == 404
    assert wrong_dataset.json()["error"]["code"] == "DATASET_VERSION_NOT_FOUND"

    missing = _channels(client, dataset_id, raw_id, str(uuid4()))
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "DATASET_VERSION_NOT_FOUND"

    missing_dataset = _channels(client, str(uuid4()), raw_id, raw_id)
    assert missing_dataset.status_code == 404
    assert missing_dataset.json()["error"]["code"] == "DATASET_NOT_FOUND"

    for operation in ("preprocessing.lag_compensation", "preprocessing.feature_selection"):
        ineligible_id, _ = _add_version(
            client,
            tmp_path,
            dataset_id=dataset_id,
            parent_version_id=raw_id,
            content=_regular_csv(4),
            operation_name=operation,
        )
        rejected = _channels(client, dataset_id, raw_id, ineligible_id)
        assert rejected.status_code == 422
        assert rejected.json()["error"]["code"] == "CLEANING_COMPARE_VERSION_INELIGIBLE"


def test_channel_metadata_preserves_matching_units_and_warns_on_mismatch(
    client: TestClient, tmp_path: Path
) -> None:
    content = (
        "timestamp,pressure,temperature,flow\n"
        "2026-01-01T00:00:00Z,100.5,20.1,4\n"
        "2026-01-01T00:00:01Z,101.5,20.2,5\n"
    ).encode()
    dataset_id, baseline_id = _upload(client, content)
    compare_id, _ = _add_version(
        client,
        tmp_path,
        dataset_id=dataset_id,
        parent_version_id=baseline_id,
        content=content,
    )

    async def set_units() -> None:
        async with client.app.state.session_factory() as session:
            columns = list(
                (
                    await session.scalars(
                        select(DatasetColumn).where(
                            DatasetColumn.version_id.in_(
                                {UUID(baseline_id), UUID(compare_id)}
                            )
                        )
                    )
                ).all()
            )
            for column in columns:
                if column.name == "pressure":
                    column.unit = "kPa"
                elif column.name == "temperature":
                    column.unit = "°C" if column.version_id == UUID(baseline_id) else "K"
            await session.commit()

    asyncio.run(set_units())
    response = _channels(client, dataset_id, baseline_id, compare_id)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    options = {channel["name"]: channel for channel in data["channels"]}
    assert options["pressure"]["unit"] == "kPa"
    assert options["temperature"]["unit"] is None
    assert options["flow"]["unit"] is None
    assert len(data["warnings"]) == 1
    assert "temperature" in data["warnings"][0]


def test_channel_metadata_reports_missing_and_tampered_artifacts(
    client: TestClient, tmp_path: Path
) -> None:
    dataset_id, raw_id = _upload(client, _regular_csv(4))
    missing_id, missing_path = _add_version(
        client,
        tmp_path,
        dataset_id=dataset_id,
        parent_version_id=raw_id,
        content=_regular_csv(4, offset=1),
    )
    missing_path.unlink()
    missing = _channels(client, dataset_id, raw_id, missing_id)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "DATASET_ARTIFACT_MISSING"

    tampered_id, tampered_path = _add_version(
        client,
        tmp_path,
        dataset_id=dataset_id,
        parent_version_id=raw_id,
        content=_regular_csv(4, offset=2),
    )
    tampered_path.write_bytes(_regular_csv(4, offset=3))
    tampered = _channels(client, dataset_id, raw_id, tampered_id)
    assert tampered.status_code == 409
    assert tampered.json()["error"]["code"] == "DATASET_ARTIFACT_INTEGRITY_FAILED"
