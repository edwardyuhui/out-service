"""Prepare public process measurements using the predeclared generalization protocol.

Raw downloads stay outside Git. No label is used, no row is shuffled, and no
operating runs are concatenated. Numeric values do not choose the source files.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def prepare(base: Path, output: Path) -> None:
    protocol = json.loads((output / "protocol.json").read_text())
    prepared = base / "prepared"
    prepared.mkdir(exist_ok=True)
    entries = []

    def save(name, columns, target, values, period, source, source_times, kind, notes):
        n = len(values[target])
        # Constant-channel removal sees only the earliest rolling Train prefix.
        stop = int(n * .4) - protocol["history_guard"]
        constant = [c for c in columns if np.nanstd(values[c][:stop]) <= 1e-12]
        active = [c for c in columns if c not in constant]
        path = prepared / f"{name}.csv"
        anchor = datetime(2000, 1, 1)
        with path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "source_time", *columns, target])
            for i in range(n):
                writer.writerow([(anchor + timedelta(seconds=i * period)).isoformat(),
                    source_times[i], *[values[c][i] for c in columns], values[target][i]])
        entries.append({"dataset": name, "path": str(path.resolve()), "sha256": sha(path),
            "source_file": source, "source_sha256": sha(base / source.split("::")[0]),
            "rows": n, "period_seconds": period, "inputs": active, "declared_inputs": columns,
            "constant_inputs_removed_on_earliest_train": constant, "output": target,
            "source_class": kind, "notes": notes,
            "missing_counts": {c: int(np.sum(~np.isfinite(values[c]))) for c in [*columns, target]},
            "synthetic_nominal_timestamps": True, "original_time_column": "source_time"})

    # Physical mappings are from the original paper's Table 1, not correlations.
    mapping = {"TV_8329ZC.AV_0#": "desuperheater_valve", "FT_8301.AV_0#": "primary_air_flow",
        "FT_8302.AV_0#": "secondary_air_flow", "ZZQBCHLL.AV_0#": "steam_flow",
        "TE_8332A.AV_0#": "outlet_steam_temperature"}
    with zipfile.ZipFile(base / "boiler-raw.zip") as z:
        rows = list(csv.DictReader(io.StringIO(z.read("xinan_uncompleted_data.csv").decode("utf-8-sig"))))
    times = [datetime.fromisoformat(row["date"]) for row in rows]
    assert all((b - a).total_seconds() == 5 for a, b in zip(times[:-1], times[1:], strict=True))
    assert len(rows) % 12 == 0
    values = {}
    for original, column in mapping.items():
        signal = np.asarray([float(row[original]) if row[original].strip() else np.nan for row in rows])
        # Disjoint trailing 60 s means: every block ends at its declared observation time.
        # No filtering across blocks or partition boundaries; missing readings are omitted.
        blocks = signal.reshape(-1, 12)
        count = np.sum(np.isfinite(blocks), axis=1)
        values[column] = np.divide(np.nansum(blocks, axis=1), count,
            out=np.full(len(blocks), np.nan), where=count > 0)
    save("boiler", list(mapping.values())[:-1], "outlet_steam_temperature", values, 60,
        "boiler-raw.zip::xinan_uncompleted_data.csv", [row["date"] for row in rows[11::12]],
        "factory_measurements", "Zhejiang chemical plant; raw incomplete release; all 86400 rows retained in 7200 nonoverlapping 60 s means; no anomaly class used; physical units preserved.")

    raw = np.loadtxt(io.BytesIO(gzip.decompress((base / "exchanger.dat.gz").read_bytes())))
    assert raw.shape == (4000, 3) and np.all(np.diff(raw[:, 0]) == 1)
    save("exchanger", ["liquid_flow"], "outlet_temperature",
        {"liquid_flow": raw[:, 1], "outlet_temperature": raw[:, 2]}, 1,
        "exchanger.dat.gz", [str(t) for t in raw[:, 0]], "experimental_measurements",
        "DaISy 97-002 copper-tube water/steam heat exchanger; only flow varies; a SISO boundary case, not evidence of multiple input identification.")

    with zipfile.ZipFile(base / "ContinuousDistillationData.zip") as z:
        for letter in "ABC":
            eligible = [n for n in sorted(z.namelist()) if f"Scenario{letter}_" in n and
                "train_normal" in n and n.endswith(".csv") and len(z.read(n).splitlines()) - 1 >= 900]
            if not eligible:
                raise ValueError(f"No eligible normal run for {letter}")
            name = eligible[0]
            rows = list(csv.DictReader(io.StringIO(z.read(name).decode("utf-8-sig"))))
            columns, target = ["M101", "TH101_SetPoint", "TV101", "T116"], "T114"
            values = {c: np.asarray([float(row[c]) if row[c].strip() else np.nan for row in rows])
                for c in [*columns, target]}
            save(f"distillation_{letter.lower()}", columns, target, values, 30,
                f"ContinuousDistillationData.zip::{name}", [row["Time"] for row in rows],
                "pilot_plant_measurements", "First lexicographic normal run with >=900 rows; one run only; original timestamp strings retained (A has minute truncation, C has small clock jitter); nominal 30 s index used; all labels, alarms and status columns excluded; three scenarios share one apparatus.")
    write_json(output / "data-manifest.json", {"protocol_sha256": sha(output / "protocol.json"),
        "data_dir": str(base.resolve()), "datasets": entries})
    print(json.dumps([{k: e[k] for k in ["dataset", "rows", "inputs", "missing_counts"]} for e in entries], indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.data_dir, args.out)
