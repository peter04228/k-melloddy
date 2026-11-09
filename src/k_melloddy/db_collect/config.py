from datetime import date
from pathlib import Path
import yaml

from ..core.storage import Store, dump, immutable_write, now, safe_name, uid

FIELDS = ['PMID', 'DOI', 'PMCID', 'PII', 'Title', 'Abstract', 'Keywords', 'MeSH',
          'Authors', 'Journal', 'Publication Date', 'Publication Type', 'Language',
          'Volume/Issue/Pages', 'Affiliation', 'Grant', 'PubMed URL', 'Full Text']
DEFAULT = dict(fields=FIELDS, formats=['csv', 'json', 'txt'], csv_bom=True,
               sort='pub_date', date_field='pdat', date_start=None, date_end=None,
               partition_start='1800-01-01', partition_end='2100-12-31',
               partition_target=9000, page_size=500, batch_size=200,
               id_order='numeric_pmid_ascending_first_seen', tool='k_melloddy', email='')


def validate(config):
    if not isinstance(config, dict):
        raise ValueError('Configuration must be a mapping')
    unknown = set(config) - set(DEFAULT)
    if unknown:
        raise ValueError(f'Unknown config keys: {sorted(unknown)}')
    c = {**DEFAULT, **config}
    if not isinstance(c['fields'], list) or any(not isinstance(f, str) or f not in FIELDS for f in c['fields']):
        raise ValueError('Unknown export field')
    if not isinstance(c['formats'], list) or not c['formats'] or any(f not in ['csv','json','txt','xlsx'] for f in c['formats']):
        raise ValueError('Invalid export formats')
    for key, limit in [('partition_target', 9999), ('page_size', 1000), ('batch_size', 500)]:
        if type(c[key]) is not int or not 1 <= c[key] <= limit:
            raise ValueError(f'{key} must be 1..{limit}')
    if c['date_field'] not in {'pdat', 'edat'}:
        raise ValueError('date_field must be pdat or edat')
    for a, b in [('date_start', 'date_end'), ('partition_start', 'partition_end')]:
        if any(c[k] is not None and not isinstance(c[k], str) for k in [a,b]):
            raise ValueError('Dates must be quoted ISO date strings in YAML')
        if a == 'partition_start' and (not c[a] or not c[b]):
            raise ValueError('Partition date coverage must be specified')
        if bool(c[a]) != bool(c[b]):
            raise ValueError(f'Both {a} and {b} required')
        if c[a] and date.fromisoformat(c[a]) > date.fromisoformat(c[b]):
            raise ValueError('Reversed date interval')
    if c['id_order'] != DEFAULT['id_order'] or type(c['csv_bom']) is not bool:
        raise ValueError('Invalid output policy')
    for key in ['sort', 'tool', 'email']:
        if not isinstance(c[key], str):
            raise ValueError(f'{key} must be text')
    return c


def init_project(base, organ, name=None, reuse=False, description=''):
    folder = safe_name(name or organ)
    root = Path(base) / folder / 'DB_Collect'
    path = root / 'Input/project.yaml'
    if path.exists():
        if not reuse:
            raise ValueError('Project exists. Use --reuse or a new --project-name.')
        p = yaml.safe_load(path.read_text(encoding='utf-8'))
        if p['organ'] != organ or p['name'] != (name or organ):
            raise ValueError('Normalized path collision with another project')
        return root
    for d in ['Input', 'Raw', 'Intermediate', 'Output', 'Reports']:
        (root / d).mkdir(parents=True, exist_ok=True)
    p = dict(project_id=uid(), organ=organ, name=name or organ, created_at=now(),
             config_version='1.0', description=description, path_name=folder)
    with_context = Store(root)
    try:
        if with_context.db.execute('SELECT COUNT(*) FROM projects').fetchone()[0]:
            raise ValueError('Database already initialized without project.yaml; inspect before reuse')
        with with_context.db:
            with_context.db.execute('INSERT INTO projects VALUES (?,?,?,?,?)',
                tuple(p[k] for k in ['project_id', 'organ', 'name', 'created_at', 'config_version']))
        immutable_write(path, yaml.safe_dump(p, allow_unicode=True))
        immutable_write(root / 'Input/config.yaml', yaml.safe_dump(DEFAULT, allow_unicode=True))
        immutable_write(root / 'Input/fields.yaml', yaml.safe_dump({'fields': FIELDS}))
        immutable_write(root / 'Input/query.txt', '')
    finally:
        with_context.close()
    from .documentation import project_docs
    project_docs(root, organ, name or organ)
    return root


def read_inputs(root):
    root = Path(root)
    project = yaml.safe_load((root / 'Input/project.yaml').read_text(encoding='utf-8'))
    config = yaml.safe_load((root / 'Input/config.yaml').read_text(encoding='utf-8')) or {}
    fields = yaml.safe_load((root / 'Input/fields.yaml').read_text(encoding='utf-8'))
    config['fields'] = fields['fields']
    query = (root / 'Input/query.txt').read_bytes().decode('utf-8')
    if not query.strip():
        raise ValueError('Input/query.txt is empty; enter your original PubMed query')
    return project, query, validate(config)
