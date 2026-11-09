import base64
import copy
import io

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from k_melloddy.core.storage import digest
from k_melloddy.db_select.full_workflow_access import inspect_material


def pdf_record(pages=1,lines=None,password=None):
    writer=PdfWriter()
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),
                           NameObject('/Subtype'):NameObject('/Type1'),
                           NameObject('/BaseFont'):NameObject('/Helvetica')})
    for _ in range(pages):
        page=writer.add_blank_page(width=300,height=300)
        page[NameObject('/Resources')]=DictionaryObject({
            NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
        stream=DecodedStreamObject()
        if lines is None:
            stream.set_data(b'BT /F1 12 Tf 10 250 Td (Synthetic aggregate ALT counts) Tj ET')
        else:
            content='BT /F1 8 Tf 10 TL 10 250 Td '+' T* '.join('('+line+') Tj' for line in lines)+' ET'
            stream.set_data(content.encode('ascii'))
        page[NameObject('/Contents')]=writer._add_object(stream)
    if password is not None:writer.encrypt(user_password=password,owner_password='synthetic-owner')
    output=io.BytesIO();writer.write(output);raw=output.getvalue()
    return dict(evidence_id='synthetic-pdf',kind='file',status='accessible',failure_reason='',
                http_status=200,complete_body=True,format='application/pdf',
                url='https://example.org/supp.pdf',final_url='https://example.org/supp.pdf',
                bytes_observed=len(raw),payload_sha256=digest(raw),
                body_sample_b64=base64.b64encode(raw).decode(),text='',columns=[],level='unverified')


def ltkb_lines():
    return ['Table S1. Synthetic fixture only',
            'LTKBID LabelCompoundName verified-DILI-Concern Area in Fig. 4',
            'LT00001 synthetic acid vMost-DILI-Concern C',
            'LTKBID LabelCompoundName verified-DILI-Concern Area in Fig. 4',
            'LT00002 synthetic control vNo-DILI-Concern A','Table S2. Other table']


def test_explicit_pdf_table_checks_all_rows_without_inventing_counts():
    from k_melloddy.db_select.archive_review import selected_ltkb_pdf_tables
    from k_melloddy.db_select.dataset_verifier import verify_dataset
    e=pdf_record(lines=ltkb_lines());bundle={'records':[e]};before=copy.deepcopy(bundle)
    selection=dict(parent_evidence_id=e['evidence_id'],start_marker='Table S1.',end_marker='Table S2.')
    result=selected_ltkb_pdf_tables(bundle,[selection]);table=result['records'][-1]
    assert bundle==before and table['columns']==['LTKBID','LabelCompoundName','verified-DILI-Concern','Area in Fig. 4']
    assert table['body_sample_b64']==e['body_sample_b64'] and table['request_performed'] is False
    assert 'synthetic acid' in table['text'] and 'compound_count' not in table
    dataset=dict(name='synthetic',identity='url:'+e['url'],version='fixture',direct_url=e['url'],
        evidence_id=table['evidence_id'],drug_identifier='LTKBID',endpoint='Area in Fig. 4',
        value_field='Area in Fig. 4',independence_reason='Synthetic fixture only',
        feature_count=None,compound_count=None,
        evidence_refs=[dict(evidence_id=table['evidence_id'],quote='LT00001')])
    assert verify_dataset(dataset,result)['verification_level']=='sample_structure'
    assert len(selected_ltkb_pdf_tables(result,[selection])['records'])==2


@pytest.mark.parametrize('mode',['bad_row','duplicate_id','wrong_header','ambiguous_marker','missing_end','wrong_hash','incomplete','restricted'])
def test_pdf_table_rejects_missing_or_ambiguous_evidence(mode):
    from k_melloddy.db_select.archive_review import selected_ltkb_pdf_tables
    lines=ltkb_lines()
    if mode=='bad_row':lines.insert(3,'unmatched wrapped continuation')
    if mode=='duplicate_id':lines[4]=lines[4].replace('LT00002','LT00001')
    if mode=='wrong_header':lines[1]=lines[1].replace('LTKBID','invented')
    if mode=='ambiguous_marker':lines.insert(0,'Table S1. Duplicate caption')
    if mode=='missing_end':lines.pop()
    e=pdf_record(lines=lines)
    if mode=='wrong_hash':e['payload_sha256']='changed'
    if mode=='incomplete':e['complete_body']=False
    if mode=='restricted':e['status']='access_restricted'
    with pytest.raises(ValueError):
        selected_ltkb_pdf_tables({'records':[e]},[dict(parent_evidence_id=e['evidence_id'],
            start_marker='Table S1.',end_marker='Table S2.')])


@pytest.mark.parametrize('password',['','nonempty-user-password'])
def test_pdf_table_opens_only_without_a_user_password(password):
    from k_melloddy.db_select.archive_review import selected_ltkb_pdf_tables
    e=pdf_record(lines=ltkb_lines(),password=password)
    selection=dict(parent_evidence_id=e['evidence_id'],start_marker='Table S1.',end_marker='Table S2.')
    if password:
        with pytest.raises(ValueError,match='user password'):selected_ltkb_pdf_tables({'records':[e]},[selection])
    else:
        result=selected_ltkb_pdf_tables({'records':[e]},[selection])['records'][-1]
        assert result['pdf_encrypted'] and result['pdf_opened_without_user_password']


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
