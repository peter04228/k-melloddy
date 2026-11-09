import copy,json
from pathlib import Path
from unittest.mock import patch
import pytest
from k_melloddy.db_select.data_observations import validate_observations,screening_data_cells,enrich_existing,source_observations
from k_melloddy.db_select.excel_export import paper_row
from k_melloddy.db_select.fixtures import scenario,make_demo_input,evidence_record
from k_melloddy.db_select.verified_workflow import VerifiedSelector
from k_melloddy.db_select.llm_adapter import FixtureProvider


def fact(**kwargs):
    result={'name':'GEO','relationship':'reuse','public_status':'reported_public','verification_level':'mentioned','url':None,
        'evidence_refs':[{'evidence_id':'tiab','quote':'Public GEO data were reused.'}]}
    result.update(kwargs);return result


@pytest.mark.parametrize('status,code',[('pending','P02'),('excluded','E01'),('excluded','E07')])
def test_known_data_is_shown_independently_of_final_status(status,code):
    p={'paper_id':'Liver-15752','pmid':'123','values':{'Title':'Study','Abstract':'Public GEO data were reused.'}}
    r={'tiab':{'decision':'candidate'},'final':{'status':status,'code':code,'reason':'fixture'},'data_observations':[fact()]}
    row=paper_row(p,r)
    assert len(row)==16 and row[9]=='GEO' and row[10]=='기존 DB 재사용'
    assert '다운로드 미검증' in row[11] and row[12]=='미확인'
    if code=='E01':assert 'TI/AB 제외' in row[11]


def test_unknown_is_not_claimed_absent_or_downloadable():
    cells=screening_data_cells({'final':{'status':'excluded','code':'E02'}})
    assert cells[0]==cells[1]==cells[3]=='미확인'
    assert '검증 미수행' in cells[2] and '존재하지 않음' not in cells[2]


@pytest.mark.parametrize('fault',['invented_name','invented_url','article_url','overstated_download'])
def test_unsupported_observations_are_rejected(fault):
    p={'values':{'Title':'Study','Abstract':'Public GEO data were reused.'}};f=fact();e=evidence_record('ft',text='GEO data',url='https://publisher.test/article')
    if fault=='invented_name':f['name']='Invented DB'
    elif fault=='invented_url':f['url']='https://example.test/guessed.csv'
    elif fault=='article_url':f['url']=e['url'];f['evidence_refs']=[{'evidence_id':'ft','quote':'GEO data'}]
    else:f['verification_level']='full_file'
    with pytest.raises(ValueError):validate_observations([f],p,{'records':[e]})


def test_verified_repository_link_reaches_m_without_inclusion():
    e=evidence_record('repo','repository',text='GEO record',url='https://repository.test/observed-record')
    f=fact(public_status='verified_public',verification_level='landing_page',url=e['url'],evidence_refs=[{'evidence_id':'repo','quote':'GEO record'}])
    validate_observations([f],{'values':{'Title':'Study','Abstract':''}},{'records':[e]})
    cells=screening_data_cells({'final':{'status':'pending','code':'P03'},'data_observations':[f]})
    assert cells[3]==e['url'] and '파일 미검증' in cells[2]
    assert '전체 파일' not in cells[2]
    sources=source_observations({'source_databases':[{'name':'GEO','url':e['url'],'evidence_refs':f['evidence_refs']}]},{'records':[e]})
    assert sources[0]['url']==e['url']


def test_legacy_article_source_url_is_not_a_data_link():
    r={'final':{'status':'excluded','code':'E07'},'source_databases':[{'name':'GEO','url':'https://doi.org/article'}]}
    assert screening_data_cells(r)[3]=='미확인'


def test_enrichment_preserves_decision_and_is_idempotent(tmp_path):
    project,m=make_demo_input(tmp_path,'Enrich',1)
    class Verifier:
        def verify(self,p):return {'status':'verified','verified_metadata':dict(p['values'],PMID=p['pmid']),'mismatches':{}}
    c=VerifiedSelector(project/'DB_Select',Path('config/db_select'),provider=FixtureProvider({'1':scenario('excluded','E01')}),verifier=Verifier())
    try:
        c.run(m,export=False);run=c.run_id;before=next(iter(c.store.records(run).values()))
        f=fact(name='SYNTHETIC',public_status='unknown',evidence_refs=[{'evidence_id':'tiab','quote':'SYNTHETIC drug toxicity data for testing only.'}])
        path=tmp_path/'observations.json';path.write_text(json.dumps({'run_id':run,'papers':{before['paper_id']:{'pmid':before['pmid'],'data_observations':[f]}}}),encoding='utf8')
        with patch.object(c,'export',return_value='offline-fixture'):
            result=enrich_existing(c,run,path)
            assert result['enriched_papers']==[before['paper_id']]
            after=c.store.records(run)[before['paper_id']]
            assert after['final']==before['final'] and after['revalidation']==before['revalidation']
            assert after['source_record']==before['source_record'] and after['revision']==before['revision']+1
            assert enrich_existing(c,run,path)['enriched_papers']==[]
        docs=c.store.verify_aggregate(run)
        assert docs['screening_results.json']['papers'][0]['data_observations']==[f]
        assert any(x['content'].get('annotation_type')=='data_observations' for x in docs['evidence_log.json']['papers'][0]['entries'])
    finally:c.close()
