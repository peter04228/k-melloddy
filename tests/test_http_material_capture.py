import base64
import copy

import pytest

from k_melloddy.core.storage import digest,dump
from k_melloddy.db_select.http_material_capture import append_http_materials
from k_melloddy.db_select.html_table_review import selected_html_tables


def fixture(tmp_path):
    url='https://pmc.ncbi.nlm.nih.gov/articles/PMC12345/table/T2/'
    html='''<html><head><meta property="og:title" content="Drug-induced liver injury">
    <meta property="og:url" content="https://pmc.ncbi.nlm.nih.gov/articles/PMC12345/">
    </head><body><a href="/articles/PMC12345/">Article</a>
    <a href="https://doi.org/10.1234/example">DOI</a>
    <table><thead><tr><th>Drugs</th><th>Liver injury</th><th>Causality score</th></tr></thead>
    <tbody><tr><td>A + B</td><td>Mixed</td><td>Unlikely</td></tr>
    <tr><td>C</td><td>Cholestatic</td><td>Possible</td></tr></tbody></table></body></html>'''
    raw=html.encode()
    e=dict(evidence_id='manual-file',url=url,final_url=url,kind='file',
        timestamp='2026-11-09T00:00:00+00:00',status='accessible',text='Actual Table 2',
        level='response_sample',identity_match=False,sections=[],format='text/html',columns=[],
        payload_sha256=digest(raw),bytes_observed=len(raw),http_status=200,
        complete_body=True,body_sample_b64=base64.b64encode(raw).decode(),
        legal_access='public_request',failure_reason='')
    failed=copy.deepcopy(e);failed.update(evidence_id='native-failure',status='access_restricted',
        text='',body_sample_b64='',bytes_observed=0,http_status=403,failure_reason='HTTP_403')
    bundle=dict(records=[failed],fulltext_reviewed=False,sections_checked=[],
        supplementary_checked=False,repository_checked=False,survey_complete=False,collector='fixture')
    paper=dict(paper_id='Fixture-00001',pmid='1',_official_verified=True,
        values={'Title':'Drug-induced liver injury.','DOI':'10.1234/example','PMCID':'PMC12345'})
    capture=dict(paper_id=paper['paper_id'],pmid=paper['pmid'],reviewer_note='Actual fixture GET receipt.',record=e)
    return paper,bundle,capture


def append(tmp_path,paper,bundle,capture):
    raw=dump(capture).encode();(tmp_path/'receipt.json').write_bytes(raw)
    return append_http_materials(tmp_path,paper,bundle,[dict(path='receipt.json',sha256=digest(raw))])


def test_successful_get_is_reused_without_erasing_failed_attempt_or_claiming_structure(tmp_path):
    paper,bundle,capture=fixture(tmp_path);before=copy.deepcopy(bundle)
    result=append(tmp_path,paper,bundle,capture);e=result['records'][-1]
    assert bundle==before and result['records'][0]==before['records'][0]
    assert e['original_evidence_id']=='manual-file' and e['source_request_performed']
    assert e['request_performed'] is False and e['kind']=='file'
    assert e['columns']==[] and e['level']=='response_sample'
    assert e['downloaded_full_dataset'] is False and result['fulltext_reviewed'] is False
    assert append(tmp_path,paper,result,capture)==result
    selected=selected_html_tables(result,[dict(parent_evidence_id=e['evidence_id'],table_index=0)],paper=paper)
    table=selected['records'][-1]
    assert result['records'][-1]==e and e['identity_match'] is False
    assert table['columns']==['Drugs','Liver injury','Causality score']
    assert 'A + B' in table['text'] and 'Unlikely' in table['text'] and 'Possible' in table['text']
    assert table['source_kind']=='file' and table['payload_sha256']==e['payload_sha256']
    assert table['table_article_metadata']['scope']=='standalone table; not full article review'
    assert table['downloaded_full_dataset'] is False and selected['fulltext_reviewed'] is False


@pytest.mark.parametrize('change',['paper','pmid','post','auth','failed','truncated','bytes','hash','url','private','web'])
def test_untrusted_or_unobserved_get_receipts_are_rejected(tmp_path,change):
    paper,bundle,capture=fixture(tmp_path);e=capture['record']
    if change=='paper':capture['paper_id']='other'
    if change=='pmid':capture['pmid']='2'
    if change=='post':e['request_method']='POST'
    if change=='auth':e['legal_access']='authenticated'
    if change=='failed':e['status']='access_restricted'
    if change=='truncated':e['complete_body']=False
    if change=='bytes':e['bytes_observed']=1
    if change=='hash':e['payload_sha256']='changed'
    if change=='url':e['url']='https://example.org/unobserved'
    if change=='private':e['final_url']='http://127.0.0.1/file'
    if change=='web':e['transport']='web_tool'
    with pytest.raises(ValueError):append(tmp_path,paper,bundle,capture)


@pytest.mark.parametrize('field,value',[('Title','Other study'),('DOI','10.1234/other'),('PMCID','PMC99999')])
def test_imported_file_table_must_match_verified_official_article(tmp_path,field,value):
    paper,bundle,capture=fixture(tmp_path);result=append(tmp_path,paper,bundle,capture)
    paper['values'][field]=value
    with pytest.raises(ValueError,match='official PMC table'):
        selected_html_tables(result,[dict(parent_evidence_id=result['records'][-1]['evidence_id'],table_index=0)],paper=paper)


def test_capture_hash_scope_and_official_verification_are_required(tmp_path):
    paper,bundle,capture=fixture(tmp_path);result=append(tmp_path,paper,bundle,capture)
    with pytest.raises(ValueError,match='changed'):
        append_http_materials(tmp_path,paper,bundle,[dict(path='receipt.json',sha256='changed')])
    with pytest.raises(ValueError,match='outside'):
        append_http_materials(tmp_path,paper,bundle,[dict(path='../outside.json',sha256='changed')])
    paper['_official_verified']=False
    with pytest.raises(ValueError,match='official PMC table'):
        selected_html_tables(result,[dict(parent_evidence_id=result['records'][-1]['evidence_id'],table_index=0)],paper=paper)
