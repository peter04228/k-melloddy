"""Read-only Collect handoff with strict identity and artifact validation."""
import json
import re
from pathlib import Path
from ..core.storage import digest
from ..db_collect.exporter import validate_manifest


def paper_order(record):
    if not isinstance(record.get('paper_id'),str):raise ValueError('Missing/invalid Collect paper_id')
    match=re.fullmatch(r'(.+)-(?:P)?(\d+)',record['paper_id'])
    if not match:
        raise ValueError('Invalid Collect paper_id')
    return (match[1],int(match[2]))


def load_collect(manifest_path, collect_root):
    path, root=Path(manifest_path).resolve(),Path(collect_root).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Manifest must be inside the selected DB_Collect root')
    data=path.read_bytes()
    manifest=json.loads(data)
    validate_manifest(manifest)
    if not manifest.get('project_id'):
        raise ValueError('Missing Collect project_id')
    masters=[]
    for a in manifest['artifacts']+manifest.get('provenance_artifacts',[]):
        target=(root/a['path']).resolve()
        if not target.is_relative_to(root) or a['run_id']!=manifest['run_id'] or a['schema_version']!='1.0':
            raise ValueError('Unsafe artifact path or wrong run/schema')
        if digest(target.read_bytes())!=a['sha256']:
            raise ValueError('Collect artifact hash mismatch: '+a['path'])
        if target.name=='internal_master.json':
            masters.append(target)
    if len(masters)!=1:
        raise ValueError('Exactly one internal_master.json is required; no lossy CSV inference')
    papers=json.loads(masters[0].read_text(encoding='utf-8'))
    if len(papers)!=manifest['record_count'] or len(papers)!=manifest['counts']['unique_pmid_count']:
        raise ValueError('Collect row count mismatch')
    ids,pmids=set(),set()
    for p in papers:
        paper_order(p)
        if not isinstance(p.get('pmid'),str) or not re.fullmatch(r'[1-9]\d*',p['pmid']):
            raise ValueError('Invalid PMID')
        if p['paper_id'] in ids or p['pmid'] in pmids or p.get('source_run_id')!=manifest['run_id']:
            raise ValueError('Duplicate identity or source run mismatch')
        if not {'Title','Abstract','DOI','PMCID','PMID'} <= p.get('values',{}).keys() or p['values']['PMID']!=p['pmid']:
            raise ValueError('Missing required source columns/PMID mismatch')
        if not {'fetch_state','abstract_state'} <= p.keys():
            raise ValueError('Missing availability states')
        ids.add(p['paper_id']); pmids.add(p['pmid'])
    return manifest, sorted(papers,key=paper_order), {'path':str(path),'sha256':digest(data),'run_id':manifest['run_id'],'schema_version':'1.0'}
