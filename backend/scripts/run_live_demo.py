"""Replay the authorized real boiler workflow through a running platform HTTP API.

Writes real data and execution records to the target platform. Confirmation nodes
are acknowledged for this demo; numerical results are computed by the platform.
No API credentials are read or written by this script.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-trials", type=int, default=4)
    parser.add_argument("--base-url", default="http://127.0.0.1:18000")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    entry = next(e for e in manifest["datasets"] if e["dataset"] == "boiler")
    args.out.mkdir(parents=True, exist_ok=True)
    document = {
        "role": "previously_seen_real_boiler_integration_regression",
        "base_url": args.base_url,
        "max_trials": args.max_trials,
        "confirmation_authorization": "user authorized real-data demonstration in persistent local platform",
        "events": [],
    }

    def save():
        (args.out / "agent-integration.json").write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        )

    with httpx.Client(base_url=args.base_url, timeout=600) as client:

        def post(route, **kwargs):
            response = client.post("/api/v1" + route, **kwargs)
            if response.status_code >= 300:
                document["error"] = {
                    "route": route,
                    "status": response.status_code,
                    "response": response.json(),
                }
                save()
                raise RuntimeError(f"{route}: HTTP {response.status_code}")
            return response.json()["data"]

        raw = Path(entry["path"]).read_bytes()
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        records = list(reader)
        fields = [c for c in reader.fieldnames if c != "source_time"]
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
        upload = buffer.getvalue().encode()
        document.update(
            source_sha256=hashlib.sha256(raw).hexdigest(),
            upload_sha256=hashlib.sha256(upload).hexdigest(),
            upload_adapter="remove auxiliary source_time only; every numeric value and row preserved",
        )
        uploaded = post(
            "/datasets/upload",
            files={"file": ("boiler.csv", upload, "text/csv")},
            data={"name": "真实锅炉 · 答辩完整演示"},
        )
        dataset_id = uploaded["dataset"]["id"]
        configured = post(
            f"/datasets/{dataset_id}/config",
            json={
                "time_column": "timestamp",
                "input_columns": entry["inputs"],
                "output_column": entry["output"],
            },
        )
        chat = post(
            "/copilot/chat",
            json={
                "dataset_id": dataset_id,
                "active_version_id": configured["dataset"]["latest_version_id"],
                "message": f"先诊断数据和检测异常，执行清洗（interpolation=none、anomaly_strategy=keep、smoothing=none）。提取动态片段，估计时滞并补偿，分析共线性并保留全部输入。ARX辨识后使用全折验收闭环寻优，执行{args.max_trials}次迭代：max_trials={args.max_trials}，random_seed=31，optimization_policy=validation_guarded。最后对冻结模型进行Test评价，生成图文报告并导出最优建模数据集。",
            },
        )
        document.update(
            plan_source=chat["plan_source"],
            llm_provider=chat["llm_provider"],
            llm_model=chat["llm_model"],
            llm_fallback_reason=chat["llm_fallback_reason"],
            plan=chat["plan"],
            execution_id=chat["execution_id"],
        )
        save()
        assert chat["plan_source"] == "llm", "Cloud plan fell back; preserve explicit evidence"
        execution_id = chat["execution_id"]
        for _ in range(20):
            response = client.get(f"/api/v1/copilot/executions/{execution_id}")
            assert response.status_code == 200
            snapshot = response.json()["data"]
            document["snapshot"] = snapshot
            save()
            if snapshot["workflow_status"] in {"SUCCEEDED", "COMPLETED"}:
                document["status"] = "succeeded"
                save()
                break
            if snapshot["workflow_status"] in {"FAILED", "REJECTED", "CANCELLED"}:
                raise RuntimeError(f"Agent workflow ended: {snapshot['workflow_status']}")
            pending = snapshot["pending_confirmation_step_id"]
            if pending:
                step = next(s for s in snapshot["step_runs"] if s["step_id"] == pending)
                payload = {
                    "copilot_run_id": chat["copilot_run_id"],
                    "execution_id": execution_id,
                    "step_id": pending,
                    "confirmation_id": pending,
                    "approved": True,
                    "warning_acknowledged": True,
                    "comment": "授权真实数据集成回归；采用已计算建议，写入本地演示平台 PostgreSQL，保留真实运行记录。",
                }
                if step["tool"] == "select_variables":
                    payload["feature_drop_columns"] = []
                event = post("/copilot/confirm", json=payload)
                document["events"].append(
                    {"tool": step["tool"], "step_id": pending, "result": event}
                )
                print("confirmed", step["tool"], event["step_status"], flush=True)
            else:
                current = next(
                    (
                        s
                        for s in snapshot["step_runs"]
                        if s["step_id"] == snapshot["current_step_id"]
                    ),
                    None,
                )
                tool = current["tool"] if current else ""
                route = {
                    "optimize_pipeline": "/copilot/optimize-pipeline/execute",
                    "evaluate_model": "/copilot/evaluate-model/execute",
                }.get(tool)
                if route is None:
                    raise RuntimeError(
                        f"No executable controller for {tool}: {snapshot['workflow_status']}"
                    )
                event = post(route, json={"execution_id": execution_id})
                document["events"].append({"tool": tool, "result": event})
                print("executed", tool, event["step_status"], flush=True)
            save()
        else:
            raise RuntimeError("Agent exceeded the declared integration step budget")
        assert document.get("status") == "succeeded"
        assert all(s["status"] == "SUCCEEDED" for s in document["snapshot"]["step_runs"])


if __name__ == "__main__":
    main()
