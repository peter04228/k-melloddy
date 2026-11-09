import base64
import io
import zipfile
from k_melloddy.db_select.full_workflow_access import inspect_material


def archive_record(files):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as z:
        for name,data in files.items():z.writestr(name,data)
    return dict(status='fetch_error',failure_reason='redirect_or_empty_body_not_article',http_status=200,
                kind='file',complete_body=True,format='application/zip',final_url='https://example.org/data.zip',
                body_sample_b64=base64.b64encode(stream.getvalue()).decode(),text='')


def test_identical_archive_tables_are_one_dataset_without_executing_code():
    raw='Drug\tALT\r\r\nsynthetic\t2\r\r\n'
    e=inspect_material(archive_record({'R/data.txt':raw,'Python/data.txt':raw,'__MACOSX/._data.txt':'junk','run.py':'raise RuntimeError()'}))
    assert e['status']=='accessible' and e['columns']==['Drug','ALT'] and e['sample_row_count']==1
    assert len(e['archive_tables'])==2 and e['archive_tables'][0]['sha256']==e['archive_tables'][1]['sha256']


def test_distinct_or_malformed_archive_tables_do_not_silently_merge():
    e=inspect_material(archive_record({'a.csv':'Drug,ALT\na,1','b.csv':'Drug,ALT\nb,2'}))
    assert e['status']=='accessible' and 'Multiple' in e['structure_failure']
    assert e['level']=='response_sample' and not e.get('columns')
    e=inspect_material(archive_record({'a.csv':'Drug,ALT\na,1\nb'}))
    assert e['status']=='fetch_error' and 'Inconsistent' in e['structure_failure']
