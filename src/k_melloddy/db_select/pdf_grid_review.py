"""Bounded, explicitly selected PDF grid cells; never infer merged headers or drug columns."""
import copy
import json

from ..core.storage import digest,dump
from .form_material_capture import checked_bytes


def selected_pdf_grids(bundle, selections):
    import fitz
    result=copy.deepcopy(bundle)
    for selection in selections:
        parent=next(e for e in bundle['records'] if e['evidence_id']==selection['parent_evidence_id'])
        if parent.get('kind')!='file' or parent.get('status')!='accessible':raise ValueError('PDF grid needs actual public file')
        raw=checked_bytes(parent)
        if not raw.startswith(b'%PDF-'):raise ValueError('Not PDF bytes')
        with fitz.open(stream=raw,filetype='pdf') as document:
            page=selection['page'];table=selection['table']
            if type(page)!=int or not 0<=page<len(document)<=64:raise ValueError('PDF page limit')
            tables=document[page].find_tables().tables
            if type(table)!=int or not 0<=table<len(tables):raise ValueError('PDF table index')
            grid=tables[table].extract()
        if not grid or len(grid)>5000 or max(map(len,grid))>100:raise ValueError('PDF grid size limit')
        header_cells=selection['header_cells'];columns=[];indexes=[]
        for row,col in header_cells:
            if type(row)!=int or type(col)!=int or not 0<=row<selection['data_row_start'] or not 0<=col<len(grid[row]):
                raise ValueError('Header cell outside captured grid')
            value=grid[row][col]
            if not isinstance(value,str) or not value.strip():raise ValueError('Missing actual PDF header')
            columns.append(value.strip());indexes.append(col)
        if len(columns)!=len(set(columns)) or len(indexes)!=len(set(indexes)):raise ValueError('Ambiguous PDF grid columns')
        if columns!=selection['expected_columns']:raise ValueError('PDF headers changed')
        start=selection['data_row_start'];end=selection['data_row_end']
        if type(start)!=int or type(end)!=int or not 0<=start<end<=len(grid):raise ValueError('PDF row bounds')
        rows=[]
        for row in grid[start:end]:
            if any(i>=len(row) or not isinstance(row[i],str) or not row[i].strip() for i in indexes):
                raise ValueError('Missing PDF data cell; explicit review required')
            rows.append([row[i].strip() for i in indexes])
        caption=selection['caption_quote']
        if not caption or caption not in parent['text']:raise ValueError('Unobserved PDF caption')
        e=copy.deepcopy(parent)
        e.update(evidence_id='pdf-grid-'+digest(dump(selection).encode())[:24],
                 parent_evidence_id=parent['evidence_id'],level='sample_structure',columns=columns,
                 pdf_grid_selection=copy.deepcopy(selection),pdf_grid_rows=rows,
                 text=caption+'\n'+json.dumps({'columns':columns,'rows':rows},ensure_ascii=False),
                 document_text=parent['text'],request_performed=False,transport='pdf_grid_cells',
                 downloaded_full_dataset=False,
                 interpretation_note='Explicit PDF cells only; original units, NA and significance marks retained. No synthetic drug column or clinical toxicity label.')
        if not any(old['evidence_id']==e['evidence_id'] for old in result['records']):result['records'].append(e)
    return result
