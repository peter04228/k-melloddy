import base64
import copy
import io

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from k_melloddy.core.storage import digest
from k_melloddy.db_select.full_workflow_access import inspect_material


def pdf_record(pages=1):
    writer=PdfWriter()
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),
                           NameObject('/Subtype'):NameObject('/Type1'),
                           NameObject('/BaseFont'):NameObject('/Helvetica')})
    for _ in range(pages):
        page=writer.add_blank_page(width=300,height=300)
        page[NameObject('/Resources')]=DictionaryObject({
            NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
        stream=DecodedStreamObject()
        stream.set_data(b'BT /F1 12 Tf 10 250 Td (Synthetic aggregate ALT counts) Tj ET')
        page[NameObject('/Contents')]=writer._add_object(stream)
    output=io.BytesIO();writer.write(output);raw=output.getvalue()
    return dict(evidence_id='synthetic-pdf',kind='file',status='accessible',failure_reason='',
                http_status=200,complete_body=True,format='application/pdf',
                url='https://example.org/supp.pdf',final_url='https://example.org/supp.pdf',
                bytes_observed=len(raw),payload_sha256=digest(raw),
                body_sample_b64=base64.b64encode(raw).decode(),text='',columns=[],level='unverified')


def test_complete_supplement_pdf_text_is_not_promoted_to_dataset_structure():
    e=pdf_record();original=copy.deepcopy(e)
    result=inspect_material(e)
    assert 'Synthetic aggregate ALT counts' in result['text']
    assert result['pdf_page_count']==1 and result['pdf_text_extracted'] is True
    assert result['columns']==[] and result['level']=='response_sample'
    for key in ['body_sample_b64','payload_sha256','bytes_observed','http_status']:
        assert result[key]==original[key]
    assert inspect_material(copy.deepcopy(result))==result


@pytest.mark.parametrize('change',[
    {'complete_body':False}, {'payload_sha256':'changed'}, {'bytes_observed':0},
    {'http_status':403}, {'cloud_checksum':{'verified':False}},
])
def test_unverified_or_incomplete_pdf_cannot_gain_read_text(change):
    e=pdf_record();e.update(change)
    result=inspect_material(e)
    assert not result.get('pdf_text_extracted') and result['text']==''
    assert result['columns']==[]


def test_pdf_page_limit_prevents_unbounded_supplement_inspection():
    result=inspect_material(pdf_record(pages=65))
    assert 'page limit' in result['structure_failure']
    assert not result.get('pdf_text_extracted')


def test_binary_pdf_uses_actual_bytes_without_inventing_table_columns():
    e=pdf_record();e.update(status='fetch_error',failure_reason='redirect_or_empty_body_not_article',
                          format='application/octet-stream')
    result=inspect_material(e)
    assert result['status']=='accessible' and result['failure_reason']==''
    assert result['pdf_text_extracted'] and result['columns']==[]


def test_observed_direct_supplement_pdf_retains_original_kind():
    e=pdf_record();e['kind']='supplementary'
    result=inspect_material(e)
    assert result['kind']=='file' and result['original_kind']=='supplementary'
    assert result['pdf_text_extracted'] and result['columns']==[]
