# 1.6 Query_Partitioning

목적: 10,000건 초과 검색 분할

입력: 공식 Count, 날짜 필드/범위

출력: partitions.json, SQLite partitions

알고리즘: 전체 Count>10000이면 날짜 범위를 반으로 나누며 기본 9000 이하로 재귀 분할한다. 양 끝은 포함하며 다음 구간은 중간일+1일부터 시작한다. 하루 9001~10000은 추출 가능하며 하루>10000은 BLOCKED다.

집계 단위: search_result

## 실행·상태·추적

전체 파이프라인 실행: `python -m k_melloddy collect run --organ "Liver" --project-name "Liver"`. 개별 세부 스텝 CLI는 제공하지 않는다.
검색만 실행: `python -m k_melloddy collect search --organ "Liver" --project-name "Liver"`.
중단 후 상태 조회: `python -m k_melloddy collect status --organ "Liver" --project-name "Liver"`.
재개: `python -m k_melloddy collect run --organ "Liver" --project-name "Liver" --resume RUN_ID` (저장된 입력 스냅샷 사용).
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


## 2026-11-03 출력 형식 변경

사용자 마스터는 paper_id(내부 번호), PMID, fields.yaml에서 선택한 필드 순서입니다. Liver는 PMID/Title/Abstract를 선택해 총 4열입니다. 내부 마스터와 원본 XML은 검증용으로 유지합니다.
새 결과 경로는 Output/장기_YYYY-MM-DD/이며 한국 시간 기준입니다. 같은 날짜 폴더가 있으면 attempt ID를 붙여 보존합니다. 이전 Output/run/attempt 결과는 변경하지 않습니다. Reports/Raw 경로는 기존대로입니다.
`python -m k_melloddy collect export --organ Liver --resume RUN_ID --current-output`은 네트워크 없이 기존 체크포인트를 사용하고 현재 fields.yaml 및 formats/csv_bom만 반영합니다. 기본 재개는 고정된 설정을 사용합니다. 새 출력 설정은 attempt 입력 스냅샷에 기록되며 검증 상태는 그대로 유지됩니다.
테스트: tests/test_collection.py::test_compact_current_output_and_dated_folder. 기존 경로·출력 설명보다 이 변경 규칙이 우선합니다.


## Liver 내부 번호 (2026-11-03 변경)

새 Liver 논문은 Liver-00001 형식으로 P 없이 최소 5자리 숫자를 사용합니다. 10,000번은 Liver-10000입니다. 99,999를 초과하면 자릿수를 늘리며 중복·순환하지 않습니다. 이미 발급된 ID는 수정하지 않으며 다른 장기 형식은 유지합니다. DB_Select는 새 형식과 기존 LIVER-P000001 형식을 모두 숫자 순서로 인식합니다. 재개/재내보내기는 기존 매핑을 유지합니다. 오프라인 테스트: tests/test_collection.py::test_liver_five_digit_ids_and_select_handoff.
