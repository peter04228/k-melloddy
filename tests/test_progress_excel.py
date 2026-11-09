"""Projection transaction tests; fake bytes here do not certify Excel formatting."""
import copy
import json
from unittest.mock import patch

import pytest

from k_melloddy.core.storage import dump,immutable_write
from k_melloddy.db_select.progress_excel import export_progress,terminal_records,ProgressWorkbookError


def fixture(tmp_path):
    papers=[dict(paper_id=f'Liver-{i:05}',pmid=str(i),values=dict(Title='Synthetic title',Abstract='Synthetic abstract'),
                 source_workbook={'internal_number':str(i)}) for i in range(1,4)]
    records={p['paper_id']:dict(paper_id=p['paper_id'],pmid=p['pmid'],revision=1,workflow_version='2.0',
                initial_review_valid=True,processing_state='reviewed',datasets=[],
                final={'status':'excluded','code':'E01','reason':'Synthetic exclusion'},
                tiab={'decision':'E01'},revalidation={'terminal':True,'auto_retry':False,'attempt_count':0}) for p in papers}
    class Store:
        root=tmp_path
        def records(self,run):return copy.deepcopy(self.data)
        def run(self,run):return {'collect_ref':dump({'sha256':'synthetic-source'})}
        def artifact(self,path,value):immutable_write(self.root/path,dump(value))
    store=Store();store.data={papers[0]['paper_id']:records[papers[0]['paper_id']]}
    return store,papers,records,{'sha256':'policy','organ':{'organ':'Liver'}},tmp_path/'output/In_Progress/DB_Select_00001-00003.xlsx'


def test_incremental_projection_contains_only_terminal_verdicts_and_is_idempotent(tmp_path):
    store,papers,records,policy,target=fixture(tmp_path)
    seen=[]
    def render(root,sheets,summary,scope,saved,visual=False):
        seen.append(copy.deepcopy(sheets))
        assert summary['N_all']==len(saved)
        assert len(sheets)==5 and [len(x['headers']) for x in sheets]==[16,15,16,16,16]
        return dump(sheets).encode()
    with patch('k_melloddy.db_select.progress_excel.render_workbook',side_effect=render) as renderer:
        first=export_progress(store,'run',policy,papers,target)
        assert first['processed_papers']==1 and first['counts']['incomplete_count']==2
        assert seen[-1][0]['rows'][1][8]=='미검수'
        assert export_progress(store,'run',policy,papers,target)==first and renderer.call_count==1
        store.data[papers[1]['paper_id']]=records[papers[1]['paper_id']]
        second=export_progress(store,'run',policy,papers,target)
        assert second['processed_papers']==2 and second['counts']['N_excluded']==2
        assert seen[-1][0]['rows'][0]==seen[0][0]['rows'][0]
        assert first['revisions'][0]==second['revisions'][0]


def test_locked_workbook_retries_cached_projection_without_rereview(tmp_path):
    store,papers,records,policy,target=fixture(tmp_path)
    with patch('k_melloddy.db_select.progress_excel.render_workbook',return_value=b'synthetic projection') as render:
        with patch('k_melloddy.db_select.progress_excel._publish',side_effect=ProgressWorkbookError('locked')):
            with pytest.raises(ProgressWorkbookError):export_progress(store,'run',policy,papers,target)
        assert not target.exists() and len(store.data)==1
        result=export_progress(store,'run',policy,papers,target)
        assert result['processed_papers']==1 and render.call_count==1
        assert target.read_bytes()==b'synthetic projection'


def test_crash_after_excel_replace_repairs_pointer_and_protects_user_edits(tmp_path):
    store,papers,records,policy,target=fixture(tmp_path)
    with patch('k_melloddy.db_select.progress_excel.render_workbook',return_value=b'synthetic projection') as render:
        result=export_progress(store,'run',policy,papers,target)
        target.with_suffix('.progress.json').unlink()  # Simulate crash before pointer write.
        assert export_progress(store,'run',policy,papers,target)==result
        assert render.call_count==1
        target.write_bytes(b'user edit')
        with pytest.raises(ProgressWorkbookError,match='untracked'):export_progress(store,'run',policy,papers,target)
        assert target.read_bytes()==b'user edit'


def test_nonterminal_pending_is_not_a_final_excel_verdict_and_gap_is_rejected(tmp_path):
    store,papers,records,policy,target=fixture(tmp_path)
    r=copy.deepcopy(records[papers[1]['paper_id']]);r['final']['status']='pending'
    r['revalidation'].update(terminal=False,auto_retry=True);store.data[r['paper_id']]=r
    assert list(terminal_records(papers,store.data))==[papers[0]['paper_id']]
    r['revalidation'].update(terminal=True,auto_retry=False);r['pmid']='999'
    with pytest.raises(ProgressWorkbookError,match='identity'):terminal_records(papers,store.data)
    with pytest.raises(ProgressWorkbookError,match='prefix'):terminal_records(papers,{papers[2]['paper_id']:records[papers[2]['paper_id']]})
