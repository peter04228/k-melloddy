"""PMID-scoped official EFetch verification; never edits Collect records."""
import copy
import http.client
import re
import xml.etree.ElementTree as ET
from ..core.storage import digest,now
from ..db_collect.client import NCBIClient


def node_text(node):
    return ''.join(node.itertext()).strip() if node is not None else ''


def input_year(paper):
    value=paper['values'].get('Publication Date',[])
    def year(node):
        if isinstance(node,dict):
            if node.get('tag') in {'Year','MedlineDate'}:
                match=re.search(r'\b\d{4}\b',node.get('text') or '')
                if match:return match[0]
            for child in node.get('children',[]):
                found=year(child)
                if found:return found
        return ''
    if isinstance(value,list):
        for n in value:
            found=year(n)
            if found:return found
    match=re.search(r'\b\d{4}\b',str(value))
    return match[0] if match else ''


def parse_official(raw,pmid):
    if b'<!ENTITY' in raw.upper():raise ValueError('Unsafe XML')
    root=ET.fromstring(raw)
    articles=root.findall('PubmedArticle')
    if len(articles)!=1 or articles[0].findtext('MedlineCitation/PMID')!=pmid:
        raise ValueError('Official PMID response mismatch')
    a=articles[0];article=a.find('MedlineCitation/Article')
    ids={n.get('IdType'):node_text(n) for n in a.findall('PubmedData/ArticleIdList/ArticleId')}
    for n in article.findall('ELocationID'):ids.setdefault(n.get('EIdType'),node_text(n))
    title=node_text(article.find('ArticleTitle'))
    if not title:raise ValueError('Official title missing')
    date=article.find('Journal/JournalIssue/PubDate')
    year=node_text(date.find('Year')) if date is not None else ''
    if not year:
        match=re.search(r'\b\d{4}\b',node_text(date));year=match[0] if match else ''
    if not year:year=node_text(article.find('ArticleDate/Year'))
    return {'PMID':pmid,'DOI':ids.get('doi',''),'PMCID':ids.get('pmc',''),
            'Title':title,'Publication year':year}


class OfficialMetadataVerifier:
    def __init__(self,client=None):self.client=client
    def verify(self,paper):
        attempts=[];pmid=paper['pmid']
        url='https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&retmode=xml&id='+pmid
        def retried(n,status,delay):
            attempts.append({'attempt':n,'url':url,'http_status':status,'state':'retry',
                'failure_reason':'official_metadata_transport_failure','retry_delay_seconds':delay,'timestamp':now()})
        client=self.client or NCBIClient(retries=2,on_retry=retried)
        try:
            raw=client.fetch([pmid]);official=parse_official(raw,pmid)
            attempts.append({'attempt':len(attempts)+1,'url':url,'state':'validated','timestamp':now(),'sha256':digest(raw)})
            source={k:paper['values'].get(k,'') for k in ['PMID','DOI','PMCID','Title']}
            source['Publication year']=input_year(paper)
            differences={k:{'input':source[k],'official':v} for k,v in official.items() if source[k]!=v}
            authors=[node_text(n) for n in ET.fromstring(raw).findall('./PubmedArticle/MedlineCitation/Article/AuthorList/Author/LastName')]
            return {'status':'verified','source':'NCBI EFetch','pmid':pmid,'internal_number':paper['paper_id'],'checked_at':now(),'official_authors':authors,
                'verified_metadata':official,'input_metadata':source,'mismatches':differences,
                'attempts':attempts,'response_sha256':digest(raw),'response_xml':raw.decode('utf-8')}
        except (ValueError,RuntimeError,OSError,ET.ParseError,http.client.HTTPException) as exc:
            attempts.append({'attempt':len(attempts)+1,'url':url,'state':'failed','timestamp':now(),'failure_reason':type(exc).__name__})
            return {'status':'unverified','pmid':pmid,'verified_metadata':{},'mismatches':{},'attempts':attempts,
                'failure_reason':'공식 PMID 서지정보를 검증하지 못해 입력 DOI/PMCID 사용을 차단했습니다.'}


def verified_paper(paper,verification):
    if verification['status']!='verified':raise ValueError('Unverified metadata cannot seed Full Text')
    if verification['verified_metadata']['PMID']!=paper['pmid']:raise ValueError('Verified PMID mismatch')
    result=copy.deepcopy(paper);result['values'].update(verification['verified_metadata'])
    return result
