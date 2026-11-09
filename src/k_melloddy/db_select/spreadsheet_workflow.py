"""An isolated, hash-frozen spreadsheet input for the evidence-reviewed workflow."""
import argparse
import json
import re
import csv
from pathlib import Path
from openpyxl import load_workbook
from ..core.storage import digest,dump,immutable_write
from .full_workflow import FullWorkflow
from .policy import load_policy


def read_workbook(path,organ='Liver'):
    path=Path(path).resolve();sha=digest(path.read_bytes())
    if path.suffix.lower()=='.csv':return read_csv(path,organ)
    book=load_workbook(path,read_only=True,data_only=False)
    try:
        if len(book.worksheets)!=1:raise ValueError('Expected exactly one input sheet')
        sheet=book.worksheets[0];rows=sheet.iter_rows(values_only=True);headers=list(next(rows))
        required={'Internal_Number','PMID','Title','Abstract','DOI','PMCID'}
        if len(set(headers))!=len(headers) or not required<=set(headers):raise ValueError('Duplicate or missing input columns')
        papers=[];ids=set();pmids=set()
        for row_number,row in enumerate(rows,2):
            if not any(x is not None for x in row):continue
            raw=dict(zip(headers,row))
            if any(isinstance(x,str) and x.startswith('=') for x in row):raise ValueError('Formula in source row')
            number=str(raw['Internal_Number']).strip();pmid=str(raw['PMID']).strip()
            if not re.fullmatch(r'[1-9]\d*',number) or not re.fullmatch(r'[1-9]\d*',pmid):raise ValueError('Invalid source identity')
            if number in ids or pmid in pmids:raise ValueError('Duplicate source number/PMID')
            ids.add(number);pmids.add(pmid)
            def value(key):return str(raw[key]).strip() if raw.get(key) is not None else ''
            values={k:value(k) for k in ['Title','Abstract','DOI','PMCID','Authors','Keywords','Language']}
            values.update(PMID=pmid,Journal=value('Full_Journal_Name') or value('Journal/Book'),
                **{'Publication Date':value('Publication Year'),'Publication Type':value('Publication_Types'),
                   'PubMed URL':value('PubMed_URL')})
            papers.append(dict(paper_id=f'{organ}-{int(number):05d}',pmid=pmid,values=values,
                source_run_id='xlsx:'+sha,fetch_state='supplied_workbook',abstract_state='available' if values['Abstract'] else 'abstract_absent',
                source_workbook={'sha256':sha,'sheet':sheet.title,'row':row_number,'internal_number':number,'raw_values':raw}))
        if not papers:raise ValueError('Empty spreadsheet')
        papers.sort(key=lambda p:int(p['source_workbook']['internal_number']))
        manifest=dict(project_id='xlsx-'+sha,run_id='xlsx:'+sha,source_kind='user_spreadsheet',record_count=len(papers))
        ref=dict(path=str(path),sha256=sha,run_id=manifest['run_id'],schema_version='xlsx-input-v1',source_kind='user_spreadsheet',
                 identity_namespace='xlsx-'+sha,selection={'source_count':len(papers),'order':'asc'})
        return manifest,papers,ref
    finally:book.close()


def read_csv(path,organ='Liver'):
    path=Path(path).resolve();sha=digest(path.read_bytes());papers=[];ids=set();pmids=set()
    with path.open(encoding='utf-8-sig',newline='') as handle:
        reader=csv.DictReader(handle)
        required={'순번','PMID','TI (Title)','AB (Abstract)','DOI','PMCID'}
        if not reader.fieldnames or len(set(reader.fieldnames))!=len(reader.fieldnames) or not required<=set(reader.fieldnames):raise ValueError('Invalid CSV headers')
        for row_number,raw in enumerate(reader,2):
            if None in raw or any(v is None for v in raw.values()):raise ValueError('Invalid CSV row width')
            number=raw['순번'].strip();pmid=raw['PMID'].strip()
            if not re.fullmatch(r'[1-9]\d*',number) or not re.fullmatch(r'[1-9]\d*',pmid):raise ValueError('Invalid source identity')
            if number in ids or pmid in pmids:raise ValueError('Duplicate source number/PMID')
            ids.add(number);pmids.add(pmid)
            abstract='\n'.join(raw.get(k,'').strip() for k in ['AB (Abstract)','AB 추가 2','AB 추가 3'] if raw.get(k,'').strip())
            values=dict(PMID=pmid,Title=raw['TI (Title)'].strip(),Abstract=abstract,DOI=raw['DOI'].strip(),PMCID=raw['PMCID'].strip(),Authors='',Journal=raw.get('저널',''))
            values.update({'Publication Date':raw.get('출판연도',''),'PubMed URL':raw.get('PubMed URL','')})
            papers.append(dict(paper_id=f'{organ}-{int(number):05d}',pmid=pmid,values=values,source_run_id='csv:'+sha,
                fetch_state='supplied_csv',abstract_state='available' if abstract else 'abstract_absent',
                source_workbook=dict(sha256=sha,sheet='CSV',row=row_number,internal_number=number,raw_values=raw)))
    if not papers:raise ValueError('Empty CSV')
    papers.sort(key=lambda p:int(p['source_workbook']['internal_number']))
    manifest=dict(project_id='csv-'+sha,run_id='csv:'+sha,source_kind='user_csv',record_count=len(papers))
    ref=dict(path=str(path),sha256=sha,run_id=manifest['run_id'],schema_version='csv-input-v1',source_kind='user_csv',identity_namespace='csv-'+sha,selection={'source_count':len(papers),'order':'asc'})
    return manifest,papers,ref


class SpreadsheetWorkflow(FullWorkflow):
    def __init__(self,*args,source,**kwargs):
        self.source=Path(source);super().__init__(*args,**kwargs)
    def source_scope(self,parent):
        scope=read_workbook(self.source,self.organ)
        if parent!=scope[2]['sha256']:raise ValueError('Input workbook changed')
        return scope
    def comparison_records(self,parent):return {}


def prepare(source,root,organ):
    manifest,papers,ref=read_workbook(source,organ)
    root=Path(root);policy=load_policy('config/db_select',organ)
    immutable_write(root/('Input/source'+Path(source).suffix.lower()),Path(source).read_bytes())
    immutable_write(root/'Input/source_reference.json',dump(ref))
    immutable_write(root/'Input/normalized_papers.json',dump(papers))
    review=root/'Input/session_review.json'
    if not review.exists():immutable_write(review,dump({'policy_sha256':policy['sha256'],'papers':{}}))
    return {'source_sha256':ref['sha256'],'paper_count':len(papers),'missing_abstract_count':sum(not p['values']['Abstract'] for p in papers)}


def publish_outputs(root, destination):
    """Publish completed projections plus each round's stage-level PRISMA."""
    root, destination = Path(root), Path(destination)
    for folder in ['Output', 'JSON', 'PRISMA']:
        base = root / folder
        for path in base.rglob('*'):
            if path.is_file() and not path.name.startswith('~$'):
                relative = path.relative_to(base)
                target = destination / relative if folder == 'Output' else destination / folder / relative
                immutable_write(target, path.read_bytes())
    rounds = root / 'Runs' / 'review' / 'PRISMA'
    for path in rounds.rglob('*.json'):
        immutable_write(destination / 'PRISMA' / path.relative_to(rounds), path.read_bytes())
    immutable_write(destination / 'source_reference.json', (root / 'Input/source_reference.json').read_bytes())


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--organ',default='Liver')
    parser.add_argument('--prepare-only',action='store_true');parser.add_argument('--render',action='store_true')
    parser.add_argument('--publish',type=Path)
    args=parser.parse_args();info=prepare(args.source,args.root,args.organ)
    if args.prepare_only:print(dump(info));return
    engine=SpreadsheetWorkflow(args.root,organ=args.organ,source=args.source,review_file=args.root/'Input/session_review.json',log=lambda s:print(s,flush=True))
    try:
        result=engine.execute(info['source_sha256'],'review',render=args.render)
        if args.publish and result.get('counts',{}).get('status')=='COMPLETED':
            publish_outputs(args.root, args.publish)
        print(dump(result))
    finally:engine.close()


if __name__=='__main__':main()
