import base64
import copy
import io
import json
import shutil
import tarfile

import pytest

from k_melloddy.core.storage import digest,dump
from k_melloddy.db_select.form_material_capture import append_form_materials
from k_melloddy.db_select.pdf_grid_review import selected_pdf_grids


def sample(tmp_path, data=b'actual captured bytes'):
    html=b'<form method="POST" action="/download"><input type="hidden" name="param" value="opaque"><button>Supplementary</button></form>'
    def record(data, **extra):
        return dict(evidence_id='source',url='https://example.org/article/1',
            final_url='https://example.org/article/1',kind='fulltext',status='accessible',
            identity_match=True,http_status=200,complete_body=True,bytes_observed=len(data),
            payload_sha256=digest(data),body_sample_b64=base64.b64encode(data).decode(),
            level='response_sample',text='',**extra)
    source=record(html)
    response=record(data)
    response.update(evidence_id='response',url='https://example.org/download',
                    final_url='https://example.org/download',kind='file',request_method='POST')
    paper={'paper_id':'Fixture-00001','pmid':'1'}
    capture=dict(paper,source_evidence_id='source',source_sha256=digest(html),
                 reviewer_note='Fixture of an actually captured response.',record=response,pdf_members=[])
    return paper,{'records':[source]},capture


def append(tmp_path, paper, bundle, capture):
    raw=dump(capture).encode();(tmp_path/'capture.json').write_bytes(raw)
    return append_form_materials(tmp_path,paper,bundle,[{'path':'capture.json','sha256':digest(raw)}])


def test_form_import_preserves_post_provenance_and_original(tmp_path):
    paper,bundle,capture=sample(tmp_path)
    original=copy.deepcopy(bundle)
    result=append(tmp_path,paper,bundle,capture)
    assert bundle==original
    assert result['records'][-1]['request_method']=='POST'
    assert result['records'][-1]['columns']==[]
    assert result['records'][-1]['form_source_evidence_id']=='source'
    assert result['records'][-1]['level']=='response_sample'


@pytest.mark.parametrize('change',['paper','hash','origin','method','truncated','no_form','not_article'])
def test_reject_changed_unbound_or_nonpublic_form_capture(tmp_path,change):
    paper,bundle,capture=sample(tmp_path)
    if change=='paper':capture['pmid']='2'
    if change=='hash':capture['record']['payload_sha256']='0'*64
    if change=='origin':capture['record']['url']='https://other.example/download'
    if change=='method':capture['record']['request_method']='GET'
    if change=='truncated':capture['record']['complete_body']=False
    if change=='no_form':bundle['records'][0]['body_sample_b64']=base64.b64encode(b'no form').decode()
    if change=='not_article':bundle['records'][0]['identity_match']=False
    with pytest.raises(ValueError):append(tmp_path,paper,bundle,capture)


def grid_pdf():
    fitz=pytest.importorskip('fitz')
    doc=fitz.open();page=doc.new_page()
    page.insert_text((50,40),'Dexamethasone Human in vitro 8hr')
    for x in [50,150,250,350]:page.draw_line((x,70),(x,160))
    for y in [70,100,130,160]:page.draw_line((50,y),(350,y))
    for j,row in enumerate([['Pathways','Both','Up'],['Meta','1.78','1.98*'],['AhR','-0.29','NA']]):
        for i,value in enumerate(row):page.insert_text((55+100*i,90+30*j),value)
    return doc.tobytes()


@pytest.mark.skipif(not shutil.which('tar'),reason='A public archive reader is required')
def test_archive_member_and_selected_pdf_grid_preserve_values_without_drug_column(tmp_path):
    pdf=grid_pdf();stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode='w') as tar:
        item=tarfile.TarInfo('Supplement.pdf');item.size=len(pdf);tar.addfile(item,io.BytesIO(pdf))
    data=stream.getvalue();(tmp_path/'material.tar').write_bytes(data)
    paper,bundle,capture=sample(tmp_path,data)
    capture['pdf_members']=[{'name':'Supplement.pdf','archive_path':'material.tar','sha256':digest(pdf)}]
    result=append(tmp_path,paper,bundle,capture)
    member=result['records'][-1]
    selection=dict(parent_evidence_id=member['evidence_id'],page=0,table=0,
        header_cells=[[0,0],[0,1],[0,2]],expected_columns=['Pathways','Both','Up'],
        data_row_start=1,data_row_end=3,caption_quote='Dexamethasone Human in vitro 8hr')
    selected=selected_pdf_grids(result,[selection])['records'][-1]
    assert selected['pdf_grid_rows']==[['Meta','1.78','1.98*'],['AhR','-0.29','NA']]
    assert selected['columns']==['Pathways','Both','Up']
    assert 'drug' not in selected['columns']
    assert selected['payload_sha256']==digest(pdf)
    assert selected['parent_evidence_id']==member['evidence_id']
    assert result['records'][-1]['level']=='response_sample'
    selection['expected_columns']=['Drug','Endpoint','Value']
    with pytest.raises(ValueError,match='headers changed'):selected_pdf_grids(result,[selection])
    selection['expected_columns']=['Pathways','Both','Up'];selection['caption_quote']='unseen compound'
    with pytest.raises(ValueError,match='Unobserved'):selected_pdf_grids(result,[selection])


def test_archive_traversal_is_rejected_before_extraction(tmp_path):
    paper,bundle,capture=sample(tmp_path)
    capture['pdf_members']=[{'name':'../outside.pdf','archive_path':'missing.rar','sha256':'x'}]
    with pytest.raises(ValueError,match='Unsafe'):append(tmp_path,paper,bundle,capture)


def test_caption_from_another_page_cannot_assign_its_drug_to_selected_table(tmp_path):
    fitz=pytest.importorskip('fitz')
    first=fitz.open(stream=grid_pdf(),filetype='pdf')
    second=fitz.open(stream=grid_pdf(),filetype='pdf')
    second[0].add_redact_annot(fitz.Rect(40,20,450,50));second[0].apply_redactions()
    second[0].insert_text((50,40),'Another compound Human in vitro 8hr')
    first.insert_pdf(second);pdf=first.tobytes()
    from pypdf import PdfReader
    text='\n'.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(pdf)).pages)
    material=dict(evidence_id='pdf',kind='file',status='accessible',http_status=200,
        complete_body=True,bytes_observed=len(pdf),payload_sha256=digest(pdf),
        body_sample_b64=base64.b64encode(pdf).decode(),text=text)
    selection=dict(parent_evidence_id='pdf',page=1,table=0,header_cells=[[0,0],[0,1],[0,2]],
        expected_columns=['Pathways','Both','Up'],data_row_start=1,data_row_end=3,
        caption_quote='Dexamethasone Human in vitro 8hr')
    with pytest.raises(ValueError,match='not above'):selected_pdf_grids({'records':[material]},[selection])


def test_explicit_unruled_pdf_cells_preserve_real_headers_rows_and_original():
    fitz=pytest.importorskip('fitz')
    doc=fitz.open();page=doc.new_page()
    caption='Actual hepatic injury counts from a reporting database, not incidence or causal labels'
    page.insert_text((50,40),caption)
    for j,row in enumerate([['Drug','Cases','ROR'],['A','4','1.98*'],['B','0','NA']]):
        for i,value in enumerate(row):page.insert_text((55+100*i,90+30*j),value)
    pdf=doc.tobytes()
    material=dict(evidence_id='unruled',kind='file',status='accessible',http_status=200,
        complete_body=True,bytes_observed=len(pdf),payload_sha256=digest(pdf),
        body_sample_b64=base64.b64encode(pdf).decode(),text=page.get_text())
    bundle={'records':[material]};original=copy.deepcopy(bundle)
    selection=dict(parent_evidence_id='unruled',page=0,table=0,
        table_settings={'vertical_lines':[50,150,250,350],'horizontal_strategy':'text'},
        header_cells=[[2,0],[2,1],[2,2]],expected_columns=['Drug','Cases','ROR'],
        data_row_start=4,data_row_end=7,row_indices=[4,6],caption_quote=caption)
    result=selected_pdf_grids(bundle,[selection])
    assert bundle==original
    observed=result['records'][-1]
    assert observed['columns']==['Drug','Cases','ROR']
    assert observed['pdf_grid_rows']==[['A','4','1.98*'],['B','0','NA']]
    assert observed['pdf_grid_selection']==selection
    assert observed['payload_sha256']==digest(pdf)
    assert observed['downloaded_full_dataset'] is False
    assert selected_pdf_grids(result,[selection])==result
    bad=copy.deepcopy(selection);bad['expected_columns']=['Drug','Endpoint','Value']
    with pytest.raises(ValueError,match='headers changed'):selected_pdf_grids(bundle,[bad])
    for indices in [[6,4],[4,4],[True],[4,7],[],[4,5,6]]:
        bad=copy.deepcopy(selection);bad['row_indices']=indices
        with pytest.raises(ValueError):selected_pdf_grids(bundle,[bad])
    for lines in [[50,150,150,350],[50,350,250],[-1,150,350],[50,float('nan'),350],[True,350]]:
        bad=copy.deepcopy(selection);bad['table_settings']['vertical_lines']=lines
        with pytest.raises(ValueError,match='boundaries'):selected_pdf_grids(bundle,[bad])
    bad=copy.deepcopy(selection);bad['table_settings']['horizontal_strategy']='lines'
    with pytest.raises(ValueError,match='settings'):selected_pdf_grids(bundle,[bad])
