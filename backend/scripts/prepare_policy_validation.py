"""Freeze regression metadata and one unseen normal operating run before scoring."""
from __future__ import annotations

import argparse
import csv
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
from prepare_generalization_data import sha, write_json


def prepare(previous: Path, output: Path):
    backend = Path(__file__).resolve().parents[1]
    previous_manifest = json.loads((previous / 'data-manifest.json').read_text())
    output.mkdir(parents=True, exist_ok=False)
    protocol = {
        'frozen_at': datetime.now(UTC).isoformat(), 'algorithm_version': '4.1.0',
        'seeds': [42, 20261003, 7, 19, 31], 'max_trials': 10, 'grid_size': 102,
        'history_guard': 43, 'train_ratio': .6, 'validation_ratio': .2,
        'model_choice': 'validation only; Test masked until every model is frozen',
        'data_policies': ['full_train', 'selected'], 'coverage_candidates': [0, 3],
        'regression_datasets': [e['dataset'] for e in previous_manifest['datasets']],
        'new_run': 'ContinuousDistillationData/ScenarioA_SingleComponent_Water/operating_point_007/train_normal_experiment_001.csv',
        'new_run_choice': 'Only previously unscored normal run with at least 900 rows; schema/file length only',
        'scope': 'Five prior datasets are regression evidence; one new run is a new operating point on the same apparatus, not a new factory.',
        'code_sha256': {str(p.relative_to(backend)): sha(p) for directory in ['algorithms', 'app/services', 'app/schemas']
            for p in sorted((backend / directory).rglob('*.py'))},
        'scripts_sha256': {p.name: sha(p) for p in [Path(__file__), backend / 'scripts/benchmark_optimization_policies.py']},
        'previous_seal_sha256': sha(previous / 'freeze-seal.json'),
        'previous_development_sha256': sha(previous / 'development.json'),
        'previous_test_results_sha256': sha(previous / 'test-results.json'),
    }
    write_json(output / 'protocol.json', protocol)
    entries = [{**e, 'evidence_role': 'regression'} for e in previous_manifest['datasets']]
    raw_zip = Path(previous_manifest['data_dir']) / 'ContinuousDistillationData.zip'
    with zipfile.ZipFile(raw_zip) as z:
        rows = list(csv.DictReader(io.StringIO(z.read(protocol['new_run']).decode('utf-8-sig'))))
    columns, target = ['M101', 'TH101_SetPoint', 'TV101', 'T116'], 'T114'
    values = {c: np.asarray([float(row[c]) if row[c].strip() else np.nan for row in rows]) for c in [*columns, target]}
    n = len(rows)
    constants = [c for c in columns if np.nanstd(values[c][:int(n * .4) - 43]) <= 1e-12]
    prepared = raw_zip.parent / 'prepared-policy-validation'
    prepared.mkdir(exist_ok=True)
    path = prepared / 'distillation_a_new_op007.csv'
    with path.open('w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp', 'source_time', *columns, target])
        for i, row in enumerate(rows):
            writer.writerow([(datetime(2000, 1, 1) + timedelta(seconds=30 * i)).isoformat(),
                row['Time'], *[values[c][i] for c in columns], values[target][i]])
    entries.append({'dataset': 'distillation_a_new_op007', 'evidence_role': 'new_operating_run',
        'path': str(path), 'sha256': sha(path), 'source_file': protocol['new_run'],
        'source_sha256': sha(raw_zip), 'rows': n, 'period_seconds': 30,
        'inputs': [c for c in columns if c not in constants], 'output': target,
        'constant_inputs_removed_on_earliest_train': constants,
        'source_class': 'pilot_plant_measurements',
        'notes': 'Same real continuous-distillation apparatus; new operating point. Labels excluded; physical input roles unchanged; no run concatenation.',
        'synthetic_nominal_timestamps': True, 'original_time_column': 'source_time'})
    write_json(output / 'data-manifest.json', {'protocol_sha256': sha(output / 'protocol.json'),
        'data_dir': previous_manifest['data_dir'], 'datasets': entries})
    print(json.dumps([{k: e[k] for k in ['dataset', 'rows', 'inputs', 'evidence_role']} for e in entries], ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.previous, args.out)
