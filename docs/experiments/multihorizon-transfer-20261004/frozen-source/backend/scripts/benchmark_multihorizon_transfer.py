"""Known distillation transfer regression; independent runs, no target fitting."""
from __future__ import annotations

import argparse
import json
import sys
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from algorithms.identifiability.experiments import TrainingExperiment, fit_arx_experiments
from algorithms.identifiability.multihorizon import fit_multihorizon
from algorithms.identifiability.regressor import ArxStructure, IdentifiabilityError
from algorithms.identifiability.validation import free_run_simulate, is_stable
from benchmark_initial_and_oe import ROOT, score, sha, write
from benchmark_operating_points import CASES, CONTROLS, member, read_run


def prepare(archive, out):
    out.mkdir(parents=True, exist_ok=True)
    if (out/"protocol.json").exists():
        raise RuntimeError("Preserve existing evidence")
    files = [Path(__file__), ROOT/"backend/scripts/benchmark_operating_points.py",
        ROOT/"backend/scripts/benchmark_initial_and_oe.py", ROOT/"backend/scripts/benchmark_validation_guarded.py",
        ROOT/"backend/scripts/benchmark_oe_transfer.py", *[(ROOT/"backend/algorithms/identifiability"/f)
        for f in ("multihorizon.py", "output_error.py", "experiments.py", "estimation.py", "regressor.py", "validation.py", "support.py")]]
    cases = {name: {**case, "target_role": "previously_scored_development_regression"} for name, case in CASES.items()}
    write(out/"protocol.json", {"registered_at": datetime.now(UTC).isoformat(), "archive": str(archive.absolute()),
        "archive_sha256": sha(archive), "cases": cases, "grid": {"na": [1, 2], "nb": [1, 2], "alpha": [0., .001]},
        "arms": {"pooled_controls": ["pooled", CONTROLS], "multihorizon_controls": ["multihorizon", CONTROLS],
                 "pooled_pressure": ["pooled", [*CONTROLS, "PIC101"]], "multihorizon_pressure": ["multihorizon", [*CONTROLS, "PIC101"]]},
        "train": "[10,floor(N*.6)-10)", "validation": "[floor(N*.6)+10,floor(N*.8)-10)",
        "source_test": "all tails >=floor(N*.8) removed before fitting", "delay": 1,
        "selection": "mean leave-one-source-run-out Validation RMSE/persistence; held run excluded from fit and scaling",
        "forecast_start": 43, "initialization": "fixed measured pre-origin history; no target offsets or future output updates",
        "multihorizon": [1, 16, 64, 0], "max_nfev_per_start": 150,
        "comparison": "8 structures per arm, unequal solver budget and regularization conventions; newly fitted matched source grid, not comparison to prior exhaustive winners",
        "scope": "B/C same pilot apparatus, known targets; measured T116 and PIC101 conditional inputs; no causality or factory-transfer claim",
        "code_sha256": {str(f.relative_to(ROOT)): sha(f) for f in files}})


def check(out):
    p = json.loads((out/"protocol.json").read_text())
    assert sha(p["archive"]) == p["archive_sha256"]
    assert all(sha(ROOT/f) == h for f, h in p["code_sha256"].items())
    return p


def develop(out):
    p = check(out)
    if (out/"development.json").exists():
        raise RuntimeError("Models already frozen")
    document = {"results": []}
    with zipfile.ZipFile(p["archive"]) as z:
        for name, case in p["cases"].items():
            runs = []
            for op in case["runs"]:
                path = member(case, op)
                u, y, _ = read_run(z, path, [*CONTROLS, "PIC101"])
                te, ve = int(len(y)*.6), int(len(y)*.8)
                runs.append((TrainingExperiment(path, {c: v[:ve] for c, v in u.items()}, y[:ve], 10, te-10), te+10, ve-10))
            record = {"case": name, "arms": {}}
            for arm, (method, columns) in p["arms"].items():
                candidates = []
                for na in p["grid"]["na"]:
                    for nb in p["grid"]["nb"]:
                        for alpha in p["grid"]["alpha"]:
                            item = {"na": na, "nb": nb, "alpha": alpha, "columns": columns}
                            st = ArxStructure.create(na=na, nb=nb, nk=1, input_columns=columns)
                            started = time.perf_counter()
                            def fit(experiments):
                                if method == "pooled":
                                    result = fit_arx_experiments(experiments, structure=st, ridge_alpha=alpha).parameters
                                else:
                                    result = fit_multihorizon(experiments, structure=st, ridge_alpha=alpha,
                                        horizons=tuple(p["multihorizon"]), max_nfev=150)
                                if not is_stable(result.theta[:na])[0]:
                                    raise IdentifiabilityError("UNSTABLE_MODEL", "模型不稳定")
                                return result
                            try:
                                full = fit([r[0] for r in runs])
                                evidence = []
                                for index, (e, first, last) in enumerate(runs):
                                    held = fit([r[0] for i, r in enumerate(runs) if i != index])
                                    metric = score(held.theta, held.intercept, st, e.inputs, e.output, first, last)
                                    baseline = float(np.sqrt(np.mean((e.output[first:last]-e.output[first-1])**2)))
                                    evidence.append({**metric, "persistence_rmse": baseline, "run": e.name})
                                item.update(status="succeeded", theta=full.theta.tolist(), intercept=float(full.intercept),
                                    validation=evidence, validation_risk=float(np.mean([e["rmse"]/e["persistence_rmse"] for e in evidence])))
                            except IdentifiabilityError as error:
                                item.update(status="failed", error_code=error.code)
                            item["elapsed_seconds"] = time.perf_counter()-started
                            candidates.append(item)
                good = [c for c in candidates if c["status"] == "succeeded"]
                winner = min(good, key=lambda c: c["validation_risk"]) if good else None
                record["arms"][arm] = {"winner": winner, "candidates": candidates}
                print(name, arm, winner["validation_risk"] if winner else None, flush=True)
            available = [a for a in p["arms"] if record["arms"][a]["winner"]]
            record["selected_arm"] = min(available, key=lambda a: record["arms"][a]["winner"]["validation_risk"]) if available else None
            document["results"].append(record)
    write(out/"development.json", document)
    write(out/"freeze-seal.json", {"sealed_at": datetime.now(UTC).isoformat(),
        "protocol_sha256": sha(out/"protocol.json"), "development_sha256": sha(out/"development.json")})


def evaluate(out):
    p = check(out)
    if (out/"test-results.json").exists():
        raise RuntimeError("Targets already scored")
    seal = json.loads((out/"freeze-seal.json").read_text())
    assert seal["development_sha256"] == sha(out/"development.json")
    assert seal["protocol_sha256"] == sha(out/"protocol.json")
    results = []
    with zipfile.ZipFile(p["archive"]) as z:
        for r in json.loads((out/"development.json").read_text())["results"]:
            case = p["cases"][r["case"]]
            u, y, _ = read_run(z, member(case, case["target"]), [*CONTROLS, "PIC101"])
            result = {"case": r["case"], "role": case["target_role"], "selected_arm": r["selected_arm"],
                "persistence_rmse": float(np.sqrt(np.mean((y[43:]-y[42])**2))), "arms": {}}
            hidden = y.copy()
            hidden[43:] = np.nan
            for arm, item in r["arms"].items():
                w = item["winner"]
                if w is None:
                    result["arms"][arm] = {"status": "no_model"}
                    continue
                st = ArxStructure.create(na=w["na"], nb=w["nb"], nk=1, input_columns=w["columns"])
                theta = np.array(w["theta"])
                kwargs = dict(inputs=u, start=43, stop=len(y), intercept=w["intercept"])
                np.testing.assert_array_equal(free_run_simulate(theta, st, output=hidden, **kwargs)[1],
                    free_run_simulate(theta, st, output=y, **kwargs)[1])
                result["arms"][arm] = {**score(theta, w["intercept"], st, u, y, 43, len(y)),
                    "future_output_invariance": True, "refit": False}
            results.append(result)
            print(json.dumps(result), flush=True)
    write(out/"test-results.json", {"seal_sha256": sha(out/"freeze-seal.json"), "results": results})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, choices=["prepare", "develop", "evaluate"])
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    {"prepare": lambda: prepare(args.archive, args.out), "develop": lambda: develop(args.out),
        "evaluate": lambda: evaluate(args.out)}[args.stage]()
