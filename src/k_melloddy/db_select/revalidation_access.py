"""Independent, bounded discovery; observations never certify scientific eligibility."""
import base64
import json
import re
from html.parser import HTMLParser
from urllib.parse import quote, urlsplit, parse_qs
from .access_workflow import AccessInvestigator, material_kind


class Linkouts(HTMLParser):
    def __init__(self):
        super().__init__(); self.urls=[]
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag=='a' and attrs.get('data-ga-category')=='full_text' and 'link-item' in attrs.get('class','').split() and attrs.get('href','').startswith('https://'):
            self.urls.append(attrs['href'])


def scholarly_match(hit,paper):
    norm=lambda s:re.sub(r'\W+','',s.casefold())
    official_doi=paper['values'].get('DOI','').casefold()
    found_doi=(hit.get('doi') or '').casefold().removeprefix('https://doi.org/').removeprefix('http://doi.org/')
    found_pmid=(hit.get('ids',{}).get('pmid') or '').rstrip('/').rsplit('/',1)[-1]
    if official_doi and found_doi and official_doi!=found_doi:return False
    if found_pmid and found_pmid!=paper['pmid']:return False
    return bool((official_doi and found_doi==official_doi) or found_pmid==paper['pmid'] or norm(hit.get('title') or '')==norm(paper['values']['Title']))


def reviewed_abstract_content(e):
    """Respect an explicit cited content review over a prose keyword heuristic."""
    review=e.get('reviewed_content',{})
    ref=review.get('reference',{})
    return bool(review.get('classification')=='abstract_only'
                and e.get('kind')=='fulltext' and e.get('status')=='accessible'
                and e.get('identity_match') and ref.get('evidence_id')==e.get('evidence_id')
                and isinstance(ref.get('quote'),str) and ref['quote']
                and ref['quote'] in e.get('text',''))


def readable_body(e):
    if e.get('kind')!='fulltext' or e.get('status')!='accessible' or not e.get('identity_match'):return False
    if reviewed_abstract_content(e):return False
    # Scholarly indexes may list an abstract page as an article location.
    if urlsplit(e.get('final_url',e.get('url',''))).hostname in {'pubmed.ncbi.nlm.nih.gov','openalex.org','api.openalex.org'}:return False
    text=e.get('text','')
    # Elsevier may return only coredata; the journal name itself contains
    # "Methods" and must not satisfy the prose-based body heuristic.
    if '<full-text-retrieval-response' in text:
        import xml.etree.ElementTree as ET
        try:
            tree=ET.fromstring(text)
            return any(n.tag.rsplit('}',1)[-1] in {'body','rawtext'} and len(''.join(n.itertext()).strip())>300 for n in tree.iter())
        except ET.ParseError:return False
    # JATS scan containers have <body> but no article prose.
    if '<body' in text:
        import xml.etree.ElementTree as ET
        try:
            body=ET.fromstring(text).find('body')
            return body is not None and (any(len(''.join(p.itertext()).strip())>300 for sec in body.findall('sec') if sec.get('sec-type')!='ref-list' for p in sec.findall('p')) or
                any(len(''.join(p.itertext()).strip())>300 for p in body.findall('preformat') if p.get('preformat-type')=='pmc-ocr-text'))
        except ET.ParseError:return False
    if e.get('pdf_text_extracted'):return True
    return bool(re.search(r'(materials and methods|methods)\s+.{300}',text,re.I|re.S)) and 'Full text \n PDF' not in text


def body_requires_review(e):
    if reviewed_abstract_content(e):return False
    if readable_body(e):return True
    if e.get('status')!='accessible' or not e.get('identity_match'):return False
    import xml.etree.ElementTree as ET
    try:
        tree=ET.fromstring(e.get('text',''));body=tree if tree.tag=='body' else tree.find('body')
        if body is None:return False
        return bool((body.text or '').strip()) or any(''.join(p.itertext()).strip() for sec in body.findall('sec') if sec.get('sec-type')!='ref-list' for p in sec.findall('p'))
    except ET.ParseError:return False


def verification_state(paper, bundle, record):
    evidence=(bundle or {}).get('records',[])
    names=list(dict.fromkeys(x['name'] for x in record.get('data_observations',[])))
    bodies=[e for e in evidence if readable_body(e) or (
        (bundle or {}).get('fulltext_reviewed') and e.get('kind')=='fulltext'
        and e.get('status')=='accessible' and e.get('identity_match')
        and e.get('transport')=='web_tool' and e.get('format')=='reviewer_excerpt')]
    registered=record.get('datasets',[]) if record.get('final',{}).get('status')=='confirmed' else []
    names=list(dict.fromkeys(names+[d['name'] for d in registered]))
    attempts=[dict(source=e.get('route',e['kind']),url=e['url'],action=('reviewed web-tool excerpt' if e.get('transport')=='web_tool' else 'reuse prior HTTP evidence' if e.get('reused_from_prior_round') else 'HTTP GET'),checked_at=e['timestamp'],
        result=e['status'],error=e.get('failure_reason',''),http_status=e['http_status'],
        evidence_excerpt_or_summary=(e.get('text','')[:600] if e['status']=='accessible' else e.get('failure_reason','')),
        evidence_id=e['evidence_id']) for e in evidence]
    visual=(bundle or {}).get('visual_review',{})
    attempts += [dict(source='PMC_scan_image',url=p['url'],action=p['action'],checked_at=p['checked_at'],result=p['status'],
        error=p.get('error',''),http_status=p.get('http_status'),evidence_excerpt_or_summary=visual['reviewer_note'],
        evidence_id=p['sha256']) for p in visual.get('pages',[])]
    state=dict(full_text_access=True if bodies or visual else 'unknown',
        full_text_evidence_url=[e['url'] for e in bodies]+[p['url'] for p in visual.get('pages',[])],full_text_reviewed=(bundle or {}).get('fulltext_reviewed',False),
        dataset_identified=True if names or registered else 'unknown',dataset_name=names,
        dataset_public=True if registered else 'unknown',dataset_accessible=True if registered else 'unknown',
        dataset_downloadable=True if registered else 'unknown',dataset_reusable='unknown',
        license_or_access_constraints='unknown',download_url=[d['direct_url'] for d in registered],download_format=[d['file_format'] for d in registered],
        data_url=[d['direct_url'] for d in registered],file_format=[d['file_format'] for d in registered],
        verification_evidence=[e['evidence_id'] for e in bodies],verification_attempts=attempts,
        unresolved_questions=(record.get('fulltext',{}).get('what_unresolved',[]) or [record.get('final',{}).get('reason','Review outstanding')]) if record.get('final',{}).get('status')=='pending' else [])
    # A failed request proves only a failed request, never data nonexistence.
    if (bundle or {}).get('captured_review'):
        state['captured_review_sha256']=bundle['captured_review']['submission_sha256']
        state['review_mode']='human_review_of_captured_evidence'
        constraints=bundle['captured_review'].get('access_constraints')
        if constraints:
            state['license_or_access_constraints']=constraints.get('summary') or constraints.get('reason') or 'unknown'
            state['verification_evidence'] += [x['evidence_id'] for x in constraints['evidence_refs']]
    elif (bundle or {}).get('session_review'):
        review=bundle['session_review'];state['review_mode']='session_evidence_review'
        state['session_review_sha256']=review['answer_sha256']
        if review.get('access_constraints'):
            constraints=review['access_constraints']
            state['license_or_access_constraints']=constraints.get('summary') or constraints.get('reason') or 'unknown'
    else:state['review_mode']='network_revalidation'
    return state


class RevalidationAccess(AccessInvestigator):
    """Extra discovery only for explicit targeted campaigns, leaving ordinary runs unchanged."""
    def __init__(self,*args,trace=None,**kwargs):
        super().__init__(*args,**kwargs);self.trace=trace
        self.parallel_searches=not args and kwargs.get('opener') is None
    def search_batch(self,specs,paper):
        """Independent read-only searches within ONE paper; deterministic merge order."""
        if not self.parallel_searches:return [self.request(u,'metadata',paper,'independent_data_search') for q,u in specs]
        from concurrent.futures import ThreadPoolExecutor
        def one(spec):
            client=RevalidationAccess(retries=self.retries,timeout=self.timeout,max_bytes=self.max_bytes,trace=self.trace)
            return client.request(spec[1],'metadata',paper,'independent_data_search')
        with ThreadPoolExecutor(max_workers=3) as pool:return list(pool.map(one,specs))
    def request(self,url,kind,paper,route):
        url=quote(url,safe=":/?&=%+#[]@!$'()*;,")
        if self.trace:self.trace(f'HTTP start {paper["paper_id"]} {route}: {url}')
        old=self.max_bytes
        try:
            if urlsplit(url).hostname in {'pubmed.ncbi.nlm.nih.gov','openalex.org','api.openalex.org'}:kind='metadata'
            if '.pdf' in urlsplit(url).path.lower():self.max_bytes=max(old,8*1024*1024)
            result=super().request(url,kind,paper,route)
            if self.trace:self.trace(f'HTTP end {paper["paper_id"]} {route}: '+','.join(e['status']+':'+str(e['http_status']) for e in result))
            return result
        finally:self.max_bytes=old
    def collect(self,paper,policy,action=''):
        bundle=super().collect(paper,policy,action)
        records=bundle['records']; seen={e['url'] for e in records}; coverage=bundle['search_coverage']
        def fetch(url,kind,route):
            if url in seen:return []
            seen.add(url); found=self.request(url,kind,paper,route);records.extend(found);return found
        pmid=paper['pmid'];title=paper['values']['Title']
        pubmed=fetch(f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/','metadata','PubMed_linkouts')
        for e in pubmed:
            if e['status']!='accessible' or not e.get('identity_match'):continue
            parser=Linkouts();parser.feed(base64.b64decode(e['body_sample_b64']).decode('utf-8',errors='replace'))
            for url in parser.urls[:4]:fetch(url,'fulltext','official_PubMed_linkout')
        for item in paper.get('_review_discovery',[])[:8]:
            fetch(item['url'],item['kind'],'reviewer_observed_search_result')
        # Scholarly index exposes actual institutional repository locations, not guessed URLs.
        url='https://api.openalex.org/works?search='+quote(title)+'&per-page=3'
        found=fetch(url,'metadata','title_author_scholarly_search')
        for e in found:
            if e['status']!='accessible':continue
            try:
                for hit in json.loads(e['text']).get('results',[]):
                    if not scholarly_match(hit,paper):
                        coverage.append(dict(target='scholarly_location',state='rejected_identity_mismatch',title=hit.get('title'),doi=hit.get('doi'),ids=hit.get('ids',{})))
                        continue
                    for loc in (hit.get('locations') or [])[:3]:
                        for key in ['landing_page_url','pdf_url']:
                            if loc.get(key):fetch(loc[key],'fulltext','scholarly_observed_location')
            except (ValueError,TypeError):pass
        queries=[f'PMID "{pmid}" data',f'"{title}" supplementary']
        for name in paper.get('_known_data_names',[])[:2]:
            queries += [f'"{name}" {term}' for term in ['dataset','download','access']]
        specs=list(dict.fromkeys((q,'https://html.duckduckgo.com/html/?q='+quote(q)) for q in queries))
        specs=[(q,u) for q,u in specs if u not in seen]
        batches=self.search_batch(specs,paper)
        for (query,url),found in zip(specs,batches):
            seen.add(url);records.extend(found)
            coverage.append(dict(target='independent_data_search',query=query,url=url,
                state='searched' if found and found[-1]['status']=='accessible' else 'search_failed'))
            links=[]
            for e in found:
                if e['status']!='accessible':continue
                for link in e.get('observed_links',[]):
                    value=parse_qs(urlsplit(link).query).get('uddg',[link])[0]
                    if urlsplit(value).hostname and 'duckduckgo.com' not in urlsplit(value).hostname:links.append(value)
            for link in list(dict.fromkeys(links))[:2]:fetch(link,material_kind(link) or 'landing','independent_observed_result')
        # Follow article-specific PDFs, including old PMC scan articles. Never label these datasets.
        for e in list(records):
            if e['kind']!='fulltext' or not e.get('identity_match'):continue
            for url in list(dict.fromkeys(e.get('observed_links',[]))):
                if '.pdf' not in urlsplit(url).path.lower():continue
                if urlsplit(url).hostname!=urlsplit(e['final_url']).hostname:continue
                fetch(url,'fulltext','observed_article_pdf')
                break
        bundle['collector']='targeted-independent-revalidation-v1'
        bundle['independent_discovery_completed']=True
        return bundle
