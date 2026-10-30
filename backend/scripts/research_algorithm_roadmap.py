"""Reproduce roadmap diagnostics and a validation-only order-cap pilot.

This script does not change product algorithms. Existing Test results are used
only in explicitly retrospective diagnostics; the new model pilot hides Test.
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

from algorithms.identifiability.regressor import ArxStructure
from algorithms.identifiability.validation import free_run_simulate, input_residual_correlations
from app.schemas.modeling import ArxFitRequest
from app.services.modeling_service import ModelingDomainError, fit_arx_core
from app.services.optimization_service import _structure_grid, objective_value
from benchmark_real_process import DATASETS, load_series


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    rows = json.loads(args.results.read_text())["results"]
    document = {"existing_results_sha256": hashlib.sha256(args.results.read_bytes()).hexdigest(),
                "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    document["order_ceiling"] = {"count": len(rows), "na_at_4": sum(r["configuration"]["na"] == 4 for r in rows),
        "nb_at_3": sum(max(r["configuration"]["nb"].values()) == 3 for r in rows),
        "either": sum(r["configuration"]["na"] == 4 or max(r["configuration"]["nb"].values()) == 3 for r in rows)}
    rng = np.random.default_rng(20261003)
    flagged = 0
    for _ in range(500):
        residual = rng.normal(size=200)
        inputs = {f"u{i}": rng.normal(size=220) for i in range(3)}
        correlations = input_residual_correlations(residual, np.arange(20, 220), inputs=inputs)
        flagged += any(max(abs(v) for v in c[1:]) > 1.96 / np.sqrt(200) for c in correlations.values())
    document["independent_noise_diagnostic"] = {"seed": 20261003, "repetitions": 500, "n": 200,
        "channels": 3, "lags": 20, "false_triggers": flagged, "fraction": flagged / 500}
    structure = ArxStructure.create(na=1, nb=1, nk=0, input_columns=["u"])
    original = np.ones(200)
    changed = original.copy()
    changed[160:] = 1000
    predictions = [free_run_simulate(np.array([-.5, 1.]), structure, inputs={"u": np.full(200, 1e6)},
                   output=y, start=80, stop=120)[1] for y in (original, changed)]
    document["future_sensitive_clipping"] = {"stable_pole": .5, "evaluation_range": [80, 120],
        "modified_output_start": 160, "first_prediction_before": float(predictions[0][0]),
        "first_prediction_after": float(predictions[1][0]), "equal": bool(np.array_equal(*predictions))}
    groups = {}
    for row in rows:
        groups.setdefault((row["dataset"], row["output"], row["train_ratio"]), []).append(row)
    ratios = []
    for group in groups.values():
        winner = max(group, key=lambda r: r["validation_score"])
        full = next(r for r in group if r["strategy"] == "full")
        ratios.append(winner["test_rmse"] / full["test_rmse"])
    document["retrospective_validation_strategy_choice"] = {"comparisons": len(ratios),
        "wins_vs_full": sum(v < 1 - 1e-9 for v in ratios), "ties": sum(abs(v - 1) < 1e-9 for v in ratios),
        "median_rmse_ratio": float(np.median(ratios)), "independent_confirmation": False}
    document["partition_diagnostics"] = []
    document["validation_only_pilot"] = []
    extra = [{"na": na, "nb": nb, "estimator": "ridge", "ridge_alpha": alpha}
             for na in (2, 4, 8, 12) for nb in (2, 4, 8, 12) for alpha in (.1, 1., 10.)]
    stronger = [{"na": na, "nb": nb, "estimator": "ridge", "ridge_alpha": 10.}
                for na in (1, 2, 3, 4) for nb in (1, 2, 3)]
    for name, (columns, outputs, period) in DATASETS.items():
        for output in outputs:
            series = load_series(args.data_dir / f"{name}.csv", columns, output, period)
            y = series.values[output]
            train = y[:int(y.size * .6) - 32]
            validation = y[int(y.size * .6) + 32:int(y.size * .8) - 32]
            test = y[int(y.size * .8) + 32:]
            document["partition_diagnostics"].append({"dataset": name, "output": output,
                "validation_mean_shift_train_std": float((validation.mean() - train.mean()) / train.std()),
                "test_mean_shift_train_std": float((test.mean() - train.mean()) / train.std())})
            existing = next(r for r in rows if r["dataset"] == name and r["output"] == output
                            and r["train_ratio"] == .6 and r["strategy"] == "full")
            # Hide every Test observation before calling any fitting/validation code.
            values = {c: v.copy() for c, v in series.values.items()}
            for signal in values.values():
                signal[int(y.size * .8):] = 0
            candidates = []
            failures = Counter()
            for family, grid in (("existing", _structure_grid({})), ("stronger_ridge", stronger), ("expanded", extra)):
                for configuration in grid:
                    request = ArxFitRequest(version_id=series.version_id, input_columns=columns,
                        output_column=output, nb={c: configuration["nb"] for c in columns},
                        na=configuration["na"], estimator=configuration["estimator"],
                        ridge_alpha=configuration.get("ridge_alpha"), delays=existing["delays"],
                        history_guard=32, train_ratio=.6, validation_ratio=.2)
                    try:
                        fitted = fit_arx_core(inputs={c: values[c] for c in columns}, output=values[output],
                                              payload=request, input_columns=columns)
                        score, _ = objective_value(fitted)
                        if not np.isfinite(score):
                            failures["not_eligible"] += 1
                            continue
                        candidates.append({"family": family, "configuration": configuration,
                            "validation_rmse": fitted.validation.free_run_rmse,
                            "validation_fit": fitted.validation.free_run_fit, "composite_score": score})
                    except (ModelingDomainError, ValueError, np.linalg.LinAlgError) as error:
                        failures[getattr(error, "code", type(error).__name__)] += 1
            old = [c for c in candidates if c["family"] == "existing"]
            composite = max(old, key=lambda c: c["composite_score"])
            error_best = min(old, key=lambda c: c["validation_rmse"])
            low_order = min([c for c in candidates if c["family"] != "expanded"], key=lambda c: c["validation_rmse"])
            expanded = min(candidates, key=lambda c: c["validation_rmse"])
            result = {"dataset": name, "output": output, "training": "full", "test_hidden": True,
                "existing_composite_winner": composite, "existing_rmse_winner": error_best,
                "low_order_stronger_ridge_winner": low_order,
                "expanded_rmse_winner": expanded, "candidate_count": 120, "failures": dict(failures)}
            document["validation_only_pilot"].append(result)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
            print(name, output, round(error_best["validation_rmse"], 4), round(expanded["validation_rmse"], 4), flush=True)


if __name__ == "__main__":
    main()
