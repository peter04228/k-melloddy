from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from contextlib import contextmanager
from datetime import date, timedelta, datetime, timezone
from pathlib import Path

import yaml

from ..core.storage import Store, digest, dump, now, safe_name, uid
from .client import NCBIClient, parse_search
from .config import FIELDS, read_inputs, validate
from .exporter import csv_bytes, export_files, validate_manifest
from .metadata import parse_metadata


@contextmanager
def project_lock(root):
    """OS lock is released even after process death; stale lock files are harmless."""
    f = open(Path(root) / '.collect.lock', 'a+b')
    try:
        f.seek(0)
        if not f.read(1):
            f.write(b'0')
            f.flush()
        f.seek(0)
        if __import__('os').name == 'nt':
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        f.close()


class Collector:
    def __init__(self, root, client=None):
        self.root = Path(root)
        self.store = Store(root)
        self.client = client
        self.step = '1.1'

    def close(self):
        self.store.close()

    def status(self):
        return [dict(r) for r in self.store.db.execute(
            'SELECT search_run_id,search_date,count_reported,status,query_hash FROM search_runs ORDER BY search_date')]

    def artifact(self, folder, name, value, raw=False):
        relative = f'{folder}/{self.run_id}/{self.attempt}/{name}'
        if folder == 'Output':
            if not getattr(self, 'output_folder', None):
                day = datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d')
                base = f"Output/{safe_name(self.project['organ'])}_{day}"
                self.output_folder = base if not (self.root/base).exists() else f'{base}_{self.attempt}'
            relative = f'{self.output_folder}/{name}'
        return self.store.artifact(self.run_id, self.step, relative, value if raw else dump(value))

    def request(self, key, call, parser, kind, extension):
        cached = self.store.cached(self.run_id, key)
        if cached:
            return parser(cached[0]), cached[1]
        data = call()
        name = f'{kind}/{uid()}.{extension}'
        artifact = self.artifact('Raw', name, data, raw=True)
        parsed = parser(data)  # Keep invalid responses, but never checkpoint them.
        self.store.checkpoint(self.run_id, key, artifact['path'])
        return parsed, artifact['path']

    def search(self, query, start=0, size=0, expected=None):
        def parser(data):
            result = parse_search(data)
            if expected is not None and (result['count'] != expected or len(result['ids']) != size):
                raise ValueError(f'Search drift/page mismatch: expected count={expected}, page={size}; got count={result["count"]}, page={len(result["ids"])}')
            return result
        key = dump(['search', query, start, size, self.config['sort']])
        return self.request(key, lambda: self.client.search(query, start, size, self.config['sort']), parser, 'search_response', 'json')[0]

    def event(self, state, **kwargs):
        self.store.event(self.run_id, self.step, state, **kwargs)

    def execute_step(self, number, unit, ids, operation, input_count=None):
        self.step = f'1.{number}'
        ids = list(ids)
        total = len(ids) if input_count is None else input_count
        counts = dict(input=total, forwarded=0, removed=0, pending=total)
        self.event('started', entity_type=unit, counts=counts, ids=ids)
        started = now()
        try:
            result, forwarded, removed, pending = operation()
            if total != forwarded + removed + pending:
                raise ValueError(f'Transition invariant failed in {self.step}')
            status = 'partial' if pending else 'completed'
            if (number == 6 and self.issues) or (number in {10,12} and self.qc_status != 'COMPLETED'):
                status = 'partial'
            counts = dict(input=total, forwarded=forwarded, removed=removed, pending=pending)
            self.event(status, entity_type=unit, counts=counts, ids=ids)
            with self.store.db:
                self.store.db.execute('INSERT INTO step_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                    (uid(), self.run_id, self.step, status, started, now(), total, forwarded, removed, pending, unit, digest(dump(sorted(ids)).encode())))
            return result
        except BaseException as exc:
            self.event('failed', entity_type=unit, counts=counts, ids=ids,
                       reason='interrupted' if isinstance(exc, KeyboardInterrupt) else 'validation_or_request_failed', detail=str(exc))
            with self.store.db:
                self.store.db.execute('INSERT INTO step_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                    (uid(), self.run_id, self.step, 'failed', started, now(), total, 0, 0, total, unit, digest(dump(sorted(ids)).encode())))
            raise

    def run(self, resume=None, search_only=False, export_only=False, current_output=False):
        with project_lock(self.root):
            self.output_folder = None
            self.current_output = current_output
            return self._run(resume, search_only, export_only)

    def _run(self, resume, search_only, export_only):
        self.attempt = uid()
        self.issues = []
        db = self.store.db
        if resume:
            row = db.execute('SELECT * FROM search_runs WHERE search_run_id=?', (resume,)).fetchone()
            if row is None:
                raise ValueError('Unknown run ID')
            self.run_id, self.query = resume, row['query_text']
            snapshot = json.loads(row['config_json'])
            self.project, self.config = snapshot['project'], validate(snapshot['config'])
            if row['status'] == 'COMPLETED' and not export_only:
                return {'run_id': resume, 'status': 'COMPLETED', 'message': 'Already complete; create a new run to search again'}
            self.step = '1.1'
            self.event('retried', reason='export_requested' if export_only else 'resume_requested')
        else:
            if export_only:
                raise ValueError('Export requires --resume RUN_ID')
            self.project, self.query, self.config = read_inputs(self.root)
            self.run_id = uid()
            # Email is operational only: never persist credentials/contact in snapshots.
            self.config = dict(self.config)
            contact = self.config.pop('email', '')
            self.config['email'] = ''
            with db:
                db.execute('INSERT INTO search_runs VALUES (?,?,?,?,?,?,?,?,?)',
                    (self.run_id, self.project['project_id'], self.query, digest(self.query.encode()), now(), None, None, 'RUNNING',
                     dump({'project': self.project, 'config': self.config})))
            if self.client is None:
                self.client = NCBIClient(email=contact, tool=self.config['tool'])
        if self.client is None:
            import os
            self.client = NCBIClient(email=os.environ.get('NCBI_EMAIL', ''), tool=self.config['tool'])
        if isinstance(self.client, NCBIClient):
            self.client.on_retry = lambda n, status, delay: self.event('retried', entity_type='file', reason='network_retry', detail=f'attempt={n}; HTTP={status}; delay={delay}')
        if export_only:
            if self.current_output:
                selected = yaml.safe_load((self.root/'Input/fields.yaml').read_text(encoding='utf-8'))['fields']
                output = yaml.safe_load((self.root/'Input/config.yaml').read_text(encoding='utf-8'))
                self.config = validate({**self.config, 'fields': selected,
                    'formats': output.get('formats', self.config['formats']),
                    'csv_bom': output.get('csv_bom', self.config['csv_bom'])})
            # Cached request replay only. Never silently fetch data during export.
            class NoNetwork:
                def search(self, *args):
                    raise ValueError('Export needs an uncached search; resume collection first')
                def fetch(self, *args):
                    raise ValueError('Export needs uncached metadata; resume collection first')
            self.client = NoNetwork()
        try:
            for number, name, obj in [
                (1, 'project', self.project),
                (2, 'search_config', dict(query=self.query, query_hash=digest(self.query.encode()), sort=self.config['sort'],
                    date_start=self.config['date_start'], date_end=self.config['date_end'], date_field=self.config['date_field'])),
                (3, 'fields', {'export_fields': self.config['fields'], 'internal_required': ['PMID','Title','Abstract','DOI','PMCID','raw_xml_path','source_run_id']}),
                (4, 'output_config', self.config),
            ]:
                def configure(name=name, obj=obj):
                    self.artifact('Input/runs', name + '.json', obj)
                    return obj, 0, 0, 0
                self.execute_step(number, 'paper', [], configure)
            self.effective_query = self.query
            if self.config['date_start']:
                self.effective_query = self.date_query(self.config['date_start'], self.config['date_end'])
            def initial_search():
                result = self.search(self.effective_query)
                self.artifact('Intermediate', 'search_manifest.json', dict(result, query=self.query,
                    effective_query=self.effective_query,
                    snapshot_time=db.execute('SELECT search_date FROM search_runs WHERE search_run_id=?', (self.run_id,)).fetchone()[0],
                    sort=self.config['sort'], search_run_id=self.run_id))
                with db:
                    db.execute('UPDATE search_runs SET count_reported=?,translated_query=? WHERE search_run_id=?',
                        (result['count'], result['translation'], self.run_id))
                self.event('observed', entity_type='search_result', counts={'official_count': result['count']})
                return result, 0, 0, 0
            self.official = self.execute_step(5, 'search_result', [], initial_search)['count']
            if search_only:
                self.set_status('SEARCHED')
                self.audit_reports()
                return {'run_id': self.run_id, 'status': 'SEARCHED', 'official_count': self.official}
            self.parts = self.execute_step(6, 'search_result', [digest(self.effective_query.encode())], self.partition, input_count=self.official)
            self.occurrences = self.execute_step(7, 'pmid_occurrence', [p['partition_id'] for p in self.parts], self.retrieve,
                input_count=sum(p['expected_count'] for p in self.parts))
            self.pmids = self.execute_step(8, 'pmid_occurrence', [r['pmid'] for r in self.occurrences], self.deduplicate)
            self.records = self.execute_step(9, 'unique_pmid', self.pmids, self.metadata)
            self.qc = self.execute_step(10, 'unique_pmid', self.pmids, self.quality)
            self.execute_step(11, 'paper', self.pmids, self.assign)
            self.execute_step(12, 'paper', self.pmids, self.export)
            self.audit_reports()
            self.set_status(self.qc['status'])
            return {'run_id': self.run_id, 'status': self.qc['status'], 'counts': self.qc['counts'], 'manifest': self.manifest_path}
        except BaseException as exc:
            self.set_status('PARTIAL')
            self.artifact('Reports', 'failure.json', {'step': self.step, 'reason': str(exc), 'type': type(exc).__name__, 'resume_run_id': self.run_id})
            self.audit_reports()
            raise

    def set_status(self, status):
        with self.store.db:
            self.store.db.execute('UPDATE search_runs SET status=? WHERE search_run_id=?', (status, self.run_id))

    def date_query(self, start, end):
        return f'({self.query}) AND ("{start}"[{self.config["date_field"]}] : "{end}"[{self.config["date_field"]}])'

    def partition(self):
        nodes = []
        def add(query, count, start=None, end=None, parent=None):
            pid = f'p{len(nodes):06d}'
            node = dict(partition_id=pid, parent_id=parent, query=query, start=start, end=end,
                        inclusive=True, date_field=self.config['date_field'], expected_count=count, leaf=True)
            nodes.append(node)
            if count > self.config['partition_target']:
                if start is None:
                    node['leaf'] = False
                    a = self.config['date_start'] or self.config['partition_start']
                    b = self.config['date_end'] or self.config['partition_end']
                    q = self.date_query(a, b)
                    add(q, self.search(q)['count'], a, b, pid)
                elif start != end:
                    node['leaf'] = False
                    a, b = date.fromisoformat(start), date.fromisoformat(end)
                    mid = a + (b - a) // 2
                    for lo, hi in [(a, mid), (mid + timedelta(days=1), b)]:
                        q = self.date_query(str(lo), str(hi))
                        add(q, self.search(q)['count'], str(lo), str(hi), pid)
                elif count > 10000:
                    node['blocked'] = True
                    self.issues.append({'reason': 'single_day_overflow', 'partition_id': pid,
                                        'detail': 'Cannot enumerate >10000 for a single day; narrower external strategy required'})
            return node
        # <=10000 is retrievable as-is; partition larger snapshots to <=target.
        if self.official <= 10000:
            nodes.append(dict(partition_id='p000000', parent_id=None, query=self.effective_query,
                              expected_count=self.official, leaf=True, start=self.config['date_start'], end=self.config['date_end']))
        else:
            add(self.effective_query, self.official)
        leaves = [n for n in nodes if n['leaf']]
        if sum(n['expected_count'] for n in leaves) != self.official:
            self.issues.append({'reason': 'partition_count_mismatch', 'detail': 'Date coverage, overlapping date values or database drift; snapshot cannot be certified'})
        with self.store.db:
            for n in nodes:
                self.store.db.execute('INSERT OR IGNORE INTO partitions VALUES (?,?,?,?,?,?,?)',
                    (n['partition_id'], self.run_id, n['parent_id'], n['query'], n['expected_count'], 0, 'BLOCKED' if n.get('blocked') else 'PENDING'))
        self.artifact('Intermediate', 'partitions.json', nodes)
        for issue in self.issues:
            self.event('partial', entity_type='search_result', entity_id=issue.get('partition_id',''), reason=issue['reason'], detail=issue['detail'])
        pending = self.official if self.issues else 0
        return leaves, self.official-pending, 0, pending

    def retrieve(self):
        occurrences = []
        for p in self.parts:
            if p.get('blocked'):
                continue
            count = p['expected_count']
            actual = 0
            for page, start in enumerate(range(0, count, self.config['page_size'])):
                size = min(self.config['page_size'], count - start)
                result = self.search(p['query'], start, size, count)
                rows = [dict(search_run_id=self.run_id, partition_id=p['partition_id'], page_no=page,
                             pmid=pmid, occurrence_no=i) for i, pmid in enumerate(result['ids'])]
                actual += len(rows)
                with self.store.db:
                    self.store.db.executemany('INSERT OR IGNORE INTO pmid_occurrences VALUES (?,?,?,?,?)',
                        [(self.run_id, p['partition_id'], page, r['pmid'], r['occurrence_no']) for r in rows])
                occurrences.extend(rows)
                self.artifact('Intermediate', f'pages/{p["partition_id"]}_{page}.json',
                    dict(expected=size, actual=len(rows), duplicate_ids=len(rows)-len(set(result['ids'])),
                         partition_id=p['partition_id'], page=page, ids_hash=digest(dump(result['ids']).encode())))
            if actual != count:
                raise ValueError('Partition retrieval count mismatch')
            with self.store.db:
                self.store.db.execute('UPDATE partitions SET retrieved_count=?,status=? WHERE search_run_id=? AND partition_id=?',
                    (actual, 'RETRIEVED', self.run_id, p['partition_id']))
        self.artifact('Raw', 'pmid_occurrences.json', occurrences)
        self.event('observed', entity_type='pmid_occurrence', counts={'raw_occurrence_count': len(occurrences)}, ids=[r['pmid'] for r in occurrences])
        return occurrences, len(occurrences), 0, sum(p['expected_count'] for p in self.parts)-len(occurrences)

    def deduplicate(self):
        seen, duplicates = set(), []
        for row in self.occurrences:
            if row['pmid'] in seen:
                duplicates.append(row)
            seen.add(row['pmid'])
        pmids = sorted(seen, key=int)
        counts = dict(raw_occurrence_count=len(self.occurrences), unique_pmid_count=len(pmids), duplicate_occurrence_count=len(duplicates))
        assert counts['raw_occurrence_count'] == counts['unique_pmid_count'] + counts['duplicate_occurrence_count']
        self.artifact('Intermediate', 'dedup_manifest.json', counts)
        self.artifact('Intermediate', 'unique_pmids.csv', csv_bytes([{'PMID': p} for p in pmids], ['PMID']), raw=True)
        self.artifact('Intermediate', 'duplicate_occurrences.csv', csv_bytes(duplicates, ['search_run_id','partition_id','page_no','pmid','occurrence_no']), raw=True)
        return pmids, len(pmids), len(duplicates), 0

    def metadata(self):
        records = []
        for offset in range(0, len(self.pmids), self.config['batch_size']):
            batch = self.pmids[offset:offset + self.config['batch_size']]
            def parser(data):
                parsed = parse_metadata(data, self.config['fields'])
                got = [r['pmid'] for r in parsed]
                if set(got) != set(batch) or len(got) != len(batch):
                    raise ValueError(f'EFetch PMID mismatch: missing={sorted(set(batch)-set(got))}; unexpected={sorted(set(got)-set(batch))}; duplicates={len(got)-len(set(got))}')
                return parsed
            try:
                parsed, path = self.request(dump(['fetch', batch]), lambda: self.client.fetch(batch), parser, 'pubmed_xml', 'xml')
                for r in parsed:
                    r.update(raw_xml_path=path, source_run_id=self.run_id)
            except (ValueError, RuntimeError, OSError, ET.ParseError) as exc:
                parsed = []
                for p in batch:
                    parsed.append(dict(pmid=p, values={k: p if k == 'PMID' else '' for k in FIELDS},
                        field_states={k: 'available' if k == 'PMID' else 'fetch_failed' for k in FIELDS},
                        abstract_state='unverified', fetch_state='pending_retry', raw_xml_path=None,
                        source_run_id=self.run_id, failure_reason=str(exc)))
                    self.event('partial', entity_id=p, reason='fetch_failed', detail=str(exc))
            with self.store.db:
                for r in parsed:
                    self.store.db.execute('INSERT OR REPLACE INTO paper_metadata VALUES (?,?,?,?,?,?)',
                        (self.run_id, r['pmid'], dump(r), r['raw_xml_path'], r['abstract_state'], r['fetch_state']))
            records.extend(parsed)
        self.artifact('Intermediate', 'metadata_records.json', records)
        available = sum(r['fetch_state'] == 'available' for r in records)
        return records, available, 0, len(records) - available

    def quality(self):
        issues = list(self.issues)
        if self.official != len(self.pmids):
            issues.append({'reason': 'official_unique_mismatch', 'detail': f'official={self.official}, unique={len(self.pmids)}; possible drift, overlap or incomplete date coverage'})
        for r in self.records:
            if r['fetch_state'] != 'available':
                issues.append({'pmid': r['pmid'], 'reason': 'metadata_pending', 'detail': r['failure_reason']})
            elif not r['values']['Title']:
                issues.append({'pmid': r['pmid'], 'reason': 'missing_title', 'detail': 'Required Title is absent in source'})
            doi = r['values']['DOI']
            if doi and not re.fullmatch(r'10\.\d{4,9}/\S+', doi, re.I):
                issues.append({'pmid': r['pmid'], 'reason': 'invalid_doi', 'detail': doi})
            url = r['values']['PubMed URL']
            if url and not re.fullmatch(r'https://pubmed\.ncbi\.nlm\.nih\.gov/\d+/', url):
                issues.append({'pmid': r['pmid'], 'reason': 'invalid_url', 'detail': url})
        for artifact in self.store.db.execute('SELECT * FROM artifacts WHERE run_id=?', (self.run_id,)):
            p = self.root / artifact['relative_path']
            if not p.exists() or digest(p.read_bytes()) != artifact['sha256']:
                issues.append({'reason': 'artifact_hash_mismatch', 'detail': artifact['relative_path']})
        # DOI/title coincidences are flags only, never deduplication keys.
        for field in ['DOI', 'Title']:
            groups = {}
            for r in self.records:
                v = r['values'][field]
                if v:
                    groups.setdefault(v, []).append(r['pmid'])
            self.artifact('Reports', f'suspected_duplicate_{field}.json', [dict(value=v, pmids=ids) for v, ids in groups.items() if len(ids)>1])
        pending = sum(r['fetch_state'] != 'available' for r in self.records)
        available = len(self.records) - pending
        present = sum(r['abstract_state'] == 'available' for r in self.records)
        absent = sum(r['abstract_state'] == 'abstract_absent' for r in self.records)
        counts = dict(official_count=self.official, partition_count=sum(p['expected_count'] for p in self.parts),
            raw_occurrence_count=len(self.occurrences), unique_pmid_count=len(self.pmids),
            duplicate_occurrence_count=len(self.occurrences)-len(self.pmids), metadata_available=available,
            abstract_present=present, abstract_absent=absent, metadata_pending=pending)
        assert available == present + absent
        assert len(self.pmids) == available + pending
        status = 'BLOCKED' if any(i['reason'] == 'single_day_overflow' for i in issues) else 'PARTIAL' if issues else 'COMPLETED'
        self.qc_status = status
        qc = dict(status=status, counts=counts, issues=issues, format_validation_only=True)
        self.artifact('Reports', 'qc.json', qc)
        self.artifact('Reports', 'qc.csv', csv_bytes(issues, ['pmid','reason','detail']), raw=True)
        for issue in issues:
            self.event('partial', entity_id=issue.get('pmid', ''), reason=issue['reason'], detail=issue['detail'])
        return qc, available, 0, pending

    def assign(self):
        mapping = self.store.assign_ids(self.run_id, self.project['project_id'], safe_name(self.project['organ']), self.pmids)
        if len(set(r['paper_id'] for r in mapping.values())) != len(self.pmids):
            raise ValueError('Paper ID mapping not bijective')
        for record in self.records:
            record.update({k: mapping[record['pmid']][k] for k in ['paper_id','paper_uid']})
        self.artifact('Output', 'paper_id_map.csv', csv_bytes(list(mapping.values()), ['pmid','paper_id','paper_uid','first_seen_run_id']), raw=True)
        return mapping, len(self.pmids), 0, 0

    def export(self):
        files, warnings = export_files(self.records, self.config['fields'], self.config['formats'], self.config['csv_bom'])
        # Always retain an internal master with required fields even when export fields are narrow.
        artifacts = [self.artifact('Output', 'internal_master.json', self.records)]
        for name, content in files.items():
            artifacts.append(self.artifact('Output', name, content, raw=True))
        self.artifact('Reports', 'export_warnings.json', warnings)
        manifest = dict(schema_version='1.0', run_id=self.run_id, project_id=self.project['project_id'],
            status=self.qc['status'], record_count=len(self.records), counts=self.qc['counts'],
            artifacts=artifacts, warnings=warnings, source='PubMed', created_at=now(),
            database_path='state.sqlite', downstream_ready=self.qc['status']=='COMPLETED')
        manifest['provenance_artifacts'] = [dict(path=r['relative_path'], sha256=r['sha256'], run_id=r['run_id'], schema_version=r['schema_version'])
            for r in self.store.db.execute('SELECT * FROM artifacts WHERE run_id=?', (self.run_id,))
            if not r['relative_path'].startswith(('Output/', 'Reports/'))]
        validate_manifest(manifest)
        if any(not r.get('paper_id') or not r.get('pmid') for r in self.records):
            raise ValueError('Export record schema missing identifiers')
        self.manifest_path = self.artifact('Output', 'collect_output_manifest.json', manifest)['path']
        prisma = dict(identification={'records_identified': self.official, 'unique_records_retrieved': len(self.pmids)},
            screening=None, eligibility=None, included=None,
            note='Screening, eligibility and inclusion are not implemented; API retries are not literature exclusions.')
        self.artifact('Reports', 'prisma_summary.json', prisma)
        self.artifact('Reports', 'collection_summary.md',
            f'# Collection {self.run_id}\n\nStatus: {self.qc["status"]}\n\n```json\n{dump(self.qc["counts"])}\n```\n\nIssues: {len(self.qc["issues"])}. Screening is not performed.\n', raw=True)
        pending = self.qc['counts']['metadata_pending']
        return manifest, len(self.pmids)-pending, 0, pending

    def audit_reports(self):
        events = [dict(r) for r in self.store.db.execute('SELECT * FROM transition_events WHERE run_id=? ORDER BY rowid', (self.run_id,))]
        steps = [dict(r) for r in self.store.db.execute('SELECT * FROM step_runs WHERE run_id=? ORDER BY rowid', (self.run_id,))]
        self.artifact('Reports', 'transition_log.csv', csv_bytes(events), raw=True)
        self.artifact('Reports', 'stage_counts.csv', csv_bytes(steps), raw=True)
