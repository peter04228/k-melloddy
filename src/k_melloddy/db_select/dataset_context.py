"""Verify explicitly reviewed single-agent cohort context without inventing columns."""
import base64
import hashlib
import json
import re
from urllib.parse import urlsplit, parse_qs
from ..core.storage import digest


def verify_single_agent_context(dataset,evidence,material):
    from .dataset_verifier import citations
    context=dataset.get('drug_context',{})
    if context.get('scope')!='single_agent_cohort' or not context.get('reviewer_rationale','').strip():
        raise ValueError('Single-agent cohort requires explicit reviewer scope and rationale')
    drug=dataset['drug_identifier'].removeprefix('constant:').strip()
    if not dataset['drug_identifier'].startswith('constant:') or not drug or context.get('drug')!=drug:
        raise ValueError('Single-agent cohort drug does not match declared constant')
    refs=[context[k] for k in ['exposure_reference','population_reference','file_binding_reference']]
    lookup=citations(refs,evidence)
    body=lookup[refs[0]['evidence_id']];population=lookup[refs[1]['evidence_id']]
    meta=lookup[refs[2]['evidence_id']]
    if (body['evidence_id']!=population['evidence_id'] or body.get('kind')!='fulltext'
            or not body.get('identity_match') or body.get('status')!='accessible'
            or body.get('http_status')!=200 or not body.get('complete_body')
            or not re.search(r'(?<!\w)'+re.escape(drug)+r'(?!\w)',refs[0]['quote'],re.I)):
        raise ValueError('Single-agent context needs one verified complete article and exact exposure quote')
    if (meta.get('kind')!='metadata' or meta.get('http_status')!=200 or not meta.get('complete_body')
            or not meta.get('identity_match') or not all(meta.get('identity_checks',{}).get(k) is True
                for k in ['pmid','pmcid','doi','title'])):
        raise ValueError('Single-agent file binding requires fully verified official metadata')
    def payload(record,limit):
        raw=base64.b64decode(record.get('body_sample_b64',''),validate=True)
        if not raw or len(raw)>limit or len(raw)!=record.get('bytes_observed') or digest(raw)!=record.get('payload_sha256'):
            raise ValueError('Single-agent context payload changed, incomplete or oversized')
        return raw
    data=json.loads(payload(meta,1024*1024))
    pmcid=data.get('pmcid','');version=data.get('version')
    if not re.fullmatch(r'PMC[0-9]+',pmcid) or type(version)!=int or version<1:
        raise ValueError('Invalid official article version')
    folder=pmcid+'.'+str(version)
    expected='https://pmc-oa-opendata.s3.amazonaws.com/'+folder+'/'+folder+'.json'
    if meta.get('url')!=expected or meta.get('final_url')!=expected:
        raise ValueError('File binding metadata is not the official PMC article object')
    article=urlsplit(body.get('final_url',body.get('url','')))
    if not ((article.scheme=='https' and article.netloc=='pmc.ncbi.nlm.nih.gov'
             and article.path=='/articles/'+pmcid+'/') or
            (article.scheme=='https' and article.netloc=='www.ebi.ac.uk'
             and article.path=='/europepmc/webservices/rest/'+pmcid+'/fullTextXML')):
        raise ValueError('Exposure article and file metadata do not identify the same PMC article')
    uri=refs[2]['quote']
    if uri not in data.get('media_urls',[]) or not uri.startswith('s3://pmc-oa-opendata/'+folder+'/'):
        raise ValueError('File is not explicitly listed by this article metadata')
    url=uri.replace('s3://pmc-oa-opendata/','https://pmc-oa-opendata.s3.amazonaws.com/',1)
    if (material.get('url')!=url or material.get('final_url')!=url or dataset['direct_url']!=url
            or material.get('kind')!='file' or material.get('status')!='accessible'
            or material.get('http_status')!=200 or not material.get('complete_body')
            or material.get('cloud_checksum',{}).get('verified') is not True):
        raise ValueError('Actual complete public file and verified official checksum required')
    raw=payload(material,16*1024*1024)
    md5=parse_qs(urlsplit(url).query).get('md5',[])
    if len(md5)!=1 or hashlib.md5(raw).hexdigest()!=md5[0]:
        raise ValueError('Official material checksum does not match downloaded bytes')
    # The constant is cohort context only. No drug column, assay value, or label is added.
    return dict(context,binding_verified=True,source_pmcid=pmcid,
                binding_scope='reviewer-attested single-agent cohort; no synthetic drug column')
