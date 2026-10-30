"""Tests for provenance-bound reporting and optimised-dataset export (phase 10)."""

from __future__ import annotations

import asyncio
import csv
import json
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4
from xml.etree import ElementTree

import pytest
from algorithms.report.provenance import (
    render_template,
    resolve_path,
    validate_draft,
)
from app.core.config import Settings
from app.core.db import get_session
from app.main import create_app
from app.models import Base
from app.models.dataset import ProcessingRun
from app.models.optimization import OptimizationStudy, OptimizationTrialRecord
from app.schemas.reporting import ReportRequest, ReportSection
from app.services import report_service
from app.services.report_service import (
    RunIndex,
    _compose,
    _matches,
    _number_sections,
    _presentation_formatters,
    _report_title,
    build_execution_run_index,
)
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

RUNS = {
    "r1": {
        "run_type": "modeling.arx",
        "validation": {"free_run_fit": 97.8612, "one_step_fit": 99.1, "stable": True},
        "training_rows": 480,
        "delays": {"u1": 3, "u2": 8},
    }
}


def test_execution_report_binds_final_test_metrics_and_warns_on_failure():
    index = RunIndex(records={
        "step11": {"test": {"free_run": {"fit": -12, "rmse": 8}, "n_samples": 100}},
        "evaluation": {"test": {"free_run": {"fit": -12}},
            "model_health": {"input_support": {"status": "unsupported"}}},
    }, by_type={"modeling.arx_evaluation": "evaluation"},
        step_by_tool={"evaluate_model": "step11"}, execution_id=uuid4())
    sections = {s.key: s.body for s in _compose(index, report_service.ReportRequest())}
    assert "冻结最终模型 Test" in sections["evaluation"]
    assert "{{step:step11.test.free_run.rmse}}" in sections["evaluation"]
    assert "FIT 非正" in sections["limitations"]
    assert "真实运行数据" in sections["limitations"]


def test_trial_curve_ignores_failed_and_nonfinite_scores():
    trials = [SimpleNamespace(trial_number=i, state=state, value=value)
        for i, (state, value) in enumerate([
            ("failed", 999), ("complete", 0.1), ("failed", 999),
            ("complete", float("nan")), ("complete", 0.05), ("complete", 0.3)])]

    class Session:
        async def scalars(self, statement):
            return SimpleNamespace(all=lambda: trials)

    curve = asyncio.run(report_service._study_trial_curve(Session(), uuid4()))
    assert [p["trial_number"] for p in curve] == [1, 2, 3, 4, 5]
    assert [p["best_value"] for p in curve] == [0.1, 0.1, 0.1, 0.1, 0.3]


def test_cleaning_chart_aligns_unique_timestamps_and_excludes_duplicates(monkeypatch, tmp_path):
    import numpy as np

    dataset_id, before_id, after_id = uuid4(), uuid4(), uuid4()
    stamps = [datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=i) for i in range(4)]
    before = SimpleNamespace(declared_output="y", timestamps=[stamps[0], stamps[1], stamps[1], stamps[2], stamps[3]],
        values={"y": np.array([1., 9., 99., 3., float("nan")])})
    after = SimpleNamespace(timestamps=[stamps[2], stamps[0], stamps[1], stamps[3]],
        values={"y": np.array([30., 10., 90., 40.])})

    async def load(session, *, version_id, dataset_id, artifact_root):
        return before if version_id == before_id else after

    monkeypatch.setattr(report_service, "load_version_series", load)
    index = RunIndex(records={"step3": {"source_version_id": str(before_id),
        "effective_version_id": str(after_id)}}, by_type={},
        step_by_tool={"clean_data": "step3"}, execution_id=uuid4())
    asyncio.run(report_service._add_cleaning_preview(None, index=index,
        payload=report_service.ReportRequest(dataset_id=dataset_id), artifact_root=tmp_path))
    preview = index.records["step3"]["cleaning_preview"]
    assert preview["before"] == [1., 3.]
    assert preview["after"] == [10., 30.]
    assert preview["relative_milliseconds"] == [0, 2000]
    assert preview["before_version_id"] == str(before_id)


def test_report_explains_unexcited_and_extrapolated_inputs():
    index = RunIndex(records={"model": {"validation": {"input_support": {"status": "unsupported"}}},
        "evaluation": {"model_health": {"input_support": {"status": "extrapolation"}}}},
        by_type={"modeling.arx": "model", "modeling.arx_evaluation": "evaluation"},
        step_by_tool={}, execution_id=None)
    body = report_service._standalone_limitations(index)
    assert "未激励" in body and "真实运行数据" in body and "外推" in body


def test_report_explains_full_training_policy_and_insufficient_validation():
    index = RunIndex(records={"study": {"best_params": {"training_policy": "full_train"},
        "best_trial_metrics": {"validation_acceptance": {"status": "insufficient"}}}},
        by_type={}, step_by_tool={}, execution_id=None)
    body = report_service._standalone_limitations(index)
    assert "全量有效训练行" in body
    assert "寻优完成不代表模型效果达标" in body


def test_full_train_narration_excludes_inactive_selection_parameters():
    from algorithms.agent.llm import LlmResult

    class Provider:
        name = "test"
        model = "test"

        def complete(self, messages, *, temperature=0.0):
            assert "study.best_params.training_policy" in messages[-1].content
            for key in ("window_size", "max_segments", "temporal_coverage_bins"):
                assert f"study.best_params.{key}" not in messages[-1].content
            return LlmResult(text="采用全量训练策略。", provider=self.name, model=self.model)

    index = RunIndex(records={"study": {"best_params": {"training_policy": "full_train",
        "window_size": 100, "max_segments": 10, "temporal_coverage_bins": 3}}},
        by_type={}, step_by_tool={}, execution_id=None)
    result = report_service._narrate(Provider(), index=index,
        sections=_compose(index, report_service.ReportRequest()))
    assert result.source == "llm"


@pytest.mark.parametrize("test_fit, warns", [(-14.75, True), (0.0, True), (20.0, False)])
def test_stable_fir_report_still_warns_when_test_fit_is_nonpositive(test_fit, warns):
    index = RunIndex(records={
        "model": {"run_type": "modeling.arx", "model_type": "FIR", "validation": {"stable": True}},
        "evaluation": {"run_type": "modeling.arx_evaluation", "test": {"free_run": {"fit": test_fit}}},
    }, by_type={"modeling.arx": "model", "modeling.arx_evaluation": "evaluation"},
        step_by_tool={}, execution_id=None)
    sections = _compose(index, report_service.ReportRequest())
    model_section = next(s for s in sections if s.key == "model")
    assert "ARX" not in model_section.title
    limitations = next(s for s in sections if s.key == "limitations")
    assert ("Test 自由仿真 FIT 非正" in limitations.body) == warns


def test_narrator_receives_actual_metrics_and_input_names_not_just_paths():
    from algorithms.agent.llm import LlmResult

    class RecordingProvider:
        name = "test"
        model = "test"

        def complete(self, messages, *, temperature=0.0):
            prompt = messages[-1].content
            assert "Train 拟合参数" in messages[0].content
            assert "Test 固定参数评价" in messages[0].content
            assert '"evaluation.test.free_run.fit": -14.75' in prompt
            assert '"model.input_columns": ["M101", "TV101"]' in prompt
            assert "结构稳定性不能替代预测能力验证" in prompt
            assert "initialization_window" not in prompt
            assert "kernel_decay" not in prompt
            return LlmResult(text="FIT 为 {{run:evaluation.test.free_run.fit}}，预测效果不足。",
                provider=self.name, model=self.model)

    index = RunIndex(records={
        "model": {"run_type": "modeling.arx", "input_columns": ["M101", "TV101"],
            "model_type": "FIR", "validation": {"stable": True},
            "initialization_policy": "fixed", "initialization_window": 32,
            "regularization_kernel": "identity", "kernel_decay": .9},
        "evaluation": {"run_type": "modeling.arx_evaluation", "test": {"free_run": {"fit": -14.75}}},
    }, by_type={"modeling.arx": "model", "modeling.arx_evaluation": "evaluation"},
        step_by_tool={}, execution_id=None)
    result = report_service._narrate(RecordingProvider(), index=index,
        sections=_compose(index, report_service.ReportRequest()))
    assert result.source == "llm"
    assert render_template(result.text, runs=index.records).fully_resolved


@pytest.mark.parametrize("modern", [True, False])
def test_report_uses_recorded_composite_objective_with_legacy_fallback(modern):
    study = {"objective": "val_free_run_fit", "best_value": .1, "best_trial_number": 2}
    if modern:
        study["best_trial_metrics"] = {"objective_semantics": {
            "name": "composite_identification_score", "version": "v4"}}
    index = RunIndex(records={"r1": RUNS["r1"], "study": study},
        by_type={"modeling.arx": "r1"}, step_by_tool={}, execution_id=None)
    sections = _compose(index, report_service.ReportRequest())
    body = next(s.body for s in sections if s.key == "optimization")
    rendered = render_template(body, runs=index.records)
    assert rendered.fully_resolved
    assert ("composite_identification_score" in rendered.text) == modern
    assert ("val_free_run_fit" in rendered.text) != modern


def _collinearity_chart_and_html(
    variables: list[str], matrix: list[list[float | None]]
) -> tuple[str, str, str]:
    run_id = str(uuid4())
    index = RunIndex(
        records={
            "collinearity_run": {
                "run_id": run_id,
                "run_type": "preprocessing.collinearity",
                "variables": variables,
                "pearson": matrix,
            }
        },
        by_type={"preprocessing.collinearity": "collinearity_run"},
        step_by_tool={},
        execution_id=None,
    )
    charts = report_service._build_report_charts(index)
    assert len(charts) == 1
    html = report_service._render_html_report(
        title="测试报告",
        sections=[ReportSection(key="collinearity", title="共线性诊断", body="正式分析结果。")],
        charts=charts,
        index=index,
        payload=ReportRequest(),
    )
    return charts[0].svg, html, run_id


class TestPearsonHeatmapLabels:
    def test_three_long_names_use_the_same_axis_numbers_and_adjacent_key(self) -> None:
        variables = ["raw_material_flow", "fuel_flow", "exhaust_fan_speed"]
        matrix = [[1.0, -0.63, None], [-0.63, 1.0, 0.01], [None, 0.01, 1.0]]
        svg, html, _ = _collinearity_chart_and_html(variables, matrix)
        root = ElementTree.fromstring(svg)
        texts = root.findall("{http://www.w3.org/2000/svg}text")
        assert [item.text for item in texts if item.attrib.get("text-anchor") == "end"] == [
            "X1", "X2", "X3"
        ]
        assert [item.text for item in texts if item.text and item.text.startswith("X")
                and item.attrib.get("text-anchor") == "middle"] == [
            "X1", "X2", "X3"
        ]
        assert all(name not in svg for name in variables)
        for number, name in enumerate(variables, start=1):
            assert f'<span class="matrix-key-code">X{number}</span>' in html
            assert f'<span class="matrix-key-name">{name}</span>' in html
        assert html.index("<svg") < html.index('class="matrix-key"') < html.index("<figcaption>")
        assert '<figure class="pearson-figure">' in html

    def test_many_variables_keep_numbering_coefficients_na_and_source(self) -> None:
        variables = [f"long_signal_channel_{index}" for index in range(1, 11)]
        matrix: list[list[float | None]] = [
            [1.0 if row == column else None for column in range(10)] for row in range(10)
        ]
        matrix[0][9] = matrix[9][0] = -0.47
        svg, html, run_id = _collinearity_chart_and_html(variables, matrix)
        root = ElementTree.fromstring(svg)
        texts = root.findall("{http://www.w3.org/2000/svg}text")
        assert [item.text for item in texts if item.attrib.get("text-anchor") == "end"] == [
            f"X{index}" for index in range(1, 11)
        ]
        assert [item.text for item in texts if item.text and item.text.startswith("X")
                and item.attrib.get("text-anchor") == "middle"] == [
            f"X{index}" for index in range(1, 11)
        ]
        assert sum(item.text == "-0.47" for item in texts) == 2
        assert any(item.text == "—" for item in texts)
        assert '<span class="matrix-key-code">X10</span>' in html
        assert f'<span class="matrix-key-name">{variables[9]}</span>' in html
        assert f"来源运行：<code>{run_id}</code>；字段：<code>pearson</code>" in html
        assert "@page{size:A4" in html
        assert "section,figure{break-inside:avoid-page}" in html
        assert ".pearson-figure svg{max-width:560px;max-height:none" in html
        assert ".matrix-key-name{overflow-wrap:anywhere}" in html


class TestNumeralValidation:
    def test_a_bare_number_is_rejected(self) -> None:
        violations = validate_draft("验证集自由仿真 FIT 达到 97.86%。")
        assert len(violations) == 1
        assert violations[0].text == "97.86"

    def test_a_bound_number_is_accepted(self) -> None:
        draft = "验证集自由仿真 FIT 达到 {{run:r1.validation.free_run_fit}}%。"
        assert validate_draft(draft) == []

    def test_list_and_heading_numbering_is_allowed(self) -> None:
        draft = "## 1. 概述\n\n1. 第一条\n2) 第二条\n3、第三条\n"
        assert validate_draft(draft) == []

    def test_a_number_after_a_list_marker_is_still_rejected(self) -> None:
        """Structure is exempt; data on the same line is not."""

        violations = validate_draft("1. 拟合度为 88.2 分")
        assert [violation.text for violation in violations] == ["88.2"]

    def test_reports_line_and_column(self) -> None:
        violations = validate_draft("第一行没有数字\n第二行有 42")
        assert violations[0].line == 2
        assert violations[0].column > 1

    def test_a_markdown_table_separator_is_not_data(self) -> None:
        assert validate_draft("| a | b |\n|---|---:|\n") == []

    def test_catches_every_violation_not_just_the_first(self) -> None:
        violations = validate_draft("FIT 97.8，RMSE 0.12，条件数 3400")
        assert len(violations) == 3


class TestPathResolution:
    def test_reads_a_nested_path(self) -> None:
        assert resolve_path(RUNS["r1"], "validation.free_run_fit") == pytest.approx(97.8612)

    def test_reads_a_dict_leaf(self) -> None:
        assert resolve_path(RUNS["r1"], "delays.u1") == 3

    def test_reads_a_list_index(self) -> None:
        assert resolve_path({"values": [10, 20, 30]}, "values.1") == 20

    def test_missing_path_returns_none(self) -> None:
        assert resolve_path(RUNS["r1"], "validation.does_not_exist") is None

    def test_descending_through_a_scalar_returns_none(self) -> None:
        assert resolve_path(RUNS["r1"], "training_rows.deeper") is None


class TestRendering:
    def test_substitutes_from_the_run_record(self) -> None:
        result = render_template("FIT={{run:r1.validation.free_run_fit}}", runs=RUNS)
        assert "97.8612" in result.text
        assert result.fully_resolved
        assert result.bindings[0].run_id == "r1"
        assert result.bindings[0].path == "validation.free_run_fit"

    def test_booleans_render_readably(self) -> None:
        result = render_template("稳定性={{run:r1.validation.stable}}", runs=RUNS)
        assert "是" in result.text

    def test_an_unresolvable_placeholder_is_marked_not_blanked(self) -> None:
        """A silently dropped figure is more dangerous than a visibly missing one."""

        result = render_template("值={{run:r1.nope}}", runs=RUNS)
        assert "[未解析数值:r1.nope]" in result.text
        assert not result.fully_resolved
        assert result.unresolved

    def test_every_rendered_number_has_a_binding(self) -> None:
        template = (
            "{{run:r1.validation.free_run_fit}} / {{run:r1.validation.one_step_fit}}"
            " / {{run:r1.training_rows}}"
        )
        result = render_template(template, runs=RUNS)
        assert len(result.bindings) == 3
        assert all(binding.resolved for binding in result.bindings)

    def test_rendered_output_would_now_fail_numeral_validation(self) -> None:
        """The rendered document contains real numbers; only the *draft* must not."""

        result = render_template("FIT={{run:r1.validation.free_run_fit}}", runs=RUNS)
        assert validate_draft(result.text) != []

    def test_execution_step_placeholder_is_distinct_from_processing_run_evidence(self) -> None:
        result = render_template(
            "样本数={{step:s1.n_samples}}",
            runs={"s1": {"n_samples": 1500}},
        )

        assert result.text == "样本数=1500"
        assert result.bindings[0].kind == "step"
        assert result.bindings[0].run_id == "s1"


class TestExecutionScopedReportComposition:
    @staticmethod
    def _clean_only_index() -> RunIndex:
        return RunIndex(
            records={
                "s1": {
                    "tool_name": "profile_dataset",
                    "status": "SUCCEEDED",
                    "summary": "数据画像完成",
                    "n_samples": 1500,
                    "fingerprint": {
                        "values": {
                            "log_sample_count": 0.5132,
                            "missing_ratio": 0.0,
                            "anomaly_ratio": 0.2242,
                        }
                    },
                },
                "s2": {
                    "tool_name": "detect_anomalies",
                    "status": "SUCCEEDED",
                    "summary": "异常检测完成",
                    "anomaly_count": 0,
                    "anomaly_ratio": 0.0025,
                },
                "s3": {
                    "tool_name": "clean_data",
                    "status": "SUCCEEDED",
                    "summary": "数据清洗完成",
                    "total_cleaned_points": 0,
                    "summary_data": {
                        "rows_before": 1500,
                        "rows_after": 1500,
                        "changes": {
                            "unique_changed_cells": 0,
                            "missing_value_fills": 0,
                        },
                    },
                },
            },
            by_type={},
            step_by_tool={
                "profile_dataset": "s1",
                "detect_anomalies": "s2",
                "clean_data": "s3",
            },
            execution_id=uuid4(),
        )

    def test_clean_only_execution_has_scoped_title_and_no_modeling_claims(self) -> None:
        index = self._clean_only_index()
        payload = report_service.ReportRequest(
            execution_id=index.execution_id,
            dataset_id=uuid4(),
            version_id=uuid4(),
        )

        sections = _number_sections(_compose(index, payload))
        text = "\n".join(f"{section.title}\n{section.body}" for section in sections)

        assert _report_title(index, payload) == "IndusOpt 数据质量分析与清洗报告"
        assert [section.key for section in sections] == [
            "overview",
            "profile",
            "anomaly",
            "cleaning",
            "limitations",
        ]
        assert [section.title.split("、", 1)[0] for section in sections] == [
            "一",
            "二",
            "三",
            "四",
            "五",
        ]
        for forbidden in ("D-最优", "ARX", "Optuna", "模型评价"):
            assert forbidden not in text

    def test_execution_report_formats_only_explicit_fraction_metrics_as_percentages(
        self,
    ) -> None:
        index = self._clean_only_index()
        payload = report_service.ReportRequest(
            execution_id=index.execution_id,
            dataset_id=uuid4(),
            version_id=uuid4(),
        )
        sections = _number_sections(_compose(index, payload))
        template = "\n\n".join(
            f"## {section.title}\n\n{section.body}" for section in sections
        )
        template += "\n\n画像规模指纹 {{step:s1.fingerprint.values.log_sample_count}}"

        rendered = render_template(
            template,
            runs=index.records,
            formatters=_presentation_formatters(index),
        )

        assert "画像离群比例 22.42%" in rendered.text
        assert "疑似异常比例 0.25%" in rendered.text
        assert "缺失比例 0.00%" in rendered.text
        assert "画像规模指纹 0.5132" in rendered.text
        assert "51.32%" not in rendered.text
        anomaly_binding = next(
            binding
            for binding in rendered.bindings
            if binding.path == "fingerprint.values.anomaly_ratio"
        )
        assert anomaly_binding.value == "0.2242"

    def test_generate_report_returns_percentage_formatted_final_markdown(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        index = self._clean_only_index()
        dataset_id = uuid4()
        version_id = uuid4()
        payload = report_service.ReportRequest(
            execution_id=index.execution_id,
            dataset_id=dataset_id,
            version_id=version_id,
        )

        async def fake_build_execution_run_index(
            session: AsyncSession,
            *,
            execution_id: object,
            dataset_id: object,
            version_id: object,
        ) -> RunIndex:
            return index

        persisted = []

        async def fake_persist(
            session: AsyncSession,
            *,
            report_id: object,
            payload: object,
            rendered: object,
        ) -> None:
            persisted.append(rendered)

        monkeypatch.setattr(
            report_service,
            "build_execution_run_index",
            fake_build_execution_run_index,
        )
        monkeypatch.setattr(report_service, "_persist", fake_persist)

        data = asyncio.run(
            report_service.generate_report(
                SimpleNamespace(),
                payload=payload,
                artifact_root=tmp_path,
            )
        )

        assert "画像离群比例 22.42%" in data.markdown
        assert "疑似异常比例 0.25%" in data.markdown
        assert "画像异常比例 0.2242" not in data.markdown
        assert "疑似异常比例 0.0025" not in data.markdown
        assert "0.5132" not in data.markdown
        assert "51.32%" not in data.markdown

        binding_values = {
            binding.path: binding.value
            for binding in data.bindings
            if binding.path in {
                "fingerprint.values.anomaly_ratio",
                "anomaly_ratio",
            }
        }
        assert binding_values == {
            "fingerprint.values.anomaly_ratio": "0.2242",
            "anomaly_ratio": "0.0025",
        }
        assert persisted
        artifact = tmp_path / data.artifact_uri
        assert "画像离群比例 22.42%" in artifact.read_text(encoding="utf-8")
        assert "疑似异常比例 0.25%" in artifact.read_text(encoding="utf-8")

    def test_only_executed_capabilities_create_sections(self) -> None:
        segment_index = RunIndex(
            records={"s1": {"tool_name": "detect_dynamic_segments", "summary": "优选完成"}},
            by_type={},
            step_by_tool={"detect_dynamic_segments": "s1"},
            execution_id=uuid4(),
        )
        model_index = RunIndex(
            records={
                "s1": {"tool_name": "fit_arx", "summary": "辨识完成"},
                "s2": {"tool_name": "evaluate_model", "summary": "评价完成"},
            },
            by_type={},
            step_by_tool={"fit_arx": "s1", "evaluate_model": "s2"},
            execution_id=uuid4(),
        )

        segment_sections = {section.key for section in _compose(segment_index, report_service.ReportRequest(execution_id=segment_index.execution_id))}
        model_sections = {section.key for section in _compose(model_index, report_service.ReportRequest(execution_id=model_index.execution_id))}

        assert "selection" in segment_sections
        assert "model" not in segment_sections
        assert "model" in model_sections
        assert "evaluation" in model_sections
        assert _report_title(model_index, report_service.ReportRequest(execution_id=model_index.execution_id)) == "IndusOpt 动态建模与系统辨识报告"

    def test_execution_index_loads_only_explicit_processing_run_ids(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        execution_id = uuid4()
        dataset_id = uuid4()
        version_id = uuid4()
        explicit_run_id = uuid4()
        historical_segment_id = uuid4()
        execution = SimpleNamespace(
            id=execution_id,
            dataset_id=dataset_id,
            current_version_id=version_id,
            step_runs=[
                SimpleNamespace(
                    step_id="profile",
                    sequence=1,
                    tool_name="profile_dataset",
                    status="SUCCEEDED",
                    source_version_id=version_id,
                    result_version_id=None,
                    result_payload={"summary": "画像完成", "result": {"n_samples": 1500}},
                    processing_run_ids=[],
                    started_at=None,
                    finished_at=None,
                ),
                SimpleNamespace(
                    step_id="clean",
                    sequence=2,
                    tool_name="clean_data",
                    status="SUCCEEDED",
                    source_version_id=version_id,
                    result_version_id=version_id,
                    result_payload={"total_cleaned_points": 0},
                    processing_run_ids=[str(explicit_run_id)],
                    started_at=None,
                    finished_at=None,
                ),
            ],
        )
        explicit_run = SimpleNamespace(
            id=explicit_run_id,
            dataset_id=dataset_id,
            source_version_id=uuid4(),  # Explicitly linked intermediate version.
            run_type="preprocessing.clean",
            status="succeeded",
            parameters={},
            result={"total_cleaned_points": 0},
            created_at=None,
        )

        async def fake_get_execution(session: object, *, execution_id: object) -> object:
            return execution

        class FakeSession:
            def __init__(self) -> None:
                self.requested_ids: list[object] = []

            async def get(self, model: object, identifier: object) -> object:
                self.requested_ids.append(identifier)
                return explicit_run if identifier == explicit_run_id else None

        monkeypatch.setattr(report_service, "get_execution", fake_get_execution)
        session = FakeSession()
        index = asyncio.run(
            build_execution_run_index(
                session,
                execution_id=execution_id,
                dataset_id=dataset_id,
                version_id=version_id,
            )
        )

        assert session.requested_ids == [explicit_run_id]
        assert historical_segment_id not in session.requested_ids
        assert index.by_type == {
            "preprocessing.clean": f"r{str(explicit_run_id).replace('-', '')[:8]}"
        }
        assert "preprocessing.segment" not in index.by_type


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'report.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(prepare())

    async def session_override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    async def dispose_test_engine() -> None:
        return None

    monkeypatch.setattr("app.api.routes.get_settings", lambda: Settings(artifact_root=tmp_path))
    monkeypatch.setattr("app.main.dispose_engine", dispose_test_engine)
    app = create_app()
    app.state.report_test_session_factory = session_factory
    app.dependency_overrides[get_session] = session_override
    with TestClient(app) as client:
        yield client
    asyncio.run(engine.dispose())


def run_pipeline(client: TestClient) -> str:
    """Drive the real pipeline so the report has genuine runs to cite."""

    generated = client.post(
        "/api/v1/simulation/generate",
        json={"scenario": "S2", "n_steps": 2500, "seed": 12, "input_count": 2},
    )
    assert generated.status_code == 201, generated.text
    version_id = generated.json()["data"]["version_id"]

    lagged = client.post(
        "/api/v1/preprocessing/delay/apply",
        json={
            "version_id": version_id,
            "lag_map": {"u1": 3, "u2": 8},
            "user_confirmed": True,
            "recommendation_source": "manual",
            "evidence_summary": {"fixture": "known_simulation_lags"},
        },
    )
    assert lagged.status_code == 201, lagged.text
    version_id = lagged.json()["data"]["result_version_id"]

    segment = client.post(
        "/api/v1/preprocessing/segment",
        json={
            "version_id": version_id,
            "input_columns": ["u1", "u2"],
            "output_column": "y",
            "window_size": 60,
            "max_segments": 6,
        },
    )
    assert segment.status_code == 202, segment.text

    fitted = client.post(
        "/api/v1/modeling/arx/fit",
        json={
            "version_id": version_id,
            "input_columns": ["u1", "u2"],
            "output_column": "y",
            "na": 2,
            "nb": [2, 2],
            "delays": [3, 8],
        },
    )
    assert fitted.status_code == 200, fitted.text
    return version_id


class TestReportApi:
    def test_report_cites_real_runs_and_binds_every_number(self, client: TestClient) -> None:
        version_id = run_pipeline(client)
        response = client.post("/api/v1/reports/generate", json={"version_id": version_id})
        assert response.status_code == 200, response.text
        data = response.json()["data"]

        assert data["bindings"], "the report must bind at least one figure to a run"
        assert data["fully_resolved"] is True
        assert data["unresolved"] == []
        for binding in data["bindings"]:
            assert binding["run_id"]
            assert binding["resolved"] is True
        assert data["cited_runs"] == sorted({binding["run_id"] for binding in data["bindings"]})
        assert any(section["key"] == "selection" for section in data["sections"])
        assert any(section["key"] == "model" for section in data["sections"])

    def test_report_body_contains_no_placeholder_left_over(self, client: TestClient) -> None:
        version_id = run_pipeline(client)
        data = client.post("/api/v1/reports/generate", json={"version_id": version_id}).json()[
            "data"
        ]
        assert "{{" not in data["markdown"]

    def test_report_artifact_is_written_to_disk(self, client: TestClient, tmp_path: Path) -> None:
        version_id = run_pipeline(client)
        data = client.post("/api/v1/reports/generate", json={"version_id": version_id}).json()[
            "data"
        ]
        assert (tmp_path / data["artifact_uri"]).is_file()
        html_path = tmp_path / data["html_artifact_uri"]
        assert html_path.is_file()
        assert html_path.read_text(encoding="utf-8") == data["html"]
        assert "<svg" in data["html"]
        assert {chart["key"] for chart in data["charts"]} == {"selection"}
        selection_chart = data["charts"][0]
        assert selection_chart["source_path"] == "selected_sample_indices"
        assert selection_chart["source_run_id"]
        assert "@page{size:A4" in data["html"]
        assert "@media print" in data["html"]
        assert '<script src="http' not in data["html"]
        assert '<link href="http' not in data["html"]
        assert '<img src="http' not in data["html"]

    def test_report_without_runs_is_refused(self, client: TestClient) -> None:
        response = client.post("/api/v1/reports/generate", json={"version_id": str(uuid4())})
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "REPORT_NO_RUNS"

    def test_failed_processing_run_is_not_report_evidence(self, client: TestClient) -> None:
        generated = client.post(
            "/api/v1/simulation/generate",
            json={"scenario": "S1", "n_steps": 900, "seed": 17, "input_count": 1},
        ).json()["data"]

        async def seed_failed_run() -> None:
            session_factory = client.app.state.report_test_session_factory
            async with session_factory() as session:
                now = datetime.now(UTC)
                session.add(
                    ProcessingRun(
                        dataset_id=UUID(generated["dataset_id"]),
                        source_version_id=UUID(generated["version_id"]),
                        run_type="preprocessing.clean",
                        status="failed",
                        parameters={},
                        result={"total_cleaned_points": 999},
                        created_at=now,
                        finished_at=now,
                    )
                )
                await session.commit()

        asyncio.run(seed_failed_run())
        response = client.post(
            "/api/v1/reports/generate",
            json={
                "dataset_id": generated["dataset_id"],
                "version_id": generated["version_id"],
            },
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "REPORT_NO_RUNS"

    def test_report_rejects_study_from_another_dataset(self, client: TestClient) -> None:
        first = client.post(
            "/api/v1/simulation/generate",
            json={"scenario": "S1", "n_steps": 900, "seed": 18, "input_count": 1},
        ).json()["data"]
        second = client.post(
            "/api/v1/simulation/generate",
            json={"scenario": "S1", "n_steps": 900, "seed": 19, "input_count": 1},
        ).json()["data"]
        segment = client.post(
            "/api/v1/preprocessing/segment",
            json={
                "dataset_id": first["dataset_id"],
                "version_id": first["version_id"],
                "input_columns": ["u1"],
                "output_column": "y",
                "window_size": 60,
                "max_segments": 2,
            },
        )
        assert segment.status_code == 202, segment.text
        study_id = uuid4()

        async def seed_foreign_study() -> None:
            session_factory = client.app.state.report_test_session_factory
            async with session_factory() as session:
                now = datetime.now(UTC)
                session.add(
                    OptimizationStudy(
                        id=study_id,
                        dataset_id=UUID(second["dataset_id"]),
                        version_id=UUID(second["version_id"]),
                        status="succeeded",
                        objective="val_free_run_fit",
                        parameters={},
                        best_trial_number=0,
                        best_value=1.0,
                        best_params={},
                        optimized_model_id=uuid4(),
                        fingerprint={},
                        statistics={},
                        created_at=now,
                        finished_at=now,
                    )
                )
                await session.commit()

        asyncio.run(seed_foreign_study())
        response = client.post(
            "/api/v1/reports/generate",
            json={
                "dataset_id": first["dataset_id"],
                "version_id": first["version_id"],
                "study_id": str(study_id),
            },
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "OPTIMIZATION_STUDY_DATASET_MISMATCH"

    def test_report_accepts_a_cleaning_derived_version(self, client: TestClient) -> None:
        generated = client.post(
            "/api/v1/simulation/generate",
            json={"scenario": "S4", "n_steps": 1200, "seed": 77, "input_count": 2},
        )
        assert generated.status_code == 201, generated.text
        source_version_id = generated.json()["data"]["version_id"]

        cleaned = client.post(
            "/api/v1/preprocessing/clean",
            json={
                "version_id": source_version_id,
                "target_sample_period_seconds": 1.0,
                "interpolation": "linear",
                "anomaly_detector": "hampel",
                "hampel_window": 5,
            },
        )
        assert cleaned.status_code == 202, cleaned.text
        derived_version_id = cleaned.json()["data"]["derived_version_id"]

        response = client.post(
            "/api/v1/reports/generate", json={"version_id": derived_version_id}
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["fully_resolved"] is True
        assert data["unresolved"] == []
        assert any(section["key"] == "cleaning" for section in data["sections"])


class TestExportApi:
    def test_export_writes_the_selected_rows_and_a_manifest(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        version_id = run_pipeline(client)
        response = client.post(
            "/api/v1/delivery/export",
            json={
                "version_id": version_id,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]

        assert data["exported_rows"] > 0
        assert data["exported_rows"] < data["source_rows"], "export must be a real subset"
        assert 0 < data["coverage_ratio"] < 1

        csv_path = tmp_path / data["csv_uri"]
        assert csv_path.is_file()
        with csv_path.open(encoding="utf-8") as handle:
            rows = list(csv.reader(handle))
        assert rows[0] == data["columns"]
        assert len(rows) - 1 == data["exported_rows"]

        manifest = json.loads((tmp_path / data["manifest_uri"]).read_text(encoding="utf-8"))
        assert manifest["version_id"] == version_id
        assert manifest["exported_rows"] == data["exported_rows"]

        csv_download = client.get(f"/api/v1/delivery/exports/{data['export_id']}/csv")
        manifest_download = client.get(
            f"/api/v1/delivery/exports/{data['export_id']}/manifest"
        )
        assert csv_download.status_code == 200
        assert csv_download.headers["content-type"].startswith("text/csv")
        assert manifest_download.status_code == 200
        assert manifest_download.json()["exported_rows"] == data["exported_rows"]

    def test_explicit_indices_are_honoured(self, client: TestClient) -> None:
        version_id = run_pipeline(client)
        response = client.post(
            "/api/v1/delivery/export",
            json={
                "version_id": version_id,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "sample_indices": [100, 101, 102, 103],
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["exported_rows"] == 4

    def test_export_without_a_selection_is_refused(self, client: TestClient) -> None:
        generated = client.post(
            "/api/v1/simulation/generate",
            json={"scenario": "S1", "n_steps": 1200, "seed": 3, "input_count": 1},
        )
        version_id = generated.json()["data"]["version_id"]
        response = client.post(
            "/api/v1/delivery/export",
            json={"version_id": version_id, "input_columns": ["u1"], "output_column": "y"},
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "EXPORT_NO_SELECTION"

    def test_strict_best_export_uses_model_training_rows_not_ordinary_segment(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        generated_response = client.post(
            "/api/v1/simulation/generate",
            json={"scenario": "S2", "n_steps": 1200, "seed": 77, "input_count": 2},
        )
        assert generated_response.status_code == 201, generated_response.text
        generated = generated_response.json()["data"]
        dataset_id = generated["dataset_id"]
        lagged_response = client.post(
            "/api/v1/preprocessing/delay/apply",
            json={
                "dataset_id": dataset_id,
                "version_id": generated["version_id"],
                "lag_map": {"u1": 3, "u2": 8},
                "user_confirmed": True,
                "recommendation_source": "manual",
            },
        )
        assert lagged_response.status_code == 201, lagged_response.text
        version_id = lagged_response.json()["data"]["result_version_id"]

        ordinary_response = client.post(
            "/api/v1/preprocessing/segment",
            json={
                "dataset_id": dataset_id,
                "version_id": version_id,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "window_size": 60,
                "max_segments": 2,
            },
        )
        assert ordinary_response.status_code == 202, ordinary_response.text
        ordinary_indices = ordinary_response.json()["data"]["selected_indices"]
        best_indices = list(range(80, 560, 2))
        assert best_indices != ordinary_indices

        fitted_response = client.post(
            "/api/v1/modeling/arx/fit",
            json={
                "dataset_id": dataset_id,
                "version_id": version_id,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "na": 2,
                "nb": [2, 2],
                "delays": [3, 8],
                "training_sample_indices": best_indices,
            },
        )
        assert fitted_response.status_code == 200, fitted_response.text
        fitted_data = fitted_response.json()["data"]
        model_id = fitted_data["model_id"]
        model_run_id = UUID(fitted_data["processing_run_id"])
        model_artifact = tmp_path / fitted_data["artifact_uri"]
        study_id = uuid4()
        older_study_id = uuid4()

        async def seed_study() -> None:
            session_factory = client.app.state.report_test_session_factory
            async with session_factory() as session:
                now = datetime.now(UTC)
                study = OptimizationStudy(
                    id=study_id,
                    dataset_id=UUID(dataset_id),
                    version_id=UUID(version_id),
                    status="succeeded",
                    objective="free_run_fit",
                    parameters={},
                    best_trial_number=4,
                    best_value=88.5,
                    best_params={"window_size": 60},
                    optimized_model_id=UUID(model_id),
                    fingerprint={},
                    statistics={},
                    created_at=now,
                    finished_at=now,
                )
                session.add(study)
                session.add(
                    OptimizationStudy(
                        id=older_study_id,
                        dataset_id=UUID(dataset_id),
                        version_id=UUID(version_id),
                        status="succeeded",
                        objective="free_run_fit",
                        parameters={},
                        best_trial_number=5,
                        best_value=87.0,
                        best_params={"window_size": 60},
                        optimized_model_id=UUID(model_id),
                        fingerprint={},
                        statistics={},
                        created_at=now - timedelta(hours=1),
                        finished_at=now - timedelta(hours=1),
                    )
                )
                session.add(
                    OptimizationTrialRecord(
                        study_id=study.id,
                        trial_number=4,
                        state="complete",
                        value=88.5,
                        params={"window_size": 60},
                        metrics={"val_free_run_fit": 88.5},
                        cache_hit=False,
                        created_at=now,
                        finished_at=now,
                    )
                )
                session.add(
                    OptimizationTrialRecord(
                        study_id=older_study_id,
                        trial_number=5,
                        state="complete",
                        value=87.0,
                        params={"window_size": 60},
                        metrics={"val_free_run_fit": 87.0},
                        cache_hit=False,
                        created_at=now - timedelta(hours=1),
                        finished_at=now - timedelta(hours=1),
                    )
                )
                await session.commit()

        asyncio.run(seed_study())
        listed = client.get(
            "/api/v1/delivery/studies",
            params={"dataset_id": dataset_id, "version_id": version_id},
        )
        assert listed.status_code == 200, listed.text
        assert [item["study_id"] for item in listed.json()["data"]["items"]] == [
            str(study_id),
            str(older_study_id),
        ]

        response = client.post(
            "/api/v1/delivery/export",
            json={
                "dataset_id": dataset_id,
                "version_id": version_id,
                "study_id": str(study_id),
                "mode": "optimization_best",
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        manifest = json.loads((tmp_path / data["manifest_uri"]).read_text(encoding="utf-8"))
        assert manifest["selection_source"] == "optimization_best_trial"
        assert manifest["study_id"] == str(study_id)
        assert manifest["optimized_model_id"] == model_id
        assert manifest["selected_sample_indices"] == best_indices
        assert manifest["selected_sample_indices"] != ordinary_indices

        lineage = client.get(f"/api/v1/datasets/{dataset_id}/versions").json()["data"]
        source_node = next(node for node in lineage["nodes"] if node["id"] == version_id)
        with (tmp_path / source_node["artifact_path"]).open(encoding="utf-8") as source_handle:
            source_rows = list(csv.reader(source_handle))
        with (tmp_path / data["csv_uri"]).open(encoding="utf-8") as export_handle:
            exported_rows = list(csv.reader(export_handle))
        assert exported_rows[0] == source_rows[0]
        assert exported_rows[1:] == [source_rows[index + 1] for index in best_indices]

        def strict_export(
            *, requested_dataset_id: str = dataset_id, requested_version_id: str = version_id
        ):
            return client.post(
                "/api/v1/delivery/export",
                json={
                    "dataset_id": requested_dataset_id,
                    "version_id": requested_version_id,
                    "study_id": str(study_id),
                    "mode": "optimization_best",
                },
            )

        async def mutate_lineage(
            *,
            study_status: str = "succeeded",
            best_trial_number: int | None = 4,
            remove_optimized_model: bool = False,
            trial_state: str = "complete",
            model_run_status: str = "succeeded",
            run_indices: list[int] = best_indices,
        ) -> None:
            session_factory = client.app.state.report_test_session_factory
            async with session_factory() as session:
                study = await session.get(OptimizationStudy, study_id)
                trial = await session.scalar(
                    select(OptimizationTrialRecord).where(
                        OptimizationTrialRecord.study_id == study_id,
                        OptimizationTrialRecord.trial_number == 4,
                    )
                )
                model_run = await session.get(ProcessingRun, model_run_id)
                assert study is not None and trial is not None and model_run is not None
                study.status = study_status
                study.best_trial_number = best_trial_number
                study.optimized_model_id = None if remove_optimized_model else UUID(model_id)
                trial.state = trial_state
                model_run.status = model_run_status
                model_run.parameters = {
                    **dict(model_run.parameters or {}),
                    "training_sample_indices": run_indices,
                }
                await session.commit()

        asyncio.run(mutate_lineage(study_status="failed"))
        rejected = strict_export()
        assert rejected.status_code == 409
        assert rejected.json()["error"]["code"] == "OPTIMIZATION_STUDY_NOT_SUCCEEDED"
        asyncio.run(mutate_lineage())

        rejected = strict_export(requested_dataset_id=str(uuid4()))
        assert rejected.status_code == 409
        assert rejected.json()["error"]["code"] == "OPTIMIZATION_STUDY_DATASET_MISMATCH"
        rejected = strict_export(requested_version_id=str(uuid4()))
        assert rejected.status_code == 409
        assert rejected.json()["error"]["code"] == "OPTIMIZATION_STUDY_VERSION_MISMATCH"

        asyncio.run(mutate_lineage(best_trial_number=None))
        rejected = strict_export()
        assert rejected.status_code == 409
        assert rejected.json()["error"]["code"] == "OPTIMIZATION_BEST_TRIAL_MISSING"
        asyncio.run(mutate_lineage(trial_state="failed"))
        rejected = strict_export()
        assert rejected.status_code == 409
        assert rejected.json()["error"]["code"] == "OPTIMIZATION_BEST_TRIAL_INVALID"
        asyncio.run(mutate_lineage(remove_optimized_model=True))
        rejected = strict_export()
        assert rejected.status_code == 409
        assert rejected.json()["error"]["code"] == "OPTIMIZATION_BEST_MODEL_MISSING"
        asyncio.run(mutate_lineage())

        missing_artifact = model_artifact.with_suffix(".missing")
        model_artifact.rename(missing_artifact)
        try:
            rejected = strict_export()
            assert rejected.status_code == 409
            assert (
                rejected.json()["error"]["code"]
                == "OPTIMIZATION_BEST_MODEL_ARTIFACT_INVALID"
            )
        finally:
            missing_artifact.rename(model_artifact)

        asyncio.run(mutate_lineage(model_run_status="failed"))
        rejected = strict_export()
        assert rejected.status_code == 409
        assert rejected.json()["error"]["code"] == "OPTIMIZATION_BEST_MODEL_RUN_MISSING"
        asyncio.run(mutate_lineage())

        original_artifact = json.loads(model_artifact.read_text(encoding="utf-8"))

        def write_model_indices(indices: list[int]) -> None:
            changed = {**original_artifact}
            changed["configuration"] = {
                **dict(original_artifact["configuration"]),
                "training_sample_indices": indices,
            }
            model_artifact.write_text(json.dumps(changed), encoding="utf-8")

        try:
            for invalid_indices, expected_code in (
                ([80, 80], "OPTIMIZATION_BEST_SELECTION_INVALID"),
                ([99_999], "OPTIMIZATION_BEST_SELECTION_INVALID"),
                ([1_000], "OPTIMIZATION_BEST_SELECTION_TEST_LEAKAGE"),
            ):
                write_model_indices(invalid_indices)
                asyncio.run(mutate_lineage(run_indices=invalid_indices))
                rejected = strict_export()
                assert rejected.status_code == 409
                assert rejected.json()["error"]["code"] == expected_code
        finally:
            model_artifact.write_text(
                json.dumps(original_artifact),
                encoding="utf-8",
            )
            asyncio.run(mutate_lineage())

    def test_strict_best_export_refuses_missing_study(self, client: TestClient) -> None:
        generated = client.post(
            "/api/v1/simulation/generate",
            json={"scenario": "S1", "n_steps": 900, "seed": 31, "input_count": 1},
        ).json()["data"]
        response = client.post(
            "/api/v1/delivery/export",
            json={
                "dataset_id": generated["dataset_id"],
                "version_id": generated["version_id"],
                "mode": "optimization_best",
            },
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "OPTIMIZATION_BEST_SCOPE_REQUIRED"


def test_processing_run_scope_requires_dataset_and_version_when_both_are_requested() -> None:
    requested_dataset = uuid4()
    other_dataset = uuid4()
    requested_version = uuid4()
    other_version = uuid4()
    same_dataset_old_version = ProcessingRun(
        dataset_id=requested_dataset,
        source_version_id=other_version,
        run_type="preprocessing.clean",
        status="succeeded",
        parameters={},
        result={"effective_version_id": str(other_version)},
    )
    same_version_other_dataset = ProcessingRun(
        dataset_id=other_dataset,
        source_version_id=requested_version,
        run_type="preprocessing.clean",
        status="succeeded",
        parameters={},
        result={"effective_version_id": str(requested_version)},
    )
    exact_scope = ProcessingRun(
        dataset_id=requested_dataset,
        source_version_id=other_version,
        run_type="preprocessing.clean",
        status="succeeded",
        parameters={},
        result={"effective_version_id": str(requested_version)},
    )

    assert not _matches(
        same_dataset_old_version,
        dataset_id=requested_dataset,
        version_id=requested_version,
    )
    assert not _matches(
        same_version_other_dataset,
        dataset_id=requested_dataset,
        version_id=requested_version,
    )
    assert _matches(exact_scope, dataset_id=requested_dataset, version_id=requested_version)
    assert _matches(same_dataset_old_version, dataset_id=requested_dataset, version_id=None)
    assert _matches(same_version_other_dataset, dataset_id=None, version_id=requested_version)
