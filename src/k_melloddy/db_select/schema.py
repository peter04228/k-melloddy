"""Validator for the explicitly used JSON Schema subset (no permissive fallbacks)."""
import re


def validate(value, schema, path='$'):
    types = {'object': dict, 'array': list, 'string': str, 'boolean': bool,
             'integer': int, 'number': (int, float), 'null': type(None)}
    kind = schema.get('type')
    if kind:
        kinds = kind if isinstance(kind, list) else [kind]
        if not any(isinstance(value, types[k]) and not (k in {'integer','number'} and isinstance(value,bool)) for k in kinds):
            raise ValueError(f'{path}: expected {kind}')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError(f'{path}: unexpected value {value!r}')
    if isinstance(value, dict):
        for key in schema.get('required', []):
            if key not in value:
                raise ValueError(f'{path}: missing {key}')
        properties = schema.get('properties', {})
        if schema.get('additionalProperties') is False and set(value)-set(properties):
            raise ValueError(f'{path}: unknown fields {set(value)-set(properties)}')
        for key in value.keys() & properties.keys():
            validate(value[key], properties[key], f'{path}.{key}')
    if isinstance(value, list):
        if len(value) < schema.get('minItems', 0):
            raise ValueError(f'{path}: empty array')
        for i, item in enumerate(value):
            validate(item, schema.get('items', {}), f'{path}[{i}]')
    if isinstance(value, str):
        if len(value) < schema.get('minLength', 0) or ('pattern' in schema and not re.search(schema['pattern'], value)):
            raise ValueError(f'{path}: invalid string')
    if isinstance(value, (int, float)) and not isinstance(value,bool):
        if value < schema.get('minimum', float('-inf')) or value > schema.get('maximum', float('inf')):
            raise ValueError(f'{path}: outside range')


def obj(properties, required=None):
    return dict(type='object', properties=properties, required=list(properties) if required is None else required, additionalProperties=False)


TEXT = {'type':'string','minLength':1}
REF = obj({'evidence_id': TEXT, 'quote': TEXT})
REFS = {'type':'array','items':REF,'minItems':1}
DATA_OBSERVATION = obj({
    'name':TEXT,'relationship':{'enum':['reuse','new','derived','unknown']},
    'public_status':{'enum':['unknown','reported_public','verified_public','restricted','not_public']},
    'verification_level':{'enum':['mentioned','landing_page','sample_structure','metadata_structure','full_file','unverified']},
    'url':{'type':['string','null']},'evidence_refs':REFS,
})
DATASET = obj({
    'name':TEXT, 'identity':TEXT, 'version':TEXT, 'direct_url':TEXT, 'evidence_id':TEXT,
    'drug_identifier':TEXT, 'endpoint':TEXT, 'value_field':TEXT, 'independence_reason':TEXT,
    'evidence_refs':REFS,
    'feature_count':{'type':['integer','null'],'minimum':0},
    'compound_count':{'type':['integer','null'],'minimum':0},
})
TIAB = obj({'decision':{'enum':['candidate','pending_relevance','E01','E02']},
            'reason':TEXT,'quote':TEXT})
TIAB['properties'].update({'exposure':TEXT,'toxicity_endpoint':TEXT,
    'relevance_class':{'enum':['keyword_only','exposure_toxicity','uncertain_exposure_toxicity']}})
TIAB['properties']['data_observations']={'type':'array','items':DATA_OBSERVATION}
PROPOSAL = obj({
    'status':{'enum':['confirmed','excluded','pending']},
    'code':{'enum':['',*[f'E{i:02}' for i in range(3,9)],*[f'P{i:02}' for i in range(1,5)]]},
    'reason':TEXT, 'evidence_refs':{'type':'array','items':REF},
    'conditions':obj({k:{'type':'boolean'} for k in ['relevance','actual_data','direct_path','structure','independent']}),
    'datasets':{'type':'array','items':DATASET},
    'what_confirmed':{'type':'array','items':TEXT}, 'what_unresolved':{'type':'array','items':TEXT},
    'next_verification_action':{'type':'string'},
    'source_databases':{'type':'array','items':obj({'name':TEXT,'url':TEXT,'evidence_refs':REFS})},
})
PROPOSAL['properties']['data_observations']={'type':'array','items':DATA_OBSERVATION}
ORGAN = obj({
    'organ':TEXT, 'organ_ko':TEXT, 'version':TEXT, 'scope':TEXT,
    **{k:{'type':'array','items':TEXT,'minItems':1} for k in ['keywords','synonyms','endpoints','applicable','not_applicable','ambiguous','candidate_examples','E01_examples','E02_examples','data_examples']},
    'clinically_validated':{'enum':[False]},
})
ORGAN['properties'].update({k:{'type':'array','items':TEXT,'minItems':1} for k in [
    'database_keywords','repository_examples','compound_identifiers','experimental_metadata',
    'inclusion_requirements','data_file_formats','decision_notes',
    *[f'E{i:02}_examples' for i in range(3,9)],*[f'P{i:02}_examples' for i in range(1,5)]]})
ORGAN['properties']['pending_revalidation']=obj({f'P{i:02}':{'type':'array','items':TEXT,'minItems':1} for i in range(1,5)})
ORGAN['required'].remove('data_examples')
ORGAN['properties']['endpoints']={'type':['array','object'],'items':TEXT}
ORGAN['properties'].update({
    'workflow':{'type':'object'},
    'verification':{'type':['object','null']},
    'exclusion_codes':obj({f'E{i:02}':TEXT for i in range(1,9)}),
    'pending_codes':obj({f'P{i:02}':TEXT for i in range(1,5)}),
})
RECORD = obj({
    'schema_version':{'enum':['1.0']},'run_id':TEXT,'collect_run_id':TEXT,'paper_id':TEXT,'pmid':TEXT,'organ':TEXT,
    'tiab':{'type':'object'},'fulltext':{'type':'object'},
    'final':obj({'status':{'enum':['confirmed','excluded','pending','fetch_error','unreviewed']},'code':{'type':'string'},'reason':TEXT}),
    'datasets':{'type':'array'},'source_databases':{'type':'array'},'revalidation':{'type':'object'},
    'provenance':obj({k:TEXT for k in ['organ_policy_version','policy_sha256','prompt_version','model_provider','model_name','review_timestamp']}),
    'initial_review_valid':{'type':'boolean'},'evidence_ref':{'type':['object','null']},
    'source_record':{'type':'object'},'revision':{'type':'integer','minimum':1},
})
RECORD['properties'].update({'workflow_version':TEXT,'verified_metadata':{'type':'object'},
    'metadata_verification':{'type':'object'},'processing_state':TEXT,'public_data_status':TEXT})
RECORD['properties']['data_observations']={'type':'array','items':DATA_OBSERVATION}
