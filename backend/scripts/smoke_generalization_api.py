"""Replay frozen public-data studies through upload, optimization, report and delivery.

The same seed and search budget must reproduce the offline frozen model exactly.
Artifacts live in the public-data directory, separate from the user's live app.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import io
import json
import sys
from pathlib import Path
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
from benchmark_generalization import clean
from fastapi.testclient import TestClient
from prepare_generalization_data import sha, write_json
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    development = json.loads((args.out / "development.json").read_text())
    tests = json.loads((args.out / "test-results.json").read_text())
    assert sha(args.out / "development.json") == tests["freeze_seal"]["development_sha256"]
    root = Path(manifest["data_dir"]) / "api-artifacts"
    root.mkdir(exist_ok=True)
    # Run-specific SQLite avoids collisions and leaves reviewable artifacts behind.
    from uuid import uuid4
    database = root / f"integration-{uuid4()}.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database}")
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
    results = []
    with patch("app.api.routes.get_settings", return_value=Settings(artifact_root=root)), TestClient(app) as client:
        def post(route, **kwargs):
            response = client.post("/api/v1" + route, **kwargs)
            if response.status_code >= 300:
                raise RuntimeError(f"{route}: {response.status_code}: {response.text}")
            return response.json()["data"]

        for index, (entry, row, test_row) in enumerate(zip(manifest["datasets"], development["results"], tests["results"], strict=True)):
            if index:
                asyncio.run(engine.dispose())
                database = root / f"integration-{uuid4()}.db"
                engine = create_async_engine(f"sqlite+aiosqlite:///{database}")
                factory = async_sessionmaker(engine, expire_on_commit=False)
                asyncio.run(prepare())
            seed = row["chosen_seed_by_validation"]
            if seed is None:
                results.append({"dataset": entry["dataset"], "status": "skipped_no_optimizer_winner"})
                continue
            model = next(s["model"] for s in row["seeds"] if s["seed"] == seed)
            expected_test = next(s["test"] for s in test_row["seeds"] if s["seed"] == seed)
            source = Path(entry["path"])
            # The application's CSV contract accepts one timestamp column. Original
            # time strings remain in the frozen source; this adapter removes only that
            # auxiliary column and leaves every numeric value and row in place.
            with source.open() as handle:
                reader = csv.DictReader(handle)
                records = list(reader)
                fields = [c for c in reader.fieldnames if c != "source_time"]
            buffer = io.StringIO(newline="")
            writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(records)
            upload_bytes = buffer.getvalue().encode()
            uploaded = post("/datasets/upload", files={"file": (source.name, upload_bytes, "text/csv")}, data={"name": entry["dataset"]})
            dataset_id = uploaded["dataset"]["id"]
            configured = post(f"/datasets/{dataset_id}/config", json={"time_column": "timestamp", "input_columns": entry["inputs"], "output_column": entry["output"]})
            version = configured["dataset"]["latest_version_id"]
            profile = client.get(f"/api/v1/datasets/{dataset_id}/profile", params={"version_id": version})
            assert profile.status_code == 200
            # The frozen data is already regular and finite; cleaning is a verified NoOp.
            cleaned = post("/preprocessing/clean", json={"version_id": version,
                "interpolation": "none", "anomaly_strategy": "keep", "smoothing": "none"})
            assert cleaned["no_op"], "Cleaning changed the frozen source"
            request = {**model["request"], "version_id": version, "evaluate_test": False}
            study_response = client.post("/api/v1/optimization/optuna/start", json={
                "version_id": version, "input_columns": entry["inputs"], "output_column": entry["output"],
                "random_seed": seed, "history_guard": 43, "max_trials": 10})
            if study_response.status_code >= 300:
                results.append({"dataset": entry["dataset"], "status": "failed",
                    "phase": "optimization_api", "response": study_response.json(), "database": str(database)})
                write_json(args.out / "api-integration.json", {"artifact_root": str(root), "results": results})
                print(entry["dataset"], "optimization API failed", flush=True)
                continue
            study_id = study_response.json()["data"]["study_id"]
            study_status = client.get(f"/api/v1/optimization/optuna/{study_id}/status").json()["data"]
            model_id = study_status.get("optimized_model_id")
            assert model_id, study_status
            artifact = root / "models" / f"{model_id}.json"
            before = sha(artifact)
            saved = modeling_service.load_saved_arx_model(model_id=UUID(model_id), artifact_root=root)
            assert saved.payload.training_sample_indices == request["training_sample_indices"]
            assert saved.payload.sample_weights == {int(k): v for k, v in request["sample_weights"].items()}
            np.testing.assert_allclose(saved.theta, model["theta"], rtol=1e-10, atol=1e-10)
            np.testing.assert_allclose(saved.intercept, model["intercept"], rtol=1e-10, atol=1e-10)

            async def evaluate(version=version, saved=saved, factory=factory):
                async with factory() as session:
                    series = await load_version_series(session, version_id=UUID(version), artifact_root=root)
                    with patch.object(modeling_service, "estimate_parameters", side_effect=AssertionError("API Test refitted coefficients")):
                        result = await modeling_service.evaluate_saved_arx_model(session, model_id=saved.model_id,
                            artifact_root=root, expected_source_version_id=UUID(version))
                    return series, result

            series, evaluation = asyncio.run(evaluate())
            assert sha(artifact) == before
            if expected_test["state"] == "succeeded":
                np.testing.assert_allclose(evaluation.test.free_run.rmse,
                    expected_test["free_run"]["rmse"], rtol=1e-10, atol=1e-10)
            # Strict API Study provenance must recover the frozen optimizer's rows.
            indices = request["training_sample_indices"]
            assert indices
            exported = post("/delivery/export", json={"dataset_id": dataset_id, "version_id": version, "input_columns": entry["inputs"],
                "output_column": entry["output"], "mode": "optimization_best", "study_id": study_id})
            export_path = root / exported["csv_uri"]
            with export_path.open() as handle:
                exported_rows = list(csv.DictReader(handle))
            assert len(exported_rows) == len(indices) == exported["exported_rows"]
            for record, index in zip(exported_rows, indices, strict=True):
                for column in [*entry["inputs"], entry["output"]]:
                    assert np.isclose(float(record[column]), series.values[column][index], rtol=1e-10, atol=1e-10)
            report = post("/reports/generate", json={"dataset_id": dataset_id, "version_id": version, "study_id": study_id,
                "title": f"{entry['dataset']} 公开流程数据固定模型验证报告"})
            assert report["fully_resolved"] and report["bindings"] and "{{" not in report["markdown"]
            result = {"dataset": entry["dataset"], "status": "succeeded", "seed": seed,
                "study_id": study_id, "database": str(database), "api_trials": 10,
                "source_sha256": entry["sha256"], "model_matches_offline_frozen_parameters": True,
                "upload_sha256": hashlib.sha256(upload_bytes).hexdigest(),
                "upload_adapter": "remove auxiliary source_time only; original source preserved",
                "evaluation_did_not_refit": True, "model_artifact_unchanged": True,
                "test_rmse": evaluation.test.free_run.rmse, "test_fit": evaluation.test.free_run.fit,
                "cleaning_no_op": True, "exported_rows": len(indices),
                "export_path": str(export_path), "export_sha256": sha(export_path),
                "model_path": str(artifact), "model_sha256": before,
                "report_markdown_path": str(root / report["artifact_uri"]),
                "report_html_path": str(root / report["html_artifact_uri"]),
                "report_bindings": len(report["bindings"]), "report_charts": len(report["charts"]),
                "narration_source": report["narration_source"], "llm_provider": report["llm_provider"],
                "llm_model": report["llm_model"], "llm_fallback_reason": report["llm_fallback_reason"],
                "export_mode": "optimization_best", "warm_start_trials": study_status["statistics"]["warm_start_trials"]}
            results.append(clean(result))
            write_json(args.out / "api-integration.json", {"artifact_root": str(root),
                "results": results})
            print(entry["dataset"], "API verified", report["narration_source"], flush=True)
    asyncio.run(engine.dispose())


if __name__ == "__main__":
    main()
