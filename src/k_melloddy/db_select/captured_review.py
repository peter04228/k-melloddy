"""Append explicit human review of a captured campaign bundle, with no fake new HTTP requests."""
import copy
import json
from pathlib import Path
from ..core.storage import digest,dump,now
from ..db_collect.engine import project_lock
from .metadata import paper_order,load_collect
from .submitted_review import SubmittedReviewProvider
from .evidence_collector import validate_evidence
from .dataset_verifier import citations


def apply_captured_reviews(engine,run,campaign,path):
    data=json.loads(Path(path).read_text(encoding='utf-8'));submission_hash=digest(dump(data).encode())
    if data['run_id']!=run or data['campaign_id']!=campaign:raise ValueError('Review campaign mismatch')
    baseline=json.loads((engine.root/'Revalidation'/campaign/'baseline.json').read_text(encoding='utf-8'))
    with project_lock(engine.root):
        info=engine.store.run(run);engine.run_id=run;engine.campaign_id=campaign
        engine.policy=json.loads(info['policy_json']);engine.papers=json.loads(info['input_json']);engine.phase='revalidation'
        source=json.loads(info['collect_ref']);manifest,_,checked=load_collect(source['path'],engine.root.parent/'DB_Collect')
        if checked['sha256']!=source['sha256']:raise ValueError('Collect source changed')
        engine.collect_run_id=manifest['run_id']
        records=engine.store.records(run);prepared={}
        for key,entry in data['papers'].items():
            if key not in baseline['scope']:raise ValueError('Review outside campaign scope')
            r=records[key]
            if r.get('fulltext',{}).get('verification_state',{}).get('captured_review_sha256')==submission_hash:continue
            if r['pmid']!=entry['pmid'] or r['revision']!=entry['based_on_revision']:raise ValueError('Stale captured review')
            if r['revalidation']['attempt_count']>=engine.policy['rules']['max_revalidation_attempts']:raise ValueError('Review cap reached')
            bundle=copy.deepcopy(engine.store.read_ref(r['evidence_ref'],run,r))
            bundle['official_identity']={'pmid':r['pmid'],'doi':r['verified_metadata'].get('DOI',''),'pmcid':r['verified_metadata'].get('PMCID','')}
            # Extra responses must come from preserved, independently hashed capture files.
            for ref in entry.get('additional_evidence_files',[]):
                raw=(engine.root/ref['path']).read_bytes()
                if digest(raw)!=ref['sha256']:raise ValueError('Captured response hash mismatch')
                bundle['records'].extend(json.loads(raw))
            for correction in entry.get('access_corrections',[]):
                e=next(e for e in bundle['records'] if e['evidence_id']==correction['evidence_id'])
                if e['payload_sha256']!=correction['payload_sha256']:raise ValueError('Correction source mismatch')
                visible=e['text'].lower()
                if e['failure_reason']!='recaptcha' or any(t in visible for t in ['recaptcha','checking your browser','verify you are human','client challenge','unfortunately, bots']) or not e.get('complete_body'):
                    raise ValueError('Not the normal-page script false positive')
                e.update(status='accessible',failure_reason='',interpretation_correction='Normal page; reCAPTCHA only in script, not visible challenge',original_status=e['status'])
            for correction in entry.get('identifier_conflicts',[]):
                from urllib.parse import urlsplit,unquote
                e=next(e for e in bundle['records'] if e['evidence_id']==correction['evidence_id'])
                observed=urlsplit(e['url'])
                official=r['verified_metadata'].get('DOI','').casefold()
                if observed.hostname!='doi.org' or e.get('route')!='scholarly_observed_location' or not official or unquote(observed.path.lstrip('/')).casefold()==official:
                    raise ValueError('Not an unverified alternate DOI route')
                e.update(original_status=e['status'],original_kind=e['kind'],kind='metadata',status='fetch_error',identity_match=False,
                    failure_reason='unverified_alternate_DOI_excluded_from_article_evidence',interpretation_correction=correction['reason'])
            from urllib.parse import urlsplit
            for e in bundle['records']:
                if e['kind']=='fulltext' and urlsplit(e['url']).hostname=='account.ncbi.nlm.nih.gov':
                    e.update(original_kind=e['kind'],kind='metadata',interpretation_correction='NCBI account navigation is not an article source')
            visual=entry.get('visual_review')
            if visual:
                if not visual['pages'] or not visual['reviewer_note']:raise ValueError('Visual review missing')
                for page in visual['pages']:
                    if digest((engine.root/page['path']).read_bytes())!=page['sha256']:raise ValueError('Reviewed image changed')
                    parent=next(e for e in bundle['records'] if e['evidence_id']==page['source_evidence_id'])
                    import base64
                    if not parent['identity_match'] or page['url'] not in base64.b64decode(parent['body_sample_b64']).decode('utf-8',errors='replace'):raise ValueError('Unobserved scan image')
                bundle.update(visual_review=visual,fulltext_reviewed=True,sections_checked=visual['sections_checked'])
                for state in bundle.get('workflow',[]):
                    if state['step'] in visual['sections_checked']:state['state']='reviewed'
            bundle['captured_review']={'submission_sha256':submission_hash,'reviewed_at':now(),'based_on_revision':r['revision'],
                'network_repeated':False,'reviewer_note':entry['reviewer_note']}
            constraints=entry.get('access_constraints')
            if constraints:
                citations(constraints['evidence_refs'],bundle)
                bundle['captured_review']['access_constraints']=constraints
            validate_evidence(bundle)
            proposal=entry.get('proposal')
            if proposal:
                from .decision import fulltext_decision
                from .access_workflow import access_pending
                citations(proposal['evidence_refs'],bundle)
                fulltext_decision(copy.deepcopy(proposal),bundle)
                if proposal['status']=='pending' and proposal['code']=='P02' and not access_pending(bundle):raise ValueError('Captured P02 does not satisfy access prerequisites')
            prepared[key]=(entry,r,bundle)
        original_provider=engine.provider
        class Provider:
            name='codex_session_captured_review';model='explicit-human-review'
            def propose(self,phase,paper,policy,evidence,previous):
                entry,r,bundle=prepared[paper['paper_id']]
                if phase=='tiab':return {k:copy.deepcopy(v) for k,v in entry.get('tiab',r['tiab']).items() if k!='availability'}
                if entry.get('proposal'):return copy.deepcopy(entry['proposal'])
                raise ValueError('No final claim; preserve actual unresolved access')
        class Verifier:
            def verify(self,paper):return copy.deepcopy(prepared[paper['paper_id']][1]['metadata_verification'])
        class Collector:
            def collect(self,paper,policy,action=''):return copy.deepcopy(prepared[paper['paper_id']][2])
        engine.provider=Provider();engine.verifier=Verifier();engine.collector=Collector()
        engine.captured_review_sha256=submission_hash
        changed=[]
        for paper in sorted(engine.papers,key=paper_order):
            if paper['paper_id'] not in prepared:continue
            r=engine.review(paper,prepared[paper['paper_id']][1]);changed.append(r['paper_id'])
        current=engine.store.records(run)
        if any(current[k]!=r for k,r in baseline['records'].items() if k not in baseline['scope']):raise ValueError('Untargeted record changed')
        engine.qc(current);summary=engine.refresh(current);engine.store.set_status(run,summary['status'])
        engine.provider=original_provider
        del engine.captured_review_sha256
        return dict(changed=changed,summary=summary,submission_sha256=submission_hash)
