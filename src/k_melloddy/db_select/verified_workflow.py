"""Default v2 workflow. Legacy immutable records remain readable/exportable."""
import copy,json,base64
from .engine import Selector
from .official_metadata import OfficialMetadataVerifier,verified_paper
from .access_workflow import AccessInvestigator,access_pending,STEPS
from .decision import tiab_decision,fulltext_decision
from .policy import tiab_missing
from .evidence_collector import validate_evidence
from .metadata import paper_order
from .prisma import summarize
from .schema import validate,RECORD
from ..core.storage import dump,now,uid,digest
from .data_observations import validate_observations,merge_observations,observation_evidence


class VerifiedSelector(Selector):
    def __init__(self,*args,verifier=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.verifier=verifier or OfficialMetadataVerifier()
        self.processing_order='asc'
        if kwargs.get('collector') is None:self.collector=AccessInvestigator()
    def base_record(self,paper,previous=None):
        r=super().base_record(paper,previous)
        r.update(workflow_version='2.0',verified_metadata={},metadata_verification={},
                 processing_state='in_progress',public_data_status='unverified')
        r['data_observations']=copy.deepcopy(previous.get('data_observations',[])) if previous else []
        return r
    def review(self,paper,previous=None):
        started_at=now()
        r=self.base_record(paper,previous);bundle=None;ref=None;step='2.1'
        try:
            check=self.verifier.verify(paper);r['metadata_verification']=check
            r['verified_metadata']=check.get('verified_metadata',{})
            self.store.document(self.run_id,paper,'evidence',{'metadata_verification':check})
            if check['status']!='verified':raise ValueError('공식 PMID 서지정보 검증 실패: 입력 DOI/PMCID로 원문 접근하지 않았습니다.')
            official=verified_paper(paper,check);official['_official_verified']=True
            official['_verified_authors']=check.get('official_authors',[])
            official['_source_sha256']=digest(dump(paper).encode())
            official['_known_data_names']=[x['name'] for x in r.get('data_observations',[])]
            if hasattr(self.provider,'discovery'):official['_review_discovery']=self.provider.discovery(official,self.policy)
            self.event('2.1',paper['paper_id'],'forwarded',details={'metadata_verified':True,'mismatches':check['mismatches']})
            # A changed title requires the reviewer to assess the official title, never the mismatched source.
            step='2.3'
            missing=tiab_missing(paper,self.policy)
            if missing:
                reason='TI/AB 부재: '+', '.join(missing)
                r['tiab']={'availability':'absent','decision':'excluded','reason':reason,'missing_fields':missing}
                r['final']={'status':'excluded','code':'TIAB_ABSENT','reason':reason}
            else:
                tiab=tiab_decision(self.provider.propose('tiab',official,self.policy,{},previous),official)
                r['tiab']=dict(tiab,availability='present')
                r['data_observations']=merge_observations(r['data_observations'],tiab.get('data_observations',[]))
                official['_known_data_names']=[x['name'] for x in r.get('data_observations',[])]
                if tiab['decision'] in {'candidate','pending_relevance'}:
                    if not tiab.get('exposure') or not tiab.get('toxicity_endpoint'):
                        raise ValueError('키워드 이외의 노출·장기독성 판단 근거가 필요합니다.')
                self.event('2.2',paper['paper_id'],'forwarded')
                self.event('2.3',paper['paper_id'],'excluded' if tiab['decision'] in {'E01','E02'} else 'forwarded',tiab['decision'])
                if tiab['decision'] in {'E01','E02'}:
                    r['final']={'status':'excluded','code':tiab['decision'],'reason':tiab['reason']}
                else:
                    action='initial'
                    if previous:
                        code=previous['final']['code']
                        prior=self.store.read_ref(previous['evidence_ref'],self.run_id,previous) if previous.get('evidence_ref') else {}
                        action={'phase':'revalidation','pending_code':code,
                            'tasks':self.policy['organ'].get('pending_revalidation',{}).get(code,[]),
                            'known_records':[{k:e.get(k) for k in ['url','kind','status','identity_match']} for e in prior.get('records',[])],
                            'previous_urls':previous['fulltext'].get('urls_checked',[]),
                            'prior_evidence_ref':previous.get('evidence_ref')}
                    step='2.4';bundle=validate_evidence(self.collector.collect(official,self.policy,action))
                    bundle['official_identity']={'pmid':paper['pmid'],'doi':r['verified_metadata'].get('DOI',''),'pmcid':r['verified_metadata'].get('PMCID','')}
                    if hasattr(self.provider,'review_evidence'):
                        bundle=validate_evidence(self.provider.review_evidence(official,self.policy,bundle,previous))
                    bundle['source_artifacts']=[]
                    for item in bundle['records']:
                        if item.get('body_sample_b64'):
                            a=self.store.artifact(f'FullText/{self.run_id}/{paper["paper_id"]}/{uid()}.response_sample',base64.b64decode(item['body_sample_b64']),raw=True)
                            bundle['source_artifacts'].append(dict(a,evidence_id=item['evidence_id']))
                    ref=self.store.document(self.run_id,paper,'evidence',bundle);r['evidence_ref']=ref
                    r['data_observations']=merge_observations(r['data_observations'],validate_observations(bundle.get('data_observations',[]),official,bundle))
                    self.event('2.4',paper['paper_id'],'forwarded' if bundle['fulltext_reviewed'] else 'pending',details={'evidence_ref':ref})
                    self.event('2.5',paper['paper_id'],'forwarded' if bundle['survey_complete'] else 'pending')
                    step='2.6'
                    try:
                        proposal=self.provider.propose('fulltext',official,self.policy,bundle,previous)
                    except ValueError:
                        proposal=None
                    if proposal is not None:
                        self.store.document(self.run_id,paper,'proposal',proposal)
                        if proposal['status'] in {'confirmed','excluded'}:
                            workflow={x['step']:x['state'] for x in bundle.get('workflow',[])}
                            required=['Methods','Data Availability','Supplementary','Repository']
                            if proposal['status']=='confirmed':required+=['data_file_or_api','toxicity_features']
                            if any(workflow.get(s) not in {'reviewed','verified','not_applicable_with_reason'} for s in required):
                                raise ValueError('원문·부록·저장소·데이터 검증 순서의 실제 검토 기록이 누락되었습니다.')
                        if proposal['status']=='pending' and proposal['code']=='P02' and not access_pending(bundle):
                            raise ValueError('P02에는 복수 접근 경로·재시도·대체 검색 기록이 필요합니다.')
                        proposal=fulltext_decision(proposal,bundle)
                    elif previous and previous['final']['code'] in {'P01','P03','P04'}:
                        raise ValueError('기존 P코드를 해제하거나 변경할 새 자료 검증 근거가 부족합니다.')
                    elif access_pending(bundle):
                        failures=sorted({e.get('failure_reason','') for e in bundle['records'] if e['kind']=='fulltext' and e['status']!='accessible'})
                        proposal={'status':'pending','code':'P02',
                            'reason':'공식 서지정보 확인 후 PMC/출판사 및 정확한 PMID·제목으로 대체 경로를 조사하고 재시도했으나 본문 접근 검증을 끝내지 못했습니다. 원인: '+', '.join(failures),
                            'conditions':dict.fromkeys(['relevance','actual_data','direct_path','structure','independent'],False),
                            'evidence_refs':[],'datasets':[],'source_databases':[],
                            'what_confirmed':['공식 PMID 서지정보 및 복수 원문 경로·재시도·대체검색 확인'],
                            'what_unresolved':['Methods/Data Availability/부록/저장소/실제 파일의 검증 미완료'],
                            'next_verification_action':'합법적 기관 원문 또는 공개 저자 원고와 별도 부록 경로를 다시 조사합니다.'}
                        if bundle['fulltext_reviewed']:
                            proposal.update(reason='공식 PMC XML 원문과 Methods/Results를 확인했습니다. 출판사 접근 제한으로 별도 Supplementary 확인은 완료하지 못했으며 독립 공개 데이터/파일 검증이 남아 있어 P02를 유지합니다.',
                                what_confirmed=['동일 PMID·DOI의 공식 PMC 원문 및 제출된 절별 검토 근거 확인'],
                                what_unresolved=['출판사 별도 Supplementary 및 독립 공개 데이터/파일 검증 미완료'])
                        from .access_workflow import unlocated_fulltext
                        if unlocated_fulltext(bundle):
                            proposal['reason']='공식 서지정보에 DOI·PMCID가 없고, PubMed 및 정확한 PMID·제목의 대체 검색과 학술 색인 조사 후에도 검토 가능한 원문 경로를 확보하지 못했습니다. P02로 보류하며 데이터 비공개 또는 부재로 판정하지 않습니다.'
                    else:
                        raise ValueError('접근 기록 또는 본문·데이터 검토가 부족하여 판정 검증이 아직 완료되지 않았습니다.')
                    r['final']={k:proposal[k] for k in ['status','code','reason']}
                    r['data_observations']=merge_observations(r['data_observations'],proposal.get('data_observations',[]))
                    self.event('2.6',paper['paper_id'],{'confirmed':'forwarded','excluded':'excluded','pending':'pending'}[proposal['status']],proposal['code'])
                    r['datasets']=proposal['datasets'];r['source_databases']=proposal['source_databases']
                    r['fulltext']=dict(status='reviewed' if bundle['fulltext_reviewed'] else 'access_investigated',
                        conditions=proposal['conditions'],evidence=proposal['evidence_refs'],
                        what_confirmed=proposal['what_confirmed'],what_unresolved=proposal['what_unresolved'],
                        next_verification_action=proposal['next_verification_action'],workflow=bundle.get('workflow',[]),
                        urls_checked=[e['url'] for e in bundle['records']],sections_checked=bundle['sections_checked'])
                    if r['final']['status']=='confirmed':r['public_data_status']='verified'
            r['processing_state']='reviewed'
            r['initial_review_valid']=True
        except (ValueError,RuntimeError,OSError,KeyError,TypeError) as exc:
            # Conservative administrative hold; never a scientific exclusion or a claim of completed access investigation.
            self.event(step,paper['paper_id'],'fetch_error','METADATA_VERIFICATION_ERROR' if step=='2.1' else 'WORKFLOW_INCOMPLETE',{'error_type':type(exc).__name__,'reason':str(exc)})
            r['processing_state']='blocked_verification'
            r['final']={'status':'pending','code':previous['final']['code'] if previous else 'P02','reason':'검증 작업 보류(재검증 필요): '+str(exc)}
            r['fulltext'].update(status='verification_blocked',next_verification_action='공식 메타데이터·원문 접근 및 검수 입력을 복구하고 재검증합니다.')
            r['initial_review_valid']=True;r['datasets']=[]
        if bundle and bundle.get('collector')=='targeted-independent-revalidation-v1':
            from .revalidation_access import verification_state
            r['fulltext']['verification_state']=verification_state(paper,bundle,r)
        if getattr(self,'captured_review_sha256',None):
            if 'verification_state' not in r['fulltext']:
                from .revalidation_access import verification_state
                r['fulltext']['verification_state']=verification_state(paper,bundle,r)
            r['fulltext'].setdefault('verification_state',{})['captured_review_sha256']=self.captured_review_sha256
            r['fulltext']['verification_state']['review_mode']='human_review_of_captured_evidence'
        if previous:
            first=self.store.db.execute('SELECT record_json FROM revisions WHERE run_id=? AND paper_id=? ORDER BY revision LIMIT 1',(self.run_id,paper['paper_id'])).fetchone()
            initial=json.loads(first[0])
            history={'paper_id':paper['paper_id'],'pmid':paper['pmid'],'attempt_no':previous['revalidation']['attempt_count']+1,
                'started_at':started_at,'ended_at':now(),
                'initial_p_code':initial['final']['code'],'initial_result':initial['final'],
                'initial_timestamp':initial['provenance']['review_timestamp'],
                'revalidation_completed':r['processing_state']=='reviewed',
                'verification_resolved':r['final']['status'] in {'confirmed','excluded'},
                'decision_changed':r['final']!=previous['final'],
                'final_reason':r['final']['reason'],
                'unresolved_reason':r['final']['reason'] if r['final']['status']=='pending' else '',
                'access_results':[{k:e.get(k) for k in ['url','final_url','kind','route','attempt','timestamp','status','http_status','failure_reason','identity_match','reused_from_prior_round']} for e in bundle['records']] if bundle else [],
                'search_coverage':bundle.get('search_coverage',[]) if bundle else [{'target':'Full Text / Supplementary / Repository','state':'not_required_TIAB_excluded' if r['final']['status']=='excluded' else 'blocked'}],
                'attempt_timestamp':now(),'previous_result':previous['final'],'result':r['final'],
                'metadata_verification':r['metadata_verification'],
                'urls_checked':[e['url'] for e in bundle['records']] if bundle else [],
                'evidence_ref':ref,'what_confirmed':r['fulltext'].get('what_confirmed',[]),
                'what_unresolved':r['fulltext'].get('what_unresolved',[]),
                'next_verification_action':r['fulltext'].get('next_verification_action','')}
            if 'verification_state' in r['fulltext']:
                history.update(r['fulltext']['verification_state'])
                history.update(internal_id=paper_order(paper)[1],previous_decision=previous['final']['status'],
                    previous_code=previous['final']['code'],final_decision=r['final']['status'],final_code=r['final']['code'],
                    status='completed' if r['processing_state']=='reviewed' else 'blocked')
            if getattr(self,'campaign_id',None):history['campaign_id']=self.campaign_id
            h=self.store.document(self.run_id,paper,'revalidation',history)
            r['revalidation']={'attempt_count':history['attempt_no'],'history_refs':previous['revalidation']['history_refs']+[h]}
        r['fulltext'].setdefault('workflow',[{'step':s,'state':'not_required_TIAB_excluded' if r['final']['status']=='excluded' else 'blocked'} for s in STEPS])
        r['fulltext']['workflow'].append({'step':'decision','state':r['final']['status'],'code':r['final']['code']})
        if hasattr(self,'prepare_save'):self.prepare_save(r)
        saved=self.store.save(self.run_id,r,self.phase);self.store.aggregate(self.run_id)
        return saved
    def qc(self,records):
        current={k:v for k,v in records.items() if v.get('workflow_version')=='2.0'}
        if len(current)!=len(records):return super().qc(records)
        expected={(p['paper_id'],p['pmid']) for p in self.papers}
        if {(r['paper_id'],r['pmid']) for r in records.values()}!=expected:raise ValueError('Missing/extra final paper')
        for r in records.values():
            validate(r,RECORD)
            validate_observations(r.get('data_observations',[]),r['source_record'],observation_evidence(self.store,self.run_id,r))
            if r['provenance']['policy_sha256']!=self.policy['sha256']:raise ValueError('Policy snapshot mismatch')
            if r['final']['status']=='excluded' and r['final']['code'] not in {'ABSTRACT_ABSENT','TIAB_ABSENT',*[f'E{i:02}' for i in range(1,9)]}:raise ValueError('Missing exclusion code')
            if r['final']['status']=='confirmed' and (r['final']['code'] or not r['datasets']):raise ValueError('Confirmed dataset missing')
            if (r['final']['status']=='confirmed' or (r['final']['status']=='excluded' and r['final']['code'] not in {'E01','E02','ABSTRACT_ABSENT','TIAB_ABSENT'})) and not r.get('evidence_ref'):raise ValueError('Full-text evidence missing')
            if r['final']['status']=='confirmed':
                registered={row[0] for row in self.store.db.execute('SELECT dataset_id FROM mappings WHERE run_id=? AND paper_id=? AND revision=?',(self.run_id,r['paper_id'],r['revision']))}
                if registered!={d['dataset_id'] for d in r['datasets']}:raise ValueError('Confirmed dataset mapping mismatch')
            if len(r['revalidation']['history_refs'])!=r['revalidation']['attempt_count']:raise ValueError('Revalidation count mismatch')
            for history_ref in r['revalidation']['history_refs']:self.store.read_ref(history_ref,self.run_id,r,'revalidation')
            if r['final']['status'] not in {'confirmed','excluded','pending'}:raise ValueError('Invalid final decision')
            if r['final']['status']=='pending' and r['final']['code'] not in {'P01','P02','P03','P04'}:raise ValueError('Missing pending code')
            source_gate=r['metadata_verification'].get('status')=='source_tiab_only'
            if source_gate:
                if r['final']['status']!='excluded' or r['final']['code'] not in {'E01','E02','TIAB_ABSENT'}:raise ValueError('Invalid source-only gate')
                if r['final']['code']=='TIAB_ABSENT':
                    missing=[k for k in ['Title','Abstract'] if not r['source_record']['values'].get(k,'').strip()]
                    if not missing or missing!=r['tiab'].get('missing_fields'):raise ValueError('Unsupported TI/AB absence')
                else:tiab_decision({k:v for k,v in r['tiab'].items() if k not in {'availability','first_pass_state'}},r['source_record'])
            if r['final']['status']!='pending' and not source_gate and r['metadata_verification'].get('status')!='verified':raise ValueError('Official metadata gate failed')
            if r['verified_metadata'] and r['verified_metadata']['PMID']!=r['pmid']:raise ValueError('Official PMID changed')
            check=r['metadata_verification']
            if check.get('response_xml'):
                from .official_metadata import parse_official
                raw=check['response_xml'].encode('utf-8')
                if digest(raw)!=check['response_sha256'] or parse_official(raw,r['pmid'])!=r['verified_metadata']:
                    raise ValueError('Official metadata response/hash mismatch')
            if r.get('evidence_ref'):
                bundle=validate_evidence(self.store.read_ref(r['evidence_ref'],self.run_id,r))
                bundle['official_identity']={'pmid':r['pmid'],'doi':r['verified_metadata'].get('DOI',''),'pmcid':r['verified_metadata'].get('PMCID','')}
                if r['final']['status']=='confirmed' or (r['final']['status']=='excluded' and r['final']['code'] not in {'E01','E02','ABSTRACT_ABSENT','TIAB_ABSENT'}):
                    from .schema import DATASET
                    ft=r['fulltext']
                    fulltext_decision(dict(status=r['final']['status'],code=r['final']['code'],reason=r['final']['reason'],
                        conditions=ft['conditions'],evidence_refs=ft['evidence'],datasets=[{k:d[k] for k in DATASET['properties']} for d in r['datasets']],
                        what_confirmed=ft['what_confirmed'],what_unresolved=ft['what_unresolved'],next_verification_action=ft['next_verification_action'],source_databases=r['source_databases']),bundle)
                for a in bundle.get('source_artifacts',[]):
                    if digest((self.root/a['path']).read_bytes())!=a['sha256']:raise ValueError('Evidence sample hash mismatch')
                if r['final']['status']=='pending' and r['final']['code']=='P02' and r['processing_state']=='reviewed' and not access_pending(bundle):raise ValueError('Single-route P02 is prohibited')
            self.event('2.11',r['paper_id'],'forwarded',details={'final':r['final'],'processing_state':r['processing_state']},phase='qc')
        counts=summarize(self.papers,records)
        if counts['N_confirmed']+counts['N_excluded']+counts['N_pending']!=len(self.papers):raise ValueError('Final partition incomplete')
        from .persistence import atomic_replace
        atomic_replace(self.root/'PRISMA/qc.json',dump(dict(checks='passed',**counts)))
