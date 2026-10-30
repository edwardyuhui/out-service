"""Read-only replay and evidence collection for a completed optimisation study.

This module deliberately reuses the winner already selected on validation.  It does not
invoke Optuna, create a trial, update a study, or feed any held-out result back into the
search.  Its purpose is diagnosis, not another round of tuning.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np
from algorithms.identifiability.delay import prewhitened_cross_correlation
from algorithms.identifiability.excitation import profile_excitation
from algorithms.identifiability.regressor import IdentifiabilityError, build_regressor
from algorithms.identifiability.validation import one_step_predict, residual_whiteness_ratio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.optimization import OptimizationStudy
from app.schemas.diagnostics import (
    DelayPartitionDiagnostics,
    ExcitationDiagnostics,
    GeneralizationDiagnosticsData,
    PartitionDiagnostics,
    SelectionCoverageDiagnostics,
    SignalSummary,
    StabilityDiagnostics,
)
from app.schemas.modeling import ArxFitRequest, PredictionMetrics
from app.schemas.preprocessing import SegmentRequest
from app.services.evaluation_policy import generalization_risk
from app.services.modeling_service import (
    ModelingDomainError,
    _partition_rows,
    fit_arx_core,
    load_saved_arx_model,
    replay_saved_arx_core,
)
from app.services.optimization_service import OptimizationDomainError
from app.services.segment_service import SegmentDomainError, run_segment_selection
from app.services.version_data import VersionDataError, load_version_series


async def get_generalization_diagnostics(
    session: AsyncSession, *, study_id: UUID, artifact_root: Path
) -> GeneralizationDiagnosticsData:
    """Replay a validation-fixed winner to inspect its chronological partitions."""

    study = await session.get(OptimizationStudy, study_id)
    if study is None:
        raise OptimizationDomainError(
            "OPTIMIZATION_STUDY_NOT_FOUND", "寻优任务不存在。", status_code=404
        )
    if study.best_trial_number is None or not study.best_params:
        raise OptimizationDomainError(
            "BEST_TRIAL_UNAVAILABLE", "该寻优任务没有可诊断的 Best Trial。", status_code=409
        )

    parameters = dict(study.parameters or {})
    best = dict(study.best_params)
    input_columns = parameters.get("input_columns")
    output_column = parameters.get("output_column")
    if not isinstance(input_columns, list) or not all(isinstance(item, str) for item in input_columns):
        raise OptimizationDomainError(
            "STUDY_PARAMETERS_INVALID", "该寻优任务缺少可复现的输入变量配置。", status_code=409
        )
    if not isinstance(output_column, str):
        raise OptimizationDomainError(
            "STUDY_PARAMETERS_INVALID", "该寻优任务缺少可复现的输出变量配置。", status_code=409
        )
    train_ratio = _ratio(parameters.get("train_ratio"), default=0.6)
    validation_ratio = _ratio(parameters.get("validation_ratio"), default=0.2)

    try:
        series = await load_version_series(
            session,
            version_id=study.version_id,
            artifact_root=artifact_root,
            dataset_id=study.dataset_id,
        )
        inputs, output = series.resolve_columns(
            input_columns=list(input_columns), output_column=output_column
        )
        if study.optimized_model_id is not None:
            saved = load_saved_arx_model(model_id=study.optimized_model_id, artifact_root=artifact_root)
            if saved.source_version_id != series.version_id:
                raise ModelingDomainError("MODEL_SOURCE_VERSION_MISMATCH", "保存模型与寻优数据版本不一致", status_code=409)
            result = replay_saved_arx_core(saved=saved, inputs={c: series.values[c] for c in inputs}, output=series.values[output])
            selected = list(saved.payload.training_sample_indices)
            configured_guard = saved.payload.history_guard or 0
        else:
            selection = run_segment_selection(
                series,
                SegmentRequest(
                    version_id=series.version_id,
                    input_columns=inputs,
                    output_column=output,
                    window_size=int(best["window_size"]),
                    max_segments=int(best["max_segments"]),
                    max_anomaly_ratio=float(best["max_anomaly_ratio"]),
                    max_missing_ratio=float(best["max_missing_ratio"]),
                    min_input_activity_ratio=float(best["min_input_activity_ratio"]),
                    train_ratio=train_ratio,
                    nk=best.get("delays", best.get("nk", 0)),
                    history_guard=int(best.get("history_guard", parameters.get("history_guard", 32))),
                    selection_mode=best.get("selection_mode", "ensemble"),
                    adaptive_windows=best.get("adaptive_windows", True),
                ),
            )
            result = fit_arx_core(
                inputs={column: series.values[column] for column in inputs},
                output=series.values[output],
                payload=ArxFitRequest(
                    version_id=series.version_id,
                    input_columns=inputs,
                    output_column=output,
                    na=int(best["na"]),
                    nb={column: int(best["nb"]) for column in inputs},
                    delays={column: int(best.get("delays", {}).get(column, best.get("nk", 0))) for column in inputs},
                    model_type=best.get("model_type", "ARX"),
                    regularization_kernel=best.get("regularization_kernel", "identity"),
                    kernel_decay=best.get("kernel_decay", 0.9),
                    initialization_policy=best.get("initialization_policy", "fixed"),
                    initialization_window=best.get("initialization_window", 32),
                    history_guard=int(best.get("history_guard", parameters.get("history_guard", 32))),
                    sample_weights=selection.sample_weights,
                    estimator=best["estimator"],
                    ridge_alpha=best.get("ridge_alpha"),
                    train_ratio=train_ratio,
                    validation_ratio=validation_ratio,
                    training_sample_indices=selection.selected_sample_indices,
                    evaluate_test=True,
                ),
                input_columns=inputs,
            )
            selected = selection.selected_sample_indices
            configured_guard = int(best.get("history_guard", parameters.get("history_guard", 32)))
    except VersionDataError as error:
        raise OptimizationDomainError(
            error.code, error.message, status_code=error.status_code, details=error.details
        ) from error
    except (KeyError, TypeError, ValueError) as error:
        raise OptimizationDomainError(
            "STUDY_PARAMETERS_INVALID", "该寻优任务的最佳参数无法被复现。", status_code=409
        ) from error
    except (SegmentDomainError, ModelingDomainError) as error:
        raise OptimizationDomainError(
            error.code, error.message, status_code=error.status_code, details=error.details
        ) from error

    n_samples = series.n_samples
    train_end = int(n_samples * train_ratio)
    val_end = int(n_samples * (train_ratio + validation_ratio))
    guard = max(result.structure.max_history, configured_guard)
    windows = {
        "train": (0, max(train_end - guard, 0)),
        "validation": (train_end + guard, max(val_end - guard, train_end + guard)),
        "test": (val_end + guard, n_samples),
    }
    partitions = _partition_diagnostics(
        windows=windows,
        result=result,
        inputs={column: series.values[column] for column in inputs},
        output=series.values[output],
    )
    delay_peaks = _delay_peaks(
        windows=windows,
        inputs={column: series.values[column] for column in inputs},
        output=series.values[output],
    )
    first = min(selected) if selected else None
    last = max(selected) if selected else None
    span = None
    if first is not None and last is not None and train_end > 0:
        span = (last - first + 1) / train_end
    test_free_run = result.metrics.free_run.get("test")
    validation_free_run = result.metrics.free_run.get("validation")
    gap = _difference(
        validation_free_run.fit if validation_free_run else None,
        test_free_run.fit if test_free_run else None,
    )
    risk, _ = generalization_risk(gap)
    messages = _diagnostic_messages(partitions=partitions, delay_peaks=delay_peaks, gap=gap)

    return GeneralizationDiagnosticsData(
        study_id=study.id,
        dataset_id=study.dataset_id,
        version_id=study.version_id,
        metric_semantics=_METRIC_SEMANTICS,
        partitions=partitions,
        delay_peaks=delay_peaks,
        selection_coverage=SelectionCoverageDiagnostics(
            train_end_index=train_end,
            selected_sample_count=len(selected),
            first_selected_index=first,
            last_selected_index=last,
            selected_span_ratio=_finite(span),
        ),
        stability=StabilityDiagnostics(
            stable=result.validation.stable,
            max_pole_modulus=_finite(result.validation.max_pole_modulus),
        ),
        generalization_risk=risk,
        diagnostic_messages=messages,
    )


_METRIC_SEMANTICS = {
    "one_step": "ARX 使用真实历史输出；带偏移初始化的 FIR 使用当前时刻之前的残差更新；分区内同一对齐样本计算。",
    "free_run": "ARX 以预测起点前输出暖启动；FIR 可用预测前残差估计固定偏移；整个仿真区间不读取真实输出。",
    "fit": "100 * (1 - ||y-y_hat|| / ||y-mean(y)||)；自由仿真 FIT 无下限，保留真实误差。",
    "r2": "1 - SSE/SST；只可与同一预测模式、同一对齐样本上的 FIT 进行数学比较。",
}


def _partition_diagnostics(
    *, windows: dict[str, tuple[int, int]], result: Any, inputs: dict[str, np.ndarray], output: np.ndarray
) -> dict[str, PartitionDiagnostics]:
    regressor = build_regressor(inputs=inputs, output=output, structure=result.structure)
    predicted = one_step_predict(regressor, result.theta, intercept=result.intercept, output=output,
        initialization_policy=str(result.preprocessing.get("initialization_policy", "fixed")),
        initialization_window=int(result.preprocessing.get("initialization_window", 32)))
    diagnostics: dict[str, PartitionDiagnostics] = {}
    for label, (start, stop) in windows.items():
        rows = _partition_rows(regressor, start, stop)
        signals = {
            name: _signal_summary(values[start:stop]) for name, values in {**inputs, "__output__": output}.items()
        }
        input_activity = {column: _activity(values[start:stop]) for column, values in inputs.items()}
        excitation = None
        whiteness = None
        if rows.size:
            sampled_inputs = {
                column: values[regressor.time_indices[rows]] for column, values in inputs.items()
            }
            report = profile_excitation(regressor.take(rows), inputs=sampled_inputs)
            excitation = ExcitationDiagnostics(
                rank=report.rank,
                n_parameters=report.n_parameters,
                condition_number=_finite(report.condition_number),
                persistent_excitation_order=report.persistent_excitation_order,
                required_excitation_order=report.required_excitation_order,
            )
            whiteness = _finite(residual_whiteness_ratio(regressor.targets[rows] - predicted[rows]))
        diagnostics[label] = PartitionDiagnostics(
            start_index=start,
            end_index=stop,
            sample_count=int(rows.size),
            signals=signals,
            input_activity=input_activity,
            output_activity=_activity(output[start:stop]),
            excitation=excitation,
            one_step=_copy_metrics(result.metrics.one_step.get(label)),
            free_run=_copy_metrics(result.metrics.free_run.get(label)),
            residual_whiteness_ratio=whiteness,
        )
    return diagnostics


def _delay_peaks(
    *, windows: dict[str, tuple[int, int]], inputs: dict[str, np.ndarray], output: np.ndarray
) -> dict[str, dict[str, DelayPartitionDiagnostics]]:
    data: dict[str, dict[str, DelayPartitionDiagnostics]] = {}
    for column, values in inputs.items():
        data[column] = {}
        for label, (start, stop) in windows.items():
            length = stop - start
            if length < 12:
                data[column][label] = DelayPartitionDiagnostics()
                continue
            try:
                correlations, order = prewhitened_cross_correlation(
                    values[start:stop], output[start:stop], max_lag=min(20, max(0, length // 4))
                )
                peak = int(np.argmax(np.abs(correlations)))
                data[column][label] = DelayPartitionDiagnostics(
                    peak_lag=peak,
                    peak_correlation=_finite(float(correlations[peak])),
                    prewhitening_order=order,
                )
            except (IdentifiabilityError, ValueError, np.linalg.LinAlgError):
                data[column][label] = DelayPartitionDiagnostics()
    return data


def _diagnostic_messages(
    *,
    partitions: dict[str, PartitionDiagnostics],
    delay_peaks: dict[str, dict[str, DelayPartitionDiagnostics]],
    gap: float | None,
) -> list[str]:
    messages: list[str] = []
    validation = partitions.get("validation")
    test = partitions.get("test")
    if gap is not None:
        messages.append(f"验证与测试自由仿真 FIT 相差 {gap:.2f} 个百分点。")
    if test and test.one_step and test.free_run:
        difference = _difference(test.one_step.fit, test.free_run.fit)
        if difference is not None and difference > 25.0:
            messages.append(
                f"测试一步预测与自由仿真 FIT 相差 {difference:.2f} 个百分点，存在递推误差累积证据。"
            )
    if validation and test and _outside_training_range(partitions.get("train"), test):
        messages.append("测试分区至少一个信号范围超出训练分区的均值±0.5个标准差，存在工况覆盖差异证据。")
    if _has_delay_variation(delay_peaks):
        messages.append("分区预白化互相关峰滞后存在差异；这是 delay drift 的候选证据，不等同于真实过程时滞已改变。")
    if validation and test and _condition_worsened(partitions.get("train"), test):
        messages.append(_identifiability_message(partitions.get("train"), test))
    if test and _all_inputs_inactive(test):
        messages.append("测试分区所有输入活动率均为 0，属于无新激励的自由衰减尾段；该工况未覆盖持续受激响应。")
    if test and test.residual_whiteness_ratio is not None and test.residual_whiteness_ratio < 0.5:
        messages.append("测试一步预测残差白度比例低于 0.50，仍存在未建模的系统性结构。")
    if len(messages) <= 1:
        messages.append("当前证据不足以唯一确定泛化变差的根因。")
    return messages


def _outside_training_range(train: PartitionDiagnostics | None, test: PartitionDiagnostics) -> bool:
    if train is None:
        return False
    for name, test_summary in test.signals.items():
        train_summary = train.signals.get(name)
        if train_summary is None or train_summary.mean is None or train_summary.std is None:
            continue
        if test_summary.minimum is not None and test_summary.minimum < train_summary.mean - 0.5 * train_summary.std:
            return True
        if test_summary.maximum is not None and test_summary.maximum > train_summary.mean + 0.5 * train_summary.std:
            return True
    return False


def _has_delay_variation(delay_peaks: dict[str, dict[str, DelayPartitionDiagnostics]]) -> bool:
    for by_partition in delay_peaks.values():
        values = [
            item.peak_lag
            for item in by_partition.values()
            if item.peak_lag is not None
            and item.peak_correlation is not None
            and abs(item.peak_correlation) >= 0.1
        ]
        if len(values) >= 2 and max(values) - min(values) >= 2:
            return True
    return False


def _condition_worsened(train: PartitionDiagnostics | None, test: PartitionDiagnostics) -> bool:
    if train is None or train.excitation is None or test.excitation is None:
        return False
    baseline = train.excitation.condition_number
    candidate = test.excitation.condition_number
    if (
        test.excitation.rank is not None
        and test.excitation.n_parameters is not None
        and test.excitation.rank < test.excitation.n_parameters
    ):
        return True
    return baseline is not None and candidate is not None and candidate > max(10.0, baseline * 10.0)


def _all_inputs_inactive(partition: PartitionDiagnostics) -> bool:
    values = [value for value in partition.input_activity.values() if value is not None]
    return bool(values) and all(value == 0.0 for value in values)


def _identifiability_message(
    train: PartitionDiagnostics | None, test: PartitionDiagnostics
) -> str:
    excitation = test.excitation
    if (
        excitation
        and excitation.rank is not None
        and excitation.n_parameters is not None
        and excitation.rank < excitation.n_parameters
    ):
        return (
            f"测试分区回归矩阵秩为 {excitation.rank}/{excitation.n_parameters}，"
            "输入可辨识性不足。"
        )
    return "测试分区回归矩阵条件数明显高于训练分区，输入可辨识性变差。"


def _signal_summary(values: np.ndarray) -> SignalSummary:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if not finite.size:
        return SignalSummary()
    return SignalSummary(
        mean=float(np.mean(finite)),
        std=float(np.std(finite)),
        minimum=float(np.min(finite)),
        maximum=float(np.max(finite)),
    )


def _activity(values: np.ndarray) -> float | None:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size < 2:
        return None
    threshold = max(float(np.std(finite)) * 0.01, 1e-12)
    return float(np.mean(np.abs(np.diff(finite)) > threshold))


def _copy_metrics(metrics: PredictionMetrics | None) -> PredictionMetrics | None:
    return metrics.model_copy() if metrics is not None else None


def _difference(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return float(left - right)


def _ratio(value: object, *, default: float) -> float:
    return float(value) if isinstance(value, int | float) else default


def _finite(value: float | None) -> float | None:
    return float(value) if value is not None and np.isfinite(value) else None
