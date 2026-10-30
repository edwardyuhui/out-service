"""Transfer frozen distillation coefficients to predeclared independent runs."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from algorithms.identifiability.regressor import IdentifiabilityError
from algorithms.identifiability.validation import fit_percentage, free_run_simulate
from app.schemas.modeling import ArxFitRequest
from app.services.modeling_service import _structure
from benchmark_generalization import clean
from prepare_generalization_data import sha, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    protocol_path = args.out / "cross-run-protocol.json"
    protocol = json.loads(protocol_path.read_text())
    manifest = json.loads((args.out / "data-manifest.json").read_text())
    development_path = args.out / "development.json"
    seal = json.loads((args.out / "freeze-seal.json").read_text())
    assert sha(development_path) == seal["development_sha256"]
    development = json.loads(development_path.read_text())
    source = next(r for r in development["results"] if r["dataset"] == protocol["source_dataset"])
    models = {k: v for k, v in source["baselines"].items() if k.endswith("full_train")}
    seed = source["chosen_seed_by_validation"]
    if seed is not None:
        models["optimizer"] = next(s["model"] for s in source["seeds"] if s["seed"] == seed)
    rows = []
    with zipfile.ZipFile(Path(manifest["data_dir"]) / "ContinuousDistillationData.zip") as z:
        for target in protocol["targets"]:
            raw = z.read(target["member"])
            records = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
            tested = {**target, "member_sha256": hashlib.sha256(raw).hexdigest(),
                "rows": len(records), "forecast_start": 43, "models": {}}
            for name, model in models.items():
                if model["state"] != "frozen":
                    tested["models"][name] = model
                    continue
                request = ArxFitRequest.model_validate(model["request"])
                inputs = {c: np.asarray([float(r[c]) for r in records]) for c in request.input_columns}
                output = np.asarray([float(r[request.output_column]) for r in records])
                persistence_rmse = float(np.sqrt(np.mean((output[43:] - output[42]) ** 2)))
                output_range = float(np.ptp(output[43:]))
                try:
                    actual, predicted = free_run_simulate(np.asarray(model["theta"]),
                        _structure(request, request.input_columns), inputs=inputs, output=output,
                        start=43, stop=len(output), intercept=model["intercept"],
                        initialization_policy=request.initialization_policy,
                        initialization_window=request.initialization_window)
                    rmse = float(np.sqrt(np.mean((actual - predicted) ** 2)))
                    tested["models"][name] = {"state": "succeeded", "rmse": rmse,
                        "fit": fit_percentage(actual, predicted) if output_range > 0 else None,
                        "fit_status": "defined" if output_range > 0 else "undefined_constant_output",
                        "output_range": output_range, "persistence_rmse": persistence_rmse,
                        "persistence_skill": 1 - rmse / persistence_rmse if persistence_rmse else None,
                        "normalized_rmse_using_source_train": rmse / model["training_output_scale"],
                        "coefficient_refit": False, "initialization_policy": request.initialization_policy}
                except IdentifiabilityError as e:
                    tested["models"][name] = {"state": "failed", "error_code": e.code, "coefficient_refit": False}
            rows.append(tested)
    assert sha(development_path) == seal["development_sha256"]
    write_json(args.out / "cross-run-results.json", clean({"protocol_sha256": sha(protocol_path),
        "source_freeze_seal": seal, "chosen_seed_by_source_validation": seed, "results": rows}))
    print(json.dumps(clean(rows), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
