"""Contracts for the persistent Agent execution state machine."""

from __future__ import annotations

import asyncio
import importlib
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from uuid import UUID, uuid4

import pytest
from algorithms.agent.compliance import ComplianceProof, verify_plan
from app.models import Base, Dataset, DatasetVersion
from app.models.agent_execution import AgentExecutionSession
from app.schemas.copilot import ExecutionPlan, ExecutionPlanStep
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload


@pytest.fixture
def execution_service() -> ModuleType:
    """Load the future service lazily so its absence is an intentional RED signal."""

    return importlib.import_module("app.services.agent_execution_service")


@pytest.fixture
def session_factory(tmp_path: Path) -> Iterator[async_sessionmaker[AsyncSession]]:
    """Use the repository's isolated async SQLite service-test pattern."""

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'agent_execution_service.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(prepare())
    yield factory
    asyncio.run(engine.dispose())


async def _seed_dataset_version(session: AsyncSession) -> tuple[UUID, UUID]:
    dataset_id = uuid4()
    version_id = uuid4()
    session.add_all(
        [
            Dataset(
                id=dataset_id,
                name="execution-service-contract-dataset",
                raw_sha256="d" * 64,
                raw_path="execution-service-contract.csv",
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


def _plan(*, dataset_id: UUID, include_confirmation: bool) -> tuple[ExecutionPlan, ComplianceProof]:
    steps = [
        ExecutionPlanStep(
            step_id="s1",
            tool="profile_dataset",
            depends_on=[],
            parameters={"snapshot": "original"},
            requires_confirmation=False,
        ),
    ]
    if include_confirmation:
        steps.extend(
            [
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
            ]
        )
    else:
        steps.append(
            ExecutionPlanStep(
                step_id="s2",
                tool="detect_dynamic_segments",
                depends_on=["s1"],
                parameters={},
                requires_confirmation=False,
            )
        )

    plan = ExecutionPlan(goal="execution service contract", dataset_id=dataset_id, steps=steps)
    proof = verify_plan([step.model_dump() for step in plan.steps])
    assert proof.passed, [check.detail for check in proof.failures]
    return plan, proof


def _non_topological_plan(
    *, dataset_id: UUID
) -> tuple[ExecutionPlan, ComplianceProof]:
    """A compliant plan whose declared dependency is not sequence-adjacent."""
    plan = ExecutionPlan(
        goal="Guard declared dependencies before dispatching a step.",
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
                tool="analyze_collinearity",
                depends_on=["s1", "s3"],
                parameters={},
                requires_confirmation=False,
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
    proof = verify_plan([step.model_dump() for step in plan.steps])
    assert proof.passed is True
    return plan, proof


async def _create_execution(
    service: ModuleType,
    factory: async_sessionmaker[AsyncSession],
    *,
    include_confirmation: bool,
) -> tuple[UUID, UUID, ExecutionPlan]:
    async with factory() as session:
        dataset_id, version_id = await _seed_dataset_version(session)
        plan, proof = _plan(dataset_id=dataset_id, include_confirmation=include_confirmation)
        execution = await service.create_execution(
            session,
            dataset_id=dataset_id,
            initial_version_id=version_id,
            planner_source="rule_based",
            plan=plan,
            compliance_proof=proof,
        )
        return execution.id, version_id, plan


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


async def _start_step(service: ModuleType, factory: async_sessionmaker[AsyncSession], execution_id: UUID, step_id: str) -> None:
    async with factory() as session:
        await service.start_step(session, execution_id=execution_id, step_id=step_id)


async def _succeed_step(
    service: ModuleType, factory: async_sessionmaker[AsyncSession], execution_id: UUID, step_id: str
) -> None:
    async with factory() as session:
        await service.mark_step_succeeded(session, execution_id=execution_id, step_id=step_id)


async def _wait_for_confirmation(
    service: ModuleType, factory: async_sessionmaker[AsyncSession]
) -> UUID:
    execution_id, _, _ = await _create_execution(service, factory, include_confirmation=True)
    await _start_step(service, factory, execution_id, "s1")
    await _succeed_step(service, factory, execution_id, "s1")
    await _start_step(service, factory, execution_id, "s2")
    return execution_id

def test_create_execution_snapshots_plan_and_initializes_version_pointer(
    execution_service: ModuleType, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async def exercise() -> AgentExecutionSession:
        execution_id, version_id, plan = await _create_execution(
            execution_service, session_factory, include_confirmation=False
        )
        plan.steps[0].parameters["snapshot"] = "mutated-after-create"
        execution = await _load_execution(session_factory, execution_id)
        assert execution.initial_version_id == version_id
        assert execution.current_version_id == version_id
        return execution

    execution = asyncio.run(exercise())
    assert execution.workflow_status == "PLANNED"
    assert execution.current_step_id is None
    assert execution.pending_confirmation_step_id is None
    assert execution.finished_at is None
    assert execution.plan_json["steps"][0]["parameters"]["snapshot"] == "original"


def test_create_execution_initializes_ordered_pending_step_runs(
    execution_service: ModuleType, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async def exercise() -> AgentExecutionSession:
        execution_id, _, _ = await _create_execution(
            execution_service, session_factory, include_confirmation=True
        )
        return await _load_execution(session_factory, execution_id)

    execution = asyncio.run(exercise())
    assert [(step.step_id, step.sequence) for step in execution.step_runs] == [
        ("s1", 1),
        ("s2", 2),
        ("s3", 3),
    ]
    assert all(step.status == "PENDING" and step.attempt_count == 0 for step in execution.step_runs)


def test_create_execution_sets_confirmation_status_from_step_semantics(
    execution_service: ModuleType, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async def exercise() -> AgentExecutionSession:
        execution_id, _, _ = await _create_execution(
            execution_service, session_factory, include_confirmation=True
        )
        return await _load_execution(session_factory, execution_id)

    by_step = {step.step_id: step for step in asyncio.run(exercise()).step_runs}
    assert by_step["s1"].requires_confirmation is False
    assert by_step["s1"].confirmation_status == "NOT_REQUIRED"
    assert by_step["s2"].requires_confirmation is True
    assert by_step["s2"].confirmation_status == "PENDING"


def test_starting_a_regular_step_transitions_execution_to_running(
    execution_service: ModuleType, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async def exercise() -> AgentExecutionSession:
        execution_id, _, _ = await _create_execution(
            execution_service, session_factory, include_confirmation=False
        )
        await _start_step(execution_service, session_factory, execution_id, "s1")
        return await _load_execution(session_factory, execution_id)

    execution = asyncio.run(exercise())
    step = execution.step_runs[0]
    assert execution.workflow_status == "RUNNING"
    assert execution.current_step_id == "s1"
    assert step.status == "RUNNING"
    assert step.started_at is not None


def test_start_step_requires_declared_dependencies_to_be_terminal(
    execution_service: ModuleType, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async def exercise() -> AgentExecutionSession:
        async with session_factory() as session:
            dataset_id, version_id = await _seed_dataset_version(session)
            plan, proof = _non_topological_plan(dataset_id=dataset_id)
            execution = await execution_service.create_execution(
                session,
                dataset_id=dataset_id,
                initial_version_id=version_id,
                planner_source="rule_based",
                plan=plan,
                compliance_proof=proof,
            )
            execution_id = execution.id

        await _start_step(execution_service, session_factory, execution_id, "s1")
        await _succeed_step(execution_service, session_factory, execution_id, "s1")

        async with session_factory() as session:
            with pytest.raises(execution_service.ExecutionStateError):
                await execution_service.start_step(session, execution_id=execution_id, step_id="s2")

        return await _load_execution(session_factory, execution_id)

    execution = asyncio.run(exercise())
    by_step = {step.step_id: step for step in execution.step_runs}
    assert by_step["s2"].status == "PENDING"
    assert by_step["s3"].status == "PENDING"
    assert execution.workflow_status == "RUNNING"
    assert execution.current_step_id is None
    assert execution.pending_confirmation_step_id is None
    assert execution.finished_at is None
def test_starting_a_confirmation_step_enters_waiting_confirmation(
    execution_service: ModuleType, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async def exercise() -> AgentExecutionSession:
        execution_id, _, _ = await _create_execution(
            execution_service, session_factory, include_confirmation=True
        )
        await _start_step(execution_service, session_factory, execution_id, "s1")
        await _succeed_step(execution_service, session_factory, execution_id, "s1")
        await _start_step(execution_service, session_factory, execution_id, "s2")
        return await _load_execution(session_factory, execution_id)

    execution = asyncio.run(exercise())
    step = next(step for step in execution.step_runs if step.step_id == "s2")
    assert step.status == "WAITING_CONFIRMATION"
    assert step.confirmation_status == "PENDING"
    assert execution.workflow_status == "WAITING_CONFIRMATION"
    assert execution.pending_confirmation_step_id == "s2"
    assert execution.current_step_id == "s2"
    assert execution.finished_at is None


def test_waiting_confirmation_keeps_later_steps_pending(
    execution_service: ModuleType, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async def exercise() -> AgentExecutionSession:
        execution_id, _, _ = await _create_execution(
            execution_service, session_factory, include_confirmation=True
        )
        await _start_step(execution_service, session_factory, execution_id, "s1")
        await _succeed_step(execution_service, session_factory, execution_id, "s1")
        await _start_step(execution_service, session_factory, execution_id, "s2")
        return await _load_execution(session_factory, execution_id)

    later_step = next(step for step in asyncio.run(exercise()).step_runs if step.step_id == "s3")
    assert later_step.status == "PENDING"


def test_succeeding_a_nonfinal_step_does_not_complete_the_workflow(
    execution_service: ModuleType, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async def exercise() -> AgentExecutionSession:
        execution_id, _, _ = await _create_execution(
            execution_service, session_factory, include_confirmation=False
        )
        await _start_step(execution_service, session_factory, execution_id, "s1")
        await _succeed_step(execution_service, session_factory, execution_id, "s1")
        return await _load_execution(session_factory, execution_id)

    execution = asyncio.run(exercise())
    first = next(step for step in execution.step_runs if step.step_id == "s1")
    assert first.status == "SUCCEEDED"
    assert first.finished_at is not None
    assert execution.workflow_status == "RUNNING"


def test_last_successful_step_completes_the_workflow(
    execution_service: ModuleType, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async def exercise() -> AgentExecutionSession:
        execution_id, _, _ = await _create_execution(
            execution_service, session_factory, include_confirmation=False
        )
        await _start_step(execution_service, session_factory, execution_id, "s1")
        await _succeed_step(execution_service, session_factory, execution_id, "s1")
        await _start_step(execution_service, session_factory, execution_id, "s2")
        await _succeed_step(execution_service, session_factory, execution_id, "s2")
        return await _load_execution(session_factory, execution_id)

    execution = asyncio.run(exercise())
    assert execution.workflow_status == "SUCCEEDED"
    assert execution.finished_at is not None
    assert execution.current_step_id is None
    assert execution.pending_confirmation_step_id is None


def test_failed_step_fails_workflow_and_leaves_later_steps_pending(
    execution_service: ModuleType, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async def exercise() -> AgentExecutionSession:
        execution_id, _, _ = await _create_execution(
            execution_service, session_factory, include_confirmation=True
        )
        await _start_step(execution_service, session_factory, execution_id, "s1")
        async with session_factory() as session:
            await execution_service.mark_step_failed(
                session,
                execution_id=execution_id,
                step_id="s1",
                error_code="TOOL_FAILED",
                error_message="deterministic test failure",
            )
        return await _load_execution(session_factory, execution_id)

    execution = asyncio.run(exercise())
    assert execution.workflow_status == "FAILED"
    assert execution.error_code == "TOOL_FAILED"
    assert execution.error_message == "deterministic test failure"
    assert execution.finished_at is not None
    assert next(step for step in execution.step_runs if step.step_id == "s3").status == "PENDING"


def test_rejecting_waiting_confirmation_cancels_workflow(
    execution_service: ModuleType, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async def exercise() -> AgentExecutionSession:
        execution_id, _, _ = await _create_execution(
            execution_service, session_factory, include_confirmation=True
        )
        await _start_step(execution_service, session_factory, execution_id, "s1")
        await _succeed_step(execution_service, session_factory, execution_id, "s1")
        await _start_step(execution_service, session_factory, execution_id, "s2")
        async with session_factory() as session:
            await execution_service.reject_step(session, execution_id=execution_id, step_id="s2")
        return await _load_execution(session_factory, execution_id)

    execution = asyncio.run(exercise())
    rejected = next(step for step in execution.step_runs if step.step_id == "s2")
    later = next(step for step in execution.step_runs if step.step_id == "s3")
    assert rejected.status == "CANCELLED"
    assert rejected.confirmation_status == "REJECTED"
    assert execution.workflow_status == "CANCELLED"
    assert execution.finished_at is not None
    assert later.status == "PENDING"


def test_succeeded_step_cannot_reenter_running(
    execution_service: ModuleType, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async def exercise() -> None:
        execution_id, _, _ = await _create_execution(
            execution_service, session_factory, include_confirmation=False
        )
        await _start_step(execution_service, session_factory, execution_id, "s1")
        await _succeed_step(execution_service, session_factory, execution_id, "s1")
        async with session_factory() as session:
            with pytest.raises(execution_service.ExecutionStateError):
                await execution_service.start_step(session, execution_id=execution_id, step_id="s1")

    asyncio.run(exercise())


def test_approving_waiting_step_resumes_it_as_running(
    execution_service: ModuleType, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async def exercise() -> AgentExecutionSession:
        execution_id = await _wait_for_confirmation(execution_service, session_factory)
        async with session_factory() as session:
            await execution_service.approve_step(session, execution_id=execution_id, step_id="s2")
        return await _load_execution(session_factory, execution_id)

    execution = asyncio.run(exercise())
    approved = next(step for step in execution.step_runs if step.step_id == "s2")
    assert approved.status == "RUNNING"
    assert approved.confirmation_status == "APPROVED"
    assert approved.started_at is not None
    assert execution.workflow_status == "RUNNING"
    assert execution.pending_confirmation_step_id is None
    assert execution.current_step_id == "s2"
    assert execution.finished_at is None


def test_approving_wrong_step_leaves_waiting_execution_unchanged(
    execution_service: ModuleType, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async def exercise() -> AgentExecutionSession:
        execution_id = await _wait_for_confirmation(execution_service, session_factory)
        async with session_factory() as session:
            with pytest.raises(execution_service.ExecutionStateError):
                await execution_service.approve_step(session, execution_id=execution_id, step_id="s3")
        return await _load_execution(session_factory, execution_id)

    execution = asyncio.run(exercise())
    by_step = {step.step_id: step for step in execution.step_runs}
    assert execution.workflow_status == "WAITING_CONFIRMATION"
    assert execution.pending_confirmation_step_id == "s2"
    assert execution.current_step_id == "s2"
    assert by_step["s2"].status == "WAITING_CONFIRMATION"
    assert by_step["s2"].confirmation_status == "PENDING"
    assert by_step["s3"].status == "PENDING"


def test_approving_nonwaiting_execution_is_rejected_without_mutation(
    execution_service: ModuleType, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async def exercise() -> AgentExecutionSession:
        execution_id, _, _ = await _create_execution(
            execution_service, session_factory, include_confirmation=True
        )
        await _start_step(execution_service, session_factory, execution_id, "s1")
        await _succeed_step(execution_service, session_factory, execution_id, "s1")
        async with session_factory() as session:
            with pytest.raises(execution_service.ExecutionStateError):
                await execution_service.approve_step(session, execution_id=execution_id, step_id="s2")
        return await _load_execution(session_factory, execution_id)

    execution = asyncio.run(exercise())
    by_step = {step.step_id: step for step in execution.step_runs}
    assert execution.workflow_status == "RUNNING"
    assert execution.current_step_id is None
    assert execution.pending_confirmation_step_id is None
    assert by_step["s2"].status == "PENDING"
    assert by_step["s2"].confirmation_status == "PENDING"


def test_approving_requires_waiting_step_state_not_only_pending_pointer(
    execution_service: ModuleType, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async def exercise() -> AgentExecutionSession:
        execution_id = await _wait_for_confirmation(execution_service, session_factory)
        async with session_factory() as session:
            execution = await session.scalar(
                select(AgentExecutionSession)
                .where(AgentExecutionSession.id == execution_id)
                .options(selectinload(AgentExecutionSession.step_runs))
            )
            assert execution is not None
            step = next(item for item in execution.step_runs if item.step_id == "s2")
            step.status = "PENDING"
            await session.commit()

        async with session_factory() as session:
            with pytest.raises(execution_service.ExecutionStateError):
                await execution_service.approve_step(session, execution_id=execution_id, step_id="s2")
        return await _load_execution(session_factory, execution_id)

    execution = asyncio.run(exercise())
    step = next(item for item in execution.step_runs if item.step_id == "s2")
    assert execution.workflow_status == "WAITING_CONFIRMATION"
    assert execution.pending_confirmation_step_id == "s2"
    assert step.status == "PENDING"
    assert step.confirmation_status == "PENDING"


def test_duplicate_approve_is_idempotent_after_the_first_approval(
    execution_service: ModuleType, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async def exercise() -> tuple[AgentExecutionSession, AgentExecutionSession]:
        execution_id = await _wait_for_confirmation(execution_service, session_factory)
        async with session_factory() as session:
            await execution_service.approve_step(session, execution_id=execution_id, step_id="s2")
        first = await _load_execution(session_factory, execution_id)
        async with session_factory() as session:
            await execution_service.approve_step(session, execution_id=execution_id, step_id="s2")
        second = await _load_execution(session_factory, execution_id)
        return first, second

    first, second = asyncio.run(exercise())
    first_step = next(item for item in first.step_runs if item.step_id == "s2")
    second_step = next(item for item in second.step_runs if item.step_id == "s2")
    assert second.workflow_status == "RUNNING"
    assert second.current_step_id == "s2"
    assert second.pending_confirmation_step_id is None
    assert second_step.status == "RUNNING"
    assert second_step.confirmation_status == "APPROVED"
    assert second_step.attempt_count == first_step.attempt_count == 0
    assert second_step.started_at == first_step.started_at


def test_rejected_confirmation_cannot_be_approved_later(
    execution_service: ModuleType, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async def exercise() -> AgentExecutionSession:
        execution_id = await _wait_for_confirmation(execution_service, session_factory)
        async with session_factory() as session:
            await execution_service.reject_step(session, execution_id=execution_id, step_id="s2")
        async with session_factory() as session:
            with pytest.raises(execution_service.ExecutionStateError):
                await execution_service.approve_step(session, execution_id=execution_id, step_id="s2")
        return await _load_execution(session_factory, execution_id)

    execution = asyncio.run(exercise())
    step = next(item for item in execution.step_runs if item.step_id == "s2")
    assert execution.workflow_status == "CANCELLED"
    assert step.status == "CANCELLED"
    assert step.confirmation_status == "REJECTED"


def test_approve_only_allows_execution_and_keeps_downstream_pending(
    execution_service: ModuleType, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async def exercise() -> AgentExecutionSession:
        execution_id = await _wait_for_confirmation(execution_service, session_factory)
        async with session_factory() as session:
            await execution_service.approve_step(session, execution_id=execution_id, step_id="s2")
        return await _load_execution(session_factory, execution_id)

    execution = asyncio.run(exercise())
    by_step = {step.step_id: step for step in execution.step_runs}
    assert by_step["s2"].status == "RUNNING"
    assert by_step["s2"].status != "SUCCEEDED"
    assert by_step["s3"].status == "PENDING"
