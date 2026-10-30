"""Model-only comparison using the actual Git initial estimator and grid.

Run develop, then evaluate. All winners are sealed before Test is replayed.
Common 24 structures isolate numerical estimation changes; expanded current102
and OE24 are separately labeled, with CPU time and solver work retained.
These already inspected real datasets provide development regression evidence.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from algorithms.identifiability.estimation import estimate_parameters, tc_prior_covariance
from algorithms.identifiability.output_error import fit_output_error
from algorithms.identifiability.regressor import ArxStructure, IdentifiabilityError, build_regressor
from algorithms.identifiability.validation import fit_percentage, free_run_simulate, is_stable
from app.schemas.optimization import OptimizationStartRequest
from app.services.modeling_service import ModelingDomainError
from app.services.optimization_service import _delay_options, _structure_grid
from benchmark_real_process import load_series

ROOT = Path(__file__).resolve().parents[2]
GUARD = 43
ARMS = ("initial24", "affine24", "current102", "oe24")
CODE_PATHS = [Path(__file__), ROOT / "backend/algorithms/identifiability/output_error.py",
              ROOT / "backend/algorithms/identifiability/estimation.py",
              ROOT / "backend/algorithms/identifiability/regressor.py",
              ROOT / "backend/algorithms/identifiability/validation.py",
              ROOT / "backend/app/services/optimization_service.py"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, document):
    Path(path).write_text(json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def initial_functions():
    """Execute only the verbatim numerical/grid functions from the original snapshot.

    This avoids importing old app services into the current process or using the
    original simulator's measured-output-dependent clipping. It is not a full
    replay of the old preprocessing/Optuna/production pipeline.
    """
    commit = subprocess.check_output(["git", "rev-parse", "f832237"], cwd=ROOT, text=True).strip()
    namespace = {"np": np, "FloatArray": np.ndarray, "Literal": Literal, "Any": Any,
                 "ModelingDomainError": ModelingDomainError}
    hashes = {}
    for path, function in [("backend/app/services/modeling_service.py", "_estimate"),
                           ("backend/app/services/optimization_service.py", "_structure_grid")]:
        source = subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=ROOT, text=True)
        node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == function)
        exec(compile(ast.Module(body=[node], type_ignores=[]), f"{commit}:{path}", "exec"), namespace)
        hashes[path] = hashlib.sha256(source.encode()).hexdigest()
    grid = namespace["_structure_grid"]({})
    if len(grid) != 24:
        raise RuntimeError("Expected the initial 24-grid snapshot, refusing a mislabeled benchmark")
    return namespace["_estimate"], grid, {"commit": commit, "source_sha256": hashes,
                                          "extraction": "verbatim_AST_functions_only"}


def score(theta, intercept, structure, inputs, output, start, stop, policy="fixed"):
    actual, predicted = free_run_simulate(theta, structure, inputs=inputs, output=output,
        start=start, stop=stop, intercept=intercept, initialization_policy=policy)
    rmse = float(np.sqrt(np.mean((actual - predicted)**2)))
    if not np.isfinite(rmse):
        raise IdentifiabilityError("NONFINITE_SCORE", "自由仿真评分非有限")
    try:
        fit = fit_percentage(actual, predicted)
    except IdentifiabilityError as error:
        if error.code != "FIT_UNDEFINED":
            raise
        fit = None
    return {"rmse": rmse, "fit": fit, "n_samples": len(actual)}


def fit_candidate(arm, configuration, inputs, output, train_stop, delays, initial_estimate):
    structure = ArxStructure.create(na=configuration["na"], nb=configuration["nb"], nk=delays,
                                   input_columns=list(inputs))
    regressor = build_regressor(inputs=inputs, output=output, structure=structure,
                               start=GUARD, stop=train_stop)
    if arm == "initial24":
        theta = initial_estimate(regressor.features, regressor.targets,
                                 configuration["estimator"], configuration.get("ridge_alpha"))
        intercept, diagnostics = 0., {"model_type": "ARX", "estimation": "raw_original_git"}
    elif arm == "oe24":
        result = fit_output_error(inputs=inputs, output=output, structure=structure,
            train_stop=train_stop, start=GUARD, ridge_alpha=configuration.get("ridge_alpha", 0.), max_nfev=100)
        theta, intercept, diagnostics = result.theta, result.intercept, result.diagnostics
    else:
        prior = tc_prior_covariance(structure, decay=configuration.get("kernel_decay", .9)) if configuration.get("regularization_kernel") == "tc" else None
        result = estimate_parameters(regressor.features, regressor.targets,
            estimator=configuration["estimator"], ridge_alpha=configuration.get("ridge_alpha"),
            fit_intercept=True, standardize=True, prior_covariance=prior)
        theta, intercept, diagnostics = result.theta, result.intercept, result.preprocessing()
    return {"configuration": configuration, "theta": theta.tolist(), "intercept": float(intercept),
            "diagnostics": diagnostics, "training_rows": regressor.n_rows,
            "stable": is_stable(theta[:structure.na])[0]}, structure


def develop(manifest_path, out):
    if (out / "protocol.json").exists():
        raise RuntimeError("Existing experiment directory: choose a new directory to preserve evidence")
    out.mkdir(parents=True, exist_ok=True)
    initial_estimate, old_grid, snapshot = initial_functions()
    manifest = json.loads(manifest_path.read_text())
    protocol = {"created_at": datetime.now(UTC).isoformat(), "initial_snapshot": snapshot,
        "manifest_sha256": sha(manifest_path), "code_sha256": {str(p.relative_to(ROOT)): sha(p) for p in CODE_PATHS},
        "train_ratio": .6, "validation_ratio": .2, "history_guard": GUARD,
        "train_start": GUARD, "train_stop": "floor(N*.6)-43",
        "validation_start": "floor(N*.6)+43", "validation_stop": "floor(N*.8)",
        "test_start": "floor(N*.8)+43", "test_stop": "N",
        "data_selection": "all_contiguous_train_rows", "delay_selection": "earliest_40_percent_train_only",
        "selection_objective": "minimum_validation_free_run_RMSE_no_test_access",
        "model_only": True, "end_to_end_original_replay": False,
        "original_harmonization": "common training rows, safe simulator, validation scoring, delays; original estimator and grid verbatim",
        "equal_candidate_budget": ["initial24", "affine24", "oe24"],
        "equal_cpu_budget": False, "expanded_grid_budget": {"current102": 102},
        "oe": {"denominator": "shared", "starts": 2, "max_nfev_per_start": 100,
               "ridge_candidates": [0., .1], "convergence_required": True},
        "previously_inspected_test": True, "evidence_role": "development_regression_not_fresh_confirmation"}
    write(out / "protocol.json", protocol)
    document = {"protocol_sha256": sha(out / "protocol.json"), "results": []}
    for entry in manifest["datasets"]:
        path = Path(entry["path"])
        assert sha(path) == entry["sha256"]
        series = load_series(path, entry["inputs"], entry["output"], entry["period_seconds"])
        n = series.n_samples
        train_end, val_end = int(n*.6), int(n*.8)
        # Neither coefficients nor candidate selection can see the held-out tail.
        output = series.values[entry["output"]][:val_end].copy()
        inputs = {c: series.values[c][:val_end].copy() for c in entry["inputs"]}
        request = OptimizationStartRequest(version_id=series.version_id, input_columns=entry["inputs"],
            output_column=entry["output"], history_guard=GUARD, train_ratio=.4)
        options = _delay_options(series, request, entry["inputs"], entry["output"])
        delays = {c: v[len(v)//2] for c, v in options.items()}
        row = {"dataset": entry["dataset"], "path": str(path), "source_sha256": sha(path),
            "inputs": entry["inputs"], "output": entry["output"], "rows": n,
            "train_end": train_end, "validation_end": val_end, "delays": delays, "arms": {}}
        for arm in ARMS:
            grid = _structure_grid({}) if arm == "current102" else old_grid
            candidates, failures = [], Counter()
            started, cpu = time.perf_counter(), time.process_time()
            for index, configuration in enumerate(grid):
                candidate_start = time.perf_counter()
                try:
                    candidate, structure = fit_candidate(arm, configuration, inputs, output, train_end-GUARD, delays, initial_estimate)
                    candidate["validation"] = score(np.array(candidate["theta"]), candidate["intercept"], structure,
                        inputs, output, train_end+GUARD, val_end, configuration.get("initialization_policy", "fixed"))
                    candidate.update(index=index, status="succeeded", elapsed_seconds=time.perf_counter()-candidate_start)
                    candidates.append(candidate)
                except (IdentifiabilityError, ModelingDomainError, np.linalg.LinAlgError, ValueError) as error:
                    code = getattr(error, "code", type(error).__name__)
                    failures[code] += 1
                    candidates.append({"index": index, "configuration": configuration, "status": "failed",
                                       "error_code": code, "elapsed_seconds": time.perf_counter()-candidate_start})
            succeeded = [c for c in candidates if c["status"] == "succeeded"]
            winner = min(succeeded, key=lambda c: (c["validation"]["rmse"], c["index"])) if succeeded else None
            row["arms"][arm] = {"candidate_budget": len(grid), "failures": dict(failures),
                "elapsed_seconds": time.perf_counter()-started, "cpu_seconds": time.process_time()-cpu,
                "candidates": candidates, "winner": winner}
            print(entry["dataset"], arm, "successful", len(succeeded), "Val RMSE",
                  winner["validation"]["rmse"] if winner else None, flush=True)
        # Expanded ARX/FIR versus OE chooses family on Validation, before any Test scoring.
        pools = [(a, row["arms"][a]["winner"]) for a in ("current102", "oe24") if row["arms"][a]["winner"]]
        row["validation_chosen_family"] = min(pools, key=lambda x: x[1]["validation"]["rmse"])[0]
        document["results"].append(row)
        write(out / "development.json", document)
    write(out / "freeze-seal.json", {"development_sha256": sha(out / "development.json"),
        "protocol_sha256": sha(out / "protocol.json"), "sealed_at": datetime.now(UTC).isoformat(),
        "all_winners_frozen_before_test": True})


def evaluate(manifest_path, out):
    if (out / "test-results.json").exists():
        raise RuntimeError("Refusing to overwrite held-out results")
    seal = json.loads((out / "freeze-seal.json").read_text())
    assert seal["development_sha256"] == sha(out / "development.json")
    assert seal["protocol_sha256"] == sha(out / "protocol.json")
    protocol = json.loads((out / "protocol.json").read_text())
    assert protocol["manifest_sha256"] == sha(manifest_path)
    expected = dict(protocol["code_sha256"])
    repair_path = out / "baseline-reference-repair.json"
    if repair_path.exists():
        repair = json.loads(repair_path.read_text())
        script_path = str(Path(__file__).relative_to(ROOT))
        assert expected[script_path] == repair["before_script_sha256"]
        assert protocol["initial_snapshot"]["commit"] == repair["pinned_initial_commit"]
        expected[script_path] = repair["after_script_sha256"]
    assert all(sha(ROOT / path) == digest for path, digest in expected.items())
    development = json.loads((out / "development.json").read_text())
    result = {"freeze_seal_sha256": sha(out / "freeze-seal.json"), "previously_inspected_test": True, "results": []}
    for row in development["results"]:
        assert sha(row["path"]) == row["source_sha256"]
        series = load_series(Path(row["path"]), row["inputs"], row["output"], None)
        inputs = {c: series.values[c] for c in row["inputs"]}
        output = series.values[row["output"]]
        first = row["validation_end"] + GUARD
        record = {"dataset": row["dataset"], "arms": {}, "validation_chosen_family": row["validation_chosen_family"]}
        for arm, evidence in row["arms"].items():
            frozen = evidence["winner"]
            if frozen is None:
                record["arms"][arm] = {"status": "no_valid_candidate"}
                continue
            configuration = frozen["configuration"]
            structure = ArxStructure.create(na=configuration["na"], nb=configuration["nb"],
                                           nk=row["delays"], input_columns=row["inputs"])
            theta = np.array(frozen["theta"])
            policy = configuration.get("initialization_policy", "fixed")
            try:
                metrics = score(theta, frozen["intercept"], structure, inputs, output, first, len(output), policy)
                args = dict(inputs=inputs, start=first, stop=len(output), intercept=frozen["intercept"], initialization_policy=policy)
                prediction = free_run_simulate(theta, structure, output=output, **args)[1]
                hidden = output.copy()
                hidden[first:] = np.nan
                np.testing.assert_array_equal(prediction, free_run_simulate(theta, structure, output=hidden, **args)[1])
                record["arms"][arm] = {"status": "succeeded", **metrics, "future_output_invariance": True,
                    "validation_rmse": frozen["validation"]["rmse"], "configuration": configuration,
                    "cpu_seconds": evidence["cpu_seconds"], "training_rows": frozen["training_rows"]}
            except IdentifiabilityError as error:
                record["arms"][arm] = {"status": "failed", "error_code": error.code}
        record["persistence_rmse"] = float(np.sqrt(np.mean((output[first:] - output[first-1])**2)))
        result["results"].append(record)
        print(row["dataset"], {a: r.get("rmse") for a, r in record["arms"].items()}, flush=True)
    write(out / "test-results.json", result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=["develop", "evaluate"], required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    (develop if args.stage == "develop" else evaluate)(args.manifest, args.out)
