"""Report assembly and optimised-dataset export (phase 10).

Agent reports are composed from their persisted step results and explicitly linked
``ProcessingRun`` records. Standalone reports retain dataset/version-scoped run lookup.
Every figure enters through a typed placeholder, so the document is a view over persisted
evidence rather than a retelling of in-memory state. :mod:`algorithms.report.provenance`
enforces that a draft containing a bare numeral is rejected before rendering.

Export writes the rows the closed loop actually selected, plus a manifest recording which
runs produced the selection, so the delivered CSV can be traced back to the decisions that
shaped it.
"""

from __future__ import annotations

import csv
import html as html_lib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import numpy as np
from algorithms.agent.llm import LlmProvider
from algorithms.agent.llm_planner import LlmNarrator, NarrationOutcome
from algorithms.report.provenance import (
    RenderResult,
    format_fraction_percent,
    render_template,
    resolve_path,
    validate_draft,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_execution import AgentStepRun
from app.models.dataset import Dataset, DatasetVersion, ProcessingRun
from app.models.operation_log import OperationLog
from app.models.optimization import OptimizationStudy, OptimizationTrialRecord
from app.schemas.reporting import (
    DeliveryStudyListData,
    DeliveryStudyOption,
    ExportDatasetData,
    ExportDatasetRequest,
    ExportSelectionProvenance,
    ReportBinding,
    ReportChart,
    ReportData,
    ReportRequest,
    ReportSection,
)
from app.services.agent_execution_service import ExecutionStateError, get_execution
from app.services.contract_stubs import completed_task
from app.services.modeling_service import ModelingDomainError, load_saved_arx_model
from app.services.version_data import VersionDataError, load_version_series

# Reports cite recent work, not the whole history; this bounds the scan below.
RUN_SCAN_LIMIT = 500
NON_ANALYSIS_RUN_TYPES = frozenset({"reporting.generate", "delivery.export"})


class ReportDomainError(Exception):
    """A client-safe reporting failure for the standard error envelope."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


@dataclass(frozen=True)
class RunIndex:
    """Persisted runs keyed by short id, as the placeholder resolver sees them."""

    records: dict[str, dict[str, Any]]
    by_type: dict[str, str]
    step_by_tool: dict[str, str]
    execution_id: UUID | None

    def latest(self, run_type: str) -> str | None:
        return self.by_type.get(run_type)


@dataclass(frozen=True)
class OptimizationBestSelection:
    sample_indices: list[int]
    provenance: ExportSelectionProvenance
    input_columns: list[str]
    output_column: str
    best_trial: OptimizationTrialRecord
    model_run: ProcessingRun


async def build_run_index(
    session: AsyncSession,
    *,
    dataset_id: UUID | None,
    version_id: UUID | None,
) -> RunIndex:
    """Load the runs a report may cite, newest first per type."""

    statement = (
        select(ProcessingRun)
        .where(
            ProcessingRun.status == "succeeded",
            ProcessingRun.run_type.notin_(NON_ANALYSIS_RUN_TYPES),
        )
        .order_by(ProcessingRun.created_at.desc())
        .limit(RUN_SCAN_LIMIT)
    )
    runs = list((await session.scalars(statement)).all())
    runs = [run for run in runs if _matches(run, dataset_id=dataset_id, version_id=version_id)]

    records: dict[str, dict[str, Any]] = {}
    by_type: dict[str, str] = {}
    for run in runs:
        short = _short_id(run.id)
        records[short] = {
            "run_id": str(run.id),
            "run_type": run.run_type,
            "status": run.status,
            "parameters": dict(run.parameters or {}),
            "created_at": run.created_at.isoformat() if run.created_at else "",
            **(run.result or {}),
        }
        by_type.setdefault(run.run_type, short)
    return RunIndex(records=records, by_type=by_type, step_by_tool={}, execution_id=None)


async def build_execution_run_index(
    session: AsyncSession,
    *,
    execution_id: UUID,
    dataset_id: UUID | None,
    version_id: UUID | None,
) -> RunIndex:
    """Index one execution's persisted steps and only their explicitly linked runs."""

    try:
        execution = await get_execution(session, execution_id=execution_id)
    except ExecutionStateError as error:
        raise ReportDomainError(
            "REPORT_EXECUTION_NOT_FOUND",
            "报告绑定的 Agent 执行不存在。",
            status_code=404,
        ) from error
    if dataset_id != execution.dataset_id or version_id != execution.current_version_id:
        raise ReportDomainError(
            "REPORT_EXECUTION_SCOPE_MISMATCH",
            "报告请求的数据集或版本与当前 Agent 执行不一致。",
            status_code=409,
            details={
                "execution_id": str(execution.id),
                "execution_dataset_id": str(execution.dataset_id),
                "execution_version_id": str(execution.current_version_id),
            },
        )

    records: dict[str, dict[str, Any]] = {}
    step_by_tool: dict[str, str] = {}
    referenced_run_ids: list[UUID] = []
    for step in sorted(execution.step_runs, key=lambda item: item.sequence):
        if step.status != "SUCCEEDED":
            continue
        key = f"step{step.sequence}"
        records[key] = _step_record(step)
        step_by_tool.setdefault(step.tool_name, key)
        for raw_run_id in step.processing_run_ids:
            try:
                run_id = UUID(raw_run_id)
            except (TypeError, ValueError):
                continue
            if run_id not in referenced_run_ids:
                referenced_run_ids.append(run_id)

    by_type: dict[str, str] = {}
    for run_id in referenced_run_ids:
        run = await session.get(ProcessingRun, run_id)
        if run is None or run.status != "succeeded":
            continue
        if run.run_type in NON_ANALYSIS_RUN_TYPES or not _matches(run, dataset_id=dataset_id, version_id=None):
            continue
        short = _short_id(run.id)
        records[short] = {
            "run_id": str(run.id),
            "run_type": run.run_type,
            "status": run.status,
            "parameters": dict(run.parameters or {}),
            "created_at": run.created_at.isoformat() if run.created_at else "",
            **(run.result or {}),
        }
        by_type[run.run_type] = short
    optimize_key = step_by_tool.get("optimize_pipeline")
    if optimize_key:
        raw_study_id = records[optimize_key].get("study_id")
        if raw_study_id:
            study = await session.get(OptimizationStudy, UUID(str(raw_study_id)))
            if (study is None or study.dataset_id != execution.dataset_id
                    or str(study.version_id) != records[optimize_key].get("source_version_id")):
                raise ReportDomainError("REPORT_STUDY_SCOPE_MISMATCH", "Agent 寻优记录与当前执行的来源不一致")
            records[optimize_key]["trial_curve"] = await _study_trial_curve(session, study.id)
    return RunIndex(
        records=records,
        by_type=by_type,
        step_by_tool=step_by_tool,
        execution_id=execution.id,
    )


async def _study_trial_curve(session: AsyncSession, study_id: UUID) -> list[dict[str, Any]]:
    records = list((await session.scalars(select(OptimizationTrialRecord)
        .where(OptimizationTrialRecord.study_id == study_id)
        .order_by(OptimizationTrialRecord.trial_number))).all())
    curve, best = [], None
    for trial in records:
        if trial.state == "complete" and trial.value is not None and np.isfinite(trial.value):
            best = max(best, float(trial.value)) if best is not None else float(trial.value)
        if best is not None:
            curve.append({"trial_number": trial.trial_number, "best_value": best, "state": trial.state})
    return curve


def _step_record(step: AgentStepRun) -> dict[str, Any]:
    payload = dict(step.result_payload or {})
    result = dict(payload["result"]) if isinstance(payload.get("result"), Mapping) else payload
    summary_data = result.get("summary") if isinstance(result.get("summary"), Mapping) else None
    summary = payload.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        task_value = result.get("task")
        task: Mapping[str, Any] = task_value if isinstance(task_value, Mapping) else {}
        progress_value = task.get("progress")
        progress: Mapping[str, Any] = (
            progress_value if isinstance(progress_value, Mapping) else {}
        )
        summary = progress.get("message") if isinstance(progress.get("message"), str) else ""
    record: dict[str, Any] = {
        "step_id": step.step_id,
        "tool_name": step.tool_name,
        "status": step.status,
        "summary": summary,
        "source_version_id": str(step.source_version_id) if step.source_version_id else "",
        "result_version_id": str(step.result_version_id) if step.result_version_id else "",
        "processing_run_ids": list(step.processing_run_ids),
        **result,
    }
    record["summary"] = summary
    if summary_data is not None:
        record["summary_data"] = dict(summary_data)
    return record


async def generate_report(
    session: AsyncSession,
    *,
    payload: ReportRequest,
    artifact_root: Path,
    provider: LlmProvider | None = None,
) -> ReportData:
    """Compose, validate and render a provenance-bound report.

    When a model is configured it writes the closing engineering commentary, under the rule
    that it may not emit a single digit. Its draft goes through the same numeral validator
    as everything else, so a model that ignores the rule produces a rejected paragraph and
    the templated conclusion stands instead.
    """

    if payload.execution_id is not None:
        index = await build_execution_run_index(
            session,
            execution_id=payload.execution_id,
            dataset_id=payload.dataset_id,
            version_id=payload.version_id,
        )
    else:
        index = await build_run_index(
            session, dataset_id=payload.dataset_id, version_id=payload.version_id
        )
    if not index.records:
        raise ReportDomainError(
            "REPORT_NO_RUNS",
            "该数据集尚无可引用的处理运行记录，无法生成报告。",
            status_code=404,
        )

    if payload.execution_id is None:
        await _add_dataset_context(session, index=index, payload=payload)
    if payload.execution_id is None and payload.study_id is not None:
        if payload.dataset_id is None or payload.version_id is None:
            raise ReportDomainError(
                "REPORT_STUDY_SCOPE_REQUIRED",
                "关联寻优任务时必须同时指定数据集和数据版本。",
            )
        selection = await resolve_optimization_best_selection(
            session,
            dataset_id=payload.dataset_id,
            version_id=payload.version_id,
            study_id=payload.study_id,
            artifact_root=artifact_root,
        )
        study = await session.get(OptimizationStudy, payload.study_id)
        assert study is not None
        index.records["study"] = {
            "best_value": study.best_value,
            "best_params": dict(study.best_params or {}),
            "statistics": dict(study.statistics or {}),
            "objective": study.objective,
            "best_trial_number": study.best_trial_number,
            "finished_at": study.finished_at.isoformat() if study.finished_at else "",
            "optimized_model_id": str(study.optimized_model_id),
            "best_trial_metrics": dict(selection.best_trial.metrics or {}),
            "trial_curve": await _study_trial_curve(session, study.id),
        }

    sections = _compose(index, payload)
    await _add_cleaning_preview(session, index=index, payload=payload, artifact_root=artifact_root)
    narration = _narrate(provider or _resolve_provider(), index=index, sections=sections)
    if narration.text:
        sections.append(
            ReportSection(
                key="expert_commentary", title="专家结论（大模型撰写）", body=narration.text
            )
        )
    sections = _number_sections(sections)
    title = _report_title(index, payload)
    template = "\n\n".join(f"## {section.title}\n\n{section.body}" for section in sections)

    # The draft must contain no bare numerals. This is checked even though the composer is
    # ours, because the same path serves LLM-authored drafts and must not be weaker there.
    violations = validate_draft(template)
    if violations:
        raise ReportDomainError(
            "REPORT_CONTAINS_UNBOUND_NUMERAL",
            "报告草稿包含未溯源的数字字面量，已拒绝渲染。",
            details={"violations": [violation.to_payload() for violation in violations[:20]]},
        )

    rendered = render_template(
        template,
        runs=index.records,
        formatters=_presentation_formatters(index),
    )
    charts = _build_report_charts(index)
    report_id = uuid4()
    artifact_uri, html_artifact_uri, html_document = _write_report(
        artifact_root,
        report_id=report_id,
        rendered=rendered,
        payload=payload,
        index=index,
        title=title,
        sections=sections,
        charts=charts,
    )
    await _persist(session, report_id=report_id, payload=payload, rendered=rendered)

    return ReportData(
        report_id=report_id,
        execution_id=payload.execution_id,
        dataset_id=payload.dataset_id,
        task=completed_task(stage="generate_report", message="图文报告已生成，全部数值均已溯源。"),
        title=title,
        markdown=rendered.text,
        html=html_document,
        sections=sections,
        charts=charts,
        bindings=[ReportBinding(**binding.to_payload()) for binding in rendered.bindings],
        unresolved=list(rendered.unresolved),
        fully_resolved=rendered.fully_resolved,
        artifact_uri=artifact_uri,
        html_artifact_uri=html_artifact_uri,
        cited_runs=sorted(
            {
                binding.run_id
                for binding in rendered.bindings
                if binding.kind == "run" and binding.resolved
            }
        ),
        narration_source=narration.source,
        llm_provider=narration.provider,
        llm_model=narration.model,
        llm_fallback_reason=narration.fallback_reason,
        llm_rejected_attempts=max(0, narration.attempts - (1 if narration.text else 0)),
    )


def _resolve_provider() -> LlmProvider:
    from app.services.llm_runtime_config_service import build_effective_llm_provider

    return build_effective_llm_provider()


def _narrate(
    provider: LlmProvider,
    *,
    index: RunIndex,
    sections: list[ReportSection],
) -> NarrationOutcome:
    """Ask the model for closing commentary, offering it only real placeholder paths."""

    paths: list[str] = []
    for short, record in index.records.items():
        for path in _leaf_paths(record):
            paths.append(f"{short}.{path}")
    # Show the values as well as their paths: a list of field names cannot tell a
    # narrator whether FIT is negative or a model actually passed an independent test.
    def active_parameter(path: str) -> bool:
        short, field = path.split(".", 1)
        parent = field.rsplit(".", 1)[0] + "." if "." in field else ""
        if field.rsplit(".", 1)[-1] in {"window_size", "max_segments", "max_anomaly_ratio",
            "max_missing_ratio", "min_input_activity_ratio", "selection_mode",
            "adaptive_windows", "temporal_coverage_bins"} and resolve_path(
                index.records[short], parent + "training_policy") == "full_train":
            return False
        if field.endswith("initialization_window"):
            return bool(resolve_path(index.records[short], parent + "initialization_policy") == "past_residual")
        if field.endswith("kernel_decay"):
            return bool(resolve_path(index.records[short], parent + "regularization_kernel") == "tc")
        return True

    relevant = [path for path in paths if active_parameter(path) and not any(token in path for token in
        ("created_at", "version_id", "processing_run_id", "model_id", "run_type", ".markdown", ".html", ".svg"))
        and path.split(".", 1)[1] not in {"status", "task.status"}]
    relevant.sort(key=lambda path: 0 if any(token in path for token in
        (".test.", ".validation.", ".input_support.", ".best_validation_feedback.", ".reference_baselines.")) else 1)
    relevant = relevant[:120]
    evidence = {path: resolve_path(index.records[path.split(".", 1)[0]], path.split(".", 1)[1])
        for path in relevant}
    context = "已完成的分析环节：\n" + "\n".join(f"- {section.title}" for section in sections)
    context += "\n模型流程：Train 拟合参数，Validation 提供验证依据，Test 只回放已冻结参数。"
    context += "\n已保存证据（仅用于理解；正文数字仍必须引用对应占位符）：\n" + json.dumps(evidence, ensure_ascii=False)
    context += "\n现有局限：\n" + "\n".join(section.body for section in sections if section.key == "limitations")
    kinds = {key: "step" if key in index.step_by_tool.values() else "run" for key in index.records}
    return LlmNarrator(provider).narrate(context=context, available_paths=relevant, reference_kinds=kinds)


def _leaf_paths(record: Mapping[str, Any], prefix: str = "", depth: int = 0) -> list[str]:
    """Enumerate scalar paths a narrative may cite, so the model cannot invent fields."""

    if depth > 3:
        return []
    paths: list[str] = []
    for key, value in record.items():
        path = f"{prefix}{key}"
        if isinstance(value, Mapping):
            paths.extend(_leaf_paths(value, f"{path}.", depth + 1))
        elif isinstance(value, int | float | bool | str) or isinstance(value, list) and value and all(isinstance(item, str) for item in value):
            paths.append(path)
    return paths


def _presentation_formatters(
    index: RunIndex,
) -> dict[tuple[str, str, str], Callable[[Any], str]]:
    """Declare percentage presentation by metric semantics, never by numeric range."""

    formatters: dict[tuple[str, str, str], Callable[[Any], str]] = {}
    profile = index.step_by_tool.get("profile_dataset")
    if profile is not None:
        for path in (
            "fingerprint.values.missing_ratio",
            "fingerprint.values.anomaly_ratio",
            "fingerprint.values.dynamic_ratio",
        ):
            formatters[("step", profile, path)] = format_fraction_percent
    anomaly = index.step_by_tool.get("detect_anomalies")
    if anomaly is not None:
        formatters[("step", anomaly, "anomaly_ratio")] = format_fraction_percent
    segment = index.latest("preprocessing.segment")
    if segment is not None:
        formatters[("run", segment, "selection.coverage_ratio")] = format_fraction_percent
    return formatters


async def _add_dataset_context(
    session: AsyncSession,
    *,
    index: RunIndex,
    payload: ReportRequest,
) -> None:
    """Bind report identity to a real DatasetVersion when the standalone UI supplies it."""

    if payload.dataset_id is None or payload.version_id is None:
        return
    dataset = await session.get(Dataset, payload.dataset_id)
    version = await session.get(DatasetVersion, payload.version_id)
    if dataset is None:
        raise ReportDomainError("DATASET_NOT_FOUND", "报告数据集不存在。", status_code=404)
    if version is None or version.dataset_id != dataset.id:
        raise ReportDomainError(
            "REPORT_VERSION_SCOPE_MISMATCH",
            "报告版本不属于所选数据集。",
            status_code=409,
        )
    index.records["dataset"] = {
        "run_type": "dataset.version",
        "dataset_id": str(dataset.id),
        "dataset_name": dataset.name,
        "version_id": str(version.id),
        "version_name": version.name,
        "row_count": version.row_count,
        "column_count": version.column_count,
        "created_at": version.created_at.isoformat(),
    }


def _compose(index: RunIndex, payload: ReportRequest) -> list[ReportSection]:
    """Build only sections supported by evidence in the selected report scope."""

    if index.execution_id is not None:
        return _compose_execution(index)
    return _compose_standalone(index, payload)


def _report_title(index: RunIndex, payload: ReportRequest) -> str:
    if index.execution_id is None:
        return payload.title
    tools = set(index.step_by_tool)
    if "optimize_pipeline" in tools:
        return "IndusOpt 动态建模与闭环寻优报告"
    if tools.intersection({"fit_arx", "evaluate_model"}):
        return "IndusOpt 动态建模与系统辨识报告"
    if tools.intersection(
        {
            "detect_dynamic_segments",
            "estimate_delays",
            "apply_lag_compensation",
            "analyze_collinearity",
            "select_variables",
        }
    ):
        return "IndusOpt 建模数据预处理与优选报告"
    if tools.intersection({"profile_dataset", "detect_anomalies", "clean_data"}):
        return "IndusOpt 数据质量分析与清洗报告"
    return "IndusOpt 数据分析报告"


def _compose_execution(index: RunIndex) -> list[ReportSection]:
    sections = [
        ReportSection(
            key="overview",
            title="分析概述",
            body=(
                "本报告仅汇总当前 Agent 任务中已完成并持久化的执行步骤。"
                "未在本次任务中执行的分析阶段及同一数据资源的历史处理记录，均不进入本次结论。"
            ),
        )
    ]
    definitions = [
        ("profile_dataset", "profile", "数据画像", _profile_body),
        ("detect_anomalies", "anomaly", "异常检测", _anomaly_body),
        ("clean_data", "cleaning", "数据清洗与规整", _cleaning_body),
        ("detect_dynamic_segments", "selection", "动态区间与数据优选", _summary_body),
        ("estimate_delays", "delay", "时滞估计", _summary_body),
        ("apply_lag_compensation", "lag", "时滞补偿", _summary_body),
        ("analyze_collinearity", "collinearity", "共线性诊断", _summary_body),
        ("select_variables", "feature_selection", "变量优选", _summary_body),
        ("fit_arx", "model", "动态模型辨识", _summary_body),
        ("evaluate_model", "evaluation", "模型评价", _summary_body),
        ("optimize_pipeline", "optimization", "闭环寻优", _summary_body),
        ("export_dataset", "export", "数据导出", _summary_body),
    ]
    metrics = {
        "detect_dynamic_segments": [("selection.selected_rows", "优选训练行", "条"),
            ("selection.selected_count", "优选窗口", "个"), ("selection.coverage_ratio", "训练覆盖比例", "")],
        "fit_arx": [("validation.free_run_fit", "初始模型验证自由仿真 FIT", ""),
            ("validation.free_run_rmse", "初始模型验证自由仿真 RMSE", ""), ("training_rows", "初始训练行", "条")],
        "evaluate_model": [("test.free_run.fit", "冻结最终模型 Test 自由仿真 FIT", ""),
            ("test.free_run.rmse", "冻结最终模型 Test 自由仿真 RMSE", ""), ("test.n_samples", "Test 评价样本", "条")],
        "optimize_pipeline": [("best_value", "最佳滚动验证目标", ""),
            ("best_validation_feedback.summary.free_run_fit", "优化模型验证自由仿真 FIT", ""),
            ("best_validation_feedback.summary.free_run_rmse", "优化模型验证自由仿真 RMSE", "")],
    }
    for tool, section_key, title, body_builder in definitions:
        record_key = index.step_by_tool.get(tool)
        if record_key is None:
            continue
        sections.append(
            ReportSection(
                key=section_key,
                title=title,
                body=_body_with_summary(record_key, index.records[record_key],
                    _step_metric_clauses(record_key, index.records[record_key], metrics[tool]))
                    if tool in metrics else body_builder(record_key, index.records[record_key]),
            )
        )
    limitations = "\n\n".join(filter(None, [_execution_limitations(set(index.step_by_tool)),
        _standalone_limitations(index)]))
    if limitations:
        sections.append(
            ReportSection(key="limitations", title="局限与风险提示", body=limitations)
        )
    return sections


def _summary_body(record_key: str, record: Mapping[str, Any]) -> str:
    if isinstance(record.get("summary"), str) and record["summary"].strip():
        return f"本阶段执行摘要：{{{{step:{record_key}.summary}}}}"
    return "本阶段已在当前 Agent 任务中完成，详细结果保存在对应步骤证据中。"


def _profile_body(record_key: str, record: Mapping[str, Any]) -> str:
    clauses = _step_metric_clauses(
        record_key,
        record,
        [
            ("n_samples", "本次数据画像覆盖样本", "个"),
            ("fingerprint.values.missing_ratio", "缺失比例", ""),
            ("fingerprint.values.anomaly_ratio", "画像离群比例", ""),
        ],
    )
    return _body_with_summary(record_key, record, clauses)


def _anomaly_body(record_key: str, record: Mapping[str, Any]) -> str:
    clauses = _step_metric_clauses(
        record_key,
        record,
        [("anomaly_count", "检出疑似异常点", "个"), ("anomaly_ratio", "疑似异常比例", "")],
    )
    return _body_with_summary(record_key, record, clauses)


def _cleaning_body(record_key: str, record: Mapping[str, Any]) -> str:
    clauses = _step_metric_clauses(
        record_key,
        record,
        [
            ("total_cleaned_points", "清洗修改单元格", "个"),
            ("summary_data.rows_before", "清洗前样本", "条"),
            ("summary_data.rows_after", "清洗后样本", "条"),
            ("summary_data.changes.unique_changed_cells", "实际修改单元格", "个"),
            ("summary_data.changes.missing_value_fills", "缺失填补", "个"),
            ("summary_data.changes.outlier_replacements", "异常替换", "个"),
            ("summary_data.changes.duplicate_timestamps_processed", "重复时间戳处理", "个"),
            ("summary_data.changes.resampling_empty_rows_created", "重采样空行", "条"),
            ("summary_data.changes.smoothing_changes", "平滑修改", "个"),
        ],
    )
    return _body_with_summary(record_key, record, clauses)


def _body_with_summary(
    record_key: str, record: Mapping[str, Any], clauses: list[str]
) -> str:
    paragraphs: list[str] = []
    if clauses:
        paragraphs.append("，".join(clauses) + "。")
    if isinstance(record.get("summary"), str) and record["summary"].strip():
        paragraphs.append(f"执行摘要：{{{{step:{record_key}.summary}}}}")
    return "\n\n".join(paragraphs) or "本阶段已完成，未产生可量化的结构化摘要。"


def _step_metric_clauses(
    record_key: str,
    record: Mapping[str, Any],
    definitions: list[tuple[str, str, str]],
) -> list[str]:
    return [
        f"{label} {{{{step:{record_key}.{path}}}}}{suffix}"
        for path, label, suffix in definitions
        if resolve_path(record, path) is not None
    ]


def _execution_limitations(tools: set[str]) -> str:
    limitations: list[str] = []
    if "detect_anomalies" in tools:
        limitations.append("疑似异常点由当前检测方法识别，结果用于提示复核，不等同于过程故障诊断。")
    if "clean_data" in tools:
        limitations.append("清洗结果受当前插值、异常处理和时间规整参数约束，仍需结合工艺语义复核。")
    if "detect_dynamic_segments" in tools:
        limitations.append("D-最优区间优选依赖候选窗口与质量门控结果，不能替代对工况覆盖性的工程判断。")
    if tools.intersection({"estimate_delays", "apply_lag_compensation"}):
        limitations.append("时滞结论受采样周期、信号激励与相关结构影响，补偿前应确认工艺因果方向。")
    if tools.intersection({"fit_arx", "evaluate_model"}):
        limitations.append("ARX 模型建立在线性与时不变近似上，外推至未覆盖工况时应重新验证。")
    if "optimize_pipeline" in tools:
        limitations.append("闭环寻优结果受搜索空间、目标函数和试验预算约束，不代表全局最优保证。")
    return "\n\n".join(limitations)


def _compose_standalone(index: RunIndex, payload: ReportRequest) -> list[ReportSection]:
    if "dataset" in index.records:
        overview = (
            "本报告对应数据集 {{run:dataset.dataset_name}}、版本 "
            "{{run:dataset.version_name}}，该版本包含 {{run:dataset.row_count}} 行、"
            "{{run:dataset.column_count}} 列。报告只引用该作用域内成功完成的持久化记录。"
        )
    else:
        record_key = next(iter(index.records))
        overview = (
            f"本报告由 IndusOpt 自动生成，引用了 "
            f"{{{{run:{record_key}.run_type}}}} 等当前数据资源范围内的成功处理记录。"
            "报告数值均通过持久化证据占位符解析。"
        )
    sections = [ReportSection(key="overview", title="数据概况与来源", body=overview)]
    clean = index.latest("preprocessing.clean")
    segment = index.latest("preprocessing.segment")
    delay = index.latest("preprocessing.delay")
    collinearity = index.latest("preprocessing.collinearity")
    modeling = index.latest("modeling.arx")
    evaluation = index.latest("modeling.arx_evaluation")
    standalone_sections = [
        (clean, "cleaning", "数据清洗与规整", [("total_cleaned_points", "清洗修改数据点", "个")]),
        (
            segment,
            "selection",
            "动态区间与数据优选",
            [
                ("selection.candidate_count", "候选窗口", "个"),
                ("selection.gated_count", "通过质量门控", "个"),
                ("selection.selected_count", "最终选中区间", "个"),
                ("selection.coverage_ratio", "采样占比", ""),
            ],
        ),
        (delay, "delay", "时滞估计", [("refined_delays", "最终时滞", ""), ("validation_fit", "验证结果", "")]),
        (collinearity, "collinearity", "共线性诊断", [("condition_number", "设计矩阵条件数", ""), ("groups", "高相关变量组", "")]),
        (
            modeling,
            "model",
            "模型辨识与验证",
            [
                ("validation.free_run_fit", "验证集自由仿真 FIT", ""),
                ("validation.one_step_fit", "一步预测 FIT", ""),
                ("validation.stable", "模型稳定性", ""),
                ("training_rows", "训练样本", "条"),
            ],
        ),
        (
            evaluation,
            "evaluation",
            "模型评价（Test）",
            [
                ("test.free_run.fit", "Test 自由仿真 FIT", ""),
                ("test.one_step.fit", "Test 一步预测 FIT", ""),
                ("test.free_run.rmse", "Test 自由仿真 RMSE", ""),
                ("test.n_samples", "Test 样本", "条"),
            ],
        ),
    ]
    for optional_record_key, section_key, title, metrics in standalone_sections:
        if optional_record_key:
            sections.append(
                ReportSection(
                    key=section_key,
                    title=title,
                    body=_run_body(
                        optional_record_key,
                        index.records[optional_record_key],
                        metrics,
                    ),
                )
            )
    if "study" in index.records:
        objective_path = (
            "best_trial_metrics.objective_semantics.name"
            if resolve_path(index.records["study"], "best_trial_metrics.objective_semantics.name") is not None
            else "objective"
        )
        sections.append(
            ReportSection(
                key="optimization",
                title="闭环寻优",
                body=_run_body(
                    "study",
                    index.records["study"],
                    [
                        (objective_path, "寻优目标", ""),
                        ("best_trial_metrics.objective_semantics.version", "目标版本", ""),
                        ("best_value", "Best 目标值", ""),
                        ("best_trial_number", "Best Trial 编号", ""),
                    ],
                ),
            )
        )
    sections.append(
        ReportSection(
            key="provenance",
            title="数据来源与处理溯源",
            body=(
                "本报告章节由同一数据集、同一版本下成功完成的 ProcessingRun 动态组成；"
                "每个图表标注唯一来源运行和字段路径，未执行或缺少可恢复数据的阶段不生成图表。"
            ),
        )
    )
    limitations = _standalone_limitations(index)
    if limitations:
        sections.append(ReportSection(key="limitations", title="局限与风险提示", body=limitations))
    _ = payload
    return sections


def _run_body(
    record_key: str,
    record: Mapping[str, Any],
    definitions: list[tuple[str, str, str]],
) -> str:
    clauses = [
        f"{label} {{{{run:{record_key}.{path}}}}}{suffix}"
        for path, label, suffix in definitions
        if resolve_path(record, path) is not None
    ]
    return "，".join(clauses) + "。" if clauses else "该处理记录已完成，但未提供可量化摘要。"


def _standalone_limitations(index: RunIndex) -> str:
    limitations: list[str] = []
    if index.latest("preprocessing.clean"):
        limitations.append("清洗结论受当前处理参数约束，仍需结合工艺语义复核。")
    if index.latest("preprocessing.segment"):
        limitations.append("D-最优区间优选依赖候选窗口与质量门控结果。")
    if index.latest("preprocessing.delay"):
        limitations.append("时滞估计受采样周期、信号激励与相关结构影响。")
    model = index.latest("modeling.arx")
    if model:
        limitations.append("模型采用线性与时不变近似，外推时应重新验证。结构稳定性不能替代预测能力验证。")
        if resolve_path(index.records[model], "parameters.initialization_policy") == "past_residual":
            limitations.append("历史扰动补偿仅使用预测开始前的观测，自由仿真期间冻结补偿量。它假设扰动在预测期间持续，不能修复动态系数变化，也不能解释为完全没有输出历史的迁移。")
    evaluation = index.latest("modeling.arx_evaluation")
    supports = [resolve_path(index.records[model], "validation.input_support") if model else None,
        resolve_path(index.records[evaluation], "model_health.input_support") if evaluation else None]
    if "study" in index.records:
        supports.append(resolve_path(index.records["study"], "best_trial_metrics.validation_feedback.summary.input_support"))
    statuses = {item.get("status") for item in supports if isinstance(item, Mapping)}
    if "unsupported" in statuses:
        limitations.append("存在训练期间未激励、在评价期间变化的控制量，其变化影响缺少辨识依据；应补充该控制量变化的真实运行数据，再重新训练和验证。")
    if "extrapolation" in statuses:
        limitations.append("评价输入超出实际训练行的取值范围，当前预测包含外推。输入范围覆盖只是工况诊断，不能证明跨工况动态关系相同。")
    if "unavailable" in statuses:
        limitations.append("已保存模型缺少完整输入范围证据，或部分监测输入不可用，当前无法确认输入工况覆盖。")
    test_fit = resolve_path(index.records[evaluation], "test.free_run.fit") if evaluation else None
    if isinstance(test_fit, int | float) and test_fit <= 0:
        limitations.append("Test 自由仿真 FIT 非正，误差已达到或超过该测试段自身波动，当前证据不足以说明有效的自由仿真能力。")
    if "study" in index.records:
        limitations.append("闭环寻优受搜索空间、目标函数和试验预算约束。")
        if resolve_path(index.records["study"], "best_params.initialization_policy") == "past_residual":
            limitations.append("所选模型使用预测前历史估计持续扰动，仿真期间冻结补偿量；跨工况效果须在相同历史上下文条件下验证。")
        acceptance = resolve_path(index.records["study"], "best_trial_metrics.validation_acceptance.status")
        if acceptance == "insufficient":
            limitations.append("所选模型未通过全部滚动验证的效果或工况覆盖检查。寻优完成不代表模型效果达标，应补充激励或调整模型后复核。")
        elif acceptance == "inconclusive":
            limitations.append("滚动验证的持值预测对照证据不足，当前模型效果尚不能确认。")
        policy = resolve_path(index.records["study"], "best_params.training_policy")
        if policy == "full_train":
            limitations.append("滚动验证选择了全量有效训练行；当前数据未证明优选片段具有更高验证得分，交付数据按该训练策略保留。")
    return "\n\n".join(limitations)


_SECTION_NUMERALS = ("零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十")


def _section_numeral(value: int) -> str:
    if value <= 10:
        return _SECTION_NUMERALS[value]
    if value < 20:
        return f"十{_SECTION_NUMERALS[value - 10]}"
    return str(value)


def _number_sections(sections: list[ReportSection]) -> list[ReportSection]:
    return [
        section.model_copy(update={"title": f"{_section_numeral(index)}、{section.title}"})
        for index, section in enumerate(sections, start=1)
    ]


def _build_report_charts(index: RunIndex) -> list[ReportChart]:
    charts: list[ReportChart] = []
    clean_key = index.step_by_tool.get("clean_data") or index.latest("preprocessing.clean")
    if clean_key:
        record = index.records[clean_key]
        preview = record.get("cleaning_preview")
        if isinstance(preview, Mapping):
            svg = _line_chart_svg({"清洗前": preview["before"], "清洗后": preview["after"]},
                y_label=str(preview["channel"]), x_values=preview["relative_milliseconds"], x_label="相对时间（毫秒）")
            if svg:
                charts.append(ReportChart(key="cleaning", title="清洗前后同一通道对比", svg=svg,
                    source_run_id=str(record.get("run_id") or clean_key),
                    source_path=f"versions.{preview['before_version_id']}+{preview['after_version_id']}.{preview['channel']}",
                    description="从不可变版本读取；仅绘制共同、唯一且数值有效的时间点，新增、删除或歧义点不作人为配对。"))
    segment_key = index.latest("preprocessing.segment")
    if segment_key is not None:
        record = index.records[segment_key]
        indices = record.get("selected_sample_indices")
        if isinstance(indices, list) and indices and all(
            isinstance(value, int) and not isinstance(value, bool) for value in indices
        ):
            charts.append(
                ReportChart(
                    key="selection",
                    title="优选样本在来源序列中的分布",
                    svg=_selection_svg(indices),
                    source_run_id=str(record.get("run_id") or segment_key),
                    source_path="selected_sample_indices",
                    description="柱高表示各等宽样本区间内被真实优选的样本数量。",
                )
            )

    delay_key = index.latest("preprocessing.delay")
    if delay_key is not None:
        record = index.records[delay_key]
        correlations = record.get("correlations")
        if isinstance(correlations, Mapping):
            series = {
                str(column): values
                for column, values in correlations.items()
                if isinstance(values, list) and values
            }
            lag_values = list(range(len(next(iter(series.values()))))) if series else []
            svg = (
                _line_chart_svg(
                    series,
                    y_label="相关系数",
                    x_values=lag_values,
                    x_label="滞后步数 Lag（步）",
                )
                if lag_values
                else ""
            )
            if svg:
                charts.append(
                    ReportChart(
                        key="delay",
                        title="预白化互相关谱",
                        svg=svg,
                        source_run_id=str(record.get("run_id") or delay_key),
                        source_path="correlations",
                        description="各曲线直接来自该时滞分析运行持久化的 correlation spectrum。",
                    )
                )

    collinearity_key = index.latest("preprocessing.collinearity")
    if collinearity_key is not None:
        record = index.records[collinearity_key]
        variables = record.get("variables")
        matrix = record.get("pearson")
        if isinstance(variables, list) and isinstance(matrix, list):
            svg = _heatmap_svg(variables, matrix)
            if svg:
                charts.append(
                    ReportChart(
                        key="collinearity",
                        title="Pearson 相关矩阵",
                        svg=svg,
                        source_run_id=str(record.get("run_id") or collinearity_key),
                        source_path="pearson",
                        description="色块和标注值均来自同一共线性分析运行。",
                    )
                )

    evaluation_key = index.latest("modeling.arx_evaluation")
    if evaluation_key is not None:
        record = index.records[evaluation_key]
        series_record = record.get("series")
        if isinstance(series_record, Mapping):
            svg = _line_chart_svg(
                {
                    "真实输出": series_record.get("y_true"),
                    "自由仿真": series_record.get("free_run_prediction"),
                },
                    y_label="输出",
                    x_values=series_record.get("sample_indices"),
                    x_label="来源样本索引" if series_record.get("sample_indices") is not None else None,
            )
            if svg:
                charts.append(
                    ReportChart(
                        key="evaluation",
                        title="Test 真实输出与自由仿真",
                        svg=svg,
                        source_run_id=str(record.get("run_id") or evaluation_key),
                        source_path="series.y_true + series.free_run_prediction",
                        description="两条曲线来自同一次已持久化的 held-out Test 评价。",
                    )
                )
    optimization_key = index.step_by_tool.get("optimize_pipeline") or ("study" if "study" in index.records else None)
    if optimization_key:
        record = index.records[optimization_key]
        curve = record.get("trial_curve", [])
        if curve:
            svg = _line_chart_svg({"累计最佳验证目标": [point["best_value"] for point in curve]},
                y_label="滚动验证目标", x_values=[point["trial_number"] for point in curve], x_label="Trial 编号")
            if svg:
                charts.append(ReportChart(key="optimization", title="寻优累计最佳验证目标",
                    svg=svg, source_run_id=str(record.get("study_id") or optimization_key), source_path="trial_curve",
                    description="仅来自该寻优任务的已持久化 Trial；失败试验不贡献改善，单个有效点不代表收敛。"))
    return charts


async def _add_cleaning_preview(
    session: AsyncSession, *, index: RunIndex, payload: ReportRequest, artifact_root: Path,
) -> None:
    key = index.step_by_tool.get("clean_data") or index.latest("preprocessing.clean")
    if not key or payload.dataset_id is None:
        return
    record = index.records[key]
    before_id = record.get("source_version_id") or resolve_path(record, "parameters.version_id")
    after_id = record.get("effective_version_id") or record.get("derived_version_id") or record.get("result_version_id")
    if not before_id or not after_id:
        return
    try:
        before_uuid, after_uuid = UUID(str(before_id)), UUID(str(after_id))
        before = await load_version_series(session, version_id=before_uuid,
            dataset_id=payload.dataset_id, artifact_root=artifact_root)
        after = await load_version_series(session, version_id=after_uuid,
            dataset_id=payload.dataset_id, artifact_root=artifact_root)
    except (ValueError, VersionDataError):
        return
    channel = before.declared_output
    if not channel or channel not in after.values or not before.timestamps or not after.timestamps:
        return
    # Duplicate timestamp groups are excluded, never paired by occurrence order.
    def unique_indices(timestamps):
        indices, repeated = {}, set()
        for i, stamp in enumerate(timestamps):
            if stamp in indices:
                repeated.add(stamp)
            else:
                indices[stamp] = i
        return {stamp: i for stamp, i in indices.items() if stamp not in repeated}
    left, right = unique_indices(before.timestamps), unique_indices(after.timestamps)
    common = [stamp for stamp in sorted(left.keys() & right.keys())
        if np.isfinite(before.values[channel][left[stamp]]) and np.isfinite(after.values[channel][right[stamp]])]
    if not common:
        return
    common = [common[i] for i in np.linspace(0, len(common)-1, min(241, len(common)), dtype=int)]
    record["cleaning_preview"] = {"before_version_id": str(before_uuid), "after_version_id": str(after_uuid),
        "channel": channel, "relative_milliseconds": [round((t-common[0]).total_seconds()*1000) for t in common],
        "before": [float(before.values[channel][left[t]]) for t in common],
        "after": [float(after.values[channel][right[t]]) for t in common]}


def _selection_svg(indices: list[int]) -> str:
    values = sorted(indices)
    bin_count = min(36, max(8, int(len(values) ** 0.5)))
    lower, upper = values[0], values[-1]
    span = max(upper - lower + 1, 1)
    counts = [0] * bin_count
    for value in values:
        position = min(bin_count - 1, int((value - lower) * bin_count / span))
        counts[position] += 1
    width, height, left, top, bottom = 760, 250, 54, 22, 42
    plot_width, plot_height = width - left - 20, height - top - bottom
    maximum = max(counts) or 1
    bar_width = plot_width / bin_count
    bars = []
    for index, count in enumerate(counts):
        bar_height = plot_height * count / maximum
        x = left + index * bar_width + 1
        y = top + plot_height - bar_height
        bars.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{max(bar_width - 2, 1):.2f}" '
            f'height="{bar_height:.2f}" fill="#5f835b"><title>{count}</title></rect>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" '
        'aria-label="优选样本索引分布">'
        '<rect width="100%" height="100%" fill="#fff"/>'
        f'<line x1="{left}" y1="{top + plot_height}" x2="{width - 20}" '
        f'y2="{top + plot_height}" stroke="#879187"/>{"".join(bars)}'
        f'<text x="{left}" y="{height - 14}" font-size="12" fill="#526052">{lower}</text>'
        f'<text x="{width - 20}" y="{height - 14}" text-anchor="end" font-size="12" '
        f'fill="#526052">{upper}</text>'
        f'<text x="16" y="{top + 12}" font-size="12" fill="#526052">数量</text>'
        '</svg>'
    )


def _line_chart_svg(
    series: Mapping[str, object],
    *,
    y_label: str,
    x_values: list[int] | None = None,
    x_label: str | None = None,
) -> str:
    if (x_values is None) != (x_label is None):
        return ""

    shared_x_values: list[float] | None = None
    shared_sample_indices: list[int] | None = None
    if x_values is not None:
        if not x_values or any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in x_values
        ):
            return ""
        shared_x_values = [float(value) for value in x_values]
        if any(
            current <= previous
            for previous, current in zip(shared_x_values, shared_x_values[1:], strict=False)
        ):
            return ""
        if len(shared_x_values) <= 241:
            shared_sample_indices = list(range(len(shared_x_values)))
        else:
            last_index = len(shared_x_values) - 1
            shared_sample_indices = [
                round(position * last_index / 240) for position in range(241)
            ]

    normalized: dict[str, list[tuple[float, float]]] = {}
    for label, raw_values in series.items():
        if not isinstance(raw_values, list):
            continue
        if shared_x_values is not None and shared_sample_indices is not None:
            if len(raw_values) != len(shared_x_values) or any(
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not np.isfinite(value)
                for value in raw_values
            ):
                return ""
            normalized[str(label)] = [
                (shared_x_values[index], float(raw_values[index]))
                for index in shared_sample_indices
            ]
        else:
            values = [
                float(value)
                for value in raw_values
                if isinstance(value, int | float)
                and not isinstance(value, bool)
                and np.isfinite(value)
            ]
            if len(values) < 2:
                continue
            step = max(1, len(values) // 240)
            normalized[str(label)] = [
                (float(index), value) for index, value in enumerate(values[::step][:241])
            ]
    if not normalized:
        return ""
    all_values = [value for points in normalized.values() for _, value in points]
    minimum, maximum = min(all_values), max(all_values)
    if minimum == maximum:
        minimum -= 1.0
        maximum += 1.0
    has_x_axis = shared_x_values is not None and x_label is not None
    width, height, left, right, top, bottom = (
        (760, 330, 96, 24, 24, 102) if has_x_axis else (760, 280, 96, 24, 24, 52)
    )
    plot_width, plot_height = width - left - right, height - top - bottom
    y_axis_title_x = 18
    y_axis_tick_x = left - 10
    y_axis_midpoint = top + plot_height / 2
    x_minimum = min(point[0] for points in normalized.values() for point in points)
    x_maximum = max(point[0] for points in normalized.values() for point in points)

    def x_coordinate(value: float) -> float:
        if x_minimum == x_maximum:
            return float(left)
        return left + plot_width * (value - x_minimum) / (x_maximum - x_minimum)

    colors = ("#496f47", "#b46f3c", "#557da5", "#8a5f91")
    paths: list[str] = []
    legends: list[str] = []
    for series_index, (label, points_with_values) in enumerate(normalized.items()):
        color = colors[series_index % len(colors)]
        points = " ".join(
            f"{x_coordinate(x_value):.2f},"
            f"{top + plot_height * (maximum - value) / (maximum - minimum):.2f}"
            for x_value, value in points_with_values
        )
        paths.append(
            f'<polyline points="{points}" fill="none" stroke="{color}" '
            'stroke-width="1.8" vector-effect="non-scaling-stroke"/>'
        )
        if len(points_with_values) == 1:
            x_value, value = points_with_values[0]
            paths.append(
                f'<circle cx="{x_coordinate(x_value):.2f}" '
                f'cy="{top + plot_height * (maximum - value) / (maximum - minimum):.2f}" '
                f'r="2.5" fill="{color}"/>'
            )
        legend_x = left + series_index * 170
        legends.append(
            f'<line x1="{legend_x}" y1="{height - 18}" x2="{legend_x + 22}" '
            f'y2="{height - 18}" stroke="{color}" stroke-width="3"/>'
            f'<text x="{legend_x + 28}" y="{height - 14}" font-size="12" fill="#394339">'
            f'{html_lib.escape(label)}</text>'
        )
    x_axis_elements = ""
    if has_x_axis:
        integer_minimum = int(x_minimum)
        integer_maximum = int(x_maximum)
        if integer_minimum == integer_maximum:
            tick_values = [integer_minimum]
        else:
            tick_values = sorted(
                {
                    round(integer_minimum + (integer_maximum - integer_minimum) * index / 5)
                    for index in range(6)
                }
            )
        ticks = "".join(
            f'<line x1="{x_coordinate(float(value)):.2f}" y1="{top + plot_height}" '
            f'x2="{x_coordinate(float(value)):.2f}" y2="{top + plot_height + 6}" '
            f'stroke="#879187"/>'
            f'<text x="{x_coordinate(float(value)):.2f}" y="{top + plot_height + 20}" '
            f'text-anchor="middle" font-size="11" fill="#687568">{value}</text>'
            for value in tick_values
        )
        x_axis_elements = (
            f'{ticks}<text x="{left + plot_width / 2:.2f}" y="{top + plot_height + 46}" '
            f'text-anchor="middle" font-size="12" fill="#526052">'
            f'{html_lib.escape(x_label or "")}</text>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img">'
        '<rect width="100%" height="100%" fill="#fff"/>'
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" stroke="#879187"/>'
        f'<line x1="{left}" y1="{top + plot_height}" x2="{left + plot_width}" '
        f'y2="{top + plot_height}" stroke="#879187"/>{"".join(paths)}'
        f'<text x="{y_axis_title_x}" y="{y_axis_midpoint:.2f}" text-anchor="middle" '
        f'transform="rotate(-90 {y_axis_title_x} {y_axis_midpoint:.2f})" font-size="12" '
        f'fill="#526052">{html_lib.escape(y_label)}</text>'
        f'<text x="{y_axis_tick_x}" y="{top + 8}" text-anchor="end" font-size="11" fill="#687568">'
        f'{maximum:.4g}</text>'
        f'<text x="{y_axis_tick_x}" y="{top + plot_height}" text-anchor="end" font-size="11" '
        f'fill="#687568">{minimum:.4g}</text>{x_axis_elements}{"".join(legends)}</svg>'
    )


def _heatmap_svg(variables: list[object], matrix: list[object]) -> str:
    size = len(variables)
    if size == 0 or size > 16 or len(matrix) != size:
        return ""
    cells: list[str] = []
    cell = min(54, max(30, int(560 / size)))
    left, top = 52, 52
    for row_index, row in enumerate(matrix):
        if not isinstance(row, list) or len(row) != size:
            return ""
        for column_index, raw in enumerate(row):
            if raw is None:
                fill, label = "#eef0ed", "—"
            elif isinstance(raw, int | float) and not isinstance(raw, bool) and np.isfinite(raw):
                value = max(-1.0, min(1.0, float(raw)))
                intensity = int(235 - 105 * abs(value))
                fill = (
                    f"rgb({intensity},{intensity + 18},{intensity})"
                    if value >= 0
                    else f"rgb({intensity + 20},{intensity},{intensity})"
                )
                label = f"{value:.2f}"
            else:
                return ""
            x, y = left + column_index * cell, top + row_index * cell
            cells.append(
                f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" fill="{fill}" '
                'stroke="#fff"/>'
                f'<text x="{x + cell / 2}" y="{y + cell / 2 + 4}" text-anchor="middle" '
                f'font-size="10" fill="#263226">{label}</text>'
            )
    width, height = left + size * cell + 20, top + size * cell + 20
    axis = []
    for index in range(size):
        axis_label = f"X{index + 1}"
        axis.append(
            f'<text x="{left - 8}" y="{top + index * cell + cell / 2 + 4}" '
            f'text-anchor="end" font-size="11" fill="#394339">{axis_label}</text>'
            f'<text x="{left + index * cell + cell / 2}" y="{top - 10}" '
            f'text-anchor="middle" font-size="11" fill="#394339">{axis_label}</text>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" '
        'aria-label="Pearson 相关矩阵">'
        '<rect width="100%" height="100%" fill="#fff"/>'
        f'{"".join(axis)}{"".join(cells)}</svg>'
    )


def _render_html_report(
    *,
    title: str,
    sections: list[ReportSection],
    charts: list[ReportChart],
    index: RunIndex,
    payload: ReportRequest,
) -> str:
    def figure_html(chart: ReportChart) -> str:
        key_html = ""
        figure_class = ""
        if chart.key == "collinearity":
            figure_class = ' class="pearson-figure"'
            record = next(
                (
                    record
                    for key, record in index.records.items()
                    if str(record.get("run_id") or key) == chart.source_run_id
                ),
                None,
            )
            variables = record.get("variables") if record is not None else None
            if isinstance(variables, list):
                key_html = '<div class="matrix-key" aria-label="相关矩阵变量编号对照">' + "".join(
                    '<div class="matrix-key-item">'
                    f'<span class="matrix-key-code">X{number}</span>'
                    f'<span class="matrix-key-name">{html_lib.escape(str(name))}</span>'
                    '</div>'
                    for number, name in enumerate(variables, start=1)
                ) + '</div>'
        return (
            f"<figure{figure_class}>"
            f"<h3>{html_lib.escape(chart.title)}</h3>{chart.svg}{key_html}"
            f"<figcaption>{html_lib.escape(chart.description)} "
            f"来源运行：<code>{html_lib.escape(chart.source_run_id)}</code>；"
            f"字段：<code>{html_lib.escape(chart.source_path)}</code></figcaption>"
            "</figure>"
        )

    charts_by_key: dict[str, list[ReportChart]] = {}
    for chart in charts:
        charts_by_key.setdefault(chart.key, []).append(chart)
    section_html: list[str] = []
    for section in sections:
        rendered_body = render_template(
            section.body,
            runs=index.records,
            formatters=_presentation_formatters(index),
        ).text
        paragraphs = "".join(
            f"<p>{html_lib.escape(paragraph).replace(chr(10), '<br>')}</p>"
            for paragraph in rendered_body.split("\n\n")
            if paragraph.strip()
        )
        figures = "".join(figure_html(chart) for chart in charts_by_key.get(section.key, []))
        section_html.append(
            f'<section><h2>{html_lib.escape(section.title)}</h2>{paragraphs}{figures}</section>'
        )
    metadata = ""
    if payload.dataset_id is not None and payload.version_id is not None:
        metadata = (
            f"<p class=meta>数据集：<code>{html_lib.escape(str(payload.dataset_id))}</code> · "
            f"版本：<code>{html_lib.escape(str(payload.version_id))}</code></p>"
        )
    return (
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html_lib.escape(title)}</title><style>"
        "@page{size:A4;margin:16mm 15mm 18mm}*{box-sizing:border-box}"
        "body{margin:0;color:#263226;background:#f4f5f2;font-family:'Noto Sans SC','Microsoft YaHei',sans-serif;line-height:1.75}"
        "main{max-width:900px;margin:24px auto;padding:36px 44px;background:#fff;box-shadow:0 4px 24px #1f2b2014}"
        "h1{margin:0 0 8px;font-size:28px}h2{margin:28px 0 10px;padding-bottom:7px;border-bottom:1px solid #dfe4dc;font-size:20px}"
        "h3{margin:0 0 8px;font-size:15px}p{margin:8px 0}.meta{color:#647064;font-size:12px}"
        "section,figure{break-inside:avoid-page}figure{margin:18px 0;padding:14px;border:1px solid #dfe4dc;border-radius:8px;background:#fff}"
        "svg{display:block;width:100%;height:auto;max-height:420px}figcaption{margin-top:8px;color:#647064;font-size:11px}"
        ".pearson-figure{page-break-inside:avoid}.pearson-figure svg{max-width:560px;max-height:none;margin-inline:auto}"
        ".matrix-key{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:3px 16px;margin-top:10px;font-size:11px;line-height:1.45}"
        ".matrix-key-item{display:flex;gap:6px;min-width:0;break-inside:avoid}.matrix-key-code{flex:none;font-weight:700;color:#426340}"
        ".matrix-key-name{overflow-wrap:anywhere}"
        "code{font-family:'JetBrains Mono',monospace;overflow-wrap:anywhere}"
        "@media print{body{background:#fff}main{max-width:none;margin:0;padding:0;box-shadow:none}h2{break-after:avoid}figure{border-color:#bbb}}"
        "</style></head><body><main>"
        f"<header><h1>{html_lib.escape(title)}</h1>{metadata}"
        f"<p class=meta>生成时间：{html_lib.escape(datetime.now(UTC).isoformat())} · "
        f"图表数量：{len(charts)}</p></header>{''.join(section_html)}"
        "</main></body></html>"
    )


def _write_report(
    artifact_root: Path,
    *,
    report_id: UUID,
    rendered: RenderResult,
    payload: ReportRequest,
    index: RunIndex,
    title: str,
    sections: list[ReportSection],
    charts: list[ReportChart],
) -> tuple[str, str, str]:
    root = artifact_root / "reports"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{report_id}.md"
    header = (
        f"# {title}\n\n"
        f"生成时间：{datetime.now(UTC).isoformat()}\n\n"
        f"引用运行记录：{', '.join(sorted(index.records))}\n\n"
        f"数值绑定数：{len(rendered.bindings)}，未解析：{len(rendered.unresolved)}\n\n"
        "---\n\n"
    )
    path.write_text(header + rendered.text + "\n", encoding="utf-8")
    html_document = _render_html_report(
        title=title,
        sections=sections,
        charts=charts,
        index=index,
        payload=payload,
    )
    html_path = root / f"{report_id}.html"
    html_path.write_text(html_document, encoding="utf-8")
    return (
        path.relative_to(artifact_root).as_posix(),
        html_path.relative_to(artifact_root).as_posix(),
        html_document,
    )


async def _persist(
    session: AsyncSession,
    *,
    report_id: UUID,
    payload: ReportRequest,
    rendered: RenderResult,
) -> None:
    now = datetime.now(UTC)
    session.add(
        ProcessingRun(
            id=report_id,
            dataset_id=payload.dataset_id,
            source_version_id=payload.version_id,
            run_type="reporting.generate",
            status="succeeded",
            parameters=payload.model_dump(mode="json"),
            result=rendered.to_payload(),
            created_at=now,
            finished_at=now,
        )
    )
    session.add(
        OperationLog(
            id=uuid4(),
            event_type="reporting.generate.completed",
            subject_id=str(payload.dataset_id) if payload.dataset_id else str(report_id),
            payload_json=json.dumps(
                {
                    "report_id": str(report_id),
                    "bindings": len(rendered.bindings),
                    "unresolved": list(rendered.unresolved),
                    "executed_at": now.isoformat(),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            created_at=now,
        )
    )
    await session.commit()


async def resolve_optimization_best_selection(
    session: AsyncSession,
    *,
    dataset_id: UUID,
    version_id: UUID,
    study_id: UUID,
    artifact_root: Path,
) -> OptimizationBestSelection:
    """Validate one Study and recover the exact persisted Best model training rows."""

    study = await session.get(OptimizationStudy, study_id)
    if study is None:
        raise ReportDomainError(
            "OPTIMIZATION_STUDY_NOT_FOUND", "寻优任务不存在。", status_code=404
        )
    if study.status != "succeeded" or study.finished_at is None:
        raise ReportDomainError(
            "OPTIMIZATION_STUDY_NOT_SUCCEEDED",
            "寻优任务尚未成功完成。",
            status_code=409,
        )
    if study.dataset_id != dataset_id:
        raise ReportDomainError(
            "OPTIMIZATION_STUDY_DATASET_MISMATCH",
            "寻优任务不属于所选数据集。",
            status_code=409,
        )
    if study.version_id != version_id:
        raise ReportDomainError(
            "OPTIMIZATION_STUDY_VERSION_MISMATCH",
            "寻优任务不属于所选数据版本。",
            status_code=409,
        )
    if (
        study.best_trial_number is None
        or study.best_value is None
        or not np.isfinite(study.best_value)
    ):
        raise ReportDomainError(
            "OPTIMIZATION_BEST_TRIAL_MISSING",
            "成功的寻优任务缺少合法 Best Trial。",
            status_code=409,
        )
    if study.optimized_model_id is None:
        raise ReportDomainError(
            "OPTIMIZATION_BEST_MODEL_MISSING",
            "Best Trial 缺少关联优化模型。",
            status_code=409,
        )

    best_trial = await session.scalar(
        select(OptimizationTrialRecord).where(
            OptimizationTrialRecord.study_id == study.id,
            OptimizationTrialRecord.trial_number == study.best_trial_number,
        )
    )
    if (
        best_trial is None
        or best_trial.state != "complete"
        or best_trial.value is None
        or not np.isfinite(best_trial.value)
    ):
        raise ReportDomainError(
            "OPTIMIZATION_BEST_TRIAL_INVALID",
            "Best Trial 记录不存在、未完成或缺少有效目标值。",
            status_code=409,
        )
    if not np.isclose(best_trial.value, study.best_value, rtol=1e-12, atol=1e-12):
        raise ReportDomainError(
            "OPTIMIZATION_BEST_TRIAL_MISMATCH",
            "Best Trial 的目标值与 Study 记录不一致。",
            status_code=409,
        )
    if dict(best_trial.params or {}) != dict(study.best_params or {}):
        raise ReportDomainError(
            "OPTIMIZATION_BEST_TRIAL_MISMATCH",
            "Best Trial 的参数与 Study 记录不一致。",
            status_code=409,
        )

    try:
        saved = load_saved_arx_model(
            model_id=study.optimized_model_id,
            artifact_root=artifact_root,
        )
    except ModelingDomainError as error:
        raise ReportDomainError(
            "OPTIMIZATION_BEST_MODEL_ARTIFACT_INVALID",
            "Best Trial 的模型 artifact 不存在或不可验证。",
            status_code=409,
            details=error.details,
        ) from error
    if saved.dataset_id != dataset_id or saved.source_version_id != version_id:
        raise ReportDomainError(
            "OPTIMIZATION_BEST_MODEL_LINEAGE_MISMATCH",
            "Best 模型 artifact 与所选数据集或版本不一致。",
            status_code=409,
        )

    model_runs = list(
        (
            await session.scalars(
                select(ProcessingRun)
                .where(
                    ProcessingRun.dataset_id == dataset_id,
                    ProcessingRun.source_version_id == version_id,
                    ProcessingRun.run_type == "modeling.arx",
                    ProcessingRun.status == "succeeded",
                )
                .order_by(ProcessingRun.finished_at.desc(), ProcessingRun.created_at.desc())
            )
        ).all()
    )
    model_run = next(
        (
            run
            for run in model_runs
            if str((run.result or {}).get("model_id") or "")
            == str(study.optimized_model_id)
        ),
        None,
    )
    if model_run is None:
        raise ReportDomainError(
            "OPTIMIZATION_BEST_MODEL_RUN_MISSING",
            "Best 模型缺少成功的 ProcessingRun。",
            status_code=409,
        )

    raw_indices = saved.payload.training_sample_indices
    if not raw_indices or any(
        not isinstance(value, int) or isinstance(value, bool) for value in raw_indices
    ):
        raise ReportDomainError(
            "OPTIMIZATION_BEST_SELECTION_MISSING",
            "Best 模型 artifact 未保存合法训练样本下标。",
            status_code=409,
        )
    sample_indices = list(raw_indices)
    if len(sample_indices) != len(set(sample_indices)):
        raise ReportDomainError(
            "OPTIMIZATION_BEST_SELECTION_INVALID",
            "Best Trial 的训练样本下标包含重复值。",
            status_code=409,
        )
    recorded_indices = (model_run.parameters or {}).get("training_sample_indices")
    if not isinstance(recorded_indices, list) or recorded_indices != sample_indices:
        raise ReportDomainError(
            "OPTIMIZATION_BEST_MODEL_RUN_MISMATCH",
            "Best 模型 ProcessingRun 与模型 artifact 的训练样本不一致。",
            status_code=409,
        )

    try:
        series = await load_version_series(
            session,
            version_id=version_id,
            dataset_id=dataset_id,
            artifact_root=artifact_root,
        )
        input_columns, output_column = series.resolve_columns(
            input_columns=list(saved.payload.input_columns),
            output_column=saved.payload.output_column,
        )
    except VersionDataError as error:
        raise ReportDomainError(
            error.code, error.message, status_code=error.status_code, details=error.details
        ) from error
    invalid = [index for index in sample_indices if index < 0 or index >= series.n_samples]
    if invalid:
        raise ReportDomainError(
            "OPTIMIZATION_BEST_SELECTION_INVALID",
            "Best Trial 的训练样本下标超出来源数据范围。",
            status_code=409,
            details={"invalid_indices": invalid[:20], "source_rows": series.n_samples},
        )
    train_end = int(series.n_samples * saved.payload.train_ratio)
    leaked = [index for index in sample_indices if index >= train_end]
    if leaked:
        raise ReportDomainError(
            "OPTIMIZATION_BEST_SELECTION_TEST_LEAKAGE",
            "Best Trial 的导出选择包含 Validation/Test 样本。",
            status_code=409,
            details={"invalid_indices": leaked[:20], "train_end": train_end},
        )
    return OptimizationBestSelection(
        sample_indices=sample_indices,
        provenance=ExportSelectionProvenance(
            study_id=study.id,
            best_trial_number=study.best_trial_number,
            best_trial_id=best_trial.id,
            optimized_model_id=study.optimized_model_id,
            model_processing_run_id=model_run.id,
            study_finished_at=study.finished_at,
        ),
        input_columns=input_columns,
        output_column=output_column,
        best_trial=best_trial,
        model_run=model_run,
    )


async def list_delivery_studies(
    session: AsyncSession,
    *,
    dataset_id: UUID,
    version_id: UUID,
    artifact_root: Path,
) -> DeliveryStudyListData:
    """Return only completed Studies whose Best lineage passes strict delivery checks."""

    candidates = list(
        (
            await session.scalars(
                select(OptimizationStudy)
                .where(
                    OptimizationStudy.dataset_id == dataset_id,
                    OptimizationStudy.version_id == version_id,
                    OptimizationStudy.status == "succeeded",
                )
                .order_by(OptimizationStudy.finished_at.desc())
            )
        ).all()
    )
    items: list[DeliveryStudyOption] = []
    for study in candidates:
        try:
            selection = await resolve_optimization_best_selection(
                session,
                dataset_id=dataset_id,
                version_id=version_id,
                study_id=study.id,
                artifact_root=artifact_root,
            )
        except ReportDomainError:
            continue
        assert study.finished_at is not None
        assert study.best_trial_number is not None
        assert study.best_value is not None
        assert study.optimized_model_id is not None
        items.append(
            DeliveryStudyOption(
                study_id=study.id,
                dataset_id=dataset_id,
                version_id=version_id,
                finished_at=study.finished_at,
                best_trial_number=study.best_trial_number,
                best_value=study.best_value,
                optimized_model_id=study.optimized_model_id,
                input_columns=selection.input_columns,
                output_column=selection.output_column,
            )
        )
    return DeliveryStudyListData(
        dataset_id=dataset_id,
        version_id=version_id,
        items=items,
    )


async def export_optimised_dataset(
    session: AsyncSession,
    *,
    payload: ExportDatasetRequest,
    artifact_root: Path,
    selection_provenance: ExportSelectionProvenance | None = None,
) -> ExportDatasetData:
    """Write the selected rows to CSV alongside a manifest naming their provenance."""

    strict_indices: list[int] | None = None
    strict_input_columns: list[str] | None = None
    strict_output_column: str | None = None
    if payload.mode == "optimization_best":
        if payload.dataset_id is None or payload.study_id is None:
            raise ReportDomainError(
                "OPTIMIZATION_BEST_SCOPE_REQUIRED",
                "严格 Best 导出必须指定数据集、版本和 Study。",
            )
        if payload.sample_indices:
            raise ReportDomainError(
                "OPTIMIZATION_BEST_EXPLICIT_INDICES_FORBIDDEN",
                "严格 Best 导出不接受客户端提供的样本下标。",
            )
        strict = await resolve_optimization_best_selection(
            session,
            dataset_id=payload.dataset_id,
            version_id=payload.version_id,
            study_id=payload.study_id,
            artifact_root=artifact_root,
        )
        strict_indices = sorted(strict.sample_indices)
        strict_input_columns = strict.input_columns
        strict_output_column = strict.output_column
        selection_provenance = strict.provenance

    try:
        series = await load_version_series(
            session,
            version_id=payload.version_id,
            artifact_root=artifact_root,
            dataset_id=payload.dataset_id,
        )
        input_columns, output_column = series.resolve_columns(
            input_columns=strict_input_columns or payload.input_columns or None,
            output_column=strict_output_column or payload.output_column,
        )
    except VersionDataError as error:
        raise ReportDomainError(
            error.code, error.message, status_code=error.status_code, details=error.details
        ) from error

    indices = (
        strict_indices
        if strict_indices is not None
        else sorted(set(payload.sample_indices)) if payload.sample_indices else None
    )
    selection_metadata: dict[str, object] = (
        selection_provenance.model_dump(mode="json")
        if selection_provenance is not None
        else {"selection_source": "explicit_sample_indices"}
        if indices is not None
        else {}
    )
    if indices is None:
        statement = (
            select(ProcessingRun)
            .where(ProcessingRun.run_type == "preprocessing.segment")
            .order_by(ProcessingRun.created_at.desc())
            .limit(RUN_SCAN_LIMIT)
        )
        candidates = list((await session.scalars(statement)).all())
        run = next(
            (
                candidate
                for candidate in candidates
                if _matches(
                    candidate,
                    dataset_id=payload.dataset_id,
                    version_id=payload.version_id,
                )
            ),
            None,
        )
        if run is not None:
            indices = sorted(
                set(int(v) for v in (run.result or {}).get("selected_sample_indices", []))
            )
            selection_metadata = {
                "selection_source": "preprocessing_segment",
                "selection_processing_run_id": str(run.id),
            }
    if not indices:
        raise ReportDomainError(
            "EXPORT_NO_SELECTION",
            "没有可导出的优选样本，请先执行动态区间优选或显式提供样本下标。",
            status_code=404,
        )

    n_samples = series.n_samples
    invalid_indices = [index for index in indices if not 0 <= index < n_samples]
    if selection_provenance is not None and invalid_indices:
        raise ReportDomainError(
            "OPTIMIZATION_BEST_SELECTION_INVALID",
            "Optuna Best Trial 的优选样本下标超出来源数据范围。",
            status_code=409,
            details={"invalid_indices": invalid_indices[:20], "source_rows": n_samples},
        )
    indices = [index for index in indices if 0 <= index < n_samples]
    if not indices:
        raise ReportDomainError("EXPORT_NO_SELECTION", "优选样本下标全部越界。", status_code=400)

    export_id = uuid4()
    root = artifact_root / "exports"
    root.mkdir(parents=True, exist_ok=True)
    csv_path = root / f"{export_id}.csv"
    columns = [*input_columns, output_column]
    has_timestamps = len(series.timestamps) == n_samples

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow((["timestamp"] if has_timestamps else ["sample_index"]) + columns)
        for index in indices:
            first = series.timestamps[index].isoformat() if has_timestamps else str(index)
            row = [first]
            for column in columns:
                value = series.values[column][index]
                row.append("" if not np.isfinite(value) else format(float(value), ".12g"))
            writer.writerow(row)

    manifest_path = root / f"{export_id}.manifest.json"
    manifest = {
        "export_id": str(export_id),
        "dataset_id": str(series.dataset_id),
        "version_id": str(series.version_id),
        "source_version_id": str(series.version_id),
        "origin": series.origin,
        "input_columns": list(input_columns),
        "output_column": output_column,
        "exported_rows": len(indices),
        "selected_row_count": len(indices),
        "selected_sample_indices": indices,
        "source_rows": n_samples,
        "coverage_ratio": len(indices) / n_samples if n_samples else 0.0,
        **selection_metadata,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    now = datetime.now(UTC)
    session.add(
        ProcessingRun(
            id=export_id,
            dataset_id=series.dataset_id if series.origin == "dataset" else None,
            source_version_id=series.version_id if series.origin == "dataset" else None,
            run_type="delivery.export",
            status="succeeded",
            parameters=payload.model_dump(mode="json"),
            result=manifest,
            created_at=now,
            finished_at=now,
        )
    )
    await session.commit()

    return ExportDatasetData(
        export_id=export_id,
        dataset_id=series.dataset_id,
        version_id=series.version_id,
        task=completed_task(stage="export_dataset", message="优选数据集已导出。"),
        csv_uri=csv_path.relative_to(artifact_root).as_posix(),
        manifest_uri=manifest_path.relative_to(artifact_root).as_posix(),
        exported_rows=len(indices),
        source_rows=n_samples,
        coverage_ratio=manifest["coverage_ratio"],
        columns=["timestamp" if has_timestamps else "sample_index", *columns],
    )


async def get_export_artifact(
    session: AsyncSession,
    *,
    export_id: UUID,
    artifact_root: Path,
    kind: str,
) -> tuple[Path, str, str]:
    """Resolve a persisted delivery artifact without trusting a client-provided path."""

    run = await session.get(ProcessingRun, export_id)
    if run is None or run.run_type != "delivery.export" or run.status != "succeeded":
        raise ReportDomainError(
            "EXPORT_NOT_FOUND",
            "优选数据导出记录不存在。",
            status_code=404,
        )
    if kind == "csv":
        path = artifact_root / "exports" / f"{export_id}.csv"
        filename = f"optimised-dataset-{export_id}.csv"
        media_type = "text/csv"
    elif kind == "manifest":
        path = artifact_root / "exports" / f"{export_id}.manifest.json"
        filename = f"optimised-dataset-{export_id}.manifest.json"
        media_type = "application/json"
    else:
        raise ReportDomainError("EXPORT_ARTIFACT_KIND_INVALID", "不支持的导出产物类型。")
    if not path.is_file():
        raise ReportDomainError(
            "EXPORT_ARTIFACT_MISSING",
            "优选数据导出文件不存在。",
            status_code=404,
        )
    return path, filename, media_type


def _matches(
    run: ProcessingRun,
    *,
    dataset_id: UUID | None,
    version_id: UUID | None,
) -> bool:
    """Decide whether a run belongs to the requested dataset or version.

    The foreign keys alone are not enough. Runs on S1-S6 benchmark artifacts have no row in
    ``dataset_versions`` to point at, so their FKs are deliberately null and the identity
    lives in the run's own recorded parameters. Matching on both keeps benchmark runs — the
    ones every demonstration uses — citable in a report.
    """

    parameters = run.parameters or {}
    result = run.result or {}
    dataset_matches = dataset_id is None or (
        run.dataset_id == dataset_id
        or str(parameters.get("dataset_id") or "") == str(dataset_id)
    )
    version_matches = version_id is None or (
        run.source_version_id == version_id
        or str(parameters.get("version_id") or "") == str(version_id)
        or str(parameters.get("active_version_id") or "") == str(version_id)
        or any(
            str(result.get(key) or "") == str(version_id)
            for key in ("derived_version_id", "effective_version_id", "result_version_id")
        )
    )
    return dataset_matches and version_matches


def _short_id(value: UUID) -> str:
    """Placeholders read better with a short handle than a full UUID."""

    return f"r{str(value).replace('-', '')[:8]}"
