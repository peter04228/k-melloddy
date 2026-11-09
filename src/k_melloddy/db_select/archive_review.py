"""Explicit reviewer-selected archive tables; bounded in-memory inspection only."""
import base64
import copy
import io
import json
import zipfile
import xml.etree.ElementTree as ET
from ..core.storage import digest, dump


def selected_docx_tables(bundle, selections):
    """Inspect an exact table without merging unrelated tables or inventing columns."""
    result=copy.deepcopy(bundle)
    for selection in selections:
        parent=next(e for e in bundle['records'] if e['evidence_id']==selection['parent_evidence_id'])
        if not parent.get('complete_body') or parent['status']!='accessible' or parent['kind']!='file':
            raise ValueError('DOCX selection requires complete accessible file')
        data=base64.b64decode(parent['body_sample_b64'],validate=True)
        if digest(data)!=parent['payload_sha256'] or len(data)>16*1024*1024:raise ValueError('DOCX payload changed or oversized')
        if parent.get('cloud_checksum',{}).get('verified') is False:
            raise ValueError('DOCX selection rejected: official cloud checksum failed')
        members=selection.get('members',[])
        if not isinstance(members,list) or len(members)>3:raise ValueError('DOCX archive depth exceeds limit')
        chain=[]
        for name in members:
            if not isinstance(name,str) or not name:raise ValueError('Invalid DOCX archive member')
            with zipfile.ZipFile(io.BytesIO(data)) as outer:
                if len(outer.infolist())>1000:raise ValueError('DOCX archive member limit')
                matches=[m for m in outer.infolist() if m.filename==name]
                if len(matches)!=1 or matches[0].is_dir() or matches[0].file_size>16*1024*1024:
                    raise ValueError('Missing, duplicate or oversized DOCX archive member')
                data=outer.read(matches[0])
            chain.append(dict(member=name,sha256=digest(data),bytes=len(data)))
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            member=archive.getinfo('word/document.xml')
            if member.file_size>8*1024*1024:raise ValueError('DOCX expansion limit')
            xml=archive.read(member)
        if b'<!ENTITY' in xml.upper() or b'<!DOCTYPE' in xml.upper():raise ValueError('Unsafe DOCX XML')
        ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        index=selection['table_index']
        tables=ET.fromstring(xml).findall('.//w:tbl',ns)
        if type(index)!=int or not 0<=index<len(tables):raise ValueError('Invalid DOCX table index')
        table=tables[index]
        selected_rows=table.findall('w:tr',ns)
        end=selection.get('row_end',len(selected_rows))
        if type(end)!=int or not 2<=end<=len(selected_rows):raise ValueError('Invalid DOCX row range')
        selected_rows=selected_rows[:end]
        if any(r.findall('.//w:gridSpan',ns) or r.findall('.//w:vMerge',ns) for r in selected_rows):raise ValueError('Merged table needs separate interpretation')
        rows=[[''.join(c.itertext()) for c in r.findall('w:tc',ns)] for r in selected_rows]
        if len(rows)<2 or not rows[0] or any(not c.strip() for c in rows[0]) or len(set(rows[0]))!=len(rows[0]):raise ValueError('Invalid DOCX headers')
        if any(len(r)!=len(rows[0]) for r in rows):raise ValueError('Irregular DOCX rows')
        record=copy.deepcopy(parent)
        record.update(evidence_id='docx-table-'+digest(dump(selection).encode())[:24],
            parent_evidence_id=parent['evidence_id'],docx_selection=selection,request_performed=False,
            transport='document_table',columns=rows[0],level='sample_structure',
            text=dump({'selection':selection,'sample':rows[:6]}),downloaded_full_dataset=False,
            interpretation_note='Selected table from captured DOCX; parent URL/HTTP metadata retained; no new request or inferred columns')
        if members:
            record.update(archive_members=chain,format='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                          body_sample_b64=base64.b64encode(data).decode(),payload_sha256=digest(data),bytes_observed=len(data),
                          interpretation_note='Selected DOCX table inside captured archive; parent URL/HTTP metadata and archive checksum refer to original request; no new request or inferred columns')
        if not any(e['evidence_id']==record['evidence_id'] for e in result['records']):result['records'].append(record)
    return result


def selected_tables(bundle, selections):
    result=copy.deepcopy(bundle)
    originals={e['evidence_id']:e for e in bundle['records']}
    for selection in selections:
        parent=originals[selection['parent_evidence_id']]
        if parent.get('cloud_checksum',{}).get('verified') is False:
            raise ValueError('Archive selection rejected: official cloud checksum failed')
        if (not parent.get('complete_body') or parent.get('http_status')!=200
                or parent['kind']!='file' or parent['status']=='access_restricted'):
            raise ValueError('Archive selection requires complete public file bytes')
        data=base64.b64decode(parent['body_sample_b64'],validate=True)
        if digest(data)!=parent['payload_sha256']:raise ValueError('Archive payload changed')
        members=selection['members']
        if not isinstance(members,list) or not 0<=len(members)<=3:raise ValueError('Archive depth exceeds limit')
        if not members and len(data)>16*1024*1024:raise ValueError('Direct workbook size limit')
        chain=[]
        for name in members:
            if not isinstance(name,str) or not name or len(data)>32*1024*1024:raise ValueError('Invalid archive selection')
            # Inspect magic bytes, never trust a misleading .tgz extension.
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if len(archive.infolist())>1000:raise ValueError('Archive member limit')
                matches=[m for m in archive.infolist() if m.filename==name]
                if len(matches)!=1 or matches[0].is_dir() or matches[0].file_size>16*1024*1024:
                    raise ValueError('Missing, duplicate or oversized archive member')
                data=archive.read(matches[0])
                chain.append({'member':name,'sha256':digest(data),'bytes':len(data)})
        from openpyxl import load_workbook
        row_number=selection['header_row']
        if type(row_number)!=int or not 1<=row_number<=20:raise ValueError('Invalid header row')
        if data.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'):
            import xlrd
            try:book=xlrd.open_workbook(file_contents=data,on_demand=True)
            except xlrd.biffh.XLRDError as exc:raise ValueError('Unreadable archive XLS: '+str(exc)) from exc
            try:
                if not 1<=book.nsheets<=64:raise ValueError('XLS worksheet limit')
                if selection['sheet'] not in book.sheet_names():raise ValueError('Missing selected XLS worksheet')
                sheet=book.sheet_by_name(selection['sheet'])
                if sheet.ncols>256:raise ValueError('Workbook column limit')
                rows=[sheet.row_values(i) for i in range(row_number-1,min(sheet.nrows,row_number+100))]
            finally:book.release_resources()
            file_format='application/vnd.ms-excel'
        else:
            with zipfile.ZipFile(io.BytesIO(data)) as book_archive:
                if sum(m.file_size for m in book_archive.infolist())>64*1024*1024:raise ValueError('Workbook expansion limit')
            book=load_workbook(io.BytesIO(data),read_only=True,data_only=False)
            try:
                sheet=book[selection['sheet']]
                if sheet.max_column>256:raise ValueError('Workbook column limit')
                rows=list(sheet.iter_rows(min_row=row_number,max_row=row_number+100,max_col=256,values_only=True))
            finally:book.close()
            file_format='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        while rows and rows[0] and rows[0][-1] in (None,''):
            if any(r[-1] not in (None,'') for r in rows):raise ValueError('Unlabelled populated column')
            rows=[r[:-1] for r in rows]
        if len(rows)<2 or not rows[0] or any(not isinstance(x,str) or not x.strip() for x in rows[0]):
            raise ValueError('Missing observed table headers')
        columns=list(rows[0])
        if len(columns)!=len(set(columns)):raise ValueError('Duplicate table headers')
        if any(isinstance(c,str) and c.startswith('=') for row in rows for c in row):raise ValueError('Formula cells require separate review')
        text=dump({'archive_members':chain,'sheet':selection['sheet'],'header_row':row_number,'sample':rows[:6]})
        e=copy.deepcopy(parent)
        e.update(evidence_id='archive-'+digest(dump(selection).encode())[:24],
                 transport='archive_member' if members else 'workbook_sheet',parent_evidence_id=parent['evidence_id'],archive_members=chain,
                 archive_selection=selection,request_performed=False,
                 status='accessible',failure_reason='',text=text,columns=columns,level='sample_structure',
                 format=file_format,
                 body_sample_b64=base64.b64encode(data).decode(),payload_sha256=digest(data),bytes_observed=len(data),
                 complete_body=True,downloaded_full_dataset=False,
                 interpretation_note='Derived from captured archive bytes; HTTP metadata and URL refer to parent request, not another request')
        if not members:
            e.update(workbook_inspection={'sheet':selection['sheet'],'header_row':row_number},
                     workbook_preview={'sheet':selection['sheet'],'rows':rows[:6]},
                     interpretation_note='Selected sheet from captured complete workbook; parent URL/HTTP metadata retained; no new request or inferred columns')
        if not any(x['evidence_id']==e['evidence_id'] for x in result['records']):result['records'].append(e)
    return result
