import json
import copy
import base64
from pathlib import Path
from ..core.storage import digest,dump,now,uid
from ..db_collect.engine import project_lock
from .metadata import load_collect,paper_order
from .policy import load_policy,PENDING
from .llm_adapter import load_provider,UnconfiguredProvider
from .evidence_collector import HttpEvidenceCollector,validate_evidence
from .decision import tiab_decision,fulltext_decision
from .persistence import SelectionStore
from .revalidator import initial_complete,eligible,valid_initial
from .prisma import write_prisma,summarize
from .schema import validate,RECORD


class Selector:
    def __init__(self,root,policy_dir='config/db_select',organ='Heart',provider=None,collector=None,log=None):
        self.root=Path(root); self.policy_dir=Path(policy_dir); self.organ=organ
        self.provider=provider; self.collector=collector or HttpEvidenceCollector()
        self.store=SelectionStore(root); self.log=log or (lambda text:None)
    def close(self): self.store.close()
    def status(self):
        return [dict(r) for r in self.store.db.execute('SELECT run_id,status,created_at FROM runs ORDER BY created_at')]
    def event(self,step,paper,outcome,code='',details=None,phase=None):
        self.store.event(self.run_id,step,paper,phase or self.phase,outcome,code,details)
        self.log(f'{paper} {step} {outcome} {code} saved')
    def validate(self,manifest_path):
        manifest,papers,ref=load_collect(manifest_path,self.root.parent/'DB_Collect')
        policy=load_policy(self.policy_dir,self.organ)
        return {'status':'VALIDATED','paper_count':len(papers),'collect_run_id':manifest['run_id'],'policy_sha256':policy['sha256'],'provider':policy['rules']['provider']}
    def run(self,manifest_path=None,resume=None,revalidate_only=False,export=True,render=False,limit=None,order='asc',additional_pass=False,revalidate_ids=None):
        if additional_pass and not (resume and revalidate_only):raise ValueError('Additional pass requires explicit revalidation of an existing run')
        if revalidate_ids and not (resume and revalidate_only):raise ValueError('Paper filter is only valid for revalidation')
        with project_lock(self.root):
            if resume:
                info=self.store.run(resume); self.run_id=resume
                self.policy=json.loads(info['policy_json']); self.papers=json.loads(info['input_json'])
                ref=json.loads(info['collect_ref'])
                if digest(Path(ref['path']).read_bytes())!=ref['sha256']:raise ValueError('Collect manifest changed')
                manifest,checked,_=load_collect(ref['path'],self.root.parent/'DB_Collect')
                scope=ref.get('selection',{})
                checked=sorted(checked,key=paper_order,reverse=scope.get('order','asc')=='desc')[:scope.get('limit')]
                if checked!=self.papers:raise ValueError('Frozen input changed')
            else:
                if revalidate_only:raise ValueError('Revalidation requires --resume RUN_ID')
                if not manifest_path:raise ValueError('Set Input/collect_manifest.txt or --manifest')
                manifest,self.papers,ref=load_collect(manifest_path,self.root.parent/'DB_Collect')
                if order not in {'asc','desc'} or (limit is not None and (type(limit)!=int or limit<1)):
                    raise ValueError('Invalid selection order/limit')
                ref['selection']={'order':order,'limit':limit,'source_count':len(self.papers),
                    'collect_status':manifest['status'],'collect_downstream_ready':manifest.get('downstream_ready',False)}
                self.papers=sorted(self.papers,key=paper_order,reverse=order=='desc')[:limit]
                self.policy=load_policy(self.policy_dir,self.organ)
            # Fail before creating any purported review run if no model is connected.
            if self.provider is None:self.provider=load_provider(self.policy['rules']['provider'])
            if isinstance(self.provider,UnconfiguredProvider):raise ValueError('LLM provider is not configured')
            if not resume:self.run_id=self.store.create(manifest,ref,self.policy,self.papers)
            self.collect_run_id=manifest['run_id']; self.phase='initial'
            try:
                records=self.store.records(self.run_id)
                execution_before={k:(r['final']['status'],r['revalidation']['attempt_count']) for k,r in records.items()}
                self.store.aggregate(self.run_id)
                if not revalidate_only:
                    for paper in sorted(self.papers,key=paper_order) if getattr(self,'processing_order',None)=='asc' else self.papers:
                        previous=records.get(paper['paper_id'])
                        if previous and valid_initial(previous):
                            continue
                        if getattr(self,'processing_order',None)!='asc':
                            self.event('2.1',paper['paper_id'],'forwarded',details={'pmid':paper['pmid']})
                        records[paper['paper_id']]=self.review(paper)
                        self.refresh(records)
                complete=initial_complete(self.papers,records)
                for paper in self.papers:
                    self.event('2.8',paper['paper_id'],'forwarded' if records.get(paper['paper_id'],{}).get('initial_review_valid') else 'fetch_error')
                if complete:
                    self.phase='revalidation'
                    automatic_attempts=self.policy['rules'].get('automatic_revalidation_attempts',1)
                    for pass_no in range(1 if revalidate_only else automatic_attempts):
                        selected=eligible(records,self.policy['rules']['max_revalidation_attempts'],automatic=not revalidate_only,additional_pass=additional_pass,automatic_attempts=automatic_attempts)
                        if revalidate_ids:
                            if set(revalidate_ids)-{p['paper_id'] for p in self.papers}:raise ValueError('Unknown paper ID in revalidation filter')
                            selected=[r for r in selected if r['paper_id'] in revalidate_ids]
                        if not selected:break
                        lookup={p['paper_id']:p for p in self.papers}
                        for previous in selected:
                            self.event('2.9',previous['paper_id'],'started',details={'explicit_additional_pass':additional_pass,'previous_attempt_count':previous['revalidation']['attempt_count'],'pass_no':pass_no+1})
                            records[previous['paper_id']]=self.review(lookup[previous['paper_id']],previous)
                            self.refresh(records)
                self.qc(records)
                result=self.refresh(records)
                if export:
                    result['manifest']=self.export(records,render)
                self.store.set_status(self.run_id,result['status'])
                result['this_execution']={
                    'initial_processed_count':len(set(records)-set(execution_before)),
                    'revalidation_attempt_count':sum(r['revalidation']['attempt_count']-execution_before.get(k,('',0))[1] for k,r in records.items()),
                    'converted_to_included_count':sum(execution_before.get(k,('',0))[0]=='pending' and r['final']['status']=='confirmed' for k,r in records.items()),
                    'converted_to_excluded_count':sum(execution_before.get(k,('',0))[0]=='pending' and r['final']['status']=='excluded' for k,r in records.items())}
                return dict(result,run_id=self.run_id)
            except BaseException:
                self.store.set_status(self.run_id,'PARTIAL'); raise
    def base_record(self,paper,previous=None):
        return dict(schema_version='1.0',run_id=self.run_id,collect_run_id=self.collect_run_id,paper_id=paper['paper_id'],
            data_observations=copy.deepcopy(previous.get('data_observations',[])) if previous else [],
            pmid=paper['pmid'],organ=self.organ,tiab={},fulltext={},final={'status':'fetch_error','code':'','reason':'Review not completed'},
            datasets=[],source_databases=[],revalidation=(dict(previous['revalidation']) if previous else {'attempt_count':0,'history_refs':[]}),
            provenance=dict(organ_policy_version=self.policy['organ']['version'],policy_sha256=self.policy['sha256'],
                prompt_version=self.policy['rules']['prompt_version'],model_provider=self.provider.name,model_name=self.provider.model,review_timestamp=now()),
            initial_review_valid=False,evidence_ref=None,source_record=paper,revision=1)
    def review(self,paper,previous=None):
        r=self.base_record(paper,previous); step='2.2'; bundle=None; proposal=None; attempted_evidence_ref=None
        try:
            if paper['fetch_state']!='available' or not paper['values']['Title']:
                raise ValueError('Source metadata fetch failure or missing title; recollect required')
            if paper['abstract_state']=='abstract_absent' and not paper['values']['Abstract']:
                r['tiab']={'availability':'abstract_absent','decision':'excluded','reason':'PubMed source has no Abstract'}
                r['final']={'status':'excluded','code':'ABSTRACT_ABSENT','reason':'PubMed 원본 Abstract 부재'}
                r['initial_review_valid']=True
                self.event(step,paper['paper_id'],'excluded','ABSTRACT_ABSENT')
            else:
                if not paper['values']['Abstract']:raise ValueError('Abstract empty but absence not verified in source')
                self.event(step,paper['paper_id'],'forwarded')
                step='2.3'
                tiab=tiab_decision(self.provider.propose('tiab',paper,self.policy,{},previous),paper)
                r['tiab']=dict(tiab,availability='present')
                from .data_observations import merge_observations
                r['data_observations']=merge_observations(r['data_observations'],tiab.get('data_observations',[]))
                if tiab['decision'] in {'E01','E02'}:
                    if previous:raise ValueError('Pending revalidation cannot replace Full Text review with a new TIAB exclusion')
                    r['final']={'status':'excluded','code':tiab['decision'],'reason':tiab['reason']};r['initial_review_valid']=True
                    self.event(step,paper['paper_id'],'excluded',tiab['decision'])
                else:
                    self.event(step,paper['paper_id'],'forwarded',tiab['decision'])
                    step='2.4'
                    action=PENDING[previous['final']['code']] if previous else ''
                    bundle=validate_evidence(self.collector.collect(paper,self.policy,action))
                    bundle['source_artifacts']=[]
                    for item in bundle['records']:
                        if item.get('body_sample_b64'):
                            ref=self.store.artifact(f'FullText/{self.run_id}/{paper["paper_id"]}/{uid()}.response_sample',
                                base64.b64decode(item['body_sample_b64'],validate=True),raw=True)
                            bundle['source_artifacts'].append(dict(ref,evidence_id=item['evidence_id']))
                    r['evidence_ref']=self.store.document(self.run_id,paper,'evidence',bundle)
                    attempted_evidence_ref=r['evidence_ref']
                    self.event(step,paper['paper_id'],'forwarded' if bundle['fulltext_reviewed'] else 'pending',details={'evidence_ref':r['evidence_ref']})
                    step='2.5'
                    self.event(step,paper['paper_id'],'forwarded' if bundle['supplementary_checked'] and bundle['repository_checked'] else 'pending',details={'sections_checked':bundle['sections_checked']})
                    step='2.6'
                    raw=self.provider.propose('fulltext',paper,self.policy,bundle,previous)
                    self.store.document(self.run_id,paper,'proposal',raw)
                    proposal=fulltext_decision(raw,bundle)
                    self.event(step,paper['paper_id'],'forwarded' if proposal['status']=='confirmed' else 'pending' if proposal['status']=='pending' else 'excluded',proposal['code'])
                    r['datasets']=proposal['datasets'];r['source_databases']=proposal['source_databases']
                    r['data_observations']=merge_observations(r['data_observations'],proposal.get('data_observations',[]))
                    r['fulltext']=dict(status='reviewed' if bundle['fulltext_reviewed'] else 'access_investigated',
                        conditions=proposal['conditions'],
                        sections_checked=bundle['sections_checked'],urls_checked=[e['url'] for e in bundle['records']],
                        evidence=proposal['evidence_refs'],what_confirmed=proposal['what_confirmed'],what_unresolved=proposal['what_unresolved'],
                        next_verification_action=proposal['next_verification_action'],
                        **{k:[e['url'] for e in bundle['records'] if e['kind'] in kinds] for k,kinds in
                           [('fulltext_urls',{'fulltext'}),('supplementary_urls',{'supplementary'}),('repository_urls',{'repository','landing'})]})
                    r['final']={k:proposal[k] for k in ['status','code','reason']}
                    r['initial_review_valid']=True
            step='2.7'
            # Final decision event is committed atomically with the record below.
        except (ValueError,RuntimeError,OSError,KeyError,TypeError) as exc:
            # Provider/network failures are not final exclusion decisions.
            self.event(step,paper['paper_id'],'fetch_error','REVIEW_ERROR',{'error_type':type(exc).__name__})
            r['final']={'status':'fetch_error','code':'','reason':f'{step}: {type(exc).__name__}: review/evidence validation failed; inspect the immutable proposal and evidence at this step'}
            from .submitted_review import ReviewIncomplete
            if isinstance(exc,ReviewIncomplete):r['final']['reason']=str(exc)
            r['datasets']=[]
            if previous:
                # Preserve a legitimate pending decision after a failed revalidation.
                r=json.loads(dump(previous));r['provenance']['review_timestamp']=now()
                r['fulltext']['last_revalidation_error']=type(exc).__name__
        if previous:
            attempt=previous['revalidation']['attempt_count']+1
            history=dict(paper_id=paper['paper_id'],pmid=paper['pmid'],attempt_no=attempt,attempt_timestamp=now(),
                what_confirmed=r['fulltext'].get('what_confirmed',[]),what_unresolved=r['fulltext'].get('what_unresolved',[]),
                urls_checked=[e['url'] for e in bundle['records']] if bundle else [],
                next_verification_action=r['fulltext'].get('next_verification_action',PENDING[previous['final']['code']]),
                result=r['final'],evidence_ref=attempted_evidence_ref,error=r['fulltext'].get('last_revalidation_error'))
            ref=self.store.document(self.run_id,paper,'revalidation',history)
            r['revalidation']={'attempt_count':attempt,'history_refs':previous['revalidation']['history_refs']+[ref]}
            # 2.9 is committed together with the new revision.
        saved=self.store.save(self.run_id,r,self.phase)
        self.store.aggregate(self.run_id)
        return saved
    def refresh(self,records):
        self.store.aggregate(self.run_id)
        summary,_=write_prisma(self.store,self.run_id,self.policy,self.papers,records,uid())
        return summary
    def qc(self,records):
        for p in self.papers:
            r=records.get(p['paper_id'])
            if not r: continue
            validate(r,RECORD)
            if r['pmid']!=p['pmid'] or r['paper_id']!=p['paper_id']:raise ValueError('Identity mutation')
            status,code=r['final']['status'],r['final']['code']
            if status=='confirmed' and (not r['datasets'] or not r['initial_review_valid']):raise ValueError('Confirmed mapping missing')
            if status=='excluded' and code not in {'ABSTRACT_ABSENT',*[f'E{i:02}' for i in range(1,9)]}:raise ValueError('Exclusion code missing')
            if status=='pending' and code not in PENDING:raise ValueError('Pending code missing')
            if r['provenance']['policy_sha256']!=self.policy['sha256']:raise ValueError('Policy snapshot mismatch')
            for ref in ([r['evidence_ref']] if r.get('evidence_ref') else [])+r['revalidation']['history_refs']:
                self.store.read_ref(ref,self.run_id,r)
            if status in {'confirmed','pending'} or (status=='excluded' and code not in {'E01','E02','ABSTRACT_ABSENT'}):
                if not valid_initial(r):raise ValueError('Initial Full Text investigation invalid')
                evidence=validate_evidence(self.store.read_ref(r['evidence_ref'],self.run_id,r,'evidence'))
                for raw_ref in evidence.get('source_artifacts',[]):
                    path=(self.root/raw_ref['path']).resolve()
                    if not path.is_relative_to(self.root.resolve()) or digest(path.read_bytes())!=raw_ref['sha256']:
                        raise ValueError('Raw evidence sample hash mismatch')
                ft=r['fulltext']
                from .schema import DATASET
                verified=fulltext_decision(dict(status=status,code=code,reason=r['final']['reason'],
                    conditions=ft['conditions'],evidence_refs=ft['evidence'],
                    datasets=[{k:d[k] for k in DATASET['properties']} for d in r['datasets']],
                    what_confirmed=ft['what_confirmed'],what_unresolved=ft['what_unresolved'],
                    next_verification_action=ft['next_verification_action'],source_databases=r['source_databases']),evidence)
            self.event('2.11',p['paper_id'],'fetch_error' if status=='fetch_error' else 'forwarded',details={'decision':status,'code':code},phase='qc')
        from .persistence import atomic_replace
        atomic_replace(self.root/'PRISMA/qc.json',dump(dict(checks='passed',**summarize(self.papers,records))))
    def export(self,records=None,render=False):
        from .excel_export import export
        records=self.store.records(self.run_id)
        self.qc(records); snapshot=uid()
        ref=export(self.store,self.run_id,self.policy,self.papers,records,snapshot,render)
        return str(self.root/ref['path'])
    def export_run(self,run,render=False):
        with project_lock(self.root):
            info=self.store.run(run);self.run_id=run;self.policy=json.loads(info['policy_json']);self.papers=json.loads(info['input_json']);self.phase='export'
            try:return self.export(render=render)
            except BaseException:
                self.store.set_status(run,'PARTIAL');raise
