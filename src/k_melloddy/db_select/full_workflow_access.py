"""Bounded article discovery, context extraction and structured-material inspection."""
import base64
import copy
import csv
import io
import json
import re
import zipfile
import unicodedata
import urllib.request
import urllib.error
import http.client
from html.parser import HTMLParser
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit,quote

from ..core.storage import digest, dump, now
from .revalidation_access import RevalidationAccess
from .access_workflow import material_kind
from .evidence_collector import public_url


def recover_pdf_bytes(paper, record):
    """Inspect complete PDF bytes even when an institutional server mislabels MIME."""
    if (record.get('kind')!='fulltext' or not record.get('complete_body')
            or record.get('http_status')!=200 or record.get('pdf_text_extracted')):return record
    data=base64.b64decode(record.get('body_sample_b64',''))
    if not data.startswith(b'%PDF-') or len(data)>8*1024*1024:return record
    try:
        from pypdf import PdfReader
        reader=PdfReader(io.BytesIO(data))
        text='\n'.join(page.extract_text() or '' for page in reader.pages)
    except Exception:return record
    original={'status':record.get('status'),'failure_reason':record.get('failure_reason'),'format':record.get('format')}
    record.update(text=text,pdf_page_count=len(reader.pages),pdf_text_extracted=len(text.strip())>300,
                  detected_format='application/pdf',pdf_detection='complete_body_magic_bytes')
    # Reuse strict title AND verified DOI check; downloading a PDF is not a full review.
    if record.get('status')!='access_restricted':
        record.update(status='fetch_error',failure_reason='article_identity_not_verified')
        recover_typographic_identity(paper,record)
        record['prior_classification']=original
    return record


def recover_typographic_identity(paper, record):
    """Reclassify complete title/DOI-matched text, preserving original transport evidence."""
    if (record.get('kind')!='fulltext' or record.get('failure_reason')!='article_identity_not_verified'
            or not record.get('complete_body') or record.get('http_status')!=200):return record
    def normalized(text):
        text=unicodedata.normalize('NFKC',text).casefold()
        return ' '.join(''.join('-' if unicodedata.category(c)=='Pd' else c for c in text).split()).rstrip('.')
    title=normalized(paper['values'].get('Title',''));body=normalized(record.get('text',''))
    # PubMed encloses translated titles in square brackets; PMC prints the same
    # translated words without that bibliographic wrapper. Do not remove inner
    # brackets or alter the title words, and still require the verified DOI.
    if title.startswith('[') and title.endswith(']'):
        if record.get('identity_checks',{}).get('pmid') is not True:return record
        title=title[1:-1].strip()
    doi=paper['values'].get('DOI','').casefold()
    if title and title in body and doi and doi in re.sub(r'\s+','',body):
        record.update(status='accessible',failure_reason='',identity_match=True,level='response_sample',
                      identity_recovery='typographic_title_and_verified_DOI',
                      prior_classification={'status':'fetch_error','failure_reason':'article_identity_not_verified'})
        record.setdefault('identity_checks',{}).update(title=True,doi=True)
    return record


class ScanImages(HTMLParser):
    def __init__(self):super().__init__();self.pages=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='img' and 'graphic' in a.get('class','').split() and a.get('alt','').isdigit():
            url=a.get('src','')
            if url.startswith('https://cdn.ncbi.nlm.nih.gov/pmc/blobs/'):
                self.pages.append((url,a['alt']))


def extract_context(bundle):
    result=[]
    pattern=r'data availability|data access|supplement(?:ary|al)?|supporting information|materials and methods|methods|results|repository|database|dataset|accession|licen[cs]e'
    for e in bundle['records']:
        if e['status']!='accessible':continue
        text=e.get('text','')
        for m in list(re.finditer(pattern,text,re.I))[:30]:
            result.append(dict(evidence_id=e['evidence_id'],url=e['url'],section_hint=m.group(),
                               quote=text[max(0,m.start()-160):min(len(text),m.end()+900)],
                               identity_match=e.get('identity_match',False)))
    return result


def recover_json_metadata(paper,record):
    """Interpret complete captured JSON despite a generic binary MIME type."""
    if (record.get('kind')!='metadata' or record.get('status')!='fetch_error'
            or record.get('failure_reason')!='redirect_or_empty_body_not_article'
            or record.get('http_status')!=200 or not record.get('complete_body')
            or not urlsplit(record.get('final_url',record.get('url',''))).path.lower().endswith('.json')):return
    try:
        raw=base64.b64decode(record.get('body_sample_b64',''),validate=True)
        if len(raw)!=record.get('bytes_observed') or digest(raw)!=record.get('payload_sha256'):return
        text=raw.decode('utf-8-sig');data=json.loads(text)
        if not isinstance(data,(dict,list)):return
    except (ValueError,UnicodeError):return
    record['prior_classification']={k:record.get(k) for k in ['status','failure_reason']}
    record.update(status='accessible',failure_reason='',text=text,detected_format='application/json',
                  level='response_sample',interpretation_note='Complete captured JSON parsed; HTTP MIME and original bytes retained')
    if isinstance(data,dict):
        norm=lambda s:re.sub(r'\W+','',str(s).casefold())
        values=paper['values']
        checks=dict(pmid=str(data.get('pmid',''))==paper.get('pmid'),
            pmcid=bool(values.get('PMCID')) and data.get('pmcid')==values['PMCID'],
            doi=bool(values.get('DOI')) and str(data.get('doi','')).casefold()==values['DOI'].casefold(),
            title=bool(values.get('Title')) and norm(data.get('title',''))==norm(values['Title']))
        record['identity_checks']=checks;record['identity_match']=all(checks.values())


def inspect_material(e):
    inspection_key=digest(dump([e.get('body_sample_b64',''),e.get('final_url',''),e.get('format','')]+
                              (['xls-parser-v1'] if urlsplit(e.get('final_url','')).path.lower().endswith('.xls') else [])+
                              (['pdf-text-v1'] if urlsplit(e.get('final_url','')).path.lower().endswith('.pdf') else [])).encode())
    if e.get('material_inspection_key')==inspection_key:return e
    # A directly captured supplementary document is a file, not a landing page.
    material_path=urlsplit(e.get('final_url','')).path.lower()
    if (e.get('kind')=='supplementary' and e.get('status')=='accessible' and e.get('complete_body')
            and ((material_path.endswith('.docx') and base64.b64decode(e.get('body_sample_b64','')).startswith(b'PK'))
                 or (material_path.endswith('.pdf') and base64.b64decode(e.get('body_sample_b64','')).startswith(b'%PDF-')))):
        e['original_kind']='supplementary'
        e['kind']='file'
    binary_candidate=e['status']=='fetch_error' and e.get('failure_reason')=='redirect_or_empty_body_not_article' and e.get('http_status')==200
    if (e['status']!='accessible' and not binary_candidate) or e['kind'] not in {'file','api'} or not e.get('complete_body'):return e
    data=base64.b64decode(e.get('body_sample_b64',''));fmt=e.get('format','');suffix=urlsplit(e['final_url']).path.lower()
    rows=[]
    try:
        if suffix.endswith('.pdf'):
            # Reading a downloaded supplement does not establish a reusable table.
            if (e.get('http_status')!=200 or len(data)>8*1024*1024
                    or not data.startswith(b'%PDF-')
                    or len(data)!=e.get('bytes_observed') or digest(data)!=e.get('payload_sha256')
                    or e.get('cloud_checksum',{}).get('verified') is False):
                raise ValueError('PDF completeness, payload or checksum validation failed')
            try:
                from pypdf import PdfReader
                reader=PdfReader(io.BytesIO(data))
                if reader.is_encrypted:raise ValueError('Encrypted PDF requires separate review')
                if not 1<=len(reader.pages)<=64:raise ValueError('PDF page limit exceeded')
                passages=[];characters=0
                for page in reader.pages:
                    passage=page.extract_text() or '';characters+=len(passage)
                    if characters>250000:raise ValueError('PDF text limit exceeded')
                    passages.append(passage)
            except Exception as exc:
                raise ValueError('PDF text inspection failed: '+str(exc)) from exc
            e.update(text='\n'.join(passages),pdf_page_count=len(passages),
                     pdf_text_extracted=bool(characters),columns=[],level='response_sample',
                     interpretation_note='Complete PDF text read; no table schema or dataset reusability inferred')
            if binary_candidate:e.update(status='accessible',failure_reason='')
        elif 'json' in fmt or suffix.endswith('.json'):
            parsed=json.loads(data)
            if isinstance(parsed,dict):
                choices=[v for v in parsed.values() if isinstance(v,list) and v and isinstance(v[0],dict)]
                parsed=choices[0] if len(choices)==1 else []
            if isinstance(parsed,list) and parsed and all(isinstance(x,dict) for x in parsed):
                columns=list(parsed[0]);rows=[columns]+[[x.get(k) for k in columns] for x in parsed[:100]]
        elif suffix.endswith(('.csv','.tsv','.txt')) or any(k in fmt for k in ['csv','tab-separated']):
            delim='\t' if suffix.endswith('.tsv') or 'tab-separated' in fmt else ','
            rows=list(csv.reader(io.StringIO(data.decode('utf-8-sig')),delimiter=delim))[:101]
        elif suffix.endswith('.zip'):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                members=[m for m in archive.infolist() if not m.filename.startswith('__MACOSX/')
                         and not m.filename.rsplit('/',1)[-1].startswith('.')
                         and m.filename.lower().endswith(('.csv','.tsv','.txt'))]
                if len(members)>32 or sum(m.file_size for m in members)>8*1024*1024:
                    raise ValueError('Archive table inspection exceeds limit')
                tables={};e['archive_tables']=[]
                for member in members:
                    raw=archive.read(member);decoded=raw.decode('utf-8-sig')
                    lines=decoded.splitlines()
                    if not lines:continue
                    delim='\t' if '\t' in lines[0] else ','
                    table=[r for r in csv.reader(lines,delimiter=delim) if r]
                    if len(table)<2 or len(table[0])<2:continue
                    sha=digest(raw);tables[sha]=table
                    e['archive_tables'].append(dict(member=member.filename,sha256=sha,rows=len(table)-1,columns=table[0]))
                if len(tables)==1:
                    table=next(iter(tables.values()))
                    if not all(len(row)==len(table[0]) for row in table):raise ValueError('Inconsistent archive table rows')
                    rows=table[:101]
                    e['text']=e.get('text','')+'\nArchive tables: '+json.dumps(e['archive_tables'],ensure_ascii=False)
                elif tables:
                    e['structure_failure']='Multiple distinct archive tables require explicit selection'
                    e.update(status='accessible',failure_reason='',level='response_sample',
                             interpretation_note='Complete ZIP opened; distinct tables preserved without inferring a common schema')
                    e['text']=e.get('text','')+'\nArchive tables: '+json.dumps(e['archive_tables'],ensure_ascii=False)
        elif suffix.endswith('.docx'):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                member=archive.getinfo('word/document.xml')
                if member.file_size>8*1024*1024:raise ValueError('DOCX document exceeds inspection limit')
                xml=archive.read(member)
            if b'<!ENTITY' in xml.upper() or b'<!DOCTYPE' in xml.upper():raise ValueError('Unsafe DOCX XML')
            tree=ET.fromstring(xml);ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            def cell_text(node):return ''.join(node.itertext())
            tables=[]
            for table in tree.findall('.//w:tbl',ns):
                if table.findall('.//w:vMerge',ns) or table.findall('.//w:gridSpan',ns):
                    continue  # Merged headers require explicit review, never guess column names.
                table_rows=[[cell_text(cell) for cell in row.findall('w:tc',ns)] for row in table.findall('w:tr',ns)]
                if table_rows:tables.append(table_rows)
            e['document_table_count']=len(tree.findall('.//w:tbl',ns))
            e['document_text']=' '.join(node.text or '' for node in tree.findall('.//w:t',ns))
            e['text']=e.get('text','')+'\nDOCX document text:\n'+e['document_text']
            if len(tables)==1:rows=tables[0][:101]
        elif suffix.endswith('.xls'):
            import xlrd
            if len(data)>16*1024*1024 or not data.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'):
                raise ValueError('Invalid or oversized legacy XLS response')
            try:book=xlrd.open_workbook(file_contents=data,on_demand=True)
            except xlrd.biffh.XLRDError as exc:raise ValueError('Unreadable legacy XLS: '+str(exc)) from exc
            try:
                if not 1<=book.nsheets<=64:raise ValueError('XLS worksheet limit')
                sheet=book.sheet_by_index(0)
                if sheet.ncols>256:raise ValueError('XLS column limit')
                rows=[sheet.row_values(i) for i in range(min(sheet.nrows,101))]
                rows=[r for r in rows if any(v not in ('',None) for v in r)]
                e['workbook_inspection']={'sheet':sheet.name,'header_row':1,'parser':'xlrd'}
                e['workbook_preview']={'sheet':sheet.name,'rows':rows[:6]}
                e['text']=e.get('text','')+'\nWorkbook raw rows (headers not inferred): '+json.dumps(e['workbook_preview'],ensure_ascii=False,default=str)
                if binary_candidate and rows:
                    e.setdefault('original_status',e['status'])
                    e.update(status='accessible',failure_reason='',interpretation_note='Complete legacy XLS opened; original transport record preserved')
            finally:book.release_resources()
        elif suffix.endswith('.xlsx'):
            from openpyxl import load_workbook
            wb=load_workbook(io.BytesIO(data),read_only=True,data_only=True)
            try:
                rows=list(wb.worksheets[0].iter_rows(min_row=1,max_row=101,values_only=True))
                rows=[list(r) for r in rows if any(v is not None for v in r)]
                e['workbook_inspection']={'sheet':wb.worksheets[0].title,'header_row':1}
                e['workbook_preview']={'sheet':wb.worksheets[0].title,'rows':rows[:6]}
                e['text']=e.get('text','')+'\nWorkbook raw rows (headers not inferred): '+json.dumps(e['workbook_preview'],ensure_ascii=False,default=str)
                if binary_candidate and rows:
                    e.update(status='accessible',failure_reason='',interpretation_note='Downloaded workbook opened; raw cells preserved, structure requires independent validation')
                if len(rows)>2 and rows[0][0] and all(v is None for v in rows[0][1:]) and all(v is not None for v in rows[1]):
                    e['workbook_inspection'].update(caption=str(rows[0][0]),header_row=2)
                    e['text']=e.get('text','')+'\nWorkbook caption: '+str(rows[0][0])
                    rows=rows[1:]
            finally:wb.close()
        elif 'xml' in fmt or suffix.endswith('.xml'):
            if b'<!ENTITY' in data.upper():raise ValueError('Unsafe XML')
            tree=ET.fromstring(data);children=list(tree)
            if len(children)>1 and len({x.tag for x in children})==1:
                columns=[x.tag for x in children[0]]
                if columns:rows=[columns]+[[x.findtext(k) for k in columns] for x in children[:100]]
        if len(rows)>1 and len(rows[0])>1 and all(len(r)==len(rows[0]) for r in rows):
            columns=[str(k) for k in rows[0]]
            if len(set(columns))!=len(columns) or any(k in {'','None'} for k in columns):raise ValueError('Duplicate or missing columns')
            e.update(columns=columns,level='sample_structure',sample_row_count=len(rows)-1,
                     text=e.get('text','')+'\nStructured sample:\n'+json.dumps(rows[:6],ensure_ascii=False,default=str))
            if binary_candidate:e.update(status='accessible',failure_reason='',interpretation_note='Binary structured response parsed successfully; empty decoded text was not an empty response')
    except (ValueError,TypeError,ET.ParseError,KeyError,OSError,zipfile.BadZipFile) as exc:
        e['structure_failure']=type(exc).__name__+': '+str(exc)
    e['material_inspection_key']=inspection_key
    return e


class FullWorkflowAccess(RevalidationAccess):
    def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);self.engine=None
    def additional_discovery(self,paper,prior,additions):
        bundle=copy.deepcopy(prior)
        seen={e['url'] for e in bundle['records']}
        for item in additions:
            if item['url'] in seen and not item.get('referer'):continue
            seen.add(item['url'])
            request_paper=paper
            if item.get('referer'):
                if not any(e['url']==item['referer'] and item['url'] in e.get('observed_links',[]) for e in bundle['records']):
                    raise ValueError('Download referer must be an observed linking page')
                request_paper=dict(paper,_observed_referer=item['referer'])
            found=self.request(item['url'],item['kind'],request_paper,'reviewer_additional_route')
            bundle['records']+=found
            for e in found:
                if e['kind']!='fulltext' or not e.get('identity_match'):continue
                for url in e.get('observed_links',[]):
                    if '/pdf/' not in urlsplit(url).path.lower() or url in seen:continue
                    if urlsplit(url).hostname!=urlsplit(e['final_url']).hostname:continue
                    seen.add(url);bundle['records']+=self.request(url,'fulltext',paper,'observed_publisher_pdf');break
        bundle['search_coverage'].append({'target':'reviewer_additional_routes','state':'attempted','urls':[x['url'] for x in additions]})
        return bundle
    def request(self,url,kind,paper,route):
        # Each completed request survives interruption; a new deep pass has a distinct cache.
        if self.engine is None:return self._bounded_article_request(url,kind,paper,route)
        key='request_'+digest(dump([url,kind,route]+([paper['_observed_referer']] if paper.get('_observed_referer') else [])).encode())
        return self.engine.cached(paper,key,lambda:self._bounded_article_request(url,kind,paper,route))

    def _bounded_article_request(self,url,kind,paper,route):
        records=super().request(url,kind,paper,route)
        # HTML publisher pages can exceed the small metadata response limit.
        # Preserve the truncated response; never relabel it as a complete article.
        cap=8*1024*1024
        truncated=next((e for e in records if (kind=='fulltext' or e.get('format')=='application/pdf')
                        and (e.get('failure_reason')=='response_exceeds_limit'
                             or (e.get('complete_body') is False and e.get('bytes_observed',0)>self.max_bytes))),None)
        if truncated and self.max_bytes<cap and not any(e.get('status')=='accessible' for e in records):
            old=self.max_bytes
            try:
                self.max_bytes=cap
                extra=super().request(url,kind,paper,route+'_bounded_size_retry')
                for e in extra:e['retry_of_evidence_id']=truncated['evidence_id']
                records+=extra
            finally:self.max_bytes=old
        return records

    def recover_truncated(self,paper,bundle):
        """Append a bounded recovery for older immutable truncated checkpoints."""
        bundle=copy.deepcopy(bundle)
        done={e['url'] for e in bundle['records'] if e.get('status')=='accessible'}
        for e in list(bundle['records']):
            large_file=e['kind']=='file' and e.get('format')!='application/pdf'
            cap=(32 if large_file else 8)*1024*1024
            if (e['url'] in done or e.get('complete_body') is not False
                    or not 0<e.get('bytes_observed',0)<cap
                    or e.get('http_status')!=200
                    or e.get('status')=='access_restricted'
                    or not (e['kind'] in {'fulltext','file'} or e.get('format')=='application/pdf')):continue
            done.add(e['url']);old=self.max_bytes
            try:
                self.max_bytes=cap
                route='checkpoint_truncated_response_recovery'+('_file32mb' if large_file else '')
                found=self.request(e['url'],e['kind'],paper,route)
                for row in found:row['retry_of_evidence_id']=e['evidence_id']
                bundle['records']+=found
            finally:self.max_bytes=old
        return bundle

    def collect(self,paper,policy,action=''):
        deep=isinstance(action,dict) and action.get('phase')=='revalidation' and self.engine is not None
        if deep:
            def unavailable():raise ValueError('Initial evidence cache missing')
            bundle=copy.deepcopy(self.engine.cached(paper,'collected_evidence',unavailable,round_number=1))
            bundle['action']=action
            bundle['focused_pending_code']=action.get('pending_code')
            for e in bundle['records']:e['reused_from_prior_round']=True
            targets=[]
            successful={e['url'] for e in bundle['records'] if e['status']=='accessible'}
            for e in bundle['records']:
                kinds={'fulltext'} if action.get('pending_code')=='P02' else {'repository','supplementary','landing','file','api'}
                if e['kind'] in kinds and ((e['status']!='accessible' and e['url'] not in successful) or action.get('pending_code')!='P02'):
                    pair=(e['url'],e['kind'])
                    if pair not in targets:targets.append(pair)
            for url,kind in targets[:4]:bundle['records']+=self.request(url,kind,paper,'focused_'+action.get('pending_code','pending'))
            bundle['search_coverage'].append({'target':'prior_successful_searches','state':'reused_with_original_timestamps','pending_code':action.get('pending_code')})
        else:bundle=super().collect(paper,policy,action)
        seen={e['url'] for e in bundle['records']}
        if deep:
            # A reviewer can discover a new legal route after the initial pass.
            # Preserve initial evidence and actually request only the new URLs.
            for item in paper.get('_review_discovery',[])[:8]:
                if item['url'] in seen:continue
                seen.add(item['url'])
                bundle['records']+=self.request(item['url'],item['kind'],paper,'deep_reviewer_observed_search_result')
        if isinstance(action,dict) and action.get('phase')=='revalidation':
            # Add a distinct official metadata route, not just the same failed URL.
            doi=paper['values'].get('DOI')
            url=('https://api.crossref.org/works/'+quote(doi,safe='') if doi else
                 'https://api.crossref.org/works?rows=3&query.bibliographic='+quote(paper['values']['Title']))
            found=self.request(url,'metadata',paper,'deep_Crossref_discovery');bundle['records']+=found
            for record in found:
                if record['status']!='accessible':continue
                try:
                    message=json.loads(record['text'])['message'];hits=[message] if doi else message.get('items',[])
                    for hit in hits:
                        norm=lambda s:re.sub(r'\W+','',s.casefold())
                        if doi and hit.get('DOI','').casefold()!=doi.casefold():continue
                        if not doi and norm((hit.get('title') or [''])[0])!=norm(paper['values']['Title']):continue
                        for link in hit.get('link',[])[:3]:
                            target=link.get('URL')
                            if target and target not in seen:
                                seen.add(target);bundle['records']+=self.request(target,'fulltext',paper,'deep_Crossref_observed_article')
                except (ValueError,KeyError,TypeError):pass
            bundle['search_coverage'].append({'target':'deep_Crossref_discovery','url':url,'state':'searched' if found and found[-1]['status']=='accessible' else 'search_failed'})
        # Some publishers use /pdf/ endpoints without a .pdf suffix.
        for e in list(bundle['records']):
            if e['kind']!='fulltext' or not e.get('identity_match'):continue
            for url in e.get('observed_links',[]):
                if '/pdf/' not in urlsplit(url).path.lower() or url in seen:continue
                if urlsplit(url).hostname!=urlsplit(e['final_url']).hostname:continue
                seen.add(url);bundle['records']+=self.request(url,'fulltext',paper,'observed_publisher_pdf')
                break
        bundle['scan_captures']=[]
        if self.engine:
            for e in bundle['records']:
                if e['kind']!='fulltext' or not e.get('identity_match') or e['status']!='accessible':continue
                parser=ScanImages();parser.feed(base64.b64decode(e.get('body_sample_b64','')).decode('utf-8',errors='replace'))
                for url,page in parser.pages[:30]:
                    def capture(url=url,page=page,e=e):
                        row=dict(url=url,source_evidence_id=e['evidence_id'],page=page,checked_at=now(),action='GET observed PMC page image',status='fetch_error',http_status=None)
                        try:
                            public_url(url)
                            with self.opener.open(urllib.request.Request(url,headers={'User-Agent':'K-Melloddy research evidence review'}),timeout=self.timeout) as response:
                                data=response.read(8*1024*1024+1);row['http_status']=response.status
                            if len(data)>8*1024*1024:raise ValueError('Image exceeds limit')
                            from PIL import Image
                            with Image.open(io.BytesIO(data)) as image:image.verify()
                            relative=str((self.engine.session/'scans'/paper['paper_id']/f'round_{self.engine.round}'/(digest(url.encode())+'.png')).relative_to(self.engine.root))
                            ref=self.engine.store.artifact(relative,data,raw=True)
                            row.update(status='retrieved',path=relative,sha256=ref['sha256'],bytes=len(data))
                        except (OSError,ValueError,urllib.error.URLError,http.client.HTTPException) as exc:row['error']=str(exc)
                        return row
                    row=self.engine.cached(paper,'scan_'+digest(url.encode()),capture)
                    bundle['scan_captures'].append(row)
        return bundle

    def verify_materials(self,paper,bundle):
        seen={e['url'] for e in bundle['records']};count=0
        for source in list(bundle['records']):
            if source['status']!='accessible' or source['kind']=='metadata':continue
            if source['kind']=='fulltext' and not source.get('identity_match'):continue
            for url in source.get('observed_links',[]):
                path=urlsplit(url).path.lower()
                if url in seen or not path.endswith(('.csv','.tsv','.xlsx','.json','.xml','.docx')):continue
                if count>=8:break
                seen.add(url);count+=1
                bundle['records']+=self.request(url,'file',paper,'observed_structured_material')
        bundle['records']=[inspect_material(e) for e in bundle['records']]
        return bundle
