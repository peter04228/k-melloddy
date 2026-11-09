from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return uuid.uuid4().hex


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_name(value):
    value = re.sub(r'[^\w-]+', '_', value, flags=re.UNICODE).strip('_')
    if not value or value.upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(10)), *(f'LPT{i}' for i in range(10))}:
        raise ValueError('Invalid or reserved project path name')
    return value[:100]


def immutable_write(path, data):
    """Publish a complete file without overwriting any existing content."""
    path = Path(path)
    data = data.encode('utf-8') if isinstance(data, str) else data
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f'Immutable artifact collision: {path}')
        return
    fd, temp = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        # A hard link publishes atomically and fails if another writer won.
        try:
            source = '\\\\?\\' + str(Path(temp).resolve()) if os.name == 'nt' else temp
            target = '\\\\?\\' + str(path.resolve()) if os.name == 'nt' else path
            os.link(source, target)
        except FileExistsError:
            if path.read_bytes() != data:
                raise ValueError(f'Immutable artifact collision: {path}')
    finally:
        os.unlink(temp)


SCHEMA = '''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS projects(project_id TEXT PRIMARY KEY, organ TEXT NOT NULL,
 name TEXT NOT NULL, created_at TEXT NOT NULL, config_version TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS search_runs(search_run_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects,
 query_text TEXT NOT NULL, query_hash TEXT NOT NULL, search_date TEXT NOT NULL,
 count_reported INTEGER, translated_query TEXT, status TEXT NOT NULL, config_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS partitions(partition_id TEXT, search_run_id TEXT REFERENCES search_runs,
 parent_id TEXT, query_filter TEXT, expected_count INTEGER, retrieved_count INTEGER DEFAULT 0,
 status TEXT, PRIMARY KEY(search_run_id, partition_id));
CREATE TABLE IF NOT EXISTS pmid_occurrences(search_run_id TEXT, partition_id TEXT, page_no INTEGER,
 pmid TEXT NOT NULL, occurrence_no INTEGER, PRIMARY KEY(search_run_id,partition_id,page_no,occurrence_no),
 FOREIGN KEY(search_run_id,partition_id) REFERENCES partitions(search_run_id,partition_id));
CREATE TABLE IF NOT EXISTS papers(paper_uid TEXT PRIMARY KEY, project_id TEXT REFERENCES projects,
 paper_id TEXT NOT NULL, pmid TEXT NOT NULL, first_seen_run_id TEXT REFERENCES search_runs, created_at TEXT,
 UNIQUE(project_id,paper_id), UNIQUE(project_id,pmid));
CREATE TABLE IF NOT EXISTS paper_metadata(source_run_id TEXT REFERENCES search_runs, pmid TEXT,
 metadata_json TEXT, raw_xml_path TEXT, abstract_state TEXT, fetch_state TEXT,
 PRIMARY KEY(source_run_id,pmid));
CREATE TABLE IF NOT EXISTS step_runs(step_run_id TEXT PRIMARY KEY, run_id TEXT REFERENCES search_runs,
 step_id TEXT, status TEXT, started_at TEXT, ended_at TEXT, input_count INTEGER,
 output_count INTEGER, removed_count INTEGER, pending_count INTEGER, metric_unit TEXT, ids_hash TEXT);
CREATE TABLE IF NOT EXISTS transition_events(event_id TEXT PRIMARY KEY, run_id TEXT REFERENCES search_runs,
 search_run_id TEXT, step_id TEXT, entity_type TEXT, entity_id TEXT, from_state TEXT, to_state TEXT,
 reason_code TEXT, reason_detail TEXT, timestamp TEXT, source TEXT, software_version TEXT,
 prompt_version TEXT, details_json TEXT);
CREATE TABLE IF NOT EXISTS artifacts(artifact_id TEXT PRIMARY KEY, run_id TEXT REFERENCES search_runs,
 step_id TEXT, relative_path TEXT UNIQUE, sha256 TEXT, schema_version TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS checkpoints(run_id TEXT REFERENCES search_runs, cache_key TEXT,
 relative_path TEXT, sha256 TEXT, PRIMARY KEY(run_id,cache_key));
CREATE TRIGGER IF NOT EXISTS immutable_events_update BEFORE UPDATE ON transition_events BEGIN SELECT RAISE(ABORT,'append-only ledger'); END;
CREATE TRIGGER IF NOT EXISTS immutable_events_delete BEFORE DELETE ON transition_events BEGIN SELECT RAISE(ABORT,'append-only ledger'); END;
CREATE TRIGGER IF NOT EXISTS immutable_steps_update BEFORE UPDATE ON step_runs BEGIN SELECT RAISE(ABORT,'append-only steps'); END;
CREATE TRIGGER IF NOT EXISTS immutable_steps_delete BEFORE DELETE ON step_runs BEGIN SELECT RAISE(ABORT,'append-only steps'); END;
'''


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.db = sqlite3.connect(self.root / 'state.sqlite', timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.execute('PRAGMA journal_mode=WAL')

    def close(self):
        self.db.close()

    def event(self, run, step, state, *, entity_type='unique_pmid', entity_id='', reason='', detail='', counts=None, previous='pending', ids=()):
        details = dict(counts or {})
        details['ids_hash'] = digest(dump(sorted(ids)).encode())
        with self.db:
            self.db.execute('INSERT INTO transition_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (uid(), run, run, step, entity_type, entity_id, previous, state, reason, detail,
                 now(), 'k_melloddy', '0.1.0', None, dump(details)))

    def artifact(self, run, step, relative, data):
        immutable_write(self.root / relative, data)
        sha = digest((self.root / relative).read_bytes())
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO artifacts VALUES (?,?,?,?,?,?,?)',
                (uid(), run, step, relative, sha, '1.0', now()))
        return {'path': relative, 'sha256': sha, 'run_id': run, 'schema_version': '1.0'}

    def cached(self, run, key):
        row = self.db.execute('SELECT * FROM checkpoints WHERE run_id=? AND cache_key=?', (run, key)).fetchone()
        if row:
            data = (self.root / row['relative_path']).read_bytes()
            if digest(data) != row['sha256']:
                raise ValueError('Artifact hash mismatch: ' + row['relative_path'])
            return data, row['relative_path']
        return None

    def checkpoint(self, run, key, relative):
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO checkpoints VALUES (?,?,?,?)',
                (run, key, relative, digest((self.root / relative).read_bytes())))

    def assign_ids(self, run, project, prefix, pmids):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            existing = {r['pmid']: dict(r) for r in self.db.execute('SELECT * FROM papers WHERE project_id=?', (project,))}
            n = len(existing)
            for pmid in sorted(set(pmids), key=int):
                if pmid not in existing:
                    n += 1
                    paper_id = f'Liver-{n:05d}' if prefix.lower() == 'liver' else f'{prefix.upper()}-P{n:06d}'
                    row = (uid(), project, paper_id, pmid, run, now())
                    self.db.execute('INSERT INTO papers VALUES (?,?,?,?,?,?)', row)
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        wanted = set(pmids)
        return {r['pmid']: dict(r) for r in self.db.execute('SELECT * FROM papers WHERE project_id=?', (project,)) if r['pmid'] in wanted}
