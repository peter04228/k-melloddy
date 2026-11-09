> Current CLI contract: [Verified workflow 2.0](verified_workflow.README.md). This supersedes legacy fetch_error/final-state and descending-processing descriptions below; historical runs remain immutable.
>
> Added modules: [official metadata](official_metadata.README.md), [access investigation](access_workflow.README.md), [verified orchestration](verified_workflow.README.md). Updated modules: engine/CLI (ascending processing), schema/submitted_review (verified overlay), prisma (blocked completion), excel_export/workbooks (verified fields and pending summary), documentation (all step contracts). The linked workflow defines inputs/outputs, algorithms/states, units, audit/retry/resume, commands, validation/tests and limitations for these changes.

# DB_Select

Current pending-loop behavior, history fields, initial/final counters, code-specific tasks and limitations are documented in [revalidator README](revalidator.README.md). This update covers engine, persistence, prisma, submitted_review and both verified workflow modules.

순차 문헌 검수 엔진. 입력은 Collect manifest/internal_master, 출력은 SQLite 원장, 누적 JSON 3개, 단계별 PRISMA JSON, 최종 XLSX 1개(5시트), Download manifest입니다. 실행 방법은 루트 README와 프로젝트 2.1~2.12 README에 있습니다.

## 모듈 경계

| 파일 | 역할 |
|---|---|
| policy.py / schema.py | 고정 E/P 역할, 장기 YAML·후보·저장 JSON 검증 |
| metadata.py | 입력 경로·해시·run·스키마·ID 및 내부 번호 정렬 |
| llm_adapter.py | 교체 가능한 LLMProvider, 미설정 오류, 합성 fixture |
| evidence_collector.py | 별도 자료 수집기, 실제 응답/URL/인용 텍스트 계약 |
| dataset_verifier.py / decision.py | 근거 인용 대조, 파일/API 구조·5조건·E/P 전제 |
| persistence.py | 독립 SQLite, 유일 ID, revision/event append-only, 데이터셋·논문 동시 저장 |
| revalidator.py | 전체 초기 패스 완료 후 유한 보류 순회, r01 무효화 |
| prisma.py | 논문 단위 보존식·최종 집계, 별도 데이터셋 수 |
| excel_export.py / workbooks.mjs | 고정 16열/15열 헤더의 5시트 XLSX 1개, 저장 후 전체 필드/행 검증 |
| engine.py / cli.py | 순차 실행, 즉시 저장, 재개, 진행 로그와 CLI |
| fixtures.py / setup_config.py / documentation.py | 합성 데모·초기 기준·프로젝트 문서 생성 |

## 제공자 계약

LLMProvider는 `name`, `model`, `propose(phase,paper,policy,evidence,previous)`를 제공합니다. phase는 tiab 또는 fulltext입니다. 반환값은 config/db_select의 해당 JSON Schema에 맞는 dict입니다. TIAB 인용은 원본 Title/Abstract와, Full Text 인용은 실제 수집 text와 정확히 일치해야 합니다. 후보 출력은 아직 사실/최종판정이 아니며 decision.py가 검증한 뒤 반영합니다. 제공자는 웹 접근 성공 여부를 자체 인증할 수 없습니다.

`common_rules.yaml`의 `provider: python:your_module:factory`는 인자 없는 factory가 제공자를 반환하도록 합니다. 기본 unconfigured, codex/openai/local 이름은 연결하지 않은 상태로 오류 처리합니다. 실제 연결이 없는 fixture를 연구용 추론으로 사용하면 안 됩니다. 사용자가 제공자를 결정하기 전까지 외부 API를 호출하지 않습니다.

EvidenceCollector는 `collect(paper,policy,action)`으로 실제 관찰 records와 조사 범위를 반환합니다. 각 record에 evidence_id, URL/final URL, kind, UTC timestamp, status/HTTP status, text, payload SHA-256, bytes_observed, identity_match, sections, file format/columns, 검증 level을 포함합니다. 조사 완료 boolean은 수집기 책임이며 기본 HTTP 수집기는 저장소/부록 전체 검수를 완료했다고 주장하지 않습니다. 실제 제공자와 수집기 통합은 `Selector(..., provider=..., collector=...)`로 주입합니다.

## 저장·집계·오류

입력 = 전달 + 제외 + 보류 + 수집 오류(paper). 현재 판정만 최종 분할에 포함하고 사건 이력은 보존합니다. `pending_relevance`는 TIAB 전달 분기이며 최종 P코드가 아닙니다. 논문 수와 dataset 수를 더하지 않습니다. 무효 후보·자료 접근 오류는 fetch_error이며 최초 패스 완료로 세지 않습니다. 보류 자동 재검증은 1회, 명시적 재검증은 설정 최대 횟수까지 한 번씩 순회합니다.

dataset canonical key는 정규화 DOI 또는 accession/repository 또는 canonical URL + version의 SHA-256입니다. URL 경로 대소문자는 보존합니다. 근거가 없는 alias 병합은 하지 않으므로 서로 다른 식별자의 동일 자료 여부는 별도 검토가 필요합니다. E07은 원천 DB 관계만 저장하고 신규 dataset으로 등록하지 않습니다.

논문 판정·데이터셋 연결·최종 감사 이벤트를 SQLite transaction으로 먼저 commit합니다. 이후 JSON/screening_results.json, evidence_log.json, revalidation_history.json을 내부 번호 오름차순으로 원자 교체합니다. 세 파일의 generation_id와 checkpoint 해시로 부분 갱신을 검출하며 재개 시 SQLite에서 복구합니다. Windows 일시 파일 잠금은 최대 6회 재시도합니다. 현재 revision 포인터는 current_records, 과거 revision/document/event 및 published_exports는 갱신·삭제 금지입니다. 기존 파일 기반 결과는 해시 검증 후 추가로 읽어들이며 원본을 보존합니다. 정책 변경은 새 실행, 재개는 기존 스냅샷입니다.

최종 파일은 Output/DB_Select_Final.xlsx 하나입니다. 01_논문스크리닝, 02_확정DB, 03_확정논문, 04_제외논문, 05_보류논문 순서이며 config/db_select/excel_template.json의 정확한 헤더를 사용합니다. 공유 데이터셋은 한 행에 연결 논문 번호/PMID를 세미콜론으로 기재합니다. 이전 공식 출력 바이트는 SQLite preserved_outputs/published_exports에 보존합니다. 최신 검수 후 Excel은 export해야 하며 manifest의 generation_id로 대응 여부를 확인합니다.

테스트: `python -m pytest -q tests/test_select.py`. 데모: `python -m k_melloddy select demo --base demo_runs --project-name SelectDemo --render`.

한계: 실제 제공자/LLM은 미연결, 실제 웹 smoke test 미실행, 기본 수집기는 PDF/JavaScript/인증 자료·부록/저장소 전체 조사 미지원, 전체 데이터 파일 다운로드는 다음 단계 책임입니다. Excel은 artifact-tool Node runtime이 필요하며 런타임 경로 설정은 루트 README 참조. 긴 원문 전체는 누적 JSON에 보존하고 Excel에 참조 위치를 표시하며 Excel 행 높이 제한상 모든 글자가 한 화면에 보이지 않을 수 있습니다.


## Liver 내부 번호 (2026-11-03 변경)

새 Liver 논문은 Liver-00001 형식으로 P 없이 최소 5자리 숫자를 사용합니다. 10,000번은 Liver-10000입니다. 99,999를 초과하면 자릿수를 늘리며 중복·순환하지 않습니다. 이미 발급된 ID는 수정하지 않으며 다른 장기 형식은 유지합니다. DB_Select는 새 형식과 기존 LIVER-P000001 형식을 모두 숫자 순서로 인식합니다. 재개/재내보내기는 기존 매핑을 유지합니다. 오프라인 테스트: tests/test_collection.py::test_liver_five_digit_ids_and_select_handoff.


2026-11-03: Select는 --limit/--order로 범위를 고정하며 --review-file로 명시적 Codex 세션 검수만 재생합니다. 미작성 단계는 미완료이며 자동 추론하지 않습니다. capture_review.py 입력은 Collect manifest/ID 목록, 출력은 관측 근거 입력 JSON입니다. 실제 네트워크는 명시적 호출에서만 사용하며 원문 확인 완료를 자동 보증하지 않습니다. submitted_review.py는 입력/정책 해시를 검증합니다. Collect DOI/PMCID는 참고문헌을 제외한 직접 ArticleIdList에서 추출하도록 수정했습니다. 기존 결과는 보존합니다. 상세 명령·상태·재개·제한은 Liver 단계 README 및 Output/pilot10_review_report.md를 참조하세요.


## liver-v3 및 시범 검수 표시

liver-v3의 확장 예시·재검증·포함 요건·decision_notes는 스키마 검증 후 정책 스냅샷에 포함합니다. 기존 v1/v2 필수 필드는 유지합니다. ReviewIncomplete는 검수자가 제출한 구체적인 미완료 사유를 final.reason에 저장하고 기술 예외 유형은 이벤트로 분리합니다. fetch_error의 Excel 표시는 미확정입니다. P02 보류는 최종 포함/제외가 아니며 미완료 원문 조사와 구분합니다. 테스트: test_extended_liver_policy_and_incomplete_display 및 전체 pytest. 이번 결과/한계/재검증 대기는 Output/pilot20_liverv3_report.md에 기록했습니다.


## Stabilization update

See [stabilization contract](stabilization.README.md) for changed inputs/outputs, bounded automatic-pass configuration, start/end audit, transport/CSV handling, strict final checks, crash/resume and offline/live tests.


## Screening data columns

The evidence-backed [data observation contract](data_observations.README.md) defines response fields, extraction/validation, JSON persistence, J?M mapping, unknown/excluded states, audit, resume, tests and limitations. Verdict-independent observations never register confirmed datasets.


## P02 29-paper targeted revalidation

The explicit campaign preserves the other 71 records, checkpoints each paper in SQLite and retains prior JSON/PRISMA/Excel snapshots. Article access and data availability are recorded separately. See `src/k_melloddy/db_select/revalidation_campaign.README.md` and `revalidation_access.README.md` for the command, stage audit, units, validation, retries, resume, tests and access limitations. The final workbook still contains all 100 papers and the same five sheets.


## Full workflow update (2026-11-03)

The optional full_workflow entry point adds sequential per-paper stages 0/1/2/3. Source TI/AB absence records TIAB_ABSENT and missing fields; source E01/E02 exclusions do not require unnecessary Full Text requests. Official identifiers are still required before article access. First-pass uncertainty is first_pass_pending, never a final P code. A second-stage decision requires an evidence-hash-bound session reviewer answer; unavailable answers remain AWAITING_REVIEW.

Pending papers receive a separate deep round and terminal pending records have auto_retry=false. Each request and stage transition has immutable evidence plus atomic resume checkpoints. Workflow PRISMA projections use one latest outcome per paper/stage/round. Source inputs, previous runs and publications remain preserved. Existing five-sheet Excel and 16/15 columns are unchanged. Run-specific outputs are under Runs/SESSION/published/PUBLICATION_ID.

Validation/retries/resume/commands/tests/limitations: see src/k_melloddy/db_select/full_workflow.README.md and full_workflow_access.README.md. Offline coverage includes missing TI/AB, E01/E02, explicit review boundaries, one-paper-at-a-time deep review, terminal retry suppression, structured JSON sampling and existing identifier/access/decision tests. No unresolved scientific review is reported complete.
