import copy,json
from pathlib import Path
from unittest.mock import patch
import pytest
from k_melloddy.db_select.official_metadata import OfficialMetadataVerifier,verified_paper,parse_official
from k_melloddy.db_select.access_workflow import AccessInvestigator,access_pending
from k_melloddy.db_select.verified_workflow import VerifiedSelector
from k_melloddy.db_select.fixtures import make_demo_input,scenario
from k_melloddy.db_select.llm_adapter import FixtureProvider
from k_melloddy.db_select.evidence_collector import FixtureEvidenceCollector
from k_melloddy.db_collect.fake import FakeClient
from k_melloddy.db_select.prisma import summarize


def test_official_identifiers_ignore_references_and_keep_original():
    raw=b'''<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>1</PMID><Article><ArticleTitle>Actual title</ArticleTitle><Journal><JournalIssue><PubDate><Year>2026</Year></PubDate></JournalIssue></Journal></Article></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">10.1/actual</ArticleId><ArticleId IdType="pmc">PMC1</ArticleId></ArticleIdList><ReferenceList><Reference><ArticleIdList><ArticleId IdType="doi">10.1/wrong</ArticleId></ArticleIdList></Reference></ReferenceList></PubmedData></PubmedArticle></PubmedArticleSet>'''
    class Client:
        def fetch(self,pmids):assert pmids==['1'];return raw
    paper={'paper_id':'Liver-00001','pmid':'1','values':{'PMID':'1','Title':'old','DOI':'wrong','PMCID':'PMC9','Publication Date':'2025'}}
    original=copy.deepcopy(paper)
    check=OfficialMetadataVerifier(Client()).verify(paper)
    assert check['status']=='verified' and len(check['mismatches'])==4
    assert verified_paper(paper,check)['values']['DOI']=='10.1/actual'
    assert paper==original and check['verified_metadata']['Publication year']=='2026'
    with pytest.raises(ValueError):parse_official(raw,'2')
    with pytest.raises(ValueError):verified_paper(paper,{'status':'unverified'})


def test_single_403_does_not_authorize_p02():
    bundle={'records':[{'url':'https://example.org/a','kind':'fulltext','status':'access_restricted','attempt':1}]}
    assert not access_pending(bundle)
    bundle['alternative_search_completed']=True
    assert not access_pending(bundle)
    bundle['records']+=[{'url':'https://example.org/a','kind':'fulltext','status':'access_restricted','attempt':2},
                        {'url':'https://other.org/search','kind':'metadata','status':'accessible','attempt':1}]
    assert access_pending(bundle)


def test_unverified_metadata_never_reaches_access():
    with pytest.raises(ValueError,match='gate'):
        AccessInvestigator().collect({'values':{'DOI':'wrong'}},{})


def test_wrong_article_page_is_retried_and_audited():
    import io
    from email.message import Message
    class Response(io.BytesIO):
        status=200;url='https://example.org/paper';headers=Message();headers['Content-Type']='text/html'
    class Opener:
        def open(self,*args,**kwargs):return Response(b'<html><h1>Unrelated paper</h1></html>')
    a=AccessInvestigator(opener=Opener(),retries=1)
    with patch('k_melloddy.db_select.access_workflow.public_url',side_effect=lambda x:x),patch('time.sleep'):
        rows=a.request('https://example.org/paper','fulltext',{'values':{'Title':'Correct title'}},'publisher')
    assert len(rows)==2 and [r['attempt'] for r in rows]==[1,2]
    assert all(r['failure_reason']=='article_identity_not_verified' and r['status']=='fetch_error' for r in rows)
    assert all(r['payload_sha256'] and r['timestamp'] for r in rows)


def test_metadata_failure_retains_paper_and_blocks_completion(tmp_path):
    project,manifest=make_demo_input(tmp_path,'Blocked',1)
    class FailedVerifier:
        def verify(self,p):return {'status':'unverified','verified_metadata':{},'attempts':[{'failure_reason':'timeout'}]}
    class NoAccess:
        def collect(self,*args):raise AssertionError('Unverified identifiers reached access')
    c=VerifiedSelector(project/'DB_Select',Path('config/db_select'),provider=FixtureProvider({'1':scenario()}),collector=NoAccess(),verifier=FailedVerifier())
    try:
        result=c.run(manifest,export=False)
        assert result['N_pending']==result['input_count']==1 and result['status']=='PARTIAL'
        r=next(iter(c.store.records(c.run_id).values()))
        assert r['processing_state']=='blocked_verification' and r['final']['code']=='P02'
        assert r['revalidation']['attempt_count']==1
    finally:c.close()


def test_verified_scope_final_partition_and_resume(tmp_path):
    project,manifest=make_demo_input(tmp_path,'Test',3)
    cases={str(i):scenario('pending','P02') for i in range(1,4)}
    for s in cases.values():
        s['tiab'].update(exposure='test compound exposure',toxicity_endpoint='hepatic injury',relevance_class='exposure_toxicity')
        s['evidence']['alternative_search_completed']=True
        for e in s['evidence']['records']:e['attempt']=2
    class Verifier:
        def verify(self,p):
            return {'status':'verified','verified_metadata':{'PMID':p['pmid'],'Title':p['values']['Title'],'DOI':'10.1/verified','PMCID':'','Publication year':'2026'},'mismatches':{'DOI':{'input':p['values']['DOI'],'official':'10.1/verified'}}}
    class Collector(FixtureEvidenceCollector):
        def collect(self,p,policy,action=''):
            assert p['_official_verified'] and p['values']['DOI']=='10.1/verified'
            return super().collect(p,policy,action)
    c=VerifiedSelector(project/'DB_Select',Path('config/db_select'),provider=FixtureProvider(cases),collector=Collector(cases),verifier=Verifier())
    try:
        result=c.run(manifest,limit=3,order='desc',export=False)
        assert result['N_pending']==3 and result['N_all']==3 and result['incomplete_count']==0
        events=c.store.db.execute("SELECT paper_id FROM events WHERE step_id='2.3' AND phase='initial' ORDER BY rowid").fetchall()
        assert [r[0] for r in events]==[f'HEART-P{i:06}' for i in range(1,4)]
        records=c.store.records(c.run_id)
        assert all(r['revalidation']['attempt_count']==1 for r in records.values())
        assert all(r['final']['status']=='pending' and r['verified_metadata']['DOI']=='10.1/verified' for r in records.values())
        calls=list(c.provider.calls);c.run(resume=c.run_id,export=False);assert calls==c.provider.calls
        p=list(records.values())[0];p['processing_state']='blocked_verification'
        assert summarize(c.papers,records)['status']=='PARTIAL'
    finally:c.close()


@pytest.mark.parametrize('code',['P01','P02','P03','P04'])
@pytest.mark.parametrize('target',['confirmed','excluded'])
def test_pending_pass_runs_after_initial_and_resolves_with_history(tmp_path,code,target):
    project,manifest=make_demo_input(tmp_path,'PendingPass',2)
    initial=scenario('pending',code);resolved=scenario(target,'E04' if target=='excluded' else '')
    initial['tiab'].update(exposure='compound',toxicity_endpoint='hepatic injury')
    initial['evidence']['alternative_search_completed']=True
    for row in initial['evidence']['records']:row['attempt']=2
    resolved['evidence']['workflow']=[{'step':x,'state':'reviewed'} for x in ['Methods','Data Availability','Supplementary','Repository','data_file_or_api','toxicity_features']]
    cases={str(i):copy.deepcopy(initial) for i in [1,2]}
    for value in cases.values():value['revalidated']=resolved['final']
    class Verifier:
        def verify(self,p):return {'status':'verified','verified_metadata':dict(p['values'],PMID=p['pmid']),'mismatches':{}}
    class Collector:
        def collect(self,p,policy,action=''):
            if isinstance(action,dict):
                assert action['pending_code']==code
                assert c.store.db.execute("SELECT COUNT(*) FROM events WHERE step_id='2.7' AND phase='initial'").fetchone()[0]==2
                return copy.deepcopy(resolved['evidence'])
            return copy.deepcopy(initial['evidence'])
    c=VerifiedSelector(project/'DB_Select',Path('config/db_select'),provider=FixtureProvider(cases),collector=Collector(),verifier=Verifier())
    try:
        result=c.run(manifest,export=False)
        assert result['N_pending']==0 and result['N_all']==2
        metrics=result['revalidation_metrics']
        assert metrics['initial_processed_count']==metrics['initial_pending_count']==metrics['revalidation_attempt_count']==2
        assert metrics['converted_to_included_count' if target=='confirmed' else 'converted_to_excluded_count']==2
        history=c.store.verify_aggregate(c.run_id)['revalidation_history.json']['papers']
        assert len(history)==2
        for row in history:
            assert row['initial_p_code']==code and row['verification_resolved'] and row['revalidation_completed']
            h=row['attempts'][0]['content']
            assert h['initial_p_code']==code and h['previous_result']['code']==code
            assert h['access_results'] and h['final_reason'] and h['result']['status']==target
    finally:c.close()


def test_explicit_additional_pass_is_bounded_and_opt_in():
    from k_melloddy.db_select.revalidator import eligible
    rows={'Liver-00001':{'paper_id':'Liver-00001','final':{'status':'pending'},'initial_review_valid':True,'revalidation':{'attempt_count':3}}}
    assert eligible(rows,3,automatic=False)==[]
    assert len(eligible(rows,3,automatic=False,additional_pass=True))==1


def test_biostudies_numeric_links_preserves_observed_accession():
    a=AccessInvestigator();seen=[]
    def request(url,kind,paper,route):
        seen.append((url,route))
        text=json.dumps({'hits':[{'title':'A verified title','accession':'S-EPMC123','links':1}]}) if route.startswith('BioStudies') else '{}'
        return [{'url':url,'kind':kind,'route':route,'status':'accessible','identity_match':False,'text':text,'attempt':1}]
    a.request=request
    result=a.collect({'pmid':'123','_official_verified':True,'values':{'Title':'A verified title'}},{},{'phase':'initial'})
    assert ('https://www.ebi.ac.uk/biostudies/studies/S-EPMC123','independent_repository_match') in seen
    assert any(c.get('matched_urls') for c in result['search_coverage'])


def test_revalidation_discovers_repositories_without_accessible_fulltext():
    a=AccessInvestigator();seen=[]
    def request(url,kind,paper,route):
        seen.append((url,route))
        return [{'url':url,'kind':kind,'route':route,'status':'fetch_error','identity_match':False,'text':'','attempt':2}]
    a.request=request
    result=a.collect({'pmid':'123','_official_verified':True,'values':{'Title':'A verified title','DOI':'10.1/correct','PMCID':'PMC123'}},{}, {'phase':'revalidation','pending_code':'P03','known_records':[{'kind':'file','url':'https://example.org/observed.csv'}]})
    assert any('fullTextXML' in u for u,r in seen)
    assert any('biostudies' in u for u,r in seen) and any('zenodo' in u for u,r in seen)
    assert any(r=='prior_observed_location' for u,r in seen)
    assert result['focused_pending_code']=='P03'
    assert next(x for x in result['search_coverage'] if x['target']=='publisher_supplementary')['state']=='no_observed_link'


@pytest.mark.parametrize('code',['P01','P03','P04'])
def test_failed_revalidation_preserves_specific_pending_code(tmp_path,code):
    project,manifest=make_demo_input(tmp_path,'KeepCode',1)
    initial=scenario('pending',code)
    initial['tiab'].update(exposure='compound',toxicity_endpoint='hepatic injury')
    initial['revalidated']=ValueError('Reviewer evidence unavailable')
    class Verifier:
        def verify(self,p):return {'status':'verified','verified_metadata':dict(p['values'],PMID=p['pmid']),'mismatches':{}}
    c=VerifiedSelector(project/'DB_Select',Path('config/db_select'),provider=FixtureProvider({'1':initial}),collector=FixtureEvidenceCollector({'1':initial}),verifier=Verifier())
    try:
        result=c.run(manifest,export=False)
        assert result['status']=='PARTIAL' and result['N_pending']==1
        assert result['this_execution']['revalidation_attempt_count']==1
        record=next(iter(c.store.records(c.run_id).values()))
        assert record['final']['code']==code
        history=c.store.verify_aggregate(c.run_id)['revalidation_history.json']['papers'][0]
        assert history['initial_p_code']==code and not history['revalidation_completed']
        assert history['unresolved_reason']
    finally:c.close()


@pytest.mark.parametrize('pmid,expected',[('123',True),('999',False)])
def test_xml_identity_uses_own_pmid_and_normalized_title(pmid,expected):
    import io
    from email.message import Message
    raw=b'<article><front><article-meta><article-id pub-id-type="pmid">123</article-id><title-group><article-title>Correct title</article-title></title-group></article-meta></front><body><sec>Methods text</sec></body></article>'
    class Response(io.BytesIO):
        status=200;url='https://example.org/paper';headers=Message();headers['Content-Type']='application/xml'
    class Opener:
        def open(self,*args,**kwargs):return Response(raw)
    a=AccessInvestigator(opener=Opener(),retries=0)
    with patch('k_melloddy.db_select.access_workflow.public_url',side_effect=lambda x:x):
        row=a.request('https://example.org/paper','fulltext',{'pmid':pmid,'values':{'Title':'Correct title.'}},'PMC_XML')[0]
    assert row['identity_match']==expected
    assert (row['status']=='accessible')==expected


def test_available_body_requires_review_before_supplementary_p02():
    bundle={'alternative_search_completed':True,'records':[{'kind':'fulltext','url':'https://pmc.test/body','status':'accessible','identity_match':True,'text':'<body>Methods</body>','route':'PMC_XML'}, {'kind':'fulltext','url':'https://publisher.test/paper','status':'access_restricted','identity_match':False,'text':'','route':'publisher','attempt':2}], 'search_coverage':[{'target':'publisher_supplementary','state':'no_observed_link'}], 'fulltext_reviewed':False,'supplementary_checked':False}
    assert not access_pending(bundle)
    bundle['fulltext_reviewed']=True
    assert access_pending(bundle)
    bundle['supplementary_checked']=True
    assert not access_pending(bundle)



def test_reference_journal_supplement_is_not_supplementary_material():
    from k_melloddy.db_select.access_workflow import material_kind
    assert material_kind('https://scholar.google.com/scholar_lookup?volume=65(Supplement_1)') is None
    assert material_kind('https://publisher.test/article?title=Supplement_1') is None
    assert material_kind('https://publisher.test/supplementary/table.csv')=='supplementary'
