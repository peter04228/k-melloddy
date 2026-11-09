from collections import Counter
import json
from ..core.storage import digest,dump,now
from .revalidator import valid_initial


def summarize(papers,records):
    outcomes=Counter((records[p['paper_id']]['final']['status'] if valid_initial(records[p['paper_id']]) or records[p['paper_id']]['final']['status']=='fetch_error' else 'unreviewed') if p['paper_id'] in records else 'unreviewed' for p in papers)
    completed=sum(outcomes[k] for k in ['confirmed','excluded','pending'])
    incomplete=len(papers)-completed
    assert len(papers)==completed+incomplete
    due=sum(r['final']['status']=='pending' and r['revalidation']['attempt_count']<1 for r in records.values())
    blocked=sum(r.get('processing_state')=='blocked_verification' for r in records.values())
    return dict(input_count=len(papers),N_all=completed,N_confirmed=outcomes['confirmed'],
        N_excluded=outcomes['excluded'],N_pending=outcomes['pending'],incomplete_count=incomplete,
        fetch_error_count=outcomes['fetch_error'],unreviewed_count=outcomes['unreviewed'],
        confirmed_dataset_count=len({d['dataset_id'] for r in records.values() if r['final']['status']=='confirmed' for d in r['datasets']}),
        revalidation_due_count=due,status='COMPLETED' if incomplete==0 and due==0 and blocked==0 else 'PARTIAL')


def write_prisma(store,run,policy,papers,records,snapshot):
    from .persistence import atomic_replace
    cumulative=store.verify_aggregate(run)
    generation=cumulative['screening_results.json']['generation_id']
    refs=[]
    for n in range(1,13):
        step=f'2.{n}'
        all_events=[dict(e) for e in store.db.execute('SELECT * FROM events WHERE run_id=? AND step_id=? ORDER BY rowid',(run,step))]
        latest={}
        for e in all_events:
            if e['outcome']!='started': latest[e['paper_id']]=e
        outcomes=Counter(e['outcome'] for e in latest.values())
        if step in {'2.7','2.10'}:
            expected={key:({'confirmed':'forwarded','excluded':'excluded','pending':'pending','fetch_error':'fetch_error'}[r['final']['status']],r['final']['code']) for key,r in records.items()}
            actual={key:(e['outcome'],e['reason_code']) for key,e in latest.items()}
            if actual!=expected:raise ValueError('Stage PRISMA/SQLite decision mismatch: '+step)
        count=len(latest)
        row=dict(run_id=run,step_id=step,input_count=count,forwarded_count=outcomes['forwarded'],
            excluded_count=outcomes['excluded'],pending_count=outcomes['pending'],fetch_error_count=outcomes['fetch_error'],
            revalidated_count=sum(e['phase']=='revalidation' for e in latest.values()),
            reason_code_counts=dict(Counter(e['reason_code'] for e in latest.values() if e['reason_code'])),
            unit='paper',timestamp=now(),policy_version=policy['organ']['version'],policy_sha256=policy['sha256'],generation_id=generation,
            identifier_snapshot_sha256=digest(dump(sorted(latest)).encode()),events=all_events)
        if count!=sum(row[k] for k in ['forwarded_count','excluded_count','pending_count','fetch_error_count']):raise ValueError('Stage PRISMA conservation mismatch: '+step)
        path=f'PRISMA/{step}.json';atomic_replace(store.root/path,dump(row));refs.append({'path':path,'sha256':digest(dump(row).encode())})
    summary=summarize(papers,records)
    tiab_excluded=sum(r['final']['status']=='excluded' and r['final']['code'] in {'E01','E02','ABSTRACT_ABSENT','TIAB_ABSENT'} for r in records.values())
    if summary!=cumulative['screening_results.json']['counts']:raise ValueError('Cumulative JSON/PRISMA counts mismatch')
    summary.update(run_id=run,unit='paper',timestamp=now(),policy_sha256=policy['sha256'],generation_id=generation,
        revalidation_metrics=cumulative['revalidation_history.json']['metrics'],
        academic_prisma={'Identification':len(papers),'Screening_excluded':tiab_excluded,
                         'Eligibility_excluded':summary['N_excluded']-tiab_excluded,'Included':summary['N_confirmed'],
                         'Pending':summary['N_pending']},
        dataset_unit='dataset',note='Initial pending events remain in step histories; final counts use latest per-paper decisions.')
    path='PRISMA/final_summary.json';atomic_replace(store.root/path,dump(summary));refs.append({'path':path,'sha256':digest(dump(summary).encode())})
    return summary,refs
