import json
from pathlib import Path
import yaml
from ..core.storage import digest, dump
from .schema import validate, ORGAN, PROPOSAL, TIAB, RECORD

EXCLUSIONS = {
 'E01':'약물·화합물 유발 독성 연구 자체가 아님',
 'E02':'약물 연구지만 해당 장기 독성 평가가 실제 연구 내용에 없음',
 'E03':'Review·메타분석에서 별도 공개 독성자료 미확인',
 'E04':'실험·기전 연구이나 공개 재사용 데이터 미확인',
 'E05':'임상·환자자료 연구이나 독립 공개 파일 미확인',
 'E06':'ML·QSAR·전산모델 연구이나 재사용 입력·관측 데이터 미확인',
 'E07':'기존 공개 DB·약물감시 자료만 이용하고 논문별 별도 공개자료 미확인',
 'E08':'그 외 유형에서 구조화된 재사용 데이터 파일 미확인',
}
PENDING = {
 'P01':'공식 파일 URL, accession, API endpoint, 정확한 메뉴 재탐색',
 'P02':'DOI 외 PubMed, PMC, 출판사, 기관 공개 저장소 재시도',
 'P03':'실제 파일명, 파일 형식, 접근 가능 여부, 구조 확인',
 'P04':'약물 식별자, 엔드포인트, 측정값/라벨, 표본 컬럼 확인',
}


def load_policy(directory, organ):
    directory=Path(directory)
    files=['common_rules.yaml','exclusion_codes.yaml','pending_codes.yaml','fulltext_protocol.md',
           'output_schema.json', 'organ_schema.json', 'record_schema.json', 'tiab_schema.json',f'organs/{organ.lower()}.yaml']
    raw={name:(directory/name).read_text(encoding='utf-8') for name in files}
    organ_policy=yaml.safe_load(raw[files[-1]])
    validate(organ_policy, ORGAN)
    endpoints=organ_policy['endpoints']
    if isinstance(endpoints,dict):
        if not endpoints:raise ValueError('Empty endpoint groups')
        for group,values in endpoints.items():
            validate(values,{'type':'array','items':{'type':'string','minLength':1},'minItems':1},'endpoints.'+group)
    workflow=organ_policy.get('workflow')
    if workflow:
        if set(workflow)!={'step_0','step_1','step_2','step_3'}:raise ValueError('Unsupported workflow steps')
        if workflow['step_0'].get('require_title_and_abstract') is not True:raise ValueError('Unsupported TIAB presence rule')
        if workflow['step_1'].get('allowed_exclusion_codes')!=['E01','E02']:raise ValueError('Invalid Step 1 codes')
        if workflow['step_2'].get('allowed_exclusion_codes')!=[f'E{i:02}' for i in range(3,9)]:raise ValueError('Invalid Step 2 codes')
        if workflow['step_2'].get('allowed_pending_codes')!=[f'P{i:02}' for i in range(1,5)]:raise ValueError('Invalid pending codes')
        if workflow['step_3'].get('max_automatic_revalidation_rounds')!=1:raise ValueError('Only one automatic revalidation round supported')
    if organ_policy['organ'].casefold()!=organ.casefold():
        raise ValueError('Organ policy mismatch')
    rules=yaml.safe_load(raw['common_rules.yaml'])
    if set(rules)-{'automatic_revalidation_attempts'}!={'version','prompt_version','max_revalidation_attempts','max_urls','max_response_bytes','timeout_seconds','provider'}:
        raise ValueError('Invalid common rules keys')
    for key in ['max_revalidation_attempts','max_urls','max_response_bytes','timeout_seconds']:
        if type(rules[key]) is not int or rules[key]<1:
            raise ValueError(f'Invalid {key}')
    auto=rules.get('automatic_revalidation_attempts',1)
    if type(auto) is not int or not 1<=auto<=rules['max_revalidation_attempts']:raise ValueError('Invalid automatic_revalidation_attempts')
    if not isinstance(rules['provider'],str) or not rules['version'] or not rules['prompt_version']:
        raise ValueError('Missing provider/version')
    if yaml.safe_load(raw['exclusion_codes.yaml'])!=EXCLUSIONS or yaml.safe_load(raw['pending_codes.yaml'])!=PENDING:
        raise ValueError('E/P code roles are fixed; organ-specific examples belong in organs YAML')
    for name, schema in [('output_schema.json',PROPOSAL),('tiab_schema.json',TIAB),('record_schema.json',RECORD),('organ_schema.json',ORGAN)]:
        if json.loads(raw[name])!=schema:
            raise ValueError(f'Unsupported schema modification: {name}')
    payload={'files':raw,'organ':organ_policy,'rules':rules}
    payload['sha256']=digest(dump(payload).encode())
    return payload


def tiab_missing(paper,policy):
    return [k for k in ['Title','Abstract'] if not (paper['values'].get(k) or '').strip()]


def review_instructions(policy,round_number=1,previous_code=''):
    """The complete organ criteria are visible to the reviewer, without keyword filtering."""
    return {'organ_criteria':policy['organ'],'step':3 if round_number>1 else 2,
            'pending_tasks':policy['organ'].get('pending_revalidation',{}).get(previous_code,[]),
            'rules':['Write decision reasons, review explanations, unresolved issues and next actions in Korean. Preserve original titles, dataset names, URLs and verbatim evidence quotes.',
                     'Judge research purpose, exposure and organ toxicity from actual evidence; keywords are cues only.',
                     'Step 1 allows only E01/E02 exclusion; uncertainty advances to Step 2.',
                     'Step 2/3 inclusion requires verified access, data structure and compound-to-toxicity linkage.',
                     'Access failure is not proof of data absence. Preserve unresolved P codes and prior history.']}
