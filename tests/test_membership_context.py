import base64
import copy
import hashlib
import io
import json

import pytest
from openpyxl import Workbook

from k_melloddy.core.storage import digest
from k_melloddy.db_select.dataset_verifier import verify_dataset


LABEL='DS7 (hepatocellular injury)'


def book_bytes(sheet,rows):
    w=Workbook();s=w.active;s.title=sheet
    for row in rows:s.append(row)
    out=io.BytesIO();w.save(out);w.close();return out.getvalue()


def example(members=None,metadata_rows=None):
    members=members if members is not None else ['A.1.3 hr','B.2.8 day']
    raw=book_bytes('states',[[None,LABEL]]+[[i+1,v] for i,v in enumerate(members)])
    exposure=book_bytes('treatments',[
        ['CDT','Compound','Organ','Dose','Time'],
        *(metadata_rows if metadata_rows is not None else [
            ['A.1.3 hr','A','Liver','10 mg/kg','3 hr'],
            ['A.1.3 hr','A','Liver','10 mg/kg','3 hr'],
            ['B.2.8 day','B','Liver','20 mg/kg','8 day'],
            ['B.2.8 day','B','Kidney','20 mg/kg','8 day']])])
    def file(eid,name,data):
        url='https://pmc-oa-opendata.s3.amazonaws.com/PMC123.1/'+name+'?md5='+hashlib.md5(data).hexdigest()
        return dict(evidence_id=eid,kind='file',status='accessible',http_status=200,
            complete_body=True,url=url,final_url=url,bytes_observed=len(data),payload_sha256=digest(data),
            body_sample_b64=base64.b64encode(data).decode(),cloud_checksum={'verified':True},
            format='xlsx',text=LABEL,columns=[LABEL],level='sample_structure')
    f=file('members','states.xlsx',raw);f['archive_selection']={'sheet':'states','header_row':1}
    x=file('exposure','exposure.xlsx',exposure)
    meta=dict(pmcid='PMC123',pmid=123,doi='10.1234/example',version=1,
        media_urls=[e['url'].replace('https://pmc-oa-opendata.s3.amazonaws.com/','s3://pmc-oa-opendata/') for e in [f,x]])
    encoded=json.dumps(meta).encode()
    m=dict(evidence_id='manifest',kind='metadata',status='accessible',http_status=200,complete_body=True,
        url='https://pmc-oa-opendata.s3.amazonaws.com/PMC123.1/PMC123.1.json',
        identity_checks={k:True for k in ['pmid','pmcid','doi','title']},
        bytes_observed=len(encoded),payload_sha256=digest(encoded),
        body_sample_b64=base64.b64encode(encoded).decode(),text=encoded.decode())
    a=dict(evidence_id='article',kind='fulltext',status='accessible',http_status=200,
        complete_body=True,identity_match=True,text='10.1234/example describes computed DS7 category membership, not clinical causality.')
    ref=lambda eid,q:dict(evidence_id=eid,quote=q)
    context=dict(scope='column_membership_list',reviewer_rationale='Computed category; retain original condition IDs.',
        member_column=LABEL,metadata_evidence_id='exposure',metadata_sheet='treatments',
        key_field='CDT',drug_field='Compound',context_fields=['Dose','Time'],filter={'field':'Organ','value':'Liver'},
        binding_reference=ref('manifest','states.xlsx'),classification_reference=ref('article','computed DS7 category membership'))
    d=dict(name=LABEL,identity='url:'+f['url'],version='original',direct_url=f['url'],evidence_id='members',
        drug_identifier=LABEL,endpoint=LABEL,value_field=LABEL,independence_reason='New published computed list.',
        feature_count=None,compound_count=None,evidence_refs=[ref('members',LABEL)])
    b=dict(records=[f,x,m,a],column_memberships=[dict(evidence_id='members',context=context)])
    return d,b


def test_actual_membership_and_exposure_values_are_bound_without_new_columns():
    d,b=example();before=copy.deepcopy(b);out=verify_dataset(d,b)
    p=out['membership_context'];assert b==before and b['records'][0]['columns']==[LABEL]
    assert p['member_count_checked']==2 and p['filter']=={'field':'Organ','value':'Liver'}
    assert p['bindings']==[
        {'member':'A.1.3 hr','source_values':{'Compound':'A','Dose':'10 mg/kg','Time':'3 hr'}},
        {'member':'B.2.8 day','source_values':{'Compound':'B','Dose':'20 mg/kg','Time':'8 day'}}]
    assert out['compound_count'] is None and out['feature_count'] is None
    assert verify_dataset(d,b)==out


def test_session_review_retains_context_outside_the_unchanged_scientific_proposal():
    from k_melloddy.db_select.full_workflow import SessionProvider
    d,b=example();contexts=b.pop('column_memberships');b['workflow']=[]
    answer=dict(proposal=d,reviewer_note='Reviewed published computed membership.',
        evidence_review={'column_memberships':contexts})
    original=copy.deepcopy(answer)
    provider=object.__new__(SessionProvider);provider.response=lambda *args:answer
    reviewed=provider._review_evidence({}, {}, b, None)
    assert 'column_memberships' not in b and answer==original
    assert verify_dataset(d,reviewed)['membership_context']['member_count_checked']==2
    assert 'membership_context' not in d


@pytest.mark.parametrize('members',[
    ['A.1.3 hr','A.1.3 hr'],['A.1.3 hr',None,'B.2.8 day'],['=SUM(1,2)'],['unmatched'],[123]])
def test_invalid_or_unmapped_membership_values_are_rejected(members):
    d,b=example(members=members)
    with pytest.raises(ValueError):verify_dataset(d,b)


@pytest.mark.parametrize('rows',[
    [['A.1.3 hr','A','Kidney','10 mg/kg','3 hr'],['B.2.8 day','B','Liver','20 mg/kg','8 day']],
    [['A.1.3 hr','A','Liver','10 mg/kg','3 hr'],['A.1.3 hr','other','Liver','10 mg/kg','3 hr'],['B.2.8 day','B','Liver','20 mg/kg','8 day']],
    [['A.1.3 hr','A','Liver',None,'3 hr'],['B.2.8 day','B','Liver','20 mg/kg','8 day']],
    [['A.1.3 hr','A','Liver','=1+1','3 hr'],['B.2.8 day','B','Liver','20 mg/kg','8 day']]])
def test_missing_ambiguous_or_formula_exposure_binding_is_rejected(rows):
    d,b=example(metadata_rows=rows)
    with pytest.raises(ValueError):verify_dataset(d,b)


@pytest.mark.parametrize('change',['absent','duplicate','column','hash','checksum','manifest','article','unverified'])
def test_explicit_provenance_context_is_mandatory(change):
    d,b=example()
    if change=='absent':d=verify_dataset(d,b);b.pop('column_memberships')
    if change=='duplicate':b['column_memberships']*=2
    if change=='column':b['column_memberships'][0]['context']['member_column']='invented'
    if change=='hash':b['records'][1]['payload_sha256']='changed'
    if change=='checksum':b['records'][1]['cloud_checksum']['verified']=False
    if change=='manifest':b['records'][2]['url']='https://example.org/manifest'
    if change=='article':b['records'][3]['text']='Other DOI computed DS7 category membership'
    if change=='unverified':b['records'][2]['identity_checks']['doi']=False
    with pytest.raises(ValueError):verify_dataset(d,b)
