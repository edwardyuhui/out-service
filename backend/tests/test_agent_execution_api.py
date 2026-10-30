"""API contracts for persistent Agent confirmation state transitions."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from algorithms.agent.compliance import verify_plan
from app.core.config import Settings
from app.core.db import get_session
from app.main import create_app
from app.models import Base, Dataset, DatasetVersion
from app.models.agent_execution import AgentExecutionSession
from app.models.dataset import ProcessingRun
from app.schemas.copilot import ExecutionPlan, ExecutionPlanStep
from app.services.agent_execution_service import (
    create_execution,
    get_execution,
    mark_step_succeeded,
    start_step,
)
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload


@dataclass(frozen=True)
class ApiHarness:
    client: TestClient
    session_factory: async_sessionmaker[AsyncSession]


@pytest.fixture
def api_harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ApiHarness]:
    """Run the route against an isolated SQLite database."""

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'agent_execution_api.db'}")
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
        yield ApiHarness(client=client, session_factory=session_factory)
    asyncio.run(engine.dispose())


async def _seed_dataset_version(session: AsyncSession) -> tuple[UUID, UUID]:
    dataset_id = uuid4()
    version_id = uuid4()
    session.add_all(
        [
            Dataset(
                id=dataset_id,
                name="agent-execution-api-contract-dataset",
                raw_sha256="d" * 64,
                raw_path="agent-execution-api-contract.csv",
                byte_size=1,
            ),
            DatasetVersion(
                id=version_id,
                dataset_id=dataset_id,
                version_index=0,
                name="raw",
                operation_name="raw_upload",
                parameters={},
                artifact_path="raw.csv",
                sha256="e" * 64,
                row_count=1,
                column_count=1,
            ),
        ]
    )
    await session.commit()
    return dataset_id, version_id


def _plan(dataset_id: UUID) -> ExecutionPlan:
    return ExecutionPlan(
        goal="Confirm an export with an unavailable artifact and persist its failure.",
        dataset_id=dataset_id,
        steps=[
            ExecutionPlanStep(
                step_id="s1",
                tool="profile_dataset",
                depends_on=[],
                parameters={},
                requires_confirmation=False,
            ),
            ExecutionPlanStep(
                step_id="s2",
                tool="export_dataset",
                depends_on=["s1"],
                parameters={},
                requires_confirmation=True,
            ),
            ExecutionPlanStep(
                step_id="s3",
                tool="detect_dynamic_segments",
                depends_on=["s1"],
                parameters={},
                requires_confirmation=False,
            ),
        ],
    )


async def _create_waiting_execution(factory: async_sessionmaker[AsyncSession]) -> UUID:
    async with factory() as session:
        dataset_id, version_id = await _seed_dataset_version(session)
        plan = _plan(dataset_id)
        proof = verify_plan([step.model_dump() for step in plan.steps])
        assert proof.passed
        execution = await create_execution(
            session,
            dataset_id=dataset_id,
            initial_version_id=version_id,
            planner_source="rule_based",
            plan=plan,
            compliance_proof=proof,
        )
        execution_id = execution.id

    async with factory() as session:
        await start_step(session, execution_id=execution_id, step_id="s1")
    async with factory() as session:
        await mark_step_succeeded(session, execution_id=execution_id, step_id="s1")
    async with factory() as session:
        await start_step(session, execution_id=execution_id, step_id="s2")
    return execution_id


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


def _confirm_payload(execution_id: UUID, *, step_id: str, approved: bool) -> dict[str, object]:
    return {
        "copilot_run_id": str(execution_id),
        "confirmation_id": step_id,
        "execution_id": str(execution_id),
        "step_id": step_id,
        "approved": approved,
    }


def test_confirm_api_approves_waiting_execution(api_harness: ApiHarness) -> None:
    execution_id = asyncio.run(_create_waiting_execution(api_harness.session_factory))

    response = api_harness.client.post(
        "/api/v1/copilot/confirm", json=_confirm_payload(execution_id, step_id="s2", approved=True)
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["execution_id"] == str(execution_id)
    assert data["workflow_status"] == "FAILED"
    assert data["current_step_id"] == "s2"
    assert data["pending_confirmation_step_id"] is None
    assert data["step_id"] == "s2"
    assert data["step_status"] == "FAILED"
    assert data["confirmation_status"] == "APPROVED"


def test_confirm_api_rejects_waiting_execution(api_harness: ApiHarness) -> None:
    execution_id = asyncio.run(_create_waiting_execution(api_harness.session_factory))

    response = api_harness.client.post(
        "/api/v1/copilot/confirm", json=_confirm_payload(execution_id, step_id="s2", approved=False)
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["execution_id"] == str(execution_id)
    assert data["workflow_status"] == "CANCELLED"
    assert data["step_status"] == "CANCELLED"
    assert data["confirmation_status"] == "REJECTED"


def test_confirm_api_rejects_wrong_pending_step_without_mutation(api_harness: ApiHarness) -> None:
    execution_id = asyncio.run(_create_waiting_execution(api_harness.session_factory))

    response = api_harness.client.post(
        "/api/v1/copilot/confirm", json=_confirm_payload(execution_id, step_id="s3", approved=True)
    )

    assert response.status_code == 409, response.text
    execution = asyncio.run(_load_execution(api_harness.session_factory, execution_id))
    by_step = {step.step_id: step for step in execution.step_runs}
    assert execution.workflow_status == "WAITING_CONFIRMATION"
    assert execution.pending_confirmation_step_id == "s2"
    assert by_step["s2"].status == "WAITING_CONFIRMATION"
    assert by_step["s3"].status == "PENDING"


def test_confirm_api_duplicate_approve_is_idempotent(api_harness: ApiHarness) -> None:
    execution_id = asyncio.run(_create_waiting_execution(api_harness.session_factory))
    payload = _confirm_payload(execution_id, step_id="s2", approved=True)

    first = api_harness.client.post("/api/v1/copilot/confirm", json=payload)
    assert first.status_code == 200, first.text
    before_replay = asyncio.run(_load_execution(api_harness.session_factory, execution_id))
    second = api_harness.client.post("/api/v1/copilot/confirm", json=payload)

    assert second.status_code == 200, second.text
    after_replay = asyncio.run(_load_execution(api_harness.session_factory, execution_id))
    before_step = next(step for step in before_replay.step_runs if step.step_id == "s2")
    after_step = next(step for step in after_replay.step_runs if step.step_id == "s2")
    assert second.json()["data"]["step_status"] == "FAILED"
    assert after_step.attempt_count == before_step.attempt_count == 0
    assert after_step.started_at == before_step.started_at
    assert after_step.finished_at == before_step.finished_at
    assert second.json()["data"] == first.json()["data"]


def test_confirm_api_cannot_approve_cancelled_execution(api_harness: ApiHarness) -> None:
    execution_id = asyncio.run(_create_waiting_execution(api_harness.session_factory))
    rejected = api_harness.client.post(
        "/api/v1/copilot/confirm", json=_confirm_payload(execution_id, step_id="s2", approved=False)
    )
    assert rejected.status_code == 200, rejected.text

    response = api_harness.client.post(
        "/api/v1/copilot/confirm", json=_confirm_payload(execution_id, step_id="s2", approved=True)
    )

    assert response.status_code == 409, response.text


def test_confirm_api_approve_persists_export_failure(api_harness: ApiHarness) -> None:
    execution_id = asyncio.run(_create_waiting_execution(api_harness.session_factory))

    response = api_harness.client.post(
        "/api/v1/copilot/confirm", json=_confirm_payload(execution_id, step_id="s2", approved=True)
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["step_status"] == "FAILED"
    assert response.json()["data"]["step_status"] != "SUCCEEDED"


def test_confirm_api_approve_keeps_downstream_step_pending(api_harness: ApiHarness) -> None:
    execution_id = asyncio.run(_create_waiting_execution(api_harness.session_factory))

    response = api_harness.client.post(
        "/api/v1/copilot/confirm", json=_confirm_payload(execution_id, step_id="s2", approved=True)
    )

    assert response.status_code == 200, response.text
    execution = asyncio.run(_load_execution(api_harness.session_factory, execution_id))
    downstream = next(step for step in execution.step_runs if step.step_id == "s3")
    assert downstream.status == "PENDING"


def test_confirm_api_missing_execution_returns_client_error(api_harness: ApiHarness) -> None:
    response = api_harness.client.post(
        "/api/v1/copilot/confirm", json=_confirm_payload(uuid4(), step_id="s2", approved=True)
    )

    assert response.status_code == 409, response.text
    payload = response.json()
    assert payload["success"] is False

def _single_step_plan(dataset_id: UUID) -> ExecutionPlan:
    return ExecutionPlan(
        goal="Persist and recover a single Agent execution step.",
        dataset_id=dataset_id,
        steps=[
            ExecutionPlanStep(
                step_id="s1",
                tool="profile_dataset",
                depends_on=[],
                parameters={"scope": "dataset"},
                requires_confirmation=False,
            )
        ],
    )


async def _create_terminal_execution(
    factory: async_sessionmaker[AsyncSession], *, failed: bool
) -> tuple[UUID, UUID]:
    async with factory() as session:
        dataset_id, version_id = await _seed_dataset_version(session)
        plan = _single_step_plan(dataset_id)
        proof = verify_plan([step.model_dump() for step in plan.steps])
        assert proof.passed
        copilot_run_id = uuid4()
        execution = await create_execution(
            session,
            dataset_id=dataset_id,
            initial_version_id=version_id,
            planner_source="rule_based",
            plan=plan,
            compliance_proof=proof,
            copilot_run_id=copilot_run_id,
        )
        execution_id = execution.id

    async with factory() as session:
        await start_step(session, execution_id=execution_id, step_id="s1")
    async with factory() as session:
        if failed:
            from app.services.agent_execution_service import mark_step_failed

            await mark_step_failed(
                session,
                execution_id=execution_id,
                step_id="s1",
                error_code="SNAPSHOT_TEST_FAILURE",
                error_message="persisted failure for snapshot recovery",
            )
        else:
            await mark_step_succeeded(
                session,
                execution_id=execution_id,
                step_id="s1",
                result_payload={"model_id": "saved-model-001", "metrics": {"rmse": 0.12}},
                processing_run_ids=["processing-run-001"],
            )
    return execution_id, copilot_run_id


async def _snapshot_read_only_state(
    factory: async_sessionmaker[AsyncSession], execution_id: UUID
) -> tuple[str, tuple[tuple[str, str], ...], int, int]:
    async with factory() as session:
        execution = await get_execution(session, execution_id=execution_id)
        dataset_version_count = await session.scalar(select(func.count()).select_from(DatasetVersion))
        processing_run_count = await session.scalar(select(func.count()).select_from(ProcessingRun))
    return (
        execution.workflow_status,
        tuple((step.step_id, step.status) for step in execution.step_runs),
        int(dataset_version_count or 0),
        int(processing_run_count or 0),
    )


def test_snapshot_api_recovers_waiting_confirmation_and_is_read_only(
    api_harness: ApiHarness,
) -> None:
    execution_id = asyncio.run(_create_waiting_execution(api_harness.session_factory))
    copilot_run_id = uuid4()

    async def link_and_prepare_confirmation() -> None:
        async with api_harness.session_factory() as session:
            execution = await get_execution(session, execution_id=execution_id)
            execution.copilot_run_id = copilot_run_id
            step = next(item for item in execution.step_runs if item.step_id == "s2")
            step.input_payload = {
                **step.input_payload,
                "confirmation_payload": {"recommended": "persisted confirmation input"},
            }
            await session.commit()

    asyncio.run(link_and_prepare_confirmation())
    before = asyncio.run(_snapshot_read_only_state(api_harness.session_factory, execution_id))

    response = api_harness.client.get(f"/api/v1/copilot/executions/{execution_id}")

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["execution_id"] == str(execution_id)
    assert data["copilot_run_id"] == str(copilot_run_id)
    assert data["workflow_status"] == "WAITING_CONFIRMATION"
    assert data["pending_confirmation_step_id"] == "s2"
    assert data["plan"]["steps"][1]["step_id"] == "s2"
    by_step = {step["step_id"]: step for step in data["step_runs"]}
    assert by_step["s2"]["confirmation_status"] == "PENDING"
    assert by_step["s2"]["input_payload"]["confirmation_payload"] == {
        "recommended": "persisted confirmation input"
    }
    assert asyncio.run(_snapshot_read_only_state(api_harness.session_factory, execution_id)) == before


def test_snapshot_api_recovers_succeeded_result_payload(api_harness: ApiHarness) -> None:
    execution_id, copilot_run_id = asyncio.run(
        _create_terminal_execution(api_harness.session_factory, failed=False)
    )

    response = api_harness.client.get(f"/api/v1/copilot/executions/{execution_id}")

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["copilot_run_id"] == str(copilot_run_id)
    assert data["workflow_status"] == "SUCCEEDED"
    step = data["step_runs"][0]
    assert step["step_id"] == "s1"
    assert step["status"] == "SUCCEEDED"
    assert step["result_payload"] == {"model_id": "saved-model-001", "metrics": {"rmse": 0.12}}
    assert step["processing_run_ids"] == ["processing-run-001"]


def test_snapshot_api_recovers_failed_error(api_harness: ApiHarness) -> None:
    execution_id, _ = asyncio.run(
        _create_terminal_execution(api_harness.session_factory, failed=True)
    )

    response = api_harness.client.get(f"/api/v1/copilot/executions/{execution_id}")

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["workflow_status"] == "FAILED"
    assert data["error_code"] == "SNAPSHOT_TEST_FAILURE"
    assert data["error_message"] == "persisted failure for snapshot recovery"
    assert data["step_runs"][0]["status"] == "FAILED"
    assert data["step_runs"][0]["error_code"] == "SNAPSHOT_TEST_FAILURE"
    assert data["step_runs"][0]["error_message"] == "persisted failure for snapshot recovery"


def test_snapshot_api_returns_404_for_missing_execution(api_harness: ApiHarness) -> None:
    response = api_harness.client.get(f"/api/v1/copilot/executions/{uuid4()}")

    assert response.status_code == 404, response.text
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "AGENT_EXECUTION_NOT_FOUND"