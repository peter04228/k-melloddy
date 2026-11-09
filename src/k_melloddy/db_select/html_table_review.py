"""Explicit tables from complete identity-verified article HTML; no requests."""
import base64
import copy
from html.parser import HTMLParser
from ..core.storage import digest, dump


class Tables(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables=[];self.table=None;self.row=None;self.cell=None;self.section=None

    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='table':
            if self.table is not None:raise ValueError('Nested HTML tables unsupported')
            if len(self.tables)>=64:raise ValueError('HTML table count limit')
            self.table={'head':[],'body':[]};self.tables.append(self.table)
        elif self.table is not None:
            if tag in {'thead','tbody','tfoot'}:self.section=tag
            elif tag=='tr':
                if self.row is not None:raise ValueError('Unclosed HTML row')
                if self.section not in {'thead','tbody'}:raise ValueError('Explicit HTML header/body required')
                self.row=[]
            elif tag in {'td','th'}:
                if self.row is None or self.cell is not None:raise ValueError('Malformed HTML cell')
                spans=[attrs.get(k,'1') for k in ['rowspan','colspan']]
                if any(not v.isdigit() or not 1<=int(v)<=64 for v in spans):raise ValueError('Invalid HTML span')
                self.cell={'rowspan':int(spans[0]),'colspan':int(spans[1]),'parts':[]}
            elif tag=='br' and self.cell is not None:self.cell['parts'].append(' ')

    def handle_data(self,data):
        if self.cell is not None:self.cell['parts'].append(data)

    def handle_endtag(self,tag):
        if self.table is None:return
        if tag in {'td','th'}:
            if self.cell is None:raise ValueError('Missing HTML cell')
            self.cell['text']=' '.join(''.join(self.cell.pop('parts')).split())
            self.row.append(self.cell);self.cell=None
            if len(self.row)>256:raise ValueError('HTML column limit')
        elif tag=='tr':
            if self.row is None or self.cell is not None:raise ValueError('Unclosed HTML cell')
            target='head' if self.section=='thead' else 'body'
            self.table[target].append(self.row);self.row=None
            if len(self.table[target])>5000:raise ValueError('HTML row limit')
        elif tag in {'thead','tbody','tfoot'}:self.section=None
        elif tag=='table':
            if self.row is not None or self.cell is not None:raise ValueError('Unclosed HTML table')
            self.table=None;self.section=None


def selected_html_tables(bundle,selections):
    result=copy.deepcopy(bundle)
    for choice in selections:
        parent=next(e for e in bundle['records'] if e['evidence_id']==choice['parent_evidence_id'])
        if (parent.get('kind')!='fulltext' or parent.get('status')!='accessible'
                or not parent.get('identity_match') or parent.get('http_status')!=200
                or not parent.get('complete_body') or parent.get('cloud_checksum',{}).get('verified') is False):
            raise ValueError('HTML table requires complete verified article evidence')
        raw=base64.b64decode(parent['body_sample_b64'],validate=True)
        if len(raw)>8*1024*1024 or len(raw)!=parent['bytes_observed'] or digest(raw)!=parent['payload_sha256']:
            raise ValueError('HTML table source bytes changed or oversized')
        text=raw.decode('utf-8-sig')
        parser=Tables();parser.feed(text);parser.close()
        if parser.table is not None:raise ValueError('Incomplete HTML table')
        index=choice['table_index']
        if type(index)!=int or not 0<=index<len(parser.tables):raise ValueError('Invalid HTML table index')
        table=parser.tables[index];heads=table['head'];body=table['body']
        if not 1<=len(heads)<=8 or not body:raise ValueError('HTML table lacks header/data')
        grid={}
        for y,row in enumerate(heads):
            x=0
            for cell in row:
                while (y,x) in grid:x+=1
                for dy in range(cell['rowspan']):
                    for dx in range(cell['colspan']):
                        key=(y+dy,x+dx)
                        if key in grid or key[0]>=len(heads) or key[1]>=256:raise ValueError('Overlapping/excessive HTML header spans')
                        grid[key]=cell['text']
                x+=cell['colspan']
        width=1+max(x for y,x in grid)
        if any((y,x) not in grid for y in range(len(heads)) for x in range(width)):
            raise ValueError('Incomplete HTML header grid')
        columns=[grid[(len(heads)-1,x)] for x in range(width)]
        if any(not c for c in columns) or len(set(columns))!=len(columns):raise ValueError('Blank/duplicate HTML headers')
        rows=[]
        for row in body:
            if len(row)!=width or any(c['rowspan']!=1 or c['colspan']!=1 for c in row):
                raise ValueError('Merged or irregular HTML data rows unsupported')
            rows.append([c['text'] for c in row])
        record=copy.deepcopy(parent)
        record.update(evidence_id='html-table-'+digest(dump(choice).encode())[:24],
                      parent_evidence_id=parent['evidence_id'],source_kind=parent['kind'],kind='file',
                      html_table_selection=choice,source_header_rows=heads,columns=columns,
                      level='sample_structure',transport='html_table',request_performed=False,
                      text=dump({'columns':columns,'source_header_rows':heads,'sample':rows[:5]}),
                      sample_row_count=min(5,len(rows)),downloaded_full_dataset=False,
                      interpretation_note='Selected observed article HTML table; explicit header spans only, no merged data filling, inferred fields, counts or new request.')
        if not any(e['evidence_id']==record['evidence_id'] for e in result['records']):result['records'].append(record)
    return result
