"""Ordered, bounded legal access investigation with per-request retry evidence."""
import base64,csv,io,json,re,time,urllib.parse,urllib.request,urllib.error
import xml.etree.ElementTree as ET
import http.client
from ..core.storage import digest,now,uid
from .evidence_collector import Page,PublicRedirect,public_url

STEPS=['official_metadata','legal_fulltext','publisher_fulltext','Methods','Data Availability',
       'Supplementary','Repository','data_file_or_api','toxicity_features','decision']


def material_kind(url):
    parsed=urllib.parse.urlsplit(url);path=parsed.path.lower();host=(parsed.hostname or '').lower()
    if host.endswith('google.com') or 'scholar_lookup' in path:return None
    if any(x in path for x in ['supplement','mediaobjects']):return 'supplementary'
    if any(x in (host+path) for x in ['geo/query/acc.cgi','zenodo.org/records/','figshare.com/articles/','datadryad.org','osf.io/']):return 'repository'
    return None


class AccessInvestigator:
    def __init__(self,opener=None,retries=1,timeout=12,max_bytes=1500000):
        self.opener=opener or urllib.request.build_opener(PublicRedirect())
        self.retries=retries;self.timeout=timeout;self.max_bytes=max_bytes
    def request(self,url,kind,paper,route):
        records=[]
        for attempt in range(self.retries+1):
            row=dict(evidence_id=uid(),url=url,final_url=url,kind=kind,route=route,attempt=attempt+1,
                timestamp=now(),status='fetch_error',http_status=None,text='',payload_sha256=None,bytes_observed=0,
                level='unverified',identity_match=False,sections=[],format='',columns=[],failure_reason='',
                complete_body=False,legal_access='public_request',downloaded_full_dataset=False)
            try:
                public_url(url)
                headers={'User-Agent':'K-Melloddy research metadata verification'}
                referer=paper.get('_observed_referer')
                if referer:
                    if urllib.parse.urlsplit(referer).netloc!=urllib.parse.urlsplit(url).netloc:
                        raise ValueError('Cross-origin download referer')
                    headers['Referer']=referer
                    row['request_referer']=referer
                with self.opener.open(urllib.request.Request(url,headers=headers),timeout=self.timeout) as response:
                    # Socket timeouts restart on each packet. Bound slow streaming too.
                    deadline=time.monotonic()+self.timeout
                    chunks=[];remaining=self.max_bytes+1
                    read=getattr(response,'read1',response.read)
                    while remaining:
                        if time.monotonic()>deadline:raise TimeoutError('response body deadline exceeded')
                        chunk=read(min(65536,remaining))
                        if not chunk:break
                        chunks.append(chunk);remaining-=len(chunk)
                    data=b''.join(chunks);ctype=response.headers.get_content_type()
                    row.update(http_status=response.status,final_url=response.url,format=ctype)
                row.update(payload_sha256=digest(data),bytes_observed=len(data),body_sample_b64=base64.b64encode(data).decode(),complete_body=len(data)<=self.max_bytes)
                decoded=data.decode('utf-8',errors='replace');page=Page()
                if 'html' in ctype:page.feed(decoded);text=' '.join(page.text)
                else:text=decoded if any(t in ctype for t in ['text','json','xml']) else ''
                if ctype=='application/pdf' and row['complete_body']:
                    try:
                        from pypdf import PdfReader
                        reader=PdfReader(io.BytesIO(data))
                        text='\n'.join(p.extract_text() or '' for p in reader.pages)
                        row['pdf_page_count']=len(reader.pages)
                        row['pdf_text_extracted']=len(text.strip())>300
                        if not row['pdf_text_extracted']:row['extraction_limitation']='scan_or_unextractable_pdf_requires_visual_review'
                    except Exception as exc:
                        row['extraction_limitation']='PDF extraction: '+type(exc).__name__
                row['text']=text;row['observed_links']=[urllib.parse.urljoin(row['final_url'],u) for u in page.links]
                if 'xml' in ctype:
                    try:
                        tree=ET.fromstring(decoded)
                        row['observed_links'] += [u for n in tree.iter() for k,u in n.attrib.items() if k.endswith('href') and u.startswith(('https://','http://'))]
                    except ET.ParseError:pass
                normalized=' '.join(text.lower().split());title=' '.join(paper['values']['Title'].lower().split()).rstrip('.')
                row['identity_match']=bool(title and title in normalized)
                row['identity_checks']={'title':row['identity_match'],'pmid':paper.get('pmid','') in text if paper.get('pmid') else None,
                    'doi':paper['values'].get('DOI','').lower() in normalized if paper['values'].get('DOI') else None,
                    'authors':all(a.casefold() in normalized for a in paper.get('_verified_authors',[])) if paper.get('_verified_authors') else None}
                if 'xml' in ctype:
                    try:
                        tree=ET.fromstring(decoded)
                        own=tree.find('./front/article-meta')
                        if own is not None:
                            ids={n.get('pub-id-type'):n.text for n in own.findall('article-id')}
                            actual_title=' '.join(''.join(own.find('title-group/article-title').itertext()).lower().split()).rstrip('.')
                            row['identity_match']=ids.get('pmid')==paper.get('pmid') and actual_title==title
                            doi=paper['values'].get('DOI')
                            if doi:row['identity_match']=row['identity_match'] and ids.get('doi','').casefold()==doi.casefold()
                            row['identity_checks'].update(pmid=ids.get('pmid')==paper.get('pmid'),title=actual_title==title,doi=ids.get('doi','').casefold()==doi.casefold() if doi else None)
                    except (ET.ParseError,AttributeError):row['identity_match']=False
                # A normal article may load a reCAPTCHA script for an unrelated form.
                # Only visible challenge messages (or the dedicated search challenge form) block access.
                challenge=next((t for t in ['recaptcha','client challenge','checking your browser','verify you are human','javascript is disabled','unfortunately, bots','preparing to download ...'] if t in normalized),'')
                if not challenge and 'id="challenge-form"' in decoded.lower():challenge='challenge-form'
                paywall=next((t for t in ['preview of subscription content','log in via an institution'] if t in normalized),'')
                redirect=normalized.strip() in {'redirecting','redirecting...',''}
                if challenge or paywall:row.update(status='access_restricted',failure_reason=challenge or paywall)
                elif redirect:row.update(status='fetch_error',failure_reason='redirect_or_empty_body_not_article')
                elif kind=='fulltext' and not row['identity_match']:
                    row.update(status='fetch_error',failure_reason='article_identity_not_verified')
                elif not row['complete_body']:row.update(status='fetch_error',failure_reason='response_exceeds_limit')
                else:row.update(status='accessible',level='response_sample')
                if kind in {'file','api'} and row['status']=='accessible':
                    row['file_name']=urllib.parse.unquote(urllib.parse.urlsplit(row['final_url']).path.rsplit('/',1)[-1])
                    if 'csv' in ctype or 'tab-separated' in ctype:
                        try:
                            sample=list(csv.reader(io.StringIO(text),delimiter='\t' if 'tab-separated' in ctype else ','))
                            if len(sample)>1 and len(sample[0])>1 and all(len(x)==len(sample[0]) for x in sample[1:] if x):
                                row.update(columns=sample[0],level='sample_structure',sample_row_count=len(sample)-1)
                            else:row['structure_failure']='missing_or_inconsistent_columns'
                        except csv.Error:row['structure_failure']='csv_parse_failed'
            except urllib.error.HTTPError as exc:
                row.update(http_status=exc.code,status='access_restricted' if exc.code in {401,403,451} else 'fetch_error',failure_reason='HTTP_'+str(exc.code))
            except (ValueError,OSError,urllib.error.URLError,http.client.HTTPException) as exc:
                cause=getattr(exc,'reason',exc)
                row['failure_reason']='Timeout' if isinstance(cause,TimeoutError) else type(exc).__name__
            if row['final_url']!=url:row['redirected']=True
            records.append(row)
            if row['status']=='accessible':break
            if attempt<self.retries:time.sleep(0.5*(attempt+1))
        return records
    def collect(self,paper,policy,action=''):
        rules=policy.get('rules',{})
        self.timeout=rules.get('timeout_seconds',self.timeout);self.max_bytes=rules.get('max_response_bytes',self.max_bytes)
        v=paper['values'];records=[];coverage=[];workflow=[{'step':'official_metadata','state':'verified'}]
        # Only verified identifiers supplied by verified_workflow can reach this method.
        if not paper.get('_official_verified'):raise ValueError('Official metadata gate missing')
        pmc=v.get('PMCID','')
        if pmc:
            records+=self.request('https://pmc.ncbi.nlm.nih.gov/articles/'+pmc+'/','fulltext',paper,'PMC')
            records+=self.request('https://www.ebi.ac.uk/europepmc/webservices/rest/'+pmc+'/fullTextXML','fulltext',paper,'PMC_XML_supplement_discovery')
        coverage.append({'target':'PMC','state':'attempted' if pmc else 'no_official_PMCID'})
        workflow.append({'step':'legal_fulltext','state':'attempted' if pmc else 'no_official_PMCID'})
        if v.get('DOI'):
            records+=self.request('https://doi.org/'+urllib.parse.quote(v['DOI'],safe='/'),'fulltext',paper,'publisher')
        workflow.append({'step':'publisher_fulltext','state':'attempted' if v.get('DOI') else 'no_official_DOI'})
        # Exact PMID and exact title discovery; do not guess article/download URLs.
        queries=[f'EXT_ID:{paper["pmid"]} AND SRC:MED','TITLE:"'+v['Title'].replace('"','')+'"']
        discovered=[]
        for query in queries:
            url='https://www.ebi.ac.uk/europepmc/webservices/rest/search?format=json&resultType=core&query='+urllib.parse.quote(query)
            found=self.request(url,'metadata',paper,'alternative_search');records+=found
            try:
                data=json.loads(found[-1]['text'])
                for result in data.get('resultList',{}).get('result',[]):
                    if str(result.get('id'))!=paper['pmid'] or result.get('source')!='MED':continue
                    if str(result.get('title','')).strip().rstrip('.').casefold()!=v['Title'].strip().rstrip('.').casefold():continue
                    for link in result.get('fullTextUrlList',{}).get('fullTextUrl',[]):
                        if link.get('availabilityCode') in {'OA','F'} and link.get('url'):discovered.append(link['url'])
            except (ValueError,KeyError,TypeError):pass
        attempted={e['url'] for e in records}
        for url in list(dict.fromkeys(discovered))[:3]:
            if url not in attempted:records+=self.request(url,'fulltext',paper,'alternative_fulltext')
        workflow.append({'step':'alternative_exact_PMID_title','state':'attempted','queries':queries})
        coverage.append({'target':'official_fulltext','state':'attempted','queries':queries})
        # Independent repository discovery works even when publisher HTML is blocked.
        # Search responses remain metadata, not evidence that a dataset was verified.
        if isinstance(action,dict):
            searches=[('BioStudies','https://www.ebi.ac.uk/biostudies/api/v1/search?query='+urllib.parse.quote(paper['pmid'])),
                      ('BioStudies_title','https://www.ebi.ac.uk/biostudies/api/v1/search?query='+urllib.parse.quote(v['Title'])),
                      ('Zenodo','https://zenodo.org/api/records?q='+urllib.parse.quote('"'+(v.get('DOI') or v['Title'])+'"')+'&size=5')]
            for route,url in searches:
                found=self.request(url,'metadata',paper,route+'_repository_search');records+=found
                matched=[]
                try:
                    data=json.loads(found[-1]['text'])
                    hits=data.get('hits',[])
                    if isinstance(hits,dict):hits=hits.get('hits',[])
                    for hit in hits[:5]:
                        meta=hit.get('metadata',hit)
                        title=str(meta.get('title','')).strip().rstrip('.').casefold()
                        related=meta.get('related_identifiers',[])
                        doi_match=bool(v.get('DOI')) and any(x.get('identifier','').lower().removeprefix('https://doi.org/')==v['DOI'].lower() for x in related)
                        if title!=v['Title'].strip().rstrip('.').casefold() and not doi_match:continue
                        links=hit.get('links',{})
                        link=links.get('html') if isinstance(links,dict) else None
                        if route.startswith('BioStudies') and hit.get('accession'):link='https://www.ebi.ac.uk/biostudies/studies/'+urllib.parse.quote(hit['accession'],safe='')
                        if link:matched.append(link)
                    for link in matched:
                        if link not in attempted:records+=self.request(link,'repository',paper,'independent_repository_match');attempted.add(link)
                except (ValueError,KeyError,TypeError):pass
                coverage.append({'target':route,'state':'searched' if found[-1]['status']=='accessible' else 'search_failed','url':url,'matched_urls':matched})
            # P03/P04 focus on previously observed locations; never fabricate file URLs.
            for previous in action.get('known_records',[]):
                if previous.get('kind')=='supplementary' and material_kind(previous.get('url',''))!='supplementary':continue
                if previous.get('kind') in {'supplementary','repository','landing','file','api'} and previous.get('url') not in attempted:
                    records+=self.request(previous['url'],previous['kind'],paper,'prior_observed_location');attempted.add(previous['url'])
        # Article-specific links only; never follow NCBI site footer GitHub links.
        for source in list(records):
            if source['kind']!='fulltext' or not source['identity_match']:continue
            for url in source.get('observed_links',[]):
                if url in attempted:continue
                kind=material_kind(url)
                if not kind:continue
                if len(attempted)>=rules.get('max_urls',18):break
                attempted.add(url)
                records+=self.request(url,kind,paper,kind)
        coverage.append({'target':'publisher_supplementary','state':'attempted' if any(e['kind']=='supplementary' for e in records) else 'no_observed_link',
            'unresolved_reason':'No article-specific supplementary URL was observed; absence of supplementary material is not established.' if not any(e['kind']=='supplementary' for e in records) else ''})
        for step in STEPS[3:-1]:workflow.append({'step':step,'state':'awaiting_review'})
        return dict(records=records,fulltext_reviewed=False,sections_checked=[],supplementary_checked=False,
            repository_checked=False,survey_complete=False,collector='verified-sequential-access-v2',workflow=workflow,
            alternative_search_completed=True,action=action,search_coverage=coverage,
            focused_pending_code=action.get('pending_code') if isinstance(action,dict) else None)


def unlocated_fulltext(bundle):
    """Documented failure to discover any article route, not proof of data absence."""
    identity=bundle.get('official_identity',{})
    if not identity.get('pmid') or identity.get('doi') or identity.get('pmcid') or not bundle.get('independent_discovery_completed'):return False
    records=bundle['records']
    if any(e['kind']=='fulltext' and urllib.parse.urlsplit(e['url']).hostname not in {'pubmed.ncbi.nlm.nih.gov','account.ncbi.nlm.nih.gov'} for e in records):return False
    searches=set()
    for e in records:
        if e.get('route')!='alternative_search' or e['status']!='accessible':continue
        try:
            hits=json.loads(e['text']).get('resultList',{}).get('result',[])
            match=next((h for h in hits if str(h.get('id'))==identity['pmid'] and h.get('source')=='MED'),None)
            if match is not None and not (match.get('fullTextUrlList') or {}).get('fullTextUrl'):searches.add(e['url'])
        except (ValueError,TypeError):pass
    return len(searches)>=2 and any(e.get('route')=='PubMed_linkouts' for e in records) and any(e.get('route')=='title_author_scholarly_search' for e in records)


def reviewed_abstract_only(bundle):
    """A reviewer verified that observed full-text/PDF routes only return abstracts."""
    if not bundle.get('session_review') or not bundle.get('alternative_search_completed'):return False
    lookup={e['evidence_id']:e for e in bundle['records']}
    seen=set()
    for item in bundle.get('content_access_review',[]):
        ref=item.get('reference',{});e=lookup.get(ref.get('evidence_id'),{})
        if (item.get('classification')=='abstract_only' and e.get('kind')=='fulltext'
            and e.get('status')=='accessible' and e.get('identity_match')
            and ref.get('quote') and ref['quote'] in e.get('text','')):seen.add(e['url'])
    return len(seen)>=2


def access_pending(bundle):
    """No single 403 or isolated network error is enough to authorize P02."""
    if not bundle.get('alternative_search_completed'):return False
    if unlocated_fulltext(bundle):return True
    if reviewed_abstract_only(bundle):return True
    article=[e for e in bundle['records'] if e['kind']=='fulltext' and urllib.parse.urlsplit(e['url']).hostname not in {'account.ncbi.nlm.nih.gov','pubmed.ncbi.nlm.nih.gov'}]
    from .revalidation_access import body_requires_review
    body_available=any(body_requires_review(e) for e in article)
    if body_available:
        # A DOI redirect can be empty while the observed publisher URL is 403.
        # Accept an explicit, cited supplementary-access review only when its
        # named URL has an actual retried restriction in captured evidence.
        constraints=bundle.get('session_review',{}).get('access_constraints',{})
        blocked=set(constraints.get('blocked_material_urls',[]))
        if (bundle.get('fulltext_reviewed') and not bundle.get('supplementary_checked')
                and blocked and constraints.get('evidence_refs')):
            from .dataset_verifier import citations
            try:citations(constraints['evidence_refs'],bundle)
            except ValueError:return False
            if any(e['url'] in blocked and e['status']=='access_restricted'
                   and e.get('attempt',0)>=2 for e in bundle['records']):return True
        # A reviewed alternative body does not establish access to separate publisher supplements.
        return bool(bundle.get('fulltext_reviewed') and not bundle.get('supplementary_checked') and
            any(e['route']=='publisher' and e['status']=='access_restricted' and e.get('attempt',0)>=2 for e in article) and
            any(x.get('target')=='publisher_supplementary' and x.get('state')=='no_observed_link' for x in bundle.get('search_coverage',[])))
    failed=[e for e in article if e['status']!='accessible']
    return bool(failed) and len({e['url'] for e in bundle['records']})>=2 and any(e.get('attempt',0)>=2 for e in failed)
