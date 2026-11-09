import csv
import pytest
from k_melloddy.db_select.policy import load_policy,tiab_missing,review_instructions
from k_melloddy.db_select.spreadsheet_workflow import read_workbook,prepare

@pytest.mark.parametrize('title,abstract,missing',[('T','',True),('','A',True),('','',True),('T','A',False),('T','  ',True),('  ','A',True),(None,'A',True),('T',None,True)])
def test_presence(title,abstract,missing):
    p=load_policy('config/db_select','Liver')
    assert bool(tiab_missing({'values':{'Title':title,'Abstract':abstract}},p))==missing

def test_all_criteria_reach_review_and_pending_tasks():
    p=load_policy('config/db_select','Liver')
    for code in ['P01','P02','P03','P04']:
        prompt=review_instructions(p,2,code)
        assert any('Korean' in rule for rule in prompt['rules'])
        assert prompt['pending_tasks']==p['organ']['pending_revalidation'][code]
        for field in ['keywords','synonyms','endpoints','applicable','not_applicable','ambiguous','inclusion_requirements',*[f'E{i:02}_examples' for i in range(1,9)],*[f'P{i:02}_examples' for i in range(1,5)]]:
            assert prompt['organ_criteria'][field]==p['organ'][field]

def test_csv_mapping_and_immutable_input(tmp_path):
    path=tmp_path/'input.csv'
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['순번','PMID','TI (Title)','AB (Abstract)','AB 추가 2','DOI','PMCID'])
        w.writerow([1,123,'Title','','','',''])
    before=path.read_bytes();_,papers,ref=read_workbook(path)
    assert papers[0]['paper_id']=='Liver-00001' and papers[0]['values']['Abstract']==''
    assert ref['source_kind']=='user_csv'
    prepare(path,tmp_path/'batch','Liver')
    assert (tmp_path/'batch/Input/source.csv').read_bytes()==before==path.read_bytes()


def test_source_absence_excel_does_not_claim_step_one_review():
    from k_melloddy.db_select.excel_export import paper_row
    paper={'paper_id':'Liver-00009','pmid':'27842778','values':{'Title':'Title only','Abstract':''}}
    record={'tiab':{'decision':'excluded','availability':'absent'},
            'final':{'status':'excluded','code':'TIAB_ABSENT','reason':'TI/AB 부재: Abstract'}}
    row=paper_row(paper,record)
    assert row[7]=='미실시 (TI/AB 부재)'
    assert row[8]=='제외'
    assert 'TI/AB 부재' in row[14]
    assert row[15]=='TI/AB 존재 확인'
