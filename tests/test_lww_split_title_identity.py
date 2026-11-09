"""Publisher split headings require complete trusted bytes and exact title words."""
import base64
import copy
import pytest
from k_melloddy.core.storage import digest
from k_melloddy.db_select.full_workflow_access import recover_typographic_identity

DOI='10.1097/gme.example'
URL='https://journals.lww.com/menopausejournal/fulltext/'+DOI+'~study-title'
PAPER={'values':{'Title':'Study title: findings and limitations.','DOI':DOI,'PMCID':''}}
HTML='<meta property="og:url" content="'+URL+'"><h1 id="omni-article-title">Study <span>title</span></h1><h2 id="omni-article-sub-title">Findings and limitations</h2>'


def record(html=HTML):
    raw=html.encode()
    return dict(kind='fulltext',status='fetch_error',failure_reason='article_identity_not_verified',
                identity_match=False,http_status=200,complete_body=True,url='https://doi.org/'+DOI,
                final_url=URL,body_sample_b64=base64.b64encode(raw).decode(),bytes_observed=len(raw),
                payload_sha256=digest(raw),text='Study title Findings and limitations DOI '+DOI,
                identity_checks={'title':False,'doi':True})


def test_split_title_recovers_only_identity_and_preserves_transport():
    e=record();before=copy.deepcopy(e);recover_typographic_identity(PAPER,e)
    assert e['identity_match'] and e['identity_recovery']=='official_LWW_split_title_and_verified_DOI'
    assert e['article_heading_metadata']['subtitle']=='Findings and limitations'
    assert e['prior_classification']['status']=='fetch_error'
    for k in ['text','body_sample_b64','bytes_observed','payload_sha256','url','final_url','http_status']:
        assert e[k]==before[k]
    assert not e.get('fulltext_reviewed') and not e.get('downloaded_full_dataset')


def test_same_publisher_url_and_same_words_punctuation_are_accepted():
    e=record();e['url']=URL
    assert recover_typographic_identity(PAPER,e)['identity_match']


@pytest.mark.parametrize('field,value',[
    ('status','access_restricted'),('failure_reason','recaptcha'),('http_status',403),
    ('complete_body',False),('kind','metadata'),('bytes_observed',1),('payload_sha256','wrong'),
    ('body_sample_b64','invalid'),('url','https://example.org/'+DOI),
    ('url','https://doi.org/'+DOI+'-wrong'),('final_url',URL+'?changed=true'),
    ('final_url',URL.replace('journals.lww.com','example.org')),('final_url',URL.replace(DOI,DOI+'-wrong')),
    ('text','Different DOI 10.1097/another')])
def test_wrong_incomplete_or_restricted_record_cannot_recover(field,value):
    e=record();e[field]=value
    assert not recover_typographic_identity(PAPER,e)['identity_match']


@pytest.mark.parametrize('before,after',[
    ('Findings and limitations','Findings and different limitations'),
    ('omni-article-sub-title','another-subtitle'),
    ('<h1 id="omni-article-title">','<h1 id="wrong">'),
    (URL,URL+'-wrong'),
    ('</h2>','</h2><h2 id="omni-article-sub-title">Another</h2>'),
    ('</h2>','</h2><meta property="og:url" content="'+URL+'">'),
    ('</h1>',''),
])
def test_different_words_ambiguous_metadata_or_malformed_headings_fail(before,after):
    assert not recover_typographic_identity(PAPER,record(HTML.replace(before,after)))['identity_match']


@pytest.mark.parametrize('field,value',[('DOI',''),('Title','Study title: other findings.'),('DOI','10.1097/other')])
def test_official_metadata_required(field,value):
    paper=copy.deepcopy(PAPER);paper['values'][field]=value
    assert not recover_typographic_identity(paper,record())['identity_match']
