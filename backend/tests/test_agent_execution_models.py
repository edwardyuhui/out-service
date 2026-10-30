"""RED contracts for the persistent Agent execution workflow models.

The production models are deliberately absent during this TDD step.  Each test
loads them lazily so the resulting RED failure identifies the missing model
contract rather than the Python test environment.
"""

from __future__ import annotations

import asyncio
import importlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.models import Base, Dataset, DatasetVersion
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

WORKFLOW_PLANNED = "PLANNED"
STEP_PENDING = "PENDING"


@pytest.fixture
def execution_models() -> tuple[type[Any], type[Any]]:
    """Load the future models lazily so model absence is an intentional RED signal."""

    module = importlib.import_module("app.models.agent_execution")
    return module.AgentExecutionSession, module.AgentStepRun


@pytest.fixture
def session_factory(
    tmp_path: Path, execution_models: tuple[type[Any], type[Any]]
) -> Iterator[async_sessionmaker[AsyncSession]]:
    """Follow the repository's async SQLite model-test pattern."""

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'agent_execution.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(prepare())
    yield factory
    asyncio.run(engine.dispose())


async def _seed_versions(session: AsyncSession) -> tuple[UUID, UUID, UUID]:
    dataset_id = uuid4()
    initial_version_id = uuid4()
    current_version_id = uuid4()
    dataset = Dataset(
        id=dataset_id,
        name="agent-contract-dataset",
        raw_sha256="a" * 64,
        raw_path="agent-contract.csv",
        byte_size=1,
    )
    initial_version = DatasetVersion(
        id=initial_version_id,
        dataset_id=dataset_id,
        version_index=0,
        name="raw",
        operation_name="raw_upload",
        parameters={},
        artifact_path="raw.csv",
        sha256="b" * 64,
        row_count=1,
        column_count=1,
    )
    current_version = DatasetVersion(
        id=current_version_id,
        dataset_id=dataset_id,
        parent_version_id=initial_version_id,
        version_index=2,
        name="derived",
        operation_name="feature_apply",
        parameters={},
        artifact_path="derived.csv",
        sha256="c" * 64,
        row_count=1,
        column_count=1,
    )
    session.add_all([dataset, initial_version, current_version])
    await session.flush()
    return dataset_id, initial_version_id, current_version_id


def _new_execution(
    execution_type: type[Any],
    *,
    dataset_id: UUID,
    initial_version_id: UUID,
    current_version_id: UUID,
) -> Any:
    return execution_type(
        id=uuid4(),
        dataset_id=dataset_id,
        initial_version_id=initial_version_id,
        current_version_id=current_version_id,
        planner_source="rule_based",
        plan_json={"steps": []},
        workflow_status=WORKFLOW_PLANNED,
        artifacts={},
    )


def _new_step(
    step_type: type[Any],
    *,
    execution_id: UUID,
    step_id: str,
    sequence: int,
    source_version_id: UUID,
    result_version_id: UUID | None = None,
) -> Any:
    return step_type(
        id=uuid4(),
        execution_id=execution_id,
        step_id=step_id,
        sequence=sequence,
        tool_name="profile_dataset",
        status=STEP_PENDING,
        requires_confirmation=False,
        confirmation_status="NOT_REQUIRED",
        attempt_count=0,
        source_version_id=source_version_id,
        result_version_id=result_version_id,
        input_payload={"inputs": ["u1"]},
        result_payload={},
        processing_run_ids=[],
    )


def test_execution_session_minimum_field_contract(
    execution_models: tuple[type[Any], type[Any]],
) -> None:
    execution_type, _ = execution_models
    columns = set(execution_type.__table__.columns.keys())

    assert {
        "id",
        "dataset_id",
        "initial_version_id",
        "current_version_id",
        "planner_source",
        "plan_json",
        "workflow_status",
        "current_step_id",
        "pending_confirmation_step_id",
        "artifacts",
        "error_code",
        "error_message",
        "created_at",
        "updated_at",
        "finished_at",
    } <= columns
    assert "pending_confirmation_payload" not in columns

    execution = _new_execution(
        execution_type,
        dataset_id=uuid4(),
        initial_version_id=uuid4(),
        current_version_id=uuid4(),
    )
    assert execution.workflow_status == WORKFLOW_PLANNED
    assert execution.pending_confirmation_step_id is None
    assert execution.finished_at is None


def test_step_run_minimum_field_contract(
    execution_models: tuple[type[Any], type[Any]],
) -> None:
    _, step_type = execution_models
    columns = set(step_type.__table__.columns.keys())

    assert {
        "id",
        "execution_id",
        "step_id",
        "sequence",
        "tool_name",
        "status",
        "requires_confirmation",
        "confirmation_status",
        "attempt_count",
        "source_version_id",
        "result_version_id",
        "input_payload",
        "result_payload",
        "processing_run_ids",
        "error_code",
        "error_message",
        "started_at",
        "finished_at",
    } <= columns

    step = _new_step(
        step_type,
        execution_id=uuid4(),
        step_id="s1",
        sequence=1,
        source_version_id=uuid4(),
    )
    assert step.status == STEP_PENDING
    assert step.requires_confirmation is False
    assert step.result_version_id is None


def test_execution_exposes_ordered_step_runs(
    execution_models: tuple[type[Any], type[Any]],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    execution_type, step_type = execution_models

    async def exercise() -> list[str]:
        async with session_factory() as session:
            dataset_id, initial_version_id, current_version_id = await _seed_versions(session)
            execution = _new_execution(
                execution_type,
                dataset_id=dataset_id,
                initial_version_id=initial_version_id,
                current_version_id=current_version_id,
            )
            session.add(execution)
            session.add_all(
                [
                    _new_step(
                        step_type,
                        execution_id=execution.id,
                        step_id="s3",
                        sequence=3,
                        source_version_id=current_version_id,
                    ),
                    _new_step(
                        step_type,
                        execution_id=execution.id,
                        step_id="s1",
                        sequence=1,
                        source_version_id=initial_version_id,
                    ),
                    _new_step(
                        step_type,
                        execution_id=execution.id,
                        step_id="s2",
                        sequence=2,
                        source_version_id=current_version_id,
                    ),
                ]
            )
            await session.commit()

            loaded = await session.scalar(
                select(execution_type)
                .where(execution_type.id == execution.id)
                .options(selectinload(execution_type.step_runs))
            )
            assert loaded is not None
            return [step.step_id for step in loaded.step_runs]

    assert asyncio.run(exercise()) == ["s1", "s2", "s3"]


def test_step_id_is_unique_within_an_execution(
    execution_models: tuple[type[Any], type[Any]],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    execution_type, step_type = execution_models

    async def exercise() -> None:
        async with session_factory() as session:
            dataset_id, initial_version_id, current_version_id = await _seed_versions(session)
            execution = _new_execution(
                execution_type,
                dataset_id=dataset_id,
                initial_version_id=initial_version_id,
                current_version_id=current_version_id,
            )
            session.add(execution)
            session.add(
                _new_step(
                    step_type,
                    execution_id=execution.id,
                    step_id="s1",
                    sequence=1,
                    source_version_id=initial_version_id,
                )
            )
            await session.commit()

            session.add(
                _new_step(
                    step_type,
                    execution_id=execution.id,
                    step_id="s1",
                    sequence=2,
                    source_version_id=current_version_id,
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()

    asyncio.run(exercise())


def test_sequence_is_unique_within_an_execution(
    execution_models: tuple[type[Any], type[Any]],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    execution_type, step_type = execution_models

    async def exercise() -> None:
        async with session_factory() as session:
            dataset_id, initial_version_id, current_version_id = await _seed_versions(session)
            execution = _new_execution(
                execution_type,
                dataset_id=dataset_id,
                initial_version_id=initial_version_id,
                current_version_id=current_version_id,
            )
            session.add(execution)
            session.add(
                _new_step(
                    step_type,
                    execution_id=execution.id,
                    step_id="s1",
                    sequence=1,
                    source_version_id=initial_version_id,
                )
            )
            await session.commit()

            session.add(
                _new_step(
                    step_type,
                    execution_id=execution.id,
                    step_id="s2",
                    sequence=1,
                    source_version_id=current_version_id,
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()

    asyncio.run(exercise())


def test_step_id_can_repeat_in_different_executions(
    execution_models: tuple[type[Any], type[Any]],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    execution_type, step_type = execution_models

    async def exercise() -> int:
        async with session_factory() as session:
            dataset_id, initial_version_id, current_version_id = await _seed_versions(session)
            first = _new_execution(
                execution_type,
                dataset_id=dataset_id,
                initial_version_id=initial_version_id,
                current_version_id=current_version_id,
            )
            second = _new_execution(
                execution_type,
                dataset_id=dataset_id,
                initial_version_id=initial_version_id,
                current_version_id=current_version_id,
            )
            session.add_all([first, second])
            session.add_all(
                [
                    _new_step(
                        step_type,
                        execution_id=first.id,
                        step_id="s1",
                        sequence=1,
                        source_version_id=initial_version_id,
                    ),
                    _new_step(
                        step_type,
                        execution_id=second.id,
                        step_id="s1",
                        sequence=1,
                        source_version_id=current_version_id,
                    ),
                ]
            )
            await session.commit()
            return len(
                list(
                    await session.scalars(
                        select(step_type).where(step_type.step_id == "s1")
                    )
                )
            )

    assert asyncio.run(exercise()) == 2


def test_execution_initial_and_current_versions_are_independent(
    execution_models: tuple[type[Any], type[Any]],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    execution_type, _ = execution_models

    async def exercise() -> tuple[UUID, UUID]:
        async with session_factory() as session:
            dataset_id, initial_version_id, current_version_id = await _seed_versions(session)
            execution = _new_execution(
                execution_type,
                dataset_id=dataset_id,
                initial_version_id=initial_version_id,
                current_version_id=current_version_id,
            )
            session.add(execution)
            await session.commit()
            await session.refresh(execution)
            return execution.initial_version_id, execution.current_version_id

    initial_version_id, current_version_id = asyncio.run(exercise())
    assert initial_version_id != current_version_id
