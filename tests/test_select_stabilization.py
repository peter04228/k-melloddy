"""Offline fault injection; all papers and HTTP responses are synthetic."""
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from email.message import Message
from unittest.mock import patch
import pytest
from k_melloddy.db_select.verified_workflow import VerifiedSelector
from k_melloddy.db_select.fixtures import make_demo_input,scenario
from k_melloddy.db_select.llm_adapter import FixtureProvider
from k_melloddy.db_select.evidence_collector import FixtureEvidenceCollector
from k_melloddy.db_select.access_workflow import AccessInvestigator


class Verifier:
    def verify(self,p):
        return {'status':'verified','verified_metadata':dict(p['values'],PMID=p['pmid']),'mismatches':{}}


def setup(tmp_path,cases):
    project,manifest=make_demo_input(tmp_path,'Stability',len(cases))
    for case in cases.values():case['tiab'].update(exposure='synthetic exposure',toxicity_endpoint='synthetic toxicity')
    return VerifiedSelector(project/'DB_Select',Path('config/db_select'),provider=FixtureProvider(cases),
        collector=FixtureEvidenceCollector(cases),verifier=Verifier()),manifest


@pytest.mark.parametrize('mutation',['missing','excluded_code','dataset','history','policy'])
def test_strict_qc_rejects_incomplete_or_corrupt_final_state(tmp_path,mutation):
    c,m=setup(tmp_path,{'1':scenario('excluded','E01')})
    try:
        c.run(m,export=False);records=c.store.records(c.run_id);r=next(iter(records.values()))
        if mutation=='missing':records.clear()
        elif mutation=='excluded_code':r['final']['code']=''
        elif mutation=='dataset':r['final']={'status':'confirmed','code':'','reason':'invalid fixture'}
        elif mutation=='history':r['revalidation']['attempt_count']=1
        else:r['provenance']['policy_sha256']='wrong'
        with pytest.raises(ValueError):c.qc(records)
    finally:c.close()


def test_configured_automatic_passes_have_timestamps_and_are_finite(tmp_path):
    case=scenario('pending','P03');c,m=setup(tmp_path,{'1':case})
    from k_melloddy.db_select.policy import load_policy
    policy=load_policy(Path('config/db_select'),'Heart');policy['rules']['automatic_revalidation_attempts']=2
    try:
        with patch('k_melloddy.db_select.engine.load_policy',return_value=policy):result=c.run(m,export=False)
        assert result['revalidation_metrics']['revalidation_attempt_count']==2
        history=c.store.verify_aggregate(c.run_id)['revalidation_history.json']['papers'][0]
        assert all(h['content']['started_at']<=h['content']['ended_at'] for h in history['attempts'])
        calls=list(c.provider.calls);c.run(resume=c.run_id,export=False);assert c.provider.calls==calls
    finally:c.close()


def test_real_process_exit_after_sqlite_commit_resumes_without_reprocessing(tmp_path):
    project,m=make_demo_input(tmp_path,'HardExit',2)
    script='''
import os,sys
from pathlib import Path
from k_melloddy.db_select.verified_workflow import VerifiedSelector
from k_melloddy.db_select.fixtures import scenario
from k_melloddy.db_select.llm_adapter import FixtureProvider
class V:
 def verify(self,p):return {'status':'verified','verified_metadata':dict(p['values'],PMID=p['pmid']),'mismatches':{}}
c=VerifiedSelector(Path(sys.argv[1]),Path('config/db_select'),provider=FixtureProvider({'1':scenario('excluded','E01'),'2':scenario('excluded','E02')}),verifier=V())
original=c.store.aggregate
def stop(run):
 if len(c.store.records(run))==1:os._exit(77)
 return original(run)
c.store.aggregate=stop
c.run(Path(sys.argv[2]),export=False)
'''
    child=subprocess.run([sys.executable,'-c',script,str(project/'DB_Select'),str(m)],timeout=30,capture_output=True)
    assert child.returncode==77,child.stderr.decode(errors='replace')
    provider=FixtureProvider({'1':scenario('excluded','E01'),'2':scenario('excluded','E02')})
    c=VerifiedSelector(project/'DB_Select',Path('config/db_select'),provider=provider,verifier=Verifier())
    try:
        run=c.store.db.execute('SELECT run_id FROM runs').fetchone()[0]
        before=c.store.records(run);assert len(before)==1
        result=c.run(resume=run,export=False)
        assert result['N_excluded']==2 and result['status']=='COMPLETED'
        assert c.store.records(run)['HEART-P000001']==before['HEART-P000001']
        assert all(p!='HEART-P000001' for p,phase in provider.calls)
        c.store.verify_aggregate(run)
    finally:c.close()


def test_excel_json_and_prisma_disagreement_are_rejected(tmp_path):
    from k_melloddy.db_select.excel_export import workbook_payload,template_contract,verify_workbook
    c,m=setup(tmp_path,{'1':scenario('excluded','E01')})
    try:
        summary=c.run(m,export=False);c.export()
        records=c.store.records(c.run_id);sheets,_=workbook_payload(c.papers,records,template_contract()[0])
        bad=dict(summary,N_excluded=99)
        with pytest.raises(ValueError,match='counts mismatch'):verify_workbook(c.root/'Output/DB_Select_Final.xlsx',sheets,c.papers,records,bad)
        c.store.event(c.run_id,'2.7',c.papers[0]['paper_id'],'initial','pending','P02')
        with pytest.raises(ValueError,match='PRISMA/SQLite'):c.refresh(records)
    finally:c.close()


@pytest.mark.parametrize('mode',['csv','timeout','404','wrong_doi','incomplete'])
def test_actual_response_parser_and_repository_failures(mode):
    import urllib.error
    class Response(io.BytesIO):
        status=200;url='https://example.test/data.csv';headers=Message()
    class Opener:
        def open(self,*args,**kwargs):
            if mode=='incomplete':
                import http.client
                raise http.client.IncompleteRead(b'partial')
            if mode=='timeout':raise TimeoutError()
            if mode=='404':raise urllib.error.HTTPError('https://example.test/data.csv',404,'absent',{},None)
            if mode=='csv':
                r=Response(b'drug,endpoint,value\na,ALT,12\n');r.headers['Content-Type']='text/csv';return r
            r=Response(b'<article><front><article-meta><article-id pub-id-type="pmid">1</article-id><article-id pub-id-type="doi">10.1/wrong</article-id><title-group><article-title>Right title</article-title></title-group></article-meta></front></article>');r.headers['Content-Type']='application/xml';return r
    a=AccessInvestigator(opener=Opener(),retries=0)
    with patch('k_melloddy.db_select.access_workflow.public_url',side_effect=lambda x:x):
        row=a.request('https://example.test/data.csv','fulltext' if mode=='wrong_doi' else 'file',{'pmid':'1','values':{'Title':'Right title','DOI':'10.1/correct'}},'repository')[0]
    if mode=='csv':assert row['columns']==['drug','endpoint','value'] and row['level']=='sample_structure'
    elif mode=='timeout':assert row['failure_reason']=='Timeout'
    elif mode=='404':assert row['http_status']==404 and row['status']=='fetch_error'
    elif mode=='incomplete':assert row['failure_reason']=='IncompleteRead' and row['status']=='fetch_error'
    else:assert not row['identity_match'] and not row['identity_checks']['doi']


@pytest.mark.parametrize('fault',['duplicate_pmid','missing_id'])
def test_invalid_collect_identity_is_rejected_before_run(tmp_path,fault):
    from k_melloddy.core.storage import digest,dump
    from k_melloddy.db_select.metadata import load_collect
    project,m=make_demo_input(tmp_path,'InvalidInput',2)
    manifest=json.loads(m.read_text(encoding='utf8'));root=project/'DB_Collect'
    artifact=next(x for x in manifest['artifacts'] if Path(x['path']).name=='internal_master.json')
    path=root/artifact['path'];papers=json.loads(path.read_text(encoding='utf8'))
    if fault=='duplicate_pmid':papers[1]['pmid']=papers[0]['pmid'];papers[1]['values']['PMID']=papers[0]['pmid']
    else:papers[1].pop('paper_id')
    path.write_text(dump(papers),encoding='utf8');artifact['sha256']=digest(path.read_bytes());m.write_text(dump(manifest),encoding='utf8')
    with pytest.raises(ValueError):load_collect(m,root)


def test_csv_response_verified_before_inclusion():
    from k_melloddy.db_select.decision import fulltext_decision
    class Response(io.BytesIO):
        status=200;url='https://fixture.invalid/data.csv';headers=Message();headers['Content-Type']='text/csv'
    class Opener:
        def open(self,*args,**kwargs):return Response(b'drug,endpoint,value\ncompound-a,ALT,12\n')
    with patch('k_melloddy.db_select.access_workflow.public_url',side_effect=lambda x:x):
        record=AccessInvestigator(opener=Opener()).request('https://fixture.invalid/data.csv','file',{'pmid':'1','values':{'Title':'SYNTHETIC fixture'}},'repository')[0]
    record['evidence_id']='data'
    case=scenario();case['evidence']['records']=[e for e in case['evidence']['records'] if e['evidence_id']!='data']+[record]
    result=fulltext_decision(case['final'],case['evidence'])
    assert result['status']=='confirmed' and result['datasets'][0]['verification_level']=='sample_structure'
    assert result['datasets'][0]['evidence_sha256']==record['payload_sha256']
