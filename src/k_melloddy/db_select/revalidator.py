"""Finite passes: select each pending paper once, never reselect in the same pass."""
from .metadata import paper_order


def eligible(records,max_attempts,automatic=True,additional_pass=False,automatic_attempts=1):
    threshold=automatic_attempts if automatic else max_attempts
    return sorted([r for r in records.values() if r['final']['status']=='pending'
                   and r.get('initial_review_valid') is True
                   and (additional_pass or r.get('revalidation',{}).get('auto_retry',True))
                   and (additional_pass or r['revalidation']['attempt_count']<min(threshold,max_attempts))],key=paper_order)


def audit_metrics(store,run):
    """Derive initial/final populations from committed immutable revisions, not HTTP calls."""
    rows=store.db.execute('SELECT paper_id,record_json FROM revisions WHERE run_id=? ORDER BY revision',(run,)).fetchall()
    first={}
    for row in rows:first.setdefault(row['paper_id'],__import__('json').loads(row['record_json']))
    current=store.records(run)
    pending={k:r for k,r in first.items() if r['final']['status']=='pending'}
    return dict(initial_processed_count=len(first),initial_pending_count=len(pending),
        initial_pending_code_counts={code:sum(r['final']['code']==code for r in pending.values()) for code in ['P01','P02','P03','P04']},
        tiab_present_count=sum(r['tiab'].get('availability')=='present' for r in first.values()),
        tiab_absent_count=sum(r['final']['code'] in {'ABSTRACT_ABSENT','TIAB_ABSENT'} for r in first.values()),
        E01_excluded_count=sum(r['final']['code']=='E01' for r in current.values()),
        E02_excluded_count=sum(r['final']['code']=='E02' for r in current.values()),
        fulltext_target_count=sum(r['tiab'].get('decision') in {'candidate','pending_relevance'} and r['final']['code']!='ABSTRACT_ABSENT' for r in first.values()),
        fulltext_exclusion_code_counts={code:sum(r['final']['code']==code for r in current.values()) for code in [f'E{i:02}' for i in range(3,9)]},
        revalidation_target_count=len(pending),
        retained_pending_count=sum(current[k]['final']['status']=='pending' for k in pending),
        revalidation_attempt_count=sum(r['revalidation']['attempt_count'] for r in current.values()),
        revalidated_paper_count=sum(r['revalidation']['attempt_count']>0 for r in current.values()),
        converted_to_included_count=sum(current[k]['final']['status']=='confirmed' for k in pending),
        converted_to_excluded_count=sum(current[k]['final']['status']=='excluded' for k in pending),
        final_pending_count=sum(r['final']['status']=='pending' for r in current.values()))


def initial_complete(papers,records):
    return all(p['paper_id'] in records and valid_initial(records[p['paper_id']]) for p in papers)


def valid_initial(record):
    if record.get('workflow_version')=='2.0':
        return record.get('initial_review_valid') is True and record['final']['status'] in {'confirmed','excluded','pending'}
    if record.get('initial_review_valid') is not True or record.get('schema_version')!='1.0':return False
    if 'r01' in record.get('provenance',{}).get('prompt_version','').lower():return False
    final=record.get('final',{})
    if final.get('status')=='excluded' and final.get('code') in {'E01','E02','ABSTRACT_ABSENT','TIAB_ABSENT'}:return True
    return final.get('status') in {'confirmed','excluded','pending'} and bool(record.get('evidence_ref')) and record.get('fulltext',{}).get('status') in {'reviewed','access_investigated'}
