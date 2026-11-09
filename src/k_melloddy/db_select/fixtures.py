"""Synthetic selection scenarios. None of these are research findings."""
import copy
import base64
from pathlib import Path
from ..core.storage import digest,now
from ..db_collect.config import init_project
from ..db_collect.engine import Collector
from ..db_collect.fake import FakeClient
from .documentation import project_docs
from .engine import Selector
from .llm_adapter import FixtureProvider
from .evidence_collector import FixtureEvidenceCollector


class SelectCollectClient(FakeClient):
    def fetch(self,pmids):
        return ('<PubmedArticleSet>'+''.join(
            f'<PubmedArticle><MedlineCitation><PMID>{p}</PMID><Article><ArticleTitle>SYNTHETIC selection paper {p}</ArticleTitle>'
            '<Abstract><AbstractText>SYNTHETIC drug toxicity data for testing only.</AbstractText></Abstract>'
            '</Article></MedlineCitation></PubmedArticle>' for p in pmids)+'</PubmedArticleSet>').encode()


def evidence_record(eid,kind='fulltext',text=None,url=None):
    text=text or 'SYNTHETIC Methods Results Data Availability. Independent drug toxicity dataset. drug endpoint value. No additional public dataset.'
    return dict(evidence_id=eid,url=url or f'https://fixture.invalid/{eid}',final_url=url or f'https://fixture.invalid/{eid}',
        kind=kind,timestamp=now(),status='accessible',http_status=200,text=text,payload_sha256=digest(text.encode()),
        bytes_observed=len(text.encode()),complete_body=True,level='sample_structure' if kind=='file' else 'response_sample',
        identity_match=kind=='fulltext',sections=['Methods','Results','Data Availability'] if kind=='fulltext' else [],
        format='text/csv' if kind=='file' else 'text/html',columns=['drug','endpoint','value'] if kind=='file' else [],
        downloaded_full_dataset=False,body_sample_b64=base64.b64encode(text.encode()).decode('ascii'))


def scenario(status='confirmed',code='',*,two_datasets=False):
    ft=evidence_record('ft'); file=evidence_record('data','file',url='https://fixture.invalid/data.csv')
    repo=evidence_record('repo','repository',url='https://fixture.invalid/repository')
    bundle=dict(records=[ft,repo,file],fulltext_reviewed=True,sections_checked=['Methods','Results','Data Availability'],
        supplementary_checked=True,repository_checked=True,survey_complete=True,collector='synthetic-fixture-v1')
    refs=[{'evidence_id':'ft','quote':'Independent drug toxicity dataset.'}]
    proposal=dict(status=status,code=code,reason='SYNTHETIC scenario: '+(code or status),evidence_refs=refs,
        conditions={k:True for k in ['relevance','actual_data','direct_path','structure','independent']},datasets=[],
        what_confirmed=['SYNTHETIC data clue'],what_unresolved=['Synthetic verification task'] if status=='pending' else [],
        next_verification_action='Inspect the specified synthetic evidence' if status=='pending' else '',source_databases=[])
    dataset=dict(name='SYNTHETIC dataset',identity='doi:10.9999/synthetic-data',version='v1',direct_url=file['url'],evidence_id='data',
        drug_identifier='drug',endpoint='endpoint',value_field='value',independence_reason='Independent curated synthetic data',
        evidence_refs=refs,feature_count=None,compound_count=None)
    tiab=dict(decision='candidate',reason='Synthetic source supports this fixture branch',quote='SYNTHETIC drug toxicity data for testing only.')
    if code in {'E01','E02'}:tiab['decision']=code
    if status=='confirmed':
        proposal['datasets']=[dataset]
        if two_datasets:
            other=copy.deepcopy(dataset);other.update(name='SYNTHETIC second dataset',identity='accession:fixture:second')
            proposal['datasets'].append(other)
    if code=='E07':proposal['source_databases']=[{'name':'Synthetic reused DB','url':repo['url'],'evidence_refs':[{'evidence_id':'repo','quote':'SYNTHETIC'}]}]
    if code=='P02':
        bundle['fulltext_reviewed']=False;bundle['sections_checked']=[]
        restricted=[]
        for i,url in enumerate(['https://publisher.invalid/blocked','https://pmc.invalid/blocked']):
            e=evidence_record('blocked'+str(i),url=url);e.update(status='access_restricted',http_status=403,text='',payload_sha256=None,bytes_observed=0,identity_match=False,body_sample_b64=None)
            restricted.append(e)
        bundle['records']=restricted;proposal['evidence_refs']=[]
    if code=='P03':
        bundle['records']=[ft,repo]
        proposal['evidence_refs']=[{'evidence_id':'repo','quote':'SYNTHETIC'}]
    if code=='P04':proposal['evidence_refs']=[{'evidence_id':'data','quote':'SYNTHETIC'}]
    return {'tiab':tiab,'evidence':bundle,'final':proposal}


def make_demo_input(base,name,count=1):
    root=init_project(base,'Heart',name)
    (root/'Input/query.txt').write_text('SYNTHETIC SELECT TEST ONLY',encoding='utf-8')
    c=Collector(root,SelectCollectClient(count))
    try:result=c.run()
    finally:c.close()
    return root.parent,root/result['manifest']


def run_demo(base,name,policy_dir,render=False):
    project,manifest=make_demo_input(base,name,5)
    scenarios={'1':scenario(two_datasets=True),'2':scenario('excluded','E01'),'3':scenario('pending','P01'),
               '4':scenario('pending','P04'),'5':scenario()}
    scenarios['3']['revalidated']=scenario()['final']
    root=project/'DB_Select';project_docs(root,'Heart',name)
    engine=Selector(root,policy_dir,provider=FixtureProvider(scenarios),collector=FixtureEvidenceCollector(scenarios))
    try:return engine.run(manifest,render=render)
    finally:engine.close()
