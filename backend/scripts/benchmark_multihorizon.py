"""Registered model-only comparison on the unseen official cascaded-tanks Test."""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import numpy as np
from scipy.io import loadmat, whosmat

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from algorithms.identifiability.estimation import estimate_parameters
from algorithms.identifiability.experiments import TrainingExperiment
from algorithms.identifiability.multihorizon import fit_multihorizon
from algorithms.identifiability.output_error import fit_output_error
from algorithms.identifiability.regressor import ArxStructure, IdentifiabilityError, build_regressor
from algorithms.identifiability.validation import free_run_simulate, is_stable
from benchmark_initial_and_oe import ROOT, initial_functions, score, sha, write

ARMS = ("initial24", "affine24", "single_horizon24", "multihorizon24")


def raw_data(archive):
    with zipfile.ZipFile(archive) as z:
        member = next(n for n in z.namelist() if n.endswith("/dataBenchmark.mat") and not n.startswith("__MACOSX"))
        return z.read(member)


def prepare(archive, out):
    out.mkdir(parents=True, exist_ok=True)
    if (out/"protocol.json").exists():
        raise RuntimeError("Existing evidence must not be overwritten")
    _, grid, original = initial_functions()
    files = [Path(__file__), *[(ROOT/"backend/algorithms/identifiability"/f) for f in
        ("multihorizon.py", "output_error.py", "experiments.py", "estimation.py", "regressor.py", "validation.py", "support.py")],
        ROOT/"backend/scripts/benchmark_initial_and_oe.py"]
    metadata = [(name, list(shape), dtype) for name, shape, dtype in whosmat(io.BytesIO(raw_data(archive)))]
    write(out/"protocol.json", {
        "registered_at": datetime.now(UTC).isoformat(), "archive": str(archive.absolute()),
        "archive_sha256": sha(archive), "metadata_only": metadata,
        "source": "https://www.nonlinearbenchmark.org/benchmarks/cascaded-tanks",
        "official_loader": "https://github.com/MaartenSchoukens/nonlinear_benchmarks",
        "input": "u pump control voltage", "output": "y lower tank level sensor voltage",
        "train_variables": ["uEst", "yEst"], "test_variables": ["uVal", "yVal"],
        "fresh_test": True, "scope": "one real SISO fluid-level apparatus, separate official Test record; not MISO or cross-factory proof",
        "original": original, "original_grid": grid,
        "arms": ARMS, "simulation_grid": {"na": [1, 2, 3, 4], "nb": [1, 2, 3], "alpha": [0., .001]},
        "train": "[50,floor(N_est*.6))", "validation": "[floor(N_est*.65),N_est), [floor(N_est*.82),N_est)",
        "selection": "minimum mean normalized RMSE against persistence over two overlapping source Validation horizons; fixed ordering breaks ties",
        "delay": 1, "multihorizon": [1, 16, 64, 0], "max_nfev_per_start": 150,
        "refit_after_selection": False, "initialization": "measured output history strictly before origin; no fitted target offset",
        "test_start": 50, "test_forecast": "one continuous free-run to record end; known pump control inputs; no output updates",
        "comparison": "model-only, all contiguous Train rows; 24 candidates per arm, unequal solver/CPU budget, no full original pipeline replay",
        "acceptance": "report fresh Test once; do not change algorithm or selection after viewing it; no default replacement based on one SISO record",
        "code_sha256": {str(f.relative_to(ROOT)): sha(f) for f in files}})
    print("Registered metadata", metadata, flush=True)


def check(out):
    p = json.loads((out/"protocol.json").read_text())
    assert sha(p["archive"]) == p["archive_sha256"]
    assert all(sha(ROOT/f) == h for f, h in p["code_sha256"].items())
    return p


def develop(out):
    p = check(out)
    if (out/"development.json").exists():
        raise RuntimeError("Models already frozen")
    # scipy only deserializes these named variables; Test outputs are not loaded.
    data = loadmat(io.BytesIO(raw_data(p["archive"])), variable_names=["uEst", "yEst", "Ts"])
    u, y = {"u": data["uEst"].ravel()}, data["yEst"].ravel()
    n, stop = len(y), int(len(y)*.6)
    validation = [(int(n*.65), n), (int(n*.82), n)]
    initial, grid, _ = initial_functions()
    newer = [{"na": na, "nb": nb, "ridge_alpha": alpha} for na in p["simulation_grid"]["na"]
        for nb in p["simulation_grid"]["nb"] for alpha in p["simulation_grid"]["alpha"]]
    result = {"sample_period": float(data["Ts"].item()), "train_start": 50, "train_stop": stop,
              "validation_intervals": validation, "arms": {}}
    for arm in ARMS:
        candidates = []
        for config in grid if arm in ARMS[:2] else newer:
            started = time.perf_counter()
            st = ArxStructure.create(na=config["na"], nb=config["nb"], nk=1, input_columns=["u"])
            item = {"configuration": config}
            try:
                reg = build_regressor(inputs=u, output=y, structure=st, start=50, stop=stop)
                if arm == "initial24":
                    theta = initial(reg.features, reg.targets, config["estimator"], config.get("ridge_alpha"))
                    intercept, diagnostics = 0., {"estimation": "original_git_raw"}
                elif arm == "affine24":
                    fitted = estimate_parameters(reg.features, reg.targets, estimator=config["estimator"],
                        ridge_alpha=config.get("ridge_alpha", 0.), fit_intercept=True, standardize=True)
                    theta, intercept, diagnostics = fitted.theta, fitted.intercept, fitted.preprocessing()
                else:
                    kwargs = dict(structure=st, ridge_alpha=config["ridge_alpha"], max_nfev=150)
                    fitted = fit_output_error(inputs=u, output=y, start=50, train_stop=stop, **kwargs) if arm == "single_horizon24" else fit_multihorizon(
                        [TrainingExperiment("tanks_est_train", u, y, 50, stop)], horizons=tuple(p["multihorizon"]), **kwargs)
                    theta, intercept, diagnostics = fitted.theta, fitted.intercept, fitted.diagnostics
                if not is_stable(theta[:st.na])[0]:
                    raise IdentifiabilityError("UNSTABLE_MODEL", "模型不稳定")
                metrics = [score(theta, intercept, st, u, y, a, b) for a, b in validation]
                baseline = [float(np.sqrt(np.mean((y[a:b]-y[a-1])**2))) for a, b in validation]
                risk = float(np.mean([m["rmse"]/b for m, b in zip(metrics, baseline, strict=True)]))
                item.update(status="succeeded", theta=theta.tolist(), intercept=float(intercept),
                    diagnostics=diagnostics, validation=metrics, validation_risk=risk)
            except IdentifiabilityError as error:
                item.update(status="failed", error_code=error.code)
            item["elapsed_seconds"] = time.perf_counter()-started
            candidates.append(item)
            print(arm, config, item["status"], item.get("validation_risk"), flush=True)
        successful = [c for c in candidates if c["status"] == "succeeded"]
        result["arms"][arm] = {"winner": min(successful, key=lambda c: c["validation_risk"]) if successful else None,
                               "candidates": candidates}
    result["selected_arm"] = min([a for a in ARMS if result["arms"][a]["winner"]],
                                  key=lambda a: result["arms"][a]["winner"]["validation_risk"])
    write(out/"development.json", result)
    write(out/"freeze-seal.json", {"sealed_at": datetime.now(UTC).isoformat(),
        "protocol_sha256": sha(out/"protocol.json"), "development_sha256": sha(out/"development.json"),
        "test_outputs_loaded_during_development": False})


def evaluate(out):
    p = check(out)
    if (out/"test-results.json").exists():
        raise RuntimeError("Test already scored; preserve evidence")
    seal = json.loads((out/"freeze-seal.json").read_text())
    assert seal["protocol_sha256"] == sha(out/"protocol.json")
    assert seal["development_sha256"] == sha(out/"development.json")
    dev = json.loads((out/"development.json").read_text())
    data = loadmat(io.BytesIO(raw_data(p["archive"])), variable_names=["uVal", "yVal"])
    u, y = {"u": data["uVal"].ravel()}, data["yVal"].ravel()
    hidden = y.copy()
    hidden[50:] = np.nan
    result = {"seal_sha256": sha(out/"freeze-seal.json"), "selected_arm": dev["selected_arm"],
        "n_samples": len(y)-50, "persistence_rmse": float(np.sqrt(np.mean((y[50:]-y[49])**2))), "arms": {}}
    with patch("scipy.optimize.least_squares", side_effect=AssertionError("Test fitting forbidden")), patch(
            "numpy.linalg.lstsq", side_effect=AssertionError("Test fitting forbidden")):
        for arm, record in dev["arms"].items():
            w = record["winner"]
            if w is None:
                result["arms"][arm] = {"status": "no_model"}
                continue
            config = w["configuration"]
            st = ArxStructure.create(na=config["na"], nb=config["nb"], nk=1, input_columns=["u"])
            kwargs = dict(theta=np.array(w["theta"]), structure=st, inputs=u,
                start=50, stop=len(y), intercept=w["intercept"])
            prediction = free_run_simulate(output=hidden, **kwargs)[1]
            np.testing.assert_array_equal(prediction, free_run_simulate(output=y, **kwargs)[1])
            result["arms"][arm] = {**score(kwargs["theta"], w["intercept"], st, u, y, 50, len(y)),
                "future_output_invariance": True, "refit": False}
    write(out/"test-results.json", result)
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=["prepare", "develop", "evaluate"], required=True)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    {"prepare": lambda: prepare(args.archive, args.out), "develop": lambda: develop(args.out),
        "evaluate": lambda: evaluate(args.out)}[args.stage]()
