import base64
import copy
import json

import pytest

from k_melloddy.core.storage import digest
from k_melloddy.db_select.manuscript_binding import bind_manuscripts


def fixture(front_doi='',author_label='Authors: Kevin Wing1 Ian Douglas2',surnames=None):
    fitz=pytest.importorskip('fitz')
    title='Development of predictive tests: a concept paper on routine records'
    doc=fitz.open();page=doc.new_page()
    page.insert_text((40,40),title);page.insert_text((40,60),author_label)
    if front_doi:page.insert_text((40,80),front_doi)
    raw=doc.tobytes()
    from pypdf import PdfReader
    import io
    text='\n'.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(raw)).pages)
    pdf=dict(evidence_id='pdf',kind='fulltext',status='fetch_error',failure_reason='article_identity_not_verified',
        http_status=200,complete_body=True,url='https://university.example/paper.pdf',
        final_url='https://university.example/paper.pdf',body_sample_b64=base64.b64encode(raw).decode(),
        bytes_observed=len(raw),payload_sha256=digest(raw),text=text,identity_match=False)
    paper=dict(pmid='1',values={'DOI':'10.1234/test','Title':'Development of predictive tests: routine records.'})
    hit=dict(id='1',source='MED',doi='10.1234/test',title=paper['values']['Title'],
        fullTextUrlList={'fullTextUrl':[dict(documentStyle='pdf',availabilityCode='F',url=pdf['url'])]},
        authorList={'author':[{'lastName':n} for n in (surnames or ['Wing','Douglas'])]})
    rawmeta=json.dumps({'resultList':{'result':[hit]}}).encode()
    url='https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=EXT_ID:1'
    meta=dict(evidence_id='meta',kind='metadata',status='accessible',http_status=200,complete_body=True,
        url=url,final_url=url,body_sample_b64=base64.b64encode(rawmeta).decode(),
        bytes_observed=len(rawmeta),payload_sha256=digest(rawmeta))
    selection=dict(pdf_evidence_id='pdf',metadata_evidence_id='meta',manuscript_title=title,
                   title_quote=title,reviewer_note='Explicit editorial-subtitle comparison.')
    return paper,{'records':[pdf,meta]},selection


def test_exact_official_link_binds_version_without_changing_original():
    paper,bundle,selection=fixture();original=copy.deepcopy(bundle)
    result=bind_manuscripts(paper,bundle,[selection]);bound=result['records'][-1]
    assert bundle==original and bound['identity_match'] is True
    assert bound['text']==bundle['records'][0]['text']
    assert bound['parent_evidence_id']=='pdf' and bound['request_performed'] is False
    assert bound['prior_identity_classification']['status']=='fetch_error'


@pytest.mark.parametrize('change',['doi','url','title','author','hash','not_free','no_note'])
def test_unbound_or_mismatched_manuscripts_are_rejected(change):
    paper,bundle,selection=fixture();meta=bundle['records'][1]
    raw=json.loads(base64.b64decode(meta['body_sample_b64']));hit=raw['resultList']['result'][0]
    if change=='doi':hit['doi']='10.1234/another'
    if change=='url':hit['fullTextUrlList']['fullTextUrl'][0]['url']='https://university.example/other.pdf'
    if change=='title':selection['manuscript_title']='Different paper: routine records'
    if change=='author':hit['authorList']['author'].append({'lastName':'MissingAuthor'})
    if change=='not_free':hit['fullTextUrlList']['fullTextUrl'][0]['availabilityCode']='S'
    if change=='no_note':selection['reviewer_note']=''
    data=json.dumps(raw).encode();meta.update(body_sample_b64=base64.b64encode(data).decode(),bytes_observed=len(data),payload_sha256=digest(data))
    if change=='hash':bundle['records'][0]['payload_sha256']='0'*64
    with pytest.raises(ValueError):bind_manuscripts(paper,bundle,[selection])


def test_conflicting_front_page_doi_is_rejected():
    paper,bundle,selection=fixture('doi:10.1234/conflicting')
    with pytest.raises(ValueError,match='Conflicting'):bind_manuscripts(paper,bundle,[selection])


def test_unicode_spacing_in_multiword_surname_is_compared_without_changing_names():
    paper,bundle,selection=fixture(author_label='Authors: Tjeerd van Staa1 Ian Douglas2',
        surnames=['van\u00a0Staa','Douglas'])
    assert bind_manuscripts(paper,bundle,[selection])['records'][-1]['identity_match'] is True
