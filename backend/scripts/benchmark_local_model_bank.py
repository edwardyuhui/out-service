"""Validate local model routing on source runs; targets are development regression."""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from algorithms.identifiability.model_bank import FrozenLocalModel, simulate_local_bank
from algorithms.identifiability.regressor import ArxStructure, IdentifiabilityError
from algorithms.identifiability.support import assess_input_support
from algorithms.identifiability.validation import fit_percentage, is_stable
from benchmark_initial_and_oe import ROOT, score, sha
from benchmark_operating_points import (
    CASES,
    CONTROLS,
    FORECAST_START,
    GUARD,
    fit,
    member,
    read_run,
    write,
)

GROUPS = {"controls": CONTROLS, "pressure": [*CONTROLS, "PIC101"]}
ROUTES = ["past_block", "nearest_input", "uniform"]


def restore(model):
    return FrozenLocalModel(model["name"], ArxStructure.create(na=model["na"], nb=model["nb"], nk=1,
        input_columns=model["columns"]), np.array(model["theta"]), model["intercept"], model["policy"], model["input_center"])


def metrics(actual, predicted):
    try:
        fit = fit_percentage(actual, predicted)
    except IdentifiabilityError as error:
        if error.code != "FIT_UNDEFINED":
            raise
        fit = None
    return {"rmse": float(np.sqrt(np.mean((actual-predicted)**2))), "fit": fit, "n_samples": len(actual)}


def scales(models, columns):
    # Source means and within-run variances were frozen from Train rows only.
    center = {c: float(np.mean([m["input_center"][c] for m in models])) for c in columns}
    return {c: max(float(np.sqrt(np.mean([m["input_variance"][c]+(m["input_center"][c]-center[c])**2 for m in models]))), 1e-8)
        for c in columns}


def prepare(archive, source, out):
    out.mkdir(parents=True, exist_ok=True)
    if (out/"protocol.json").exists():
        raise RuntimeError("Preserve existing protocol")
    files = [Path(__file__), ROOT/"backend/algorithms/identifiability/model_bank.py",
        ROOT/"backend/scripts/benchmark_operating_points.py", ROOT/"backend/algorithms/identifiability/operating_points.py",
        ROOT/"backend/algorithms/identifiability/experiments.py", ROOT/"backend/algorithms/identifiability/estimation.py",
        ROOT/"backend/algorithms/identifiability/regressor.py", ROOT/"backend/algorithms/identifiability/validation.py",
        ROOT/"backend/algorithms/identifiability/support.py", ROOT/"backend/scripts/benchmark_initial_and_oe.py",
        ROOT/"backend/scripts/benchmark_validation_guarded.py", ROOT/"backend/scripts/benchmark_oe_transfer.py"]
    write(out/"protocol.json", {"registered_at": datetime.now(UTC).isoformat(), "archive": str(archive.absolute()),
        "archive_sha256": sha(archive), "source": str(source.absolute()),
        "source_development_sha256": sha(source/"development.json"), "cases": CASES,
        "groups": GROUPS, "routing": ROUTES, "grid": {"na": [1, 2, 4], "nb": [1, 2, 3], "alpha": [.01, .1, 1.], "policy": ["fixed", "past_residual"]},
        "local_selection": "each model from its run Train, configuration by that run chronological Validation only",
        "routing_selection": "mean leave-one-run-out RMSE/persistence across source runs, held run excluded from bank and normalization",
        "global_comparator": "source stage-one pooled candidate with lowest leave-one-run-out risk, controls/pressure reported separately",
        "prefix_policy": "routing may use known target observations strictly before origin; model coefficients and routing rule frozen, route fixed for whole horizon",
        "forecast_start": FORECAST_START, "guard": GUARD,
        "input_roles": "T116/PIC101 are measured sensor trajectories; conditional simulation, not future-unknown open-loop prediction",
        "target_role": "both target runs have already been scored, including C op003 in stage one; development regression only",
        "formal_default_changed": False,
        "code_sha256": {str(p.relative_to(ROOT)): sha(p) for p in files}})


def check(out):
    p = json.loads((out/"protocol.json").read_text())
    assert sha(p["archive"]) == p["archive_sha256"]
    assert sha(Path(p["source"])/"development.json") == p["source_development_sha256"]
    assert all(sha(ROOT/path) == digest for path, digest in p["code_sha256"].items())
    return p


def develop(out):
    p = check(out)
    if (out/"development.json").exists():
        raise RuntimeError("Development results exist")
    global_sources = {r["case"]: r for r in json.loads((Path(p["source"])/"development.json").read_text())["results"]}
    result = {"protocol_sha256": sha(out/"protocol.json"), "results": []}
    with zipfile.ZipFile(p["archive"]) as z:
        for name, case in p["cases"].items():
            runs = []
            for op in case["runs"]:
                path = member(case, op)
                u, y, audit = read_run(z, path, GROUPS["pressure"])
                te, ve = int(len(y)*.6), int(len(y)*.8)
                runs.append({"member": path, "inputs": {c: v[:ve] for c, v in u.items()}, "output": y[:ve],
                    "train_end": te, "val_end": ve, "time_audit": audit})
            record = {"case": name, "banks": {}, "candidates": [], "global": {}}
            for group, columns in GROUPS.items():
                models = []
                for r in runs:
                    candidates = []
                    for na in p["grid"]["na"]:
                        for nb in p["grid"]["nb"]:
                            for alpha in p["grid"]["alpha"]:
                                structure = ArxStructure.create(na=na, nb=nb, nk=1, input_columns=columns)
                                estimate = fit([r], columns, "pooled", structure, alpha)
                                if not is_stable(estimate.parameters.theta[:na])[0]:
                                    continue
                                for policy in p["grid"]["policy"]:
                                    try:
                                        evidence = score(estimate.parameters.theta, estimate.parameters.intercept, structure,
                                            r["inputs"], r["output"], r["train_end"]+GUARD, r["val_end"]-GUARD, policy)
                                    except IdentifiabilityError:
                                        continue
                                    values = {c: r["inputs"][c][GUARD:r["train_end"]-GUARD] for c in columns}
                                    candidates.append({"name": r["member"], "na": na, "nb": nb, "alpha": alpha,
                                        "policy": policy, "columns": columns, "theta": estimate.parameters.theta.tolist(),
                                        "intercept": estimate.parameters.intercept, "validation": evidence,
                                        "input_center": {c: float(v.mean()) for c, v in values.items()},
                                        "input_variance": {c: float(v.var()) for c, v in values.items()},
                                        "input_support": estimate.input_support, "lineage": estimate.lineage})
                    if not candidates:
                        raise RuntimeError(f"No local source model for {r['member']}")
                    models.append(min(candidates, key=lambda c: c["validation"]["rmse"]))
                record["banks"][group] = models
                for route in p["routing"]:
                    evidence = []
                    try:
                        for r in runs:
                            held_bank = [m for m in models if m["name"] != r["member"]]
                            first, last = r["train_end"]+GUARD, r["val_end"]-GUARD
                            actual, predicted, decision = simulate_local_bank([restore(m) for m in held_bank], inputs=r["inputs"],
                                output=r["output"], start=first, stop=last, policy=route, input_scale=scales(held_bank, columns))
                            evidence.append({"run": r["member"], **metrics(actual, predicted), "routing": decision,
                                "persistence_rmse": float(np.sqrt(np.mean((actual-r["output"][first-1])**2))),
                                "held_train_used": False})
                        if any(e["persistence_rmse"] <= 1e-10 for e in evidence):
                            raise IdentifiabilityError("FIT_UNDEFINED", "持值对照误差为零")
                        risk = float(np.mean([e["rmse"]/e["persistence_rmse"] for e in evidence]))
                        record["candidates"].append({"group": group, "route": route, "status": "succeeded", "risk": risk, "validation": evidence})
                        print(name, group, route, risk, flush=True)
                    except IdentifiabilityError as error:
                        record["candidates"].append({"group": group, "route": route, "status": "failed", "error_code": error.code})
                arm = "pooled" if group == "controls" else "pooled_pressure"
                good = [c for c in global_sources[name]["arms"][arm]["candidates"] if c["status"] == "succeeded"]
                def loo_risk(c):
                    held = [e for e in c["validation"] if e["kind"] == "leave_one_run_out"]
                    return float(np.mean([e["rmse"]/e["persistence_rmse"] for e in held]))
                winner = min(good, key=loo_risk)
                record["global"][group] = {"model": winner, "risk": loo_risk(winner)}
            good = [c for c in record["candidates"] if c["status"] == "succeeded"]
            record["selected_local"] = min(good, key=lambda c: c["risk"]) if good else None
            record["selected_global"] = min(record["global"], key=lambda g: record["global"][g]["risk"])
            local = record["selected_local"]
            global_risk = record["global"][record["selected_global"]]["risk"]
            record["selected_family"] = "local" if local and local["risk"] < global_risk else "global"
            result["results"].append(record)
    write(out/"development.json", result)
    write(out/"freeze-seal.json", {"sealed_at": datetime.now(UTC).isoformat(), "protocol_sha256": sha(out/"protocol.json"),
        "development_sha256": sha(out/"development.json"), "target_role": "already_observed_development_regression"})


def evaluate(out):
    p = check(out)
    if (out/"test-results.json").exists():
        raise RuntimeError("Regression scores exist")
    seal = json.loads((out/"freeze-seal.json").read_text())
    assert sha(out/"development.json") == seal["development_sha256"]
    dev = json.loads((out/"development.json").read_text())
    results = []
    with zipfile.ZipFile(p["archive"]) as z, patch("algorithms.identifiability.experiments.estimate_parameters",
            side_effect=AssertionError("Forecast refit forbidden")):
        for r in dev["results"]:
            case = p["cases"][r["case"]]
            u, y, audit = read_run(z, member(case, case["target"]), GROUPS["pressure"])
            item = {"case": r["case"], "role": p["target_role"], "time_audit": audit,
                "selected_family": r["selected_family"], "local": {}, "global": {}}
            item["persistence_rmse"] = float(np.sqrt(np.mean((y[FORECAST_START:]-y[FORECAST_START-1])**2)))
            for c in r["candidates"]:
                if c["status"] != "succeeded":
                    continue
                models = r["banks"][c["group"]]
                kwargs = dict(inputs=u, start=FORECAST_START, stop=len(y), policy=c["route"], input_scale=scales(models, GROUPS[c["group"]]))
                actual, pred, decision = simulate_local_bank([restore(m) for m in models], output=y, **kwargs)
                hidden = y.copy()
                hidden[FORECAST_START:] = np.nan
                _, replay, same = simulate_local_bank([restore(m) for m in models], output=hidden, **kwargs)
                np.testing.assert_array_equal(pred, replay)
                assert same == decision
                support = {m["name"]: assess_input_support(m["input_support"], u, start=FORECAST_START, stop=len(y))
                    for m, w in zip(models, decision["weights"], strict=True) if w > 0}
                item["local"][c["group"]+":"+c["route"]] = {**metrics(actual, pred), "routing": decision,
                    "future_output_invariance": True, "active_input_support": support, "validation_risk": c["risk"]}
            for group, global_model in r["global"].items():
                w = global_model["model"]
                st = ArxStructure.create(na=w["na"], nb=w["nb"], nk=1, input_columns=w["columns"])
                item["global"][group] = score(np.array(w["theta"]), w["intercept"], st, u, y, FORECAST_START, len(y), w["policy"])
            local = r["selected_local"]
            item["selected_local"] = local["group"]+":"+local["route"] if local else None
            item["selected_global"] = r["selected_global"]
            item["selected_result"] = item["local"][item["selected_local"]] if r["selected_family"] == "local" else item["global"][r["selected_global"]]
            results.append(item)
            print(r["case"], "selected", r["selected_family"], item["selected_result"]["rmse"], "persistence", item["persistence_rmse"], flush=True)
    write(out/"test-results.json", {"seal_sha256": sha(out/"freeze-seal.json"), "results": results})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=["prepare", "develop", "evaluate"], required=True)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    {"prepare": lambda: prepare(args.archive, args.source, args.out), "develop": lambda: develop(args.out),
        "evaluate": lambda: evaluate(args.out)}[args.stage]()
