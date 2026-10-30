"""Reproducible DaISy process benchmark with validation-only model selection.

    .venv/bin/python scripts/benchmark_real_process.py --data-dir ../../公开工业数据集/DaISy

Every selection strategy receives the same model grid and shared channel delays.
The chronological Test tail is evaluated once after the winner is chosen on Validation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from algorithms.identifiability.delay import estimate_delays
from algorithms.identifiability.regressor import ArxStructure, build_regressor
from algorithms.identifiability.selection import build_window_grid, select_by_energy
from algorithms.identifiability.validation import free_run_simulate
from app.schemas.modeling import ArxFitRequest
from app.schemas.preprocessing import SegmentRequest
from app.services.modeling_service import ModelingDomainError, fit_arx_core
from app.services.optimization_service import _structure_grid, objective_value
from app.services.segment_service import SegmentDomainError, run_segment_selection
from app.services.version_data import VersionSeries

DATASETS = {
    "dryer2": (["fuel_flow", "exhaust_fan_speed", "raw_material_flow"], ["dry_bulb_temperature", "wet_bulb_temperature", "raw_material_moisture"], 10.0),
    "evaporator": (["feed_flow", "vapor_flow", "cooling_water_flow"], ["product_dry_matter", "product_flow", "product_temperature"], None),
    "glassfurnace": (["heating_input_1", "cooling_input", "heating_input_2"], [f"temperature_sensor_{i}" for i in range(1, 7)], None),
}
STRATEGIES = ("full", "random_contiguous", "energy", "single_dopt", "ensemble_dopt", "adaptive_ensemble")
GUARD = 32


def load_series(path: Path, columns: list[str], output: str, period: float | None) -> VersionSeries:
    with path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    values = {column: np.asarray([float(row[column]) for row in rows]) for column in [*columns, output]}
    return VersionSeries(dataset_id=uuid5(NAMESPACE_URL, path.stem), version_id=uuid5(NAMESPACE_URL, hashlib.sha256(path.read_bytes()).hexdigest()),
                         dataset_name=path.stem, origin="dataset", timestamps=[], values=values,
                         declared_inputs=tuple(columns), declared_output=output, sample_period_seconds=period)


def select_rows(series: VersionSeries, strategy: str, delays: dict[str, int], ratio: float, budget: int, window: int, seed: int) -> tuple[list[int], dict[int, float], dict[str, object]]:
    columns, output = list(series.declared_inputs), str(series.declared_output)
    if strategy == "full":
        return [], {}, {"criterion": "all_training_rows"}
    if strategy in {"single_dopt", "ensemble_dopt", "adaptive_ensemble"}:
        outcome = run_segment_selection(series, SegmentRequest(
            version_id=series.version_id, input_columns=columns, output_column=output,
            train_ratio=ratio, nk=delays, max_rows=budget, window_size=window, history_guard=GUARD,
            selection_mode="single" if strategy == "single_dopt" else "ensemble",
            adaptive_windows=strategy == "adaptive_ensemble",
            max_anomaly_ratio=.2, min_snr_db=-10, min_input_activity_ratio=.01,
        ))
        return outcome.selected_sample_indices, outcome.sample_weights, {"criterion": outcome.selection.criterion, "model_count": outcome.selection.model_count, "candidate_count": outcome.selection.candidate_count}
    inputs = {c: series.values[c] for c in columns}
    structure = ArxStructure.create(na=4, nb=3, nk=delays, input_columns=columns)
    regressor = build_regressor(inputs=inputs, output=series.values[output], structure=structure,
                                stop=int(series.n_samples * ratio) - GUARD)
    grid = build_window_grid(regressor, window_size=window, stride=window)
    if strategy == "energy":
        # Normalise each input's contribution with training statistics only.
        normalized = regressor.features.copy()
        scale = np.std(normalized, axis=0)
        normalized /= np.where(scale > 0, scale, 1)
        from dataclasses import replace
        indices = select_by_energy(replace(regressor, features=normalized), grid, budget_rows=budget)
    else:
        order = np.random.default_rng(seed).permutation(grid.count)
        count = min(grid.count, budget // window)
        indices = np.unique(np.concatenate([grid.positions[int(i)] for i in order[:count]]))
    return regressor.time_indices[indices].astype(int).tolist(), {}, {"criterion": strategy}


def evaluate(series: VersionSeries, strategy: str, ratio: float, delays: dict[str, int], seed: int) -> dict[str, object]:
    started = time.perf_counter()
    columns, output = list(series.declared_inputs), str(series.declared_output)
    window = 20 if series.n_samples < 1500 else 40
    budget = max(window, int((int(series.n_samples * ratio) - GUARD - GUARD) * .25))
    base: dict[str, object] = {"dataset": series.dataset_name, "output": output, "strategy": strategy,
        "train_ratio": ratio, "validation_ratio": .8-ratio, "seed": seed,
        "history_guard": GUARD, "row_budget": None if strategy == "full" else budget, "delays": delays}
    failures: Counter[str] = Counter()
    try:
        indices, weights, evidence = select_rows(series, strategy, delays, ratio, budget, window, seed)
        candidates = []
        for configuration in _structure_grid({}):
            request = ArxFitRequest(version_id=series.version_id, input_columns=columns, output_column=output,
                na=configuration["na"], nb={c: configuration["nb"] for c in columns}, delays=delays,
                estimator=configuration["estimator"], ridge_alpha=configuration.get("ridge_alpha"),
                train_ratio=ratio, validation_ratio=.8-ratio, history_guard=GUARD,
                training_sample_indices=indices, sample_weights=weights)
            try:
                result = fit_arx_core(inputs={c: series.values[c] for c in columns}, output=series.values[output], payload=request, input_columns=columns)
                score, _ = objective_value(result)
                if not np.isfinite(score):
                    failures["invalid_validation_candidate"] += 1
                    continue
                candidates.append((score, request, result))
            except (ModelingDomainError, ValueError, np.linalg.LinAlgError) as error:
                failures[getattr(error, "code", type(error).__name__)] += 1
        if not candidates:
            return {**base, "status": "failed", "failure_reason": "no_valid_model", "candidate_failures": dict(failures), "elapsed_seconds": time.perf_counter()-started}
        _, winner, validation = max(candidates, key=lambda item: item[0])
        # Fixed coefficients are used for Test; no post-selection parameter estimation.
        first = int(series.n_samples * .8) + GUARD
        actual, predicted = free_run_simulate(validation.theta, validation.structure,
            inputs={c: series.values[c] for c in columns}, output=series.values[output],
            start=first, stop=series.n_samples, intercept=validation.intercept)
        residual = actual - predicted
        norm = float(np.linalg.norm(actual - np.mean(actual)))
        test_fit = 100*(1-float(np.linalg.norm(residual))/norm) if norm > 0 else None
        return {**base, "status": "succeeded", "selection": evidence,
            "configuration": winner.model_dump(mode="json"), "coefficients": validation.coefficients,
            "intercept": validation.intercept, "preprocessing": validation.preprocessing,
            "selected_indices": indices, "training_rows": validation.training_rows,
            "validation_fit": validation.metrics.val_free_run_fit, "validation_rmse": validation.validation.free_run_rmse,
            "validation_score": objective_value(validation)[0], "test_fit": test_fit,
            "test_rmse": float(np.sqrt(np.mean(residual**2))), "test_mae": float(np.mean(np.abs(residual))),
            "test_nrmse_train_scale": float(np.sqrt(np.mean(residual**2))/validation.training_output_scale),
            "test_sample_indices": list(range(first, series.n_samples)), "test_actual": actual.tolist(), "test_prediction": predicted.tolist(),
            "candidate_failures": dict(failures), "candidate_count": len(_structure_grid({})),
            "elapsed_seconds": time.perf_counter()-started}
    except (SegmentDomainError, ModelingDomainError, ValueError, np.linalg.LinAlgError) as error:
        return {**base, "status": "failed", "failure_reason": getattr(error, "code", str(error)), "elapsed_seconds": time.perf_counter()-started}


def report(document: dict[str, object], path: Path) -> None:
    rows = document["results"]
    lines = ["# 真实过程数据评测", "", "模型仅依据 Validation 选择；固定系数在尾部 Test 上评价。以下是离线辨识结果。", "",
             "主比较：同一数据、时间分区、每通道时滞及 60 个模型候选，选段方法使用相同的唯一训练行预算上限。全量训练是额外参考。", "",
             "| 数据/输出 | 训练比例 | 策略 | 训练行 | 验证 FIT | Test FIT | Test RMSE | 耗时/s |", "|---|---:|---|---:|---:|---:|---:|---:|"]
    for row in rows:
        if row["status"] == "succeeded":
            lines.append(f'| {row["dataset"]}/{row["output"]} | {row["train_ratio"]:.0%} | {row["strategy"]} | {row["training_rows"]} | {row["validation_fit"]:.2f} | {row["test_fit"]:.2f} | {row["test_rmse"]:.5f} | {row["elapsed_seconds"]:.2f} |')
        else:
            lines.append(f'| {row["dataset"]}/{row["output"]} | {row["train_ratio"]:.0%} | {row["strategy"]} | — | — | — | {row["failure_reason"]} | {row["elapsed_seconds"]:.2f} |')
    lines += ["", "## 口径与限制", "",
              "- FIT 是自由仿真拟合指标，不是准确率；表中 Test FIT 不裁剪负值。", 
              "- 每个训练比例在同一条序列上划分；两种比例共享尾部 Test，不是独立工厂或独立重复样本。",
              "- 随机连续片段为预先固定的一次种子运行，不构成统计显著性证明。",
              "- 所有方法保留原时间索引，不把不连续片段拼接后生成滞后。",
              "- 25% 是唯一训练行预算上限，窗口不可拆分，实际使用量可能不同。",
              "- 每通道时滞在训练/验证范围内估计；共享估计耗时单独记录，表内耗时为选段、模型扫描和最终评价。",
              "- 蒸发器和玻璃炉的物理采样周期未注明，CSV 的 1 秒占位不用于物理时滞解释；数值误差沿用源数据尺度。",
              "- 未进行生产控制投运或企业现场验证。", "",
              "完整配置、数据与算法 SHA256、失败候选统计、选中行和 Test 预测保存在 results.json。"]
    path.write_text("\n".join(lines)+"\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("../docs/experiments/real-process-20261003"))
    parser.add_argument("--all-outputs", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if (args.out / "results.json").exists():
        parser.error("输出目录已有评测结果，请指定新目录以保留历史运行")
    args.out.mkdir(parents=True, exist_ok=True)
    code = hashlib.sha256()
    for path in sorted([*Path("algorithms").rglob("*.py"), *Path("app").rglob("*.py")]):
        code.update(str(path).encode())
        code.update(path.read_bytes())
    document = {"generated_at": datetime.now(UTC).isoformat(), "code_sha256": code.hexdigest(), "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "protocol_version": "train-affine-ensemble-v2", "data_sha256": {}, "delay_runs": [], "results": []}
    for name, (columns, outputs, period) in DATASETS.items():
        path = args.data_dir / f"{name}.csv"
        document["data_sha256"][name] = hashlib.sha256(path.read_bytes()).hexdigest()
        for output in outputs if args.all_outputs else outputs[:1]:
            data = load_series(path, columns, output, period)
            for ratio in (.5, .6):
                started = time.perf_counter()
                delay = estimate_delays(inputs={c: data.values[c] for c in columns}, output=data.values[output],
                    max_lag=20, top_k=2, train_ratio=ratio, validation_ratio=.8-ratio, max_combinations=80, history_guard=GUARD)
                document["delay_runs"].append({"dataset": name, "output": output, "train_ratio": ratio, "delays": delay.refined_delays, "elapsed_seconds": time.perf_counter()-started})
                for strategy in STRATEGIES:
                    result = evaluate(data, strategy, ratio, delay.refined_delays, args.seed)
                    document["results"].append(result)
                    (args.out / "results.json").write_text(json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
                    report(document, args.out / "report.md")
                    print(json.dumps({k: result.get(k) for k in ("dataset", "output", "train_ratio", "strategy", "status", "validation_fit", "test_fit", "test_rmse", "elapsed_seconds", "failure_reason")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
