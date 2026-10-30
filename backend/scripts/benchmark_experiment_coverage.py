"""Separate restoring constant controls from adding real operating-run coverage."""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import zipfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from algorithms.identifiability.experiments import TrainingExperiment, fit_arx_experiments
from algorithms.identifiability.regressor import ArxStructure, IdentifiabilityError
from algorithms.identifiability.validation import free_run_simulate, is_stable
from benchmark_initial_and_oe import ROOT, score, sha, write
from benchmark_validation_guarded import first_contiguous_rows

CONTROLS = ["M101", "TH101_SetPoint", "TV101", "T116"]
CASES = {
    "distillation_b": {"scenario": "ScenarioB_BinaryComponent_n-butanolwater", "runs": ["006", "001"], "filtered": ["M101", "T116"]},
    "distillation_c": {"scenario": "ScenarioC_ReactiveOME", "runs": ["006", "001", "002"], "filtered": ["M101", "TV101", "T116"]},
}
ARMS = ("single_filtered", "single_full_controls", "multiple_full_controls")
OUT = "T114"
GUARD = 10


def prepare(archive, out):
    if (out / "coverage-protocol.json").exists():
        raise RuntimeError("Protocol already exists")
    targets = []
    with zipfile.ZipFile(archive) as z:
        for name, case in CASES.items():
            member = f"ContinuousDistillationData/{case['scenario']}/operating_point_004/test_anormal_experiment_001.csv"
            count = sum(1 for _ in csv.DictReader(io.StringIO(z.read(member).decode("utf-8-sig"))))
            targets.append({"case": name, "member": member, "rows": count, "role": "unseen_anomalous_stress_same_apparatus"})
    files = [Path(__file__), ROOT / "backend/algorithms/identifiability/experiments.py",
        ROOT / "backend/algorithms/identifiability/estimation.py", ROOT / "backend/algorithms/identifiability/regressor.py",
        ROOT / "backend/algorithms/identifiability/validation.py", ROOT / "backend/scripts/benchmark_validation_guarded.py",
        ROOT / "backend/scripts/benchmark_initial_and_oe.py", ROOT / "backend/scripts/benchmark_oe_transfer.py"]
    write(out / "coverage-protocol.json", {"archive": str(archive.resolve()), "archive_sha256": sha(archive),
        "cases": CASES, "targets": targets, "arms": ARMS, "controls": CONTROLS,
        "train_ratio": .6, "validation_ratio": .2, "guard": GUARD, "delay": 1,
        "grid": {"na": [1, 2, 4], "nb": [1, 2, 3], "alpha": [.01, .1, 1.], "initialization": ["fixed", "past_residual"]},
        "run_balance": "equal total weight per run", "dynamic_boundaries": "separate per-run regressors, no signal concatenation",
        "source_role": "previously_inspected_normal_runs_development", "macro_validation": "mean RMSE / frozen-context persistence RMSE, across source validation runs with >=8 samples",
        "time_policy": "first contiguous 30-second block; no interpolation or concatenation; target forecast begins at43",
        "selection": "Validation only; all coefficients and initialization policy sealed before target values scored",
        "scope": "data coverage ablation; different data volume, not equal fitting budget; controlled inputs retain their physical roles; no causal/deployment claim",
        "code_sha256": {str(p.relative_to(ROOT)): sha(p) for p in files}})


def check(out):
    p = json.loads((out / "coverage-protocol.json").read_text())
    assert sha(p["archive"]) == p["archive_sha256"]
    assert all(sha(ROOT / f) == digest for f, digest in p["code_sha256"].items())
    return p


def read_run(z, member):
    rows, audit = first_contiguous_rows(list(csv.DictReader(io.StringIO(z.read(member).decode("utf-8-sig")))))
    u = {c: np.array([float(row[c]) for row in rows]) for c in CONTROLS}
    y = np.array([float(row[OUT]) for row in rows])
    return u, y, audit


def develop(out):
    p = check(out)
    if (out / "coverage-development.json").exists():
        raise RuntimeError("Already developed")
    document = {"protocol_sha256": sha(out / "coverage-protocol.json"), "results": []}
    with zipfile.ZipFile(p["archive"]) as z:
        for name, case in CASES.items():
            runs = []
            for op in case["runs"]:
                member = f"ContinuousDistillationData/{case['scenario']}/operating_point_{op}/train_normal_experiment_001.csv"
                u, y, audit = read_run(z, member)
                te, ve = int(len(y)*.6), int(len(y)*.8)
                if te-GUARD <= GUARD or ve-GUARD-(te+GUARD) < 8:
                    raise RuntimeError(f"Predeclared normal run too short: {member}")
                # Source Test tails are hidden for every numerical operation below.
                y = y[:ve].copy()
                u = {c: v[:ve].copy() for c, v in u.items()}
                runs.append({"member": member, "inputs": u, "output": y, "train_end": te, "val_end": ve, "time_audit": audit})
            result = {"case": name, "arms": {}, "source_runs": [{k: v for k, v in r.items() if k not in {"inputs", "output"}} for r in runs]}
            for arm in ARMS:
                chosen_runs = runs if arm == "multiple_full_controls" else runs[:1]
                columns = case["filtered"] if arm == "single_filtered" else CONTROLS
                candidates = []
                # Validate every arm on the same normal-run Validation intervals.
                # Additional runs are validation-only for the single-run baselines.
                for na in p["grid"]["na"]:
                    for nb in p["grid"]["nb"]:
                        for alpha in p["grid"]["alpha"]:
                            st = ArxStructure.create(na=na, nb=nb, nk=1, input_columns=columns)
                            training = [TrainingExperiment(r["member"], r["inputs"], r["output"], GUARD, r["train_end"]-GUARD) for r in chosen_runs]
                            estimate = fit_arx_experiments(training, structure=st, ridge_alpha=alpha)
                            if not is_stable(estimate.parameters.theta[:na])[0]:
                                candidates.append({"na": na, "nb": nb, "alpha": alpha, "status": "unstable"})
                                continue
                            for policy in p["grid"]["initialization"]:
                                evidence = []
                                try:
                                    for r in runs:
                                        first, last = r["train_end"]+GUARD, r["val_end"]-GUARD
                                        metrics = score(estimate.parameters.theta, estimate.parameters.intercept, st, r["inputs"], r["output"], first, last, policy)
                                        persistence = float(np.sqrt(np.mean((r["output"][first:last]-r["output"][first-1])**2)))
                                        if persistence <= 1e-10:
                                            raise IdentifiabilityError("FIT_UNDEFINED", "验证持续值误差为零")
                                        evidence.append({"run": r["member"], **metrics, "persistence_rmse": persistence})
                                except IdentifiabilityError as error:
                                    candidates.append({"na": na, "nb": nb, "alpha": alpha, "policy": policy, "status": error.code})
                                    continue
                                risk = float(np.mean([e["rmse"]/e["persistence_rmse"] for e in evidence]))
                                reference = {}
                                for c in CONTROLS:
                                    values = np.concatenate([r["inputs"][c][GUARD:r["train_end"]-GUARD] for r in chosen_runs])
                                    reference[c] = {"minimum": float(values.min()), "maximum": float(values.max()), "constant": bool(np.ptp(values)<1e-10)}
                                candidates.append({"status": "succeeded", "na": na, "nb": nb, "alpha": alpha,
                                    "policy": policy, "columns": columns, "theta": estimate.parameters.theta.tolist(),
                                    "intercept": estimate.parameters.intercept, "macro_validation_risk": risk,
                                    "validation": evidence, "control_reference": reference, "lineage": estimate.lineage})
                eligible = [c for c in candidates if c["status"] == "succeeded"]
                winner = min(eligible, key=lambda c: c["macro_validation_risk"]) if eligible else None
                result["arms"][arm] = {"candidates": candidates, "winner": winner}
                print(name, arm, "Validation risk", winner["macro_validation_risk"] if winner else None, flush=True)
            document["results"].append(result)
    write(out / "coverage-development.json", document)
    write(out / "coverage-seal.json", {"development_sha256": sha(out / "coverage-development.json"), "protocol_sha256": sha(out / "coverage-protocol.json")})


def evaluate(out):
    p = check(out)
    if (out / "coverage-transfer.json").exists():
        raise RuntimeError("Already evaluated")
    seal = json.loads((out / "coverage-seal.json").read_text())
    assert seal["development_sha256"] == sha(out / "coverage-development.json")
    assert seal["protocol_sha256"] == sha(out / "coverage-protocol.json")
    sources = {r["case"]: r for r in json.loads((out / "coverage-development.json").read_text())["results"]}
    results = []
    with zipfile.ZipFile(p["archive"]) as z:
        for target in p["targets"]:
            u, y, audit = read_run(z, target["member"])
            record = {**target, "time_audit": audit, "arms": {}}
            for arm in ARMS:
                w = sources[target["case"]]["arms"][arm]["winner"]
                if not w or len(y)<59:
                    record["arms"][arm] = {"status": "no_model_or_insufficient_contiguous_rows"}
                    continue
                st = ArxStructure.create(na=w["na"], nb=w["nb"], nk=1, input_columns=w["columns"])
                theta = np.array(w["theta"])
                metrics = score(theta, w["intercept"], st, u, y, 43, len(y), w["policy"])
                args = dict(inputs=u, start=43, stop=len(y), intercept=w["intercept"], initialization_policy=w["policy"])
                predicted = free_run_simulate(theta, st, output=y, **args)[1]
                hidden = y.copy()
                hidden[43:] = np.nan
                np.testing.assert_array_equal(predicted, free_run_simulate(theta, st, output=hidden, **args)[1])
                unsupported = [c for c, ref in w["control_reference"].items() if ref["constant"] and np.any(abs(u[c]-ref["minimum"])>1e-8)]
                record["arms"][arm] = {"status": "scored_for_research", **metrics,
                    "unsupported_constant_controls": unsupported, "future_output_invariance": True, "coefficient_refit": False,
                    "model_recommendation": "unsupported_operating_point" if unsupported else "requires_independent_validation",
                    "persistence_rmse": float(np.sqrt(np.mean((y[43:]-y[42])**2)))}
            results.append(record)
            print(target["case"], record["arms"], flush=True)
    write(out / "coverage-transfer.json", {"seal_sha256": sha(out / "coverage-seal.json"), "results": results})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=["prepare", "develop", "evaluate"], required=True)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.stage == "prepare":
        prepare(args.archive, args.out)
    else:
        (develop if args.stage == "develop" else evaluate)(args.out)
