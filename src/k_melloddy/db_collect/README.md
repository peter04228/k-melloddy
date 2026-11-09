# db_collect

Implemented collection infrastructure.

Transport recovery: truncated HTTP bodies (IncompleteRead) and remote disconnects retry the complete request with bounded exponential backoff (default four retries). Partial bytes are never returned as valid XML or checkpointed. Retry callbacks record audit events without increasing scientific counts. Exhaustion becomes a controlled request failure; resume reuses prior validated checkpoints. Offline regression: tests/test_edge_cases.py::test_interrupted_response_read_retries_whole_request covers successful retry and exhaustion for both errors.

Inputs and outputs: see root README, core/contracts.py and project step READMEs. Algorithms and metric units: DB_Collect uses search_result, pmid_occurrence, unique_pmid and paper; later stages will use dataset/file/compound/measurement separately. State transitions: started/completed/partial/failed/retried in append-only audit events for collection. Later stages have no runtime events. Validation: input = forwarded + removed + pending; SHA-256 and schema/ID invariants. Retry/resume: run-scoped validated checkpoints and immutable attempt artifacts, no retries for unimplemented stages.

Run: `python -m k_melloddy collect demo --base demo_runs --project-name Example --count 12`. Test: `python -m pytest -q`. Limitations: no GUI, no ELink, no implementation of stages 2-4.


## 2026-11-03 출력 형식 변경

사용자 마스터는 paper_id(내부 번호), PMID, fields.yaml에서 선택한 필드 순서입니다. Liver는 PMID/Title/Abstract를 선택해 총 4열입니다. 내부 마스터와 원본 XML은 검증용으로 유지합니다.
새 결과 경로는 Output/장기_YYYY-MM-DD/이며 한국 시간 기준입니다. 같은 날짜 폴더가 있으면 attempt ID를 붙여 보존합니다. 이전 Output/run/attempt 결과는 변경하지 않습니다. Reports/Raw 경로는 기존대로입니다.
`python -m k_melloddy collect export --organ Liver --resume RUN_ID --current-output`은 네트워크 없이 기존 체크포인트를 사용하고 현재 fields.yaml 및 formats/csv_bom만 반영합니다. 기본 재개는 고정된 설정을 사용합니다. 새 출력 설정은 attempt 입력 스냅샷에 기록되며 검증 상태는 그대로 유지됩니다.
테스트: tests/test_collection.py::test_compact_current_output_and_dated_folder. 기존 경로·출력 설명보다 이 변경 규칙이 우선합니다.


## Liver 내부 번호 (2026-11-03 변경)

새 Liver 논문은 Liver-00001 형식으로 P 없이 최소 5자리 숫자를 사용합니다. 10,000번은 Liver-10000입니다. 99,999를 초과하면 자릿수를 늘리며 중복·순환하지 않습니다. 이미 발급된 ID는 수정하지 않으며 다른 장기 형식은 유지합니다. DB_Select는 새 형식과 기존 LIVER-P000001 형식을 모두 숫자 순서로 인식합니다. 재개/재내보내기는 기존 매핑을 유지합니다. 오프라인 테스트: tests/test_collection.py::test_liver_five_digit_ids_and_select_handoff.


2026-11-03: Select는 --limit/--order로 범위를 고정하며 --review-file로 명시적 Codex 세션 검수만 재생합니다. 미작성 단계는 미완료이며 자동 추론하지 않습니다. capture_review.py 입력은 Collect manifest/ID 목록, 출력은 관측 근거 입력 JSON입니다. 실제 네트워크는 명시적 호출에서만 사용하며 원문 확인 완료를 자동 보증하지 않습니다. submitted_review.py는 입력/정책 해시를 검증합니다. Collect DOI/PMCID는 참고문헌을 제외한 직접 ArticleIdList에서 추출하도록 수정했습니다. 기존 결과는 보존합니다. 상세 명령·상태·재개·제한은 Liver 단계 README 및 Output/pilot10_review_report.md를 참조하세요.
