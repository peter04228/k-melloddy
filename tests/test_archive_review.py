import base64
import io
import zipfile
import pytest
from openpyxl import Workbook
from k_melloddy.core.storage import digest
from k_melloddy.db_select.archive_review import selected_tables


def sample():
    book=Workbook();sheet=book.active;sheet.title='Data'
    sheet.append(['Caption']);sheet.append(['Drug','Toxicity']);sheet.append(['synthetic',1])
    stream=io.BytesIO();book.save(stream)
    nested=io.BytesIO()
    with zipfile.ZipFile(nested,'w') as z:z.writestr('data.xlsx',stream.getvalue())
    outer=io.BytesIO()
    with zipfile.ZipFile(outer,'w') as z:z.writestr('misnamed.tgz',nested.getvalue())
    data=outer.getvalue()
    parent=dict(evidence_id='parent',kind='file',complete_body=True,http_status=200,
                status='fetch_error',body_sample_b64=base64.b64encode(data).decode(),payload_sha256=digest(data))
    selection=dict(parent_evidence_id='parent',members=['misnamed.tgz','data.xlsx'],sheet='Data',header_row=2)
    return {'records':[parent]},selection


def test_selected_nested_table_preserves_parent_and_records_no_new_request():
    bundle,selection=sample();result=selected_tables(bundle,[selection]);e=result['records'][1]
    assert len(bundle['records'])==1 and result['records'][0]==bundle['records'][0]
    assert e['columns']==['Drug','Toxicity'] and e['transport']=='archive_member'
    assert e['request_performed'] is False and len(e['archive_members'])==2
    assert e['level']=='sample_structure' and e['downloaded_full_dataset'] is False


def test_archive_selection_rejects_incomplete_wrong_member_and_unlabelled_header():
    bundle,selection=sample();bundle['records'][0]['complete_body']=False
    with pytest.raises(ValueError):selected_tables(bundle,[selection])
    bundle,selection=sample();selection['members'][1]='missing.xlsx'
    with pytest.raises(ValueError):selected_tables(bundle,[selection])
    bundle,selection=sample();selection['header_row']=1
    with pytest.raises(ValueError):selected_tables(bundle,[selection])


def test_archive_selection_cannot_bypass_failed_official_checksum():
    bundle,selection=sample()
    bundle['records'][0]['cloud_checksum']={'verified':False}
    with pytest.raises(ValueError,match='official cloud checksum failed'):
        selected_tables(bundle,[selection])
    assert len(bundle['records'])==1
    bundle['records'][0]['cloud_checksum']['verified']=True
    assert selected_tables(bundle,[selection])['records'][-1]['columns']==['Drug','Toxicity']


def test_explicit_direct_workbook_sheet_preserves_source_and_rejects_bad_selection():
    book=Workbook();book.active.title='Metadata';book.active.append(['Description'])
    sheet=book.create_sheet('Clinical');sheet.append(['Drug','ALT']);sheet.append(['synthetic',40])
    stream=io.BytesIO();book.save(stream);raw=stream.getvalue()
    bundle,selection=sample();parent=bundle['records'][0]
    parent.update(body_sample_b64=base64.b64encode(raw).decode(),payload_sha256=digest(raw))
    selection.update(members=[],sheet='Clinical',header_row=1)
    result=selected_tables(bundle,[selection]);record=result['records'][-1]
    assert record['transport']=='workbook_sheet' and record['columns']==['Drug','ALT']
    assert record['workbook_inspection']=={'sheet':'Clinical','header_row':1}
    assert len(bundle['records'])==1 and record['request_performed'] is False
    assert record['payload_sha256']==parent['payload_sha256']
    with pytest.raises(KeyError):selected_tables(bundle,[dict(selection,sheet='Absent')])
    parent['complete_body']=False
    with pytest.raises(ValueError):selected_tables(bundle,[selection])
    parent['complete_body']=True;parent['cloud_checksum']={'verified':False}
    with pytest.raises(ValueError,match='official cloud checksum failed'):selected_tables(bundle,[selection])


def test_legacy_xls_archive_requires_explicit_headers_and_sheet(monkeypatch):
    import xlrd
    from types import SimpleNamespace
    content=b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'+b'synthetic-parser-input'
    outer=io.BytesIO()
    with zipfile.ZipFile(outer,'w') as z:z.writestr('table.xls',content)
    raw=outer.getvalue()
    parent=dict(evidence_id='parent',kind='file',complete_body=True,http_status=200,
        status='fetch_error',body_sample_b64=base64.b64encode(raw).decode(),payload_sha256=digest(raw))
    rows=[['Caption',''],['',''],['Drug','DILI'],['synthetic',1]]
    sheet=SimpleNamespace(ncols=2,nrows=len(rows),row_values=lambda i:rows[i])
    released=[]
    book=SimpleNamespace(nsheets=1,sheet_names=lambda:['Data'],sheet_by_name=lambda name:sheet,
        release_resources=lambda:released.append(True))
    def open_book(*,file_contents,on_demand):
        assert file_contents==content and on_demand is True
        return book
    monkeypatch.setattr(xlrd,'open_workbook',open_book)
    selection=dict(parent_evidence_id='parent',members=['table.xls'],sheet='Data',header_row=3)
    bundle={'records':[parent]};e=selected_tables(bundle,[selection])['records'][-1]
    assert e['columns']==['Drug','DILI'] and e['format']=='application/vnd.ms-excel'
    assert e['request_performed'] is False and released
    assert parent['status']=='fetch_error'  # Preserve captured classification and bytes.
    with pytest.raises(ValueError):selected_tables(bundle,[dict(selection,header_row=1)])
    with pytest.raises(ValueError):selected_tables(bundle,[dict(selection,sheet='Unknown')])
