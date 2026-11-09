"""Sequential 0/1/2/3 workflow with explicit, evidence-bound session review."""
import argparse
import copy
import json
from pathlib import Path
from collections import Counter

from ..core.storage import digest, dump, now, uid
from ..db_collect.engine import project_lock
from .verified_workflow import VerifiedSelector
from .submitted_review import SubmittedReviewProvider
from .official_metadata import OfficialMetadataVerifier
from .decision import tiab_decision, fulltext_decision
from .evidence_collector import validate_evidence
from .dataset_verifier import citations
from .metadata import load_collect, paper_order
from .persistence import atomic_replace
from .policy import load_policy, tiab_missing, review_instructions
from .full_workflow_access import FullWorkflowAccess, extract_context


class ReviewRequired(Exception):
    """Do not turn an absent reviewer response into a scientific P code."""


class SessionProvider(SubmittedReviewProvider):
    def __init__(self, path, engine):
        super().__init__(path)
        self.engine = engine

    def response(self, paper, policy, bundle):
        engine = self.engine
        identity = dict(run_id=engine.run_id, paper_id=paper['paper_id'], pmid=paper['pmid'],
                        round=engine.round, policy_sha256=policy['sha256'],
                        evidence_sha256=digest(dump(bundle).encode()))
        folder = engine.session / 'reviews'
        stem = paper['paper_id'] + '_r' + str(engine.round)
        request = dict(identity, paper=paper, policy=policy, evidence=bundle,
                       decision_instructions=review_instructions(policy,engine.round,
                           engine.store.records(engine.run_id).get(paper['paper_id'],{}).get('final',{}).get('code','')),
                       instruction='Review actual captured evidence; no unperformed requests or invented data.')
        request_path = folder / (stem + '.request.json')
        if request_path.exists():
            existing=json.loads(request_path.read_text(encoding='utf-8'))
            if any(existing[k]!=v for k,v in identity.items() if k!='evidence_sha256'):
                raise ValueError('Review identity changed')
            if existing['evidence_sha256']!=identity['evidence_sha256']:
                # Supplementary discovery never overwrites a prior request/answer.
                stem += '_e' + identity['evidence_sha256'][:16]
                request_path = folder / (stem + '.request.json')
        if not request_path.exists():
            engine.store.artifact(str(request_path.relative_to(engine.root)), request)
        else:
            existing=json.loads(request_path.read_text(encoding='utf-8'))
            if any(existing[k]!=v for k,v in identity.items()):raise ValueError('Review request changed')
        answer_path = folder / (stem + '.answer.json')
        if not answer_path.exists():
            engine.transition(paper, '2.4', 'pending', {'request': str(request_path), 'state':'awaiting_LLM_review'})
            raise ReviewRequired(str(request_path))
        answer = json.loads(answer_path.read_text(encoding='utf-8'))
        if answer.get('request_sha256') != digest(request_path.read_bytes()):
            raise ValueError('Review answer is not bound to the exact request')
        if not answer.get('reviewer_note'):raise ValueError('Missing explicit review explanation')
        return answer

    def review_evidence(self, paper, policy, bundle, previous):
        try:return self._review_evidence(paper,policy,bundle,previous)
        except (ValueError,KeyError,TypeError) as exc:
            raise ReviewRequired('Review validation failed; no final decision saved: '+str(exc)) from exc

    def _review_evidence(self, paper, policy, bundle, previous):
        answer = self.response(paper, policy, bundle)
        bundle = copy.deepcopy(bundle)
        review = answer.get('evidence_review', {})
        if review.get('archive_selections'):
            from .archive_review import selected_tables
            bundle=selected_tables(bundle,review['archive_selections'])
        if review.get('docx_selections'):
            from .archive_review import selected_docx_tables
            bundle=selected_docx_tables(bundle,review['docx_selections'])
            validate_evidence(bundle)
        lookup = {e['evidence_id']: e for e in bundle['records']}
        for item in review.get('sections', []):
            citations([item['reference']], bundle)
            e = lookup[item['reference']['evidence_id']]
            if e['kind'] != 'fulltext' or not e['identity_match']:
                raise ValueError('Section reference is not the verified article')
        if review.get('fulltext_reviewed'):
            if not review.get('sections') and not review.get('visual_review'):
                raise ValueError('Full-text review requires section or visual evidence')
            bundle['fulltext_reviewed'] = True
        if review.get('visual_review'):
            import base64
            visual=review['visual_review']
            if not visual.get('pages') or not visual.get('reviewer_note'):raise ValueError('Visual review empty')
            for page in visual['pages']:
                path=(self.engine.root/page['path']).resolve()
                if not path.is_relative_to(self.engine.root.resolve()) or digest(path.read_bytes())!=page['sha256']:
                    raise ValueError('Visual evidence hash/path mismatch')
                e=lookup[page['source_evidence_id']]
                if not e['identity_match'] or page['url'] not in base64.b64decode(e['body_sample_b64']).decode('utf-8',errors='replace'):
                    raise ValueError('Scan is not linked from this article')
            bundle['visual_review']=visual
        bundle['sections_checked'] = [x['name'] for x in review.get('sections', [])]
        if review.get('visual_review'):
            bundle['sections_checked'] = list(dict.fromkeys(bundle['sections_checked']+review['visual_review']['sections_checked']))
        for field in ['supplementary_checked','repository_checked','survey_complete']:
            if review.get(field):
                refs=review.get(field+'_evidence',[])
                citations(refs,bundle)
                bundle[field]=True
        for state in bundle.get('workflow',[]):
            if state['step'] in bundle['sections_checked']:state['state']='reviewed'
            if state['step']=='Supplementary' and bundle['supplementary_checked']:state['state']='reviewed'
            if state['step']=='Repository' and bundle['repository_checked']:state['state']='reviewed'
        for step in review.get('verified_steps',[]):
            if step not in {'data_file_or_api','toxicity_features'}:raise ValueError('Invalid verified step')
            citations(review['verified_steps'][step],bundle)
            for state in bundle.get('workflow',[]):
                if state['step']==step:state['state']='verified'
        bundle['content_access_review']=review.get('content_access_review',[])
        for item in bundle['content_access_review']:
            citations([item['reference']],bundle)
            e=lookup[item['reference']['evidence_id']]
            if e['kind']!='fulltext' or not e['identity_match'] or item['classification']!='abstract_only':
                raise ValueError('Unsupported content access classification')
        bundle['session_review']={'reviewer_note':answer['reviewer_note'],'checked_at':now(),
                                  'answer_sha256':digest(dump(answer).encode())}
        if review.get('access_constraints'):
            citations(review['access_constraints']['evidence_refs'],bundle)
            bundle['session_review']['access_constraints']=review['access_constraints']
        # Store answer in memory only after the exact fetched bundle was reviewed.
        self.answer=answer
        return bundle

    def propose(self, phase, paper, policy, evidence, previous):
        if phase=='tiab':
            if paper['paper_id'] not in self.data.get('papers',{}):raise ReviewRequired('TI/AB review required: '+paper['paper_id'])
            return super().propose(phase,paper,policy,evidence,previous)
        if not getattr(self,'answer',None):raise ReviewRequired('Full-text response missing')
        proposal=copy.deepcopy(self.answer['proposal'])
        try:fulltext_decision(copy.deepcopy(proposal),evidence)
        except ValueError as exc:raise ReviewRequired('Invalid final proposal; no automatic P02 fallback: '+str(exc)) from exc
        self.engine.transition(paper,'2.4','forwarded',{'reviewer_note':self.answer['reviewer_note']})
        return proposal


class CachedVerifier:
    def __init__(self, engine, real):self.engine=engine;self.real=real
    def verify(self, paper):
        folder=self.engine.session/'cache'/paper['paper_id']
        existed=(folder/'official_metadata_0.json').exists()
        result=self.engine.cached(paper,'official_metadata',lambda:self.real.verify(paper),round_number=0)
        if result.get('status')=='verified' or not existed:return result
        # A failed transport checkpoint is evidence of an attempt, not a permanent
        # official-metadata verdict. Preserve it and append recovery checkpoints.
        recoveries=sorted(folder.glob('official_metadata_recovery_*_0.json'))
        for path in reversed(recoveries):
            previous=self.engine.cached(paper,path.stem[:-2],lambda:None,round_number=0)
            if previous.get('status')=='verified':return previous
        return self.engine.cached(paper,f'official_metadata_recovery_{len(recoveries)+1:04d}',
                                  lambda:self.real.verify(paper),round_number=0)


class CachedCollector:
    def __init__(self,engine,real):self.engine=engine;self.real=real
    def collect(self,paper,policy,action=''):
        def gather():
            self.engine.transition(paper,'2.1','started',{'action':action})
            bundle=self.real.collect(paper,policy,action if isinstance(action,dict) else {'phase':'initial','known_records':[]})
            self.engine.transition(paper,'2.1','forwarded',{'requests':len(bundle['records']), 'coverage':bundle.get('search_coverage',[])})
            bundle['extracted_context']=extract_context(bundle)
            self.engine.transition(paper,'2.2','forwarded',{'excerpts':bundle['extracted_context']})
            if hasattr(self.real,'verify_materials'):bundle=self.real.verify_materials(paper,bundle)
            self.engine.transition(paper,'2.3','forwarded',{'materials':[{k:e.get(k) for k in ['evidence_id','url','status','format','columns','level','failure_reason']} for e in bundle['records'] if e['kind'] in {'file','api','repository','supplementary'}]})
            return validate_evidence(bundle)
        bundle=self.engine.cached(paper,'collected_evidence',gather)
        # A changed discovery list must not hide evidence already captured this round.
        bundle=copy.deepcopy(bundle)
        cache_folder=self.engine.session/'cache'/paper['paper_id']
        for path in sorted(cache_folder.glob(f'additional_discovery_*_{self.engine.round}.json')):
            wrapper=json.loads(path.read_text(encoding='utf-8'))
            if wrapper['sha256']!=digest(dump(wrapper['value']).encode()):raise ValueError('Additional discovery checkpoint changed')
            seen={e['evidence_id'] for e in bundle['records']}
            bundle['records'].extend(copy.deepcopy(e) for e in wrapper['value']['records'] if e['evidence_id'] not in seen)
            for coverage in wrapper['value'].get('search_coverage',[]):
                if coverage not in bundle.setdefault('search_coverage',[]):bundle['search_coverage'].append(copy.deepcopy(coverage))
        if isinstance(action,dict) and action.get('prior_evidence_ref'):
            prior=self.engine.store.read_ref(action['prior_evidence_ref'],self.engine.run_id,paper)
            bundle=copy.deepcopy(bundle)
            seen_ids={e['evidence_id'] for e in bundle['records']}
            for record in prior.get('records',[]):
                if record['evidence_id'] not in seen_ids:
                    item=copy.deepcopy(record);item['reused_from_prior_round']=True
                    bundle['records'].append(item);seen_ids.add(item['evidence_id'])
        observed={e['url'] for e in bundle['records']}
        additions=[x for x in paper.get('_review_discovery',[])[:8] if x['url'] not in observed or
                   (x.get('referer') and not any(e['url']==x['url'] and e.get('request_referer')==x['referer'] for e in bundle['records']))]
        if additions and hasattr(self.real,'additional_discovery'):
            def supplement():
                extended=self.real.additional_discovery(paper,bundle,additions)
                extended['extracted_context']=extract_context(extended)
                self.engine.transition(paper,'2.1','forwarded',{'additional_discovery':additions,'requests':len(extended['records'])})
                self.engine.transition(paper,'2.2','forwarded',{'excerpts':extended['extracted_context']})
                extended=self.real.verify_materials(paper,extended)
                self.engine.transition(paper,'2.3','forwarded',{'additional_discovery':additions})
                return validate_evidence(extended)
            bundle=self.engine.cached(paper,'additional_discovery_'+digest(dump(additions).encode()),supplement)
        if isinstance(self.real,FullWorkflowAccess) and paper.get('_official_verified') and paper['values'].get('PMCID'):
            from .pmc_cloud import collect_cloud
            def cloud_discovery():
                delta=collect_cloud(paper,self.real.request,bundle['records'])
                self.engine.transition(paper,'2.1','forwarded',{'PMC_cloud':delta['search_coverage'],
                    'captured_records':len(delta['records'])})
                return delta
            delta=self.engine.cached(paper,'pmc_cloud_2026_v1',cloud_discovery)
            seen={e['evidence_id'] for e in bundle['records']}
            bundle['records'].extend(copy.deepcopy(e) for e in delta['records'] if e['evidence_id'] not in seen)
            for coverage in delta['search_coverage']:
                if coverage not in bundle.setdefault('search_coverage',[]):bundle['search_coverage'].append(copy.deepcopy(coverage))
        if hasattr(self.real,'recover_truncated'):
            bundle=self.real.recover_truncated(paper,bundle)
            validate_evidence(bundle)
        if isinstance(self.real,FullWorkflowAccess):
            from .pmc_cloud import recover_cloud_materials
            bundle=recover_cloud_materials(paper,bundle)
            validate_evidence(bundle)
        # Reinspect downloaded DOCX bytes for unfinished reviews; retain immutable caches.
        from .full_workflow_access import inspect_material, recover_typographic_identity, recover_pdf_bytes, recover_json_metadata
        from urllib.parse import urlsplit
        bundle=copy.deepcopy(bundle)
        for record in bundle['records']:
            recover_json_metadata(paper,record)
            recover_pdf_bytes(paper,record)
            recover_typographic_identity(paper,record)
            if ((urlsplit(record.get('final_url','')).path.lower().endswith('.docx') and 'document_table_count' not in record)
                    or (urlsplit(record.get('final_url','')).path.lower().endswith('.zip') and ('archive_tables' not in record or record.get('status')=='fetch_error'))
                    or (urlsplit(record.get('final_url','')).path.lower().endswith(('.xlsx','.xls')) and 'workbook_preview' not in record)):
                inspect_material(record)
        validate_evidence(bundle)
        captures=self.engine.provider.entry(paper,policy).get('web_captures',[])
        if captures:
            from .web_capture import append_captures
            bundle=append_captures(self.engine.root,paper,bundle,captures)
            validate_evidence(bundle)
        bundle['extracted_context']=extract_context(bundle)
        return bundle


class FullWorkflow(VerifiedSelector):
    def __init__(self,*args,review_file,**kwargs):
        verifier=kwargs.pop('verifier',None) or OfficialMetadataVerifier()
        collector=kwargs.pop('collector',None) or FullWorkflowAccess(trace=kwargs.get('log'))
        super().__init__(*args,**kwargs)
        self.provider=SessionProvider(review_file,self)
        self.verifier=CachedVerifier(self,verifier);self.collector=CachedCollector(self,collector)
        self.round=1

    def cached(self,paper,kind,operation,round_number=None):
        number=self.round if round_number is None else round_number
        path=self.session/'cache'/paper['paper_id']/f'{kind}_{number}.json'
        if path.exists():
            wrapper=json.loads(path.read_text(encoding='utf-8'))
            if wrapper['sha256']!=digest(dump(wrapper['value']).encode()):raise ValueError('Checkpoint payload changed')
            return wrapper['value']
        value=operation()
        self.store.artifact(str(path.relative_to(self.root)),dict(sha256=digest(dump(value).encode()),value=value))
        return value

    def transition(self,paper,stage,outcome,details=None):
        key=digest(dump([self.run_id,paper['paper_id'],self.round,stage,outcome,details]).encode())
        path=self.session/'transitions'/(key+'.json')
        if path.exists():return
        value=dict(run_id=self.run_id,paper_id=paper['paper_id'],pmid=paper['pmid'],round=self.round,
                   stage=stage,outcome=outcome,timestamp=now(),details=details or {},unit='paper')
        self.store.artifact(str(path.relative_to(self.root)),value)
        self.store.event(self.run_id,'workflow.'+stage,paper['paper_id'],self.phase,outcome,details=value)
        events=[json.loads(row[0]) for row in self.store.db.execute(
            'SELECT details_json FROM events WHERE run_id=? AND step_id=? ORDER BY rowid',
            (self.run_id,'workflow.'+stage))]
        latest={e['paper_id']:e for e in events if e['round']==self.round and e['outcome']!='started'}
        counts=Counter(e['outcome'] for e in latest.values())
        prisma=dict(run_id=self.run_id,stage=stage,round=self.round,unit='paper',input_count=len(latest),
                    forwarded_count=counts['forwarded'],included_count=sum(e.get('details',{}).get('final',{}).get('status')=='confirmed' for e in latest.values()),
                    excluded_count=counts['excluded'],pending_count=counts['pending'],collection_error_count=counts['fetch_error'],
                    events=events,timestamp=now())
        assert prisma['input_count']==sum(prisma[k] for k in ['forwarded_count','excluded_count','pending_count','collection_error_count'])
        atomic_replace(self.session/'PRISMA'/f'round_{self.round}'/(stage+'.json'),dump(prisma))
        atomic_replace(self.session/'checkpoint.json',dump(value))
        self.log(f"{paper['paper_id']} round {self.round} stage {stage}: {outcome}")

    def prepare_save(self,r):
        r['tiab']['first_pass_state']='first_pass_pending' if r['tiab'].get('decision')=='pending_relevance' else r['tiab'].get('decision','excluded')
        r['revalidation']['auto_retry']=False if self.round>=2 or r['final']['status']!='pending' else True
        r['revalidation']['terminal']=(self.round>=2 or r['final']['status']!='pending') and r.get('processing_state')!='blocked_verification'
        r['revalidation']['workflow']='per_paper_0_1_2_3'

    def review_source(self,paper):
        missing=tiab_missing(paper,self.policy)
        self.transition(paper,'0','excluded' if missing else 'forwarded',{'missing_fields':missing})
        if missing:
            tiab=dict(availability='absent',decision='excluded',reason='TI/AB 부재: '+', '.join(missing),missing_fields=missing)
            code='TIAB_ABSENT'
        else:
            tiab=tiab_decision(self.provider.propose('tiab',paper,self.policy,{},None),paper)
            self.transition(paper,'1','excluded' if tiab['decision'] in {'E01','E02'} else 'forwarded',
                            {'state':'first_pass_pending' if tiab['decision']=='pending_relevance' else tiab['decision'],'proposal':tiab})
            if tiab['decision'] not in {'E01','E02'}:return None
            code=tiab['decision'];tiab=dict(tiab,availability='present')
        r=self.base_record(paper)
        r.update(tiab=tiab,final=dict(status='excluded',code=code,reason=tiab['reason']),
                 processing_state='reviewed',initial_review_valid=True,
                 metadata_verification={'status':'source_tiab_only','reason':'No Full Text access required for source TI/AB exclusion'})
        r['fulltext']['workflow']=[{'step':'decision','state':'excluded','code':code}]
        r['data_observations']=copy.deepcopy(tiab.get('data_observations',[]))
        self.prepare_save(r)
        self.event('2.2',paper['paper_id'],'excluded' if missing else 'forwarded',code if missing else '')
        if not missing:self.event('2.3',paper['paper_id'],'excluded',code)
        r=self.store.save(self.run_id,r,'initial');self.store.aggregate(self.run_id)
        return r

    def require_saved_terminal(self,paper,record):
        """Never advance the paper loop before a durable terminal decision."""
        saved=self.store.records(self.run_id).get(paper['paper_id'])
        if saved!=record or not saved:
            raise ValueError('Current paper result is not durably saved; next paper blocked')
        if (saved['final']['status'] not in {'confirmed','excluded','pending'}
                or not saved['revalidation'].get('terminal')
                or saved['revalidation'].get('auto_retry')
                or saved.get('processing_state')=='blocked_verification'):
            raise ValueError('Current paper verification is unfinished; next paper blocked')

    def source_scope(self,parent):
        parent_info=self.store.run(parent)
        ref=json.loads(parent_info['collect_ref']);manifest,allpapers,checked=load_collect(ref['path'],self.root.parent/'DB_Collect')
        if checked['sha256']!=ref['sha256']:raise ValueError('Collect manifest changed')
        original=json.loads(parent_info['input_json']);lookup={p['paper_id']:p for p in allpapers}
        if any(lookup.get(p['paper_id'])!=p for p in original):raise ValueError('Collect input changed')
        return manifest,original,ref

    def comparison_records(self,parent):return self.store.records(parent)

    def execute(self,parent,session_name,resume=None,render=False):
        with project_lock(self.root):
            manifest,original,ref=self.source_scope(parent)
            self.papers=sorted(original,key=paper_order);self.collect_run_id=manifest['run_id']
            self.policy=load_policy(self.policy_dir,self.organ)
            self.session=self.root/'Runs'/session_name
            header=self.session/'run.json'
            if header.exists():
                meta=json.loads(header.read_text(encoding='utf-8'));self.run_id=meta['run_id']
                if meta['parent_run_id']!=parent or self.store.run(self.run_id)['policy_json']!=dump(self.policy):raise ValueError('Resume context changed')
                if resume and resume!=self.run_id:raise ValueError('Resume run mismatch')
            else:
                if resume:raise ValueError('Resume checkpoint missing')
                # Archive derived aliases before the new run writes any projections.
                for folder in ['JSON','PRISMA','Output']:
                    for p in (self.root/folder).glob('*'):
                        if p.is_file() and not p.name.startswith('~$'):self.store.artifact(str((self.session/'baseline'/folder/p.name).relative_to(self.root)),p.read_bytes(),raw=True)
                self.run_id=self.store.create(manifest,ref,self.policy,self.papers)
                self.store.artifact(str(header.relative_to(self.root)),dict(run_id=self.run_id,parent_run_id=parent,created_at=now(),source_sha256=ref['sha256']))
            if hasattr(self.collector.real,'engine'):self.collector.real.engine=self
            try:
                if getattr(self,'progress_callback',None):self.progress_callback()
                for paper in self.papers:
                    r=self.store.records(self.run_id).get(paper['paper_id'])
                    if r and r['revalidation'].get('terminal') and r.get('processing_state')!='blocked_verification':
                        self.require_saved_terminal(paper,r)
                        continue
                    if not r:
                        self.round=1;self.phase='initial'
                        r=self.review_source(paper)
                        if r is None:r=self.review(paper)
                        self.transition(paper,'2.final' if r['tiab'].get('decision') in {'candidate','pending_relevance'} else 'final',
                                        {'confirmed':'forwarded','excluded':'excluded','pending':'pending'}[r['final']['status']],{'final':r['final']})
                    if r['final']['status']=='pending' and (not r['revalidation'].get('terminal') or r.get('processing_state')=='blocked_verification'):
                        self.round=2;self.phase='revalidation'
                        self.transition(paper,'3','started',{'previous':r['final']})
                        r=self.review(paper,r)
                        self.transition(paper,'3','pending' if r['final']['status']=='pending' else 'excluded' if r['final']['status']=='excluded' else 'forwarded',{'previous_code':self.store.records(self.run_id)[paper['paper_id']]['revalidation'].get('attempt_count'),'final':r['final'],'auto_retry':False})
                    self.require_saved_terminal(paper,r)
                    self.refresh(self.store.records(self.run_id))
                    if getattr(self,'progress_callback',None):self.progress_callback()
                    atomic_replace(self.session/'checkpoint.json',dump(dict(run_id=self.run_id,paper_id=paper['paper_id'],pmid=paper['pmid'],state='paper_saved',revision=r['revision'],timestamp=now())))
                records=self.store.records(self.run_id);self.qc(records);summary=self.refresh(records)
                self.store.set_status(self.run_id,summary['status'])
                export_path=self.export(records,render)
                old=self.comparison_records(parent)
                comparison=[{'paper_id':k,'pmid':r['pmid'],'before':old[k]['final'] if k in old else None,'after':r['final']} for k,r in records.items()]
                publication=uid()
                result=dict(run_id=self.run_id,parent_run_id=parent,counts=summary,comparison=comparison,manifest=export_path,publication_id=publication)
                self.store.artifact(str((self.session/'results'/f'{publication}.json').relative_to(self.root)),result)
                for folder in ['JSON','PRISMA','Output']:
                    for p in (self.root/folder).glob('*'):
                        if p.is_file() and not p.name.startswith('~$'):self.store.artifact(str((self.session/'published'/publication/folder/p.name).relative_to(self.root)),p.read_bytes(),raw=True)
                return result
            except ReviewRequired as exc:
                self.store.set_status(self.run_id,'AWAITING_REVIEW')
                saved=self.store.records(self.run_id)
                terminal=[r for r in saved.values() if r.get('processing_state')=='reviewed'
                          and r['revalidation'].get('terminal') and not r['revalidation'].get('auto_retry')]
                return {'run_id':self.run_id,'status':'AWAITING_REVIEW','request':str(exc),
                        'saved_count':len(saved),'terminal_count':len(terminal),
                        'terminal_outcomes':dict(Counter(r['final']['status'] for r in terminal))}
            except BaseException:
                self.store.set_status(self.run_id,'PARTIAL');raise


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--organ',required=True)
    p.add_argument('--parent',required=True);p.add_argument('--session',required=True);p.add_argument('--review-file',type=Path,required=True)
    p.add_argument('--resume');p.add_argument('--render',action='store_true')
    a=p.parse_args()
    if Path(a.session).name!=a.session or a.session in {'.','..'}:raise ValueError('Invalid session name')
    e=FullWorkflow(a.root,organ=a.organ,review_file=a.review_file,log=lambda s:print(s,flush=True))
    try:print(dump(e.execute(a.parent,a.session,a.resume,a.render)))
    finally:e.close()


if __name__=='__main__':main()
