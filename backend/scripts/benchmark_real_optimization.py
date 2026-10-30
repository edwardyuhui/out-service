"""Run the actual staged optimizer on one output from each real process."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.schemas.optimization import OptimizationStartRequest
from app.services.optimization_service import evaluate_best_trial, run_study
from benchmark_real_process import DATASETS, load_series


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--trials", type=int, default=10)
    args = parser.parse_args()
    results = []
    for name, (columns, outputs, period) in DATASETS.items():
        series = load_series(args.data_dir / f"{name}.csv", columns, outputs[0], period)
        payload = OptimizationStartRequest(version_id=series.version_id, input_columns=columns,
            output_column=outputs[0], max_trials=args.trials, random_seed=42, history_guard=32)
        started = time.perf_counter()
        outcome = run_study(series, payload, input_columns=columns, output_column=outputs[0])
        evaluation = evaluate_best_trial(series, payload, outcome, input_columns=columns, output_column=outputs[0]) if outcome.best_params else None
        reference_baselines = {}
        if evaluation is not None and evaluation.test_free_run_rmse is not None:
            guard = int(evaluation.parameters.get("history_guard", payload.history_guard))
            first = int(series.n_samples * (payload.train_ratio + payload.validation_ratio)) + guard
            output = series.values[outputs[0]]
            for label, constant in (("persistence", output[first - 1]),
                                    ("past_median", np.median(output[max(0, first - 32):first]))):
                rmse = float(np.sqrt(np.mean((output[first:] - constant) ** 2)))
                reference_baselines[f"{label}_rmse"] = rmse
                reference_baselines[f"{label}_skill"] = 1 - evaluation.test_free_run_rmse / rmse if rmse else None
        results.append({"dataset": name, "output": outputs[0], "request": payload.model_dump(mode="json"),
            "best_parameters": outcome.best_params, "best_validation_score": outcome.best_value, "best_metrics": outcome.best_metrics, "statistics": outcome.statistics,
            "test": {"status": evaluation.status, "validation_fit": evaluation.validation_free_run_fit, "test_fit": evaluation.test_free_run_fit, "test_rmse": evaluation.test_free_run_rmse, "parameters": evaluation.parameters, "error_code": evaluation.error_code, "reference_baselines": reference_baselines} if evaluation else None,
            "trials": [{"number": t.number, "state": t.state, "value": t.value, "parameters": t.params,
                        "error_code": t.error_code, "feedback": t.metrics.get("adaptive_feedback"), "rolling_validation": t.metrics.get("rolling_validation"), "diagnostic": t.metrics.get("validation_feedback", {}).get("summary", {}).get("input_residual_test")} for t in outcome.trials],
            "elapsed_seconds": time.perf_counter() - started})
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"selection_partition": "validation", "seed": 42,
            "results": results}, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        print(name, evaluation.status if evaluation else "no_winner", flush=True)


if __name__ == "__main__":
    main()
