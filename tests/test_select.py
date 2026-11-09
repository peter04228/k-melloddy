import copy
import json
from pathlib import Path
import sqlite3
from unittest.mock import patch
import pytest

from k_melloddy.core.storage import digest
from k_melloddy.db_select.engine import Selector
from k_melloddy.db_select.fixtures import make_demo_input,scenario,evidence_record
from k_melloddy.db_select.llm_adapter import FixtureProvider,UnconfiguredProvider
from k_melloddy.db_select.evidence_collector import FixtureEvidenceCollector
from k_melloddy.db_select.decision import fulltext_decision
from k_melloddy.db_select.policy import load_policy
from k_melloddy.db_select.revalidator import valid_initial

POLICY=Path('config/db_select')


def setup(tmp_path,scenarios):
    project,manifest=make_demo_input(tmp_path,'Test',len(scenarios))
    engine=Selector(project/'DB_Select',POLICY,provider=FixtureProvider(scenarios),collector=FixtureEvidenceCollector(scenarios))
    return engine,manifest


@pytest.mark.parametrize('code',[f'E{i:02}' for i in range(1,9)])
def test_exclusions_require_matching_evidence(tmp_path,code):
    c,m=setup(tmp_path,{'1':scenario('excluded',code)})
    try:
        result=c.run(m,export=False)
        assert result['N_excluded']==1 and result['incomplete_count']==0
        record=c.store.records(result['run_id'])['HEART-P000001']
        assert record['final']['code']==code
        if code=='E07':assert record['source_databases'] and not record['datasets']
    finally:c.close()


@pytest.mark.parametrize('code',['P01','P02','P03','P04'])
def test_pending_finite_revalidation(tmp_path,code):
    c,m=setup(tmp_path,{'1':scenario('pending',code)})
    try:
        result=c.run(m,export=False)
        assert result['N_pending']==1 and result['incomplete_count']==0
        record=c.store.records(c.run_id)['HEART-P000001']
        assert record['revalidation']['attempt_count']==1
        c.run(resume=c.run_id,export=False)
        assert c.store.records(c.run_id)['HEART-P000001']['revalidation']['attempt_count']==1
        c.run(resume=c.run_id,revalidate_only=True,export=False)
        assert c.store.records(c.run_id)['HEART-P000001']['revalidation']['attempt_count']==2
        c.run(resume=c.run_id,revalidate_only=True,export=False)
        c.run(resume=c.run_id,revalidate_only=True,export=False)
        assert c.store.records(c.run_id)['HEART-P000001']['revalidation']['attempt_count']==3
    finally:c.close()


def test_first_pass_then_revalidation_and_shared_dataset(tmp_path):
    scenarios={'1':scenario('pending','P01'),'2':scenario(two_datasets=True),'3':scenario()}
    scenarios['1']['revalidated']=scenario()['final']
    c,m=setup(tmp_path,scenarios)
    try:
        result=c.run(m,export=False)
        assert result['N_confirmed']==3 and result['confirmed_dataset_count']==2
        calls=c.provider.calls
        assert calls[:6]==[(f'HEART-P{i:06}',phase) for i in range(1,4) for phase in ['tiab','fulltext']]
        assert calls[6:]==[('HEART-P000001','tiab'),('HEART-P000001','fulltext')]
        records=c.store.records(c.run_id)
        assert records['HEART-P000001']['datasets'][0]['dataset_id']==records['HEART-P000003']['datasets'][0]['dataset_id']
        events=c.store.db.execute("SELECT outcome FROM events WHERE step_id='2.7' AND paper_id='HEART-P000001'").fetchall()
        assert [e[0] for e in events]==['pending','forwarded']
        assert all(e[0]=='qc' for e in c.store.db.execute("SELECT phase FROM events WHERE step_id='2.11'"))
    finally:c.close()


def test_landings_code_only_and_fabrications_rejected():
    for mutation in ['landing','code_only','unobserved_url','bad_quote','unknown_columns','unsupported_counts']:
        s=scenario()
        if mutation in {'landing','code_only'}:s['evidence']['records'][2]['kind']='repository' if mutation=='code_only' else 'landing'
        if mutation=='unobserved_url':s['final']['datasets'][0]['direct_url']='https://invented.invalid/file.csv'
        if mutation=='bad_quote':s['final']['evidence_refs'][0]['quote']='invented evidence'
        if mutation=='unknown_columns':s['evidence']['records'][2]['columns']=['source code']
        if mutation=='unsupported_counts':s['final']['datasets'][0]['compound_count']=123
        with pytest.raises(ValueError):fulltext_decision(s['final'],s['evidence'])


def test_pending_prerequisites_and_exclusion_scope():
    for code in ['P01','P02','P03','P04']:
        s=scenario('pending',code)
        s['evidence']['records']=[]
        with pytest.raises(ValueError):fulltext_decision(s['final'],s['evidence'])
    s=scenario('excluded','E04');s['evidence']['repository_checked']=False
    with pytest.raises(ValueError):fulltext_decision(s['final'],s['evidence'])


def test_doi_failure_pmc_success(tmp_path):
    s=scenario();failed=evidence_record('doi',url='https://doi.invalid/failed')
    failed.update(status='fetch_error',http_status=503,bytes_observed=0,payload_sha256=None,identity_match=False,body_sample_b64=None)
    s['evidence']['records'].insert(0,failed)
    s['evidence']['records'][1].update(url='https://pmc.invalid/article',final_url='https://pmc.invalid/article')
    c,m=setup(tmp_path,{'1':s})
    try:assert c.run(m,export=False)['N_confirmed']==1
    finally:c.close()


def test_revalidation_failure_preserves_pending(tmp_path):
    s=scenario('pending','P01');s['revalidated']=RuntimeError('synthetic model error')
    c,m=setup(tmp_path,{'1':s})
    try:
        r=c.run(m,export=False)
        assert r['N_pending']==1
        record=c.store.records(c.run_id)['HEART-P000001']
        assert record['revalidation']['attempt_count']==1
        ref=record['revalidation']['history_refs'][0]
        history=c.store.read_ref(ref,c.run_id,record)
        assert history['error']=='RuntimeError'
    finally:c.close()


def test_incomplete_initial_blocks_revalidation_then_resume(tmp_path):
    s=scenario();s['final']=RuntimeError('synthetic temporary provider failure')
    c,m=setup(tmp_path,{'1':scenario('pending','P01'),'2':s,'3':scenario()})
    try:
        r=c.run(m,export=False)
        assert r['incomplete_count']==1 and r['status']=='PARTIAL'
        assert c.store.records(c.run_id)['HEART-P000001']['revalidation']['attempt_count']==0
        c.provider.scenarios['2']=scenario()
        r=c.run(resume=c.run_id,export=False)
        assert r['status']=='COMPLETED'
        assert c.store.records(c.run_id)['HEART-P000001']['revalidation']['attempt_count']==1
    finally:c.close()


def test_interruption_and_resume_with_stable_datasets(tmp_path):
    c,m=setup(tmp_path,{'1':scenario(),'2':scenario()})
    original=c.provider.propose
    def interrupt(phase,paper,*args):
        if paper['pmid']=='2':raise KeyboardInterrupt
        return original(phase,paper,*args)
    c.provider.propose=interrupt
    try:
        with pytest.raises(KeyboardInterrupt):c.run(m,export=False)
        run=c.run_id;before=c.store.records(run)['HEART-P000001'];data_id=before['datasets'][0]['dataset_id']
        revisions=[tuple(r) for r in c.store.db.execute('SELECT * FROM revisions ORDER BY rowid')]
        c.provider.propose=original
        result=c.run(resume=run,export=False)
        assert result['N_confirmed']==2
        assert c.store.records(run)['HEART-P000001']==before
        assert c.store.records(run)['HEART-P000002']['datasets'][0]['dataset_id']==data_id
        assert [tuple(r) for r in c.store.db.execute('SELECT * FROM revisions ORDER BY rowid')][:len(revisions)]==revisions
    finally:c.close()


def test_unconfigured_provider_no_fake_success(tmp_path):
    c,m=setup(tmp_path,{'1':scenario()});c.provider=UnconfiguredProvider()
    try:
        with pytest.raises(ValueError,match='not configured'):c.run(m,export=False)
        assert c.status()==[]
    finally:c.close()


def test_policy_change_frozen_resume_and_new_snapshot(tmp_path):
    import shutil,yaml
    policy=tmp_path/'policy';shutil.copytree(POLICY,policy)
    c,m=setup(tmp_path/'data',{'1':scenario()});c.policy_dir=policy
    try:
        first=c.run(m,export=False);sha=c.policy['sha256']
        p=policy/'organs/heart.yaml';values=yaml.safe_load(p.read_text(encoding='utf-8'));values['version']='heart-v2'
        p.write_text(yaml.safe_dump(values,allow_unicode=True),encoding='utf-8')
        c.run(resume=first['run_id'],export=False);assert c.policy['sha256']==sha
        second=c.run(m,export=False);assert c.policy['sha256']!=sha and second['run_id']!=first['run_id']
        assert c.store.records(first['run_id'])['HEART-P000001']['provenance']['organ_policy_version']=='heart-v1'
    finally:c.close()


def test_legacy_r01_not_valid():
    assert not valid_initial({'initial_review_valid':True,'schema_version':'1.0','provenance':{'prompt_version':'r01'},
                              'final':{'status':'pending','code':'P01'},'fulltext':{'status':'reviewed'},'evidence_ref':{'path':'old'}})


def test_descending_pilot_scope_and_resume(tmp_path):
    c,m=setup(tmp_path,{str(i):scenario('excluded','E01') for i in range(1,5)})
    try:
        result=c.run(m,limit=2,order='desc',export=False)
        assert result['input_count']==2
        assert [p['paper_id'] for p in c.papers]==['HEART-P000004','HEART-P000003']
        calls=list(c.provider.calls)
        c.run(resume=c.run_id,export=False)
        assert calls==c.provider.calls
        assert len(c.store.records(c.run_id))==2
        scope=json.loads(c.store.run(c.run_id)['collect_ref'])['selection']
        assert scope['source_count']==4 and scope['limit']==2
    finally:c.close()


def test_collect_manifest_tampering_and_ledger(tmp_path):
    c,m=setup(tmp_path,{'1':scenario()})
    try:
        c.run(m,export=False)
        with pytest.raises(sqlite3.IntegrityError):c.store.db.execute('DELETE FROM events')
        c.store.db.rollback()
        data=json.loads(m.read_text(encoding='utf-8'));data['artifacts'][0]['sha256']='0'*64;m.write_text(json.dumps(data),encoding='utf-8')
        with pytest.raises(ValueError,match='hash mismatch'):c.validate(m)
    finally:c.close()


def test_abstract_absence_vs_fetch_error(tmp_path):
    c,m=setup(tmp_path,{'1':scenario(),'2':scenario()})
    try:
        # Inject source states only at the engine boundary; source manifests are untouched.
        import k_melloddy.db_select.engine as module
        real=module.load_collect
        def source(*args):
            manifest,papers,ref=real(*args)
            papers[0]['abstract_state']='abstract_absent';papers[0]['values']['Abstract']=''
            papers[1]['fetch_state']='pending_retry';papers[1]['abstract_state']='unverified';papers[1]['values']['Abstract']=''
            return manifest,papers,ref
        with patch.object(module,'load_collect',side_effect=source):r=c.run(m,export=False)
        records=c.store.records(c.run_id)
        assert records['HEART-P000001']['final']['code']=='ABSTRACT_ABSENT'
        assert records['HEART-P000002']['final']['status']=='fetch_error'
        assert r['incomplete_count']==1
    finally:c.close()


def test_final_workbook_empty_pending_and_long_text(tmp_path):
    from openpyxl import load_workbook
    c,m=setup(tmp_path,{'1':scenario(),'2':scenario('excluded','E01')})
    try:
        import k_melloddy.db_select.engine as module
        original=module.load_collect
        def source(*args):
            manifest,papers,ref=original(*args)
            papers[0]['values']['Abstract']+='한'*34000
            return manifest,papers,ref
        with patch.object(module,'load_collect',side_effect=source):result=c.run(m,export=False)
        output=Path(c.export(render=False));manifest=json.loads(output.read_text(encoding='utf-8'))
        assert manifest['record_count']==2
        counts={}
        for a in manifest['artifacts']:
            path=c.root/a['path']
            assert digest(path.read_bytes())==a['sha256']
            if path.suffix=='.xlsx':
                wb=load_workbook(path,read_only=False)
                from k_melloddy.db_select.excel_export import SHEETS,template_contract
                assert wb.sheetnames==SHEETS
                for s in wb:counts[s.title]=s.max_row-(2 if s.title==SHEETS[1] else 4)
                assert 'JSON/screening_results.json' in wb[SHEETS[0]]['G5'].value
                assert [s.max_column for s in wb]==[16,15,16,16,16]
                assert [c.value for c in wb[SHEETS[1]][2]]==template_contract()[0]['sheets'][1]['headers']
                wb.close()
        assert counts=={'01_논문스크리닝':2,'02_확정DB':1,'03_확정논문':1,'04_제외논문':1,'05_보류논문':0}
        screening=json.loads((c.root/'JSON/screening_results.json').read_text(encoding='utf-8'))
        assert len(screening['papers'][0]['source_record']['values']['Abstract'])>34000
        assert len(list((c.root/'Output').rglob('*.xlsx')))==1
        assert {p.name for p in (c.root/'JSON').rglob('*.json')}=={'screening_results.json','evidence_log.json','revalidation_history.json'}
    finally:c.close()


def test_evidence_tamper_prevents_export(tmp_path):
    c,m=setup(tmp_path,{'1':scenario()})
    try:
        c.run(m,export=False)
        records=c.store.records(c.run_id)
        records['HEART-P000001']['evidence_ref']['sha256']='0'*64
        with pytest.raises(ValueError,match='hash mismatch'):c.qc(records)
    finally:c.close()


def test_dataset_url_identity_is_case_sensitive():
    from k_melloddy.db_select.dataset_verifier import canonical_identity
    assert canonical_identity('url:https://example.org/Data.csv','v1')!=canonical_identity('url:https://example.org/data.csv','v1')
    assert canonical_identity('https://doi.org/10.9999/DATA','v1')==canonical_identity('doi:10.9999/data','v1')


def test_sqlite_commit_before_cumulative_json_failure(tmp_path):
    c,m=setup(tmp_path,{'1':scenario()})
    from k_melloddy.db_select import persistence
    original=persistence.atomic_json
    def fail(path,*args):
        if Path(path).name=='evidence_log.json' and c.store.db.execute('SELECT COUNT(*) FROM revisions').fetchone()[0]:
            raise KeyboardInterrupt
        return original(path,*args)
    try:
        with patch.object(persistence,'atomic_json',side_effect=fail):
            with pytest.raises(KeyboardInterrupt):c.run(m,export=False)
        run=c.run_id
        assert len(c.store.records(run))==1
        assert c.store.db.execute('SELECT COUNT(*) FROM datasets').fetchone()[0]==1
        with pytest.raises(ValueError):c.store.verify_aggregate(run)
        calls=list(c.provider.calls)
        assert c.run(resume=run,export=False)['N_confirmed']==1
        assert c.provider.calls==calls
        c.store.verify_aggregate(run)
    finally:c.close()


def test_http_collector_mocked_and_no_completeness_claim():
    import io
    from email.message import Message
    from k_melloddy.db_select.evidence_collector import HttpEvidenceCollector,validate_evidence
    class Response(io.BytesIO):
        status=200;url='https://pmc.ncbi.nlm.nih.gov/articles/PMC123/'
        headers=Message();headers['Content-Type']='text/html'
    html=b'<h1>Exact source title</h1><h2>Methods</h2><h2>Results</h2><h2>Data Availability</h2>'
    paper={'pmid':'123','values':{'Title':'Exact source title','DOI':'','PMCID':'PMC123'}}
    with patch('k_melloddy.db_select.evidence_collector.public_url',side_effect=lambda u:u), patch('urllib.request.build_opener') as opener:
        opener.return_value.open.side_effect=lambda *a,**kw:Response(html)
        evidence=validate_evidence(HttpEvidenceCollector().collect(paper,load_policy(POLICY,'Heart')))
    assert evidence['fulltext_reviewed'] is True
    assert evidence['survey_complete'] is False and evidence['repository_checked'] is False


def test_invalid_policies_and_missing_provider_plugins():
    from k_melloddy.db_select.schema import validate,ORGAN
    from k_melloddy.db_select.llm_adapter import load_provider
    p=load_policy(POLICY,'Heart')['organ'];p['keywords']='not a list'
    with pytest.raises(ValueError):validate(p,ORGAN)
    with pytest.raises(ValueError):load_provider('python:not_installed_melloddy_adapter:factory')


def test_extended_liver_policy_and_incomplete_display():
    from k_melloddy.db_select.schema import ORGAN,validate
    from k_melloddy.db_select.excel_export import LABELS
    from k_melloddy.db_select.submitted_review import ReviewIncomplete
    policy=load_policy(POLICY,'Liver')
    assert policy['organ']['version']=='liver-v4'
    assert policy['organ']['pending_revalidation']['P02']
    bad=copy.deepcopy(policy['organ']);bad['decision_notes']='invalid list'
    with pytest.raises(ValueError):validate(bad,ORGAN)
    assert LABELS['fetch_error']=='미확정'
    assert str(ReviewIncomplete('원문 접근 제한'))=='원문 접근 제한'


def test_manifest_identity_mutation(tmp_path):
    from k_melloddy.db_select.metadata import load_collect
    c,m=setup(tmp_path,{'1':scenario()})
    try:
        manifest,papers,ref=load_collect(m,c.root.parent/'DB_Collect')
        c.store.create(manifest,ref,load_policy(POLICY,'Heart'),papers)
        changed=copy.deepcopy(papers);changed[0]['pmid']='777'
        with pytest.raises(ValueError,match='mapping changed'):c.store.create(manifest,ref,load_policy(POLICY,'Heart'),changed)
    finally:c.close()


def test_cumulative_rebuild_sort_and_shared_dataset(tmp_path):
    from k_melloddy.db_select.excel_export import workbook_payload,template_contract
    c,m=setup(tmp_path,{str(i):scenario() for i in range(1,11)})
    try:
        c.run(m,export=False)
        docs=c.store.aggregate(c.run_id)
        before={p.name:p.read_bytes() for p in (c.root/'JSON').glob('*.json')}
        records=c.store.records(c.run_id)
        for name,doc in docs.items():
            assert [int(p['paper_id'].split('-P')[1]) for p in doc['papers']]==sorted(int(p['paper_id'].split('-P')[1]) for p in doc['papers'])
            assert all(doc['index'][p['paper_id']]=={'pmid':p['pmid'],'position':i} for i,p in enumerate(doc['papers']))
        (c.root/'JSON/evidence_log.json').write_text('{}',encoding='utf-8')
        (c.root/'JSON/screening_results.json').unlink()
        c.store.aggregate(c.run_id);c.store.verify_aggregate(c.run_id)
        assert before=={p.name:p.read_bytes() for p in (c.root/'JSON').glob('*.json')}
        sheets,dbs=workbook_payload(c.papers,records,template_contract()[0])
        assert len(dbs)==1 and len(sheets[1]['rows'])==1
        assert sheets[1]['rows'][0][4].split('; ')==[str(i) for i in range(1,11)]
        assert len(sheets[2]['rows'])==10
        assert len(list((c.root/'JSON').rglob('*.json')))==3
    finally:c.close()


def test_legacy_import_preserves_revisions_and_files(tmp_path):
    from k_melloddy.db_select.persistence import SelectionStore
    from k_melloddy.core.storage import dump
    c,m=setup(tmp_path,{'1':scenario('pending','P01')})
    legacy=SelectionStore(tmp_path/'legacy')
    try:
        c.run(m,export=False);run=c.run_id
        # Reconstruct the old on-disk reference format without changing any source rows.
        info=c.store.run(run)
        legacy.db.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?)',tuple(info.values()))
        for row in c.store.db.execute('SELECT * FROM revisions ORDER BY revision'):
            r=json.loads(row['record_json'])
            for ref in [r['evidence_ref'],*r['revalidation']['history_refs']]:
                value=c.store.read_ref(ref)
                if value.get('evidence_ref'):
                    nested=value['evidence_ref'];nested_value=c.store.read_ref(nested)
                    nested.update(legacy.artifact('JSON/Evidence/'+nested['sha256']+'.json',nested_value))
                ref.update(legacy.artifact('JSON/Legacy/'+ref['sha256']+'.json',value))
            ref=legacy.artifact(f'JSON/Screening/{r["revision"]}.json',r)
            legacy.db.execute('INSERT INTO revisions VALUES (?,?,?,?,?,?,?)',(run,r['paper_id'],r['revision'],dump(r),ref['path'],ref['sha256'],row['created_at']))
        legacy.db.execute('INSERT INTO current_records VALUES (?,?,?)',(run,r['paper_id'],r['revision']));legacy.db.commit()
        before={str(p):p.read_bytes() for p in legacy.root.rglob('*.json')}
        revisions=[tuple(r) for r in legacy.db.execute('SELECT * FROM revisions')]
        docs=legacy.aggregate(run);legacy.aggregate(run)
        assert all(Path(p).read_bytes()==data for p,data in before.items())
        assert revisions==[tuple(r) for r in legacy.db.execute('SELECT * FROM revisions')]
        assert len(docs['revalidation_history.json']['papers'][0]['attempts'])==1
        assert not docs['revalidation_history.json']['papers'][0]['interrupted_attempts']
        assert legacy.records(run)[r['paper_id']]['final']['code']=='P01'
    finally:legacy.close();c.close()
