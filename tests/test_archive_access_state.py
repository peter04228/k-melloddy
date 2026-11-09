import base64
import copy
import io
import zipfile

from k_melloddy.db_select.full_workflow_access import inspect_material


def test_multiple_zip_tables_are_accessible_without_inferred_schema():
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as archive:
        archive.writestr('a.csv','drug,label\na,1\n')
        archive.writestr('b.csv','sample,value\nb,2\n')
    record=dict(kind='file',status='fetch_error',http_status=200,
                failure_reason='redirect_or_empty_body_not_article',complete_body=True,
                final_url='https://example.org/material.zip',format='application/zip',
                body_sample_b64=base64.b64encode(stream.getvalue()).decode(),columns=[])
    incomplete=copy.deepcopy(record);incomplete['complete_body']=False
    inspect_material(incomplete)
    assert incomplete['status']=='fetch_error'
    inspect_material(record)
    assert record['status']=='accessible' and record['level']=='response_sample'
    assert len(record['archive_tables'])==2 and not record['columns']
    assert 'explicit selection' in record['structure_failure']
    assert not record.get('downloaded_full_dataset')
