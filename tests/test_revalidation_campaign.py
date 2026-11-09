import copy
from pathlib import Path
from unittest.mock import patch
import pytest
from k_melloddy.db_select.revalidation_access import readable_body,verification_state,Linkouts
from k_melloddy.db_select.revalidation_campaign import run_campaign
from k_melloddy.db_select.verified_workflow import VerifiedSelector
from k_melloddy.db_select.fixtures import scenario,make_demo_input
from k_melloddy.db_select.evidence_collector import FixtureEvidenceCollector
from k_melloddy.db_select.llm_adapter import FixtureProvider


def test_scan_container_is_not_read_fulltext_or_public_dataset():
    e=dict(kind='fulltext',status='accessible',identity_match=True,text='<article><body><sec><title>Full text</title><graphic href="scan.png"/></sec></body></article>')
    assert not readable_body(e)
    e['text']='<article><body><preformat preformat-type="pmc-ocr-text">'+('actual OCR prose '*40)+'</preformat></body></article>'
    assert readable_body(e)
    state=verification_state({},dict(records=[],fulltext_reviewed=False),{'data_observations':[{'name':'Named study database'}]})
    assert state['dataset_identified'] is True
    assert state['dataset_public']==state['dataset_downloadable']==state['full_text_access']=='unknown'
    e['text']='<article><body><sec><title>Methods</title><p>'+('actual prose '*40)+'</p></sec></body></article>'
    assert readable_body(e)
    e.update(url='https://pubmed.ncbi.nlm.nih.gov/123/',text='Methods '+('abstract prose '*40))
    assert not readable_body(e)


def test_linkouts_ignore_navigation():
    p=Linkouts();p.feed('<a href="https://navigation.test">x</a><a class="link-item" href="https://account.ncbi.nlm.nih.gov/">Login</a><a data-ga-category="full_text" class="link-item dialog-focus" href="https://publisher.test/article">full text</a>')
    assert p.urls==['https://publisher.test/article']


def test_independent_searches_merge_in_input_order():
    from k_melloddy.db_select.revalidation_access import RevalidationAccess
    specs=[('one','https://example.org/one'),('two','https://example.org/two')]
    with patch.object(RevalidationAccess,'request',side_effect=lambda url,*args:[{'url':url}]):
        assert RevalidationAccess().search_batch(specs,{'paper_id':'test'})==[[{'url':u}] for q,u in specs]


def test_identical_title_never_overrides_conflicting_official_doi_or_pmid():
    from k_melloddy.db_select.revalidation_access import scholarly_match
    p={'pmid':'123','values':{'Title':'Same title.','DOI':'10.9999/original'}}
    hit={'title':'Same title','doi':'https://doi.org/10.9999/other','ids':{'pmid':'https://pubmed.ncbi.nlm.nih.gov/123'}}
    assert not scholarly_match(hit,p)
    hit['doi']='https://doi.org/10.9999/original'
    assert scholarly_match(hit,p)
    hit['ids']['pmid']='https://pubmed.ncbi.nlm.nih.gov/999'
    assert not scholarly_match(hit,p)


def test_no_article_path_requires_actual_identity_matched_search_results():
    import json
    from k_melloddy.db_select.access_workflow import access_pending
    from k_melloddy.db_select.fixtures import evidence_record
    records=[]
    for route in ['alternative_search','alternative_search','PubMed_linkouts','title_author_scholarly_search']:
        e=evidence_record(str(len(records)),kind='metadata',url='https://example.org/'+str(len(records)))
        e.update(route=route,text=json.dumps({'resultList':{'result':[{'id':'123','source':'MED'}]}}));records.append(e)
    bundle=dict(records=records,alternative_search_completed=True,independent_discovery_completed=True,official_identity={'pmid':'123','doi':'','pmcid':''})
    assert access_pending(bundle)
    bundle['official_identity']['pmid']='999'
    assert not access_pending(bundle)
    bundle['official_identity']['pmid']='123';bundle['records'].pop(0)
    assert not access_pending(bundle)


def test_captcha_script_on_normal_article_is_not_access_block():
    import io
    from email.message import Message
    from k_melloddy.db_select.access_workflow import AccessInvestigator
    class Response(io.BytesIO):
        status=200
        url='https://example.org/article'
        headers=Message()
        headers['Content-Type']='text/html'
    class Opener:
        def open(self,*args,**kwargs):return Response(b'<h1>Exact paper title</h1><p>Actual article.</p><script src="https://www.google.com/recaptcha/api.js"></script>')
    with patch('k_melloddy.db_select.access_workflow.public_url'):
        rows=AccessInvestigator(opener=Opener(),retries=0).request('https://example.org/article','fulltext',{'pmid':'123','values':{'Title':'Exact paper title'}},'test')
    assert rows[0]['status']=='accessible'
    assert rows[0]['identity_match']


def test_pending_clue_does_not_require_claimed_fulltext_and_location_must_be_cited():
    from k_melloddy.db_select.decision import fulltext_decision
    case=scenario('pending','P01')
    case['evidence']['fulltext_reviewed']=False
    fulltext_decision(case['final'],case['evidence'])
    case=scenario('pending','P03')
    proposal=case['final'];bundle=case['evidence']
    nonlocation=next(e for e in bundle['records'] if e['kind']=='fulltext')
    proposal['evidence_refs']=[{'evidence_id':nonlocation['evidence_id'],'quote':nonlocation['text'][:20]}]
    with pytest.raises(ValueError,match='must be cited'):fulltext_decision(proposal,bundle)


def setup(tmp_path):
    project,manifest=make_demo_input(tmp_path,'Camp',3)
    cases={'1':scenario('pending','P02'),'2':scenario('excluded','E01'),'3':scenario('pending','P02')}
    for case in cases.values():
        case['tiab'].update(exposure='synthetic exposure',toxicity_endpoint='synthetic liver injury')
        case['evidence']['alternative_search_completed']=True
        for e in case['evidence']['records']:e['attempt']=2
    class Verifier:
        def verify(self,p):return {'status':'verified','verified_metadata':dict(p['values'],PMID=p['pmid']),'mismatches':{}}
    c=VerifiedSelector(project/'DB_Select',provider=FixtureProvider(cases),collector=FixtureEvidenceCollector(cases),verifier=Verifier())
    c.run(manifest,export=False)
    scope={k:r['pmid'] for k,r in c.store.records(c.run_id).items() if r['final']['status']=='pending'}
    return c,scope


def test_campaign_resume_after_commit_no_double_count_and_exclusions_unchanged(tmp_path):
    c,scope=setup(tmp_path)
    try:
        old=copy.deepcopy(c.store.records(c.run_id));save=c.store.aggregate;count=0
        def fail(run):
            nonlocal count
            count+=1
            if count==1:raise RuntimeError('after paper commit')
            return save(run)
        with patch.object(c.store,'aggregate',side_effect=fail),pytest.raises(RuntimeError):
            run_campaign(c,c.run_id,'test',scope,export=False)
        result=run_campaign(c,c.run_id,'test',scope,export=False)
        assert result['input_count']==result['processed_count']==2
        assert sum(result['transitions'].values())==2
        current=c.store.records(c.run_id)
        assert all(current[k]==r for k,r in old.items() if k not in scope)
        assert all(current[k]['revalidation']['attempt_count']==2 for k in scope)
        run_campaign(c,c.run_id,'test',scope,export=False)
        assert c.store.records(c.run_id)==current
    finally:c.close()


def test_scope_mismatch_fails_before_revisions(tmp_path):
    c,scope=setup(tmp_path)
    try:
        old=c.store.records(c.run_id);scope[next(iter(scope))]='999'
        with pytest.raises(ValueError,match='mismatch'):run_campaign(c,c.run_id,'bad',scope,export=False)
        assert c.store.records(c.run_id)==old
    finally:c.close()


def test_captured_human_review_is_separate_and_idempotent(tmp_path):
    import json
    from k_melloddy.db_select.captured_review import apply_captured_reviews
    c,scope=setup(tmp_path)
    try:
        run_campaign(c,c.run_id,'review',scope,export=False)
        records=c.store.records(c.run_id);key=next(iter(scope));r=records[key]
        # The synthetic collector is explicitly tagged to exercise the detailed audit path.
        bundle=c.store.read_ref(r['evidence_ref'],c.run_id,r)
        bundle['collector']='targeted-independent-revalidation-v1'
        ref=c.store.document(c.run_id,r,'evidence',bundle);r['evidence_ref']=ref
        r=c.store.save(c.run_id,r,'test_capture')
        other=next(k for k in scope if k!=key);other_record=records[other]
        tiab=copy.deepcopy(other_record['tiab']);tiab.pop('availability',None);tiab['decision']='E02'
        entries={key:dict(pmid=r['pmid'],based_on_revision=r['revision'],reviewer_note='Synthetic explicit review'),
            other:dict(pmid=other_record['pmid'],based_on_revision=other_record['revision'],reviewer_note='Synthetic TIAB reassessment',tiab=tiab)}
        p=tmp_path/'review.json';p.write_text(json.dumps(dict(run_id=c.run_id,campaign_id='review',papers=entries)),encoding='utf-8')
        del c.collect_run_id  # A fresh process must reconstruct the original Collect reference.
        result=apply_captured_reviews(c,c.run_id,'review',p)
        assert set(result['changed'])=={key,other}
        assert c.store.records(c.run_id)[key]['revalidation']['attempt_count']==3
        assert c.store.records(c.run_id)[other]['final']['code']=='E02'
        assert apply_captured_reviews(c,c.run_id,'review',p)['changed']==[]
    finally:c.close()
