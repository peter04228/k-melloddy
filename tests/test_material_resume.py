import base64
import copy

from k_melloddy.db_select.full_workflow_access import inspect_material


def test_repeated_material_inspection_preserves_exact_review_evidence():
    record = dict(kind='file', status='accessible', complete_body=True,
                  final_url='https://example.org/data.csv', format='text/csv',
                  body_sample_b64=base64.b64encode(b'drug,ALT\nA,20\n').decode(),
                  text='drug,ALT\nA,20\n')
    first = copy.deepcopy(inspect_material(record))
    assert first['columns'] == ['drug', 'ALT']
    assert inspect_material(record) == first
    assert record['text'].count('Structured sample:') == 1


def test_complete_legacy_xls_recovers_transport_classification_and_is_idempotent():
    from unittest.mock import Mock,patch
    sheet=Mock(name='legacy_sheet')
    sheet.name='build02';sheet.ncols=3;sheet.nrows=2
    sheet.row_values.side_effect=[['cmap_name','concentration (M)','duration (h)'],['metformin',1e-5,6]]
    book=Mock(nsheets=1);book.sheet_by_index.return_value=sheet
    record=dict(kind='file',status='fetch_error',failure_reason='redirect_or_empty_body_not_article',
                http_status=200,complete_body=True,final_url='https://example.org/annotation.xls',
                format='application/octet-stream',body_sample_b64=base64.b64encode(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'+b'fixture').decode(),text='')
    with patch('xlrd.open_workbook',return_value=book):
        first=copy.deepcopy(inspect_material(record))
        assert first['status']=='accessible' and first['original_status']=='fetch_error'
        assert first['columns']==['cmap_name','concentration (M)','duration (h)']
        assert first['level']=='sample_structure'
        assert inspect_material(record)==first
    book.release_resources.assert_called_once()


def test_truncated_or_non_xls_bytes_never_gain_structure():
    for complete,raw in [(False,b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'),(True,b'<html>Login</html>')]:
        record=dict(kind='file',status='fetch_error',failure_reason='redirect_or_empty_body_not_article',
                    http_status=200,complete_body=complete,final_url='https://example.org/data.xls',
                    format='application/octet-stream',body_sample_b64=base64.b64encode(raw).decode(),text='')
        result=inspect_material(record)
        assert result['status']=='fetch_error' and not result.get('columns')
