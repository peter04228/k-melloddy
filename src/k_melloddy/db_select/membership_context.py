"""Verify a published category-membership column against actual exposure metadata."""
import base64
import hashlib
import io
import json
import re
import zipfile

from ..core.storage import digest,dump


def workbook(record):
    from openpyxl import load_workbook
    raw=base64.b64decode(record.get('body_sample_b64',''),validate=True)
    if (record.get('kind')!='file' or record.get('status')!='accessible'
            or record.get('http_status')!=200 or record.get('complete_body') is not True
            or not raw or len(raw)>16*1024*1024 or len(raw)!=record.get('bytes_observed')
            or digest(raw)!=record.get('payload_sha256')
            or record.get('cloud_checksum',{}).get('verified') is not True):
        raise ValueError('Membership needs complete checksum-verified workbook bytes')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if sum(x.file_size for x in archive.infolist())>64*1024*1024:
            raise ValueError('Membership workbook expansion limit')
    return load_workbook(io.BytesIO(raw),read_only=True,data_only=False),raw


def verify_membership_context(dataset,evidence,material,context):
    from .dataset_verifier import citations
    from .pmc_cloud import _resource
    if (context.get('scope')!='column_membership_list'
            or not context.get('reviewer_rationale','').strip()):
        raise ValueError('Membership requires explicit scope and rationale')
    column=context.get('member_column')
    if not column or material['columns']!=[column] or any(dataset[k]!=column for k in ['drug_identifier','endpoint','value_field']):
        raise ValueError('Membership must preserve its one actual source column')
    refs=[context[k] for k in ['binding_reference','classification_reference']]
    lookup=citations(refs,evidence);manifest=lookup[refs[0]['evidence_id']];article=lookup[refs[1]['evidence_id']]
    if (manifest.get('kind')!='metadata' or manifest.get('status')!='accessible'
            or manifest.get('http_status')!=200 or not manifest.get('complete_body')
            or not all(manifest.get('identity_checks',{}).get(k) is True for k in ['pmid','pmcid','doi','title'])):
        raise ValueError('Membership requires verified official file metadata')
    raw=base64.b64decode(manifest.get('body_sample_b64',''),validate=True)
    if not raw or len(raw)>1024*1024 or len(raw)!=manifest['bytes_observed'] or digest(raw)!=manifest['payload_sha256']:
        raise ValueError('Membership metadata bytes changed')
    meta=json.loads(raw);pmcid=meta.get('pmcid','');version=meta.get('version')
    if not re.fullmatch(r'PMC[0-9]+',pmcid) or type(version)!=int or version<1:
        raise ValueError('Membership metadata identity incomplete')
    prefix=f'{pmcid}.{version}/'
    if manifest['url']!='https://pmc-oa-opendata.s3.amazonaws.com/'+prefix+prefix.rstrip('/')+'.json':
        raise ValueError('Membership metadata is not the official article manifest')
    if (article.get('kind')!='fulltext' or not article.get('identity_match')
            or article.get('status')!='accessible' or not article.get('complete_body')
            or article.get('http_status')!=200 or not meta.get('doi')
            or meta['doi'].casefold() not in article.get('text','').casefold()):
        raise ValueError('Membership classification must cite the same verified article')
    metadata=lookup.get(context.get('metadata_evidence_id'))
    if metadata is None:raise ValueError('Membership exposure metadata not captured')
    resources=dict(res for uri in meta.get('media_urls',[]) if (res:=_resource(uri,prefix)))
    for record in [material,metadata]:
        expected=resources.get(record['url'])
        if not expected:raise ValueError('Membership workbook not listed for this article')
        body=base64.b64decode(record.get('body_sample_b64',''),validate=True)
        if hashlib.md5(body).hexdigest()!=expected:raise ValueError('Membership official checksum mismatch')
    book,_=workbook(material)
    try:
        selection=material.get('archive_selection',{})
        sheet=book[selection['sheet']];header_row=selection['header_row']
        if sheet.max_row>5001 or sheet.max_column>1024:raise ValueError('Membership list bounds exceeded')
        it=iter(sheet.iter_rows(min_row=header_row,values_only=True));head=next(it)
        if head.count(column)!=1:raise ValueError('Membership header ambiguous')
        index=head.index(column);members=[];ended=False
        for row in it:
            value=row[index]
            if value in (None,''):ended=True;continue
            if ended or not isinstance(value,str) or not value.strip() or value.startswith('='):
                raise ValueError('Membership contains gaps, formulas or non-identifiers')
            members.append(value)
        if not members or len(members)!=len(set(members)):raise ValueError('Membership empty or duplicated')
    finally:book.close()
    member_set=set(members)
    if not isinstance(context.get('context_fields'),list) or not isinstance(context.get('filter'),dict):
        raise ValueError('Membership exposure metadata declaration invalid')
    drug=context['drug_field'];fields=[drug]+context['context_fields'];flt=context['filter']
    if (not 1<=len(fields)<=8 or len(fields)!=len(set(fields))
            or not all(isinstance(x,str) and x for x in fields)
            or set(flt)!={'field','value'} or not isinstance(flt['value'],str) or not flt['value']):
        raise ValueError('Membership exposure metadata declaration invalid')
    book,_=workbook(metadata)
    try:
        sheet=book[context['metadata_sheet']]
        if sheet.max_row>50001 or sheet.max_column>256:raise ValueError('Membership metadata table bounds exceeded')
        it=iter(sheet.iter_rows(values_only=True));head=next(it)
        needed=[context['key_field'],flt['field']]+fields
        if any(head.count(x)!=1 for x in needed):raise ValueError('Membership metadata headers missing or duplicated')
        indices=[head.index(x) for x in needed];bound={}
        for row in it:
            key,organ,*values=[row[i] for i in indices]
            if organ!=flt['value'] or key not in member_set:continue
            if any(v in (None,'') or (isinstance(v,str) and v.startswith('=')) for v in values):
                raise ValueError('Membership exposure metadata missing or formula')
            bound.setdefault(key,set()).add(tuple(values))
        if any(len(bound.get(key,set()))!=1 for key in members):
            raise ValueError('Membership identifiers unmatched or ambiguous in exposure metadata')
        bindings=[dict(member=key,source_values=dict(zip(fields,next(iter(bound[key]))))) for key in members]
    finally:book.close()
    return dict(scope='column_membership_list',column=column,member_count_checked=len(members),
                metadata_evidence_id=metadata['evidence_id'],filter=flt,bindings=bindings,
                metadata_source=dict(url=metadata['url'],sha256=metadata['payload_sha256']),
                category_source=dict(url=material['url'],sha256=material['payload_sha256'],selection=selection),
                bindings_sha256=digest(dump(bindings).encode()),references=refs,
                reviewer_rationale=context['reviewer_rationale'],
                interpretation='Original header supplies category membership; cells are existing condition identifiers, not numeric toxicity measurements or clinical causality labels. No new data columns or source values generated.')
