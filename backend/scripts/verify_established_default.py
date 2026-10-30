"""Verify default rollout on known data without opening Test or changing models."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.schemas.optimization import OptimizationStartRequest
from app.services.optimization_service import _trial_delays, replay_training_selection, run_study
from benchmark_generalization import clean, fit, request_for
from benchmark_real_process import load_series
from prepare_generalization_data import sha, write_json


def main(previous, out):
    manifest=json.loads((previous/'data-manifest.json').read_text())
    old=json.loads((previous/'development.json').read_text())
    results=[]
    for entry, row in zip(manifest['datasets'],old['results'],strict=True):
        seed=row['chosen_seed_by_validation']
        expected=next(s for s in row['seeds'] if s['seed']==seed)
        source=load_series(Path(entry['path']),entry['inputs'],entry['output'],entry['period_seconds'])
        masked={c:v.copy() for c,v in source.values.items()}
        for signal in masked.values():
            signal[int(source.n_samples*.8):]=0
        hidden=replace(source,values=masked)
        request=OptimizationStartRequest(version_id=source.version_id,input_columns=entry['inputs'],
            output_column=entry['output'],history_guard=43,max_trials=10,random_seed=seed)
        assert request.optimization_policy=='established'
        outcome=run_study(hidden,request,input_columns=entry['inputs'],output_column=entry['output'])
        params=outcome.best_params
        selection=replay_training_selection(hidden,params,entry['inputs'],entry['output'],train_ratio=.6)
        formal=request_for(hidden,params,_trial_delays(params,entry['inputs']),selection.selected_sample_indices,selection.sample_weights)
        model=fit(hidden,formal)
        saved=expected['model']
        matching=(np.allclose(model.theta,saved['theta'],rtol=1e-10,atol=1e-10) and
            np.isclose(model.intercept,saved['intercept'],rtol=1e-10,atol=1e-10) and
            selection.selected_sample_indices==saved['request']['training_sample_indices'] and
            selection.sample_weights=={int(k):v for k,v in saved['request']['sample_weights'].items()})
        results.append(clean({'dataset':entry['dataset'],'seed':seed,'source_sha256':sha(Path(entry['path'])),
            'optimization_policy':request.optimization_policy,'matches_previous_frozen_model':bool(matching),
            'previous_validation_score':expected['validation_score'],'current_validation_score':outcome.best_value,
            'test_opened':False,'previous_model_unchanged':True,'theta':model.theta.tolist(),'intercept':model.intercept,
            'training_rows':model.training_rows,'validation_acceptance':outcome.best_metrics['validation_acceptance']}))
        write_json(out/'established-default-verification.json',{'results':results})
        print(entry['dataset'],'default frozen model match',matching,flush=True)
    assert all(r['matches_previous_frozen_model'] for r in results), 'Default numerical behavior changed'


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    main(args.previous,args.out)
