"""Independent public-process confirmation: develop first, immutable Test replay later.

Usage: run --stage develop, then --stage evaluate with the same --manifest.
All seeds and failures are retained. Selection sees a zeroed Test tail. Evaluation
patches parameter estimation to fail, proving coefficients cannot be refitted.
"""
from __future__ import annotations

import argparse
import json
import math
import platform
import sys
import time
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid5

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.schemas.modeling import ArxFitRequest
from app.schemas.optimization import OptimizationStartRequest
from app.schemas.preprocessing import SegmentRequest
from app.services import modeling_service
from app.services.modeling_service import ModelingDomainError, SavedArxModel, fit_arx_core
from app.services.optimization_service import (
    _delay_options,
    _rolling_fold_specs,
    _selection_params,
    _structure_grid,
    _trial_delays,
    objective_value,
    run_study,
)
from app.services.segment_service import run_segment_selection
from benchmark_real_process import load_series
from prepare_generalization_data import sha, write_json


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(value) else None
    return value


def request_for(series, configuration, delays, indices=None, weights=None):
    columns = list(series.declared_inputs)
    return ArxFitRequest(version_id=series.version_id, input_columns=columns,
        output_column=series.declared_output, na=configuration["na"],
        nb={c: configuration["nb"] for c in columns}, delays=delays,
        model_type=configuration.get("model_type", "ARX"),
        estimator=configuration["estimator"], ridge_alpha=configuration.get("ridge_alpha"),
        regularization_kernel=configuration.get("regularization_kernel", "identity"),
        kernel_decay=configuration.get("kernel_decay", .9), history_guard=43,
        initialization_policy=configuration.get("initialization_policy", "fixed"),
        initialization_window=configuration.get("initialization_window", 32),
        training_sample_indices=indices or [], sample_weights=weights or {}, evaluate_test=False)


def fit(series, request):
    return fit_arx_core(inputs={c: series.values[c] for c in request.input_columns},
        output=series.values[request.output_column], payload=request, input_columns=request.input_columns)


def freeze(series, request, result, **evidence):
    assert "test" not in result.metrics.free_run
    assert not request.evaluate_test
    assert all(i < int(series.n_samples * .6) - 43 for i in request.training_sample_indices)
    return clean({"state": "frozen", "request": request.model_dump(mode="json"),
        "theta": result.theta.tolist(), "intercept": result.intercept,
        "preprocessing": result.preprocessing, "training_rows": result.training_rows,
        "training_output_scale": result.training_output_scale,
        "validation_rmse": result.validation.free_run_rmse,
        "validation_fit": result.validation.free_run_fit,
        "excitation_shortfall": result.excitation_shortfall, **evidence})


def full_baselines(series, study):
    columns, target = list(series.declared_inputs), str(series.declared_output)
    folds = _rolling_fold_specs(series.n_samples, study)
    options = _delay_options(series, study.model_copy(update={"train_ratio": folds[0][0] / series.n_samples}), columns, target)
    delays = {c: v[len(v) // 2] for c, v in options.items()}
    candidates, failures = [], Counter()
    for index, configuration in enumerate(_structure_grid({})):
        request = request_for(series, configuration, delays)
        try:
            fitted = fit(series, request)
            score = objective_value(fitted)[0]
        except ModelingDomainError as e:
            failures[e.code] += 1
            continue
        if np.isfinite(score):
            candidates.append((score, index, request, fitted))
        else:
            failures["OBJECTIVE_REJECTED"] += 1
    result = {"delay_options": options, "delays": delays, "candidate_failures": dict(failures)}
    old = [item for item in candidates if item[1] < 60]
    if old:
        item = max(old, key=lambda x: x[0])
        result["original_grid_full_train"] = freeze(series, item[2], item[3], validation_score=item[0])
    else:
        result["original_grid_full_train"] = {"state": "failed", "error_code": "NO_VALID_CANDIDATE"}
    ranked = sorted(candidates, key=lambda x: x[0], reverse=True)
    shortlist = ranked[:study.structure_shortlist]
    for family in ("ARX", "FIR"):
        item = next((x for x in ranked if x[2].model_type == family), None)
        if item and all(x[1] != item[1] for x in shortlist):
            shortlist.append(item)
    rolling = []
    for score, _, request, fitted in shortlist:
        scores, evidence = [score], []
        for train_end, val_end in folds[:-1]:
            length = val_end + 1
            prefix = replace(series, timestamps=[], values={c: v[:length] for c, v in series.values.items()})
            folded = request.model_copy(update={"train_ratio": (train_end + .25) / length,
                "validation_ratio": (val_end - train_end) / length})
            try:
                core = fit(prefix, folded)
                value = objective_value(core)[0]
            except ModelingDomainError as e:
                failures["ROLLING_" + e.code] += 1
                break
            if not np.isfinite(value):
                failures["ROLLING_OBJECTIVE_REJECTED"] += 1
                break
            scores.append(value)
            evidence.append({"train_end": train_end, "validation_end": val_end,
                "rmse": core.validation.free_run_rmse, "score": value})
        if len(scores) == len(folds):
            evidence.append({"train_end": folds[-1][0], "validation_end": folds[-1][1],
                "rmse": fitted.validation.free_run_rmse, "score": score})
            rolling.append((float(np.mean(scores) - .25 * np.std(scores)), request, fitted, evidence))
    if rolling:
        item = max(rolling, key=lambda x: x[0])
        result["current_grid_full_train"] = freeze(series, item[1], item[2],
            validation_score=item[0], rolling_folds=item[3])
    else:
        result["current_grid_full_train"] = {"state": "failed", "error_code": "NO_ROLLING_CANDIDATE"}
    result["candidate_failures"] = dict(failures)
    return result


def develop(manifest_path, output):
    manifest = json.loads(manifest_path.read_text())
    protocol_path = manifest_path.with_name("protocol.json")
    protocol = json.loads(protocol_path.read_text())
    assert sha(protocol_path) == manifest["protocol_sha256"]
    backend = Path(__file__).resolve().parents[1]
    # A separately recorded report-only repair followed confirmation. It cannot
    # authorize a change to a numerical algorithm, even during later reproduction.
    expected = dict(protocol["code_sha256"])
    report_fix = output / "post-confirmation-report-fix.json"
    if report_fix.exists():
        for change in json.loads(report_fix.read_text())["changes"]:
            assert change["path"] in {"algorithms/agent/llm_planner.py", "app/services/report_service.py"}
            assert change["frozen_sha256"] == expected[change["path"]]
            expected[change["path"]] = change["current_sha256"]
    assert all(sha(backend / p) == digest for p, digest in expected.items()), "Algorithm changed after protocol freeze"
    assert len(_structure_grid({})) == protocol["grid_size"]
    document = {"stage": "validation_only_development", "protocol_sha256": sha(protocol_path),
        "manifest_sha256": sha(manifest_path), "started_at": datetime.now(UTC).isoformat(),
        "environment": {"python": platform.python_version(), "numpy": np.__version__}, "results": []}
    for entry in manifest["datasets"]:
        path = Path(entry["path"])
        assert sha(path) == entry["sha256"]
        series = load_series(path, entry["inputs"], entry["output"], entry["period_seconds"])
        masked = {c: v.copy() for c, v in series.values.items()}
        test_start = int(series.n_samples * .8)
        for values in masked.values():
            values[test_start:] = 0
        hidden = replace(series, values=masked)
        study = OptimizationStartRequest(version_id=hidden.version_id, input_columns=entry["inputs"],
            output_column=entry["output"], history_guard=43, max_trials=protocol["max_trials"])
        print(entry["dataset"], "developing baselines", flush=True)
        started = time.perf_counter()
        row = {"dataset": entry["dataset"], "rows": series.n_samples,
            "test_start": test_start, "test_score_start": test_start + 43,
            "baselines": full_baselines(hidden, study), "seeds": []}
        for seed in protocol["seeds"]:
            request = study.model_copy(update={"random_seed": seed})
            outcome = run_study(hidden, request, input_columns=entry["inputs"], output_column=entry["output"])
            seed_row = clean({"seed": seed, "best_parameters": outcome.best_params,
                "validation_score": outcome.best_value, "statistics": outcome.statistics,
                "trials": [{"number": t.number, "state": t.state, "value": t.value,
                    "parameters": t.params, "error_code": t.error_code, "metrics": t.metrics} for t in outcome.trials]})
            if outcome.best_params:
                params = outcome.best_params
                selection = run_segment_selection(hidden, SegmentRequest(version_id=hidden.version_id,
                    **_selection_params(params, entry["inputs"], entry["output"], train_ratio=.6)))
                formal = request_for(hidden, params, _trial_delays(params, entry["inputs"]),
                    selection.selected_sample_indices, selection.sample_weights)
                seed_row["model"] = freeze(hidden, formal, fit(hidden, formal),
                    validation_score=outcome.best_value,
                    rolling_validation=outcome.best_metrics.get("rolling_validation"),
                    selection=outcome.best_metrics.get("selection_provenance"))
            else:
                seed_row["model"] = {"state": "failed", "error_code": "NO_OPTIMIZER_WINNER"}
            row["seeds"].append(seed_row)
            print(entry["dataset"], "seed", seed, seed_row["model"]["state"], flush=True)
        valid = [s for s in row["seeds"] if s["model"]["state"] == "frozen"]
        row["chosen_seed_by_validation"] = max(valid, key=lambda s: s["validation_score"])["seed"] if valid else None
        row["elapsed_seconds"] = time.perf_counter() - started
        document["results"].append(row)
        write_json(output / "development.json", clean(document))
    document["completed_at"] = datetime.now(UTC).isoformat()
    document["all_models_frozen_before_test"] = True
    write_json(output / "development.json", clean(document))
    write_json(output / "freeze-seal.json", {"development_sha256": sha(output / "development.json"),
        "sealed_at": datetime.now(UTC).isoformat(), "datasets": len(document["results"])})


def evaluate(manifest_path, output):
    manifest = json.loads(manifest_path.read_text())
    path = output / "development.json"
    seal = json.loads((output / "freeze-seal.json").read_text())
    assert sha(path) == seal["development_sha256"]
    document = json.loads(path.read_text())
    assert document["all_models_frozen_before_test"]
    assert len(document["results"]) == len(manifest["datasets"])
    assert sha(manifest_path) == document["manifest_sha256"]
    output_rows = []
    for entry, row in zip(manifest["datasets"], document["results"], strict=True):
        assert entry["dataset"] == row["dataset"] and sha(Path(entry["path"])) == entry["sha256"]
        series = load_series(Path(entry["path"]), entry["inputs"], entry["output"], entry["period_seconds"])
        target = series.values[entry["output"]]
        start = row["test_score_start"]
        measured = target[start:]
        reference = float(target[start - 1])
        persistence_rmse = float(np.sqrt(np.mean((measured - reference) ** 2)))

        def replay(model, series=series, target=target, persistence_rmse=persistence_rmse):
            if model["state"] != "frozen":
                return model
            request = ArxFitRequest.model_validate(model["request"])
            saved = SavedArxModel(model_id=uuid5(NAMESPACE_URL, json.dumps(model, sort_keys=True)),
                dataset_id=series.dataset_id, source_version_id=series.version_id, payload=request,
                structure=modeling_service._structure(request, request.input_columns),
                theta=np.asarray(model["theta"]), intercept=model["intercept"],
                preprocessing=model["preprocessing"], artifact_uri="development.json")
            try:
                with patch.object(modeling_service, "estimate_parameters", side_effect=AssertionError("Test refitted coefficients")):
                    fitted = modeling_service.replay_saved_arx_core(saved=saved,
                        inputs={c: series.values[c] for c in request.input_columns}, output=target)
                np.testing.assert_array_equal(fitted.theta, saved.theta)
                assert fitted.intercept == saved.intercept
                free_run = fitted.metrics.free_run["test"]
                rmse = free_run.rmse
                return clean({"state": "succeeded" if rmse is not None else "failed",
                    "free_run": free_run.model_dump(mode="json"),
                    "one_step": fitted.metrics.one_step["test"].model_dump(mode="json"),
                    "normalized_rmse": rmse / model["training_output_scale"] if rmse is not None and model["training_output_scale"] > 0 else None,
                    "persistence_skill": 1 - rmse / persistence_rmse if rmse is not None and persistence_rmse > 0 else None,
                    "fixed_coefficients_verified": True})
            except ModelingDomainError as e:
                return {"state": "failed", "error_code": e.code, "fixed_coefficients_verified": True}

        tested = {"dataset": entry["dataset"], "test_samples": len(measured),
            "persistence_rmse": persistence_rmse, "persistence_initial_value": reference,
            "chosen_seed_by_validation": row["chosen_seed_by_validation"],
            "baselines": {k: replay(v) for k, v in row["baselines"].items() if k.endswith("full_train")},
            "seeds": [{"seed": s["seed"], "test": replay(s["model"])} for s in row["seeds"]]}
        output_rows.append(tested)
        print(entry["dataset"], json.dumps(tested, ensure_ascii=False), flush=True)
    assert sha(path) == seal["development_sha256"], "Frozen artifacts mutated during evaluation"
    write_json(output / "test-results.json", {"evaluated_at": datetime.now(UTC).isoformat(),
        "freeze_seal": seal, "manifest_sha256": sha(manifest_path),
        "fixed_replay_without_estimation": True, "results": output_rows})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--stage", choices=["develop", "evaluate"], required=True)
    args = parser.parse_args()
    (develop if args.stage == "develop" else evaluate)(args.manifest, args.out)
