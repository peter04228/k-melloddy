"""One resumable, frozen P02 pass; preserve the complete parent run and its outputs."""
import argparse
import json
from pathlib import Path
from ..core.storage import dump,digest,now,uid,safe_name
from ..db_collect.engine import project_lock
from .metadata import load_collect,paper_order
from .persistence import atomic_replace
from .submitted_review import SubmittedReviewProvider
from .verified_workflow import VerifiedSelector
from .revalidation_access import RevalidationAccess


def run_campaign(engine,run,campaign,scope,render=False,export=True):
    campaign=safe_name(campaign);root=engine.root/'Revalidation'/campaign
    baseline_path=root/'baseline.json'
    with project_lock(engine.root):
        info=engine.store.run(run);engine.run_id=run;engine.campaign_id=campaign
        engine.policy=json.loads(info['policy_json']);engine.papers=json.loads(info['input_json'])
        ref=json.loads(info['collect_ref'])
        manifest,allpapers,checked=load_collect(ref['path'],engine.root.parent/'DB_Collect')
        if checked['sha256']!=ref['sha256']:raise ValueError('Collect manifest changed')
        selected=sorted(allpapers,key=paper_order,reverse=ref.get('selection',{}).get('order')=='desc')[:ref.get('selection',{}).get('limit')]
        if selected!=engine.papers:raise ValueError('Frozen Collect input changed')
        pairs={p['paper_id']:p['pmid'] for p in engine.papers}
        if not scope or len(scope)!=len(set(scope)) or any(pairs.get(k)!=v for k,v in scope.items()):raise ValueError('Scope ID/PMID mismatch')
        records=engine.store.records(run)
        if baseline_path.exists():
            baseline=json.loads(baseline_path.read_text(encoding='utf-8'))
            if baseline['parent_run_id']!=run or baseline['scope']!=scope:raise ValueError('Campaign scope changed')
            for key,value in baseline['records'].items():
                if key not in scope and records[key]!=value:raise ValueError('Untargeted record changed')
        else:
            actual={k:r['pmid'] for k,r in records.items() if r['final']['status']=='pending' and r['final']['code']=='P02'}
            if actual!=scope:raise ValueError('Scope must match all current P02 records exactly')
            if any(records[k]['revalidation']['attempt_count']>=engine.policy['rules']['max_revalidation_attempts'] for k in scope):raise ValueError('Revalidation cap reached')
            baseline=dict(campaign_id=campaign,parent_run_id=run,created_at=now(),scope=scope,records=records,
                policy_sha256=engine.policy['sha256'],target_attempts={k:records[k]['revalidation']['attempt_count']+1 for k in scope})
            # Preserve all derived aliases before any mutation; no existing research file is deleted.
            for directory in ['JSON','PRISMA','Output']:
                for p in (engine.root/directory).glob('*'):
                    if p.is_file():engine.store.artifact(f'Revalidation/{campaign}/baseline/{directory}/{p.name}',p.read_bytes(),raw=True)
            engine.store.artifact(f'Revalidation/{campaign}/baseline.json',baseline)
        engine.collect_run_id=manifest['run_id'];engine.phase='revalidation'
        lookup={p['paper_id']:p for p in engine.papers}
        try:
            for key in sorted(scope,key=lambda k:paper_order(lookup[k])):
                previous=engine.store.records(run)[key]
                # Atomic paper revision is authoritative if process died before writing the JSON checkpoint.
                if previous['revalidation']['attempt_count']>=baseline['target_attempts'][key]:continue
                started=dict(campaign_id=campaign,paper_id=key,pmid=scope[key],attempt=baseline['target_attempts'][key],status='in_progress',checked_at=now())
                engine.store.artifact(f'Revalidation/{campaign}/events/{uid()}.json',started)
                atomic_replace(root/'checkpoint.json',dump(started))
                engine.event('2.9',key,'started',details=started)
                record=engine.review(lookup[key],previous)
                saved=dict(started,status='saved',final=record['final'],processing_state=record['processing_state'],revision=record['revision'],checked_at=now())
                engine.store.artifact(f'Revalidation/{campaign}/events/{uid()}.json',saved)
                atomic_replace(root/'checkpoint.json',dump(saved))
            records=engine.store.records(run)
            if any(records[k]!=r for k,r in baseline['records'].items() if k not in scope):raise ValueError('Untargeted paper mutation')
            engine.qc(records);summary=engine.refresh(records)
            transitions=dict(to_confirmed=0,to_excluded=0,to_other_pending=0,retained_P02=0)
            for key in scope:
                f=records[key]['final'];bucket='to_confirmed' if f['status']=='confirmed' else 'to_excluded' if f['status']=='excluded' else 'retained_P02' if f['code']=='P02' else 'to_other_pending'
                transitions[bucket]+=1
            assert sum(transitions.values())==len(scope)
            result=dict(campaign_id=campaign,parent_run_id=run,input_count=len(scope),transitions=transitions,counts=summary,
                first_pass_papers=len(baseline['records']),initial_pending_papers=len(scope),
                network_revalidation_papers=sum(bool(engine.store.read_ref(records[k]['revalidation']['history_refs'][baseline['target_attempts'][k]-1],run,records[k]).get('access_results')) for k in scope),
                captured_review_papers=sum(bool(records[k].get('fulltext',{}).get('verification_state',{}).get('captured_review_sha256')) for k in scope),
                processed_count=sum(records[k]['revalidation']['attempt_count']>=baseline['target_attempts'][k] for k in scope),
                blocked_ids=[k for k in scope if records[k]['processing_state']=='blocked_verification'],
                untouched_count=len(records)-len(scope),scope=scope,checked_at=now())
            engine.store.artifact(f'Revalidation/{campaign}/results/{uid()}.json',result)
            atomic_replace(root/'summary.json',dump(result))
            if export:result['manifest']=engine.export(records,render)
            engine.store.set_status(run,summary['status'])
            return result
        except BaseException:
            engine.store.set_status(run,'PARTIAL');raise


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--root',type=Path,required=True);p.add_argument('--run',required=True)
    p.add_argument('--campaign',required=True);p.add_argument('--scope',type=Path,required=True)
    p.add_argument('--review-file',type=Path,required=True);p.add_argument('--render',action='store_true')
    p.add_argument('--no-export',action='store_true',help='Save JSON/PRISMA now; publish Excel after evidence review')
    p.add_argument('--trace-http',action='store_true',help='Print request-level progress for slow external sites')
    a=p.parse_args();scope=json.loads(a.scope.read_text(encoding='utf-8'))
    log=lambda x:print(x,flush=True)
    engine=VerifiedSelector(a.root,organ='Liver',provider=SubmittedReviewProvider(a.review_file),collector=RevalidationAccess(trace=log if a.trace_http else None),log=log)
    try:print(json.dumps(run_campaign(engine,a.run,a.campaign,scope,a.render,export=not a.no_export),ensure_ascii=False,indent=2))
    finally:engine.close()


if __name__=='__main__':main()
