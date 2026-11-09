"""Append reviewed narrative corrections without changing decisions or HTTP evidence."""
import copy
from ..core.storage import now


def amend(store,run,corrections):
    records=store.records(run)
    for key,entry in corrections.items():
        r=records[key]
        if entry['pmid']!=r['pmid']:raise ValueError('Narrative PMID mismatch')
        for field in ['initial_reason','final_reason','reviewer_note']:
            if not entry[field] or '??' in entry[field]:raise ValueError('Unreadable correction')
        if r['final']['status']!='pending' or r['revalidation']['attempt_count']!=1:raise ValueError('Expected one completed pending review')
        if not r['revalidation'].get('terminal'):raise ValueError('Cannot amend active review')
    for key,entry in corrections.items():
        r=copy.deepcopy(records[key])
        if r['fulltext'].get('narrative_amendment')==entry:continue
        original=copy.deepcopy(r)
        bundle=store.read_ref(r['evidence_ref'],run,r,'evidence')
        bundle['narrative_amendment']={'previous_evidence_ref':r['evidence_ref'],'timestamp':now(),
            'reason':'Windows shell text encoding replaced reviewer prose with question marks; explicit reviewed correction',
            'reviewer_note':entry['reviewer_note'],'http_evidence_unchanged':True}
        bundle.setdefault('session_review',{})['reviewer_note']=entry['reviewer_note']
        if bundle.get('visual_review'):bundle['visual_review']['reviewer_note']=entry['reviewer_note']
        constraints=bundle.get('session_review',{}).get('access_constraints')
        if constraints and '??' in constraints.get('summary',''):
            constraints['summary']='No reusable dataset access permission was established in this review.'
        new_evidence=store.document(run,r,'evidence',bundle)
        r['evidence_ref']=new_evidence
        r['final']['reason']=entry['final_reason']
        ft=r['fulltext'];ft['what_confirmed']=entry['confirmed'];ft['what_unresolved']=entry['unresolved']
        ft['next_verification_action']=entry['next'];ft['narrative_amendment']=entry
        state=ft.get('verification_state',{})
        state['unresolved_questions']=entry['unresolved']
        if '??' in str(state.get('license_or_access_constraints','')):
            state['license_or_access_constraints']='No reusable dataset access permission was established in this review.'
        for attempt in state.get('verification_attempts',[]):
            if attempt.get('source')=='PMC_scan_image':attempt['evidence_excerpt_or_summary']=entry['reviewer_note']
        old_ref=r['revalidation']['history_refs'][0]
        h=store.read_ref(old_ref,run,r,'revalidation')
        h.update(supersedes_document_id=old_ref['path'].rsplit('/',1)[-1],narrative_amendment=entry,
            narrative_amended_at=now(),evidence_ref=new_evidence,result=r['final'],final_reason=entry['final_reason'],
            unresolved_reason=entry['final_reason'],what_confirmed=entry['confirmed'],what_unresolved=entry['unresolved'],
            unresolved_questions=entry['unresolved'],next_verification_action=entry['next'])
        h['initial_result']=dict(h['initial_result'],reason=entry['initial_reason'])
        h['previous_result']=dict(h['previous_result'],reason=entry['initial_reason'])
        h['verification_attempts']=state.get('verification_attempts',h.get('verification_attempts',[]))
        h['license_or_access_constraints']=state.get('license_or_access_constraints',h.get('license_or_access_constraints','unknown'))
        new_history=store.document(run,r,'revalidation',h)
        r['revalidation']['history_refs']=[new_history]
        assert (r['final']['status'],r['final']['code'])==(original['final']['status'],original['final']['code'])
        assert bundle['records']==store.read_ref(original['evidence_ref'],run,r,'evidence')['records']
        store.save(run,r,'narrative_amendment')
    return store.aggregate(run)
