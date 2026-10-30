"""Exercise real CSV upload, model persistence, immutable evaluation and export.

Uses an isolated temporary database and artifact directory. Delay suggestions come
from the recorded offline benchmark, never from simulation ground truth. This is
an integration test; it does not approve a production dataset's engineering delays.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings
from app.core.db import get_session
from app.main import create_app
from app.models import Base
from app.services import modeling_service
from app.services.version_data import load_version_series
from benchmark_real_process import DATASETS
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--family", choices=["ARX", "FIR"], default="ARX")
    parser.add_argument("--initialization-policy", choices=["fixed", "past_residual"], default="fixed")
    args = parser.parse_args()
    benchmark = json.loads(args.benchmark.read_text())
    results = []
    with TemporaryDirectory(prefix="indusopt-real-api-") as temporary:
        root = Path(temporary)
        engine = create_async_engine(f"sqlite+aiosqlite:///{root / 'smoke.db'}")
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async def prepare():
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)

        async def override_session():
            async with factory() as session:
                yield session

        asyncio.run(prepare())
        app = create_app()
        app.dependency_overrides[get_session] = override_session
        with patch("app.api.routes.get_settings", return_value=Settings(artifact_root=root)), TestClient(app) as client:
            def post(route, **kwargs):
                response = client.post("/api/v1" + route, **kwargs)
                if response.status_code >= 300:
                    raise RuntimeError(f"{route}: {response.status_code}: {response.text}")
                return response.json()["data"]

            for name, (columns, outputs, _) in DATASETS.items():
                output = outputs[0]
                source = args.data_dir / f"{name}.csv"
                delays = next(d["delays"] for d in benchmark["delay_runs"] if d["dataset"] == name and d["output"] == output and d["train_ratio"] == .6)
                uploaded = post("/datasets/upload", files={"file": (source.name, source.read_bytes(), "text/csv")}, data={"name": name})
                dataset_id = uploaded["dataset"]["id"]
                configured = post(f"/datasets/{dataset_id}/config", json={"time_column": "timestamp", "input_columns": columns, "output_column": output})
                version = configured["dataset"]["latest_version_id"]
                profile = client.get(f"/api/v1/datasets/{dataset_id}/profile", params={"version_id": version})
                assert profile.status_code == 200
                aligned = post("/preprocessing/delay/apply", json={"version_id": version, "lag_map": delays, "user_confirmed": True, "recommendation_source": "manual"})
                version = aligned["result_version_id"]
                selected = post("/preprocessing/segment", json={"version_id": version, "input_columns": columns, "output_column": output, "window_size": 20, "max_rows": 180, "history_guard": 32, "min_snr_db": -10})
                indices = selected["selected_indices"]
                assert 0 < len(indices) == selected["selection"]["selected_rows"] <= 180
                fitted = post("/modeling/arx/fit", json={"version_id": version, "input_columns": columns, "output_column": output, "initialization_policy": args.initialization_policy, "model_type": args.family, "regularization_kernel": "tc" if args.family == "FIR" else "identity", "na": 0 if args.family == "FIR" else 2, "nb": [16 if args.family == "FIR" else 2] * len(columns), "delays": [0] * len(columns), "estimator": "ridge" if args.family == "FIR" else "huber", "ridge_alpha": .1, "history_guard": 32, "training_sample_indices": indices, "sample_weights": selected["sample_weights"]})
                model_id = UUID(fitted["model_id"])
                saved = modeling_service.load_saved_arx_model(model_id=model_id, artifact_root=root)
                assert saved.intercept == fitted["intercept"]
                assert saved.payload.resolved_estimator() == ("ridge" if args.family == "FIR" else "huber")
                assert saved.payload.model_type == args.family
                assert fitted["model_structure"]["model_type"] == args.family
                artifact_path = root / fitted["artifact_uri"]
                before_hash = hashlib.sha256(artifact_path.read_bytes()).hexdigest()

                async def evaluate(version=version, model_id=model_id):
                    async with factory() as session:
                        source_series = await load_version_series(session, version_id=UUID(version), artifact_root=root)
                        # Saved-model evaluation must not estimate parameters again.
                        with patch.object(modeling_service, "estimate_parameters", side_effect=AssertionError("evaluation refitted parameters")):
                            result = await modeling_service.evaluate_saved_arx_model(session, model_id=model_id, artifact_root=root, expected_source_version_id=UUID(version))
                        return source_series, result

                series, evaluation = asyncio.run(evaluate())
                times = np.asarray(evaluation.series.sample_indices)
                expected = np.full(times.size, saved.intercept)
                for coefficient, feature in zip(saved.theta, saved.structure.feature_names(), strict=True):
                    if feature.startswith("a"):
                        expected -= coefficient * series.values[output][times - int(feature[1:])]
                    else:
                        column, lag = feature[2:].rsplit("_", 1)
                        expected += coefficient * series.values[column][times - int(lag)]
                if args.initialization_policy == "past_residual":
                    raw = np.full(series.n_samples, saved.intercept)
                    for column, coefficients in fitted["b_coefficients"].items():
                        for lag, coefficient in enumerate(coefficients):
                            positions = np.arange(saved.structure.max_history, series.n_samples)
                            raw[positions] += coefficient * series.values[column][positions - lag]
                    residual = series.values[output] - raw
                    for j, t in enumerate(times):
                        expected[j] += np.median(residual[t - 32:t])
                    start = int(series.n_samples * .8) + 32
                    expected_simulated = raw[times] + np.median(residual[start - 32:start])
                    np.testing.assert_allclose(expected_simulated, evaluation.series.free_run_prediction, atol=1e-10)
                np.testing.assert_allclose(expected, evaluation.series.one_step_prediction, atol=1e-10)
                assert before_hash == hashlib.sha256(artifact_path.read_bytes()).hexdigest()
                exported = post("/delivery/export", json={"version_id": version, "input_columns": columns, "output_column": output, "sample_indices": indices})
                with (root / exported["csv_uri"]).open() as file:
                    rows = list(csv.DictReader(file))
                assert len(rows) == exported["exported_rows"] == len(indices)
                for row, index in zip(rows, indices, strict=True):
                    for column in [*columns, output]:
                        assert np.isclose(float(row[column]), series.values[column][index], rtol=1e-10, atol=1e-10)
                results.append({"dataset": name, "output": output, "model_type": args.family, "initialization_policy": args.initialization_policy, "status": "succeeded", "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "estimated_delays": delays, "model_id": str(model_id), "source_version_id": version, "training_rows": fitted["training_rows"], "intercept": saved.intercept, "validation_fit": fitted["metrics"]["val_free_run_fit"], "test_fit": evaluation.test.free_run.fit, "exported_rows": len(rows), "model_artifact_unchanged": True, "fixed_coefficient_replay_verified": True})
                print(name, "succeeded", flush=True)
        asyncio.run(engine.dispose())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"mode": "isolated_api_integration", "results": results}, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
