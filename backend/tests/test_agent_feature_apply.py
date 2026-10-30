"""Controlled feature-selection contracts for persistent Agent executions."""

from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from algorithms.agent.llm import NullProvider
from algorithms.agent.planner import RuleBasedPlanner, parse_intent
from app.core.config import Settings
from app.core.db import get_session
from app.main import create_app
from app.models import Base, DatasetVersion, ProcessingRun
from app.models.agent_execution import AgentExecutionSession
from app.services import agent_service
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload


@dataclass(frozen=True)
class FeatureHarness:
    client: TestClient
    session_factory: async_sessionmaker[AsyncSession]
    artifact_root: Path


@pytest.fixture
def feature_harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[FeatureHarness]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'agent_feature_apply.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def session_override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    asyncio.run(prepare())
    monkeypatch.setattr("app.api.routes.get_settings", lambda: Settings(artifact_root=tmp_path))
    monkeypatch.setattr(agent_service, "_resolve_provider", lambda: NullProvider())
    app = create_app()
    app.dependency_overrides[get_session] = session_override
    with TestClient(app) as client:
        yield FeatureHarness(client=client, session_factory=session_factory, artifact_root=tmp_path)
    asyncio.run(engine.dispose())


def _correlated_csv() -> bytes:
    start = datetime(2026, 2, 1, tzinfo=UTC)
    rows = ["timestamp,u1,u2,u3,y"]
    for index in range(600):
        timestamp = (start + timedelta(seconds=index)).isoformat()
        u1 = ((index % 41) - 20) / 7
        u2 = 0.98 * u1 + ((index % 5) - 2) * 0.001
        u3 = ((index * 17) % 53 - 26) / 9
        y = 0.7 * u1 - 0.2 * u3 + 0.01 * (index % 3)
        rows.append(f"{timestamp},{u1:.8f},{u2:.8f},{u3:.8f},{y:.8f}")
    return ("\n".join(rows) + "\n").encode("utf-8")


def _independent_csv() -> bytes:
    start = datetime(2026, 2, 1, tzinfo=UTC)
    rows = ["timestamp,u1,u2,u3,y"]
    for index in range(600):
        timestamp = (start + timedelta(seconds=index)).isoformat()
        u1 = math.sin(2 * math.pi * index / 50)
        u2 = math.cos(2 * math.pi * index / 60)
        u3 = math.sin(2 * math.pi * index / 75)
        y = 0.7 * u1 - 0.2 * u2 + 0.3 * u3
        rows.append(f"{timestamp},{u1:.8f},{u2:.8f},{u3:.8f},{y:.8f}")
    return ("\n".join(rows) + "\n").encode("utf-8")


def _upload(feature_harness: FeatureHarness, csv: bytes | None = None) -> tuple[UUID, UUID]:
    response = feature_harness.client.post(
        "/api/v1/datasets/upload",
        files={"file": ("feature-selection.csv", csv if csv is not None else _correlated_csv(), "text/csv")},
        data={"name": "Agent Feature Selection"},
    )
    assert response.status_code == 202, response.text
    dataset = response.json()["data"]["dataset"]
    dataset_id = UUID(dataset["id"])
    version_id = UUID(dataset["latest_version_id"])
    configured = feature_harness.client.post(
        f"/api/v1/datasets/{dataset_id}/config",
        json={
            "columns": [
                {"name": "timestamp", "role": "time"},
                {"name": "u1", "role": "input"},
                {"name": "u2", "role": "input"},
                {"name": "u3", "role": "input"},
                {"name": "y", "role": "output"},
            ]
        },
    )
    assert configured.status_code == 200, configured.text
    lagged = feature_harness.client.post(
        "/api/v1/preprocessing/delay/apply",
        json={
            "dataset_id": str(dataset_id),
            "version_id": str(version_id),
            "lag_map": {"u1": 1, "u2": 1, "u3": 1},
            "user_confirmed": True,
            "recommendation_source": "manual",
            "evidence_summary": {"fixture": "shared_nonzero_alignment"},
        },
    )
    assert lagged.status_code == 201, lagged.text
    return dataset_id, UUID(lagged.json()["data"]["result_version_id"])


async def _load_execution(harness: FeatureHarness, execution_id: UUID) -> AgentExecutionSession:
    async with harness.session_factory() as session:
        execution = await session.scalar(
            select(AgentExecutionSession)
            .where(AgentExecutionSession.id == execution_id)
            .options(selectinload(AgentExecutionSession.step_runs))
        )
        assert execution is not None
        return execution


async def _version_artifact(harness: FeatureHarness, version_id: UUID) -> tuple[DatasetVersion, bytes]:
    async with harness.session_factory() as session:
        version = await session.get(DatasetVersion, version_id)
        assert version is not None
        return version, (harness.artifact_root / version.artifact_path).read_bytes()


async def _counts(harness: FeatureHarness, dataset_id: UUID) -> tuple[int, int]:
    async with harness.session_factory() as session:
        versions = int(
            await session.scalar(
                select(func.count())
                .select_from(DatasetVersion)
                .where(DatasetVersion.dataset_id == dataset_id)
            )
            or 0
        )
        feature_runs = int(
            await session.scalar(
                select(func.count())
                .select_from(ProcessingRun)
                .where(
                    ProcessingRun.dataset_id == dataset_id,
                    ProcessingRun.run_type == "preprocessing.feature_selection",
                )
            )
            or 0
        )
        return versions, feature_runs


def _chat_to_feature_confirmation(
    harness: FeatureHarness,
    *,
    csv: bytes | None = None,
) -> tuple[AgentExecutionSession, dict[str, str]]:
    dataset_id, source_version_id = _upload(harness, csv)
    response = harness.client.post(
        "/api/v1/copilot/chat",
        json={
            "message": "分析共线性、选择变量，然后做 ARX 辨识",
            "dataset_id": str(dataset_id),
            "active_version_id": str(source_version_id),
        },
    )
    assert response.status_code == 200, response.text
    execution = asyncio.run(_load_execution(harness, UUID(response.json()["data"]["execution_id"])))
    analyze = next(step for step in execution.step_runs if step.tool_name == "analyze_collinearity")
    apply = next(step for step in execution.step_runs if step.tool_name == "select_variables")
    assert analyze.status == "SUCCEEDED"
    assert analyze.source_version_id == source_version_id
    assert analyze.result_version_id is None
    assert analyze.processing_run_ids
    assert apply.status == "WAITING_CONFIRMATION"
    assert apply.confirmation_status == "PENDING"
    recommended = {
        item["variable"]: item["action"] for item in analyze.result_payload["recommendations"]
    }
    assert apply.input_payload["recommended_selection"] == recommended
    return execution, recommended


def _validate(
    harness: FeatureHarness,
    *,
    execution_id: UUID,
    step_id: str,
    drop_columns: list[str] | None = None,
):
    payload: dict[str, object] = {
        "execution_id": str(execution_id),
        "step_id": step_id,
    }
    if drop_columns is not None:
        payload["drop_columns"] = drop_columns
    return harness.client.post("/api/v1/copilot/feature-selection/validate", json=payload)


def _confirm(
    harness: FeatureHarness,
    *,
    execution_id: UUID,
    step_id: str,
    approved: bool = True,
    drop_columns: list[str] | None = None,
):
    payload: dict[str, object] = {
        "copilot_run_id": str(execution_id),
        "confirmation_id": step_id,
        "execution_id": str(execution_id),
        "step_id": step_id,
        "approved": approved,
    }
    if drop_columns is not None:
        payload["feature_drop_columns"] = drop_columns
    return harness.client.post("/api/v1/copilot/confirm", json=payload)


def test_planner_emits_confirmed_feature_apply_after_collinearity() -> None:
    steps, _, _ = RuleBasedPlanner().plan(parse_intent("分析共线性并选择变量"))
    by_tool = {step.tool: step for step in steps}
    apply = by_tool["select_variables"]
    assert apply.requires_confirmation is True
    assert apply.depends_on == (by_tool["analyze_collinearity"].step_id,)


def test_feature_recommendation_is_formal_and_validation_is_authoritative(
    feature_harness: FeatureHarness,
) -> None:
    execution, recommended = _chat_to_feature_confirmation(feature_harness)
    assert "drop" in recommended.values()
    apply = next(step for step in execution.step_runs if step.tool_name == "select_variables")
    accepted = _validate(
        feature_harness, execution_id=execution.id, step_id=apply.step_id
    )
    assert accepted.status_code == 200, accepted.text
    accepted_data = accepted.json()["data"]
    assert accepted_data["overall_status"] == "VALID"
    assert accepted_data["recommended_drop_columns"] == sorted(
        variable for variable, action in recommended.items() if action == "drop"
    )

    for invalid_columns in (["missing"], ["u1", "u1"], ["timestamp"], ["y"]):
        invalid = _validate(
            feature_harness,
            execution_id=execution.id,
            step_id=apply.step_id,
            drop_columns=list(invalid_columns),
        )
        assert invalid.status_code == 200, invalid.text
        assert invalid.json()["data"]["overall_status"] == "INVALID"


def test_recommendation_approve_creates_v3_once_and_resumes_to_arx_confirmation(
    feature_harness: FeatureHarness,
) -> None:
    execution, _ = _chat_to_feature_confirmation(feature_harness)
    apply = next(step for step in execution.step_runs if step.tool_name == "select_variables")
    source = execution.current_version_id
    _, source_bytes_before = asyncio.run(_version_artifact(feature_harness, source))
    before = asyncio.run(_counts(feature_harness, execution.dataset_id))

    first = _confirm(feature_harness, execution_id=execution.id, step_id=apply.step_id)
    assert first.status_code == 200, first.text
    data = first.json()["data"]
    assert data["step_status"] == "SUCCEEDED"
    assert data["confirmation_status"] == "APPROVED"
    result = UUID(data["result_version_id"])
    assert UUID(data["current_version_id"]) == result

    persisted = asyncio.run(_load_execution(feature_harness, execution.id))
    applied = next(step for step in persisted.step_runs if step.tool_name == "select_variables")
    downstream = next(step for step in persisted.step_runs if step.tool_name == "fit_arx")
    assert applied.source_version_id == source
    assert applied.result_version_id == result
    assert applied.processing_run_ids
    assert downstream.status == "WAITING_CONFIRMATION"
    assert downstream.input_payload["arx_structure_recommendation"]["source_version_id"] == str(
        result
    )
    result_node, _ = asyncio.run(_version_artifact(feature_harness, result))
    _, source_bytes_after = asyncio.run(_version_artifact(feature_harness, source))
    assert result_node.parent_version_id == source
    assert source_bytes_after == source_bytes_before

    after_first = asyncio.run(_counts(feature_harness, execution.dataset_id))
    assert after_first == (before[0] + 1, before[1] + 1)
    replay = _confirm(feature_harness, execution_id=execution.id, step_id=apply.step_id)
    assert replay.status_code == 200, replay.text
    assert replay.json()["data"]["result_version_id"] == str(result)
    assert asyncio.run(_counts(feature_harness, execution.dataset_id)) == after_first


def test_no_drop_recommendation_keeps_version_and_resumes_to_arx_confirmation(
    feature_harness: FeatureHarness,
) -> None:
    execution, recommended = _chat_to_feature_confirmation(
        feature_harness, csv=_independent_csv()
    )
    assert set(recommended.values()) == {"keep"}
    apply = next(step for step in execution.step_runs if step.tool_name == "select_variables")
    source = execution.current_version_id
    before = asyncio.run(_counts(feature_harness, execution.dataset_id))
    assert apply.input_payload["recommended_drop_columns"] == []

    validation = _validate(
        feature_harness, execution_id=execution.id, step_id=apply.step_id, drop_columns=[]
    )
    assert validation.status_code == 200, validation.text
    assert validation.json()["data"]["overall_status"] == "VALID"

    response = _confirm(
        feature_harness, execution_id=execution.id, step_id=apply.step_id, drop_columns=[]
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["step_status"] == "SUCCEEDED"
    assert data["confirmation_status"] == "APPROVED"
    assert data["result_version_id"] is None
    assert UUID(data["current_version_id"]) == source

    persisted = asyncio.run(_load_execution(feature_harness, execution.id))
    applied = next(step for step in persisted.step_runs if step.tool_name == "select_variables")
    downstream = next(step for step in persisted.step_runs if step.tool_name == "fit_arx")
    assert applied.source_version_id == source
    assert applied.result_version_id is None
    assert applied.processing_run_ids == []
    assert applied.input_payload["final_drop_columns"] == []
    assert applied.result_payload["data_changed"] is False
    assert applied.result_payload["summary"]["dropped_columns"] == []
    assert applied.result_payload["summary"]["kept_input_columns"] == ["u1", "u2", "u3"]
    assert "未创建新数据版本" in applied.result_payload["summary"]["reason"]
    assert downstream.status == "WAITING_CONFIRMATION"
    assert downstream.input_payload["arx_structure_recommendation"]["source_version_id"] == str(source)
    assert asyncio.run(_counts(feature_harness, execution.dataset_id)) == before

    replay = _confirm(
        feature_harness, execution_id=execution.id, step_id=apply.step_id, drop_columns=[]
    )
    assert replay.status_code == 200, replay.text
    assert asyncio.run(_counts(feature_harness, execution.dataset_id)) == before

    confirmed_fit = _confirm(
        feature_harness, execution_id=execution.id, step_id=downstream.step_id
    )
    assert confirmed_fit.status_code == 200, confirmed_fit.text
    completed = asyncio.run(_load_execution(feature_harness, execution.id))
    fitted = next(step for step in completed.step_runs if step.tool_name == "fit_arx")
    assert fitted.status == "SUCCEEDED"
    assert fitted.source_version_id == source


def test_manual_feature_adjustment_persists_final_selection_and_provenance(
    feature_harness: FeatureHarness,
) -> None:
    execution, recommended = _chat_to_feature_confirmation(feature_harness)
    apply = next(step for step in execution.step_runs if step.tool_name == "select_variables")
    recommended_drop = next(name for name, action in recommended.items() if action == "drop")
    correlated_keeper = next(
        name
        for name, action in recommended.items()
        if action == "keep" and name in {"u1", "u2"}
    )

    response = _confirm(
        feature_harness,
        execution_id=execution.id,
        step_id=apply.step_id,
        drop_columns=[correlated_keeper],
    )
    assert response.status_code == 200, response.text
    persisted = asyncio.run(_load_execution(feature_harness, execution.id))
    applied = next(step for step in persisted.step_runs if step.tool_name == "select_variables")
    assert applied.input_payload["recommended_drop_columns"] == [recommended_drop]
    assert applied.input_payload["manual_drop_columns"] == [correlated_keeper]
    assert applied.input_payload["final_drop_columns"] == [correlated_keeper]
    assert applied.input_payload["selection_sources"][correlated_keeper] == "manual_override"
    assert applied.input_payload["selection_sources"][recommended_drop] == "manual_override"
    assert applied.result_payload["summary"]["dropped_columns"] == [correlated_keeper]


def test_completed_feature_apply_rejects_a_different_selection_replay(
    feature_harness: FeatureHarness,
) -> None:
    execution, recommended = _chat_to_feature_confirmation(feature_harness)
    apply = next(step for step in execution.step_runs if step.tool_name == "select_variables")
    first = _confirm(feature_harness, execution_id=execution.id, step_id=apply.step_id)
    assert first.status_code == 200, first.text
    before = asyncio.run(_counts(feature_harness, execution.dataset_id))
    different = [name for name, action in recommended.items() if action == "keep" and name != "u3"]

    replay = _confirm(
        feature_harness,
        execution_id=execution.id,
        step_id=apply.step_id,
        drop_columns=different,
    )
    assert replay.status_code == 409, replay.text
    assert asyncio.run(_counts(feature_harness, execution.dataset_id)) == before


def test_reject_does_not_apply_features_or_create_v3(feature_harness: FeatureHarness) -> None:
    execution, _ = _chat_to_feature_confirmation(feature_harness)
    apply = next(step for step in execution.step_runs if step.tool_name == "select_variables")
    source = execution.current_version_id
    before = asyncio.run(_counts(feature_harness, execution.dataset_id))

    response = _confirm(
        feature_harness,
        execution_id=execution.id,
        step_id=apply.step_id,
        approved=False,
    )
    assert response.status_code == 200, response.text
    persisted = asyncio.run(_load_execution(feature_harness, execution.id))
    rejected = next(step for step in persisted.step_runs if step.tool_name == "select_variables")
    assert persisted.workflow_status == "CANCELLED"
    assert persisted.current_version_id == source
    assert rejected.status == "CANCELLED"
    assert rejected.confirmation_status == "REJECTED"
    assert asyncio.run(_counts(feature_harness, execution.dataset_id)) == before


def test_confirm_keep_all_preserves_version_and_resumes_modeling(feature_harness: FeatureHarness) -> None:
    execution, _ = _chat_to_feature_confirmation(feature_harness)
    apply = next(step for step in execution.step_runs if step.tool_name == "select_variables")
    source = execution.current_version_id
    before = asyncio.run(_counts(feature_harness, execution.dataset_id))
    _, source_bytes = asyncio.run(_version_artifact(feature_harness, source))
    response = _confirm(feature_harness, execution_id=execution.id, step_id=apply.step_id, drop_columns=[])
    assert response.status_code == 200, response.text
    result = response.json()["data"]
    assert result["step_status"] == "SUCCEEDED"
    assert result["result_version_id"] is None
    assert result["current_version_id"] == str(source)
    assert result["result_payload"]["operation_name"] == "feature_selection_noop"
    assert result["result_payload"]["summary"]["kept_input_columns"] == ["u1", "u2", "u3"]
    persisted = asyncio.run(_load_execution(feature_harness, execution.id))
    downstream = next(step for step in persisted.step_runs if step.tool_name == "fit_arx")
    assert downstream.status == "WAITING_CONFIRMATION"
    assert downstream.input_payload["arx_structure_recommendation"]["source_version_id"] == str(source)
    assert asyncio.run(_counts(feature_harness, execution.dataset_id)) == before
    assert asyncio.run(_version_artifact(feature_harness, source))[1] == source_bytes
    replay = _confirm(feature_harness, execution_id=execution.id, step_id=apply.step_id, drop_columns=[])
    assert replay.status_code == 200, replay.text
    assert replay.json()["data"]["result_payload"] == result["result_payload"]
    assert asyncio.run(_counts(feature_harness, execution.dataset_id)) == before
    conflict = _confirm(feature_harness, execution_id=execution.id, step_id=apply.step_id, drop_columns=["u1"])
    assert conflict.status_code == 409, conflict.text
    assert asyncio.run(_counts(feature_harness, execution.dataset_id)) == before
