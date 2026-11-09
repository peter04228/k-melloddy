"""Bind an explicitly reviewed title-variant manuscript to official bibliographic links."""
import base64
import copy
import io
import json
import re
import unicodedata

from ..core.storage import digest,dump


def normalized(text):
    return ' '.join(unicodedata.normalize('NFKC',text).casefold().split()).rstrip('.')


def bind_manuscripts(paper,bundle,selections):
    result=copy.deepcopy(bundle)
    if not isinstance(selections,list) or len(selections)>3:raise ValueError('Manuscript binding limit')
    for selection in selections:
        original=next(e for e in bundle['records'] if e['evidence_id']==selection['pdf_evidence_id'])
        metadata=next(e for e in bundle['records'] if e['evidence_id']==selection['metadata_evidence_id'])
        if (not selection.get('reviewer_note','').strip() or original.get('kind')!='fulltext'
                or original.get('status')!='fetch_error'
                or original.get('failure_reason')!='article_identity_not_verified'
                or original.get('http_status')!=200 or original.get('complete_body') is not True
                or metadata.get('kind')!='metadata' or metadata.get('status')!='accessible'
                or metadata.get('http_status')!=200 or metadata.get('complete_body') is not True):
            raise ValueError('Binding requires complete actual PDF and bibliographic response')
        if (not metadata.get('url','').startswith('https://www.ebi.ac.uk/europepmc/webservices/rest/search?')
                or metadata.get('final_url')!=metadata['url']):
            raise ValueError('Not the official Europe PMC metadata route')
        rawmeta=base64.b64decode(metadata.get('body_sample_b64',''),validate=True)
        if len(rawmeta)>1024*1024 or len(rawmeta)!=metadata.get('bytes_observed') or digest(rawmeta)!=metadata.get('payload_sha256'):
            raise ValueError('Bibliographic payload changed')
        hits=json.loads(rawmeta).get('resultList',{}).get('result',[])
        values=paper['values'];doi=values.get('DOI','')
        hits=[h for h in hits if h.get('id')==paper['pmid'] and h.get('source')=='MED'
              and doi and h.get('doi','').casefold()==doi.casefold()
              and normalized(h.get('title',''))==normalized(values['Title'])]
        if len(hits)!=1:raise ValueError('Official PMID DOI title not uniquely matched')
        hit=hits[0]
        linked=[x for x in hit.get('fullTextUrlList',{}).get('fullTextUrl',[])
                if x.get('documentStyle')=='pdf' and x.get('availabilityCode')=='F'
                and x.get('url') in {original['url'],original['final_url']}]
        if not linked:raise ValueError('Official record does not link this exact free PDF URL')
        raw=base64.b64decode(original.get('body_sample_b64',''),validate=True)
        if (not raw.startswith(b'%PDF-') or len(raw)>8*1024*1024
                or len(raw)!=original.get('bytes_observed') or digest(raw)!=original.get('payload_sha256')):
            raise ValueError('Manuscript PDF payload changed')
        from pypdf import PdfReader
        reader=PdfReader(io.BytesIO(raw))
        if reader.is_encrypted or not 1<=len(reader.pages)<=64:raise ValueError('Unsupported manuscript PDF')
        text='\n'.join(p.extract_text() or '' for p in reader.pages)
        if len(text)>250000 or text!=original.get('text'):raise ValueError('Manuscript text changed')
        title=selection['manuscript_title'];quote=selection['title_quote']
        if (not quote or quote not in text[:7000] or normalized(title) not in normalized(quote)
                or ':' not in title or ':' not in values['Title']
                or normalized(title.split(':',1)[0])!=normalized(values['Title'].split(':',1)[0])):
            raise ValueError('Unverified manuscript title or different primary title')
        authors=hit.get('authorList',{}).get('author',[])
        surnames=[a.get('lastName','') for a in authors]
        if (not surnames or not all(surnames) or any(not re.search(r'(?<!\w)'+re.escape(normalized(n))+r'(?=\d|\W|$)',normalized(text[:7000])) for n in surnames)):
            raise ValueError('Manuscript does not contain all official author surnames')
        front_dois=re.findall(r'10\.\d{4,9}/[^\s<>]+',text[:2500])
        if front_dois and not any(d.rstrip('.,;').casefold()==doi.casefold() for d in front_dois):
            raise ValueError('Conflicting manuscript front-page DOI')
        e=copy.deepcopy(original)
        e.update(evidence_id='manuscript-bound-'+digest(dump(selection).encode())[:24],
                 parent_evidence_id=original['evidence_id'],status='accessible',failure_reason='',identity_match=True,
                 request_performed=False,transport='verified_manuscript_identity',
                 manuscript_identity_binding=copy.deepcopy(selection),
                 prior_identity_classification={k:copy.deepcopy(original.get(k)) for k in ['status','failure_reason','identity_checks']},
                 identity_binding_scope='Exact official free-PDF URL, PMID/DOI/title and author names; original manuscript subtitle retained. Not a data or inclusion decision.')
        if not any(x['evidence_id']==e['evidence_id'] for x in result['records']):result['records'].append(e)
    return result
