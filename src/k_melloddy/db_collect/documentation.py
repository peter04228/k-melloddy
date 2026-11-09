"""Project documentation templates generated for every organ/project."""
from ..core.storage import immutable_write

STEPS = [
    ('Project_Configuration', '프로젝트 식별자·경로 설정', 'organ, project_name, Input/project.yaml', '프로젝트 DB, 실행별 project.json', '경로를 OS 안전 이름으로 정규화하고 원본 장기명·프로젝트명을 저장한다. 기존 프로젝트는 --reuse로만 재사용한다.', 'paper (설정 시 0)'),
    ('Search_Query_Configuration', '원본 검색식 보존', 'Input/query.txt, config.yaml', '실행별 search_config.json', 'UTF-8 원본 검색식을 변경 없이 저장하고 SHA-256을 계산한다. 선택한 날짜 조건만 괄호로 결합한다. 새 실행은 새 run ID를 만들고 재개는 저장된 검색식을 사용한다.', 'paper (설정 시 0)'),
    ('Data_Field_Selection', '필수 내부 필드와 내보내기 필드 선택', 'Input/fields.yaml', 'fields.json, internal_master.json의 field_states', 'PMID/Title/Abstract/DOI/PMCID/원본 XML/실행 출처는 항상 보존한다. 반복 필드는 JSON 구조로 내보내며 XML을 원본으로 유지한다. available/missing_in_source/not_requested/fetch_failed를 구분한다.', 'paper (설정 시 0)'),
    ('Output_Configuration', '내보내기 형식 설정', 'Input/config.yaml', 'output_config.json', 'CSV/JSON/TXT/XLSX를 검증한다. CSV BOM은 선택 가능하다. ID는 최초 등장 실행에서 PMID 숫자 오름차순으로 배정하고 기존 번호는 보존한다.', 'paper (설정 시 0)'),
    ('PubMed_Search', '공식 검색 Count 확보', '원본 검색식, 선택 날짜, sort', 'Raw 검색 응답, search_manifest.json', 'ESearch retmax=0으로 Count/QueryTranslation을 검증한다. 오류 응답을 0건으로 대체하지 않는다. 실제 검색 시간과 실행 ID, 요청 파라미터 체크포인트를 기록한다.', 'search_result'),
    ('Query_Partitioning', '10,000건 초과 검색 분할', '공식 Count, 날짜 필드/범위', 'partitions.json, SQLite partitions', '전체 Count>10000이면 날짜 범위를 반으로 나누며 기본 9000 이하로 재귀 분할한다. 양 끝은 포함하며 다음 구간은 중간일+1일부터 시작한다. 하루 9001~10000은 추출 가능하며 하루>10000은 BLOCKED다.', 'search_result'),
    ('PMID_Retrieval', '페이지별 PMID 확보', '검증된 파티션', 'Raw/pmid_occurrences.json, pages/*.json', '기본 500개 페이지로 수집한다. 페이지의 Count 및 ID 개수와 형식을 검증한다. 성공한 페이지는 DB 체크포인트로 재사용하고 실패 응답은 원본만 남긴다. 반복 PMID는 삭제하지 않고 다음 단계로 전달한다.', 'pmid_occurrence'),
    ('Deduplication', 'PMID 기준 중복 제거', 'PMID 출현 기록', 'dedup_manifest.json, unique_pmids.csv, duplicate_occurrences.csv', 'PMID 집합을 만들고 두 번째 이후 출현은 파티션·페이지 정보와 함께 보존한다. DOI/제목 일치로 다른 PMID를 합치지 않는다.', 'pmid_occurrence → unique_pmid'),
    ('Metadata_Retrieval', 'EFetch 메타데이터 확보', '고유 PMID', 'Raw/pubmed_xml, metadata_records.json, paper_metadata', '기본 200개씩 XML을 받고 요청/응답 PMID 집합과 중복을 검증한다. 실패 배치 전체를 pending_retry로 유지한다. 구조화 초록의 Label/Category와 여러 AbstractText를 보존하며 부재는 abstract_absent다.', 'unique_pmid'),
    ('Quality_Control', '수량·필드·원본 무결성 검증', '공식 Count, 파티션/PMID/메타데이터/해시', 'qc.json, qc.csv, suspected_duplicate_*.json', '공식 수와 고유 PMID, 파티션 합, 원본 SHA-256, 제목 필수값, DOI/URL 형식, 초록 유무 합을 검사한다. 의심 중복은 보고만 한다. 불일치 및 보류는 PARTIAL, 하루 초과는 BLOCKED다.', 'unique_pmid'),
    ('Internal_ID_Assignment', '영구 내부 ID 할당', '프로젝트, PMID', 'paper_id_map.csv, SQLite papers', 'BEGIN IMMEDIATE 트랜잭션과 두 고유 제약으로 ID 충돌을 막는다. Liver는 Liver-00001(최소 5자리, 초과 시 확장), 다른 장기는 HEART-P000001 형태의 paper_id와 UUID paper_uid를 생성한다. 기존 ID는 변경하지 않는다. 재검색·정렬 변경에도 기존 매핑을 유지한다.', 'paper'),
    ('Export_and_PRISMA', '마스터·전달 계약·PRISMA 내보내기', '검증된 문헌과 ID', 'pubmed_master.*, internal_master.json, collect_output_manifest.json, PRISMA/audit 보고서', '선택 필드 마스터와 전체 내부 마스터를 저장한다. manifest의 버전·실행·상태·레코드 수·경로·SHA-256을 검증한다. Identification만 집계하며 Screening/Eligibility/Included는 null이다.', 'paper'),
]


def project_docs(root, organ, project_name):
    command = f'python -m k_melloddy collect run --organ "{organ}" --project-name "{project_name}"'
    shared = f'''
## 출력 표시 규칙

pubmed_master의 열은 paper_id(내부 번호), PMID, fields.yaml 선택 필드 순서이다.
출력은 Output/장기_YYYY-MM-DD/에 저장하며 날짜는 한국 시간이다. 같은 날 재실행 시 attempt ID를 붙여 기존 결과를 보존한다.
내부 마스터·원본 XML·감사 기록은 별도로 유지한다. PubMed XML 응답 전체는 전송되지만 사용자 마스터에는 선택 필드만 표시한다.
export --resume RUN_ID --current-output은 네트워크 없이 현재 fields.yaml과 출력 형식만 적용한다.
검색 조건과 ID는 원래 실행 것을 유지하며 새 출력 설정은 해당 attempt의 입력 스냅샷에 기록한다.
테스트: tests/test_collection.py::test_compact_current_output_and_dated_folder.

## 실행·상태·추적

전체 파이프라인 실행: `{command}`. 개별 세부 스텝 CLI는 제공하지 않는다.
검색만 실행: `python -m k_melloddy collect search --organ "{organ}" --project-name "{project_name}"`.
중단 후 상태 조회: `python -m k_melloddy collect status --organ "{organ}" --project-name "{project_name}"`.
재개: `{command} --resume RUN_ID` (저장된 입력 스냅샷 사용).
다른 저장 위치는 모든 명령에 `--base PATH`를 지정한다.

상태는 started → completed/partial/failed이며 재개 시 retried 이벤트를 추가한다.
각 단계 시작·종료 시 집계와 식별자 목록 해시를 append-only SQLite ledger에 기록한다.
설정 단계의 논문 수는 0이다. 검색/출현 수는 observed 이벤트에서 별도 단위로 기록하며
단위 전환을 동일 단위의 보존식과 섞지 않는다. 같은 단위 전환은
`input = forwarded + removed + pending`을 검증한다.

## 오류·재시도·재실행

네트워크 timeout 및 429/5xx에 지수 백오프와 Retry-After를 적용한다.
새 실행은 새 run ID, 재개는 같은 run ID와 새 attempt ID를 사용한다.
원본 및 보고서는 `분류/run_id/attempt_id/`에 저장하여 이전 결과를 덮어쓰지 않는다.
성공 응답 체크포인트는 SHA-256 검증 후 재사용한다. 응답 검증 실패는 체크포인트로 승인하지 않는다.
원본 저장 후 DB 커밋 전에 종료되면 해당 파일은 남고 요청을 재시도할 수 있다.
각 파일은 같은 디렉터리 임시 파일을 fsync한 뒤 원자적으로 공개한다.
OS 프로젝트 잠금은 프로세스 종료 시 해제된다. state.sqlite는 현재 상태,
ledger와 버전별 산출물은 과거 이력의 근거다.

## 테스트·제한

저장소 루트에서 `python -m pytest -q`.
오프라인 데모: `python -m k_melloddy collect demo --base demo_runs --project-name Example --count 12`.
Example 경로가 이미 있으면 새 이름을 사용한다. 데모 데이터는 합성 테스트 자료다.
실제 PubMed는 실행 도중 변경될 수 있어 완전히 동결된 서버 스냅샷을 보장하지 않는다.
ELink Full Text 별도 조회는 미구현이며 not_requested로 표시한다.
날짜 커버리지 불일치/하루 10000건 초과는 대체 전략을 자동 추정하지 않는다.
2~4단계는 인터페이스만 제공한다. CSV의 긴 셀은 보존하며 XLSX 제한 초과/제어문자는
별도 xlsx_overflow.json에 원문을 보존하고 경고한다. DOI 검증은 형식 검사다.
'''
    immutable_write(root/'README.md', '# DB_Collect\n\n1.1~1.12 실행 엔진. 입력은 Input, 원본은 Raw, 가공 중간값은 Intermediate, 전달물은 Output, 검증은 Reports에 저장한다.\n' + shared)
    for n, (slug, purpose, inputs, outputs, algorithm, unit) in enumerate(STEPS, 1):
        extra = ''
        if n == 8:
            extra = '\n검산: raw_occurrences = unique_pmids + duplicate_occurrences.\n'
        if n == 10:
            extra = '\n검산: unique_pmids = metadata_available + metadata_pending; metadata_available = abstract_present + abstract_absent; official_count = unique_pmids 및 파티션 합계를 대조한다.\n'
        immutable_write(root/f'1.{n}_{slug}'/'README.md', f'# 1.{n} {slug}\n\n목적: {purpose}\n\n입력: {inputs}\n\n출력: {outputs}\n\n알고리즘: {algorithm}\n\n집계 단위: {unit}\n' + extra + shared)
    for stage, contract in [
        ('DB_Select', 'SelectionRequest: 수집 manifest와 버전 있는 정책 ArtifactRef. TIAB 300 / Full Text 50 단위 판정, 논문↔DB 다대다 매핑과 영구 DB_ID는 향후 구현.'),
        ('DB_Download', 'DownloadRequest: 검증된 데이터셋 manifest와 접근 정책 ArtifactRef. URL·라이선스 확인, 파일 해시/버전/재시도는 향후 구현.'),
        ('DB_Preprocessing', 'PreprocessingRequest: 원본 파일 manifest와 변환 정책 ArtifactRef. 원본 보존, compound/measurement provenance, 결측/단위/QC는 향후 구현.'),
    ]:
        if stage == 'DB_Select':
            immutable_write(root.parent/stage/'README.md', '# DB_Select\n\n순차 검수 엔진이 구현되어 있습니다. 실제 LLM 제공자는 기본 미설정입니다. `python -m k_melloddy select init --organ '+organ+' --project-name '+project_name+'`으로 2.1~2.12 README를 생성하세요. 입력은 Collect manifest, 출력은 판정 JSON·근거·PRISMA·XLSX 4종입니다. 집계·상태·검증·재시도·한계는 루트 README의 DB_Select 절과 src/k_melloddy/db_select/README.md를 참고하세요. 테스트: `python -m pytest -q`.\n')
            continue
        immutable_write(root.parent/stage/'README.md', f'# {stage}\n\n상태: **미구현, 인터페이스만 제공**.\n\n{contract}\n\n출력 계약: 경로·SHA-256·run_id·schema_version을 포함한 ArtifactRef. 실행 함수는 NotImplementedError를 발생시킨다. PRISMA/데이터셋 집계 및 상태 전이는 실행하지 않는다. 재시도·재개도 미구현이다. 테스트: `python -m pytest -q`. src/k_melloddy/core/contracts.py 참조.\n')
    for folder, purpose in [('Input','사용자 입력과 실행별 입력 스냅샷'),('Raw','불변 API 원본'),('Intermediate','재현 가능한 가공 중간값'),('Output','실행별 확정 또는 부분 결과와 전달 manifest'),('Reports','QC 및 PRISMA/audit 보고서')]:
        immutable_write(root/folder/'README.md', f'# {folder}\n\n{purpose}.\n' + shared)
    immutable_write(root.parent/'Reports'/'README.md', '# Project Reports\n\n장기별 통합 보고서는 향후 구현. 현재 단계별 보고서는 DB_Collect/Reports/run_id/attempt_id에 있다.\n')
