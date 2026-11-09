"""Import explicitly reviewed public GET receipts; retain failed native attempts."""
import copy
import ipaddress
import json
from urllib.parse import urlsplit

from ..core.storage import digest
from .evidence_collector import validate_evidence
from .form_material_capture import checked_bytes


def append_http_materials(root, paper, bundle, refs):
    result=copy.deepcopy(bundle)
    if len(refs)>3:raise ValueError('HTTP capture limit')
    for ref in refs:
        path=(root/ref['path']).resolve()
        if not path.is_relative_to(root.resolve()):raise ValueError('HTTP capture outside run')
        if path.stat().st_size>16*1024*1024:raise ValueError('HTTP capture changed or oversized')
        raw=path.read_bytes()
        if len(raw)>16*1024*1024 or digest(raw)!=ref['sha256']:raise ValueError('HTTP capture changed or oversized')
        capture=json.loads(raw)
        if (capture.get('paper_id')!=paper['paper_id'] or capture.get('pmid')!=paper['pmid']
                or not capture.get('reviewer_note')):raise ValueError('Unbound HTTP capture')
        e=copy.deepcopy(capture['record'])
        if (e.get('kind') not in {'file','api'} or e.get('status')!='accessible'
                or e.get('legal_access')!='public_request'
                or e.get('request_method','GET')!='GET' or e.get('transport')=='web_tool'
                or e.get('failure_reason') or not e.get('timestamp')):
            raise ValueError('Not a successful public GET receipt')
        for key in ['url','final_url']:
            u=urlsplit(e.get(key,''))
            if (u.scheme not in {'http','https'} or not u.hostname or u.username or u.password
                    or u.hostname in {'localhost','localhost.localdomain'}):
                raise ValueError('Invalid HTTP capture URL')
            try:address=ipaddress.ip_address(u.hostname)
            except ValueError:address=None
            if address is not None and not address.is_global:raise ValueError('Nonpublic HTTP capture URL')
        if not any(old.get('kind')==e['kind'] and e['url'] in
                   {old.get('url'),old.get('final_url')} for old in bundle['records']):
            raise ValueError('HTTP material route was not observed by collector')
        checked_bytes(e)
        original=e['evidence_id']
        e.update(evidence_id='http-capture-'+digest(raw)[:24],original_evidence_id=original,
                 source_capture_file=copy.deepcopy(ref),transport='reviewed_http_capture',
                 capture_reviewer_note=capture['reviewer_note'],
                 source_request_performed=True,request_performed=False,
                 level='response_sample',columns=[],downloaded_full_dataset=False,
                 interpretation_note='Reused actual successful public GET receipt; no new request, structure or scientific verdict inferred')
        if not any(old['evidence_id']==e['evidence_id'] for old in result['records']):
            result['records'].append(e)
    return validate_evidence(result)
