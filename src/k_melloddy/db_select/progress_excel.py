"""A replaceable, verified Excel projection of durably finished papers."""
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from ..core.storage import digest, dump, now
from .excel_export import template_contract, workbook_payload, verify_workbook
from .metadata import paper_order
from .persistence import atomic_replace
from .prisma import summarize


class ProgressWorkbookError(RuntimeError):
    pass


def terminal_records(papers, records):
    ordered=sorted(papers,key=paper_order)
    selected={p['paper_id']:records[p['paper_id']] for p in ordered
              if p['paper_id'] in records
              and records[p['paper_id']].get('processing_state')=='reviewed'
              and records[p['paper_id']]['revalidation'].get('terminal')
              and not records[p['paper_id']]['revalidation'].get('auto_retry')}
    if list(selected)!=[p['paper_id'] for p in ordered[:len(selected)]]:
        raise ProgressWorkbookError('Finished papers are not an uninterrupted source prefix')
    for p in ordered[:len(selected)]:
        r=selected[p['paper_id']]
        if r['pmid']!=p['pmid'] or r['final']['status'] not in {'confirmed','excluded','pending'}:
            raise ProgressWorkbookError('Progress workbook identity or final decision invalid')
    return selected


def render_workbook(root, sheets, summary, papers, records, render=False):
    dependency=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node'
    node=Path(os.environ.get('KM_ARTIFACT_NODE',str(dependency/'bin/node.exe')))
    modules=Path(os.environ.get('KM_ARTIFACT_MODULES',str(dependency/'node_modules')))
    if not node.exists() or not (modules/'@oai/artifact-tool').exists():
        raise ProgressWorkbookError('Configure artifact-tool runtime for progress Excel')
    build=Path(root)/'.build';build.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=build) as temporary:
        stage=Path(temporary);payload=stage/'payload.json'
        payload.write_text(dump(dict(sheets=sheets,summary=summary,output_dir=str(stage.resolve()),render=render)),encoding='utf-8')
        result=subprocess.run([str(node),str(Path(__file__).with_name('workbooks.mjs')),str(payload.resolve()),str(modules.resolve())],
                              capture_output=True,text=True,encoding='utf-8',timeout=180)
        if result.returncode:raise ProgressWorkbookError(result.stderr[-1500:])
        path=stage/'DB_Select_Final.xlsx'
        verify_workbook(path,sheets,papers,records,summary)
        data=path.read_bytes()
        if render:
            for image in stage.glob('*.png'):
                atomic_replace(Path(root)/'Output/progress_previews'/image.name,image.read_bytes())
    return data


def _publish(target, data):
    for attempt in range(3):
        try:
            atomic_replace(target,data)
            return
        except PermissionError as exc:
            if attempt==2:raise ProgressWorkbookError('Excel update blocked by open file: '+str(target)) from exc
            time.sleep(1)


def export_progress(store, run, policy, papers, target, render=False):
    """SQLite commits first. Any Excel failure must block entry into the next paper."""
    target=Path(target).resolve();records=terminal_records(papers,store.records(run))
    if not records:return None
    contract,template_sha=template_contract()
    revisions=[dict(paper_id=k,pmid=r['pmid'],revision=r['revision'],sha256=digest(dump(r).encode())) for k,r in records.items()]
    identity=dict(run_id=run,policy_sha256=policy['sha256'],template_sha256=template_sha,
                  source_sha256=json.loads(store.run(run)['collect_ref'])['sha256'],
                  target=str(target),revisions=revisions)
    fingerprint=digest(dump(identity).encode())
    pointer=target.with_suffix('.progress.json')
    previous=json.loads(pointer.read_text(encoding='utf-8')) if pointer.exists() else None
    pending_dir=store.root/'.build/progress_excel';pending_dir.mkdir(parents=True,exist_ok=True)
    pending_path=pending_dir/(target.stem+'.xlsx')
    pending_meta=pending_path.with_suffix('.json')
    pending=json.loads(pending_meta.read_text(encoding='utf-8')) if pending_meta.exists() else None
    existing=digest(target.read_bytes()) if target.exists() else None
    # Recover a crash between replacing Excel and writing its pointer. Never clobber unknown edits.
    if existing and previous and existing==previous['sha256'] and previous['fingerprint']==fingerprint:
        return previous
    if existing and pending and existing==pending['sha256'] and pending['fingerprint']==fingerprint:
        atomic_replace(pointer,dump(pending));return pending
    if existing and (not previous or existing!=previous['sha256']):
        raise ProgressWorkbookError('Progress Excel has untracked changes; original preserved: '+str(target))
    summary=summarize(papers,records)
    if summary['N_all']!=len(records) or sum(summary[k] for k in ['N_confirmed','N_excluded','N_pending'])!=len(records):
        raise ProgressWorkbookError('Progress Excel final partition does not match saved papers')
    if pending and pending['fingerprint']==fingerprint and pending_path.exists() and digest(pending_path.read_bytes())==pending['sha256']:
        data=pending_path.read_bytes();manifest=pending
    else:
        sheets,_=workbook_payload(papers,records,contract)
        for sheet in sheets:sheet['title']=f"K-MELLODDY {policy['organ']['organ']} 진행 중 ({len(records)}/{len(papers)})"
        data=render_workbook(store.root,sheets,summary,papers,records,render)
        manifest=dict(**identity,fingerprint=fingerprint,sha256=digest(data),
                      status='IN_PROGRESS',processed_papers=len(records),scope_count=len(papers),
                      counts=summary,last_paper_id=list(records)[-1],timestamp=now(),downstream_ready=False)
        # Audit remains immutable. The current XLSX is an explicitly requested projection, not a final artifact.
        store.artifact('Runs/review/progress_excel/'+digest(dump(manifest).encode())+'.json',manifest)
        atomic_replace(pending_path,data);atomic_replace(pending_meta,dump(manifest))
    _publish(target,data)
    atomic_replace(pointer,dump(manifest))
    return manifest
