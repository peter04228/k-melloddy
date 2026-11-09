"""Bounded public PMC cloud discovery; retrieval never supplies a verdict."""
import base64
import copy
import hashlib
import io
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from urllib.parse import urlencode, urlsplit, urlunsplit, unquote, parse_qs, quote
from ..core.storage import digest
from .full_workflow_access import recover_json_metadata, inspect_material
from .revalidation_access import readable_body

BASE='https://pmc-oa-opendata.s3.amazonaws.com/'
HOST='pmc-oa-opendata.s3.amazonaws.com'
NS={'s':'http://s3.amazonaws.com/doc/2006-03-01/'}
MATERIALS=('.zip','.csv','.tsv','.txt','.xls','.xlsx','.json','.xml','.doc','.docx','.h5','.h5ad','.pdf')


def _xml(text):
    if '<!ENTITY' in text.upper() or '<!DOCTYPE' in text.upper():raise ValueError('Unsafe cloud listing XML')
    return ET.fromstring(text)


def _resource(uri,prefix):
    """Map an actually observed official S3 URI to its documented HTTPS form."""
    if not isinstance(uri,str):return None
    u=urlsplit(uri)
    if u.scheme=='s3' and u.netloc=='pmc-oa-opendata':u=u._replace(scheme='https',netloc=HOST)
    if u.scheme!='https' or u.netloc!=HOST or u.fragment:return None
    path=unquote(u.path)
    if not path.startswith('/'+prefix) or any(p in {'.','..'} for p in path.split('/')):return None
    expected=(parse_qs(u.query).get('md5') or [''])[0]
    if not re.fullmatch('[0-9a-fA-F]{32}',expected):return None
    return urlunsplit(u),expected.lower()


def _check_bytes(row,expected):
    if row.get('http_status')!=200 or not row.get('complete_body'):return None
    try:raw=base64.b64decode(row.get('body_sample_b64',''),validate=True)
    except ValueError:return None
    if len(raw)!=row.get('bytes_observed') or digest(raw)!=row.get('payload_sha256'):return None
    actual=hashlib.md5(raw).hexdigest()
    row['cloud_checksum']={'algorithm':'MD5','expected':expected,'observed':actual,'verified':actual==expected}
    if actual!=expected:
        row.update(status='fetch_error',failure_reason='PMC_cloud_MD5_mismatch')
        return None
    return raw


def _legacy_doc_observation(row):
    """Citable access metadata for opaque DOC bytes, never document contents."""
    if (urlsplit(row['url']).path.lower().endswith('.doc')
            and row.get('status')=='accessible' and not row.get('text')):
        row['text']=json.dumps({'observed_file':unquote(urlsplit(row['url']).path.rsplit('/',1)[-1]),
                               'bytes_observed':row['bytes_observed'],
                               'official_md5':row['cloud_checksum'],
                               'document_contents_inspected':False},sort_keys=True)
        row['interpretation_note']='Verified file-access metadata only; opaque legacy DOC contents and table structure are unverified.'


def _article_xml(paper,row,raw):
    if row.get('status')=='access_restricted':return
    try:
        text=raw.decode('utf-8-sig')
        # JATS commonly declares an external DTD. Remove only the declaration;
        # never resolve it, and continue rejecting internal subsets/entities.
        parse_text=re.sub(r'<!DOCTYPE\s+article\s+(?:PUBLIC\s+"[^"<>\[\]]*"\s+"[^"<>\[\]]*"|SYSTEM\s+"[^"<>\[\]]*")\s*>',
                          '',text,count=1,flags=re.I)
        tree=_xml(parse_text);own=tree.find('./front/article-meta')
        if own is None:return
        ids={n.get('pub-id-type'):n.text for n in own.findall('article-id')}
        title=own.find('title-group/article-title')
        norm=lambda s:re.sub(r'\W+','',str(s).casefold())
        actual_pmc=str(ids.get('pmcid') or ids.get('pmc') or '').removeprefix('PMC')
        checks=dict(pmid=ids.get('pmid')==paper['pmid'],
            pmcid=actual_pmc==paper['values']['PMCID'].removeprefix('PMC'),
            doi=bool(paper['values'].get('DOI')) and str(ids.get('doi','')).casefold()==paper['values']['DOI'].casefold(),
            title=title is not None and norm(''.join(title.itertext()))==norm(paper['values']['Title']))
        if not all(checks.values()):
            row.update(status='fetch_error',failure_reason='PMC_cloud_article_identity_mismatch',identity_match=False,identity_checks=checks)
            return
        row['prior_classification']={k:row.get(k) for k in ['status','failure_reason']}
        row.update(status='accessible',failure_reason='',text=text,detected_format='application/xml',
                   identity_match=True,identity_checks=checks,level='response_sample')
    except (ValueError,ET.ParseError,UnicodeError):return


def recover_cloud_materials(paper,bundle):
    """Recheck complete recovery attempts against observed, identity-matched metadata."""
    pmc=paper.get('values',{}).get('PMCID','')
    if not paper.get('_official_verified') or not re.fullmatch(r'PMC\d+',pmc):return bundle
    resources={}
    norm=lambda s:re.sub(r'\W+','',str(s).casefold())
    for record in bundle['records']:
        url=record.get('url','')
        if (record.get('kind')!='metadata' or record.get('status')!='accessible'
                or not url.startswith(BASE)):continue
        path=urlsplit(url).path.lstrip('/')
        if not re.fullmatch(re.escape(pmc)+r'\.[1-9]\d*/'+re.escape(pmc)+r'\.[1-9]\d*\.json',path):continue
        try:data=json.loads(record['text'])
        except (ValueError,KeyError):continue
        if not isinstance(data,dict):continue
        values=paper['values']
        if not (str(data.get('pmid',''))==paper['pmid'] and data.get('pmcid')==pmc
                and values.get('DOI') and str(data.get('doi','')).casefold()==values['DOI'].casefold()
                and norm(data.get('title',''))==norm(values['Title'])):continue
        media=data.get('media_urls',[])
        if not isinstance(media,list):continue
        prefix=path.rsplit('/',1)[0]+'/'
        article_resource=_resource(data.get('xml_url'),prefix)
        if article_resource:
            resources[article_resource[0]]=(data['xml_url'],article_resource[1],'fulltext')
        for uri in media:
            resource=_resource(uri,prefix)
            if resource and urlsplit(resource[0]).path.lower().endswith(MATERIALS):
                resources[resource[0]]=(uri,resource[1],'file')
    for row in bundle['records']:
        if row.get('kind') not in {'file','fulltext'} or row.get('status')=='access_restricted':continue
        resource=resources.get(row.get('url',''))
        if not resource:continue
        uri,expected,kind=resource
        if row['kind']!=kind:continue
        raw=_check_bytes(row,expected)
        if raw is None:continue
        row['cloud_source_uri']=uri
        if kind=='fulltext':
            if row.get('status')!='accessible':_article_xml(paper,row,raw)
            continue
        if row.get('status')=='fetch_error' and row.get('failure_reason')=='redirect_or_empty_body_not_article':
            row['prior_classification']={k:row.get(k) for k in ['status','failure_reason']}
            row.update(status='accessible',failure_reason='',level='response_sample',
                interpretation_note='Complete recovered official cloud object matches observed metadata MD5; structure still requires inspection')
        if urlsplit(row['url']).path.lower().endswith('.zip') and zipfile.is_zipfile(io.BytesIO(raw)):
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                if len(archive.infolist())>1000 or sum(x.file_size for x in archive.infolist())>32*1024*1024:
                    row.update(status='fetch_error',failure_reason='PMC_cloud_archive_expansion_limit');continue
        inspect_material(row)
        _legacy_doc_observation(row)
    return bundle


def collect_cloud(paper,request,prior_records,max_versions=2,max_materials=3):
    """Only use official verified identities, observed keys and checked metadata URLs."""
    if type(max_versions)!=int or not 1<=max_versions<=2 or type(max_materials)!=int or not 0<=max_materials<=3:
        raise ValueError('PMC cloud discovery bounds exceeded')
    result={'records':[],'search_coverage':[]}
    pmc=paper.get('values',{}).get('PMCID','')
    if not paper.get('_official_verified') or not re.fullmatch(r'PMC\d+',pmc):return result
    coverage={'target':'official_PMC_cloud','pmcid':pmc,'state':'attempted','versions':[],
              'documentation':'https://pmc.ncbi.nlm.nih.gov/tools/pmcaws/'}
    result['search_coverage'].append(coverage)
    def fetch(url,kind,route):
        rows=copy.deepcopy(request(url,kind,paper,route));result['records'].extend(rows)
        return rows
    def accessible(rows):return next((e for e in reversed(rows) if e['status']=='accessible'),None)
    try:
        versions=accessible(fetch(BASE+'?'+urlencode({'list-type':2,'prefix':pmc+'.','delimiter':'/','max-keys':100}),
                                  'metadata','PMC_cloud_versions'))
        if not versions:
            coverage['state']='version_lookup_failed';return result
        tree=_xml(versions['text'])
        prefixes=[n.text for n in tree.findall('s:CommonPrefixes/s:Prefix',NS)
                  if re.fullmatch(re.escape(pmc)+r'\.[1-9]\d*/',n.text or '')]
        coverage['version_listing_truncated']=tree.findtext('s:IsTruncated',default='',namespaces=NS)=='true'
        coverage['version_limit_reached']=len(prefixes)>max_versions
        matches=[]
        for prefix in prefixes[:max_versions]:
            state={'prefix':prefix};coverage['versions'].append(state)
            listing=accessible(fetch(BASE+'?'+urlencode({'list-type':2,'prefix':prefix,'max-keys':100}),
                                     'metadata','PMC_cloud_objects'))
            if not listing:state['state']='object_lookup_failed';continue
            tree=_xml(listing['text'])
            keys=[n.text for n in tree.findall('s:Contents/s:Key',NS)]
            state['object_listing_truncated']=tree.findtext('s:IsTruncated',default='',namespaces=NS)=='true'
            key=prefix+prefix.rstrip('/')+'.json'
            if key not in keys:state['state']='metadata_key_not_observed';continue
            rows=fetch(BASE+quote(key,safe='/'),'metadata','PMC_cloud_metadata')
            for row in rows:recover_json_metadata(paper,row)
            meta=accessible(rows)
            if not meta:state['state']='metadata_identity_unverified';continue
            data=json.loads(meta['text']);values=paper['values']
            norm=lambda s:re.sub(r'\W+','',str(s).casefold())
            if not isinstance(data,dict):state['state']='invalid_metadata_schema';continue
            checks=dict(pmid=str(data.get('pmid',''))==paper['pmid'],pmcid=data.get('pmcid')==pmc,
                doi=bool(values.get('DOI')) and str(data.get('doi','')).casefold()==values['DOI'].casefold(),
                title=norm(data.get('title',''))==norm(values['Title']))
            meta.update(identity_checks=checks,identity_match=all(checks.values()))
            if not meta['identity_match']:state['state']='metadata_identity_unverified';continue
            state.update(state='identity_verified',metadata_evidence_id=meta['evidence_id'],
                         license_code=data.get('license_code'),is_manuscript=data.get('is_manuscript'),
                         is_retracted=data.get('is_retracted'))
            matches.append((prefix,data,state))
        # Version numbers do not establish recency. Keep provenance for every matched version.
        matches.sort(key=lambda x:bool(x[1].get('is_manuscript')))
        body_available=any(readable_body(e) for e in prior_records)
        remaining=max_materials
        for prefix,data,state in matches:
            if not body_available and (resource:=_resource(data.get('xml_url'),prefix)):
                url,expected=resource;rows=fetch(url,'fulltext','PMC_cloud_article_xml')
                for row in rows:
                    raw=_check_bytes(row,expected)
                    if raw is not None:_article_xml(paper,row,raw)
                body_available=any(readable_body(e) for e in rows)
            media=data.get('media_urls',[])
            if not isinstance(media,list):state['media_state']='invalid_metadata';continue
            materials=[(uri,res) for uri in media if (res:=_resource(uri,prefix))
                       and urlsplit(res[0]).path.lower().endswith(MATERIALS)]
            state['material_limit_reached']=len(materials)>remaining
            for uri,(url,expected) in materials[:remaining]:
                rows=fetch(url,'file','PMC_cloud_supplement')
                for row in rows:
                    row['cloud_source_uri']=uri
                    raw=_check_bytes(row,expected)
                    if raw is None or row.get('status')=='access_restricted':continue
                    if (raw and row.get('status')=='fetch_error'
                            and row.get('failure_reason')=='redirect_or_empty_body_not_article'):
                        row['prior_classification']={k:row.get(k) for k in ['status','failure_reason']}
                        row.update(status='accessible',failure_reason='',level='response_sample',
                            interpretation_note='Complete official cloud object matches metadata MD5; content structure still requires inspection')
                    # A valid complete archive is accessible even when selecting its table is still outstanding.
                    if (urlsplit(url).path.lower().endswith('.zip') and zipfile.is_zipfile(io.BytesIO(raw))):
                        with zipfile.ZipFile(io.BytesIO(raw)) as z:
                            if len(z.infolist())>1000 or sum(x.file_size for x in z.infolist())>32*1024*1024:
                                row.update(status='fetch_error',failure_reason='PMC_cloud_archive_expansion_limit');continue
                        row['prior_classification']={k:row.get(k) for k in ['status','failure_reason']}
                        row.update(status='accessible',failure_reason='',level='response_sample',detected_format='application/zip')
                    inspect_material(row)
                    _legacy_doc_observation(row)
                remaining-=1
        coverage['state']='investigated' if matches else 'no_verified_version'
    except (ValueError,TypeError,KeyError,ET.ParseError,zipfile.BadZipFile) as exc:
        coverage.update(state='metadata_or_inspection_error',unresolved_reason=type(exc).__name__+': '+str(exc))
    return result
