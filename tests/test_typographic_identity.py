from k_melloddy.db_select.full_workflow_access import recover_typographic_identity


def test_recovery_requires_complete_matching_title_and_doi():
    p={'values':{'Title':'Drug-induced injury.','DOI':'10.1234/test'}}
    def record(**kw):
        return dict(kind='fulltext',failure_reason='article_identity_not_verified',complete_body=True,
                    http_status=200,status='fetch_error',text='Drug\u2010induced injury DOI: 10.1234/test',**kw)
    e=record();assert recover_typographic_identity(p,e)['identity_match']
    assert e['prior_classification']['status']=='fetch_error'
    for field,value in [('text','Other study DOI: 10.1234/test'),('text','Drug-induced injury DOI: 10.1234/other'),
                         ('complete_body',False),('failure_reason','client challenge'),('http_status',403)]:
        e=record();e[field]=value
        assert recover_typographic_identity(p,e)['status']=='fetch_error'
def test_translated_title_wrapper_requires_same_words_doi_and_verified_pmid():
    import copy
    paper={'values':{'Title':'[Herbal preparations and liver injury].','DOI':'10.1234/test'}}
    source={'kind':'fulltext','status':'fetch_error','failure_reason':'article_identity_not_verified',
            'complete_body':True,'http_status':200,'identity_match':False,
            'identity_checks':{'pmid':True},
            'text':'Herbal preparations and liver injury. DOI:10.1234/test'}
    e=recover_typographic_identity(paper,copy.deepcopy(source))
    assert e['identity_match'] and e['prior_classification']['status']=='fetch_error'
    assert source['identity_match'] is False
    for replacement in [{'identity_checks':{'pmid':False}},
                        {'text':'Other herbal study DOI:10.1234/test'},
                        {'text':'Herbal preparations and liver injury DOI:10.1234/wrong'},
                        {'complete_body':False}]:
        e=dict(copy.deepcopy(source),**replacement)
        assert not recover_typographic_identity(paper,e)['identity_match']
