from k_melloddy.db_select.access_workflow import access_pending
from k_melloddy.db_select.revalidation_access import verification_state
import pytest


@pytest.mark.parametrize('constraints,expected',[
    ({'summary':'verified summary','reason':'older reason'},'verified summary'),
    ({'reason':'actual blocked file'},'actual blocked file'),
    ({'evidence_refs':[]},'unknown')])
def test_verification_state_keeps_reviewed_web_access_and_constraint_alias(constraints,expected):
    excerpt=dict(evidence_id='reviewed',kind='fulltext',status='accessible',identity_match=True,
        url='https://pmc.ncbi.nlm.nih.gov/articles/PMC1/',timestamp='2026-11-08T00:00:00Z',
        http_status=None,text='Reviewer paraphrase of actually inspected article.',
        transport='web_tool',format='reviewer_excerpt',complete_body=False)
    bundle=dict(records=[excerpt],fulltext_reviewed=True,
        session_review=dict(answer_sha256='accepted-answer',access_constraints=constraints))
    state=verification_state({},bundle,{'final':{'status':'pending','reason':'File not verified'}})
    assert state['license_or_access_constraints']==expected
    assert state['full_text_access'] is True
    assert state['verification_evidence']==['reviewed']
    assert state['verification_attempts'][0]['action']=='reviewed web-tool excerpt'
    assert state['verification_attempts'][0]['http_status'] is None
    bundle['fulltext_reviewed']=False
    assert verification_state({},bundle,{})['full_text_access']=='unknown'


def test_supplement_access_requires_citation_named_url_and_actual_retry():
    body={'evidence_id':'body','kind':'fulltext','status':'accessible','identity_match':True,
          'url':'https://institution.example/article','text':'<article><body><sec><p>Supplementary data at publisher.</p></sec></body></article>',
          'route':'institution','attempt':1}
    blocked={'evidence_id':'blocked','kind':'fulltext','status':'access_restricted','url':'https://publisher.example/article','route':'reviewer_additional_route','attempt':2}
    constraints={'evidence_refs':[{'evidence_id':'body','quote':'Supplementary data at publisher.'}],
                 'blocked_material_urls':[blocked['url']]}
    bundle={'records':[body,blocked],'fulltext_reviewed':True,'supplementary_checked':False,
            'alternative_search_completed':True,'session_review':{'access_constraints':constraints}}
    assert access_pending(bundle)
    blocked['attempt']=1
    assert not access_pending(bundle)
    blocked['attempt']=2;constraints['blocked_material_urls']=['https://invented.example/file']
    assert not access_pending(bundle)
    constraints['blocked_material_urls']=[blocked['url']];constraints['evidence_refs'][0]['quote']='Invented quote'
    assert not access_pending(bundle)
