"""RED contracts for the persistent Agent Execution Workflow.

These tests intentionally describe safety guarantees that the current one-request
executor does not yet provide.  They only mock the dispatch boundary to observe
which steps were scheduled; no industrial algorithm result is fabricated.

Phase 2 specification (not implemented here): a repeated approval for the same
``execution_id + step_id`` must not create another DatasetVersion, Model, or Study.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

from algorithms.agent.compliance import verify_plan
from algorithms.agent.planner import PlannedStep
from app.models.dataset import ProcessingRun
from app.schemas.copilot import CopilotChatRequest
from app.services import agent_service


def _three_step_plan() -> list[PlannedStep]:
    """A deterministic plan with one confirmation gate and one downstream step."""

    return [
        PlannedStep(
            step_id="s1",
            tool="profile_dataset",
            depends_on=(),
            parameters={},
            requires_confirmation=False,
        ),
        PlannedStep(
            step_id="s2",
            tool="export_dataset",
            depends_on=("s1",),
            parameters={},
            requires_confirmation=True,
        ),
        PlannedStep(
            step_id="s3",
            tool="detect_dynamic_segments",
            depends_on=("s2",),
            parameters={},
            requires_confirmation=False,
        ),
    ]


def _series() -> SimpleNamespace:
    """Provide only the column-resolution boundary required before dispatch."""

    return SimpleNamespace(
        resolve_columns=lambda *, input_columns, output_column: (["u1"], "y"),
        dataset_id=uuid4(),
        version_id=uuid4(),
        origin="dataset",
    )


def test_waiting_confirmation_stops_before_downstream_step(
    monkeypatch: object,
) -> None:
    """A confirmation gate must leave all later plan steps pending and undispatched."""

    dispatched: list[str] = []

    def record_dispatch(
        step: PlannedStep,
        series: object,
        context: dict[str, object],
        hints: dict[str, object],
    ) -> tuple[str, dict[str, object]]:
        dispatched.append(step.step_id)
        return "read-only step completed", {}

    monkeypatch.setattr(agent_service, "_dispatch", record_dispatch)

    executions = agent_service._execute(_series(), _three_step_plan(), {})

    assert dispatched == ["s1"]
    assert [execution.step_id for execution in executions] == ["s1", "s2"]
    assert agent_service._status_of("s3", executions) == "pending"


def test_waiting_confirmation_has_no_downstream_side_effect(
    monkeypatch: object,
) -> None:
    """A downstream tool invocation is a scheduling side effect and must remain zero."""

    invocation_count = 0

    def record_dispatch(
        step: PlannedStep,
        series: object,
        context: dict[str, object],
        hints: dict[str, object],
    ) -> tuple[str, dict[str, object]]:
        nonlocal invocation_count
        if step.step_id == "s3":
            invocation_count += 1
        return "read-only step completed", {}

    monkeypatch.setattr(agent_service, "_dispatch", record_dispatch)

    agent_service._execute(_series(), _three_step_plan(), {})

    assert invocation_count == 0


def test_waiting_confirmation_is_not_persisted_as_a_succeeded_run() -> None:
    """A run still awaiting a human decision cannot truthfully be marked succeeded.

    ``ProcessingRun.status`` is currently an unconstrained string, so this test only
    requires the minimum safe contract: it must not be ``succeeded``.  The future
    ``AgentExecutionSession.workflow_status`` will carry the explicit
    ``WAITING_CONFIRMATION`` state.
    """

    proof = verify_plan(
        [
            {"step_id": "profile", "tool": "profile_dataset", "depends_on": [],
             "parameters": {}, "requires_confirmation": False},
            {
                "step_id": "s1",
                "tool": "export_dataset",
                "depends_on": ["profile"],
                "parameters": {},
                "requires_confirmation": True,
            }
        ]
    )
    assert proof.passed
    payload = CopilotChatRequest(
        message="导出优选数据集",
        dataset_id=uuid4(),
        active_version_id=uuid4(),
    )
    session = _RecordingSession()
    series = SimpleNamespace(
        dataset_id=payload.dataset_id,
        version_id=payload.active_version_id,
        origin="dataset",
    )

    asyncio.run(
        agent_service._persist(
            session,
            run_id=uuid4(),
            payload=payload,
            proof=proof,
            executions=[
                agent_service.StepExecution(
                    step_id="s1",
                    tool="export_dataset",
                    status="waiting_confirmation",
                    parameters={},
                    summary="高影响操作，等待人工确认后执行。",
                )
            ],
            series=series,
        )
    )

    persisted = next(item for item in session.added if isinstance(item, ProcessingRun))
    assert persisted.status != "succeeded"


class _RecordingSession:
    """Minimal AsyncSession observation fake for the persistence contract."""

    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, item: object) -> None:
        self.added.append(item)

    async def commit(self) -> None:
        return None
