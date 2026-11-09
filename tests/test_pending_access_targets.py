"""Offline regressions for actual focused request dispatch, not scientific counts."""
import copy
import pytest
from k_melloddy.db_select.full_workflow_access import FullWorkflowAccess,pending_access_targets


def failed(url,kind='fulltext'):
    return dict(url=url,kind=kind,status='access_restricted',identity_match=False)


def test_p02_prioritizes_supplement_discovered_after_initial_collection():
    records=[failed(f'https://example.org/article/{i}') for i in range(4)]
    known=[failed('https://example.org/supplement.docx','supplementary')]
    before=copy.deepcopy((records,known))
    targets=pending_access_targets(records,known,'P02')
    assert targets==[(known[0]['url'],'supplementary')]+[(e['url'],'fulltext') for e in records[:3]]
    assert (records,known)==before


def test_successful_same_material_is_not_retried_but_metadata_does_not_mask_failure():
    old=failed('https://example.org/supplement.docx','supplementary')
    assert pending_access_targets([old,dict(old,status='accessible')],[old],'P02')==[]
    assert pending_access_targets([old,dict(old,kind='metadata',status='accessible')],[old],'P02')==[(old['url'],'supplementary')]


@pytest.mark.parametrize('code',['P01','P03','P04'])
def test_other_pending_codes_keep_existing_material_order_and_limit(code):
    records=[dict(failed('https://example.org/'+kind,kind),status='accessible') for kind in ['repository','supplementary','landing','file','api']]
    assert pending_access_targets(records,[failed('https://example.org/other','supplementary')],code)==[(e['url'],e['kind']) for e in records[:4]]


def test_unobserved_routes_are_not_invented_and_duplicate_routes_are_requested_once():
    e=failed('https://example.org/supplement.docx','supplementary')
    assert pending_access_targets([e,e],[e],'P02')==[(e['url'],'supplementary')]
    assert pending_access_targets([],[],'P02')==[]


def test_deep_collector_performs_fresh_supplement_request_from_prior_review(monkeypatch):
    records=[dict(failed(f'https://example.org/article/{i}'),evidence_id='old-'+str(i)) for i in range(4)]
    initial={'records':records,'search_coverage':[]}
    before=copy.deepcopy(initial)
    class Engine:
        def cached(self,paper,key,producer,round_number=None):
            assert key=='collected_evidence' and round_number==1
            return copy.deepcopy(initial)
    access=FullWorkflowAccess();access.engine=Engine();calls=[]
    def request(url,kind,paper,route):
        calls.append((url,kind,route))
        if kind=='metadata':return []
        return [dict(failed(url,kind),evidence_id='fresh-'+str(len(calls)),route=route)]
    monkeypatch.setattr(access,'request',request)
    url='https://example.org/supplement.docx'
    paper={'values':{'DOI':'10.1234/offline','Title':'Synthetic offline article'}}
    result=access.collect(paper,{},dict(phase='revalidation',pending_code='P02',known_records=[failed(url,'supplementary')]))
    focused=[x for x in calls if x[2]=='focused_P02']
    assert focused[0]==(url,'supplementary','focused_P02') and len(focused)==4
    fresh=next(e for e in result['records'] if e['url']==url)
    assert fresh['evidence_id'].startswith('fresh-') and not fresh.get('reused_from_prior_round')
    assert all(e.get('reused_from_prior_round') for e in result['records'][:4])
    assert initial==before
    assert any(x[2]=='deep_Crossref_discovery' for x in calls)
