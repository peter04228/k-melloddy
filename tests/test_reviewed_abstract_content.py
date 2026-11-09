import copy

from k_melloddy.db_select.access_workflow import access_pending
from k_melloddy.db_select.fixtures import scenario
from k_melloddy.db_select.full_workflow import SessionProvider
from k_melloddy.db_select.revalidation_access import body_requires_review, readable_body, verification_state


def setup_review():
    bundle=copy.deepcopy(scenario('pending','P02')['evidence'])
    bundle['alternative_search_completed']=True
    article=bundle['records'][0]
    article.update(status='accessible',identity_match=True,http_status=200,attempt=2,
        text='Abstract: WikiPathways. Recommended books: Novel Extraction Methods '
             'for Herbal Products. '+'Catalogue descriptions. '*30)
    bundle['records'][1]['attempt']=2
    answer={'reviewer_note':'Reviewed abstract and unrelated book menu.',
        'evidence_review':{'content_access_review':[{'classification':'abstract_only',
            'reference':{'evidence_id':article['evidence_id'],'quote':'WikiPathways'}}]}}
    provider=object.__new__(SessionProvider)
    provider.response=lambda *args:answer
    return bundle,provider


def test_cited_abstract_overrides_menu_without_changing_capture_or_claiming_body():
    original,provider=setup_review()
    assert readable_body(original['records'][0])
    reviewed=provider._review_evidence({}, {}, original, None)
    assert not readable_body(reviewed['records'][0])
    assert not body_requires_review(reviewed['records'][0])
    assert access_pending(reviewed)
    assert 'reviewed_content' not in original['records'][0]
    assert original['records'][0]['text']==reviewed['records'][0]['text']
    assert reviewed['records'][0]['status']=='accessible'
    state=verification_state({},reviewed,{'final':{'status':'pending'}})
    assert state['full_text_access'] is not True
    assert state['full_text_reviewed'] is False


def test_another_genuine_unreviewed_body_still_blocks_p02():
    original,provider=setup_review()
    body=copy.deepcopy(original['records'][0])
    body.update(evidence_id='actualbody',url='https://article.invalid/full',
        final_url='https://article.invalid/full',text='Methods '+'Actual study prose. '*40)
    original['records'].append(body)
    reviewed=provider._review_evidence({}, {}, original, None)
    assert body_requires_review(reviewed['records'][-1])
    assert not access_pending(reviewed)


def test_abstract_review_does_not_replace_search_or_retried_failure():
    original,provider=setup_review()
    original['alternative_search_completed']=False
    assert not access_pending(provider._review_evidence({}, {}, original, None))
    original['alternative_search_completed']=True
    original['records'][1]['attempt']=1
    assert not access_pending(provider._review_evidence({}, {}, original, None))
    original['records']=original['records'][:1]
    assert not access_pending(provider._review_evidence({}, {}, original, None))


def test_uncited_or_wrong_record_marker_cannot_hide_body():
    original,_=setup_review()
    article=original['records'][0]
    for ref in [{}, {'evidence_id':'different','quote':'WikiPathways'},
                {'evidence_id':article['evidence_id'],'quote':'not present'}]:
        candidate=copy.deepcopy(article)
        candidate['reviewed_content']={'classification':'abstract_only','reference':ref}
        assert readable_body(candidate)
        assert body_requires_review(candidate)


def test_cited_abstract_is_not_reintroduced_by_xml_fallback():
    original,provider=setup_review()
    original['records'][0]['text']='<body><sec><p>WikiPathways '+'Preview text. '*40+'</p></sec></body>'
    assert body_requires_review(original['records'][0])
    reviewed=provider._review_evidence({}, {}, original, None)
    assert not readable_body(reviewed['records'][0])
    assert not body_requires_review(reviewed['records'][0])
