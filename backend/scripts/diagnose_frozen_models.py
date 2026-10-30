"""Posthoc cause analysis of already inspected source models, without refitting."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from algorithms.identifiability.regressor import ArxStructure, IdentifiabilityError, build_regressor
from algorithms.identifiability.validation import free_run_simulate, is_stable, steady_state_gains
from benchmark_real_process import load_series


def diagnose(source, out):
    development = json.loads((source / "development.json").read_text())
    records = []
    for row in development["results"]:
        series = load_series(Path(row["path"]), row["inputs"], row["output"], None)
        y = series.values[row["output"]]
        u = {c: series.values[c] for c in row["inputs"]}
        te, ve = row["train_end"], row["validation_end"]
        train = slice(43, te-43)
        record = {"dataset": row["dataset"], "splits": {}, "arms": {}}
        for label, region in [("train", train), ("validation", slice(te+43, ve)), ("test", slice(ve+43, len(y)))]:
            record["splits"][label] = {"y_mean": float(y[region].mean()), "y_std": float(y[region].std()),
                "inputs": {c: {"mean": float(v[region].mean()), "std": float(v[region].std()),
                    "outside_train_range_fraction": float(np.mean((v[region]<v[train].min()) | (v[region]>v[train].max())))} for c, v in u.items()}}
        for arm, evidence in row["arms"].items():
            frozen = evidence["winner"]
            cfg = frozen["configuration"]
            st = ArxStructure.create(na=cfg["na"], nb=cfg["nb"], nk=row["delays"], input_columns=row["inputs"])
            theta = np.array(frozen["theta"])
            reg = build_regressor(inputs=u, output=y, structure=st, start=43, stop=te-43)
            normalized = (reg.features-reg.features.mean(0)) / np.maximum(reg.features.std(0), 1e-12)
            model = {"configuration": cfg, "A1": float(1+theta[:st.na].sum()),
                "stable": is_stable(theta[:st.na])[0], "max_pole": is_stable(theta[:st.na])[1],
                "gains": steady_state_gains(theta, st), "intercept": frozen["intercept"],
                "standardized_design_condition": float(np.linalg.cond(normalized)), "scores": {}}
            for label, start, stop in [("validation", te+43, ve), ("test", ve+43, len(y))]:
                args = dict(inputs=u, output=y, start=start, stop=stop, intercept=frozen["intercept"])
                actual, pred = free_run_simulate(theta, st, **args, initialization_policy=cfg.get("initialization_policy", "fixed"))
                residual = actual-pred
                bias = float(residual.mean())
                score = {"rmse": float(np.sqrt(np.mean(residual**2))), "bias": bias,
                    "bias_squared_fraction": float(bias**2/np.mean(residual**2)),
                    "prediction_mean": float(pred.mean()), "centered_rmse": float(np.std(residual)),
                    "persistence_rmse": float(np.sqrt(np.mean((actual-y[start-1])**2)))}
                one_step = build_regressor(inputs=u, output=y, structure=st, start=start, stop=stop)
                score["fixed_one_step_rmse"] = float(np.sqrt(np.mean((one_step.targets-one_step.features@theta-frozen["intercept"])**2)))
                for policy in ("fixed", "past_residual"):
                    try:
                        predicted = free_run_simulate(theta, st, **args, initialization_policy=policy)[1]
                        score[policy+"_rmse"] = float(np.sqrt(np.mean((actual-predicted)**2)))
                    except IdentifiabilityError as error:
                        score[policy+"_error"] = error.code
                model["scores"][label] = score
            record["arms"][arm] = model
        records.append(record)
        print(row["dataset"], "y mean/std", [(k, round(v["y_mean"], 3), round(v["y_std"], 3)) for k, v in record["splits"].items()])
        for arm, model in record["arms"].items():
            s = model["scores"]["test"]
            print(arm, "A1", round(model["A1"], 6), "pole", round(model["max_pole"], 6),
                  "bias² share", round(s["bias_squared_fraction"], 3), "fixed/past",
                  round(s["fixed_rmse"], 3), s.get("past_residual_rmse", s.get("past_residual_error")))
    out.write_text(json.dumps({"evidence_role": "posthoc_seen_data_diagnosis_not_confirmation", "records": records}, ensure_ascii=False, indent=2)+"\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    diagnose(args.source, args.out)
