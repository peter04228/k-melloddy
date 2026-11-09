import io
import json
import urllib.error
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from k_melloddy.db_collect.client import NCBIClient, parse_search
from k_melloddy.db_collect.exporter import export_files
from k_melloddy.db_collect.fake import FakeClient
from k_melloddy.db_collect.metadata import parse_metadata
from test_collection import setup


def test_date_boundaries_exact_coverage(tmp_path):
    c = setup(tmp_path, FakeClient(10001), {'partition_start':'2020-01-01','partition_end':'2020-12-30'})
    try:
        c.run()
        leaves = sorted(c.parts, key=lambda p:p['start'])
        assert leaves[0]['start']=='2020-01-01'
        assert leaves[-1]['end']=='2020-12-30'
        assert all(date.fromisoformat(a['end'])+timedelta(days=1)==date.fromisoformat(b['start']) for a,b in zip(leaves,leaves[1:]))
        assert sum(p['expected_count'] for p in leaves)==10001
    finally:
        c.close()


def test_incomplete_date_coverage_blocks_completion(tmp_path):
    c = setup(tmp_path, FakeClient(10001), {'partition_start':'2020-01-02','partition_end':'2020-12-30'})
    try:
        r=c.run()
        assert r['status']=='PARTIAL'
        assert any(i['reason']=='partition_count_mismatch' for i in c.qc['issues'])
    finally:
        c.close()


def test_overlapping_partition_ids_not_silently_accepted(tmp_path):
    class Overlap(FakeClient):
        def search(self, query, start=0, size=0, sort='pub_date'):
            result=json.loads(super().search(query,start,size,sort))
            ids=result['esearchresult']['idlist']
            if ids and '2020-07' in query:
                ids[0]='1'
            return json.dumps(result).encode()
    c=setup(tmp_path,Overlap(10001),{'partition_start':'2020-01-01','partition_end':'2020-12-30'})
    try:
        result=c.run()
        assert result['status']=='PARTIAL'
        assert result['counts']['duplicate_occurrence_count']>0
    finally:
        c.close()


def test_page_failure_restarts_only_unfinished_requests(tmp_path):
    class FailPage(FakeClient):
        failed=False
        def search(self,query,start=0,size=0,sort='pub_date'):
            if start==2 and not self.failed:
                self.failed=True
                raise RuntimeError('Simulated interruption')
            return super().search(query,start,size,sort)
    client=FailPage(5)
    c=setup(tmp_path,client,{'page_size':2})
    try:
        with pytest.raises(RuntimeError): c.run()
        run=c.run_id
        before=len([x for x in client.calls if x[0]=='search' and x[2]==0 and x[3]==2])
        assert c.run(resume=run)['status']=='COMPLETED'
        assert len([x for x in client.calls if x[0]=='search' and x[2]==0 and x[3]==2])==before
        assert c.store.db.execute('SELECT COUNT(*) FROM pmid_occurrences').fetchone()[0]==5
    finally: c.close()


def test_malformed_xml_pending_then_resume(tmp_path):
    class BadXML(FakeClient):
        bad=True
        def fetch(self,pmids):
            if self.bad:
                self.bad=False
                return b'<PubmedArticleSet><broken>'
            return super().fetch(pmids)
    c=setup(tmp_path,BadXML(1))
    try:
        first=c.run()
        assert first['status']=='PARTIAL'
        assert c.run(resume=first['run_id'])['status']=='COMPLETED'
    finally: c.close()


def test_xlsx_long_cell_keeps_original_and_literal_formula():
    records=parse_metadata(FakeClient(1).fetch(['1']), ['PMID','Title','Abstract'])
    records[0].update(paper_id='HEART-P000001',paper_uid='uid',source_run_id='run',raw_xml_path='test.xml')
    records[0]['values']['Abstract']='x'*33000
    records[0]['values']['Title']='=1+1'
    files,warnings=export_files(records,['Title','Abstract'],['xlsx'],True)
    assert warnings
    assert len(json.loads(files['xlsx_overflow.json'])[0]['original'])==33000
    from openpyxl import load_workbook
    book=load_workbook(io.BytesIO(files['pubmed_master.xlsx']))
    assert book.active['C2'].value=='=1+1'
    assert book.active['C2'].data_type=='s'
    book.close()


def test_retry_after_and_redacted_errors():
    retries=[]
    client=NCBIClient(retries=1,on_retry=lambda *x:retries.append(x))
    response=io.BytesIO(b'{}')
    error=urllib.error.HTTPError('https://example.invalid?api_key=SECRET',429,'limit',{'Retry-After':'0'},None)
    with patch('urllib.request.urlopen',side_effect=[error,response]), patch('time.sleep'), patch('time.monotonic',side_effect=range(100)):
        assert client.search('test')==b'{}'
    assert retries[0][1]==429
    with patch('urllib.request.urlopen',side_effect=error), patch('time.sleep'), patch('time.monotonic',side_effect=range(100)):
        with pytest.raises(RuntimeError) as e: client.search('test')
    assert 'SECRET' not in str(e.value)


def test_search_errors_are_not_zero():
    for data in [b'{}',b'{"error":"rate limited"}',b'{"esearchresult":{"count":"-1"}}']:
        with pytest.raises((ValueError,KeyError)): parse_search(data)


def test_reference_article_ids_never_replace_primary_ids():
    raw=b'''<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>1</PMID><Article><ArticleTitle>T</ArticleTitle></Article></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">10.1000/primary</ArticleId><ArticleId IdType="pmc">PMC1</ArticleId></ArticleIdList><ReferenceList><Reference><ArticleIdList><ArticleId IdType="doi">10.1000/reference</ArticleId><ArticleId IdType="pmc">PMC2</ArticleId></ArticleIdList></Reference></ReferenceList></PubmedData></PubmedArticle></PubmedArticleSet>'''
    record=parse_metadata(raw,['PMID','Title','Abstract'])[0]
    assert record['values']['DOI']=='10.1000/primary'
    assert record['values']['PMCID']=='PMC1'


@pytest.mark.parametrize('disconnect',[False,True])
def test_interrupted_response_read_retries_whole_request(disconnect):
    import http.client
    class BrokenResponse(io.BytesIO):
        def read(self,*args):
            if disconnect:raise http.client.RemoteDisconnected('connection closed')
            raise http.client.IncompleteRead(b'partial XML')
    retries=[]
    client=NCBIClient(retries=1,on_retry=lambda *args:retries.append(args))
    broken=BrokenResponse()
    with patch('urllib.request.urlopen',side_effect=[broken,io.BytesIO(b'complete XML')]) as opened, patch('time.sleep'), patch('time.monotonic',side_effect=range(100)):
        assert client.fetch(['1'])==b'complete XML'
        assert opened.call_count==2
        assert opened.call_args_list[0].args[0].data==opened.call_args_list[1].args[0].data
    assert broken.closed and retries==[(1,None,1)]
    with patch('urllib.request.urlopen',side_effect=lambda *a,**k:BrokenResponse()), patch('time.sleep'), patch('time.monotonic',side_effect=range(100)):
        with pytest.raises(RuntimeError,match='failed after retries'):client.fetch(['1'])


def test_project_documentation_created(tmp_path):
    c=setup(tmp_path,FakeClient(0))
    try:
        assert len(list(c.root.glob('1.*/README.md')))==12
        for p in c.root.glob('1.*/README.md'):
            text=p.read_text(encoding='utf-8')
            assert '알고리즘' in text and '재시도' in text and '검증' in text
    finally:c.close()


def test_realistic_structural_fixture():
    from pathlib import Path
    from k_melloddy.db_collect.config import FIELDS
    data=(Path(__file__).parent/'fixtures/structured_article.xml').read_bytes()
    r=parse_metadata(data,FIELDS)[0]
    assert r['values']['Title']=='Mixed title markup'
    assert len(r['values']['Authors'])==2
    assert len(r['abstract_sections'])==3
    assert r['abstract_sections'][0]['category']=='METHODS'
    assert r['values']['MeSH'][0]['children'][0]['attributes']['UI']=='D000001'
    assert r['values']['PMCID']=='PMC123'


def test_interrupted_publication_leaves_no_final_file(tmp_path):
    from k_melloddy.core.storage import immutable_write
    final=tmp_path/'result.xml'
    with patch('os.link',side_effect=KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt): immutable_write(final,b'complete bytes')
    assert not final.exists()
    immutable_write(final,b'complete bytes')
    assert final.read_bytes()==b'complete bytes'


def test_resume_uses_frozen_query_and_config(tmp_path):
    c=setup(tmp_path,FakeClient(1))
    try:
        first=c.run(search_only=True)
        original=c.query
        (c.root/'Input/query.txt').write_text('changed after search',encoding='utf-8')
        (c.root/'Input/config.yaml').write_text('invalid: yes',encoding='utf-8')
        assert c.run(resume=first['run_id'])['status']=='COMPLETED'
        assert c.query==original
    finally:c.close()
