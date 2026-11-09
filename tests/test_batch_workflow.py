import csv
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from k_melloddy.core.storage import digest, dump, immutable_write
from k_melloddy.db_select.batch_workflow import prepare_batches, run_batches
from k_melloddy.db_select.spreadsheet_workflow import read_workbook


def source_csv(path, count):
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['순번', 'PMID', 'TI (Title)', 'AB (Abstract)', 'DOI', 'PMCID'])
        for number in range(1, count + 1):
            writer.writerow([number, 100000 + number, f'Synthetic title {number}', 'Synthetic, abstract\ncontinued', '', ''])
    return path


class FakeExportEngine:
    """Stub an already-validated exporter; these bytes test publication, not Excel format."""
    calls = []

    def __init__(self, root, **kwargs):
        self.root = Path(root)
        self.calls.append(self.root.name)

    def records(self, papers):
        return [{'paper_id':p['paper_id'], 'pmid':p['pmid']} for p in papers]

    def execute(self, parent, session, render=False):
        papers = json.loads((self.root / 'Input/normalized_papers.json').read_text(encoding='utf-8'))
        ref = json.loads((self.root / 'Input/source_reference.json').read_text(encoding='utf-8'))
        review = json.loads((self.root / 'Input/session_review.json').read_text(encoding='utf-8'))
        count = len(papers)
        counts = dict(status='COMPLETED', input_count=count, N_all=count, N_confirmed=0,
                      N_excluded=count, N_pending=0, incomplete_count=0, fetch_error_count=0,
                      unreviewed_count=0, revalidation_due_count=0, confirmed_dataset_count=0)
        publication = 'f' * 32
        snapshot = self.root / 'Runs/review/published' / publication
        contents = {'Output/DB_Select_Final.xlsx':b'synthetic validated-exporter fixture'}
        for name in ['screening_results', 'evidence_log', 'revalidation_history']:
            contents[f'JSON/{name}.json'] = dump(dict(papers=self.records(papers), counts=counts)).encode()
        for i in range(1, 13):
            contents[f'PRISMA/2.{i}.json'] = dump(dict(input_count=count, excluded_count=count)).encode()
        for name, raw in contents.items():
            immutable_write(snapshot / name, raw)
        manifest = dict(status='COMPLETED', run_id='synthetic-run', record_count=count, counts=counts,
                        policy_sha256=review['policy_sha256'], collect_ref=ref,
                        artifacts=[dict(path=k, sha256=digest(v)) for k,v in contents.items() if not k.startswith('PRISMA/')],
                        prisma_artifacts=[dict(path=k, sha256=digest(v)) for k,v in contents.items() if k.startswith('PRISMA/')])
        immutable_write(snapshot / 'Output/select_output_manifest.json', dump(manifest))
        return dict(counts=counts, run_id='synthetic-run', publication_id=publication)

    def close(self):
        pass


def test_1500_boundary_tail_global_numbers_and_immutable_source(tmp_path):
    source = source_csv(tmp_path / 'input.csv', 1501)
    original = source.read_bytes()
    root = tmp_path / 'run'
    plan = prepare_batches(source, root)
    assert plan['batch_count'] == 2
    assert [(b['start'],b['end'],b['paper_count']) for b in plan['batches']] == [(1,1500,1500),(1501,1501,1)]
    assert [b['workbook'] for b in plan['batches']] == ['DB_Select_00001-01500.xlsx','DB_Select_01501-01501.xlsx']
    _, papers, _ = read_workbook(root / plan['batches'][1]['root'] / 'Input/selection.csv')
    assert papers[0]['paper_id'] == 'Liver-01501' and papers[0]['pmid'] == '101501'
    assert papers[0]['values']['Abstract'] == 'Synthetic, abstract\ncontinued'
    assert source.read_bytes() == (root/'Input/source.csv').read_bytes() == original
    assert prepare_batches(source, root) == plan
    with pytest.raises(ValueError, match='Immutable artifact collision'):
        prepare_batches(source, root, batch_size=1000)


@pytest.mark.parametrize('problem', ['duplicate_pmid','gap'])
def test_whole_source_validation_before_creating_batches(tmp_path, problem):
    source = source_csv(tmp_path/'input.csv', 4)
    with source.open(encoding='utf-8-sig',newline='') as handle:
        rows = list(csv.reader(handle))
    if problem == 'duplicate_pmid': rows[4][1] = rows[1][1]
    else: rows[4][0] = '5'
    with source.open('w',encoding='utf-8-sig',newline='') as handle:
        csv.writer(handle).writerows(rows)
    with pytest.raises(ValueError):
        prepare_batches(source,tmp_path/'run',batch_size=2)
    assert not (tmp_path/'run/Input/batch_plan.json').exists()


def test_unanswered_review_blocks_next_batch_and_claims_no_completed_papers(tmp_path):
    class Awaiting(FakeExportEngine):
        calls = []
        def execute(self, *args, **kwargs):
            return dict(status='AWAITING_REVIEW',saved_count=1,terminal_count=0,
                        terminal_outcomes={},request='synthetic-request')
    result = run_batches(source_csv(tmp_path/'input.csv',3),tmp_path/'run',tmp_path/'output',batch_size=2,engine_factory=Awaiting)
    assert Awaiting.calls == ['00001-00002']
    assert result['status'] == 'PARTIAL' and result['review_state'] == 'AWAITING_REVIEW'
    assert result['completed_batches'] == result['completed_papers'] == 0
    assert result['saved_in_current_batch'] == 1
    assert result['processed_papers'] == result['terminal_in_current_batch'] == 0
    assert not list((tmp_path/'output').glob('*.xlsx'))


def test_range_publications_and_completed_resume_do_not_rereview(tmp_path):
    source = source_csv(tmp_path/'input.csv',3)
    root,output = tmp_path/'run',tmp_path/'output'
    FakeExportEngine.calls = []
    result = run_batches(source,root,output,batch_size=2,engine_factory=FakeExportEngine)
    assert FakeExportEngine.calls == ['00001-00002','00003-00003']
    assert result['status'] == 'COMPLETED' and result['completed_papers'] == 3
    assert result['completed_batch_counts'] == dict(N_confirmed=0,N_excluded=3,N_pending=0)
    assert sorted(p.name for p in output.glob('*.xlsx')) == ['DB_Select_00001-00002.xlsx','DB_Select_00003-00003.xlsx']
    assert not (output/'DB_Select_Final.xlsx').exists()
    snapshots = {p:p.read_bytes() for p in output.rglob('*') if p.is_file()}
    def must_not_review(*args,**kwargs):
        raise AssertionError('Completed batches must not re-run')
    again = run_batches(source,root,output,batch_size=2,engine_factory=must_not_review)
    assert again == result
    assert all(p.read_bytes()==raw for p,raw in snapshots.items())


def test_failed_publication_resumes_staged_bytes_without_new_export(tmp_path):
    source = source_csv(tmp_path/'input.csv',2)
    root,output = tmp_path/'run',tmp_path/'output'
    with patch('k_melloddy.db_select.batch_workflow.publish_batch',side_effect=OSError('file in use')):
        with pytest.raises(OSError,match='file in use'):
            run_batches(source,root,output,batch_size=2,engine_factory=FakeExportEngine)
    publication = root/'Batches/00001-00002/Publication'
    assert (publication/'staged.json').exists() and not (publication/'completed.json').exists()
    def must_not_export(*args,**kwargs):
        raise AssertionError('Staged publication must not regenerate workbook')
    result = run_batches(source,root,output,batch_size=2,engine_factory=must_not_export)
    assert result['status']=='COMPLETED'
    assert (output/'DB_Select_00001-00002.xlsx').read_bytes()==(publication/'files/DB_Select_00001-00002.xlsx').read_bytes()


def test_mismatched_pmid_blocks_publication_and_next_batch(tmp_path):
    class WrongIdentity(FakeExportEngine):
        calls = []
        def records(self,papers):
            result = super().records(papers)
            result[0]['pmid']='9999999'
            return result
    with pytest.raises(ValueError,match='identities'):
        run_batches(source_csv(tmp_path/'input.csv',3),tmp_path/'run',tmp_path/'output',batch_size=2,engine_factory=WrongIdentity)
    assert WrongIdentity.calls == ['00001-00002']
    assert not list((tmp_path/'output').glob('*.xlsx'))


def test_changed_publication_bytes_never_overwrite_previous_results(tmp_path):
    source = source_csv(tmp_path/'input.csv',1)
    root,output=tmp_path/'run',tmp_path/'output'
    run_batches(source,root,output,batch_size=2,engine_factory=FakeExportEngine)
    workbook=output/'DB_Select_00001-00001.xlsx'
    workbook.write_bytes(b'user-modified-fixture')
    with pytest.raises(ValueError,match='Immutable artifact collision'):
        run_batches(source,root,output,batch_size=2,engine_factory=FakeExportEngine)
    assert workbook.read_bytes()==b'user-modified-fixture'
