"""Compare the old model grid with rolling selection on all real process outputs.

Shared delays come from the earliest fold's Train only. Models are frozen before
Test evaluation. Previously inspected datasets provide regression evidence, not
an independent confirmation set. No segment selection in this model-only ablation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from algorithms.identifiability.validation import input_residual_correlations, input_residual_test
from app.schemas.modeling import ArxFitRequest
from app.schemas.optimization import OptimizationStartRequest
from app.services.modeling_service import ModelingDomainError, fit_arx_core
from app.services.optimization_service import (
    _delay_options,
    _rolling_fold_specs,
    _structure_grid,
    objective_value,
)
from benchmark_real_process import DATASETS, load_series


def noise_calibration() -> list[dict]:
    rows = []
    for phi in (0., .8):
        rng = np.random.default_rng(20261003)
        old_count = new_count = 0
        for _ in range(500):
            values = rng.normal(size=(4, 520))
            for t in range(1, values.shape[1]):
                values[:, t] += phi * values[:, t - 1]
            residual = values[0, 320:]
            inputs = {f"u{i}": values[i+1, 300:] for i in range(3)}
            indices = np.arange(20, 220)
            correlations = input_residual_correlations(residual, indices, inputs=inputs)
            old_count += any(max(abs(v) for v in c[1:]) > 1.96 / np.sqrt(200) for c in correlations.values())
            new_count += bool(input_residual_test(residual, indices, inputs=inputs)["rejected_channels"])
        rows.append({"independent_channels": True, "ar_coefficient": phi, "seed": 20261003,
                     "repetitions": 500, "old_false_triggers": old_count, "new_false_triggers": new_count,
                     "old_fraction": old_count / 500, "new_fraction": new_count / 500})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    document = {"mode": "model_grid_and_rolling_ablation", "train_ratio": .6, "validation_ratio": .2,
                "history_guard": 43, "selected_rows": "full_train", "previously_inspected_test": True,
                "noise_calibration": noise_calibration(), "results": []}
    grid = _structure_grid({})
    for name, (columns, outputs, period) in DATASETS.items():
        for output_column in outputs:
            series = load_series(args.data_dir / f"{name}.csv", columns, output_column, period)
            study_request = OptimizationStartRequest(version_id=series.version_id, input_columns=columns,
                output_column=output_column, history_guard=43)
            folds = _rolling_fold_specs(series.n_samples, study_request)
            options = _delay_options(series, study_request.model_copy(update={"train_ratio": folds[0][0] / series.n_samples}), columns, output_column)
            delays = {c: choices[len(choices) // 2] for c, choices in options.items()}
            hidden = {c: v.copy() for c, v in series.values.items()}
            test_start = int(series.n_samples * .8)
            for v in hidden.values():
                v[test_start:] = 0
            candidates = []
            failures = Counter()
            for index, configuration in enumerate(grid):
                request = ArxFitRequest(version_id=series.version_id, input_columns=columns,
                    output_column=output_column, model_type=configuration.get("model_type", "ARX"),
                    na=configuration["na"], nb={c: configuration["nb"] for c in columns}, delays=delays,
                    estimator=configuration["estimator"], ridge_alpha=configuration.get("ridge_alpha"),
                    regularization_kernel=configuration.get("regularization_kernel", "identity"),
                    kernel_decay=configuration.get("kernel_decay", .9), history_guard=43,
                    initialization_policy=configuration.get("initialization_policy", "fixed"),
                    initialization_window=configuration.get("initialization_window", 32))
                try:
                    result = fit_arx_core(inputs={c: hidden[c] for c in columns}, output=hidden[output_column],
                                          payload=request, input_columns=columns)
                    score = objective_value(result)[0]
                except ModelingDomainError as error:
                    failures[error.code] += 1
                    continue
                if np.isfinite(score):
                    candidates.append((score, index, request, result))
            old = max((item for item in candidates if item[1] < 60), key=lambda item: item[0])
            ranked = sorted(candidates, key=lambda item: item[0], reverse=True)
            shortlist = ranked[:6]
            for family in ("ARX", "FIR"):
                item = next((item for item in ranked if item[2].model_type == family), None)
                if item and all(existing[1] != item[1] for existing in shortlist):
                    shortlist.append(item)
            rolling_candidates = []
            for score, _index, request, result in shortlist:
                scores = [score]
                evidence = [{"train_end": folds[-1][0], "validation_end": folds[-1][1],
                             "rmse": result.validation.free_run_rmse, "score": score}]
                for train_end, val_end in folds[:-1]:
                    length = val_end + 1
                    fold_request = request.model_copy(update={"train_ratio": (train_end + .25) / length,
                        "validation_ratio": (val_end - train_end) / length})
                    try:
                        fitted = fit_arx_core(inputs={c: hidden[c][:length] for c in columns},
                            output=hidden[output_column][:length], payload=fold_request, input_columns=columns)
                        fold_score = objective_value(fitted)[0]
                    except ModelingDomainError:
                        break
                    if not np.isfinite(fold_score):
                        break
                    scores.append(fold_score)
                    evidence.append({"train_end": train_end, "validation_end": val_end,
                                     "rmse": fitted.validation.free_run_rmse, "score": fold_score})
                if len(scores) == len(folds):
                    rolling_candidates.append((float(np.mean(scores)) - .25 * float(np.std(scores)), request, evidence))
            winner = max(rolling_candidates, key=lambda item: item[0])
            row = {"dataset": name, "output": output_column, "delays": delays,
                   "source_sha256": hashlib.sha256((args.data_dir / f"{name}.csv").read_bytes()).hexdigest(),
                   "successful_candidates": len(candidates), "failures": dict(failures), "rolling_folds": winner[2]}
            for label, request in (("old_grid_latest_validation", old[2]), ("new_grid_rolling_validation", winner[1])):
                fitted = fit_arx_core(inputs={c: series.values[c] for c in columns}, output=series.values[output_column],
                    payload=request.model_copy(update={"evaluate_test": True}), input_columns=columns)
                row[label] = {"configuration": request.model_dump(mode="json"),
                              "validation_rmse": fitted.validation.free_run_rmse,
                              "test_rmse": fitted.metrics.free_run["test"].rmse,
                              "test_fit": fitted.metrics.test_free_run_fit,
                              "test_samples": series.n_samples - test_start - 43}
            row["test_rmse_ratio"] = row["new_grid_rolling_validation"]["test_rmse"] / row["old_grid_latest_validation"]["test_rmse"]
            document["results"].append(row)
            ratios = [r["test_rmse_ratio"] for r in document["results"]]
            document["summary"] = {"comparisons": len(ratios), "improved": sum(r < 1 - 1e-8 for r in ratios),
                "ties": sum(abs(r - 1) <= 1e-8 for r in ratios), "median_rmse_ratio": float(np.median(ratios)),
                "worst_rmse_ratio": max(ratios)}
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
            print(name, output_column, f"RMSE ratio {row['test_rmse_ratio']:.3f}", flush=True)


if __name__ == "__main__":
    main()
