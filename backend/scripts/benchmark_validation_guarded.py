"""Freeze the cause-based quality policy before source Test and unseen run replay."""
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

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from algorithms.identifiability.validation import free_run_simulate
from app.schemas.optimization import OptimizationStartRequest
from app.services import modeling_service as modeling
from app.services.optimization_service import _trial_delays, replay_training_selection, run_study
from benchmark_arx_disturbance import saved_model
from benchmark_generalization import clean, fit, freeze, request_for
from benchmark_initial_and_oe import ROOT, score, sha, write
from benchmark_oe_transfer import time_audit
from benchmark_real_process import load_series

TARGETS = [
    ("distillation_a", "ScenarioA_SingleComponent_Water", "005"),
    ("distillation_b", "ScenarioB_BinaryComponent_n-butanolwater", "005"),
    ("distillation_c", "ScenarioC_ReactiveOME", "005"),
]


def prepare(manifest_path, out):
    if (out / "protocol.json").exists():
        raise RuntimeError("Refusing to overwrite protocol")
    manifest = json.loads(manifest_path.read_text())
    archive = Path(manifest["data_dir"]) / "ContinuousDistillationData.zip"
    entries = []
    with zipfile.ZipFile(archive) as z:
        for source, scenario, op in TARGETS:
            member = f"ContinuousDistillationData/{scenario}/operating_point_{op}/test_anormal_experiment_001.csv"
            rows = list(csv.DictReader(io.StringIO(z.read(member).decode("utf-8-sig"))))
            entries.append({"source": source, "member": member, "rows": len(rows), "role": "previously_unscored_anomalous_stress"})
    files = [p for directory in ("algorithms", "app/services", "app/schemas") for p in (ROOT / "backend" / directory).rglob("*.py")]
    files += [Path(__file__), ROOT / "backend/scripts/benchmark_generalization.py",
              ROOT / "backend/scripts/benchmark_arx_disturbance.py", ROOT / "backend/scripts/benchmark_oe_transfer.py",
              ROOT / "backend/scripts/benchmark_initial_and_oe.py", ROOT / "backend/scripts/benchmark_real_process.py"]
    protocol = {"frozen_at": datetime.now(UTC).isoformat(), "manifest": str(manifest_path.resolve()),
        "manifest_sha256": sha(manifest_path), "archive": str(archive), "archive_sha256": sha(archive), "targets": entries,
        "policies": ["established", "validation_guarded"], "grid_sizes": [102, 180],
        "seeds": [42, 20261003, 7, 19, 31], "max_trials": 1, "history_guard": 43,
        "selection": "source rolling Validation only, strict policy requires all folds positive FIT and skill versus persistence",
        "source_test_role": "previously_seen_development_regression", "default_policy_changed": False,
        "equal_compute_budget": False, "scope": "search-mode comparison, not single-mechanism ablation; 1 trial per seed is bounded verification, not converged optimization",
        "transfer": "source model/seed choice frozen before target scores; no target fitting; previous 43 samples for state initialization only",
        "target_time_policy": "first contiguous 30-second block only, ends at first duplicate/gap/reordering; no interpolation/concatenation; minimum 43+16 rows; retain skipped records",
        "code_sha256": {str(p.relative_to(ROOT)): sha(p) for p in files}}
    write(out / "protocol.json", protocol)


def check(out):
    protocol = json.loads((out / "protocol.json").read_text())
    assert all(sha(ROOT / p) == digest for p, digest in protocol["code_sha256"].items())
    assert sha(protocol["manifest"]) == protocol["manifest_sha256"]
    assert sha(protocol["archive"]) == protocol["archive_sha256"]
    return protocol, json.loads(Path(protocol["manifest"]).read_text())


def develop(out):
    protocol, manifest = check(out)
    if (out / "development.json").exists():
        raise RuntimeError("Refusing to overwrite development")
    result = {"protocol_sha256": sha(out / "protocol.json"), "results": []}
    for entry in manifest["datasets"]:
        assert sha(entry["path"]) == entry["sha256"]
        series = load_series(Path(entry["path"]), entry["inputs"], entry["output"], entry["period_seconds"])
        # Offline prepared metadata is nominal; do not label synthetic timestamps as
        # independent verification of the original sampling times.
        values = {c: v.copy() for c, v in series.values.items()}
        for v in values.values():
            v[int(series.n_samples*.8):] = 0
        hidden = replace(series, values=values)
        row = {"dataset": entry["dataset"], "policies": {}}
        for policy in protocol["policies"]:
            seeds = []
            for seed in protocol["seeds"]:
                request = OptimizationStartRequest(version_id=hidden.version_id, input_columns=entry["inputs"],
                    output_column=entry["output"], max_trials=protocol["max_trials"], random_seed=seed,
                    history_guard=43, optimization_policy=policy)
                outcome = run_study(hidden, request, input_columns=entry["inputs"], output_column=entry["output"])
                item = {"seed": seed, "validation_score": outcome.best_value, "parameters": outcome.best_params,
                        "statistics": outcome.statistics, "metrics": outcome.best_metrics,
                        "trials": [{"state": t.state, "error_code": t.error_code, "metrics": t.metrics, "parameters": t.params} for t in outcome.trials]}
                if outcome.best_params:
                    params = outcome.best_params
                    selected = replay_training_selection(hidden, params, entry["inputs"], entry["output"], train_ratio=.6)
                    formal = request_for(hidden, params, _trial_delays(params, entry["inputs"]), selected.selected_sample_indices, selected.sample_weights)
                    item["model"] = freeze(hidden, formal, fit(hidden, formal), validation_score=outcome.best_value)
                seeds.append(clean(item))
                print(entry["dataset"], policy, seed, "winner", bool(item.get("model")), "fits", outcome.statistics["structure_evaluations"], flush=True)
            winners = [s for s in seeds if s.get("model")]
            chosen = max(winners, key=lambda s: s["validation_score"]) if winners else None
            row["policies"][policy] = {"seeds": seeds, "chosen_seed_by_validation": chosen["seed"] if chosen else None}
        result["results"].append(row)
        write(out / "development.json", clean(result))
    check(out)
    write(out / "freeze-seal.json", {"development_sha256": sha(out / "development.json"), "protocol_sha256": sha(out / "protocol.json"), "sealed_at": datetime.now(UTC).isoformat()})


def first_contiguous_rows(rows):
    """Time metadata only determines truncation; output values cannot choose a block."""
    for i in range(1, len(rows)):
        pair = time_audit(rows[i-1:i+1])
        if pair["status"] != "monotonic" or pair.get("median_interval_seconds") != 30:
            return rows[:i], {"first_break_row": i, "original_rows": len(rows), "retained_rows": i, "break_audit": pair}
    return rows, {"first_break_row": None, "original_rows": len(rows), "retained_rows": len(rows)}


def evaluate(out):
    protocol, manifest = check(out)
    if (out / "test-results.json").exists():
        raise RuntimeError("Refusing to overwrite scoring")
    seal = json.loads((out / "freeze-seal.json").read_text())
    assert sha(out / "development.json") == seal["development_sha256"]
    assert sha(out / "protocol.json") == seal["protocol_sha256"]
    development = json.loads((out / "development.json").read_text())
    results, chosen_models = [], {}
    for row, entry in zip(development["results"], manifest["datasets"], strict=True):
        series = load_series(Path(entry["path"]), entry["inputs"], entry["output"], entry["period_seconds"])
        tested = {"dataset": row["dataset"], "policies": {}}
        for policy, evidence in row["policies"].items():
            items = []
            for item in evidence["seeds"]:
                if not item.get("model"):
                    items.append({"seed": item["seed"], "status": "no_validation_accepted_model"})
                    continue
                saved = saved_model(item["model"])
                with patch.object(modeling, "estimate_parameters", side_effect=AssertionError("Test refit forbidden")):
                    replay = modeling.replay_saved_arx_core(saved=saved, inputs={c: series.values[c] for c in entry["inputs"]}, output=series.values[entry["output"]])
                np.testing.assert_array_equal(saved.theta, replay.theta)
                items.append({"seed": item["seed"], "status": "succeeded", "test": replay.metrics.free_run["test"].model_dump(mode="json"), "coefficient_refit": False})
                if item["seed"] == evidence["chosen_seed_by_validation"]:
                    chosen_models[row["dataset"], policy] = saved
            tested["policies"][policy] = {"seeds": items, "chosen_seed_by_validation": evidence["chosen_seed_by_validation"]}
        results.append(tested)
    transfers = []
    with zipfile.ZipFile(protocol["archive"]) as z:
        for target in protocol["targets"]:
            raw = list(csv.DictReader(io.StringIO(z.read(target["member"]).decode("utf-8-sig"))))
            rows, audit = first_contiguous_rows(raw)
            record = {**target, "time_audit": audit, "policies": {}}
            for policy in protocol["policies"]:
                saved = chosen_models.get((target["source"], policy))
                if saved is None:
                    record["policies"][policy] = {"status": "no_source_validation_accepted_model"}
                    continue
                if len(rows) < 59:
                    record["policies"][policy] = {"status": "insufficient_contiguous_rows"}
                    continue
                inputs = {c: np.array([float(row[c]) for row in rows]) for c in saved.payload.input_columns}
                output = np.array([float(row[saved.payload.output_column]) for row in rows])
                metrics = score(saved.theta, saved.intercept, saved.structure, inputs, output, 43, len(rows), saved.payload.initialization_policy)
                args = dict(inputs=inputs, start=43, stop=len(rows), intercept=saved.intercept, initialization_policy=saved.payload.initialization_policy)
                predicted = free_run_simulate(saved.theta, saved.structure, output=output, **args)[1]
                hidden = output.copy()
                hidden[43:] = np.nan
                np.testing.assert_array_equal(predicted, free_run_simulate(saved.theta, saved.structure, output=hidden, **args)[1])
                record["policies"][policy] = {"status": "succeeded", **metrics, "future_output_invariance": True,
                    "persistence_rmse": float(np.sqrt(np.mean((output[43:] - output[42])**2)))}
            transfers.append(record)
            print(target["source"], "transfer", record["policies"], flush=True)
    write(out / "test-results.json", clean({"freeze_seal_sha256": sha(out / "freeze-seal.json"), "source_results": results, "transfers": transfers}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=["prepare", "develop", "evaluate"], required=True)
    parser.add_argument("--manifest", type=Path, default=ROOT / "docs/experiments/generalization-20261003/data-manifest.json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.stage == "prepare":
        prepare(args.manifest, args.out)
    else:
        (develop if args.stage == "develop" else evaluate)(args.out)
