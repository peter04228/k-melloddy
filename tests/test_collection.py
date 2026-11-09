import csv
import io
import json
import sqlite3
from pathlib import Path

import pytest
import yaml

from k_melloddy.core.storage import digest, immutable_write
from k_melloddy.db_collect.config import init_project, validate
from k_melloddy.db_collect.engine import Collector
from k_melloddy.db_collect.fake import FakeClient
from k_melloddy.db_collect.metadata import parse_metadata


def setup(tmp_path, client, config=None):
    root = init_project(tmp_path, 'Heart')
    (root / 'Input/query.txt').write_text('(heart[MeSH Terms]) AND toxicity\n', encoding='utf-8')
    if config:
        p = root / 'Input/config.yaml'
        c = yaml.safe_load(p.read_text())
        c.update(config)
        p.write_text(yaml.safe_dump(c), encoding='utf-8')
    return Collector(root, client)


@pytest.mark.parametrize('count', [0, 1, 10000, 10001, 25000])
def test_end_to_end_boundaries(tmp_path, count):
    c = setup(tmp_path, FakeClient(count))
    try:
        r = c.run()
        assert r['status'] == 'COMPLETED'
        assert r['counts']['unique_pmid_count'] == count
        assert r['counts']['metadata_available'] == count
        steps = c.store.db.execute('SELECT * FROM step_runs').fetchall()
        assert len(steps) == 12
        assert all(s['input_count'] == s['output_count'] + s['removed_count'] + s['pending_count'] for s in steps)
        assert all(s['input_count'] == 0 for s in steps[:4])
        manifest = json.loads((c.root / r['manifest']).read_text())
        for a in manifest['artifacts']:
            assert digest((c.root / a['path']).read_bytes()) == a['sha256']
        if count > 10000:
            parts = c.store.db.execute('SELECT * FROM partitions WHERE parent_id IS NOT NULL').fetchall()
            assert len(parts) > 1
    finally:
        c.close()


def test_resume_network_failure_and_preserve_snapshot(tmp_path):
    client = FakeClient(5, fail_fetch_once=True)
    c = setup(tmp_path, client, {'batch_size': 2})
    try:
        first = c.run()
        assert first['status'] == 'PARTIAL'
        original = {str(p): digest(p.read_bytes()) for p in c.root.rglob('*') if p.is_file() and p.suffix in {'.json','.xml','.csv'}}
        before = len([x for x in client.calls if x[0] == 'fetch'])
        second = c.run(resume=first['run_id'])
        assert second['status'] == 'COMPLETED'
        assert len([x for x in client.calls if x[0] == 'fetch']) == before + 1
        assert all(digest(Path(p).read_bytes()) == sha for p, sha in original.items())
        assert c.store.db.execute('SELECT COUNT(*) FROM papers').fetchone()[0] == 5
    finally:
        c.close()


def test_repeated_query_new_query_stable_ids(tmp_path):
    c = setup(tmp_path, FakeClient(3))
    try:
        a = c.run()
        ids = dict(c.store.db.execute('SELECT pmid,paper_id FROM papers'))
        b = c.run()
        assert a['run_id'] != b['run_id']
        (c.root / 'Input/query.txt').write_text('changed query', encoding='utf-8')
        c.client = FakeClient(4)
        d = c.run()
        new = dict(c.store.db.execute('SELECT pmid,paper_id FROM papers'))
        assert all(new[p] == n for p,n in ids.items())
        assert new['4'] == 'HEART-P000004'
        assert len({a['run_id'],b['run_id'],d['run_id']}) == 3
    finally:
        c.close()


@pytest.mark.parametrize('fault', ['duplicate','missing','overflow'])
def test_bad_snapshots_never_complete(tmp_path, fault):
    client = FakeClient(10001 if fault == 'overflow' else 7, duplicate=fault=='duplicate', missing=fault=='missing', same_day=fault=='overflow')
    c = setup(tmp_path, client)
    try:
        r = c.run()
        assert r['status'] != 'COMPLETED'
        if fault == 'duplicate':
            assert r['counts']['raw_occurrence_count'] == r['counts']['unique_pmid_count'] + r['counts']['duplicate_occurrence_count']
        if fault == 'missing':
            assert r['counts']['metadata_pending'] == 7
    finally:
        c.close()


def test_immutable_files_and_ledger(tmp_path):
    p = tmp_path/'immutable.txt'
    immutable_write(p, 'original')
    with pytest.raises(ValueError):
        immutable_write(p, 'replacement')
    c = setup(tmp_path/'p', FakeClient(1))
    try:
        c.run()
        with pytest.raises(sqlite3.IntegrityError):
            c.store.db.execute('DELETE FROM transition_events')
        c.store.db.rollback()
        with pytest.raises(ValueError):
            init_project(tmp_path/'p', 'Heart')
    finally:
        c.close()


def test_hash_corruption_resume_blocked(tmp_path):
    c = setup(tmp_path, FakeClient(1))
    try:
        r = c.run(search_only=True)
        path = c.store.db.execute('SELECT relative_path FROM checkpoints').fetchone()[0]
        (c.root/path).write_text('corrupted')
        with pytest.raises(ValueError, match='hash mismatch'):
            c.run(resume=r['run_id'])
        assert c.status()[0]['status'] == 'PARTIAL'
    finally:
        c.close()


def test_export_replay_without_network(tmp_path):
    c = setup(tmp_path, FakeClient(3))
    try:
        r = c.run()
        replay = c.run(resume=r['run_id'], export_only=True)
        assert replay['counts'] == r['counts']
        reports = list((c.root/'Reports'/r['run_id']).glob('*/prisma_summary.json'))
        assert len(reports) == 2
        assert json.loads(reports[0].read_text()) == json.loads(reports[1].read_text())
    finally:
        c.close()


def test_config_and_paths(tmp_path):
    with pytest.raises(ValueError):
        validate({'date_start':'2020-01-01'})
    with pytest.raises(ValueError):
        validate({'page_size':10001})
    with pytest.raises(ValueError):
        init_project(tmp_path,'CON')
    root = init_project(tmp_path,'Heart/a')
    with pytest.raises(ValueError, match='collision'):
        init_project(tmp_path,'Heart?a',reuse=True)
    assert root.name == 'DB_Collect'


def test_xml_structured_missing_abstract_and_export_formats(tmp_path):
    c = setup(tmp_path, FakeClient(3), {'formats':['csv','xlsx','json','txt']})
    try:
        r = c.run()
        assert r['counts']['abstract_absent'] == 1
        manifest = json.loads((c.root/r['manifest']).read_text())
        csvpath = next(a['path'] for a in manifest['artifacts'] if a['path'].endswith('.csv'))
        data = list(csv.DictReader(io.StringIO((c.root/csvpath).read_text(encoding='utf-8-sig'))))
        assert '\n' in data[0]['Abstract'] and 'METHODS:' in data[0]['Abstract']
        from openpyxl import load_workbook
        xlsx = next(a['path'] for a in manifest['artifacts'] if a['path'].endswith('.xlsx'))
        book = load_workbook(c.root/xlsx)
        assert book.active.max_row == 4
        book.close()
    finally:
        c.close()


def test_malformed_xml_is_rejected():
    with pytest.raises(Exception):
        parse_metadata(b'<PubmedArticleSet>', [])
    with pytest.raises(ValueError):
        parse_metadata(b'<!ENTITY bad "x"><PubmedArticleSet/>', [])


def test_liver_five_digit_ids_and_select_handoff(tmp_path):
    from k_melloddy.db_select.metadata import load_collect,paper_order
    root=init_project(tmp_path,'Liver')
    (root/'Input/query.txt').write_text('SYNTHETIC',encoding='utf-8')
    c=Collector(root,FakeClient(3))
    try:
        first=c.run()
        _,papers,_=load_collect(root/first['manifest'],root)
        assert [p['paper_id'] for p in papers]==['Liver-00001','Liver-00002','Liver-00003']
        second=c.run(resume=first['run_id'],export_only=True)
        _,again,_=load_collect(root/second['manifest'],root)
        assert [p['paper_id'] for p in again]==[p['paper_id'] for p in papers]
        assert paper_order({'paper_id':'Liver-10000'})==('Liver',10000)
        assert paper_order({'paper_id':'LIVER-P000001'})==('LIVER',1)
    finally:c.close()


def test_compact_current_output_and_dated_folder(tmp_path):
    c=setup(tmp_path,FakeClient(3))
    try:
        first=c.run();oldpath=c.root/first['manifest'];old=oldpath.read_bytes()
        (c.root/'Input/fields.yaml').write_text('fields: [PMID, Title, Abstract]',encoding='utf-8')
        second=c.run(resume=first['run_id'],export_only=True,current_output=True)
        manifest=json.loads((c.root/second['manifest']).read_text())
        path=next(a['path'] for a in manifest['artifacts'] if a['path'].endswith('pubmed_master.csv'))
        assert Path(path).parts[1].startswith('Heart_')
        assert Path(path).parent!=Path(first['manifest']).parent
        rows=list(csv.DictReader(io.StringIO((c.root/path).read_text(encoding='utf-8-sig'))))
        assert list(rows[0])==['paper_id','PMID','Title','Abstract']
        assert len(rows)==3 and rows[0]['paper_id']=='HEART-P000001'
        assert oldpath.read_bytes()==old
    finally:c.close()


def test_future_stages_are_explicit():
    from k_melloddy.db_download import download
    from k_melloddy.db_preprocessing import preprocess
    for operation in [download,preprocess]:
        with pytest.raises(NotImplementedError):
            operation({})
