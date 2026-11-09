"""Single-agent context must bind the actual file to the reviewed official article."""
import base64
import copy
import hashlib
import json
import pytest
from k_melloddy.core.storage import digest
from k_melloddy.db_select.dataset_verifier import verify_dataset


def captured(eid,kind,url,raw,text):
    return dict(evidence_id=eid,kind=kind,url=url,final_url=url,status='accessible',
                http_status=200,complete_body=True,identity_match=True,
                body_sample_b64=base64.b64encode(raw).decode(),payload_sha256=digest(raw),
                bytes_observed=len(raw),text=text,format='application/test',columns=[],level='response_sample')


def example():
    raw=b'actual synthetic fixture bytes'
    uri='s3://pmc-oa-opendata/PMC123.1/data.xlsx?md5='+hashlib.md5(raw).hexdigest()
    url=uri.replace('s3://pmc-oa-opendata/','https://pmc-oa-opendata.s3.amazonaws.com/')
    meta={'pmcid':'PMC123','pmid':123,'doi':'10.1234/example','title':'Study','version':1,'media_urls':[uri]}
    encoded=json.dumps(meta).encode()
    m=captured('meta','metadata','https://pmc-oa-opendata.s3.amazonaws.com/PMC123.1/PMC123.1.json',encoded,encoded.decode())
    m['identity_checks']={k:True for k in ['pmid','pmcid','doi','title']}
    b=captured('body','fulltext','https://pmc.ncbi.nlm.nih.gov/articles/PMC123/',b'<body>source</body>',
               'We study agent A poisoning. All participants belong to this exposure cohort.')
    f=captured('file','file',url,raw,'ALT measured values');f.update(columns=['ALT'],level='sample_structure',cloud_checksum={'verified':True})
    ref=lambda eid,q:dict(evidence_id=eid,quote=q)
    refs=[ref('body','We study agent A poisoning.'),ref('body','All participants belong to this exposure cohort.'),ref('meta',uri),ref('file','ALT')]
    d=dict(name='Observed measurements',identity='doi:10.1234/example.data',version='1',direct_url=url,
           evidence_id='file',drug_identifier='constant:agent A',endpoint='ALT',value_field='ALT',
           independence_reason='Study measurements',feature_count=None,compound_count=None,evidence_refs=refs,
           drug_context=dict(scope='single_agent_cohort',drug='agent A',reviewer_rationale='Explicitly reviewed one exposure cohort.',
                             exposure_reference=refs[0],population_reference=refs[1],file_binding_reference=refs[2]))
    context=d.pop('drug_context')
    return d,{'records':[b,m,f],'single_agent_contexts':[dict(evidence_id='file',drug_identifier=d['drug_identifier'],context=context)]}


def test_explicit_single_cohort_context_keeps_real_columns_and_source_bytes():
    d,b=example();before=copy.deepcopy(b);out=verify_dataset(d,b)
    assert out['drug_context']['binding_verified'] and out['drug_context']['source_pmcid']=='PMC123'
    assert b==before and b['records'][-1]['columns']==['ALT']
    assert out['feature_count'] is None and out['compound_count'] is None
    assert 'drug_context' not in d


@pytest.mark.parametrize('target,field,value',[
    (0,'identity_match',False),(0,'complete_body',False),(0,'http_status',403),
    (0,'final_url','https://pmc.ncbi.nlm.nih.gov/articles/PMC999/'),
    (0,'kind','metadata'),(1,'identity_match',False),(1,'payload_sha256','changed'),
    (1,'url','https://example.org/PMC123.1.json'),(1,'complete_body',False),
    (1,'identity_checks',{'pmid':True,'pmcid':False,'doi':True,'title':True}),
    (2,'cloud_checksum',{'verified':False}),(2,'complete_body',False),
    (2,'payload_sha256','changed'),(2,'bytes_observed',1),(2,'status','access_restricted'),
    (2,'final_url','https://example.org/data.xlsx')])
def test_unverified_cross_article_or_changed_file_context_is_rejected(target,field,value):
    d,b=example();b['records'][target][field]=value
    with pytest.raises(ValueError):verify_dataset(d,b)


@pytest.mark.parametrize('field,value',[('scope','mixed_cohort'),('drug','another agent'),('reviewer_rationale','')])
def test_context_cannot_be_inferred_or_silently_reassigned(field,value):
    d,b=example();b['single_agent_contexts'][0]['context'][field]=value
    with pytest.raises(ValueError):verify_dataset(d,b)


def test_cited_title_without_actual_exposure_word_is_insufficient():
    d,b=example();b['single_agent_contexts'][0]['context']['exposure_reference']['quote']='All participants belong to this exposure cohort.'
    with pytest.raises(ValueError):verify_dataset(d,b)


def test_wrong_metadata_file_uri_and_forged_md5_are_rejected():
    for change in ['different-file.xlsx','wrong-md5']:
        d,b=example();m=b['records'][1];data=json.loads(m['text'])
        uri=data['media_urls'][0]
        altered=uri.replace('data.xlsx','different-file.xlsx') if change=='different-file.xlsx' else uri[:-32]+'0'*32
        data['media_urls']=[altered];raw=json.dumps(data).encode()
        m.update(text=raw.decode(),body_sample_b64=base64.b64encode(raw).decode(),bytes_observed=len(raw),payload_sha256=digest(raw))
        b['single_agent_contexts'][0]['context']['file_binding_reference']['quote']=altered
        if change=='wrong-md5':
            new=altered.replace('s3://pmc-oa-opendata/','https://pmc-oa-opendata.s3.amazonaws.com/')
            d['direct_url']=new;b['records'][-1].update(url=new,final_url=new)
        with pytest.raises(ValueError):verify_dataset(d,b)


def test_regular_column_and_existing_caption_paths_remain_supported():
    d,b=example();b.pop('single_agent_contexts');d['drug_identifier']='ALT'
    assert verify_dataset(d,b)['drug_identifier']=='ALT'
    d['drug_identifier']='constant:agent A';b['records'][-1]['document_text']='agent A cohort ALT'
    d['evidence_refs'].append({'evidence_id':'file','quote':'agent A cohort'})
    b['records'][-1]['text']+=' agent A cohort'
    assert verify_dataset(d,b)['drug_identifier']=='constant:agent A'


def test_context_selection_passes_frozen_proposal_and_session_interface():
    from k_melloddy.db_select.full_workflow import SessionProvider
    from k_melloddy.db_select.decision import fulltext_decision
    from k_melloddy.db_select.schema import validate,PROPOSAL
    d,b=example();contexts=b.pop('single_agent_contexts');b['workflow']=[]
    proposal=dict(status='confirmed',code='',reason='Verified measured data',datasets=[d],source_databases=[],
                  conditions={k:True for k in ['relevance','actual_data','direct_path','structure','independent']},
                  evidence_refs=d['evidence_refs'],what_confirmed=['Measured file'],what_unresolved=[],next_verification_action='')
    validate(proposal,PROPOSAL)
    answer=dict(proposal=proposal,reviewer_note='Explicit review',evidence_review=dict(single_agent_contexts=contexts,
                fulltext_reviewed=True,sections=[dict(name='Methods',reference=d['evidence_refs'][1])]))
    v=object.__new__(SessionProvider);v.response=lambda *args:answer
    bundle=v._review_evidence({}, {},b,None)
    assert fulltext_decision(proposal,bundle)['datasets'][0]['drug_context']['binding_verified']
    assert 'single_agent_contexts' not in b


def test_duplicate_or_other_file_context_cannot_supply_drug_identity():
    for duplicate in [True,False]:
        d,b=example()
        if duplicate:b['single_agent_contexts']*=2
        else:b['single_agent_contexts'][0]['evidence_id']='another file'
        with pytest.raises(ValueError):verify_dataset(d,b)
