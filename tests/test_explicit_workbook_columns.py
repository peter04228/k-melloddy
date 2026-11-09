import base64
import copy
import io
import zipfile

import pytest
from openpyxl import Workbook
from openpyxl.styles import Font

from k_melloddy.core.storage import digest
from k_melloddy.db_select.archive_review import selected_tables


def fixture():
    book=Workbook();sheet=book.active;sheet.title='DATA'
    sheet.append(['Observed ID','Observed label',None,'Unselected formula','Observed score'])
    sheet.append(['LT00001','Fixture label','>','=1+2',4])
    sheet['JX1'].font=Font(bold=True)  # Formatted but empty columns, not additional features.
    out=io.BytesIO();book.save(out);raw=out.getvalue()
    record=dict(evidence_id='book',kind='file',status='fetch_error',http_status=200,
        complete_body=True,body_sample_b64=base64.b64encode(raw).decode(),
        payload_sha256=digest(raw),bytes_observed=len(raw),url='https://example.org/download')
    selection=dict(parent_evidence_id='book',members=[],sheet='DATA',header_row=1,
        column_indices=[1,2,5],expected_columns=['Observed ID','Observed label','Observed score'],
        column_selection_reason='Only named identifiers, labels and static scores; no assay values or qualifier conversion.')
    return {'records':[record]},selection


def test_explicit_columns_preserve_actual_headers_and_static_values_with_parent_bytes():
    bundle,selection=fixture();original=copy.deepcopy(bundle)
    result=selected_tables(bundle,[selection])['records'][-1]
    assert result['columns']==selection['expected_columns']
    assert result['status']=='accessible' and result['level']=='sample_structure'
    assert result['payload_sha256']==bundle['records'][0]['payload_sha256']
    assert result['archive_selection']['column_selection_reason']==selection['column_selection_reason']
    assert bundle==original


@pytest.mark.parametrize('change',['renamed','formula','no_reason','duplicates'])
def test_selection_cannot_invent_headers_or_execute_formulas(change):
    bundle,selection=fixture()
    if change=='renamed':selection['expected_columns'][0]='Invented Drug column'
    if change=='formula':
        selection['column_indices']=[1,4];selection['expected_columns']=['Observed ID','Unselected formula']
    if change=='no_reason':selection['column_selection_reason']=''
    if change=='duplicates':selection['column_indices']=[1,1,5]
    with pytest.raises(ValueError):selected_tables(bundle,[selection])


def test_csv_cannot_silently_ignore_explicit_xlsx_column_selection():
    bundle,selection=fixture();out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as archive:archive.writestr('data.csv','A,B,C\nx,y,z\n')
    raw=out.getvalue();bundle['records'][0].update(body_sample_b64=base64.b64encode(raw).decode(),
        payload_sha256=digest(raw),bytes_observed=len(raw))
    selection.update(members=['data.csv'],sheet=None,column_indices=[1,3],expected_columns=['A','C'])
    with pytest.raises(ValueError,match='XLSX only'):selected_tables(bundle,[selection])
