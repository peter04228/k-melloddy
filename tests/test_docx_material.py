import base64
import io
import zipfile
import pytest
from k_melloddy.db_select.full_workflow_access import inspect_material
from k_melloddy.db_select.dataset_verifier import verify_dataset


def record(xml):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as z:z.writestr('word/document.xml',xml)
    return dict(evidence_id='file',status='fetch_error',failure_reason='redirect_or_empty_body_not_article',
                http_status=200,kind='file',complete_body=True,format='application/octet-stream',
                url='https://example.org/data.docx',final_url='https://example.org/data.docx',payload_sha256='test',
                body_sample_b64=base64.b64encode(stream.getvalue()).decode(),text='')


XML='''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
<w:p><w:r><w:t>All subjects exposed to synthetic-drug.</w:t></w:r></w:p>
<w:tbl><w:tr><w:tc><w:p><w:r><w:t>case</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>ALT</w:t></w:r></w:p></w:tc></w:tr>
<w:tr><w:tc><w:p><w:r><w:t>1</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>12</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
</w:body></w:document>'''


def test_selected_docx_context_belongs_to_exact_table_and_supports_constant():
    import copy
    from k_melloddy.core.storage import digest
    from k_melloddy.db_select.archive_review import selected_docx_tables
    first=XML.split('<w:body>',1)[1].split('</w:body>',1)[0]
    second=first.replace('synthetic-drug','second-drug')
    e=record(XML.replace(first,first+second));e['status']='accessible'
    e['payload_sha256']=digest(base64.b64decode(e['body_sample_b64']))
    bundle={'records':[e]};before=copy.deepcopy(bundle)
    choice=dict(parent_evidence_id='file',table_index=1,include_preceding_paragraph=True)
    selected=selected_docx_tables(bundle,[choice])['records'][-1]
    assert 'synthetic-drug' not in selected['document_text']
    assert selected['document_text'].startswith('All subjects exposed to second-drug.')
    d=dict(name='fixture',identity='url:'+e['url'],version='1',direct_url=e['url'],
           evidence_id=selected['evidence_id'],drug_identifier='constant:second-drug',
           endpoint='ALT',value_field='ALT',independence_reason='fixture',
           feature_count=None,compound_count=None,evidence_refs=[
               dict(evidence_id=selected['evidence_id'],quote='All subjects exposed to second-drug.')])
    assert verify_dataset(d,{'records':[selected]})['drug_identifier']=='constant:second-drug'
    d['drug_identifier']='constant:synthetic-drug'
    with pytest.raises(ValueError,match='drug identity'):verify_dataset(d,{'records':[selected]})
    assert bundle==before


def test_explicit_docx_transpose_preserves_observed_case_identifiers_and_values():
    import copy
    import json
    from k_melloddy.core.storage import digest
    from k_melloddy.db_select.archive_review import selected_docx_tables
    def cell(s):return '<w:tc><w:p><w:r><w:t>'+s+'</w:t></w:r></w:p></w:tc>'
    matrix=[['component','Case 1','Case 2'],['ALT (U/L)','12','not done'],['score','-1','4']]
    table=''.join('<w:tr>'+''.join(cell(s) for s in row)+'</w:tr>' for row in matrix)
    xml=XML.split('<w:tbl>',1)[0].replace('All subjects exposed','All  subjects   exposed')+'<w:tbl>'+table+'</w:tbl></w:body></w:document>'
    e=record(xml);e.update(status='accessible',payload_sha256=digest(base64.b64decode(e['body_sample_b64'])))
    bundle={'records':[e]};before=copy.deepcopy(bundle)
    choice=dict(parent_evidence_id='file',table_index=0,transpose=True,include_preceding_paragraph=True)
    derived=selected_docx_tables(bundle,[choice])['records'][-1]
    assert derived['columns']==['ALT (U/L)','score'] and derived['source_columns']==matrix[0]
    assert derived['table_row_identifiers']==['Case 1','Case 2']
    assert derived['source_axis_label']=='component' and derived['sample_row_count']==2
    payload=json.loads(derived['text'].split('\n',2)[2])
    assert payload['sample']==[{'row_identifier':'Case 1','values':{'ALT (U/L)':'12','score':'-1'}},
                               {'row_identifier':'Case 2','values':{'ALT (U/L)':'not done','score':'4'}}]
    assert bundle==before and len(selected_docx_tables({'records':[e,derived]},[choice])['records'])==2
    dataset=dict(name='fixture',identity='url:'+e['url'],version='1',direct_url=e['url'],
                 evidence_id=derived['evidence_id'],drug_identifier='constant:synthetic-drug',
                 endpoint='ALT (U/L)',value_field='ALT (U/L)',independence_reason='fixture',
                 feature_count=None,compound_count=None,evidence_refs=[dict(evidence_id=derived['evidence_id'],quote='All subjects exposed to synthetic-drug.')])
    assert verify_dataset(dataset,{'records':[derived]})['compound_count'] is None
    bad=record(xml.replace('ALT (U/L)','score'));bad.update(status='accessible',payload_sha256=digest(base64.b64decode(bad['body_sample_b64'])))
    with pytest.raises(ValueError,match='unique nonempty row labels'):
        selected_docx_tables({'records':[bad]},[choice])


def test_selected_docx_context_cannot_come_from_previous_table_cell():
    from k_melloddy.core.storage import digest
    from k_melloddy.db_select.archive_review import selected_docx_tables
    table=XML.split('<w:tbl>',1)[1].split('</w:tbl>',1)[0]
    e=record(XML.replace('</w:tbl>','</w:tbl><w:tbl>'+table+'</w:tbl>'))
    e.update(status='accessible',payload_sha256=digest(base64.b64decode(e['body_sample_b64'])))
    with pytest.raises(ValueError,match='no preceding paragraph'):
        selected_docx_tables({'records':[e]},[dict(parent_evidence_id='file',table_index=1,
                                                 include_preceding_paragraph=True)])


def test_selected_docx_inside_zip_preserves_captured_parent_and_hashes():
    from k_melloddy.core.storage import digest
    from k_melloddy.db_select.archive_review import selected_docx_tables
    docx=base64.b64decode(record(XML)['body_sample_b64'])
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as z:z.writestr('supplement/Table S1.docx',docx)
    raw=stream.getvalue()
    parent=dict(evidence_id='zip',kind='file',status='accessible',complete_body=True,
                http_status=200,url='https://example.org/supp.zip',final_url='https://example.org/supp.zip',
                body_sample_b64=base64.b64encode(raw).decode(),payload_sha256=digest(raw),
                cloud_checksum={'verified':True})
    selection=dict(parent_evidence_id='zip',members=['supplement/Table S1.docx'],table_index=0)
    bundle={'records':[parent]}
    result=selected_docx_tables(bundle,[selection]);derived=result['records'][1]
    assert result['records'][0]==parent and len(bundle['records'])==1
    assert derived['columns']==['case','ALT'] and derived['request_performed'] is False
    assert derived['url']==parent['url'] and derived['payload_sha256']==digest(docx)
    assert base64.b64decode(derived['body_sample_b64'])==docx
    assert derived['archive_members'][0]['member']=='supplement/Table S1.docx'
    assert len(selected_docx_tables(result,[selection])['records'])==2
    parent['cloud_checksum']['verified']=False
    with pytest.raises(ValueError,match='checksum failed'):selected_docx_tables(bundle,[selection])
    parent['cloud_checksum']['verified']=True
    selection['members']=['missing.docx']
    with pytest.raises(ValueError,match='Missing'):selected_docx_tables(bundle,[selection])


def test_direct_supplementary_docx_is_inspected_as_file():
    e=record(XML);e.update(kind='supplementary',status='accessible')
    original=e['body_sample_b64']
    result=inspect_material(e)
    assert result['original_kind']=='supplementary' and result['kind']=='file'
    assert result['columns']==['case','ALT']
    assert result['body_sample_b64']==original
    e=record(XML);e.update(kind='supplementary',status='accessible',complete_body=False)
    assert inspect_material(e)['kind']=='supplementary'


def test_exact_docx_selection_preserves_parent_and_rejects_merges():
    import copy
    from k_melloddy.core.storage import digest
    from k_melloddy.db_select.archive_review import selected_docx_tables
    e=record(XML);e['status']='accessible'
    e['payload_sha256']=digest(base64.b64decode(e['body_sample_b64']))
    bundle={'records':[e]};original=copy.deepcopy(bundle)
    choice={'parent_evidence_id':'file','table_index':0}
    selected=selected_docx_tables(bundle,[choice])['records'][-1]
    assert selected['columns']==['case','ALT'] and selected['request_performed'] is False
    assert bundle==original and selected['parent_evidence_id']=='file'
    with pytest.raises(ValueError,match='index'):selected_docx_tables(bundle,[dict(choice,table_index=9)])
    e['body_sample_b64']=base64.b64encode(b'changed').decode()
    with pytest.raises(ValueError,match='payload'):selected_docx_tables(bundle,[choice])
    e=record(XML.replace('<w:tc>','<w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr>',1))
    e['status']='accessible';e['payload_sha256']=digest(base64.b64decode(e['body_sample_b64']))
    with pytest.raises(ValueError,match='Merged'):selected_docx_tables({'records':[e]},[choice])


def test_explicit_docx_row_bound_excludes_footer_without_guessing():
    from k_melloddy.core.storage import digest
    from k_melloddy.db_select.archive_review import selected_docx_tables
    footer='<w:tr><w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr><w:p><w:r><w:t>Normal range</w:t></w:r></w:p></w:tc></w:tr>'
    e=record(XML.replace('</w:tbl>',footer+'</w:tbl>'));e['status']='accessible'
    e['payload_sha256']=digest(base64.b64decode(e['body_sample_b64']))
    choice={'parent_evidence_id':'file','table_index':0,'row_end':2}
    result=selected_docx_tables({'records':[e]},[choice])['records'][-1]
    assert result['columns']==['case','ALT'] and 'Normal range' not in result['text']
    assert result['body_sample_b64']==e['body_sample_b64']
    with pytest.raises(ValueError,match='Merged'):
        selected_docx_tables({'records':[e]},[dict(choice,row_end=3)])


def test_docx_download_inspected_without_inventing_drug_column():
    e=inspect_material(record(XML))
    assert e['status']=='accessible' and e['columns']==['case','ALT']
    assert e['sample_row_count']==1 and 'synthetic-drug' in e['text']
    ref=dict(evidence_id='file',quote='All subjects exposed to synthetic-drug.')
    d=dict(name='synthetic',identity='url:'+e['url'],version='1',direct_url=e['url'],evidence_id='file',
           drug_identifier='synthetic-drug',endpoint='ALT',value_field='ALT',independence_reason='fixture',
           evidence_refs=[ref],feature_count=None,compound_count=None)
    with pytest.raises(ValueError,match='fields not verified'):verify_dataset(d,{'records':[e]})


def test_docx_merged_headers_and_html_are_not_structured_data():
    merged=XML.replace('<w:tc>','<w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr>',1)
    assert inspect_material(record(merged))['status']=='fetch_error'
    e=record(XML);e['status']='access_restricted'
    assert inspect_material(e)['status']=='access_restricted'
    e=record(XML);e['body_sample_b64']=base64.b64encode(b'<html>challenge</html>').decode()
    assert inspect_material(e)['status']=='fetch_error'


def test_docx_rejects_xml_entities():
    xml='<!DOCTYPE x [<!ENTITY x "injected">]>'+XML
    e=inspect_material(record(xml))
    assert e['status']=='fetch_error' and 'Unsafe DOCX' in e['structure_failure']


def test_xlsx_caption_is_preserved_and_not_used_as_column():
    from openpyxl import Workbook
    wb=Workbook();ws=wb.active
    ws.append(['Synthetic training set',None]);ws.append(['Drug','ALT']);ws.append(['synthetic',2])
    stream=io.BytesIO();wb.save(stream);wb.close()
    e=record(XML);e['final_url']='https://example.org/data.xlsx';e['body_sample_b64']=base64.b64encode(stream.getvalue()).decode()
    result=inspect_material(e)
    assert result['status']=='accessible' and result['columns']==['Drug','ALT']
    assert result['workbook_inspection']['header_row']==2 and result['sample_row_count']==1
    assert 'Synthetic training set' in result['text']


def test_xlsx_ambiguous_headers_keep_cells_but_cannot_register_structure():
    from openpyxl import Workbook
    wb=Workbook();ws=wb.active
    ws.append(['Caption',None,None]);ws.append([None,'Arm A','Arm B'])
    ws.append(['ID','Value','Value']);ws.append(['synthetic',2,3])
    stream=io.BytesIO();wb.save(stream);wb.close()
    e=record(XML);e['final_url']='https://example.org/data.xlsx'
    e['body_sample_b64']=base64.b64encode(stream.getvalue()).decode();e['level']='unverified'
    result=inspect_material(e)
    assert result['status']=='accessible'
    assert result.get('columns',[])==[] and result['level']!='sample_structure'
    assert result['workbook_preview']['rows'][2]==['ID','Value','Value']
    assert 'synthetic' in result['text'] and 'structure_failure' in result
