"""Persistent execution contracts for the Copilot chat endpoint."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import pytest
from algorithms.agent.compliance import verify_plan as verify_plan_core
from algorithms.agent.llm import NullProvider
from app.core.config import Settings
from app.core.db import get_session
from app.main import create_app
from app.models import Base
from app.models.agent_execution import AgentExecutionSession
from app.services import agent_service, agent_tool_adapter
from app.services.report_service import ReportDomainError
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload


@dataclass(frozen=True)
class ChatHarness:
    client: TestClient
    session_factory: async_sessionmaker[AsyncSession]


@pytest.fixture
def chat_harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ChatHarness]:
    """Run chat against isolated SQLite and an explicitly disabled LLM provider."""

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'agent_chat_execution.db'}")
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
        yield ChatHarness(client=client, session_factory=session_factory)
    asyncio.run(engine.dispose())


def _benchmark_version(client: TestClient) -> str:
    response = client.post(
        "/api/v1/simulation/generate",
        json={"scenario": "S2", "n_steps": 900, "seed": 81, "input_count": 2},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["version_id"]


async def _load_execution(
    factory: async_sessionmaker[AsyncSession], execution_id: UUID
) -> AgentExecutionSession:
    async with factory() as session:
        execution = await session.scalar(
            select(AgentExecutionSession)
            .where(AgentExecutionSession.id == execution_id)
            .options(selectinload(AgentExecutionSession.step_runs))
        )
        assert execution is not None
        return execution


async def _execution_count(factory: async_sessionmaker[AsyncSession]) -> int:
    async with factory() as session:
        return int(
            await session.scalar(select(func.count()).select_from(AgentExecutionSession)) or 0
        )


def test_executable_chat_persists_plan_steps_and_confirmation_gate(
    chat_harness: ChatHarness,
) -> None:
    version_id = _benchmark_version(chat_harness.client)

    response = chat_harness.client.post(
        "/api/v1/copilot/chat",
        json={
            "message": "提取高信噪比的动态数据，估计时滞，处理共线性，然后做 ARX 辨识",
            "active_version_id": version_id,
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    execution_id = UUID(data["execution_id"])
    execution = asyncio.run(_load_execution(chat_harness.session_factory, execution_id))
    assert str(execution.initial_version_id) == version_id
    assert str(execution.current_version_id) == version_id
    assert data["current_version_id"] == version_id
    assert data["workflow_status"] == "WAITING_CONFIRMATION"
    assert execution.workflow_status == "WAITING_CONFIRMATION"
    assert data["pending_confirmation_step_id"] == execution.pending_confirmation_step_id
    assert [step.step_id for step in execution.step_runs] == [
        step["step_id"] for step in data["plan"]["steps"]
    ]

    waiting_step_id = data["pending_confirmation_step_id"]
    by_step = {step.step_id: step for step in execution.step_runs}
    assert by_step[waiting_step_id].status == "WAITING_CONFIRMATION"
    assert by_step[waiting_step_id].confirmation_status == "PENDING"
    waiting_sequence = by_step[waiting_step_id].sequence
    assert all(
        step.status == "PENDING"
        for step in execution.step_runs
        if step.sequence > waiting_sequence
    )
    completed = next(run for run in data["step_runs"] if run["status"] == "completed")
    assert by_step[completed["step_id"]].result_payload["result"] == completed["result"]


def test_plan_only_chat_returns_no_execution_and_writes_no_execution_session(
    chat_harness: ChatHarness,
) -> None:
    response = chat_harness.client.post(
        "/api/v1/copilot/chat", json={"message": "清洗数据后做 ARX 辨识"}
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["execution_id"] is None
    assert data["workflow_status"] is None
    assert data["current_version_id"] is None
    assert data["pending_confirmation_step_id"] is None
    assert data["executed"] is False
    assert asyncio.run(_execution_count(chat_harness.session_factory)) == 0


def test_persistent_state_sync_never_dispatches_a_tool_twice(
    chat_harness: ChatHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    version_id = _benchmark_version(chat_harness.client)
    original_dispatch = agent_service._dispatch
    dispatch_count = 0

    def counted_dispatch(*args: object, **kwargs: object) -> tuple[str, dict[str, object]]:
        nonlocal dispatch_count
        dispatch_count += 1
        return original_dispatch(*args, **kwargs)  # type: ignore[arg-type]

    formal_dispatch = agent_service.execute_agent_tool

    async def counted_formal_dispatch(*args: object, **kwargs: object):
        nonlocal dispatch_count
        dispatch_count += 1
        return await formal_dispatch(*args, **kwargs)

    monkeypatch.setattr(agent_service, "execute_agent_tool", counted_formal_dispatch)
    monkeypatch.setattr(agent_service, "_dispatch", counted_dispatch)
    response = chat_harness.client.post(
        "/api/v1/copilot/chat",
        json={"message": "做动态区间优选", "active_version_id": version_id},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["execution_id"] is not None
    dispatched_runs = [run for run in data["step_runs"] if run["status"] == "completed"]
    assert dispatch_count == len(dispatched_runs)
    assert dispatch_count > 0


def test_compliance_rejection_does_not_create_execution(
    chat_harness: ChatHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    version_id = _benchmark_version(chat_harness.client)
    rejected = verify_plan_core(
        [
            {
                "step_id": "unsafe",
                "tool": "run_arbitrary_python",
                "depends_on": [],
                "parameters": {},
            }
        ]
    )
    assert rejected.passed is False
    monkeypatch.setattr(agent_service, "verify_plan", lambda *args, **kwargs: rejected)

    response = chat_harness.client.post(
        "/api/v1/copilot/chat",
        json={"message": "做动态区间优选", "active_version_id": version_id},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["compliance"]["passed"] is False
    assert data["execution_id"] is None
    assert asyncio.run(_execution_count(chat_harness.session_factory)) == 0


def test_failed_step_marks_persistent_execution_failed(
    chat_harness: ChatHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    version_id = _benchmark_version(chat_harness.client)

    def fail_first_step(*args: object, **kwargs: object):
        raise agent_service.AgentDomainError("SYNC_TEST_FAILURE", "deterministic state-sync failure")

    monkeypatch.setattr(agent_service, "_dispatch", fail_first_step)
    response = chat_harness.client.post(
        "/api/v1/copilot/chat",
        json={"message": "做动态区间优选", "active_version_id": version_id},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    execution = asyncio.run(
        _load_execution(chat_harness.session_factory, UUID(data["execution_id"]))
    )
    assert data["workflow_status"] == "FAILED"
    assert execution.workflow_status == "FAILED"
    assert execution.error_code == "SYNC_TEST_FAILURE"
    assert execution.step_runs[0].status == "FAILED"
    assert all(step.status == "PENDING" for step in execution.step_runs[1:])


def test_generate_report_completes_persisted_workflow(
    chat_harness: ChatHarness,
) -> None:
    version_id = _benchmark_version(chat_harness.client)
    response = chat_harness.client.post(
        "/api/v1/copilot/chat",
        json={"message": "清洗数据并生成报告", "active_version_id": version_id},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    execution = asyncio.run(
        _load_execution(chat_harness.session_factory, UUID(data["execution_id"]))
    )
    assert [step.tool_name for step in execution.step_runs] == [
        "profile_dataset",
        "detect_anomalies",
        "clean_data",
        "generate_report",
    ]
    assert all(step.status == "SUCCEEDED" for step in execution.step_runs)
    assert data["workflow_status"] == "SUCCEEDED"
    assert execution.workflow_status == "SUCCEEDED"
    assert execution.finished_at is not None
    assert execution.current_step_id is None

    report = execution.step_runs[-1]
    assert report.result_payload["report_id"]
    assert report.result_payload["artifact_uri"]
    assert report.result_payload["execution_id"] == str(execution.id)
    assert report.result_payload["title"] == "IndusOpt 数据质量分析与清洗报告"
    assert [section["key"] for section in report.result_payload["sections"]] == [
        "overview",
        "profile",
        "anomaly",
        "cleaning",
        "limitations",
    ]
    assert [
        section["title"].split("、", 1)[0]
        for section in report.result_payload["sections"]
    ] == ["一", "二", "三", "四", "五"]
    for forbidden in ("D-最优", "ARX", "Optuna", "模型评价"):
        assert forbidden not in report.result_payload["markdown"]
    assert all(
        binding["kind"] == "step" for binding in report.result_payload["bindings"]
    )
    assert report.result_payload["cited_runs"] == []
    assert report.processing_run_ids == [report.result_payload["report_id"]]

    snapshot = chat_harness.client.get(f"/api/v1/copilot/executions/{execution.id}")
    assert snapshot.status_code == 200, snapshot.text
    persisted_report = snapshot.json()["data"]["step_runs"][-1]
    assert persisted_report["status"] == "SUCCEEDED"
    assert (
        persisted_report["result_payload"]["report_id"]
        == report.result_payload["report_id"]
    )
    assert (
        persisted_report["result_payload"]["artifact_uri"]
        == report.result_payload["artifact_uri"]
    )


def test_generate_report_domain_failure_marks_execution_failed(
    chat_harness: ChatHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    version_id = _benchmark_version(chat_harness.client)

    async def fail_report(*args: object, **kwargs: object) -> object:
        raise ReportDomainError("REPORT_TEST_FAILURE", "deterministic report failure")

    monkeypatch.setattr(agent_tool_adapter, "generate_report", fail_report)
    response = chat_harness.client.post(
        "/api/v1/copilot/chat",
        json={"message": "生成报告", "active_version_id": version_id},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    execution = asyncio.run(
        _load_execution(chat_harness.session_factory, UUID(data["execution_id"]))
    )
    report = next(
        step for step in execution.step_runs if step.tool_name == "generate_report"
    )
    assert data["workflow_status"] == "FAILED"
    assert execution.workflow_status == "FAILED"
    assert execution.finished_at is not None
    assert report.status == "FAILED"
    assert report.error_code == "REPORT_TEST_FAILURE"
    assert report.error_message == "deterministic report failure"


def test_capability_registry_owns_report_and_export_without_deferred_steps() -> None:
    assert set(agent_service._TOOL_CAPABILITIES) == {
        "profile_dataset",
        "align_and_resample",
        "detect_anomalies",
        "clean_data",
        "detect_dynamic_segments",
        "estimate_delays",
        "apply_lag_compensation",
        "analyze_collinearity",
        "select_variables",
        "fit_arx",
        "evaluate_model",
        "optimize_pipeline",
        "generate_report",
        "export_dataset",
    }
    assert agent_service._TOOL_CAPABILITIES["generate_report"].mode == "FORMAL_EXECUTABLE"
    assert agent_service._TOOL_CAPABILITIES["export_dataset"].mode == "WAITING_CONFIRMATION"
    assert "generate_report" in agent_service._FORMAL_ADAPTER_TOOLS
    assert "export_dataset" in agent_service._FORMAL_ADAPTER_TOOLS
    assert not agent_service._DEFERRED_TOOLS


def _confirm(chat_harness: ChatHarness, data: dict[str, object]) -> object:
    step_id = str(data["pending_confirmation_step_id"])
    response = chat_harness.client.post(
        "/api/v1/copilot/confirm",
        json={
            "copilot_run_id": data["copilot_run_id"],
            "confirmation_id": step_id,
            "approved": True,
            "execution_id": data["execution_id"],
            "step_id": step_id,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_explicit_export_with_formal_selection_confirms_exports_and_closes(
    chat_harness: ChatHarness,
) -> None:
    version_id = _benchmark_version(chat_harness.client)
    response = chat_harness.client.post(
        "/api/v1/copilot/chat",
        json={
            "message": "做动态区间优选并导出优选数据集",
            "active_version_id": version_id,
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["workflow_status"] == "WAITING_CONFIRMATION"

    confirmed = _confirm(chat_harness, data)
    execution = asyncio.run(
        _load_execution(chat_harness.session_factory, UUID(str(data["execution_id"])))
    )
    export = next(step for step in execution.step_runs if step.tool_name == "export_dataset")
    assert confirmed["workflow_status"] == "SUCCEEDED"
    assert execution.workflow_status == "SUCCEEDED"
    assert export.status == "SUCCEEDED"
    assert export.result_payload["exported_rows"] > 0
    assert export.result_payload["exported_rows"] < export.result_payload["source_rows"]
    assert export.result_payload["csv_uri"]
    assert export.result_payload["manifest_uri"]
    replay = _confirm(chat_harness, data)
    assert replay == confirmed
    replayed = asyncio.run(_load_execution(chat_harness.session_factory, execution.id))
    replay_export = next(step for step in replayed.step_runs if step.tool_name == "export_dataset")
    assert replay_export.finished_at == export.finished_at
    assert replay_export.processing_run_ids == export.processing_run_ids
    assert replay_export.attempt_count == export.attempt_count


def test_explicit_export_without_selection_fails_terminally(
    chat_harness: ChatHarness,
) -> None:
    version_id = _benchmark_version(chat_harness.client)
    response = chat_harness.client.post(
        "/api/v1/copilot/chat",
        json={"message": "下载 CSV", "active_version_id": version_id},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["workflow_status"] == "WAITING_CONFIRMATION"

    confirmed = _confirm(chat_harness, data)
    execution = asyncio.run(
        _load_execution(chat_harness.session_factory, UUID(str(data["execution_id"])))
    )
    export = next(step for step in execution.step_runs if step.tool_name == "export_dataset")
    assert confirmed["workflow_status"] == "FAILED"
    assert execution.workflow_status == "FAILED"
    assert execution.finished_at is not None
    assert export.status == "FAILED"
    assert export.error_code == "EXPORT_NO_SELECTION"


def test_unexpected_formal_tool_exception_is_terminal(
    chat_harness: ChatHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    version_id = _benchmark_version(chat_harness.client)

    async def fail_unexpectedly(*args: object, **kwargs: object) -> object:
        raise RuntimeError("private diagnostic detail")

    monkeypatch.setattr(agent_service, "execute_agent_tool", fail_unexpectedly)
    response = chat_harness.client.post(
        "/api/v1/copilot/chat",
        json={"message": "生成报告", "active_version_id": version_id},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    execution = asyncio.run(
        _load_execution(chat_harness.session_factory, UUID(data["execution_id"]))
    )
    failed = next(step for step in execution.step_runs if step.status == "FAILED")
    assert data["workflow_status"] == "FAILED"
    assert execution.workflow_status == "FAILED"
    assert execution.finished_at is not None
    assert failed.error_code == "AGENT_UNEXPECTED_STEP_ERROR"
    assert "private diagnostic detail" not in failed.error_message


def test_cleaning_version_is_refreshed_before_following_segment(
    chat_harness: ChatHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    version_id = _benchmark_version(chat_harness.client)
    original = agent_tool_adapter.select_dynamic_segments
    observed_versions: list[UUID] = []

    async def capture_segment(*args: object, **kwargs: object) -> object:
        payload = kwargs["payload"]
        observed_versions.append(payload.version_id)
        return await original(*args, **kwargs)

    monkeypatch.setattr(agent_tool_adapter, "select_dynamic_segments", capture_segment)
    response = chat_harness.client.post(
        "/api/v1/copilot/chat",
        json={
            "message": "清洗数据后做动态区间优选",
            "active_version_id": version_id,
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    execution = asyncio.run(
        _load_execution(chat_harness.session_factory, UUID(data["execution_id"]))
    )
    cleaning = next(step for step in execution.step_runs if step.tool_name == "clean_data")
    assert cleaning.result_version_id is not None
    assert observed_versions == [cleaning.result_version_id]
    assert execution.current_version_id == cleaning.result_version_id
    assert execution.workflow_status == "SUCCEEDED"
