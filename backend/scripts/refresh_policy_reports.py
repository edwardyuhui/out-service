"""Refresh narration only; verify every frozen numerical artifact is unchanged."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.schemas.reporting import ReportRequest
from app.services.modeling_service import load_saved_arx_model
from app.services.report_service import generate_report
from prepare_generalization_data import sha, write_json
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def refresh(out, dataset=None):
    path=out/'api-integration.json'
    api=json.loads(path.read_text())
    write_json(out/'api-before-narration-repair.json',api)
    test_hash=sha(out/'test-results.json')
    development_hash=sha(out/'development.json')
    root=Path(api['artifact_root'])
    for row in api['results']:
        if dataset is not None and row['dataset'] != dataset:
            continue
        assert row['status']=='succeeded'
        assert sha(Path(row['model_path']))==row['model_sha256']
        assert sha(Path(row['export_path']))==row['export_sha256']
        saved=load_saved_arx_model(model_id=UUID(Path(row['model_path']).stem),artifact_root=root)
        engine=create_async_engine('sqlite+aiosqlite:///'+row['database'])
        try:
            async with async_sessionmaker(engine,expire_on_commit=False)() as session:
                report=await generate_report(session,payload=ReportRequest(dataset_id=saved.dataset_id,
                    version_id=saved.source_version_id,study_id=UUID(row['study_id']),
                    title=row['dataset']+' 公开流程数据固定模型验证报告'),artifact_root=root)
                await session.commit()
        finally:
            await engine.dispose()
        assert report.fully_resolved and '{{' not in report.markdown
        assert report.narration_source=='llm'
        expert=report.markdown.split('专家结论（大模型撰写）')[-1].lower()
        assert 'train' in expert and 'test' in expert
        row.update({'previous_report_markdown_path':row['report_markdown_path'],
            'report_markdown_path':str(root/report.artifact_uri),
            'report_html_path':str(root/report.html_artifact_uri),
            'report_bindings':len(report.bindings),'report_charts':len(report.charts),
            'narration_source':report.narration_source,'llm_fallback_reason':report.llm_fallback_reason,
            'llm_provider':report.llm_provider,'llm_model':report.llm_model,
            'train_test_narration_corrected':True})
        assert sha(Path(row['model_path']))==row['model_sha256']
        assert sha(Path(row['export_path']))==row['export_sha256']
        assert sha(out/'test-results.json')==test_hash and sha(out/'development.json')==development_hash
        write_json(path,api)
        print(row['dataset'],'narration refreshed; numerical artifacts unchanged',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--dataset',help='Refresh only this dataset; omit for all reports')
    args=parser.parse_args()
    asyncio.run(refresh(args.out,args.dataset))
