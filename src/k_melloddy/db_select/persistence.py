import json
import sqlite3
import os
import tempfile
import time
import hashlib
from pathlib import Path
from ..core.storage import digest,dump,immutable_write,now,uid,safe_name
from .schema import validate,RECORD

SCHEMA='''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS runs(run_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, collect_ref TEXT NOT NULL,
 policy_json TEXT NOT NULL, input_json TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS identities(project_id TEXT, paper_id TEXT, pmid TEXT,
 PRIMARY KEY(project_id,paper_id), UNIQUE(project_id,pmid));
CREATE TABLE IF NOT EXISTS revisions(run_id TEXT REFERENCES runs, paper_id TEXT, revision INTEGER,
 record_json TEXT NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(run_id,paper_id,revision));
CREATE TABLE IF NOT EXISTS current_records(run_id TEXT REFERENCES runs,paper_id TEXT,revision INTEGER,
 PRIMARY KEY(run_id,paper_id), FOREIGN KEY(run_id,paper_id,revision) REFERENCES revisions);
CREATE TABLE IF NOT EXISTS events(event_id TEXT PRIMARY KEY,run_id TEXT REFERENCES runs,step_id TEXT,paper_id TEXT,
 phase TEXT, outcome TEXT,reason_code TEXT,details_json TEXT, timestamp TEXT);
CREATE TABLE IF NOT EXISTS datasets(project_id TEXT,dataset_id TEXT,canonical_key TEXT,definition_json TEXT,
 PRIMARY KEY(project_id,dataset_id),UNIQUE(project_id,canonical_key));
CREATE TABLE IF NOT EXISTS mappings(run_id TEXT REFERENCES runs,paper_id TEXT,revision INTEGER,dataset_id TEXT,
 PRIMARY KEY(run_id,paper_id,revision,dataset_id),FOREIGN KEY(run_id,paper_id,revision) REFERENCES revisions);
CREATE TRIGGER IF NOT EXISTS event_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'append-only events'); END;
CREATE TRIGGER IF NOT EXISTS event_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'append-only events'); END;
CREATE TRIGGER IF NOT EXISTS revisions_no_update BEFORE UPDATE ON revisions BEGIN SELECT RAISE(ABORT,'append-only revisions'); END;
CREATE TRIGGER IF NOT EXISTS revisions_no_delete BEFORE DELETE ON revisions BEGIN SELECT RAISE(ABORT,'append-only revisions'); END;
CREATE TABLE IF NOT EXISTS documents(document_id TEXT PRIMARY KEY,run_id TEXT REFERENCES runs,paper_id TEXT,pmid TEXT,
 kind TEXT,content_json TEXT NOT NULL,sha256 TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS documents_no_update BEFORE UPDATE ON documents BEGIN SELECT RAISE(ABORT,'append-only documents'); END;
CREATE TRIGGER IF NOT EXISTS documents_no_delete BEFORE DELETE ON documents BEGIN SELECT RAISE(ABORT,'append-only documents'); END;
CREATE TABLE IF NOT EXISTS projection_checkpoints(run_id TEXT PRIMARY KEY,generation_id TEXT,hashes_json TEXT);
CREATE TABLE IF NOT EXISTS published_exports(snapshot_id TEXT PRIMARY KEY,run_id TEXT,manifest_json TEXT,
 workbook BLOB,screening_json TEXT,evidence_json TEXT,history_json TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS preserved_outputs(sha256 TEXT PRIMARY KEY,path TEXT,content BLOB,created_at TEXT);
CREATE TRIGGER IF NOT EXISTS exports_no_update BEFORE UPDATE ON published_exports BEGIN SELECT RAISE(ABORT,'append-only export snapshots'); END;
CREATE TRIGGER IF NOT EXISTS exports_no_delete BEFORE DELETE ON published_exports BEGIN SELECT RAISE(ABORT,'append-only export snapshots'); END;
'''


def atomic_replace(path,data):
    """Replace a derived view only; scientific source records live in SQLite."""
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    data=data.encode('utf-8') if isinstance(data,str) else data
    if path.exists() and path.read_bytes()==data:return
    fd,temp=tempfile.mkstemp(prefix='.pending-',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        for attempt in range(6):
            try:
                os.replace(temp,path);break
            except PermissionError:
                if attempt==5:raise
                time.sleep(0.025*2**attempt)
    finally:
        if os.path.exists(temp):os.unlink(temp)


def json_chunks(value):
    """Encode the exact dump() format without one giant Unicode/UTF-8 copy."""
    encoder=json.JSONEncoder(ensure_ascii=False,sort_keys=True,indent=2)
    for chunk in encoder.iterencode(value):yield chunk.encode('utf-8')


def json_digest(value):
    result=hashlib.sha256()
    for chunk in json_chunks(value):result.update(chunk)
    return result.hexdigest()


def atomic_json(path,value):
    """Stream a recoverable projection, then atomically publish the complete bytes."""
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='.pending-',suffix='.tmp',dir=path.parent)
    result=hashlib.sha256()
    try:
        with os.fdopen(fd,'wb') as f:
            for chunk in json_chunks(value):f.write(chunk);result.update(chunk)
            f.flush();os.fsync(f.fileno())
        for attempt in range(6):
            try:os.replace(temp,path);break
            except PermissionError:
                if attempt==5:raise
                time.sleep(0.025*2**attempt)
        return result.hexdigest()
    finally:
        if os.path.exists(temp):os.unlink(temp)


class SelectionStore:
    def __init__(self,root):
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.root/'state.sqlite',timeout=30)
        self.db.row_factory=sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.execute('PRAGMA journal_mode=WAL')
    def close(self): self.db.close()
    def artifact(self,relative,value,raw=False):
        data=value if raw else dump(value)
        immutable_write(self.root/relative,data)
        return {'path':relative,'sha256':digest((self.root/relative).read_bytes()),'schema_version':'1.0'}
    def event(self,run,step,paper,phase,outcome,code='',details=None):
        if outcome not in {'forwarded','excluded','pending','fetch_error','started'}: raise ValueError('Invalid audit outcome')
        with self.db:
            self.db.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?)',
                (uid(),run,step,paper,phase,outcome,code,dump(details or {}),now()))
    def create(self,manifest,collect_ref,policy,papers):
        run=uid()
        with self.db:
            for p in papers:
                old=self.db.execute('SELECT pmid FROM identities WHERE project_id=? AND paper_id=?',(manifest['project_id'],p['paper_id'])).fetchone()
                if old and old['pmid']!=p['pmid']: raise ValueError('Immutable paper_id/PMID mapping changed')
                self.db.execute('INSERT OR IGNORE INTO identities VALUES (?,?,?)',(manifest['project_id'],p['paper_id'],p['pmid']))
                actual=self.db.execute('SELECT paper_id FROM identities WHERE project_id=? AND pmid=?',(manifest['project_id'],p['pmid'])).fetchone()
                if actual['paper_id']!=p['paper_id']: raise ValueError('PMID was renumbered')
            self.db.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?)',
                (run,manifest['project_id'],dump(collect_ref),dump(policy),dump(papers),'RUNNING',now()))
        self.artifact(f'Input/{run}/collect_reference.json',collect_ref)
        self.artifact(f'Criteria/{run}/policy_snapshot.json',policy)
        return run
    def run(self,run):
        row=self.db.execute('SELECT * FROM runs WHERE run_id=?',(run,)).fetchone()
        if not row: raise ValueError('Unknown selection run')
        return dict(row)
    def records(self,run):
        rows=self.db.execute('SELECT r.* FROM revisions r JOIN current_records c USING(run_id,paper_id,revision) WHERE run_id=?',(run,)).fetchall()
        result={}
        for row in rows:
            if digest(row['record_json'].encode())!=row['sha256']:raise ValueError('Selection SQLite record hash mismatch')
            if not row['path'].startswith('sqlite:'):
                if digest((self.root/row['path']).read_bytes())!=row['sha256']:raise ValueError('Legacy selection JSON hash mismatch')
            result[row['paper_id']]=json.loads(row['record_json'])
        return result
    def save(self,run,record,phase):
        info=self.run(run); project=info['project_id']; prefix=safe_name(record['organ']).upper()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            old=self.db.execute('SELECT MAX(revision) FROM revisions WHERE run_id=? AND paper_id=?',(run,record['paper_id'])).fetchone()[0] or 0
            record['revision']=old+1
            record['datasets']=list({d['canonical_key']:d for d in record['datasets']}.values())
            for dataset in record['datasets']:
                existing=self.db.execute('SELECT dataset_id FROM datasets WHERE project_id=? AND canonical_key=?',(project,dataset['canonical_key'])).fetchone()
                if existing: dataset['dataset_id']=existing['dataset_id']
                else:
                    n=self.db.execute('SELECT COUNT(*) FROM datasets WHERE project_id=?',(project,)).fetchone()[0]+1
                    dataset['dataset_id']=f'{prefix}-D{n:06d}'
                    self.db.execute('INSERT INTO datasets VALUES (?,?,?,?)',(project,dataset['dataset_id'],dataset['canonical_key'],dump(dataset)))
            validate(record,RECORD)
            relative=f'sqlite:revision/{run}/{record["paper_id"]}/{record["revision"]}'
            content=dump(record)
            self.db.execute('INSERT INTO revisions VALUES (?,?,?,?,?,?,?)',(run,record['paper_id'],record['revision'],content,relative,digest(content.encode()),now()))
            self.db.execute('INSERT OR REPLACE INTO current_records VALUES (?,?,?)',(run,record['paper_id'],record['revision']))
            for d in record['datasets']:
                self.db.execute('INSERT INTO mappings VALUES (?,?,?,?)',(run,record['paper_id'],record['revision'],d['dataset_id']))
            outcome={'confirmed':'forwarded','excluded':'excluded','pending':'pending','fetch_error':'fetch_error'}[record['final']['status']]
            for step in ['2.7','2.10']:
                self.db.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?)',
                    (uid(),run,step,record['paper_id'],phase,outcome,record['final']['code'],dump(record['final']),now()))
            if phase=='revalidation':
                history=self.read_ref(record['revalidation']['history_refs'][-1],run,record)
                self.db.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?)',
                    (uid(),run,'2.9',record['paper_id'],phase,outcome,record['final']['code'],dump(history),now()))
            self.db.commit()
        except BaseException:
            self.db.rollback(); raise
        return record
    def document(self,run,paper,kind,value):
        key=uid();content=dump(value);sha=digest(content.encode())
        with self.db:
            self.db.execute('INSERT INTO documents VALUES (?,?,?,?,?,?,?,?)',
                (key,run,paper['paper_id'],paper['pmid'],kind,content,sha,now()))
        return {'path':'sqlite:document/'+key,'sha256':sha,'schema_version':'1.3'}
    def read_ref(self,ref,run=None,paper=None,kind=None):
        if ref['path'].startswith('sqlite:document/'):
            key=ref['path'].split('/')[-1]
            row=self.db.execute('SELECT * FROM documents WHERE document_id=?',(key,)).fetchone()
            if not row:raise ValueError('Missing SQLite evidence/history document')
            content=row['content_json'].encode()
            if run and (row['run_id']!=run or (paper and (row['paper_id']!=paper['paper_id'] or row['pmid']!=paper['pmid']))):
                raise ValueError('Evidence/history identity mismatch')
        else:
            target=(self.root/ref['path']).resolve()
            if not target.is_relative_to(self.root.resolve()):raise ValueError('Unsafe legacy reference')
            content=target.read_bytes()
        if digest(content)!=ref['sha256']:raise ValueError('Evidence or revalidation history hash mismatch')
        value=json.loads(content)
        # Additive legacy import. Original files, revisions and references stay intact.
        if not ref['path'].startswith('sqlite:') and run and paper and kind:
            key=digest(dump([run,paper['paper_id'],kind,ref['path'],ref['sha256']]).encode())
            with self.db:
                self.db.execute('INSERT OR IGNORE INTO documents VALUES (?,?,?,?,?,?,?,?)',
                    (key,run,paper['paper_id'],paper['pmid'],kind,content.decode(),ref['sha256'],'legacy'))
        return value
    def aggregate(self,run):
        from .metadata import paper_order
        from .prisma import summarize
        info=self.run(run);papers=sorted(json.loads(info['input_json']),key=paper_order)
        records=self.records(run)
        # Import every legacy revision's references, not just the latest decision.
        committed_history=set()
        for row in self.db.execute('SELECT record_json FROM revisions WHERE run_id=? ORDER BY paper_id,revision',(run,)).fetchall():
            r=json.loads(row[0])
            if r.get('evidence_ref'):self.read_ref(r['evidence_ref'],run,r,'evidence')
            for ref in r['revalidation']['history_refs']:
                committed_history.add(ref['path'].split('/')[-1] if ref['path'].startswith('sqlite:') else digest(dump([run,r['paper_id'],'revalidation',ref['path'],ref['sha256']]).encode()))
                history=self.read_ref(ref,run,r,'revalidation')
                if history.get('evidence_ref'):self.read_ref(history['evidence_ref'],run,r,'evidence')
        screening=[];evidence=[];histories=[]
        for p in papers:
            r=records.get(p['paper_id'])
            screening.append(r if r else dict(paper_id=p['paper_id'],pmid=p['pmid'],source_record=p,
                final={'status':'unreviewed','code':'','reason':'Not reviewed'},datasets=[],revalidation={'attempt_count':0,'history_refs':[]}))
            docs=self.db.execute('SELECT * FROM documents WHERE run_id=? AND paper_id=? ORDER BY rowid',(run,p['paper_id'])).fetchall()
            grouped={'evidence':[],'proposal':[],'revalidation':[]}
            for d in docs:
                if digest(d['content_json'].encode())!=d['sha256']:raise ValueError('SQLite document hash mismatch')
                grouped[d['kind']].append(dict(document_id=d['document_id'],sha256=d['sha256'],content=json.loads(d['content_json'])))
            identity={'paper_id':p['paper_id'],'pmid':p['pmid']}
            evidence.append(dict(identity,entries=grouped['evidence'],proposals=grouped['proposal']))
            if grouped['revalidation'] or (r and r['final']['status']=='pending'):
                first=self.db.execute('SELECT record_json FROM revisions WHERE run_id=? AND paper_id=? ORDER BY revision LIMIT 1',(run,p['paper_id'])).fetchone()
                initial=json.loads(first[0]) if first else r
                superseded={x['content']['supersedes_document_id'] for x in grouped['revalidation'] if x['document_id'] in committed_history and x['content'].get('supersedes_document_id')}
                attempts=sorted([x for x in grouped['revalidation'] if x['document_id'] in committed_history and x['document_id'] not in superseded],key=lambda x:(x['content']['attempt_no'],x['document_id']))
                amended=[x for x in attempts if x['content'].get('narrative_amendment')]
                if amended:initial=dict(initial,final=amended[-1]['content']['initial_result'])
                for attempt in attempts:
                    h=attempt['content']
                    access=h.get('access_results')
                    if access is None:
                        prior=self.read_ref(h['evidence_ref'],run,p) if h.get('evidence_ref') else {}
                        access=[{k:e.get(k) for k in ['url','final_url','kind','route','status','http_status','attempt','timestamp','failure_reason']} for e in prior.get('records',[])]
                    # Derived audit fields enrich legacy history without changing its hashed content.
                    attempt['audit']={'paper_id':p['paper_id'],'pmid':p['pmid'],'initial_p_code':initial['final']['code'],
                        'initial_timestamp':initial['provenance']['review_timestamp'],'attempt_no':h['attempt_no'],
                        'attempt_timestamp':h['attempt_timestamp'],'access_results':access,'result':h['result'],
                        'started_at':h.get('started_at'),'ended_at':h.get('ended_at'),
                        'final_reason':h['result']['reason'],'revalidation_completed':h.get('revalidation_completed'),
                        'verification_resolved':h['result']['status'] in {'confirmed','excluded'},
                        'unresolved_reason':h['result']['reason'] if h['result']['status']=='pending' else ''}
                histories.append(dict(identity,initial_result=initial['final'],initial_p_code=initial['final']['code'] if initial['final']['status']=='pending' else None,
                    initial_timestamp=initial['provenance']['review_timestamp'],revalidation_count=r['revalidation']['attempt_count'],
                    latest_result=r['final'],revalidation_completed=bool(attempts) and r.get('processing_state')!='blocked_verification',
                    verification_resolved=r['final']['status'] in {'confirmed','excluded'},
                    unresolved_reason=r['final']['reason'] if r['final']['status']=='pending' else '',
                    attempts=attempts,superseded_attempts=[x for x in grouped['revalidation'] if x['document_id'] in superseded],interrupted_attempts=[x for x in grouped['revalidation'] if x['document_id'] not in committed_history]))
                fields=['campaign_id','status','review_mode','captured_review_sha256','full_text_access','full_text_evidence_url','full_text_reviewed',
                    'dataset_identified','dataset_name','dataset_public','dataset_accessible','dataset_downloadable',
                    'dataset_reusable','license_or_access_constraints','download_url','download_format',
                    'verification_evidence','verification_attempts','unresolved_questions','final_reason']
                histories[-1]['revalidation_attempts']=[dict(
                    attempt=a['content']['attempt_no'],document_id=a['document_id'],sha256=a['sha256'],
                    previous_decision=a['content'].get('previous_result',{}).get('status'),previous_code=a['content'].get('previous_result',{}).get('code'),
                    final_decision=a['content']['result']['status'],final_code=a['content']['result']['code'],
                    **{k:a['content'].get(k) for k in fields}) for a in attempts]
                last=attempts[-1]['content'] if attempts else {}
                histories[-1].update(internal_id=paper_order(p)[1],previous_decision=last.get('previous_result',{}).get('status'),
                    previous_code=last.get('previous_result',{}).get('code'),final_decision=r['final']['status'],final_code=r['final']['code'])
        events=[dict(e) for e in self.db.execute('SELECT * FROM events WHERE run_id=? ORDER BY rowid',(run,))]
        generation=json_digest([run,screening,evidence,histories,events])
        times=[info['created_at']]+[e['timestamp'] for e in events]
        common=dict(schema_version='1.3',run_id=run,project_id=info['project_id'],generation_id=generation,generated_at=max(times))
        def wrap(rows):return dict(common,total_count=len(rows),papers=rows,index={r['paper_id']:{'pmid':r['pmid'],'position':i} for i,r in enumerate(rows)})
        from .revalidator import audit_metrics
        docs={'screening_results.json':dict(wrap(screening),counts=summarize(papers,records)),
              'evidence_log.json':wrap(evidence),'revalidation_history.json':dict(wrap(histories),
                  metrics=audit_metrics(self,run),decision_events=sorted([dict(e,pmid=next(p['pmid'] for p in papers if p['paper_id']==e['paper_id'])) for e in events if e['step_id'] in {'2.7','2.9'}],key=lambda e:paper_order(e)))}
        # All files share generation_id. A partial multi-file publish is detected
        # against this DB checkpoint and repaired from committed SQLite on resume.
        hashes={name:atomic_json(self.root/'JSON'/name,value) for name,value in docs.items()}
        with self.db:self.db.execute('INSERT OR REPLACE INTO projection_checkpoints VALUES (?,?,?)',(run,generation,dump(hashes)))
        return docs
    def verify_aggregate(self,run):
        row=self.db.execute('SELECT * FROM projection_checkpoints WHERE run_id=?',(run,)).fetchone()
        if not row:raise ValueError('No cumulative JSON checkpoint')
        docs={}
        for name,sha in json.loads(row['hashes_json']).items():
            content=(self.root/'JSON'/name).read_bytes()
            if digest(content)!=sha:raise ValueError('Cumulative JSON checkpoint mismatch; regenerate from SQLite')
            d=json.loads(content)
            if d['run_id']!=run or d['generation_id']!=row['generation_id']:raise ValueError('Mixed cumulative JSON generations')
            docs[name]=d
        return docs
    def set_status(self,run,status):
        with self.db: self.db.execute('UPDATE runs SET status=? WHERE run_id=?',(status,run))
