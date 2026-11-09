from unittest.mock import patch
from k_melloddy.db_select.access_workflow import AccessInvestigator

def test_slow_stream_is_not_successful_evidence():
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,n):raise AssertionError('Unbounded read used')
        def read1(self,n):return b'x'
    class Opener:
        def open(self,*args,**kwargs):return Response()
    c=AccessInvestigator(opener=Opener(),retries=0,timeout=20)
    with patch('k_melloddy.db_select.access_workflow.public_url'),patch('k_melloddy.db_select.access_workflow.time.monotonic',side_effect=[0,0,21]):
        records=c.request('https://example.org/file','fulltext',{'pmid':'123','values':{}},'test')
    assert len(records)==1 and records[0]['status']=='fetch_error'
    assert not records[0]['complete_body']
    assert records[0]['level']=='unverified'

def test_elsevier_journal_name_is_not_article_methods():
    from k_melloddy.db_select.revalidation_access import readable_body,body_requires_review
    e=dict(kind='fulltext',status='accessible',identity_match=True,url='https://api.elsevier.com/content/article/pii/test',text='<full-text-retrieval-response><coredata><title>Computer Methods and Programs in Biomedicine</title><description>'+('x'*500)+'</description></coredata></full-text-retrieval-response>')
    assert not readable_body(e) and not body_requires_review(e)
    e['text']='<full-text-retrieval-response><originalText><body>'+('Article prose '*100)+'</body></originalText></full-text-retrieval-response>'
    assert readable_body(e)
