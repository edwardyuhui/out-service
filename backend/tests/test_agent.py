"""Tests for agent planning, compliance verification and real tool execution (phase 9)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from algorithms.agent.compliance import verify_plan
from algorithms.agent.planner import TOOL_WHITELIST, RuleBasedPlanner, parse_intent
from app.core.config import Settings
from app.core.db import get_session
from app.main import create_app
from app.models import Base
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def plan_for(message: str):  # type: ignore[no-untyped-def]
    steps, assumptions, stops = RuleBasedPlanner().plan(parse_intent(message))
    return steps, assumptions, stops


def as_raw(steps):  # type: ignore[no-untyped-def]
    return [
        {
            "step_id": step.step_id,
            "tool": step.tool,
            "depends_on": list(step.depends_on),
            "parameters": dict(step.parameters),
            "requires_confirmation": step.requires_confirmation,
        }
        for step in steps
    ]


class TestIntentParsing:
    def test_parses_the_brief_s_own_example_instruction(self) -> None:
        """The example from the A14 statement must produce the workflow it describes."""

        intent = parse_intent(
            "提取 1 号塔高信噪比的动态数据，处理共线性后，通过闭环寻优找出最佳模型数据"
        )
        assert intent.wants("segment")
        assert intent.wants("collinearity")
        assert intent.wants("optimize")

    def test_recognises_optuna_optimization_model_workflow(self) -> None:
        message = "完成 ARX 模型辨识，使用 Optuna 对模型进行优化，并评估优化后的模型"
        intent = parse_intent(message)

        assert intent.wants("model") is True
        assert intent.wants("optimize") is True

        steps, _, _ = RuleBasedPlanner().plan(intent)
        by_tool = {step.tool: step for step in steps}
        ordered_tools = [step.tool for step in steps]
        assert ordered_tools.index("fit_arx") < ordered_tools.index("optimize_pipeline")
        assert ordered_tools.index("optimize_pipeline") < ordered_tools.index("evaluate_model")
        assert by_tool["optimize_pipeline"].depends_on == (by_tool["fit_arx"].step_id,)
        assert by_tool["evaluate_model"].depends_on == (
            by_tool["optimize_pipeline"].step_id,
        )

    def test_extracts_explicit_numbers(self) -> None:
        intent = parse_intent("用窗口 90 做动态区间优选，最大滞后 45，跑 60 次试验")
        assert intent.parameters["window_size"] == 90
        assert intent.parameters["max_lag"] == 45
        assert intent.parameters["max_trials"] == 60

    def test_recognises_english_requests(self) -> None:
        intent = parse_intent("clean the data, estimate delay, then fit an ARX model")
        assert intent.wants("clean")
        assert intent.wants("delay")
        assert intent.wants("model")

    def test_picks_up_mentioned_columns(self) -> None:
        intent = parse_intent("分析 u1 和 u2 对 y1 的时滞")
        assert set(intent.mentioned_columns) >= {"u1", "u2", "y1"}

    def test_unrecognised_request_falls_back_to_profiling_only(self) -> None:
        steps, assumptions, _ = plan_for("你好")
        assert [step.tool for step in steps] == ["profile_dataset"]
        assert any("未能从指令中识别" in note for note in assumptions)


class TestPlanning:
    def test_plan_only_uses_whitelisted_tools(self) -> None:
        steps, _, _ = plan_for("清洗数据，做动态优选、时滞、共线性、建模、闭环寻优、出报告并导出")
        assert all(step.tool in TOOL_WHITELIST for step in steps)

    @pytest.mark.parametrize(
        "message",
        ["报告交付", "生成报告", "生成分析报告", "分析报告", "报告生成", "给我报告"],
    )
    def test_report_delivery_does_not_imply_dataset_export(self, message: str) -> None:
        tools = [step.tool for step in plan_for(message)[0]]

        assert "generate_report" in tools
        assert "export_dataset" not in tools

    @pytest.mark.parametrize(
        "message",
        [
            "导出数据集",
            "导出优选数据集",
            "导出最优数据集",
            "导出最优建模数据集",
            "下载数据集",
            "下载优选数据集",
            "下载最优建模数据集",
            "导出 CSV",
            "下载 CSV",
            "导出清洗后的数据",
        ],
    )
    def test_explicit_dataset_export_intent_is_preserved(self, message: str) -> None:
        tools = [step.tool for step in plan_for(message)[0]]

        assert "export_dataset" in tools

    @pytest.mark.parametrize("message", ["输出结果", "查看结果", "保存报告"])
    def test_ambiguous_result_language_does_not_imply_dataset_export(
        self, message: str
    ) -> None:
        tools = [step.tool for step in plan_for(message)[0]]

        assert "export_dataset" not in tools

    def test_optimized_modeling_dataset_export_is_planned_after_final_evaluation(
        self,
    ) -> None:
        steps, _, _ = plan_for(
            "基于当前数据建立 ARX 模型并进行 Optuna 闭环寻优，"
            "寻优完成后导出最优建模数据集。"
        )
        tools = [step.tool for step in steps]

        assert tools.index("fit_arx") < tools.index("optimize_pipeline")
        assert tools.index("optimize_pipeline") < tools.index("evaluate_model")
        assert tools.index("evaluate_model") < tools.index("export_dataset")
        export = next(step for step in steps if step.tool == "export_dataset")
        assert export.requires_confirmation is True

    def test_prerequisites_come_first(self) -> None:
        steps, _, _ = plan_for("清洗后建模")
        order = [step.tool for step in steps]
        assert order.index("profile_dataset") < order.index("detect_anomalies")
        assert order.index("detect_anomalies") < order.index("clean_data")
        assert order.index("estimate_delays") < order.index("apply_lag_compensation")
        assert order.index("apply_lag_compensation") < order.index("fit_arx")
        assert order.index("fit_arx") < order.index("evaluate_model")

    @pytest.mark.parametrize("message", ["ARX", "建模", "辨识", "动态模型", "完整建模流程"])
    def test_model_goals_include_the_complete_lag_chain(self, message: str) -> None:
        steps, _, _ = plan_for(message)
        by_tool = {step.tool: step for step in steps}
        order = [step.tool for step in steps]

        assert order.index("estimate_delays") < order.index("apply_lag_compensation")
        assert order.index("apply_lag_compensation") < order.index("fit_arx")
        assert by_tool["apply_lag_compensation"].depends_on == (
            by_tool["estimate_delays"].step_id,
        )
        assert by_tool["fit_arx"].depends_on == (
            by_tool["apply_lag_compensation"].step_id,
        )

    def test_optimization_modelling_uses_the_saved_model_producer_chain(self) -> None:
        steps, _, _ = plan_for("进行 ARX 建模并闭环寻优 2 次试验")
        by_tool = {step.tool: step for step in steps}
        ordered_tools = [step.tool for step in steps]

        assert ordered_tools.index("fit_arx") < ordered_tools.index("optimize_pipeline")
        assert ordered_tools.index("optimize_pipeline") < ordered_tools.index("evaluate_model")
        assert by_tool["optimize_pipeline"].depends_on == (by_tool["fit_arx"].step_id,)
        assert by_tool["evaluate_model"].depends_on == (
            by_tool["optimize_pipeline"].step_id,
        )
        assert by_tool["fit_arx"].requires_confirmation is True
        assert by_tool["optimize_pipeline"].requires_confirmation is True
        assert by_tool["evaluate_model"].requires_confirmation is False

    def test_lag_ready_normalization_removes_redundant_direct_lag_chain(self) -> None:
        from app.services.agent_service import _normalize_plan_for_lag_context

        steps, _, _ = plan_for("进行 ARX 建模")
        normalized, removed = _normalize_plan_for_lag_context(steps, lag_ready=True)
        tools = [step.tool for step in normalized]

        assert removed is True
        assert "estimate_delays" not in tools
        assert "apply_lag_compensation" not in tools
        assert "fit_arx" in tools
        assert verify_plan(as_raw(normalized), lag_ready=True).passed

    def test_lag_ready_normalization_preserves_post_clean_lag_chain(self) -> None:
        from app.services.agent_service import _normalize_plan_for_lag_context

        steps, _, _ = plan_for("清洗后进行 ARX 建模")
        normalized, removed = _normalize_plan_for_lag_context(steps, lag_ready=True)
        tools = [step.tool for step in normalized]

        assert removed is False
        assert normalized == steps
        assert tools.index("clean_data") < tools.index("estimate_delays")
        assert tools.index("estimate_delays") < tools.index("apply_lag_compensation")
        assert tools.index("apply_lag_compensation") < tools.index("fit_arx")

    def test_modelling_implies_segment_selection(self) -> None:
        steps, assumptions, _ = plan_for("直接做 ARX 辨识")
        assert "detect_dynamic_segments" in [step.tool for step in steps]
        assert any("D-最优" in note for note in assumptions)

    def test_high_impact_steps_are_marked_for_confirmation(self) -> None:
        steps, _, _ = plan_for("处理共线性并导出数据集")
        flagged = {step.tool for step in steps if step.requires_confirmation}
        assert "select_variables" in flagged
        assert "export_dataset" in flagged

    def test_explicit_parameters_reach_the_step(self) -> None:
        steps, _, _ = plan_for("用窗口 120 提取动态区间")
        segment = next(step for step in steps if step.tool == "detect_dynamic_segments")
        assert segment.parameters["window_size"] == 120


class TestCompliance:
    def test_a_clean_plan_passes_every_check(self) -> None:
        steps, _, _ = plan_for("清洗后建模")
        proof = verify_plan(as_raw(steps))
        assert proof.passed, [check.detail for check in proof.failures]
        assert proof.signature.startswith("sha256:")
        assert proof.proof_id.startswith("PROOF-")

    def test_a_non_whitelisted_tool_is_rejected(self) -> None:
        proof = verify_plan(
            [{"step_id": "s1", "tool": "run_arbitrary_python", "depends_on": [], "parameters": {}}]
        )
        assert not proof.passed
        assert any(check.name == "tool_whitelist" for check in proof.failures)

    def test_a_cycle_is_rejected(self) -> None:
        proof = verify_plan(
            [
                {"step_id": "a", "tool": "profile_dataset", "depends_on": ["b"], "parameters": {}},
                {"step_id": "b", "tool": "fit_arx", "depends_on": ["a"], "parameters": {}},
            ]
        )
        assert not proof.passed
        assert any(check.name == "dag_acyclic" for check in proof.failures)

    def test_a_dangling_dependency_is_rejected(self) -> None:
        proof = verify_plan(
            [{"step_id": "a", "tool": "fit_arx", "depends_on": ["ghost"], "parameters": {}}]
        )
        assert not proof.passed
        assert any(check.name == "dependencies_resolved" for check in proof.failures)

    def test_a_static_prerequisite_must_be_present_and_declared(self) -> None:
        proof = verify_plan(
            [
                {"step_id": "s1", "tool": "profile_dataset", "depends_on": []},
                {
                    "step_id": "s2",
                    "tool": "apply_lag_compensation",
                    "depends_on": ["s1"],
                },
            ]
        )

        assert not proof.passed
        ordering = next(check for check in proof.failures if check.name == "tool_ordering")
        assert "缺少前置 estimate_delays" in ordering.detail

    def test_fit_requires_plan_lag_chain_when_context_is_not_ready(self) -> None:
        proof = verify_plan(
            [
                {"step_id": "s1", "tool": "profile_dataset", "depends_on": []},
                {
                    "step_id": "s2",
                    "tool": "fit_arx",
                    "depends_on": ["s1"],
                    "requires_confirmation": True,
                },
            ],
            lag_ready=False,
        )

        assert not proof.passed
        assert any(check.name == "arx_lag_ready" for check in proof.failures)

    def test_fit_accepts_server_verified_lag_ready_context_without_duplicate_lag(self) -> None:
        proof = verify_plan(
            [
                {"step_id": "s1", "tool": "profile_dataset", "depends_on": []},
                {
                    "step_id": "s2",
                    "tool": "fit_arx",
                    "depends_on": ["s1"],
                    "requires_confirmation": True,
                },
            ],
            lag_ready=True,
        )

        assert proof.passed, [check.detail for check in proof.failures]

    def test_clean_invalidates_initial_lag_ready_context(self) -> None:
        proof = verify_plan(
            [
                {"step_id": "s1", "tool": "profile_dataset", "depends_on": []},
                {"step_id": "s2", "tool": "detect_anomalies", "depends_on": ["s1"]},
                {"step_id": "s3", "tool": "clean_data", "depends_on": ["s2"]},
                {
                    "step_id": "s4",
                    "tool": "fit_arx",
                    "depends_on": ["s3"],
                    "requires_confirmation": True,
                },
            ],
            lag_ready=True,
        )

        assert not proof.passed
        lag_check = next(check for check in proof.failures if check.name == "arx_lag_ready")
        assert "s4" in lag_check.detail
        assert "Cleaning" in lag_check.detail

    def test_each_fit_uses_the_lag_state_at_its_own_position(self) -> None:
        proof = verify_plan(
            [
                {"step_id": "s1", "tool": "profile_dataset", "depends_on": []},
                {
                    "step_id": "s2",
                    "tool": "fit_arx",
                    "depends_on": ["s1"],
                    "requires_confirmation": True,
                },
                {"step_id": "s3", "tool": "detect_anomalies", "depends_on": ["s2"]},
                {"step_id": "s4", "tool": "clean_data", "depends_on": ["s3"]},
                {
                    "step_id": "s5",
                    "tool": "fit_arx",
                    "depends_on": ["s4"],
                    "requires_confirmation": True,
                },
            ],
            lag_ready=True,
        )

        assert not proof.passed
        lag_check = next(check for check in proof.failures if check.name == "arx_lag_ready")
        assert "s5" in lag_check.detail
        assert "s2" not in lag_check.detail

    @pytest.mark.parametrize("initial_lag_ready", [True, False])
    def test_clean_then_relag_is_valid_for_arx(
        self, initial_lag_ready: bool
    ) -> None:
        steps, _, _ = plan_for("清洗后进行 ARX 建模")

        proof = verify_plan(as_raw(steps), lag_ready=initial_lag_ready)

        assert proof.passed, [check.detail for check in proof.failures]

    def test_invalid_llm_clean_then_fit_candidate_falls_back_before_execution(self) -> None:
        from algorithms.agent.llm import StaticProvider
        from algorithms.agent.llm_planner import LlmPlanner

        candidate = """{
          "steps": [
            {"step_id": "s1", "tool": "profile_dataset", "depends_on": []},
            {"step_id": "s2", "tool": "detect_anomalies", "depends_on": ["s1"]},
            {"step_id": "s3", "tool": "clean_data", "depends_on": ["s2"]},
            {"step_id": "s4", "tool": "fit_arx", "depends_on": ["s3"]},
            {"step_id": "s5", "tool": "optimize_pipeline", "depends_on": ["s4"]},
            {"step_id": "s6", "tool": "evaluate_model", "depends_on": ["s5"]}
          ]
        }"""
        message = "基于当前数据建立 ARX 模型并进行 Optuna 闭环寻优。"

        outcome = LlmPlanner(StaticProvider(responses=[candidate])).plan(
            message,
            parse_intent(message),
            lag_ready=True,
        )

        assert not outcome.llm_authored
        assert "合规校验" in (outcome.fallback_reason or "")
        assert "Cleaning" in (outcome.fallback_reason or "")
        assert "clean_data" not in [step.tool for step in outcome.steps]
        assert "apply_lag_compensation" in [step.tool for step in outcome.steps]

    def test_pointing_a_step_at_the_test_partition_is_rejected(self) -> None:
        proof = verify_plan(
            [
                {
                    "step_id": "a",
                    "tool": "fit_arx",
                    "depends_on": [],
                    "parameters": {"partition": "test"},
                }
            ]
        )
        assert not proof.passed
        assert any(check.name == "test_set_untouched" for check in proof.failures)

    def test_fitting_past_the_training_boundary_is_rejected(self) -> None:
        proof = verify_plan(
            [
                {
                    "step_id": "a",
                    "tool": "detect_anomalies",
                    "depends_on": [],
                    "parameters": {"train_ratio": 0.95},
                }
            ]
        )
        assert not proof.passed
        assert any(check.name == "fitted_on_train_only" for check in proof.failures)

    def test_a_flagged_high_impact_step_is_gated_not_rejected(self) -> None:
        """The plan stays valid; the executor holds the step until a human approves."""

        steps, _, _ = plan_for("导出优选数据集")
        proof = verify_plan(as_raw(steps))
        assert proof.passed
        gate = next(check for check in proof.checks if check.name == "high_impact_gated")
        assert "等待人工确认" in gate.detail

    def test_an_unflagged_high_impact_step_is_rejected(self) -> None:
        """Slipping an export through without the confirmation flag must not verify."""

        proof = verify_plan(
            [
                {
                    "step_id": "s1",
                    "tool": "export_dataset",
                    "depends_on": [],
                    "parameters": {},
                    "requires_confirmation": False,
                }
            ]
        )
        assert not proof.passed
        assert any(check.name == "high_impact_gated" for check in proof.failures)

    def test_confirming_the_step_clears_the_gate(self) -> None:
        steps, _, _ = plan_for("导出优选数据集")
        raw = as_raw(steps)
        export = next(step for step in raw if step["tool"] == "export_dataset")
        proof = verify_plan(raw, confirmed_steps=frozenset({str(export["step_id"])}))
        assert proof.passed
        gate = next(check for check in proof.checks if check.name == "high_impact_gated")
        assert gate.detail == "高影响操作均已获人工确认"

    def test_signature_changes_when_the_plan_changes(self) -> None:
        first, _, _ = plan_for("清洗后建模")
        second, _, _ = plan_for("清洗数据")
        assert verify_plan(as_raw(first)).signature != verify_plan(as_raw(second)).signature


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'agent.db'}")
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
    app.dependency_overrides[get_session] = session_override
    with TestClient(app) as client:
        yield client
    asyncio.run(engine.dispose())


def benchmark_dataset_version(client: TestClient) -> tuple[str, str]:
    response = client.post(
        "/api/v1/simulation/generate",
        json={"scenario": "S2", "n_steps": 2500, "seed": 8, "input_count": 2},
    )
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    return data["dataset_id"], data["version_id"]


def benchmark_version(client: TestClient) -> str:
    _, version_id = benchmark_dataset_version(client)
    return version_id


def lag_compensated_benchmark_version(client: TestClient) -> str:
    dataset_id, version_id = benchmark_dataset_version(client)
    applied = client.post(
        "/api/v1/preprocessing/delay/apply",
        json={
            "dataset_id": dataset_id,
            "version_id": version_id,
            "lag_map": {"u1": 3, "u2": 8},
            "user_confirmed": True,
            "recommendation_source": "manual",
            "evidence_summary": {"fixture": "formal_lag_compensation"},
        },
    )
    assert applied.status_code == 201, applied.text
    return applied.json()["data"]["result_version_id"]


class TestAgentApi:
    def test_plan_only_without_a_version(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/copilot/chat",
            json={"message": "清洗数据后做 ARX 辨识"},
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["compliance"]["passed"] is True
        assert data["executed"] is False
        assert data["step_runs"] == []

    def test_natural_language_run_executes_real_tools_until_confirmation_gate(
        self, client: TestClient
    ) -> None:
        """A confirmation gate stops the natural-language workflow immediately."""

        version_id = benchmark_version(client)
        response = client.post(
            "/api/v1/copilot/chat",
            json={
                "message": "提取高信噪比的动态数据，估计时滞，处理共线性，然后做 ARX 辨识",
                "active_version_id": version_id,
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]

        assert data["compliance"]["passed"] is True
        assert data["executed"] is True

        by_tool = {run["tool"]: run for run in data["step_runs"]}
        assert by_tool["detect_dynamic_segments"]["status"] == "completed"
        assert by_tool["estimate_delays"]["status"] == "completed"
        assert by_tool["apply_lag_compensation"]["status"] == "waiting_confirmation"
        assert "analyze_collinearity" not in by_tool
        assert "fit_arx" not in by_tool

        planned_steps = {step["tool"]: step["status"] for step in data["plan"]["steps"]}
        assert planned_steps["fit_arx"] == "pending"
        assert planned_steps["apply_lag_compensation"] == "waiting_confirmation"
        assert "等待人工确认" in data["conclusion"]

        # Every number in the summary must come from a tool, not from the agent.
        assert by_tool["estimate_delays"]["result"]["delays"]

    def test_natural_language_run_prepares_arx_confirmation_from_lag_compensated_version(
        self, client: TestClient
    ) -> None:
        """ARX planning requires formal lag lineage and stops at its confirmation gate."""

        version_id = lag_compensated_benchmark_version(client)
        response = client.post(
            "/api/v1/copilot/chat",
            json={
                "message": "提取高信噪比的动态数据，然后做 ARX 辨识",
                "active_version_id": version_id,
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]

        by_tool = {run["tool"]: run for run in data["step_runs"]}
        fit = by_tool["fit_arx"]
        assert data["workflow_status"] == "WAITING_CONFIRMATION"
        assert data["pending_confirmation_step_id"] == fit["step_id"]
        assert fit["status"] == "waiting_confirmation"
        recommendation = fit["result"]["arx_structure_recommendation"]
        assert recommendation["lag_compensation_version_id"] == version_id
        assert recommendation["recommended_delays"] == {"u1": 0, "u2": 0}
        planned_steps = {step["tool"]: step["status"] for step in data["plan"]["steps"]}
        assert "estimate_delays" not in planned_steps
        assert "apply_lag_compensation" not in planned_steps
        assert planned_steps["evaluate_model"] == "pending"
    def test_high_impact_step_waits_for_confirmation_instead_of_running(
        self, client: TestClient
    ) -> None:
        version_id = benchmark_version(client)
        response = client.post(
            "/api/v1/copilot/chat",
            json={
                "message": "分析共线性并剔除冗余变量",
                "active_version_id": version_id,
                "context": {"confirmed_steps": ["s2"]},
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        runs = {run["tool"]: run["status"] for run in data["step_runs"]}
        assert runs.get("select_variables") == "waiting_confirmation"

    def test_conclusion_reports_what_actually_happened(self, client: TestClient) -> None:
        version_id = benchmark_version(client)
        response = client.post(
            "/api/v1/copilot/chat",
            json={"message": "做动态区间优选", "active_version_id": version_id},
        )
        data = response.json()["data"]
        assert "已执行" in data["conclusion"]

    def test_unknown_version_returns_404(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/copilot/chat",
            json={"message": "做动态区间优选", "active_version_id": str(uuid4())},
        )
        assert response.status_code == 404
