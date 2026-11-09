import base64
import copy
import json
import pytest
from k_melloddy.core.storage import digest
from k_melloddy.db_select.html_table_review import selected_html_tables
from k_melloddy.db_select.dataset_verifier import verify_dataset


HTML='''<html><table><thead><tr><td rowspan="2">Drug</td><td colspan="2">Peak values</td></tr>
<tr><td>ALT (U/L)</td><td>Outcome</td></tr></thead><tbody>
<tr><td>observed A</td><td>600</td><td>Recovered</td></tr>
<tr><td>observed B</td><td>not done</td><td>Improved</td></tr></tbody></table></html>'''


def evidence(html=HTML):
    raw=html.encode()
    return {'records':[dict(evidence_id='article',kind='fulltext',status='accessible',identity_match=True,
                           http_status=200,complete_body=True,bytes_observed=len(raw),payload_sha256=digest(raw),
                           url='https://example.org/article',final_url='https://example.org/article',
                           format='text/html',text=html,level='response_sample',columns=[],
                           body_sample_b64=base64.b64encode(raw).decode())]}


CHOICE=dict(parent_evidence_id='article',table_index=0)


def test_explicit_header_spans_preserve_rows_and_original_evidence():
    bundle=evidence();before=copy.deepcopy(bundle)
    result=selected_html_tables(bundle,[CHOICE]);e=result['records'][-1]
    assert e['columns']==['Drug','ALT (U/L)','Outcome']
    assert json.loads(e['text'])['sample']==[['observed A','600','Recovered'],['observed B','not done','Improved']]
    assert e['source_header_rows'][0][0]['rowspan']==2 and e['source_kind']=='fulltext'
    assert e['kind']=='file' and e['request_performed'] is False and e['downloaded_full_dataset'] is False
    assert bundle==before and len(selected_html_tables(result,[CHOICE])['records'])==2
    ds=dict(name='fixture',identity='url:'+e['url'],version='fixture',direct_url=e['url'],evidence_id=e['evidence_id'],
            drug_identifier='Drug',endpoint='ALT (U/L)',value_field='ALT (U/L)',independence_reason='fixture',
            feature_count=None,compound_count=None,evidence_refs=[dict(evidence_id=e['evidence_id'],quote='ALT (U/L)')])
    assert verify_dataset(ds,result)['compound_count'] is None
    ds['drug_identifier']='invented'
    with pytest.raises(ValueError):verify_dataset(ds,result)


@pytest.mark.parametrize('replacement',[
    ('rowspan="2"','rowspan="9"'),('colspan="2"','colspan="0"'),
    ('ALT (U/L)','Outcome'),('<td>600</td>',''),
    ('<td>600</td>','<td colspan="2">600</td>'),
    ('</table>',''),('<td>600</td>','<td><table></table></td>'),
])
def test_malformed_or_ambiguous_tables_fail_without_inferred_cells(replacement):
    with pytest.raises(ValueError):selected_html_tables(evidence(HTML.replace(*replacement)),[CHOICE])


@pytest.mark.parametrize('field,value',[
    ('complete_body',False),('identity_match',False),('http_status',403),
    ('payload_sha256','changed'),('cloud_checksum',{'verified':False}),('bytes_observed',1)
])
def test_source_identity_access_completeness_and_hash_are_required(field,value):
    bundle=evidence();bundle['records'][0][field]=value
    with pytest.raises(ValueError):selected_html_tables(bundle,[CHOICE])


@pytest.mark.parametrize('before',[True,False])
def test_unselected_equation_layout_does_not_change_selected_data_table(before):
    equation='<table class="disp-formula"><tr><td>observed equation</td></tr></table>'
    html=equation+HTML if before else HTML+equation
    bundle=evidence(html);original=copy.deepcopy(bundle)
    choice=dict(parent_evidence_id='article',table_index=1 if before else 0)
    result=selected_html_tables(bundle,[choice]);record=result['records'][-1]
    assert record['columns']==['Drug','ALT (U/L)','Outcome']
    assert json.loads(record['text'])['sample'][1]==['observed B','not done','Improved']
    assert record['html_table_selection']['table_index']==(1 if before else 0)
    assert bundle==original and len(selected_html_tables(result,[choice])['records'])==2
    with pytest.raises(ValueError,match='Explicit HTML header/body'):
        selected_html_tables(bundle,[dict(parent_evidence_id='article',table_index=0 if before else 1)])


@pytest.mark.parametrize('bad_index',[-1,True,1.0,'0',64])
def test_selected_table_index_remains_explicit_and_bounded(bad_index):
    with pytest.raises(ValueError,match='Invalid HTML table index'):
        selected_html_tables(evidence(),[dict(parent_evidence_id='article',table_index=bad_index)])
