import copy
import json
from pathlib import Path
from unittest.mock import patch

from k_melloddy.core.storage import digest,dump
from k_melloddy.db_select.full_workflow import FullWorkflow
from k_melloddy.db_select.fixtures import scenario,make_demo_input
from k_melloddy.db_select.evidence_collector import FixtureEvidenceCollector
from k_melloddy.db_select.llm_adapter import FixtureProvider
from k_melloddy.db_select.verified_workflow import VerifiedSelector
from k_melloddy.db_select.revalidator import eligible


def setup(tmp_path):
    project,manifest=make_demo_input(tmp_path,'Flow',3)
    cases={'1':scenario('pending','P02'),'2':scenario('excluded','E01'),'3':scenario('excluded','E02')}
    for c in cases.values():
        c['tiab'].update(exposure='synthetic exposure',toxicity_endpoint='synthetic injury')
        c['evidence']['alternative_search_completed']=True
        for e in c['evidence']['records']:e['attempt']=2
    class Verifier:
        def verify(self,p):return {'status':'verified','verified_metadata':dict(p['values'],PMID=p['pmid']),'mismatches':{}}
    e=VerifiedSelector(project/'DB_Select',provider=FixtureProvider(cases),collector=FixtureEvidenceCollector(cases),verifier=Verifier())
    e.run(manifest,export=False);parent=e.run_id
    data={'policy_sha256':e.policy['sha256'],'papers':{p['paper_id']:{'source_sha256':digest(dump(p).encode()),'tiab':cases[p['pmid']]['tiab']} for p in e.papers}}
    path=tmp_path/'review.json';path.write_text(dump(data),encoding='utf-8');e.close()
    return project,parent,path,cases,Verifier()


def test_entire_paper_before_next_and_no_automatic_final_without_review(tmp_path):
    project,parent,path,cases,verifier=setup(tmp_path)
    e=FullWorkflow(project/'DB_Select',organ='Heart',review_file=path,verifier=verifier,collector=FixtureEvidenceCollector(cases))
    try:
        first=e.execute(parent,'flow');assert first['status']=='AWAITING_REVIEW' and first['saved_count']==0
        assert first['terminal_count']==0 and first['terminal_outcomes']=={}
        p=Path(first['request']);request=json.loads(p.read_text(encoding='utf-8'))
        assert request['round']==1
        answer={'request_sha256':digest(p.read_bytes()),'reviewer_note':'Synthetic P02 evidence reviewed','proposal':cases['1']['final']}
        p.with_name(p.name.replace('.request.','.answer.')).write_text(dump(answer),encoding='utf-8')
        second=e.execute(parent,'flow');assert second['saved_count']==1
        assert second['terminal_count']==0  # Initial P02 has not completed deep review.
        p=Path(second['request']);assert json.loads(p.read_text(encoding='utf-8'))['round']==2
        answer['request_sha256']=digest(p.read_bytes());p.with_name(p.name.replace('.request.','.answer.')).write_text(dump(answer),encoding='utf-8')
        with patch.object(e,'export',return_value='not-exported-offline'):
            result=e.execute(parent,'flow')
        records=e.store.records(result['run_id']);assert len(records)==3
        first_record=next(r for r in records.values() if r['pmid']=='1')
        assert first_record['revalidation']['attempt_count']==1
        assert first_record['revalidation']['auto_retry'] is False
        assert eligible(records,3)==[]
        old=copy.deepcopy(records)
        with patch.object(e,'export',return_value='not-exported-offline'):
            e.execute(parent,'flow')
        assert e.store.records(e.run_id)==old
        from k_melloddy.db_select.narrative_amendments import amend
        key=first_record['paper_id'];before=copy.deepcopy(e.store.records(e.run_id)[key])
        old_history=e.store.read_ref(before['revalidation']['history_refs'][0],e.run_id,before)
        correction={key:dict(pmid=before['pmid'],initial_reason='Initial access unresolved',final_reason='Deep access unresolved',
            reviewer_note='Synthetic evidence reviewed; no new HTTP request',confirmed=['Captured routes checked'],
            unresolved=['Article access'],next='Manual evidence required')}
        projected=amend(e.store,e.run_id,correction)
        current=e.store.records(e.run_id)[key]
        assert current['final']['code']==before['final']['code'] and current['revalidation']['attempt_count']==1
        assert e.store.read_ref(before['revalidation']['history_refs'][0],e.run_id,before)==old_history
        history=projected['revalidation_history.json']['papers'][0]
        assert len(history['attempts'])==len(history['superseded_attempts'])==1
        assert history['initial_result']['reason']=='Initial access unresolved'
        assert history['latest_result']['reason']=='Deep access unresolved'
        amend(e.store,e.run_id,correction)
        assert e.store.records(e.run_id)[key]==current
    finally:e.close()


def test_missing_title_and_abstract_skip_network_and_preserve_source(tmp_path):
    project,parent,path,cases,verifier=setup(tmp_path)
    e=FullWorkflow(project/'DB_Select',organ='Heart',review_file=path,verifier=verifier,collector=FixtureEvidenceCollector(cases))
    try:
        e.run_id=parent;e.policy=json.loads(e.store.run(parent)['policy_json']);e.papers=json.loads(e.store.run(parent)['input_json']);e.session=e.root/'Runs'/'absence';e.phase='initial';e.collect_run_id='synthetic'
        for missing in ['Title','Abstract']:
            paper=copy.deepcopy(e.papers[0]);paper['values'][missing]=''
            with patch.object(e.verifier,'verify',side_effect=AssertionError('Network forbidden')):
                r=e.review_source(paper)
            assert r['final']['code']=='TIAB_ABSENT' and r['tiab']['missing_fields']==[missing]
            assert r['source_record']==paper
    finally:e.close()


def test_progress_excel_failure_blocks_next_paper_and_resume_flushes_first(tmp_path):
    import pytest
    project,parent,path,cases,verifier=setup(tmp_path)
    for case in cases.values():case['tiab']=copy.deepcopy(cases['2']['tiab'])
    data=json.loads(path.read_text(encoding='utf-8'))
    for item in data['papers'].values():item['tiab']=copy.deepcopy(cases['2']['tiab'])
    path.write_text(dump(data),encoding='utf-8')
    e=FullWorkflow(project/'DB_Select',organ='Heart',review_file=path,verifier=verifier,collector=FixtureEvidenceCollector(cases))
    seen=[]
    def blocked():
        saved=e.store.records(e.run_id)
        seen.append(len(saved))
        if saved:raise PermissionError('Synthetic locked workbook')
    e.progress_callback=blocked
    try:
        with pytest.raises(PermissionError):e.execute(parent,'excel-flow')
        assert seen==[0,1]
        assert len(e.store.records(e.run_id))==1
        # Resume must retry the projection before any additional paper review.
        with patch.object(e,'review_source',side_effect=AssertionError('Next paper forbidden')):
            with pytest.raises(PermissionError):e.execute(parent,'excel-flow')
        assert seen==[0,1,1]
        e.progress_callback=lambda:seen.append(len(e.store.records(e.run_id)))
        with patch.object(e,'export',return_value='not-exported-offline'):
            e.execute(parent,'excel-flow')
        assert seen[-3:]==[1,2,3]
    finally:e.close()


def test_json_material_sample_is_not_reusable_claim():
    import base64
    from k_melloddy.db_select.full_workflow_access import inspect_material
    raw=b'[{"drug":"test","ALT":12},{"drug":"other","ALT":14}]'
    e=dict(status='accessible',kind='file',complete_body=True,format='application/json',final_url='https://example.org/data.json',body_sample_b64=base64.b64encode(raw).decode(),text='')
    r=inspect_material(e)
    assert r['columns']==['drug','ALT'] and r['level']=='sample_structure'
    assert 'dataset_reusable' not in r


def test_truncated_article_retries_with_bounded_size_and_preserves_failure():
    from k_melloddy.db_select.full_workflow_access import FullWorkflowAccess
    from k_melloddy.db_select.revalidation_access import RevalidationAccess
    access=FullWorkflowAccess(max_bytes=262144)
    calls=[]
    def request(self,url,kind,paper,route):
        calls.append((self.max_bytes,route))
        return [dict(evidence_id=str(len(calls)),failure_reason='response_exceeds_limit'
                     if len(calls)==1 else '',status='fetch_error' if len(calls)==1 else 'accessible')]
    with patch.object(RevalidationAccess,'request',request):
        result=access.request('https://example.org/article','fulltext',{},'publisher')
    assert calls==[(262144,'publisher'),(8*1024*1024,'publisher_bounded_size_retry')]
    assert result[0]['status']=='fetch_error'
    assert result[1]['retry_of_evidence_id']=='1'
    assert access.max_bytes==262144


def test_restricted_article_does_not_trigger_size_retry():
    from k_melloddy.db_select.full_workflow_access import FullWorkflowAccess
    from k_melloddy.db_select.revalidation_access import RevalidationAccess
    access=FullWorkflowAccess(max_bytes=262144)
    with patch.object(RevalidationAccess,'request',return_value=[dict(failure_reason='HTTP_403')]) as request:
        access.request('https://example.org/article','fulltext',{},'publisher')
    assert request.call_count==1


def test_extensionless_truncated_pdf_retries_even_without_extracted_text():
    from k_melloddy.db_select.full_workflow_access import FullWorkflowAccess
    from k_melloddy.db_select.revalidation_access import RevalidationAccess
    access=FullWorkflowAccess(max_bytes=262144)
    failed=dict(evidence_id='pdf-first',format='application/pdf',complete_body=False,
                bytes_observed=262145,failure_reason='redirect_or_empty_body_not_article')
    with patch.object(RevalidationAccess,'request',side_effect=[[failed],[dict(evidence_id='pdf-full')]]) as request:
        result=access.request('https://example.org/files/123','file',{},'download')
    assert request.call_count==2 and result[0]==failed
    assert result[1]['retry_of_evidence_id']=='pdf-first'
    assert access.max_bytes==262144


def test_resume_recovery_preserves_truncated_checkpoint_and_skips_success():
    from k_melloddy.db_select.full_workflow_access import FullWorkflowAccess
    access=FullWorkflowAccess(max_bytes=262144)
    original=dict(records=[dict(evidence_id='old',url='https://example.org/file',kind='file',
                 format='application/pdf',complete_body=False,bytes_observed=262145,
                 http_status=200,status='fetch_error')])
    before=copy.deepcopy(original)
    def request(url,kind,paper,route):
        assert access.max_bytes==8*1024*1024 and route=='checkpoint_truncated_response_recovery'
        return [dict(evidence_id='new',url=url,kind=kind,status='accessible',complete_body=True)]
    with patch.object(access,'request',side_effect=request) as call:
        result=access.recover_truncated({},original)
        assert access.recover_truncated({},result)==result
        assert call.call_count==1
    assert original==before and result['records'][1]['retry_of_evidence_id']=='old'
    assert access.max_bytes==262144


def test_additional_evidence_versions_request_without_reusing_old_answer(tmp_path):
    from k_melloddy.db_select.full_workflow import ReviewRequired
    import pytest
    project,parent,path,cases,verifier=setup(tmp_path)
    e=FullWorkflow(project/'DB_Select',organ='Heart',review_file=path,verifier=verifier,collector=FixtureEvidenceCollector(cases))
    try:
        result=e.execute(parent,'additional-evidence');p=Path(result['request'])
        original=p.read_bytes();d=json.loads(original)
        answer={'request_sha256':digest(original),'reviewer_note':'original fixture','proposal':cases['1']['final']}
        a=p.with_name(p.name.replace('.request.','.answer.'));a.write_text(dump(answer),encoding='utf-8')
        bundle=copy.deepcopy(d['evidence']);bundle['additional_test_evidence']=True
        with pytest.raises(ReviewRequired) as exc:e.provider.response(d['paper'],d['policy'],bundle)
        revised=Path(str(exc.value));assert revised!=p and revised.exists()
        assert p.read_bytes()==original and json.loads(a.read_text(encoding='utf-8'))==answer
        assert json.loads(revised.read_text(encoding='utf-8'))['evidence_sha256']==digest(dump(bundle).encode())
    finally:e.close()


def test_europe_pmc_free_link_is_attempted_without_assuming_fulltext():
    from k_melloddy.db_select.access_workflow import AccessInvestigator
    seen=[]
    paper={'pmid':'123','values':{'Title':'Actual article','DOI':'','PMCID':''},'_official_verified':True}
    def request(url,kind,paper,route):
        seen.append((url,kind))
        text=json.dumps({'resultList':{'result':[{'id':'123','source':'MED','title':'Actual article','fullTextUrlList':{'fullTextUrl':[{'availabilityCode':'F','url':'https://example.org/actual'}]}}]}}) if kind=='metadata' else 'Abstract only'
        return [{'url':url,'kind':kind,'text':text,'status':'accessible','identity_match':True,'observed_links':[]}]
    collector=AccessInvestigator();collector.request=request
    result=collector.collect(paper,{})
    assert ('https://example.org/actual','fulltext') in seen
    assert result['fulltext_reviewed'] is False


def test_invalid_session_answer_does_not_save_scientific_pending(tmp_path):
    project,parent,path,cases,verifier=setup(tmp_path)
    e=FullWorkflow(project/'DB_Select',organ='Heart',review_file=path,verifier=verifier,collector=FixtureEvidenceCollector(cases))
    try:
        first=e.execute(parent,'invalid-answer')
        p=Path(first['request'])
        proposal=copy.deepcopy(cases['1']['final'])
        proposal['what_unresolved']='invalid string instead of an array'
        answer={'request_sha256':digest(p.read_bytes()),'reviewer_note':'Invalid schema fixture','proposal':proposal}
        p.with_name(p.name.replace('.request.','.answer.')).write_text(dump(answer),encoding='utf-8')
        result=e.execute(parent,'invalid-answer')
        assert result['status']=='AWAITING_REVIEW'
        assert result['saved_count']==0
        assert e.store.records(e.run_id)=={}
    finally:e.close()


def test_binary_spreadsheet_response_requires_actual_parse():
    import base64
    import io
    from openpyxl import Workbook
    from k_melloddy.db_select.full_workflow_access import inspect_material
    wb=Workbook();ws=wb.active
    ws.append(['compound','ALT']);ws.append(['synthetic',12])
    stream=io.BytesIO();wb.save(stream);wb.close()
    record=dict(status='fetch_error',failure_reason='redirect_or_empty_body_not_article',http_status=200,
                kind='file',complete_body=True,format='application/octet-stream',final_url='https://example.org/data.xlsx',
                body_sample_b64=base64.b64encode(stream.getvalue()).decode(),text='')
    result=inspect_material(record)
    assert result['status']=='accessible' and result['columns']==['compound','ALT']
    assert result['sample_row_count']==1 and 'dataset_reusable' not in result


def test_deep_pass_requests_new_discovery_without_repeating_successful_search():
    from k_melloddy.db_select.full_workflow_access import FullWorkflowAccess
    initial={'records':[{'url':'https://example.org/old','kind':'metadata','status':'accessible'}], 'search_coverage':[]}
    class Engine:
        def cached(self,paper,kind,operation,round_number=None):
            assert kind=='collected_evidence' and round_number==1
            return initial
    class Access(FullWorkflowAccess):
        def __init__(self):self.engine=Engine();self.requests=[]
        def request(self,url,kind,paper,route):self.requests.append((url,route));return []
    access=Access()
    paper={'values':{'Title':'Synthetic title','DOI':''},'_review_discovery':[
        {'url':'https://example.org/old','kind':'metadata'},
        {'url':'https://example.org/new.pdf','kind':'fulltext'}]}
    result=access.collect(paper,{},dict(phase='revalidation',pending_code='P02'))
    assert ('https://example.org/new.pdf','deep_reviewer_observed_search_result') in access.requests
    assert all(url!='https://example.org/old' for url,_ in access.requests)
    assert result['records'][0]['reused_from_prior_round'] is True
    assert 'reused_from_prior_round' not in initial['records'][0]


def test_terminal_gate_blocks_unsaved_and_unfinished_records():
    import pytest
    from unittest.mock import Mock
    e=object.__new__(FullWorkflow)
    e.run_id='fixture'; e.store=Mock()
    paper={'paper_id':'Liver-00001'}
    terminal={'final':{'status':'pending'},'revalidation':{'terminal':True,'auto_retry':False},'processing_state':'reviewed'}
    for status in ['confirmed','excluded','pending']:
        r=copy.deepcopy(terminal);r['final']['status']=status
        e.store.records.return_value={paper['paper_id']:copy.deepcopy(r)}
        e.require_saved_terminal(paper,r)
    for change in ['unsaved','nonterminal','retry','blocked','unreviewed']:
        r=copy.deepcopy(terminal)
        if change=='nonterminal':r['revalidation']['terminal']=False
        if change=='retry':r['revalidation']['auto_retry']=True
        if change=='blocked':r['processing_state']='blocked_verification'
        if change=='unreviewed':r['final']['status']='unreviewed'
        e.store.records.return_value={} if change=='unsaved' else {paper['paper_id']:r}
        with pytest.raises(ValueError,match='next paper blocked'):
            e.require_saved_terminal(paper,r)


def test_failed_metadata_checkpoint_recovers_without_erasing_attempt(tmp_path):
    project,parent,path,cases,verifier=setup(tmp_path)
    e=FullWorkflow(project/'DB_Select',organ='Heart',review_file=path,verifier=verifier,collector=FixtureEvidenceCollector(cases))
    try:
        e.session=e.root/'Runs'/'metadata-recovery'
        paper=json.loads(e.store.run(parent)['input_json'])[0]
        failed={'status':'unverified','attempts':[{'state':'failed'}]}
        verified=verifier.verify(paper)
        with patch.object(verifier,'verify',side_effect=[failed,verified]) as request:
            assert e.verifier.verify(paper)==failed
            original=e.session/'cache'/paper['paper_id']/'official_metadata_0.json'
            original_bytes=original.read_bytes()
            assert e.verifier.verify(paper)==verified
            assert e.verifier.verify(paper)==verified
            assert request.call_count==2
        assert original.read_bytes()==original_bytes
        assert len(list(original.parent.glob('official_metadata_recovery_*_0.json')))==1
    finally:e.close()


def test_unsaved_paper_stops_loop_before_next_paper(tmp_path):
    import pytest
    project,parent,path,cases,verifier=setup(tmp_path)
    e=FullWorkflow(project/'DB_Select',organ='Heart',review_file=path,verifier=verifier,collector=FixtureEvidenceCollector(cases))
    fake={'tiab':{'decision':'E01'},'final':{'status':'excluded','code':'E01','reason':'fixture'},'revalidation':{'terminal':True,'auto_retry':False},'processing_state':'reviewed'}
    try:
        with patch.object(e,'review_source',return_value=fake) as review, patch.object(e,'export') as export:
            with pytest.raises(ValueError,match='not durably saved'):
                e.execute(parent,'unsaved')
            assert review.call_count==1
            export.assert_not_called()
        assert e.store.run(e.run_id)['status']=='PARTIAL'
    finally:e.close()
