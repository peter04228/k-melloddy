import csv
import io
import json
import re
from ..core.storage import dump


def csv_bytes(rows, columns=None, bom=False):
    out = io.StringIO(newline='')
    columns = columns or (list(rows[0]) if rows else [])
    w = csv.DictWriter(out, fieldnames=columns, extrasaction='ignore')
    w.writeheader()
    for row in rows:
        w.writerow({k: json.dumps(v, ensure_ascii=False, sort_keys=True) if isinstance(v, (dict, list)) else v for k, v in row.items()})
    return out.getvalue().encode('utf-8-sig' if bom else 'utf-8')


def export_files(records, fields, formats, bom):
    columns = list(dict.fromkeys(['paper_id', 'PMID'] + fields))
    rows = [{**r['values'], **{k: r.get(k) for k in columns if k not in r['values']}} for r in records]
    rows = [{k: r.get(k) for k in columns} for r in rows]
    files, warnings = {}, []
    if 'csv' in formats:
        files['pubmed_master.csv'] = csv_bytes(rows, columns, bom)
    if 'json' in formats:
        files['pubmed_master.json'] = dump(rows).encode()
    if 'txt' in formats:
        files['pubmed_master.txt'] = '\n\n'.join(f"{r['paper_id']} | PMID:{r['pmid']}\n{r['values']['Title']}\n{r['values']['Abstract']}" for r in records).encode()
    if 'xlsx' in formats:
        from openpyxl import Workbook
        book = Workbook(write_only=True)
        sheet = book.create_sheet('Literature')
        sheet.append(columns)
        overflow = []
        from openpyxl.cell import WriteOnlyCell
        for row in rows:
            cells = []
            for k in columns:
                value = row[k]
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, ensure_ascii=False, sort_keys=True)
                if isinstance(value, str):
                    if len(value) > 32767 or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', value):
                        overflow.append({'PMID': row['PMID'], 'field': k, 'original': value})
                        warnings.append(f"{row['PMID']}:{k}: XLSX representation shortened/sanitized; original in xlsx_overflow.json")
                        value = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', value)[:32767]
                    cell = WriteOnlyCell(sheet, value=value)
                    cell.data_type = 's'  # Never interpret research text as an Excel formula.
                    cells.append(cell)
                else:
                    cells.append(value)
            sheet.append(cells)
        out = io.BytesIO()
        book.save(out)
        files['pubmed_master.xlsx'] = out.getvalue()
        if overflow:
            files['xlsx_overflow.json'] = dump(overflow).encode()
    return files, warnings


def validate_manifest(manifest):
    required = {'schema_version', 'run_id', 'project_id', 'status', 'record_count', 'artifacts', 'counts'}
    if not required <= manifest.keys() or manifest['schema_version'] != '1.0':
        raise ValueError('Invalid collection manifest schema')
    if manifest['status'] not in {'COMPLETED', 'PARTIAL', 'BLOCKED'}:
        raise ValueError('Invalid collection status')
    if type(manifest['record_count']) is not int or manifest['record_count'] < 0:
        raise ValueError('Invalid manifest record_count')
    for a in manifest['artifacts']:
        if not {'path', 'sha256', 'run_id', 'schema_version'} <= a.keys() or not re.fullmatch('[0-9a-f]{64}', a['sha256']):
            raise ValueError('Invalid artifact descriptor')
        if a['run_id'] != manifest['run_id'] or a['path'].startswith(('/', '\\')) or '..' in a['path'].replace('\\', '/').split('/'):
            raise ValueError('Invalid manifest artifact path/run')
