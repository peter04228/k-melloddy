"""v1.3: a single fixed-template workbook from committed SQLite results."""
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from openpyxl import load_workbook
from ..core.storage import dump,digest,now
from .metadata import paper_order
from .prisma import summarize,write_prisma
from .persistence import atomic_replace
from .data_observations import screening_data_cells

SHEETS=['01_논문스크리닝','02_확정DB','03_확정논문','04_제외논문','05_보류논문']
LABELS={'confirmed':'포함','excluded':'제외','pending':'보류','fetch_error':'미확정','unreviewed':'미검수'}


def template_contract():
    path=Path(__file__).resolve().parents[3]/'config/db_select/excel_template.json'
    path=Path(os.environ.get('KM_SELECT_EXCEL_TEMPLATE',str(path)))
    contract=json.loads(path.read_text(encoding='utf-8'))
    if [len(s['headers']) for s in contract['sheets']]!=[16,15] or [s['header_row'] for s in contract['sheets']]!=[4,2]:
        raise ValueError('Invalid fixed template contract')
    return contract,digest(path.read_bytes())


def authors(value):
    if isinstance(value,str):return value
    def leaf(node):return (node.get('text') or '')+''.join(leaf(c)+(c.get('tail') or '') for c in node.get('children',[]))
    names=[]
    for a in value or []:
        if not isinstance(a,dict):names.append(str(a));continue
        fields={c.get('tag'):leaf(c) for c in a.get('children',[])}
        names.append(fields.get('CollectiveName') or ' '.join(filter(None,[fields.get('LastName'),fields.get('ForeName') or fields.get('Initials')])) or leaf(a))
    return '; '.join(names)


def cell(value,paper_id,field):
    if value is None:return None
    if isinstance(value,(dict,list)):value=json.dumps(value,ensure_ascii=False)
    if isinstance(value,str):
        if len(value.encode('utf-16-le'))//2>32767 or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]',value):
            return f'[Excel 표시 한도: 원문은 JSON/screening_results.json → {paper_id} → {field} 참조]'
        if re.match(r'^\d{4}-\d{2}-\d{2}',value) or value.startswith('='):return json.dumps(value,ensure_ascii=False)
    return value


def paper_row(p,r):
    r=r or {};v={**p['values'],**r.get('verified_metadata',{})};f=r.get('final',{'status':'unreviewed','code':'','reason':'검수 대기'})
    tiab=r.get('tiab',{});ft=r.get('fulltext',{});ds=r.get('datasets',[]);sources=r.get('source_databases',[])
    levels={'sample_structure':'실제 응답·표본 구조 확인','metadata_structure':'공식 구조 메타데이터 확인','full_file':'전체 파일 확인'}
    reason='Abstract 부재' if f['code']=='ABSTRACT_ABSENT' else f['code']
    if reason:reason+=': '+f['reason']
    review=[]
    if tiab:review.append('TI/AB 존재 확인' if f['code'] in {'TIAB_ABSENT','ABSTRACT_ABSENT'} else 'TIAB')
    if ft.get('status')=='reviewed':review.append('Full Text')
    if ft.get('supplementary_urls'):review.append('부록 경로 조사')
    if ft.get('repository_urls'):review.append('Repository 경로 조사')
    if ds:review.append('파일/API 구조 확인')
    values=[paper_order(p)[1],p['pmid'],authors(v.get('Authors',[])),v.get('DOI',''),v.get('PMCID',''),v['Title'],v['Abstract'],
        '미실시 (TI/AB 부재)' if f['code'] in {'TIAB_ABSENT','ABSTRACT_ABSENT'} else '1차 보류' if tiab.get('decision')=='pending_relevance' else '후보' if tiab.get('decision')=='candidate' else '비후보' if tiab.get('decision') in {'E01','E02','excluded'} else '',
        LABELS[f['status']],*screening_data_cells(r),reason,f['reason'],'; '.join(review)]
    fields=['paper_id','pmid','source_record.values.Authors','source_record.values.DOI','source_record.values.PMCID','source_record.values.Title','source_record.values.Abstract',
        'tiab','final','data_observations','data_observations','data_observations','data_observations','final','final.reason','fulltext']
    return [cell(value,p['paper_id'],field) for value,field in zip(values,fields)]


def workbook_payload(papers,records,contract):
    papers=[dict(p,values={**p['values'],**records.get(p['paper_id'],{}).get('verified_metadata',{})}) for p in papers]
    papers=sorted(papers,key=paper_order);rows=[paper_row(p,records.get(p['paper_id'])) for p in papers]
    datasets={}
    for p in papers:
        r=records.get(p['paper_id'],{})
        if r.get('final',{}).get('status')!='confirmed':continue
        for d in r['datasets']:
            if d['dataset_id'] not in datasets:datasets[d['dataset_id']]=dict(d,papers=[])
            datasets[d['dataset_id']]['papers'].append(p)
    dbrows=[]
    for key,d in sorted(datasets.items(),key=lambda x:int(x[0].rsplit('-D',1)[1])):
        linked=d['papers'];pmids='; '.join(p['pmid'] for p in linked);numbers='; '.join(str(paper_order(p)[1]) for p in linked)
        join=lambda field:'; '.join(dict.fromkeys(p['values'].get(field,'') for p in linked if p['values'].get(field)))
        level={'sample_structure':'표본 응답·구조 확인','metadata_structure':'공식 구조 메타데이터 확인','full_file':'전체 파일 확인'}[d['verification_level']]
        values=[int(key.rsplit('-D',1)[1]),paper_order(linked[0])[1] if len(linked)==1 else numbers,
            '; '.join(dict.fromkeys(authors(p['values'].get('Authors',[])) for p in linked)),join('DOI'),pmids,join('Title'),
            '검증된 공개 파일/API',level,d['direct_url'],d['name'],d['file_format'],d['compound_count'],d['feature_count'],
            d['independence_reason'],'; '.join(dict.fromkeys([d['drug_identifier'],d['endpoint'],d['value_field']]))]
        dbrows.append([cell(v,linked[0]['paper_id'],'datasets') for v in values])
    sheetrows=[rows,dbrows]+[[r for r in rows if r[8]==status] for status in ['포함','제외','보류']]
    return [dict(contract['sheets'][1 if name==SHEETS[1] else 0],name=name,rows=values) for name,values in zip(SHEETS,sheetrows)],datasets


def verify_workbook(path,sheets,papers,records,summary):
    wb=load_workbook(path,read_only=False,data_only=False)
    try:
        if wb.sheetnames!=SHEETS:raise ValueError('Final Excel must contain exactly five ordered sheets')
        for expected in sheets:
            s=wb[expected['name']];h=expected['header_row'];n=len(expected['headers'])
            if s.max_column!=n or [s.cell(h,c).value for c in range(1,n+1)]!=expected['headers']:raise ValueError('Template header/column mismatch')
            actual=[[s.cell(row,col).value for col in range(1,n+1)] for row in range(h+1,s.max_row+1)]
            norm=lambda row:['' if v is None else v for v in row]
            if [norm(r) for r in actual]!=[norm(r) for r in expected['rows']]:raise ValueError('Excel/SQLite row or field mismatch')
        allrows=sheets[0]['rows'];dbrows=sheets[1]['rows'];keys=[(r[0],r[1]) for r in allrows]
        if len(keys)!=len(papers) or len(set(keys))!=len(keys) or len({r[1] for r in allrows})!=len(keys):raise ValueError('Missing/duplicate original IDs')
        if [len(s['rows']) for s in sheets[2:]]!=[summary[k] for k in ['N_confirmed','N_excluded','N_pending']]:raise ValueError('Excel/PRISMA final counts mismatch')
        if len(dbrows)!=summary['confirmed_dataset_count']:raise ValueError('Dataset count mismatch')
        dbpmids={p.strip() for row in dbrows for p in row[4].split(';')}
        if any(row[1] not in dbpmids for row in sheets[2]['rows']):raise ValueError('Included paper missing dataset link')
        if len(allrows)!=sum(len(s['rows']) for s in sheets[2:])+summary['incomplete_count']:raise ValueError('Final partition mismatch')
    finally:wb.close()


def export(store,run,policy,papers,records,snapshot,render=False):
    papers=json.loads(store.run(run)['input_json']);records=store.records(run)
    if any(r.get('workflow_version')=='2.0' for r in records.values()):
        if len(records)!=len(papers) or any(r['final']['status'] not in {'confirmed','excluded','pending'} for r in records.values()):
            raise ValueError('Every scoped paper must have a final included/excluded/pending record')
    cumulative=store.aggregate(run);summary=summarize(papers,records)
    if cumulative['screening_results.json']['counts']!=summary:raise ValueError('SQLite/JSON counts mismatch')
    for p in papers:
        r=records.get(p['paper_id'])
        if r and r['final']['status']=='pending':
            history=next((x for x in cumulative['revalidation_history.json']['papers'] if x['paper_id']==p['paper_id']),None)
            if not history or len(history['attempts'])!=r['revalidation']['attempt_count']:raise ValueError('Pending history mismatch')
    contract,template_sha=template_contract();sheets,datasets=workbook_payload(papers,records,contract)
    for sheet in sheets:
        sheet['title']=f"K-MELLODDY {policy['organ']['organ']} — {sheet['name']}"
    dependency_root=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node'
    node=Path(os.environ.get('KM_ARTIFACT_NODE',str(dependency_root/'bin/node.exe')));modules=Path(os.environ.get('KM_ARTIFACT_MODULES',str(dependency_root/'node_modules')))
    if not node.exists() or not (modules/'@oai/artifact-tool').exists():raise RuntimeError('Configure artifact-tool Node runtime for final Excel')
    build=store.root/'.build';build.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=build) as temporary:
        stage=Path(temporary);payload=stage/'payload.json'
        payload.write_text(dump(dict(sheets=sheets,output_dir=str(stage.resolve()),render=render,summary=summary)),encoding='utf-8')
        result=subprocess.run([str(node),str(Path(__file__).with_name('workbooks.mjs')),str(payload.resolve()),str(modules.resolve())],capture_output=True,text=True,encoding='utf-8',timeout=180)
        if result.returncode:raise RuntimeError('Workbook export failed: '+result.stderr[-1500:])
        path=stage/'DB_Select_Final.xlsx';verify_workbook(path,sheets,papers,records,summary);data=path.read_bytes()
        if render:
            for p in stage.glob('*.png'):atomic_replace(store.root/'Output/previews'/p.name,p.read_bytes())
    for p in papers:store.event(run,'2.12',p['paper_id'],'export','forwarded',details={'snapshot_id':snapshot})
    cumulative=store.aggregate(run);final_summary,prisma_refs=write_prisma(store,run,policy,papers,records,snapshot)
    if any(final_summary[k]!=summary[k] for k in summary):raise ValueError('Final PRISMA changed during export')
    artifacts=[dict(path='Output/DB_Select_Final.xlsx',sha256=digest(data),schema_version='1.3',run_id=run)]
    artifacts.extend(dict(path='JSON/'+name,sha256=digest(dump(value).encode()),schema_version='1.3',run_id=run) for name,value in cumulative.items())
    manifest=dict(schema_version='1.3',run_id=run,snapshot_id=snapshot,generation_id=cumulative['screening_results.json']['generation_id'],
        collect_ref=json.loads(store.run(run)['collect_ref']),policy_sha256=policy['sha256'],template_sha256=template_sha,
        status=summary['status'],record_count=len(papers),counts=summary,artifacts=artifacts,prisma_artifacts=prisma_refs,
        datasets=[dict(d,papers=[{'paper_id':p['paper_id'],'pmid':p['pmid']} for p in d['papers']]) for d in datasets.values()],
        downstream_ready=summary['status']=='COMPLETED' and json.loads(store.run(run)['collect_ref']).get('selection',{}).get('collect_downstream_ready',True),dataset_unit='dataset')
    with store.db:
        for name in ['DB_Select_Final.xlsx','select_output_manifest.json']:
            old=store.root/'Output'/name
            if old.exists():
                content=old.read_bytes();store.db.execute('INSERT OR IGNORE INTO preserved_outputs VALUES (?,?,?,?)',(digest(content),str(old),content,now()))
        store.db.execute('INSERT INTO published_exports VALUES (?,?,?,?,?,?,?,?)',
            (snapshot,run,dump(manifest),data,*[dump(cumulative[k]) for k in ['screening_results.json','evidence_log.json','revalidation_history.json']],now()))
    atomic_replace(store.root/'Output/DB_Select_Final.xlsx',data)
    atomic_replace(store.root/'Output/select_output_manifest.json',dump(manifest))
    return {'path':'Output/select_output_manifest.json','sha256':digest(dump(manifest).encode())}
