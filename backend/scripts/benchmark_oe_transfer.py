"""Predeclare unseen real operating runs; replay sealed source models without refit."""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from algorithms.identifiability.regressor import ArxStructure, IdentifiabilityError
from algorithms.identifiability.validation import free_run_simulate
from benchmark_initial_and_oe import ARMS, GUARD, ROOT, score, sha, write

TARGETS = [
    ("distillation_a", "ScenarioA_SingleComponent_Water", "003", "test_anormal_experiment_001.csv", "anomalous_stress"),
    ("distillation_b", "ScenarioB_BinaryComponent_n-butanolwater", "003", "test_anormal_experiment_001.csv", "anomalous_stress"),
    ("distillation_c", "ScenarioC_ReactiveOME", "007", "test_anormal_experiment_001.csv", "anomalous_stress"),
    ("distillation_b", "ScenarioB_BinaryComponent_n-butanolwater", "001", "train_normal_experiment_001.csv", "short_normal_boundary"),
    ("distillation_c", "ScenarioC_ReactiveOME", "001", "train_normal_experiment_001.csv", "short_normal_boundary"),
]


def prepare(source, archive, out):
    if (out / "transfer-protocol.json").exists():
        raise RuntimeError("Transfer protocol already exists")
    seal = json.loads((source / "freeze-seal.json").read_text())
    assert sha(source / "development.json") == seal["development_sha256"]
    entries = []
    with zipfile.ZipFile(archive) as z:
        for name, scenario, op, filename, role in TARGETS:
            member = f"ContinuousDistillationData/{scenario}/operating_point_{op}/{filename}"
            raw = z.read(member)
            reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
            # Metadata only: target signal values and scores are not inspected here.
            rows = sum(1 for _ in reader)
            entries.append({"source_dataset": name, "member": member, "rows": rows,
                            "role": role, "previously_performance_scored": False})
    protocol = {"created_at": datetime.now(UTC).isoformat(), "source": str(source.resolve()),
        "source_seal_sha256": sha(source / "freeze-seal.json"),
        "source_development_sha256": sha(source / "development.json"),
        "archive": str(archive.resolve()), "archive_sha256": sha(archive), "targets": entries,
        "script_sha256": sha(Path(__file__)),
        "source_code_sha256": json.loads((source / "protocol.json").read_text())["code_sha256"],
        "transfer_start": GUARD, "nominal_sample_period_seconds": 30,
        "model_choice": "source Validation choice current102 versus OE24 remains frozen; all four arms shown diagnostically",
        "target_fitting": False, "target_model_selection": False, "forecast_output_updates": False,
        "warm_start": "measured target history strictly before sample 43; known physical input trajectory",
        "input_roles": "unchanged source physical columns; labels, alarms and states excluded",
        "scope": "new runs/operating conditions on the same pilot apparatus; not new factories; stress and short normal results reported separately"}
    write(out / "transfer-protocol.json", protocol)
    print(json.dumps(entries, ensure_ascii=False), flush=True)


def time_audit(rows):
    seconds = []
    day = 0
    previous = None
    for row in rows:
        if "/" in row["Time"]:
            parsed = datetime.strptime(row["Time"], "%d/%m/%Y %H:%M:%S")
            seconds.append(parsed.toordinal()*86400 + parsed.hour*3600 + parsed.minute*60 + parsed.second)
            continue
        parsed = datetime.strptime(row["Time"], "%H:%M:%S")
        clock = parsed.hour*3600 + parsed.minute*60 + parsed.second
        if previous is not None and clock < previous:
            if previous - clock > 12*3600:
                day += 86400
            else:
                return {"status": "nonmonotonic_time", "nominal_seconds": 30}
        seconds.append(clock+day)
        previous = clock
    differences = np.diff(seconds)
    return {"status": "monotonic" if np.all(differences > 0) else "duplicate_time",
            "nominal_seconds": 30, "median_interval_seconds": float(np.median(differences)),
            "min_interval_seconds": float(np.min(differences)), "max_interval_seconds": float(np.max(differences)),
            "non_30_second_intervals": int(np.count_nonzero(differences != 30))}


def evaluate(out):
    if (out / "transfer-results.json").exists():
        raise RuntimeError("Refusing to overwrite transfer results")
    protocol = json.loads((out / "transfer-protocol.json").read_text())
    source, archive = Path(protocol["source"]), Path(protocol["archive"])
    expected_script = protocol["script_sha256"]
    repair_path = out / "transfer-parser-repair.json"
    if repair_path.exists():
        repair = json.loads(repair_path.read_text())
        assert repair["before_script_sha256"] == expected_script
        expected_script = repair["after_script_sha256"]
    assert sha(Path(__file__)) == expected_script
    assert sha(source / "freeze-seal.json") == protocol["source_seal_sha256"]
    assert sha(source / "development.json") == protocol["source_development_sha256"]
    assert sha(archive) == protocol["archive_sha256"]
    assert all(sha(ROOT / p) == h for p, h in protocol["source_code_sha256"].items())
    sources = {r["dataset"]: r for r in json.loads((source / "development.json").read_text())["results"]}
    document = {"protocol_sha256": sha(out / "transfer-protocol.json"), "results": []}
    with zipfile.ZipFile(archive) as z:
        for target in protocol["targets"]:
            raw = z.read(target["member"])
            rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
            assert len(rows) == target["rows"]
            src = sources[target["source_dataset"]]
            inputs = {c: np.array([float(row[c]) for row in rows]) for c in src["inputs"]}
            y = np.array([float(row[src["output"]]) for row in rows])
            audit = time_audit(rows)
            record = {**target, "time_audit": audit, "arms": {},
                      "validation_chosen_family": src["validation_chosen_family"]}
            if audit["status"] != "monotonic":
                record["status"] = "invalid_time_order"
                document["results"].append(record)
                continue
            for arm in ARMS:
                frozen = src["arms"][arm]["winner"]
                if frozen is None:
                    record["arms"][arm] = {"status": "no_source_model"}
                    continue
                cfg = frozen["configuration"]
                structure = ArxStructure.create(na=cfg["na"], nb=cfg["nb"], nk=src["delays"], input_columns=src["inputs"])
                theta = np.array(frozen["theta"])
                policy = cfg.get("initialization_policy", "fixed")
                try:
                    metrics = score(theta, frozen["intercept"], structure, inputs, y, GUARD, len(y), policy)
                    args = dict(inputs=inputs, start=GUARD, stop=len(y), intercept=frozen["intercept"], initialization_policy=policy)
                    prediction = free_run_simulate(theta, structure, output=y, **args)[1]
                    hidden = y.copy()
                    hidden[GUARD:] = np.nan
                    np.testing.assert_array_equal(prediction, free_run_simulate(theta, structure, output=hidden, **args)[1])
                    record["arms"][arm] = {"status": "succeeded", **metrics, "future_output_invariance": True}
                except IdentifiabilityError as error:
                    record["arms"][arm] = {"status": "failed", "error_code": error.code}
            record["selected_result"] = record["arms"][src["validation_chosen_family"]]
            record["persistence_rmse"] = float(np.sqrt(np.mean((y[GUARD:] - y[GUARD-1])**2)))
            document["results"].append(record)
            print(target["source_dataset"], target["role"], {a: r.get("rmse") for a, r in record["arms"].items()}, flush=True)
    write(out / "transfer-results.json", document)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=["prepare", "evaluate"], required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.stage == "prepare":
        prepare(args.source, args.archive, args.out)
    else:
        evaluate(args.out)
