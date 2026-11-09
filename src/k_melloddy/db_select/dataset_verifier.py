import re
from urllib.parse import urlsplit, urlunsplit
from ..core.storage import digest, dump


def citations(refs,evidence):
    lookup={e['evidence_id']:e for e in evidence['records']}
    if not refs: raise ValueError('No supporting citations')
    for ref in refs:
        e=lookup.get(ref['evidence_id'])
        if not e or e['status']!='accessible' or not ref['quote'].strip() or ref['quote'] not in e['text']:
            raise ValueError('Unsupported or fabricated evidence quote')
    return lookup


def canonical_identity(identity,version):
    identity=identity.strip()
    if identity.lower().startswith(('https://doi.org/','http://doi.org/')):
        identity='doi:'+identity.lower().split('doi.org/',1)[1]
    if identity.lower().startswith('doi:'):identity=identity.lower()
    if identity.startswith('doi:') and not re.fullmatch(r'doi:10\.\d{4,9}/\S+',identity):
        raise ValueError('Invalid dataset DOI')
    if not identity.startswith(('doi:','accession:','url:')):
        raise ValueError('Dataset identity must be doi:, accession:repository:id or url:canonical-url')
    if identity.startswith('url:'):
        u=urlsplit(identity[4:])
        if u.scheme not in {'http','https'} or not u.hostname: raise ValueError('Invalid dataset identity URL')
        identity='url:'+urlunsplit((u.scheme.lower(),u.netloc.lower(),u.path.rstrip('/'),u.query,''))
    return digest(dump([identity,version.strip()]).encode())


def verify_dataset(dataset,evidence):
    lookup=citations(dataset['evidence_refs'],evidence)
    e=lookup.get(dataset['evidence_id'])
    if not e or e['kind'] not in {'file','api'} or e['status']!='accessible':
        raise ValueError('Landing page/code repository is not a verified dataset file/API')
    if dataset['direct_url'] not in {e['url'],e['final_url']}:
        raise ValueError('Direct download path was not observed by collector')
    if e['level'] not in {'sample_structure','metadata_structure','full_file'}:
        raise ValueError('Link response alone does not verify data structure')
    if not {dataset['drug_identifier'],dataset['endpoint'],dataset['value_field']}<=set(e['columns']):
        raise ValueError('Drug/endpoint/value fields not verified in sample or official metadata')
    if not dataset['independence_reason'].strip(): raise ValueError('Missing independent registration rationale')
    # Counts can be claimed only when they are actually observed by the collector.
    for key in ['feature_count','compound_count']:
        if dataset[key] is not None and dataset[key]!=e.get(key):
            raise ValueError('Unverified dataset count: '+key)
    return dict(dataset,canonical_key=canonical_identity(dataset['identity'],dataset['version']),
                verification_level=e['level'],file_format=e['format'],evidence_sha256=e['payload_sha256'],
                downloaded_full_dataset=e.get('downloaded_full_dataset',False))
