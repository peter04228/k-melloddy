"""Import explicitly reviewed public web-tool captures without inventing HTTP metadata."""
import copy
import json
from urllib.parse import urlsplit
from ..core.storage import digest


def append_captures(root, paper, bundle, refs):
    result = copy.deepcopy(bundle)
    for ref in refs:
        path = (root / ref['path']).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError('Capture outside run root')
        raw = path.read_bytes()
        if digest(raw) != ref['sha256']:
            raise ValueError('Web capture changed')
        capture = json.loads(raw)
        if capture['pmid'] != paper['pmid'] or capture['paper_id'] != paper['paper_id']:
            raise ValueError('Web capture belongs to another paper')
        e = capture['record']
        if e.get('transport') != 'web_tool' or e.get('http_status') is not None:
            raise ValueError('Web capture must not invent HTTP status')
        validate_web_capture(e)
        # A capture is a reviewer-attested excerpt/summary, never a downloaded dataset.
        expected = paper['values'].get('PMCID', '')
        pmc_match = (e['kind']=='fulltext' and expected and urlsplit(e['url']).hostname == 'pmc.ncbi.nlm.nih.gov'
                     and '/articles/' + expected + '/' == urlsplit(e['url']).path)
        if not pmc_match:
            identifiers = capture.get('verified_identifiers', {})
            values = paper['values']
            observed = any(old.get('kind') == e['kind'] and e['url'] in
                           (old.get('url'), old.get('final_url')) for old in bundle['records'])
            if (urlsplit(e['url']).hostname == 'pmc.ncbi.nlm.nih.gov' or not observed
                    or not values.get('DOI') or not values.get('Title')
                    or identifiers.get('DOI') != values['DOI']
                    or identifiers.get('Title') != values['Title']):
                raise ValueError('Capture must match verified identity and an observed fulltext route')
        e['capture_file'] = dict(ref)
        if not any(old['evidence_id'] == e['evidence_id'] for old in result['records']):
            result['records'].append(e)
    return result


def validate_web_capture(e):
    if (e.get('kind') not in {'fulltext','repository','landing'} or e.get('format') != 'reviewer_excerpt'
            or e.get('level') != 'reviewed_excerpt' or e.get('http_status') is not None
            or e.get('complete_body') is not False or e.get('downloaded_full_dataset') is not False
            or not e.get('source_reference') or not e.get('reviewer_note') or not e.get('timestamp')
            or not e.get('identity_match') or not e.get('text') or e.get('body_sample_b64')):
        raise ValueError('Invalid explicit web-tool capture')
    raw = e['text'].encode('utf-8')
    if e.get('payload_sha256') != digest(raw) or e.get('bytes_observed') != len(raw):
        raise ValueError('Web capture excerpt hash/size mismatch')

