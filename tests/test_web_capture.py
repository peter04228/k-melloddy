import copy
import json
import pytest
from k_melloddy.core.storage import digest, dump
from k_melloddy.db_select.web_capture import append_captures, validate_web_capture
from k_melloddy.db_select.evidence_collector import validate_evidence


def fixture(tmp_path):
    text = 'Synthetic reviewer summary of a test article.'
    e = dict(evidence_id='test-capture', url='https://pmc.ncbi.nlm.nih.gov/articles/PMC123/',
             final_url='https://pmc.ncbi.nlm.nih.gov/articles/PMC123/', kind='fulltext',
             timestamp='2026-11-06T00:00:00Z', status='accessible', http_status=None,
             text=text, payload_sha256=digest(text.encode()), bytes_observed=len(text.encode()),
             complete_body=False, level='reviewed_excerpt', identity_match=True,
             sections=['Methods'], format='reviewer_excerpt', columns=[],
             downloaded_full_dataset=False, transport='web_tool',
             source_reference='synthetic-tool-reference', reviewer_note='Synthetic offline test')
    p = tmp_path / 'capture.json'
    p.write_text(dump(dict(paper_id='Test-00001', pmid='1', record=e)), encoding='utf8')
    paper = dict(paper_id='Test-00001', pmid='1', values={'PMCID':'PMC123'})
    bundle = dict(records=[], fulltext_reviewed=False, sections_checked=[], supplementary_checked=False,
                  repository_checked=False, survey_complete=False, collector='synthetic')
    return paper, bundle, [dict(path='capture.json',sha256=digest(p.read_bytes()))], e


def test_capture_keeps_transport_honest_and_is_idempotent(tmp_path):
    paper,bundle,refs,e=fixture(tmp_path)
    result=append_captures(tmp_path,paper,bundle,refs)
    validate_evidence(result)
    assert not bundle['records']
    assert result['records'][0]['http_status'] is None
    assert len(append_captures(tmp_path,paper,result,refs)['records'])==1
    assert result['records'][0]['kind']=='fulltext'


@pytest.mark.parametrize('change',[{'http_status':200},{'kind':'file'},{'complete_body':True},
                                   {'text':'fabricated change'},{'source_reference':''}])
def test_invalid_transport_claims_fail(tmp_path,change):
    *_,e=fixture(tmp_path)
    e.update(change)
    with pytest.raises(ValueError):validate_web_capture(e)


def test_capture_identity_hash_and_scope(tmp_path):
    paper,bundle,refs,e=fixture(tmp_path)
    for changed in [dict(paper,pmid='2'),dict(paper,values={'PMCID':'PMC999'})]:
        with pytest.raises(ValueError):append_captures(tmp_path,changed,bundle,refs)
    with pytest.raises(ValueError):append_captures(tmp_path,paper,bundle,[dict(refs[0],sha256='wrong')])
    with pytest.raises(ValueError):append_captures(tmp_path,paper,bundle,[dict(refs[0],path='../outside.json')])


@pytest.mark.parametrize('invalid', [None, 'doi', 'title', 'route'])
def test_non_pmc_capture_requires_official_identity_and_observed_route(tmp_path, invalid):
    paper, bundle, refs, e = fixture(tmp_path)
    paper['values'] = {'DOI': '10.1234/test', 'Title': 'Synthetic title'}
    e['url'] = e['final_url'] = 'https://example.org/test-article'
    bundle['records'] = [dict(evidence_id='failed-route', kind='fulltext', url=e['url'])]
    ids = dict(paper['values'])
    if invalid == 'doi': ids['DOI'] = '10.1234/wrong'
    if invalid == 'title': ids['Title'] = 'Other article'
    if invalid == 'route': bundle['records'] = []
    p = tmp_path / 'capture.json'
    p.write_text(dump(dict(paper_id=paper['paper_id'], pmid=paper['pmid'],
                           verified_identifiers=ids, record=e)), encoding='utf8')
    refs[0]['sha256'] = digest(p.read_bytes())
    if invalid:
        with pytest.raises(ValueError): append_captures(tmp_path, paper, bundle, refs)
    else:
        assert append_captures(tmp_path, paper, bundle, refs)['records'][-1]['http_status'] is None


def test_repository_capture_is_not_downloaded_file(tmp_path):
    paper,bundle,refs,e=fixture(tmp_path)
    paper['values']={'DOI':'10.1234/test','Title':'Synthetic title'}
    e.update(kind='repository',url='https://example.org/data',final_url='https://example.org/data')
    bundle['records']=[dict(evidence_id='attempt',kind='repository',url=e['url'])]
    p=tmp_path/'capture.json'
    p.write_text(dump(dict(paper_id=paper['paper_id'],pmid=paper['pmid'],
        verified_identifiers=paper['values'],record=e)),encoding='utf8')
    refs[0]['sha256']=digest(p.read_bytes())
    result=append_captures(tmp_path,paper,bundle,refs)['records'][-1]
    assert result['kind']=='repository' and not result['complete_body']
    assert result['http_status'] is None and result['level']=='reviewed_excerpt'
    with pytest.raises(ValueError):append_captures(tmp_path,paper,dict(bundle,records=[]),refs)
    with pytest.raises(ValueError):validate_web_capture(dict(result,kind='file'))
