"""Predeclare, freeze then score real industrial temporal holdouts.

Compare the established pipeline and the identical guarded grid with/without
validation-driven preprocessing feedback. Seeds are search repetitions on the same
physical run, not independent datasets. Test is masked throughout development.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from algorithms.identifiability.support import assess_input_support
from algorithms.identifiability.validation import free_run_simulate
from app.schemas.optimization import OptimizationStartRequest
from app.services import modeling_service
from app.services.optimization_service import _trial_delays, replay_training_selection, run_study
from benchmark_generalization import clean, fit, freeze, request_for
from benchmark_initial_and_oe import ROOT, score, sha, write
from benchmark_real_process import load_series

ARMS = {"established": ("established", True),
        "guard_without_feedback": ("validation_guarded", False),
        "guard_with_feedback": ("validation_guarded", True)}


def prepare(manifest_path: Path, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    if (out / "protocol.json").exists():
        raise RuntimeError("Refusing to replace a declared protocol")
    manifest = json.loads(manifest_path.read_text())
    files = [p for d in ("app", "algorithms") for p in (ROOT / "backend" / d).rglob("*.py")]
    files += [Path(__file__), *[ROOT / "backend/scripts" / name for name in
        ("benchmark_generalization.py", "benchmark_initial_and_oe.py", "benchmark_real_process.py")]]
    write(out / "protocol.json", {"declared_at": datetime.now(UTC).isoformat(),
        "manifest": str(manifest_path.absolute()), "manifest_sha256": sha(manifest_path),
        "sources": [{"path": d["path"], "sha256": d["sha256"], "role": d["role"]} for d in manifest["datasets"]],
        "code_sha256": {str(p.relative_to(ROOT)): sha(p) for p in files},
        "arms": ARMS, "seeds": [42, 7, 19, 31, 20261004], "max_trials": 2,
        "train_ratio": .6, "validation_ratio": .2, "history_guard": 43,
        "candidate_grids": {"established": 102, "guard_without_feedback": 180, "guard_with_feedback": 180},
        "winner": "maximum source rolling Validation score; first fixed-order seed on exact tie",
        "test_start": "floor(N*.8)+43", "future_output_invariance": True,
        "equal_trial_budget": True, "equal_model_fit_budget": False,
        "feedback_ablation": "guarded arms share grid, folds, admission and initial seed; only diagnose_feedback differs",
        "evidence_limits": "two outputs from one industrial test setup; temporal holdout, not chemical cross-run confirmation; two trials are bounded verification, not converged global search"})


def check(out):
    protocol = json.loads((out / "protocol.json").read_text())
    assert sha(protocol["manifest"]) == protocol["manifest_sha256"]
    assert all(sha(ROOT / name) == value for name, value in protocol["code_sha256"].items())
    assert all(sha(e["path"]) == e["sha256"] for e in protocol["sources"])
    return protocol, json.loads(Path(protocol["manifest"]).read_text())


def develop(out):
    protocol, manifest = check(out)
    if (out / "development.json").exists():
        raise RuntimeError("Refusing to overwrite development")
    document = {"protocol_sha256": sha(out / "protocol.json"), "results": []}
    for entry in manifest["datasets"]:
        series = load_series(Path(entry["path"]), entry["inputs"], entry["output"], entry["period_seconds"])
        values = {c: v.copy() for c, v in series.values.items()}
        for v in values.values():
            v[int(series.n_samples*.8):] = 0.
        hidden = replace(series, values=values)
        row = {"dataset": entry["dataset"], "arms": {}}
        for arm, (policy, feedback) in ARMS.items():
            seeds = []
            for seed in protocol["seeds"]:
                started = time.perf_counter()
                payload = OptimizationStartRequest(version_id=series.version_id, input_columns=entry["inputs"],
                    output_column=entry["output"], max_trials=protocol["max_trials"], random_seed=seed,
                    history_guard=43, optimization_policy=policy, diagnose_feedback=feedback)
                study = run_study(hidden, payload, input_columns=entry["inputs"], output_column=entry["output"])
                record = {"seed": seed, "validation_score": study.best_value, "parameters": study.best_params,
                    "metrics": study.best_metrics, "statistics": study.statistics,
                    "elapsed_seconds": time.perf_counter()-started,
                    "trials": [{"number": t.number, "state": t.state, "error_code": t.error_code,
                        "parameters": t.params, "metrics": t.metrics} for t in study.trials]}
                if study.best_params:
                    p = study.best_params
                    selected = replay_training_selection(hidden, p, entry["inputs"], entry["output"], train_ratio=.6)
                    request = request_for(hidden, p, _trial_delays(p, entry["inputs"]),
                        selected.selected_sample_indices, selected.sample_weights)
                    record["model"] = freeze(hidden, request, fit(hidden, request), validation_score=study.best_value)
                seeds.append(clean(record))
                print(entry["dataset"], arm, seed, "winner", bool(record.get("model")),
                    "fits", study.statistics["structure_evaluations"], flush=True)
            winners = [s for s in seeds if s.get("model")]
            chosen = max(winners, key=lambda s: s["validation_score"]) if winners else None
            row["arms"][arm] = {"seeds": seeds, "chosen_seed_by_validation": chosen["seed"] if chosen else None}
        document["results"].append(row)
        write(out / "development.json", clean(document))
    check(out)
    write(out / "freeze-seal.json", {"protocol_sha256": sha(out / "protocol.json"),
        "development_sha256": sha(out / "development.json"), "sealed_at": datetime.now(UTC).isoformat(),
        "all_models_frozen_before_any_test_score": True})


def evaluate(out):
    protocol, manifest = check(out)
    if (out / "test-results.json").exists():
        raise RuntimeError("Refusing to overwrite Test scores")
    seal = json.loads((out / "freeze-seal.json").read_text())
    assert seal["development_sha256"] == sha(out / "development.json")
    assert seal["protocol_sha256"] == sha(out / "protocol.json")
    development = json.loads((out / "development.json").read_text())
    document = {"freeze_seal": seal, "results": []}
    for entry, row in zip(manifest["datasets"], development["results"], strict=True):
        series = load_series(Path(entry["path"]), entry["inputs"], entry["output"], entry["period_seconds"])
        inputs = {c: series.values[c] for c in entry["inputs"]}
        output = series.values[entry["output"]]
        start, stop = int(series.n_samples*.8)+43, series.n_samples
        persistence = float(np.sqrt(np.mean((output[start:stop]-output[start-1])**2)))
        scored = {"dataset": entry["dataset"], "persistence_rmse": persistence, "arms": {}}
        for arm, result in row["arms"].items():
            seeds = []
            for seed in result["seeds"]:
                record = {"seed": seed["seed"], "state": "not_scored_no_accepted_model"}
                if seed.get("model"):
                    model = seed["model"]
                    request = modeling_service.ArxFitRequest.model_validate(model["request"])
                    structure = modeling_service._structure(request, request.input_columns)
                    theta = np.array(model["theta"])
                    with patch.object(modeling_service, "estimate_parameters", side_effect=AssertionError("Test refit")):
                        metrics = score(theta, model["intercept"], structure, inputs, output, start, stop, request.initialization_policy)
                        _, prediction = free_run_simulate(theta, structure, inputs=inputs, output=output,
                            start=start, stop=stop, intercept=model["intercept"], initialization_policy=request.initialization_policy)
                        altered = output.copy()
                        altered[start:] = np.nan
                        _, invariant = free_run_simulate(theta, structure, inputs=inputs, output=altered,
                            start=start, stop=stop, intercept=model["intercept"], initialization_policy=request.initialization_policy)
                    np.testing.assert_array_equal(prediction, invariant)
                    record.update(state="succeeded", free_run=metrics, future_output_invariance=True,
                        input_support=assess_input_support(model["preprocessing"]["training_input_support"], inputs, start=start, stop=stop))
                seeds.append(record)
            chosen = result["chosen_seed_by_validation"]
            scored["arms"][arm] = {"chosen_seed_by_validation": chosen, "seeds": seeds,
                "chosen_test": next((s for s in seeds if s["seed"] == chosen), None)}
        document["results"].append(scored)
    write(out / "test-results.json", clean(document))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=["prepare", "develop", "evaluate"], required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.stage == "prepare":
        prepare(args.manifest, args.out)
    elif args.stage == "develop":
        develop(args.out)
    else:
        evaluate(args.out)
