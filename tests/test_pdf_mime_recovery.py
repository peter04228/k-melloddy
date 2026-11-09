import base64
import copy
import fitz

from k_melloddy.db_select.full_workflow_access import recover_pdf_bytes


def test_binary_pdf_requires_complete_bytes_and_matching_identity():
    paper={'values':{'Title':'Synthetic liver study','DOI':'10.1234/synthetic'}}
    doc=fitz.open();page=doc.new_page()
    page.insert_text((30,40),'Synthetic liver study\n10.1234/\nsynthetic\n'+('Synthetic methods and results.\n'*20))
    data=doc.tobytes();doc.close()
    record={'kind':'fulltext','complete_body':True,'http_status':200,
            'body_sample_b64':base64.b64encode(data).decode(),'status':'fetch_error',
            'failure_reason':'redirect_or_empty_body_not_article','format':'binary/octet-stream'}
    incomplete=copy.deepcopy(record);incomplete['complete_body']=False
    recover_pdf_bytes(paper,incomplete)
    assert incomplete['status']=='fetch_error' and 'pdf_text_extracted' not in incomplete
    wrong=copy.deepcopy(record)
    recover_pdf_bytes({'values':{'Title':'Different article','DOI':'10.9999/other'}},wrong)
    assert wrong['status']=='fetch_error'
    recover_pdf_bytes(paper,record)
    assert record['status']=='accessible' and record['identity_match']
    assert record['format']=='binary/octet-stream'
    assert record['detected_format']=='application/pdf'
    assert record['prior_classification']['failure_reason']=='redirect_or_empty_body_not_article'
    assert not record.get('fulltext_reviewed')
