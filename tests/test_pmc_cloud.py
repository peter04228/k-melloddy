import base64
import copy
import hashlib
import json
from urllib.parse import urlsplit,parse_qs
from k_melloddy.core.storage import digest
from k_melloddy.db_select.pmc_cloud import collect_cloud,recover_cloud_materials,BASE,_resource


PAPER=dict(_official_verified=True,pmid='123',values=dict(PMCID='PMC123',DOI='10.1234/test',Title='Synthetic liver study.'))
CSV=b'Drug,DILI\nsynthetic,1\n'
XML=b'<article><front><article-meta><article-id pub-id-type="pmid">123</article-id><article-id pub-id-type="pmc">PMC123</article-id><article-id pub-id-type="doi">10.1234/test</article-id><title-group><article-title>Synthetic liver study</article-title></title-group></article-meta></front><body><sec><title>Methods</title><p>'+b'Actual synthetic protocol description. '*15+b'</p></sec></body></article>'


class Requests:
    def __init__(self,bad_identity=False,bad_checksum=False):
        self.urls=[];self.bad_identity=bad_identity;self.bad_checksum=bad_checksum
    def __call__(self,url,kind,paper,route):
        self.urls.append(url)
        u=urlsplit(url);q=parse_qs(u.query)
        if 'list-type' in q:
            if q['prefix']==['PMC123.']:
                body='<CommonPrefixes><Prefix>PMC123.1/</Prefix></CommonPrefixes>'
            else:body='<Contents><Key>PMC123.1/PMC123.1.json</Key></Contents>'
            raw=('<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'+body+'<IsTruncated>false</IsTruncated></ListBucketResult>').encode()
            status='accessible';fmt='application/xml';text=raw.decode()
        elif u.path.endswith('.json'):
            data=dict(pmid=999 if self.bad_identity else 123,pmcid='PMC123',doi='10.1234/test',title='Synthetic liver study',license_code='CC BY',is_manuscript=False,
                xml_url='s3://pmc-oa-opendata/PMC123.1/PMC123.1.xml?md5='+hashlib.md5(XML).hexdigest(),
                media_urls=['s3://pmc-oa-opendata/PMC123.1/data.csv?md5='+hashlib.md5(CSV).hexdigest(),
                            'https://untrusted.example/data.csv?md5='+hashlib.md5(CSV).hexdigest()])
            raw=json.dumps(data).encode();status='fetch_error';fmt='binary/octet-stream';text=''
        elif u.path.endswith('.xml'):
            raw=XML;status='fetch_error';fmt='binary/octet-stream';text=''
        else:
            raw=b'altered' if self.bad_checksum else CSV;status='fetch_error';fmt='binary/octet-stream';text=''
        return [dict(evidence_id='capture-'+str(len(self.urls)),url=url,final_url=url,kind=kind,
            timestamp='2026-11-08T00:00:00Z',attempt=1,route=route,http_status=200,
            status=status,failure_reason='redirect_or_empty_body_not_article' if status=='fetch_error' else '',
            format=fmt,text=text,identity_match=False,complete_body=True,level='unverified',columns=[],
            downloaded_full_dataset=False,body_sample_b64=base64.b64encode(raw).decode(),
            payload_sha256=digest(raw),bytes_observed=len(raw))]


def test_verified_metadata_and_md5_resource_recover_actual_binary_content():
    request=Requests();result=collect_cloud(PAPER,request,[])
    assert result['search_coverage'][0]['state']=='investigated'
    article=next(e for e in result['records'] if e['kind']=='fulltext')
    data=next(e for e in result['records'] if e['kind']=='file')
    assert article['identity_match'] and article['status']=='accessible'
    assert article['format']=='binary/octet-stream' and article['detected_format']=='application/xml'
    assert data['status']=='accessible' and data['columns']==['Drug','DILI']
    assert data['cloud_checksum']['verified'] and data['format']=='binary/octet-stream'
    assert not any('untrusted.example' in url for url in request.urls)
    assert 'fulltext_reviewed' not in result and 'datasets' not in result


def test_wrong_identity_never_follows_article_or_media_urls():
    request=Requests(bad_identity=True);result=collect_cloud(PAPER,request,[])
    assert result['search_coverage'][0]['state']=='no_verified_version'
    assert all(e['kind']=='metadata' for e in result['records'])


def test_listed_legacy_doc_is_accessible_bytes_without_claiming_structure():
    raw=b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'+b'Synthetic opaque fixture, not a clinical table.'
    md5=hashlib.md5(raw).hexdigest();url=BASE+'PMC123.1/supplement.doc?md5='+md5
    metadata=dict(pmid=123,pmcid='PMC123',doi='10.1234/test',title='Synthetic liver study',media_urls=[url])
    parent=dict(evidence_id='legacy',kind='file',status='fetch_error',http_status=200,url=url,final_url=url,
                failure_reason='redirect_or_empty_body_not_article',complete_body=True,
                body_sample_b64=base64.b64encode(raw).decode(),payload_sha256=digest(raw),bytes_observed=len(raw),
                format='binary/octet-stream',text='',level='unverified',columns=[])
    bundle={'records':[dict(kind='metadata',status='accessible',url=BASE+'PMC123.1/PMC123.1.json',text=json.dumps(metadata)),parent]}
    result=recover_cloud_materials(PAPER,copy.deepcopy(bundle))['records'][-1]
    assert result['status']=='accessible' and result['cloud_checksum']['verified']
    assert result['level']=='response_sample' and result['columns']==[]
    assert result['body_sample_b64']==parent['body_sample_b64'] and result['text']==''
    assert result['prior_classification']['status']=='fetch_error'
    altered=copy.deepcopy(bundle);altered['records'][-1]['complete_body']=False
    assert recover_cloud_materials(PAPER,altered)['records'][-1]['status']=='fetch_error'


def test_bad_checksum_never_becomes_structured_data():
    result=collect_cloud(PAPER,Requests(bad_checksum=True),[])
    file=next(e for e in result['records'] if e['kind']=='file')
    assert file['status']=='fetch_error' and file['failure_reason']=='PMC_cloud_MD5_mismatch'
    assert not file['columns'] and not file['cloud_checksum']['verified']


def test_unverified_inputs_and_foreign_paths_never_trigger_retrieval():
    request=Requests();paper=copy.deepcopy(PAPER);paper['_official_verified']=False
    assert collect_cloud(paper,request,[])=={'records':[],'search_coverage':[]}
    assert request.urls==[]
    assert _resource('s3://pmc-oa-opendata/PMC999.1/data.csv?md5='+'0'*32,'PMC123.1/') is None
    assert _resource(BASE+'PMC123.1/../PMC999.1/file?md5='+'0'*32,'PMC123.1/') is None
    assert _resource(BASE+'PMC123.1/file','PMC123.1/') is None


def recovered_bundle(corrupt=False):
    import io,zipfile
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w') as archive:
        archive.writestr('research.bin',b'x'*300000)
    raw=buffer.getvalue();expected=hashlib.md5(raw).hexdigest()
    url=BASE+'PMC123.1/supplement.zip?md5='+expected
    metadata=dict(pmid=123,pmcid='PMC123',doi='10.1234/test',title='Synthetic liver study',
                  media_urls=[url])
    meta=dict(kind='metadata',status='accessible',url=BASE+'PMC123.1/PMC123.1.json',text=json.dumps(metadata))
    def row(payload,complete,eid):
        return dict(evidence_id=eid,kind='file',status='fetch_error',http_status=200,url=url,final_url=url,
            failure_reason='redirect_or_empty_body_not_article',complete_body=complete,
            body_sample_b64=base64.b64encode(payload).decode(),payload_sha256=digest(payload),
            bytes_observed=len(payload),format='binary/octet-stream',text='',level='unverified',columns=[])
    return {'records':[meta,row(raw[:262145],False,'truncated'),row(raw+b'bad' if corrupt else raw,True,'recovered')]}


def test_complete_recovery_rechecks_metadata_md5_without_promoting_truncated_attempt():
    bundle=recovered_bundle();result=recover_cloud_materials(PAPER,bundle)
    truncated,recovered=result['records'][1:]
    assert truncated['status']=='fetch_error' and not truncated['complete_body']
    assert recovered['status']=='accessible' and recovered['cloud_checksum']['verified']
    assert recovered['level']=='response_sample' and not recovered['columns']
    assert recovered['prior_classification']['status']=='fetch_error'
    before=copy.deepcopy(result);recover_cloud_materials(PAPER,result)
    assert result==before


def test_recovered_checksum_mismatch_stays_failed():
    result=recover_cloud_materials(PAPER,recovered_bundle(corrupt=True))
    assert result['records'][-1]['status']=='fetch_error'
    assert result['records'][-1]['failure_reason']=='PMC_cloud_MD5_mismatch'


def test_recovery_requires_verified_article_and_actual_matching_metadata_resource():
    for mode in ['unverified','wrong_identity','unlisted']:
        bundle=recovered_bundle();paper=copy.deepcopy(PAPER)
        if mode=='unverified':paper['_official_verified']=False
        else:
            metadata=json.loads(bundle['records'][0]['text'])
            if mode=='wrong_identity':metadata['pmid']=999
            else:metadata['media_urls']=[]
            bundle['records'][0]['text']=json.dumps(metadata)
        recover_cloud_materials(paper,bundle)
        assert bundle['records'][-1]['status']=='fetch_error'
        assert 'cloud_checksum' not in bundle['records'][-1]


def test_external_jats_declaration_is_read_without_resolving_dtd(monkeypatch):
    declaration=b'<!DOCTYPE article PUBLIC "-//NLM//DTD JATS//EN" "https://invalid.example/JATS.dtd">\n'
    monkeypatch.setattr(__import__(__name__,fromlist=['XML']),'XML',declaration+XML)
    result=collect_cloud(PAPER,Requests(),[])
    article=next(e for e in result['records'] if e['kind']=='fulltext')
    assert article['status']=='accessible' and article['identity_match']
    assert article['text'].startswith('<!DOCTYPE') and article['cloud_checksum']['verified']
    assert all('invalid.example' not in e['url'] for e in result['records'])


def test_article_dtd_does_not_allow_internal_entities_or_wrong_identity(monkeypatch):
    original=XML
    for raw in [b'<!DOCTYPE article [<!ENTITY x SYSTEM "file:///private">]>'+original,
                b'<!DOCTYPE article SYSTEM "unused.dtd">'+original.replace(b'>123<',b'>999<')]:
        monkeypatch.setattr(__import__(__name__,fromlist=['XML']),'XML',raw)
        result=collect_cloud(PAPER,Requests(),[])
        article=next(e for e in result['records'] if e['kind']=='fulltext')
        assert article['status']!='accessible' and not article['identity_match']


def test_cached_article_xml_recovers_only_after_observed_md5_validation():
    for corrupt in [False,True]:
        result=collect_cloud(PAPER,Requests(),[])
        article=next(e for e in result['records'] if e['kind']=='fulltext')
        article.update(status='fetch_error',failure_reason='redirect_or_empty_body_not_article',text='',identity_match=False)
        if corrupt:
            raw=XML+b'bad';article.update(body_sample_b64=base64.b64encode(raw).decode(),payload_sha256=digest(raw),bytes_observed=len(raw))
        recover_cloud_materials(PAPER,result)
        assert (article['status']=='accessible') is (not corrupt)
        assert article['cloud_checksum']['verified'] is (not corrupt)
