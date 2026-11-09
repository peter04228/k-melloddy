import pytest
from openpyxl import Workbook
from k_melloddy.db_select.spreadsheet_workflow import read_workbook,prepare


def fixture(path,rows):
    w=Workbook();s=w.active
    s.append(['Internal_Number','PMID','Title','Abstract','DOI','PMCID'])
    for row in rows:s.append(row)
    w.save(path);w.close()


def test_source_numbers_raw_values_and_missing_abstract_preserved(tmp_path):
    path=tmp_path/'source.xlsx';fixture(path,[[2,'200','  Title  ','Body','',''],[1,'100','First',None,'','']])
    before=path.read_bytes();manifest,papers,ref=read_workbook(path)
    assert [p['paper_id'] for p in papers]==['Liver-00001','Liver-00002']
    assert papers[1]['source_workbook']['raw_values']['Title']=='  Title  '
    assert papers[0]['values']['Abstract']=='' and papers[0]['abstract_state']=='abstract_absent'
    assert ref['source_kind']=='user_spreadsheet' and manifest['project_id'].startswith('xlsx-')
    assert path.read_bytes()==before
    root=tmp_path/'batch';prepare(path,root,'Liver')
    fixture(path,[[1,'300','Changed','Body','','']])
    with pytest.raises((ValueError,FileExistsError)):prepare(path,root,'Liver')


@pytest.mark.parametrize('rows',[
    [[1,'100','A','B','',''],[1,'200','C','D','','']],
    [[1,'100','A','B','',''],[2,'100','C','D','','']],
    [[1,'bad','A','B','','']],
    [[1,'100','=1+1','B','','']],
])
def test_reject_invalid_source(tmp_path,rows):
    path=tmp_path/'source.xlsx';fixture(path,rows)
    with pytest.raises(ValueError):read_workbook(path)
