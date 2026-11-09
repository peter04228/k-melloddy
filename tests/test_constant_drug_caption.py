import copy
import pytest
from k_melloddy.db_select.dataset_verifier import verify_dataset


def sample():
    caption='Clinical observations in subjects exposed to synthetic-drug. '
    e=dict(evidence_id='file',kind='file',status='accessible',url='https://example.org/data.docx',
           final_url='https://example.org/data.docx',level='sample_structure',columns=['Case','ALT'],
           document_text=caption+'Case ALT 1 12',text=caption+'Case ALT 1 12',
           payload_sha256='captured-hash',format='application/docx')
    d=dict(name='synthetic',identity='url:https://example.org/data.docx',version='1',direct_url=e['url'],
           evidence_id='file',drug_identifier='constant:synthetic-drug',endpoint='ALT',value_field='ALT',
           independence_reason='Synthetic test only',feature_count=None,compound_count=None,
           evidence_refs=[dict(evidence_id='file',quote='subjects exposed to synthetic-drug')])
    return d,{'records':[e]}


def test_explicit_constant_caption_keeps_original_columns_and_identifier():
    d,b=sample();before=copy.deepcopy(b)
    result=verify_dataset(d,b)
    assert result['drug_identifier']=='constant:synthetic-drug'
    assert b==before and b['records'][0]['columns']==['Case','ALT']


@pytest.mark.parametrize('mode',['wrong_drug','empty_constant','unprefixed','body_only','quote_without_drug','different_evidence','missing_value_column'])
def test_constant_needs_same_file_caption_and_real_measurement_column(mode):
    d,b=sample();e=b['records'][0]
    if mode=='wrong_drug':d['drug_identifier']='constant:other'
    if mode=='empty_constant':d['drug_identifier']='constant:'
    if mode=='unprefixed':d['drug_identifier']='synthetic-drug'
    if mode=='body_only':e['document_text']='Unrelated caption. Case ALT synthetic-drug'
    if mode=='quote_without_drug':d['evidence_refs'][0]['quote']='Clinical observations'
    if mode=='different_evidence':
        other=copy.deepcopy(e);other['evidence_id']='article';b['records'].append(other)
        d['evidence_refs'][0]['evidence_id']='article'
    if mode=='missing_value_column':d['value_field']='invented'
    with pytest.raises(ValueError):verify_dataset(d,b)
