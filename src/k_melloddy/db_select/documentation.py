from pathlib import Path
from ..core.storage import immutable_write

STEPS=[
('Input_Validation','Collect manifest 스키마·run·SHA-256 및 PMID↔paper_id 유일성을 확인하고 입력 참조를 고정한다. 내부 마스터만 읽으며 CSV에서 누락값을 추정하지 않는다.','Collect manifest','Input/<run>/collect_reference.json'),
('TIAB_Availability','Title/Abstract와 fetch_state를 구분한다. 원본 abstract_absent만 ABSTRACT_ABSENT로 제외하고 수집 실패는 fetch_error로 둔다.','문헌 마스터','TIAB availability 및 단계 이벤트'),
('TIAB_Relevance','모델 후보 JSON을 검증한다. 원문 Title/Abstract에서 실제 인용한 문자열이 있어야 한다. E01/E02 또는 candidate/pending_relevance를 처리하며 키워드로 자동 제외하지 않는다.','논문·장기 정책','TIAB 판정 및 근거'),
('Full_Text_Retrieval','별도 수집기가 실제 응답을 확인한다. PMID/DOI/Title 대조 근거가 있는 Full Text만 reviewed로 인정한다. 공개 접근만 시도하며 제한을 우회하지 않는다.','후보·관련성 보류','SQLite documents 및 JSON/evidence_log.json'),
('Supplementary_Repository','Full Text 절과 부록·저장소 조사 범위를 기록한다. 기본 HTTP 수집기는 링크를 제한적으로 탐색하며 조사 완료를 자동 주장하지 않는다.','Full Text·실제 발견 링크','절/URL·자료 위치·미해결 작업'),
('Dataset_Verification','실제 file/API 응답과 sample_structure/metadata_structure/full_file 검증 수준을 요구한다. 약물 식별자/endpoint/측정값 필드를 확인하고 출처 인용을 대조한다.','모델 후보·수집 근거','검증된 데이터셋 후보 또는 검증 오류'),
('Final_Decision','5조건·파일·직접 경로·구조·독립 근거가 모두 있으면 confirmed. E03~E08은 세 절과 부록/저장소의 완료된 조사가 필요하다. P01~P04 전제조건을 검사하며 실패는 fetch_error이다.','검증된 후보','SQLite revisions 및 JSON/screening_results.json'),
('Initial_Pass_Completion','내부 paper_id의 숫자 순서로 한 편의 검수를 저장한 뒤 다음 편을 처리한다. r01 및 유효 Full Text 이력이 없는 완료 표시는 재검수한다. 미검수/수집 오류가 있으면 최초 패스 완료가 아니다.','현재 논문 상태','최초 패스 완료/미완료 수'),
('Pending_Revalidation','최초 패스 전체가 끝난 후 대상 목록을 한 번 고정하여 순회한다. 자동 순회는 1회, 명시적 revalidate는 최대 시도까지 회차별 1회다. 오류 시 기존 정당한 보류를 유지한다.','P01~P04 및 코드별 집중 작업','SQLite documents/events 및 JSON/revalidation_history.json'),
('Dataset_Registration','논문 저장 트랜잭션에서 확정 데이터셋도 즉시 등록한다. doi/accession/url 정규 ID+명시적 version 해시로 중복을 막는다. 다대다 매핑과 고정 ORGAN-D000001 ID를 보존한다.','확정 논문·검증된 후보','datasets/mappings 및 paper JSON dataset_id'),
('QC_PRISMA','PMID/번호·정책 해시·제외 코드·포함 매핑·최종 분할과 모든 단계 보존식을 확인한다. fetch_error/unreviewed는 incomplete_count로 분리한다.','원본 입력·최신 판정·append-only 이벤트','QC JSON 및 2.1~2.12/final_summary JSON'),
('Final_Export','SQLite에서 누적 JSON 3개를 재생성하고 DB_Select_Final.xlsx 하나에 5시트를 만든다. 실제 select_stage.xlsx의 16열/15열 헤더와 4행/2행 위치를 유지하고 추가 열을 금지한다. 긴 초록은 기존 셀에서 누적 JSON 원문 위치를 안내한다. 저장 후 행·열·헤더·분할·매핑·PRISMA 집계를 대조한다.','SQLite 최신 판정·누적 JSON·템플릿 계약','Output/DB_Select_Final.xlsx 및 select_output_manifest.json'),
]


def project_docs(root,organ='Heart',project_name='Heart'):
    root=Path(root)
    common=Path(__file__).with_name('verified_workflow.README.md').read_text(encoding='utf-8')
    common=common.replace('[revalidation contract](revalidator.README.md)','revalidation contract below')
    common+='\n\n'+Path(__file__).with_name('revalidator.README.md').read_text(encoding='utf-8')
    common+='\n\n'+Path(__file__).with_name('stabilization.README.md').read_text(encoding='utf-8')
    common=common.replace('[stabilization contract](stabilization.README.md)','stabilization contract below')
    common+='\n\n'+Path(__file__).with_name('data_observations.README.md').read_text(encoding='utf-8')
    common=common.replace('[data observation contract](data_observations.README.md)','data observation contract below')
    updates={
        1: 'Validate immutable Collect scope/hash/IDs, then re-fetch official PubMed metadata per PMID before full text.',
        2: 'Distinguish genuine abstract absence from retrieval failure; only the former permits ABSTRACT_ABSENT exclusion.',
        3: 'Use organ YAML and quoted evidence; distinguish keyword-only mention, exposure/toxicity and verified public data.',
        4: 'Use verified identifiers for PMC, publisher and exact-PMID/title alternative routes; audit retries and identity checks.',
        5: 'Review Methods, Data Availability, supplementary material and repositories in order; do not equate HTTP success with review.',
        6: 'Validate actual file/API access, toxicity features and structure; insufficient access evidence retains an auditable pending state.',
        7: 'Require confirmed/excluded/pending only; validate E/P prerequisites. Operational holds prevent completion.',
        8: 'Process numeric IDs ascending; commit each paper before the next. Require the exact complete final scope.',
        9: 'Perform a bounded fresh pending sweep, recording old/new decisions, current access attempts and next actions.',
        11: 'Validate exact scope, ID/PMID uniqueness, final partition, codes, histories, mappings and matching JSON/PRISMA/Excel counts.'}
    root.mkdir(parents=True,exist_ok=True)
    (root/'README.md').write_text(common,encoding='utf-8')
    for n,(slug,algorithm,inputs,outputs) in enumerate(STEPS,1):
        p=root/f'2.{n}_{slug}';p.mkdir(exist_ok=True)
        (p/'README.md').write_text(f'# 2.{n} {slug}\n\nAlgorithm: {updates.get(n,algorithm)}\n\nInputs: {inputs}\n\nOutputs: {outputs}\n\n'+common,encoding='utf-8')
    for name in ['Input','Criteria','JSON','FullText','PRISMA','Output']:
        p=root/name;p.mkdir(parents=True,exist_ok=True)
        (p/'README.md').write_text(f'# {name}\n\n'+common,encoding='utf-8')
    if not (root/'Input/collect_manifest.txt').exists():immutable_write(root/'Input/collect_manifest.txt','')
