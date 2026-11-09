"""Bounded public-link investigation, separate from the model's claims.

The built-in collector does not certify investigation completeness. An expert
collector plugin can supply a complete, cited survey; otherwise exclusions fail closed.
"""
import copy
import base64
import ipaddress
import socket
import urllib.parse
import urllib.request
import urllib.error
from html.parser import HTMLParser
from typing import Protocol
from ..core.storage import digest, now, uid


class EvidenceCollector(Protocol):
    def collect(self, paper: dict, policy: dict, action: str = '') -> dict: ...


def public_url(url):
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Not a public HTTP(S) URL')
    for info in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme=='https' else 80)):
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise ValueError('Nonpublic address is not allowed')
    return url


class PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        public_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


class Page(HTMLParser):
    def __init__(self):
        super().__init__(); self.text=[]; self.links=[]; self.skip=0
    def handle_starttag(self,tag,attrs):
        if tag in {'script','style'}: self.skip+=1
        attrs=dict(attrs)
        if tag=='a' and attrs.get('href'): self.links.append(attrs['href'])
    def handle_endtag(self,tag):
        if tag in {'script','style'}: self.skip=max(0,self.skip-1)
    def handle_data(self,data):
        if not self.skip: self.text.append(data)


class HttpEvidenceCollector:
    def collect(self,paper,policy,action=''):
        rules=policy['rules']; v=paper['values']
        seeds=[f'https://pubmed.ncbi.nlm.nih.gov/{paper["pmid"]}/']
        if v.get('PMCID'): seeds.append(f'https://pmc.ncbi.nlm.nih.gov/articles/{v["PMCID"]}/')
        if v.get('DOI'): seeds.append('https://doi.org/'+urllib.parse.quote(v['DOI'],safe='/'))
        queue=[(u,'fulltext') for u in seeds]; seen=set(); records=[]
        opener=urllib.request.build_opener(PublicRedirect())
        while queue and len(seen)<rules['max_urls']:
            url,kind=queue.pop(0)
            if url in seen: continue
            seen.add(url)
            item=dict(evidence_id=uid(),url=url,final_url=url,kind=kind,timestamp=now(),
                status='fetch_error',http_status=None,text='',payload_sha256=None,bytes_observed=0,
                complete_body=False,level='unverified',identity_match=False,sections=[],format='',columns=[],
                legal_access='public_request',downloaded_full_dataset=False)
            try:
                public_url(url)
                with opener.open(urllib.request.Request(url,headers={'User-Agent':'K-Melloddy/0.1 research-review'}),timeout=rules['timeout_seconds']) as response:
                    data=response.read(rules['max_response_bytes']+1)
                    content_type=response.headers.get_content_type()
                    item.update(http_status=response.status,final_url=response.url)
                item.update(status='accessible',bytes_observed=len(data),complete_body=len(data)<=rules['max_response_bytes'],
                    payload_sha256=digest(data),format=content_type,level='response_sample',body_sample_b64=base64.b64encode(data).decode('ascii'))
                if content_type in {'text/html','application/xhtml+xml','text/plain','text/csv','application/json','application/xml','text/xml'}:
                    decoded=data.decode('utf-8',errors='replace')
                    page=Page(); page.feed(decoded)
                    item['text']=' '.join(page.text) if 'html' in content_type else decoded
                    if 'html' in content_type:
                        for link in page.links:
                            absolute=urllib.parse.urljoin(item['final_url'],link)
                            low=absolute.lower()
                            if any(token in low for token in ['supp','data','zenodo','figshare','github','dryad','osf.io']):
                                k='file' if low.endswith(('.csv','.tsv','.json','.xlsx','.zip','.txt')) else 'repository' if any(t in low for t in ['zenodo','figshare','github','dryad','osf.io']) else 'supplementary'
                                queue.append((absolute,k))
                    normalized=' '.join(item['text'].lower().split())
                    title=' '.join(v['Title'].lower().split())
                    item['identity_match']=bool(title and title in normalized) or bool(v.get('DOI') and v['DOI'].lower() in normalized)
                    item['sections']=[s for s in ['Methods','Results','Data Availability'] if s.lower() in normalized]
                    if content_type=='text/csv' and item['text']:
                        import csv,io
                        item['columns']=next(csv.reader(io.StringIO(item['text'])),[])
                        item['kind']='file'; item['level']='sample_structure'
                else:
                    item['text']=''
            except urllib.error.HTTPError as e:
                item.update(http_status=e.code,status='access_restricted' if e.code in {401,403,451} else 'fetch_error')
            except (ValueError,OSError,urllib.error.URLError):
                item['status']='fetch_error'
            records.append(item)
        # PubMed abstract pages do not constitute a full-text review.
        fulltexts=[e for e in records if e['kind']=='fulltext' and e['identity_match'] and e['status']=='accessible'
                   and 'pubmed.ncbi.nlm.nih.gov' not in e['final_url'] and {'Methods','Results'}<=set(e['sections'])]
        return dict(records=records,fulltext_reviewed=bool(fulltexts),
            sections_checked=sorted({s for e in fulltexts for s in e['sections']}),
            supplementary_checked=False,repository_checked=False,survey_complete=False,
            action=action,collector='bounded-http-v1',unresolved=['Supplementary/repository investigation completeness requires an explicitly configured collector/reviewer'])


class FixtureEvidenceCollector:
    def __init__(self,scenarios): self.scenarios=scenarios; self.calls=[]
    def collect(self,paper,policy,action=''):
        self.calls.append((paper['paper_id'],action))
        scenario=self.scenarios[paper['pmid']]
        return copy.deepcopy(scenario.get('revalidation_evidence',scenario['evidence']) if action else scenario['evidence'])


def validate_evidence(bundle):
    required={'records','fulltext_reviewed','sections_checked','supplementary_checked','repository_checked','survey_complete','collector'}
    if not required<=bundle.keys(): raise ValueError('Collector returned incomplete evidence contract')
    if any(type(bundle[k]) is not bool for k in ['fulltext_reviewed','supplementary_checked','repository_checked','survey_complete']):
        raise ValueError('Collector review flags must be booleans')
    ids=set()
    for e in bundle['records']:
        keys={'evidence_id','url','final_url','kind','timestamp','status','text','level','identity_match','sections','format','columns','payload_sha256','bytes_observed','http_status'}
        if not keys<=e.keys() or e['evidence_id'] in ids: raise ValueError('Invalid/duplicate evidence')
        if e.get('transport')=='web_tool':
            from .web_capture import validate_web_capture
            validate_web_capture(e)
        elif e['status']=='accessible' and (not isinstance(e['http_status'],int) or not 200<=e['http_status']<300 or not e['payload_sha256'] or e['bytes_observed']<=0):
            raise ValueError('Accessible evidence lacks actual response metadata')
        if e.get('body_sample_b64'):
            data=base64.b64decode(e['body_sample_b64'],validate=True)
            if digest(data)!=e['payload_sha256'] or len(data)!=e['bytes_observed']:
                raise ValueError('Evidence body hash/size mismatch')
        for k in ['url','final_url']:
            u=urllib.parse.urlsplit(e[k])
            if u.scheme not in {'http','https'} or not u.hostname or u.username or u.password:
                raise ValueError('Evidence URL is invalid')
        ids.add(e['evidence_id'])
    if bundle['fulltext_reviewed'] and not any(e['kind']=='fulltext' and e['identity_match'] and e['status']=='accessible' for e in bundle['records']):
        raise ValueError('Full text identity was not verified')
    return bundle
