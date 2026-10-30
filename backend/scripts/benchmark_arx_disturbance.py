"""Predeclare causal ARX compensation, freeze source models, then evaluate unseen runs."""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import zipfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from algorithms.identifiability.validation import (
    fit_percentage,
    free_run_simulate,
    initial_output_offset,
)
from app.schemas.modeling import ArxFitRequest
from app.schemas.optimization import OptimizationStartRequest
from app.services import modeling_service as modeling
from app.services.optimization_service import (
    _delay_options,
    _rolling_fold_specs,
    _structure_grid,
    _trial_delays,
    objective_value,
    replay_training_selection,
    run_study,
)
from benchmark_generalization import clean, fit, freeze, request_for
from benchmark_real_process import load_series
from prepare_generalization_data import sha, write_json

BACKEND = Path(__file__).resolve().parents[1]


def prepare(previous, out):
    manifest = json.loads((previous / "data-manifest.json").read_text())
    out.mkdir(parents=True, exist_ok=False)
    targets = [
        ("distillation_a", "ScenarioA_SingleComponent_Water", "007", "test_anormal_experiment_001.csv", "unseen_anomalous_run"),
        ("distillation_b", "ScenarioB_BinaryComponent_n-butanolwater", "007", "train_normal_experiment_001.csv", "unseen_normal_run"),
        ("distillation_c", "ScenarioC_ReactiveOME", "002", "train_normal_experiment_001.csv", "unseen_normal_run"),
    ]
    entries = []
    archive = Path(manifest["data_dir"]) / "ContinuousDistillationData.zip"
    # Metadata and row count only; no target values or performance statistics.
    with zipfile.ZipFile(archive) as z:
        for source, scenario, op, filename, role in targets:
            member = f"ContinuousDistillationData/{scenario}/operating_point_{op}/{filename}"
            raw = z.read(member)
            rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
            entries.append({"source": source, "member": member, "rows": len(rows), "role": role})
    protocol = {
        "frozen_at": datetime.now(UTC).isoformat(), "algorithm_version": "4.2.0",
        "source_manifest": str(previous / "data-manifest.json"), "source_manifest_sha256": sha(previous / "data-manifest.json"),
        "archive": str(archive), "archive_sha256": sha(archive), "targets": entries,
        "seeds": [42, 20261003, 7, 19, 31], "max_trials": 3,
        "search_policies": ["established", "disturbance_aware"], "grid_sizes": [102, 120],
        "history_guard": 43, "initialization_window": 32, "train_ratio": .6, "validation_ratio": .2,
        "scope": "Five previously scored datasets are regression. Two unseen normal and one anomalous run share the same pilot apparatus; not new factories.",
        "transfer_protocol": "Choose fixed ARX structure and delays using source rolling Validation only; compare its frozen coefficients with and without 32-point preceding residual compensation. Forecast starts at 43; no horizon output update or target coefficient fit. Source Validation chooses policy before target scoring.",
        "source_model_grid": "78 fixed ARX candidates, all three source rolling folds; no target fitting",
        "code_sha256": {str(p.relative_to(BACKEND)): sha(p) for directory in ["algorithms", "app/services", "app/schemas"]
            for p in sorted((BACKEND / directory).rglob("*.py"))},
        "script_sha256": sha(Path(__file__)),
        "previous_evidence": {str(p): sha(p) for p in previous.iterdir() if p.is_file()},
    }
    write_json(out / "protocol.json", protocol)
    print(json.dumps(entries, ensure_ascii=False), flush=True)


def check(out):
    protocol = json.loads((out / "protocol.json").read_text())
    expected_script = protocol["script_sha256"]
    repair_path = out / "script-repair.json"
    if repair_path.exists():
        repair = json.loads(repair_path.read_text())
        assert repair["before_sha256"] == expected_script
        expected_script = repair["after_sha256"]
    assert sha(Path(__file__)) == expected_script
    assert all(sha(BACKEND / p) == digest for p, digest in protocol["code_sha256"].items())
    assert all(sha(Path(p)) == digest for p, digest in protocol["previous_evidence"].items())
    assert sha(Path(protocol["archive"])) == protocol["archive_sha256"]
    assert sha(Path(protocol["source_manifest"])) == protocol["source_manifest_sha256"]
    return protocol, json.loads(Path(protocol["source_manifest"]).read_text())


def full_arx_pair(series, study):
    columns, target = list(series.declared_inputs), str(series.declared_output)
    specs = _rolling_fold_specs(series.n_samples, study)
    options = _delay_options(series, study.model_copy(update={"train_ratio": specs[0][0] / series.n_samples}), columns, target)
    delays = {c: values[len(values) // 2] for c, values in options.items()}
    ranked = []
    failures = {}
    for config in _structure_grid({}):
        if config.get("model_type", "ARX") != "ARX":
            continue
        scores, evidence, contexts = [], [], []
        request = request_for(series, config, delays)
        try:
            for train_end, val_end in specs:
                n = val_end + 1
                prefix = replace(series, values={c: v[:n] for c, v in series.values.items()})
                folded = request.model_copy(update={"train_ratio": (train_end + .25) / n,
                    "validation_ratio": (val_end - train_end) / n})
                core = fit(prefix, folded)
                score = objective_value(core)[0]
                if not np.isfinite(score):
                    raise ValueError("OBJECTIVE_REJECTED")
                scores.append(score)
                evidence.append({"train_end": train_end, "validation_end": val_end, "score": score,
                    "rmse": core.validation.free_run_rmse})
                contexts.append((prefix, folded, core))
            # Formal coefficient fit at original source split, not altered prefix ratios.
            formal = fit(series, request)
            ranked.append((float(np.mean(scores) - .25 * np.std(scores)), request, formal, evidence, contexts))
        except (modeling.ModelingDomainError, ValueError) as error:
            code = getattr(error, "code", str(error))
            failures[code] = failures.get(code, 0) + 1
    if not ranked:
        return {"state": "failed", "failures": failures}
    score, request, core, evidence, contexts = max(ranked, key=lambda item: item[0])
    adjusted_scores, adjusted_evidence = [], []
    for (prefix, folded, fitted), old in zip(contexts, evidence, strict=True):
        saved = saved_model(freeze(prefix, folded, fitted))
        saved = replace(saved, payload=saved.payload.model_copy(update={"initialization_policy": "past_residual"}))
        # Validation only, with coefficients already fitted on that fold's Train.
        adjusted = modeling._fit_arx_core(inputs={c: prefix.values[c] for c in columns},
            output=prefix.values[target], payload=saved.payload, input_columns=columns,
            fixed_parameters=(saved.theta, saved.intercept, saved.preprocessing))
        value = objective_value(adjusted)[0]
        adjusted_scores.append(value)
        adjusted_evidence.append({**old, "score": value, "rmse": adjusted.validation.free_run_rmse})
    adjusted_score = float(np.mean(adjusted_scores) - .25 * np.std(adjusted_scores))
    fixed = freeze(series, request, core, validation_score=score, rolling_folds=evidence)
    adjusted = {**fixed, "request": request.model_copy(update={"initialization_policy": "past_residual"}).model_dump(mode="json"),
        "validation_score": adjusted_score, "rolling_folds": adjusted_evidence}
    return {"fixed": fixed, "past_residual": adjusted, "chosen_policy_by_source_validation":
        "past_residual" if adjusted_score > score else "fixed", "failures": failures}


def saved_model(model):
    request = ArxFitRequest.model_validate(model["request"])
    return modeling.SavedArxModel(model_id=uuid4(), dataset_id=uuid4(), source_version_id=request.version_id,
        payload=request, structure=modeling._structure(request, request.input_columns), theta=np.asarray(model["theta"]),
        intercept=model["intercept"], preprocessing=model["preprocessing"], artifact_uri="development.json")


def develop(out):
    protocol, manifest = check(out)
    assert not (out / "freeze-seal.json").exists(), "Already frozen; do not rerun development"
    document = (json.loads((out / "development.json").read_text()) if (out / "development.json").exists()
        else {"protocol_sha256": sha(out / "protocol.json"), "results": []})
    assert document["protocol_sha256"] == sha(out / "protocol.json")
    for entry in manifest["datasets"][:5]:
        if any(row["dataset"] == entry["dataset"] for row in document["results"]):
            continue
        assert sha(Path(entry["path"])) == entry["sha256"]
        series = load_series(Path(entry["path"]), entry["inputs"], entry["output"], entry["period_seconds"])
        masked = {c: v.copy() for c, v in series.values.items()}
        for values in masked.values():
            values[int(series.n_samples * .8):] = 0
        hidden = replace(series, values=masked)
        base = OptimizationStartRequest(version_id=series.version_id, input_columns=entry["inputs"],
            output_column=entry["output"], history_guard=43, max_trials=protocol["max_trials"])
        row = {"dataset": entry["dataset"], "policies": {}}
        for policy in protocol["search_policies"]:
            seeds = []
            for seed in protocol["seeds"]:
                request = base.model_copy(update={"optimization_policy": policy, "random_seed": seed})
                outcome = run_study(hidden, request, input_columns=entry["inputs"], output_column=entry["output"])
                item = {"seed": seed, "validation_score": outcome.best_value, "statistics": outcome.statistics,
                    "best_parameters": outcome.best_params, "quality": outcome.best_metrics.get("validation_acceptance"),
                    "trials": [{"number": t.number, "state": t.state, "value": t.value, "parameters": t.params,
                        "error_code": t.error_code, "metrics": t.metrics} for t in outcome.trials]}
                if outcome.best_params:
                    p = outcome.best_params
                    selection = replay_training_selection(hidden, p, entry["inputs"], entry["output"], train_ratio=.6)
                    formal = request_for(hidden, p, _trial_delays(p, entry["inputs"]), selection.selected_sample_indices, selection.sample_weights)
                    item["model"] = freeze(hidden, formal, fit(hidden, formal), validation_score=outcome.best_value)
                seeds.append(clean(item))
                print(entry["dataset"], policy, seed, outcome.best_value, flush=True)
            eligible = [s for s in seeds if s.get("model")]
            winner = max(eligible, key=lambda s: s["validation_score"]) if eligible else None
            row["policies"][policy] = {"seeds": seeds, "chosen_seed_by_validation": winner["seed"] if winner else None}
        if entry["dataset"].startswith("distillation_"):
            row["transfer_pair"] = full_arx_pair(hidden, base)
            print(entry["dataset"], "source ARX pair frozen", flush=True)
        document["results"].append(row)
        write_json(out / "development.json", clean(document))
    check(out)
    write_json(out / "freeze-seal.json", {"development_sha256": sha(out / "development.json"),
        "protocol_sha256": sha(out / "protocol.json"), "frozen_at": datetime.now(UTC).isoformat()})


def evaluate(out):
    protocol, manifest = check(out)
    seal = json.loads((out / "freeze-seal.json").read_text())
    assert sha(out / "development.json") == seal["development_sha256"]
    development = json.loads((out / "development.json").read_text())
    results = []
    for row, entry in zip(development["results"], manifest["datasets"][:5], strict=True):
        series = load_series(Path(entry["path"]), entry["inputs"], entry["output"], entry["period_seconds"])
        tested = {"dataset": row["dataset"], "policies": {}}
        for policy, details in row["policies"].items():
            items = []
            for item in details["seeds"]:
                if "model" not in item:
                    items.append({"seed": item["seed"], "state": "failed_no_model"})
                    continue
                saved = saved_model(item["model"])
                with patch.object(modeling, "estimate_parameters", side_effect=AssertionError("Test refit")):
                    replay = modeling.replay_saved_arx_core(saved=saved,
                        inputs={c: series.values[c] for c in entry["inputs"]}, output=series.values[entry["output"]])
                np.testing.assert_array_equal(saved.theta, replay.theta)
                assert saved.intercept == replay.intercept
                items.append({"seed": item["seed"], "free_run": replay.metrics.free_run["test"].model_dump(mode="json"),
                    "initialization_policy": saved.payload.initialization_policy, "coefficient_refit": False})
            tested["policies"][policy] = {"chosen_seed_by_validation": details["chosen_seed_by_validation"], "seeds": items}
        results.append(tested)
    transfers = []
    with zipfile.ZipFile(protocol["archive"]) as archive:
        for target in protocol["targets"]:
            records = list(csv.DictReader(io.StringIO(archive.read(target["member"]).decode("utf-8-sig"))))
            source = next(r for r in development["results"] if r["dataset"] == target["source"])
            pair = source["transfer_pair"]
            tested = {**target, "models": {}, "chosen_policy_by_source_validation": pair.get("chosen_policy_by_source_validation")}
            for policy in ("fixed", "past_residual"):
                if policy not in pair:
                    tested["models"][policy] = {"state": "failed_source_model"}
                    continue
                saved = saved_model(pair[policy])
                inputs = {c: np.asarray([float(r[c]) for r in records]) for c in saved.payload.input_columns}
                output = np.asarray([float(r[saved.payload.output_column]) for r in records])
                actual, predicted = free_run_simulate(saved.theta, saved.structure, inputs=inputs, output=output,
                    start=43, stop=len(output), intercept=saved.intercept, initialization_policy=policy)
                offset, evidence = initial_output_offset(saved.theta, saved.structure, inputs=inputs,
                    output=output, start=43, intercept=saved.intercept, window=32)
                rmse = float(np.sqrt(np.mean((actual - predicted) ** 2)))
                persistence = float(np.sqrt(np.mean((actual - output[42]) ** 2)))
                changed = output.copy()
                changed[43:] = np.nan
                np.testing.assert_array_equal(predicted, free_run_simulate(saved.theta, saved.structure,
                    inputs=inputs, output=changed, start=43, stop=len(output), intercept=saved.intercept,
                    initialization_policy=policy)[1])
                tested["models"][policy] = {"state": "succeeded", "rmse": rmse,
                    "fit": fit_percentage(actual, predicted) if np.ptp(actual) > 0 else None,
                    "persistence_rmse": persistence, "persistence_skill": 1 - rmse / persistence if persistence else None,
                    "offset": offset if policy == "past_residual" else 0, "initialization": evidence if policy == "past_residual" else {},
                    "coefficient_refit": False, "future_output_invariance": True, "forecast_start": 43}
            transfers.append(clean(tested))
    check(out)
    assert sha(out / "development.json") == seal["development_sha256"]
    write_json(out / "test-results.json", clean({"freeze_seal": seal, "results": results, "transfers": transfers}))
    print(json.dumps(transfers, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["prepare", "develop", "evaluate"])
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.stage == "prepare":
        prepare(args.previous, args.out)
    else:
        {"develop": develop, "evaluate": evaluate}[args.stage](args.out)
