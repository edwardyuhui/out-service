"""Freeze shared-dynamics ablations before scoring independent distillation runs."""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from algorithms.identifiability import operating_points
from algorithms.identifiability.experiments import TrainingExperiment, fit_arx_experiments
from algorithms.identifiability.operating_points import fit_within_run_arx
from algorithms.identifiability.regressor import ArxStructure, IdentifiabilityError
from algorithms.identifiability.support import assess_input_support
from algorithms.identifiability.validation import (
    free_run_simulate,
    initial_output_offset,
    is_stable,
)
from benchmark_initial_and_oe import ROOT, score, sha
from benchmark_initial_and_oe import write as write_raw
from benchmark_validation_guarded import first_contiguous_rows

CONTROLS = ["M101", "TH101_SetPoint", "TV101", "T116"]
ARMS = {
    "pooled": {"method": "pooled", "inputs": CONTROLS},
    "within_run": {"method": "within", "inputs": CONTROLS},
    "pooled_pressure": {"method": "pooled", "inputs": [*CONTROLS, "PIC101"]},
    "within_run_pressure": {"method": "within", "inputs": [*CONTROLS, "PIC101"]},
}
CASES = {
    "distillation_b": {"scenario": "ScenarioB_BinaryComponent_n-butanolwater", "runs": ["006", "001"],
        "target": "007", "target_role": "previously_scored_normal_run_regression"},
    "distillation_c": {"scenario": "ScenarioC_ReactiveOME", "runs": ["006", "001", "002"],
        "target": "003", "target_role": "previously_unscored_normal_independent_run"},
}
GUARD = 10
FORECAST_START = 43


def write(path, document):
    def normalize(value):
        if isinstance(value, np.generic):
            return normalize(value.item())
        if isinstance(value, dict):
            return {str(k): normalize(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [normalize(v) for v in value]
        if isinstance(value, float) and not np.isfinite(value):
            return None
        return value
    write_raw(path, normalize(document))


def member(case, op):
    return f"ContinuousDistillationData/{case['scenario']}/operating_point_{op}/train_normal_experiment_001.csv"


def prepare(archive, out):
    out.mkdir(parents=True, exist_ok=True)
    if (out / "protocol.json").exists():
        raise RuntimeError("Protocol exists; preserve previous evidence")
    files = [Path(__file__), *[(ROOT / "backend/algorithms/identifiability" / f)
        for f in ["operating_points.py", "experiments.py", "estimation.py", "regressor.py", "validation.py", "support.py"]],
        ROOT / "backend/scripts/benchmark_initial_and_oe.py",
        ROOT / "backend/scripts/benchmark_validation_guarded.py", ROOT / "backend/scripts/benchmark_oe_transfer.py"]
    targets = []
    with zipfile.ZipFile(archive) as z:
        for name, case in CASES.items():
            path = member(case, case["target"])
            raw = z.read(path)
            reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
            # Registration uses names, dimensions and time metadata only.
            times = [{"Time": r["Time"]} for r in reader]
            contiguous, audit = first_contiguous_rows(times)
            targets.append({"case": name, "member": path, "role": case["target_role"],
                "rows": len(times), "retained_rows": len(contiguous), "time_audit": audit})
    write(out / "protocol.json", {"registered_at": datetime.now(UTC).isoformat(),
        "archive": str(archive.absolute()), "archive_sha256": sha(archive), "cases": CASES,
        "targets": targets, "arms": ARMS, "grid": {"na": [1, 2, 4], "nb": [1, 2, 3],
            "alpha": [.01, .1, 1.], "initialization": ["fixed", "past_residual"]},
        "train_ratio": .6, "validation_ratio": .2, "guard": GUARD, "forecast_start": FORECAST_START,
        "selection": "minimum mean RMSE/persistence across source temporal and leave-one-run-out Validation; fixed arm order breaks ties",
        "leave_one_run_out": "held run Train never enters fit or scaling; score its same chronological Validation slice",
        "source_test": "all tails after floor(N*.8) hidden during development",
        "time_policy": "first contiguous 30-second block; no interpolation or concatenation; skip short targets explicitly",
        "equal_fit_budget": "same 27 structures and two policies per arm; same source run partitions",
        "offset_policy": "past_residual uses last32 preceding measurements; frozen over forecast; no dynamics refit",
        "input_roles": "control/sensor columns only; T116 and PIC101 are known future sensor conditions, not assumed available open-loop control signals",
        "labels": "label/status/alarm columns and anomaly YAML annotations are never numerical model features",
        "scope": "one pilot apparatus, different operating conditions/material composition; C fresh normal run is short, B is regression; not factory transfer or deployment certification",
        "code_sha256": {str(p.relative_to(ROOT)): sha(p) for p in files}})
    print("registered", targets, flush=True)


def check(out):
    protocol = json.loads((out / "protocol.json").read_text())
    assert sha(protocol["archive"]) == protocol["archive_sha256"]
    expected = dict(protocol["code_sha256"])
    repair_path = out / "protocol-repair.json"
    if repair_path.exists():
        repair = json.loads(repair_path.read_text())
        for file, change in repair["changes"].items():
            assert expected[file] == change["before_sha256"]
            expected[file] = change["after_sha256"]
    assert all(sha(ROOT / f) == digest for f, digest in expected.items())
    return protocol


def read_run(z, path, columns):
    rows = list(csv.DictReader(io.StringIO(z.read(path).decode("utf-8-sig"))))
    rows, audit = first_contiguous_rows(rows)
    return {c: np.array([float(r[c]) for r in rows]) for c in columns}, np.array([float(r["T114"]) for r in rows]), audit


def fit(runs, columns, method, structure, alpha):
    training = [TrainingExperiment(r["member"], {c: r["inputs"][c] for c in columns},
        r["output"], GUARD, r["train_end"]-GUARD) for r in runs]
    estimator = fit_arx_experiments if method == "pooled" else fit_within_run_arx
    return estimator(training, structure=structure, ridge_alpha=alpha)


def develop(out):
    protocol = check(out)
    if (out / "development.json").exists():
        raise RuntimeError("Development results already exist")
    result = {"protocol_sha256": sha(out / "protocol.json"), "results": []}
    with zipfile.ZipFile(protocol["archive"]) as z:
        for name, case in protocol["cases"].items():
            runs = []
            for op in case["runs"]:
                path = member(case, op)
                u, y, audit = read_run(z, path, [*CONTROLS, "PIC101"])
                te, ve = int(len(y)*.6), int(len(y)*.8)
                if te-GUARD < GUARD+8 or ve-GUARD-(te+GUARD) < 8:
                    raise RuntimeError(f"Predeclared source too short: {path}")
                runs.append({"member": path, "inputs": {c: v[:ve] for c, v in u.items()},
                    "output": y[:ve], "train_end": te, "val_end": ve, "time_audit": audit})
            record = {"case": name, "source_runs": [{k: v for k, v in r.items() if k not in ["inputs", "output"]} for r in runs], "arms": {}}
            for arm, config in protocol["arms"].items():
                candidates = []
                for na in protocol["grid"]["na"]:
                    for nb in protocol["grid"]["nb"]:
                        for alpha in protocol["grid"]["alpha"]:
                            structure = ArxStructure.create(na=na, nb=nb, nk=1, input_columns=config["inputs"])
                            full = fit(runs, config["inputs"], config["method"], structure, alpha)
                            held = [fit([s for s in runs if s is not r], config["inputs"], config["method"], structure, alpha) for r in runs]
                            for policy in protocol["grid"]["initialization"]:
                                candidate = {"na": na, "nb": nb, "alpha": alpha, "policy": policy, "columns": config["inputs"]}
                                evidence = []
                                try:
                                    for model, r, kind in [(full, r, "temporal") for r in runs] + [(m, r, "leave_one_run_out") for m, r in zip(held, runs, strict=True)]:
                                        if not is_stable(model.parameters.theta[:na])[0]:
                                            raise IdentifiabilityError("UNSTABLE_MODEL", "验证模型不稳定")
                                        first, last = r["train_end"]+GUARD, r["val_end"]-GUARD
                                        metrics = score(model.parameters.theta, model.parameters.intercept, structure,
                                            r["inputs"], r["output"], first, last, policy)
                                        persistence = float(np.sqrt(np.mean((r["output"][first:last]-r["output"][first-1])**2)))
                                        if persistence <= 1e-10:
                                            raise IdentifiabilityError("FIT_UNDEFINED", "验证持值误差为零")
                                        evidence.append({"run": r["member"], "kind": kind, **metrics, "persistence_rmse": persistence})
                                except IdentifiabilityError as error:
                                    candidate.update(status="failed", error_code=error.code)
                                    candidates.append(candidate)
                                    continue
                                candidate.update(status="succeeded", validation=evidence,
                                    validation_risk=float(np.mean([e["rmse"]/e["persistence_rmse"] for e in evidence])),
                                    theta=full.parameters.theta.tolist(), intercept=full.parameters.intercept,
                                    input_support=full.input_support, lineage=full.lineage,
                                    excitation=full.excitation if config["method"] == "within" else None)
                                candidates.append(candidate)
                good = [c for c in candidates if c["status"] == "succeeded"]
                winner = min(good, key=lambda c: c["validation_risk"]) if good else None
                record["arms"][arm] = {"winner": winner, "candidates": candidates}
                print(name, arm, "risk", winner["validation_risk"] if winner else None, flush=True)
            good_arms = [a for a in protocol["arms"] if record["arms"][a]["winner"]]
            record["selected_arm"] = min(good_arms, key=lambda a: record["arms"][a]["winner"]["validation_risk"]) if good_arms else None
            result["results"].append(record)
    write(out / "development.json", result)
    write(out / "freeze-seal.json", {"sealed_at": datetime.now(UTC).isoformat(),
        "protocol_sha256": sha(out / "protocol.json"), "development_sha256": sha(out / "development.json"),
        "all_models_frozen_before_any_target_score": True})


def evaluate(out):
    protocol = check(out)
    if (out / "test-results.json").exists():
        raise RuntimeError("Target results already exist")
    seal = json.loads((out / "freeze-seal.json").read_text())
    assert seal["protocol_sha256"] == sha(out / "protocol.json")
    assert seal["development_sha256"] == sha(out / "development.json")
    development = {r["case"]: r for r in json.loads((out / "development.json").read_text())["results"]}
    reference_protocol = json.loads((out / "comparison-protocol.json").read_text())
    assert sha(reference_protocol["development_path"]) == reference_protocol["development_sha256"]
    previous = {r["case"]: r for r in json.loads(Path(reference_protocol["development_path"]).read_text())["results"]}
    results = []
    with zipfile.ZipFile(protocol["archive"]) as z, patch.object(operating_points,
            "estimate_parameters", side_effect=AssertionError("Target fitting forbidden")), patch(
            "algorithms.identifiability.experiments.estimate_parameters",
            side_effect=AssertionError("Target fitting forbidden")):
        for target in protocol["targets"]:
            u, y, audit = read_run(z, target["member"], [*CONTROLS, "PIC101"])
            record = {**target, "time_audit": audit, "selected_arm": development[target["case"]]["selected_arm"], "arms": {}}
            if len(y) < FORECAST_START+16:
                record["status"] = "insufficient_contiguous_rows"
                results.append(record)
                continue
            record["persistence_rmse"] = float(np.sqrt(np.mean((y[FORECAST_START:]-y[FORECAST_START-1])**2)))
            record["context_mean_rmse"] = float(np.sqrt(np.mean((y[FORECAST_START:]-y[FORECAST_START-32:FORECAST_START].mean())**2)))
            models = dict(development[target["case"]]["arms"])
            old = dict(previous[target["case"]]["arms"]["multiple_full_controls"]["winner"])
            old["input_support"] = old["control_reference"]
            models["previous_temporal_pooled"] = {"winner": old}
            for arm, item in models.items():
                w = item["winner"]
                if w is None:
                    record["arms"][arm] = {"status": "no_source_model"}
                    continue
                structure = ArxStructure.create(na=w["na"], nb=w["nb"], nk=1, input_columns=w["columns"])
                theta = np.array(w["theta"])
                kwargs = dict(inputs=u, start=FORECAST_START, stop=len(y), intercept=w["intercept"], initialization_policy=w["policy"])
                try:
                    metrics = score(theta, w["intercept"], structure, u, y, FORECAST_START, len(y), w["policy"])
                    predicted = free_run_simulate(theta, structure, output=y, **kwargs)[1]
                    hidden = y.copy()
                    hidden[FORECAST_START:] = np.nan
                    np.testing.assert_array_equal(predicted, free_run_simulate(theta, structure, output=hidden, **kwargs)[1])
                    context = initial_output_offset(theta, structure, inputs=u, output=hidden,
                        start=FORECAST_START, intercept=w["intercept"], window=32)[1] if w["policy"] == "past_residual" else {"policy": "fixed"}
                    record["arms"][arm] = {"status": "scored_for_research", **metrics,
                        "input_support": assess_input_support(w["input_support"], u, start=FORECAST_START, stop=len(y)),
                        "future_output_invariance": True, "coefficient_refit": False, "initialization": context,
                        "rmse_vs_persistence": metrics["rmse"]/record["persistence_rmse"] if record["persistence_rmse"] > 0 else None,
                        "between_run_only_inputs": [c for c, e in (w.get("excitation") or {}).items() if e["between_run_only"]]}
                except IdentifiabilityError as error:
                    record["arms"][arm] = {"status": "failed", "error_code": error.code}
            results.append(record)
            print(target["case"], target["role"], "selected", record["selected_arm"], {a: r.get("rmse") for a, r in record["arms"].items()}, flush=True)
    assert seal["development_sha256"] == sha(out / "development.json")
    write(out / "test-results.json", {"seal_sha256": sha(out / "freeze-seal.json"),
        "comparison_protocol_sha256": sha(out / "comparison-protocol.json"), "results": results})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=["prepare", "develop", "evaluate"], required=True)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    {"prepare": lambda: prepare(args.archive, args.out), "develop": lambda: develop(args.out),
        "evaluate": lambda: evaluate(args.out)}[args.stage]()
