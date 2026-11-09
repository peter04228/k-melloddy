"""Standalone table identity must come from captured official article metadata."""
import base64
import copy
import pytest
from k_melloddy.core.storage import digest
from k_melloddy.db_select.full_workflow_access import recover_typographic_identity
from k_melloddy.db_select.html_table_review import selected_html_tables


PAPER={'values':{'Title':'Drug-induced liver injury.','DOI':'10.1234/example','PMCID':'PMC12345'}}
URL='https://pmc.ncbi.nlm.nih.gov/articles/PMC12345/table/T2/'
HTML='''<html><head><meta name="og:title" content="The Drug-induced liver injury">
<meta name="og:url" content="https://pmc.ncbi.nlm.nih.gov/articles/PMC12345/">
</head><body><a href="https://pmc.ncbi.nlm.nih.gov/articles/PMC12345/">View full-text</a>
<a href="https://doi.org/10.1234/example">10.1234/example</a>
<table><thead><tr><th>Drug</th><th>ALT</th></tr></thead><tbody>
<tr><td>Observed A</td><td>222</td></tr></tbody></table></body></html>'''


def record(html=HTML):
    raw=html.encode()
    return dict(evidence_id='table',kind='fulltext',status='fetch_error',identity_match=False,
                failure_reason='article_identity_not_verified',http_status=200,complete_body=True,
                url=URL,final_url=URL,body_sample_b64=base64.b64encode(raw).decode(),
                bytes_observed=len(raw),payload_sha256=digest(raw),text='Table2 DOI10.1234/example',
                identity_checks={'title':False,'doi':True},format='text/html',columns=[])


def test_official_table_metadata_recovers_identity_and_keeps_original_bytes():
    original=record();before=copy.deepcopy(original)
    derived=recover_typographic_identity(PAPER,copy.deepcopy(original))
    assert original==before and derived['identity_match']
    assert derived['table_article_metadata']['scope']=='standalone table; not full article review'
    assert derived['prior_classification']['status']=='fetch_error'
    for key in ['body_sample_b64','payload_sha256','bytes_observed','text','url','http_status']:
        assert derived[key]==original[key]
    bundle=selected_html_tables({'records':[derived]},[{'parent_evidence_id':'table','table_index':0}])
    assert bundle['records'][-1]['columns']==['Drug','ALT']
    assert bundle['records'][-1]['downloaded_full_dataset'] is False
    assert not derived.get('fulltext_reviewed',False)


def test_same_title_words_and_relative_official_parent_link_are_supported():
    html=HTML.replace('The Drug-induced liver injury','The Drug Induced Liver Injury')
    html=html.replace('href="https://pmc.ncbi.nlm.nih.gov/articles/PMC12345/"','href="/articles/PMC12345/"')
    assert recover_typographic_identity(PAPER,record(html))['identity_match']


@pytest.mark.parametrize('field,value',[
    ('url',URL.replace('pmc.ncbi.nlm.nih.gov','example.org')),
    ('final_url',URL.replace('PMC12345','PMC99999')),
    ('url',URL+'?changed=true'),('final_url',URL+'#changed'),
    ('url',URL.replace('https:','http:')),('url',URL.replace('/T2/','/T3/')),
    ('complete_body',False),('http_status',403),('bytes_observed',1),
    ('payload_sha256','changed'),('body_sample_b64','invalid'),
    ('status','access_restricted'),('failure_reason','recaptcha'),('kind','repository'),
])
def test_untrusted_or_incomplete_responses_never_recover(field,value):
    e=record();e[field]=value
    assert not recover_typographic_identity(PAPER,e)['identity_match']


@pytest.mark.parametrize('before,after',[
    ('The Drug-induced liver injury','Different paper'),
    ('10.1234/example','10.1234/example-extra'),
    ('content="https://pmc.ncbi.nlm.nih.gov/articles/PMC12345/"','content="https://pmc.ncbi.nlm.nih.gov/articles/PMC99999/"'),
    ('<a href="https://pmc.ncbi.nlm.nih.gov/articles/PMC12345/">','<a href="https://example.org/">'),
    ('</head>','<meta name="og:title" content="Different paper"></head>'),
    ('</head>','<meta name="og:url" content="https://example.org/"></head>'),
    ('</body>','<a href="https://doi.org/10.1234/other">other</a></body>'),
])
def test_mismatched_duplicate_or_missing_identity_cannot_pass(before,after):
    assert not recover_typographic_identity(PAPER,record(HTML.replace(before,after)))['identity_match']


@pytest.mark.parametrize('field,value',[('PMCID',''),('PMCID','PMC99999'),('DOI',''),('Title','Different study')])
def test_official_paper_identifiers_are_required(field,value):
    paper=copy.deepcopy(PAPER);paper['values'][field]=value
    assert not recover_typographic_identity(paper,record())['identity_match']
