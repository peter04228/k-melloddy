# 2.6 Dataset_Verification

Algorithm: Validate actual file/API access, toxicity features and structure; insufficient access evidence retains an auditable pending state.

Inputs: 모델 후보·수집 근거

Outputs: 검증된 데이터셋 후보 또는 검증 오류

# DB_Select verified workflow (2.0)

## Pending-pass audit update

The revalidation contract below distinguishes initial P-code/time, each paper-level attempt, URL access outcomes, current verdict, pass completion and scientific resolution. Independent BioStudies/Zenodo searches and official PMC XML supplement publisher discovery. Explicit `revalidate --additional-pass` performs one bounded extra sweep without resetting history. P01/P03/P04 are preserved on failed revalidation; evidence-backed TI/AB reclassification can end a pending case before full-text collection. Final PRISMA/JSON expose initial and post-revalidation counts; Excel format is unchanged.

## Inputs, outputs and units

Input: immutable DB_Collect manifest and internal master, organ YAML and explicit reviewer submissions/provider. One unit is one `(paper_id, PMID)` pair. Original values stay in `source_record`; official values are stored separately in `verified_metadata`, with differences in `metadata_verification.mismatches`. The CLI uses `VerifiedSelector`. The legacy `Selector` remains for compatibility and offline fixtures.

Outputs: append-only SQLite revisions/events/documents, three cumulative JSON files, twelve stage PRISMA JSON files and one five-sheet `DB_Select_Final.xlsx`. The global LLM provider remains unconfigured. `--review-file` supplies explicit human/session review proposals; it does not generate model judgments.

## Algorithm and states

1. Re-fetch official PubMed XML by exact PMID. Validate PMID, DOI, PMCID, Title and publication year before any Full Text URL is constructed.
2. Check legal PMC text, publisher text, then alternative paths found by exact PMID and title. Use only official identifiers, never stale input DOI/PMCID.
3. Review Methods, Data Availability, Supplementary, Repository, actual file/API, toxicity features and structure, then decide E03–E08 or P01–P04. HTTP access alone is not a completed scientific review.

TI/AB judgments use the complete organ YAML and quoted title/abstract evidence. Candidates must identify exposure and a toxicity endpoint. Mere keyword mentions, exposure/toxicity analysis and verified public data are separate states. Therapeutic efficacy, general liver disease and liver cancer do not by themselves establish drug-induced liver toxicity. `public_data_status=verified` requires a confirmed dataset, not a GEO mention.

Final states are only `confirmed` (포함), `excluded` (제외), `pending` (보류). Internal `blocked_verification` is an operational hold, never an automatic scientific exclusion. It receives an explicit P02 hold reason and prevents run completion until verification is repaired. Old legacy runs may retain their historical `fetch_error` states without being rewritten.

P01: data is suggested but its public path remains unresolved after investigation. P02: Full Text verification remains unavailable after multiple routes, retries and alternative lookup. P03: a repository/file location exists but actual file access or contents remain unverified. P04: data is accessible but its structure, features or eligibility remain unclear. P01/P03/P04 proposals still pass the existing evidence preconditions in `decision.py`. A single HTTP 403 or JavaScript challenge cannot establish a reviewed P02. Insufficient evidence never establishes E03–E08.

## Audit, retries and resume

Each record stores policy/source hashes, official XML and checksum, input/official differences, attempted URLs, final URLs, response status, failure reason, attempt number, UTC timestamp, response sample hash and workflow states. Scientific sections stay unreviewed until actual review evidence exists. Revalidation records previous/new decisions and unresolved actions even when the outcome is unchanged.

Process selected papers in ascending numeric internal ID order. Commit one paper and its mappings/final events to SQLite, then regenerate cumulative JSON before the next paper. `--order desc --limit 20` selects the highest twenty IDs; processing still ascends within that selection. Existing IDs and earlier revisions stay fixed.

After the initial pass, one automatic pending sweep is allowed; explicit revalidation performs one fresh sweep up to the configured maximum. Each attempt re-fetches metadata and public access evidence. Resume skips committed valid reviews. Use a new run for changed policy, and `--resume RUN_ID` for the same frozen scope/policy. Export reconstructs derived files from SQLite without repeating network review. A locked Excel leaves committed reviews intact; close it and repeat export.

## Validation and PRISMA

The final scope must exactly match all input ID/PMID pairs, with no duplicates, missing papers or invalid final states. Check exclusion reasons, P01–P04 histories, included dataset mappings, official PMID/XML checksums and evidence sample checksums. Require `included + excluded + pending = input_count`; blocked verification or missing required revalidation prevents COMPLETED. COMPLETED denotes a fully accounted triage pass, not resolution of every pending paper. An upstream PARTIAL Collect remains ineligible for downstream release.

Each stage uses latest per-paper events and preserves older audit events. Its paper counts satisfy `input = forwarded + excluded + pending + fetch_error`. The eligibility stages contain only papers reaching that stage; their input need not equal the full screening scope. Final PRISMA, cumulative JSON, SQLite and Excel counts must agree. JSON files share a generation ID, contain ascending paper arrays and join by internal ID/PMID.

Excel retains exactly `01_논문스크리닝`, `02_확정DB`, `03_확정논문`, `04_제외논문`, `05_보류논문`, existing 16/15 columns and header positions. Verified metadata is used for display without modifying Collect. Published workbook/JSON snapshots and earlier output bytes remain archived in SQLite.

## Commands and tests

```powershell
python -m k_melloddy select run --organ Liver --limit 20 --order desc --review-file PATH
python -m k_melloddy select revalidate --organ Liver --resume RUN_ID --review-file PATH
python -m k_melloddy select export --organ Liver --resume RUN_ID --render
python -m pytest -q tests/test_verified_select.py tests/test_select.py
python -m pytest -q
```

Offline tests inject official metadata and HTTP responses; no live collection is performed by pytest. They cover reference DOI contamination, immutable originals, wrong PMID refusal, single-route refusal, wrong-page retry, ascending processing, scope preservation, blocked completion and resume.

## Limitations

The default HTTP investigator captures bounded public response samples. It does not bypass authentication, solve JavaScript challenges, interpret all PDFs or perform an expert Methods/data review. Accessible full text still needs a reviewer/provider with the required evidence and workflow states. PubMed book records are not supported by the current article parser and remain blocked. DB_Download and DB_Preprocessing remain contracts only.


## Stabilization update

See stabilization contract below for changed inputs/outputs, bounded automatic-pass configuration, start/end audit, transport/CSV handling, strict final checks, crash/resume and offline/live tests.


## Screening data columns

The evidence-backed data observation contract below defines response fields, extraction/validation, JSON persistence, J?M mapping, unknown/excluded states, audit, resume, tests and limitations. Verdict-independent observations never register confirmed datasets.


# Pending revalidation

## Inputs, algorithm, states and units

Input: the frozen selected paper scope, committed initial revisions, current P01–P04 records, organ YAML `pending_revalidation` tasks and explicit reviewer/provider proposals. One revalidation attempt means one paper-level pass, not one HTTP retry. The unit for counts is paper, except `revalidation_attempt_count`, which counts committed paper-level passes.

The engine finishes and commits the entire initial scope before forming a separate pending list. It sorts that list by numeric internal ID and processes each paper once per pass. P01 searches data clues and direct paths; P02 investigates official/alternative full text and separate supplementary routes; P03 revisits observed repository/file/API locations; P04 revisits files and requires feature/structure review. Exact PMID/title lookup, official PMC XML when available, and independent BioStudies/Zenodo searches supplement publisher links. Search failures and missing observed links remain unresolved work, never proof that no data exists.

TI/AB is reassessed before network full-text collection. Explicit evidence-backed E01/E02 can resolve pending without unnecessary full-text access. Otherwise included/excluded Full Text proposals must pass section/file/structure and citation validation. Valid stronger evidence clears the P-code; insufficient new evidence preserves pending. Exceptions during P01/P03/P04 revalidation retain the specific previous code and mark processing blocked instead of collapsing everything into P02.

## Storage, audit, retries and resume

Commit each paper's new revision, final events and history references atomically. Preserve all prior revisions and initial results. JSON is a derived SQLite view, never the authoritative state. `revalidation_history.json` carries per-paper initial result/P-code/time, PMID/internal ID, committed attempt count, current result, completion/resolution flags and unresolved reason. Each new attempt stores previous/new result, timestamp, actual URL/status/error/retry records, search coverage, metadata verification, final reason and next action. Historical documents remain unchanged; the JSON wrapper supplies their initial/final context.

`revalidation_completed` means the current bounded review pass completed without a processing block. `verification_resolved` means the final state is included or excluded. A completed pass may still leave a scientifically unresolved P-code. Missing supplementary links, blocked full text or failed repository searches are reported explicitly.

Official article XML identity uses its own PMID and title with terminal punctuation normalized. Reference-list identifiers are never accepted. Explicit `revalidation_evidence_review` section attestations must match the URL, exact fetched SHA-256, identity and quoted passages; they can mark Methods/Results reviewed without falsely marking supplementary/repository review complete. Accessible alternative full text may retain P02 only for an independently unresolved publisher supplement access problem, with that reason stated. A reference journal's `Supplement` query text is not a supplementary-material URL.

`--paper-id ID` restricts a revalidation pass to specified pending papers without shrinking the frozen 20-paper export scope. Historical attempts gain derived `audit` fields in JSON; their original hashed documents are unchanged. Legacy completion flags not originally recorded remain null, not inferred.

Automatic execution performs one pending sweep after the initial pass. Explicit `revalidate` respects the configured cap. `--additional-pass` authorizes exactly one further sweep of the current pending list beyond that cap, records started events and never resets attempt counters or changes the frozen policy. It is not enabled by default. Resume skips committed reviews; additional passes require another explicit invocation.

## Counts and final export validation

Metrics come from the first immutable revision and latest committed records: initial processed papers, initial pending papers, cumulative revalidation attempts, distinct revalidated papers, initial-pending to included/excluded conversions, and final pending papers. CLI `this_execution` additionally distinguishes work in the current invocation from the cumulative history. HTTP request counts are not paper-level attempts. JSON history and final PRISMA expose cumulative metrics; Excel keeps its existing five sheets and columns.

Before Excel export, require the exact ID/PMID scope and `included + excluded + pending = input_count`. Validate E/P reasons, histories and dataset mappings, then reconcile JSON/PRISMA/Excel counts. Blocked verification prevents COMPLETED. No result or count is inferred from a missing row.

## Commands and tests

```powershell
python -m k_melloddy select revalidate --organ Liver --resume RUN_ID --review-file PATH
python -m k_melloddy select revalidate --organ Liver --resume RUN_ID --review-file PATH --additional-pass --render
python -m pytest -q tests/test_verified_select.py
python -m pytest -q
```

Tests cover all four P-codes converting to included/excluded, the initial-pass barrier, detailed histories and counts, preservation on reviewer failure, bounded explicit cap override and independent repository discovery despite inaccessible full text. Offline fixtures are not scientific evidence.

## Limitations and module boundaries

`revalidator.py` owns selection and derived metrics; `engine.py` owns pass order and explicit override; `verified_workflow.py` owns evidence checks and history creation; `access_workflow.py` owns bounded public requests/discovery; `submitted_review.py` supports separate `revalidation_tiab`/`revalidation_fulltext` submissions without modifying initial proposals; `persistence.py` projects committed history; `prisma.py` adds metrics. These modules share the inputs, outputs, states, audit, resume and validation contract above.

Repository searching is bounded, not exhaustive. A matched record is not a verified dataset; failed searches do not establish absence. PDF/JavaScript or institution-only text still requires legal access and human/provider review. Global LLM remains unconfigured. No exclusion is inferred merely from exhausted retries.


## Stabilization update

See stabilization contract below for changed inputs/outputs, bounded automatic-pass configuration, start/end audit, transport/CSV handling, strict final checks, crash/resume and offline/live tests.


# DB_Select stabilization and automatic verification

## Purpose, inputs, outputs and processing order

This update strengthens existing modules rather than replacing the selection pipeline. Input remains a Collect manifest with immutable internal numbers/PMIDs, source records, organ YAML and an explicitly configured reviewer. Output remains SQLite plus three cumulative JSON files, per-stage PRISMA and the unchanged five-sheet Excel contract. Process ascending internal IDs, one paper/commit at a time, then a separate ascending pending pass. Counts use papers; dataset counts and HTTP attempts are separate units.

## Changed modules

| Module | Specific correction |
|---|---|
| official_metadata.py | Audit stable internal number and official author surnames; record truncated HTTP responses as metadata failures |
| metadata.py | Reject a missing/non-string internal ID explicitly before processing |
| access_workflow.py | Check XML's own PMID/DOI/title; expose author/title/ID checks; try legal PMC XML during initial retrieval too; distinguish timeout/HTTP/truncation/redirect; sample CSV/TSV headers and row shape |
| policy.py / engine.py / revalidator.py | Optional configurable automatic pass target, bounded independent passes, started audit events, richer initial/final PRISMA metrics |
| verified_workflow.py | Start/end times, distinct metadata processing error, final E-code/evidence/history/policy/dataset mapping validation |
| persistence.py / prisma.py | Preserve original history content, expose derived start/end fields and detailed metrics, explicit stage conservation exception |

No keyword-only judgments or inferred scientific data are introduced. Successfully read CSV headers are structural evidence only; inclusion still requires source citations, organ relevance, drug/endpoint/value columns, independence and an observed public path. Main code remains in `src/k_melloddy`; project folders contain only inputs/docs/evidence/results.

## Configuration and commands

In `config/db_select/common_rules.yaml`, `max_revalidation_attempts` remains the lifetime default cap. Optionally add `automatic_revalidation_attempts: 2` to request two bounded automatic passes after initial processing; omission preserves the prior default of one. Require `1 <= automatic_revalidation_attempts <= max_revalidation_attempts`. Existing runs retain their frozen policy. `--additional-pass` is an explicit extra single pass, never an unbounded retry.

```powershell
python -m k_melloddy select run --organ Liver --limit 20 --order desc --review-file PATH --render
python -m k_melloddy select run --organ Liver --resume RUN_ID --review-file PATH
python -m k_melloddy select revalidate --organ Liver --resume RUN_ID --review-file PATH
python -m k_melloddy select export --organ Liver --resume RUN_ID --render
python -m pytest -q
$env:KMELLODDY_LIVE_SELECT='1'
python -m pytest -q tests/test_select_live.py
Remove-Item Env:KMELLODDY_LIVE_SELECT
```

The `desc` option selects the highest IDs for the pilot, but actual processing stays ascending. The live test is explicitly opt-in and separate from deterministic mocked tests. The global provider remains unconfigured; session submissions are explicit reviewed proposals, not automatic inference.

## Errors, states, evidence and revalidation

PubMed lookup must match PMID before verified identifiers can seed access. Original metadata is preserved. Metadata failure emits `METADATA_VERIFICATION_ERROR`, retains a blocked pending state and never excludes a paper. HTTP 403, 404, timeout, redirect, challenge, wrong identity and incomplete download are separate response facts. Unavailable author/ID checks remain null/false rather than being claimed as verified. XML identity checks use its own metadata rather than cited references.

P01–P04 retain their existing evidence prerequisites. A failed P03/P04 retry does not reset it to P02. New successful evidence can change pending to included/excluded. History stores immutable initial result, initial P-code/time, per-pass start/end, URLs/access outcomes, references, old/new final state/code, completion/resolution flags and unresolved reasons. Old histories without start/end keep null values; timestamps are not invented.

Public API/file responses are bounded by `max_response_bytes`, `timeout_seconds` and link limits. Downloaded sample headers are not a complete-dataset claim. PDF/JS/closed institutional sources and exhaustive repository review remain outside the default HTTP implementation. Independent scientific dataset confirmation still requires an explicit provider/reviewer.

## Atomic storage and recovery

One paper's revision, final PRISMA movement and dataset mappings commit atomically to SQLite before JSON projection and before the next paper. Resume rebuilds a partially published JSON generation from committed SQLite and skips completed papers. Start events remain auditable if termination occurs before a committed revalidation. Prior revisions, documents, IDs and published result snapshots are retained; only derived latest views refresh. A locked workbook can be exported again after unlocking without redoing review.

The new hard-exit test actually terminates a subprocess with `os._exit(77)` immediately after the first SQLite commit, then resumes in another process and verifies the saved paper/revision is unchanged. This supplements existing KeyboardInterrupt and failed JSON-publish recovery tests.

## PRISMA and final validation

History/PRISMA metrics separate initial processed and pending counts, TI/AB present/absent, E01/E02, Full Text targets, E03–E08, initial P01–P04, revalidation targets/attempts, included/excluded conversions, retained pending and final outcomes. Latest final states and initial states are not mixed.

Before final output, require all original ID/PMID pairs exactly once, valid final E/P codes, supported full-text evidence, intact policy/history hashes, registered dataset mappings and `included + excluded + pending = input`. Verify each stage conservation equation. Excel values, headers, row partitions, linked datasets and JSON/PRISMA counts must agree. Any failed check prevents COMPLETED; operationally blocked review also prevents completion even when rows sum correctly.

## Tests and limits

`tests/test_select_stabilization.py` adds strict corruption checks, real subprocess termination, configured finite passes, timestamp checks, Excel/PRISMA mismatch rejection, duplicate/missing IDs, CSV parsing and repository transport failures. Existing selection/verified tests cover DOI/PMCID mismatch, abstract absence, E01–E08, confirmed/multiple datasets, P-code transitions, wrong article URLs and atomic JSON recovery. `tests/test_select_live.py` separately verifies live official PMID/PMC access; default pytest skips it. External service behavior can change, so live failures are reported independently.

Actual regression evidence and per-paper before/after decisions are recorded in the new project output report. No final outcome count is used as a target. DB_Collect source data and completed historical runs are preserved; DB_Download/DB_Preprocessing remain contracts only.


# Evidence-backed data observations and screening J–M

## Purpose and root cause

The old `paper_row()` read J/K from registered `datasets` or `source_databases`, but L/M only from `datasets`. Pending/excluded proposals cannot register datasets; automatic P02 proposals also had empty source lists. As a result, known DB mentions in title/abstract/full text never reached these columns. There was no fallback status for excluded rows. The confirmed-only condition in `workbook_payload()` belongs to the confirmed DB sheet and remains unchanged.

## Inputs, outputs and schema

TI/AB and Full Text proposals can now supply optional `data_observations`, independently of their verdict. Each observation has `name`, `relationship` (reuse/new/derived/unknown), `public_status` (unknown/reported_public/verified_public/restricted/not_public), `verification_level`, nullable `url` and cited `evidence_refs`. A mention is descriptive evidence, not dataset registration or an inclusion decision. Old proposals remain valid.

`validate_observations()` requires accessible source quotations, the named DB in the quotation, actual material response URLs for links, and evidence at least as strong as any claimed file verification level. Title/abstract uses evidence ID `tiab`; Full Text/repository evidence uses its immutable evidence ID. Article DOI/PMC URLs and search URLs cannot stand in for data links. A paper saying data is public is distinct from verified public access.

`source_observations()` converts cited legacy source DB information only when its name and claimed material URL are supported. Unsupported legacy labels remain legacy source information but do not gain a new verified data link. Explicit section-review submissions can include the same observations; normal LLM/provider responses use the same schema. The global provider is still unconfigured.

## Processing, states, units and Excel

Validate TI/AB facts before branch selection, preserving facts even for E01/E02. Validate Full Text facts against captured evidence and merge them independently of the final verdict. Preserve prior observations on pending revalidation. Evidence remains in SQLite documents and `evidence_log.json`; current descriptive facts are in `screening_results.json` records. Units are observations per paper; they do not increase confirmed dataset or PRISMA paper counts.

J = observed DB/dataset names. K = supported relationship. L = actual public-access/verification level. M = observed, validated material URL only. Unknown values display `미확인`. TI/AB exclusions explicitly show `해당 없음 — TI/AB 제외로 공개·다운로드 검증 미수행`; this means no screening download check was required, not proof that no database exists. An investigated Full Text exclusion without data facts shows `조사 범위 내 공개 데이터 미확인`, not absolute nonexistence.

`reported_public` never becomes verified access/download. No data URL is synthesized from a DB name or accession. Different facts and levels remain separate in JSON. Same-level display text is deduplicated; row heights fit J–M without changing column order/count. Existing 5 sheets and fixed 16/15-column headers remain unchanged. Confirmed DB registration still requires the existing file/API and scientific eligibility checks.

## Existing records, audit, retries and resume

`enrich-data` adds reviewed facts to an existing run without rerunning science or changing verdicts. The input JSON identifies `run_id`, paper IDs, PMID and observations. Validate all submitted facts against the immutable input/evidence before writing. Each changed paper gets an append-only revision plus an evidence annotation document, then JSON regeneration. Original source, IDs, metadata, verdict, reasons and revalidation counters stay unchanged. Repeat execution is idempotent: unchanged observations create no extra revision. Existing finalized output snapshots remain in SQLite.

A failed/locked Excel export leaves committed observations intact. CLI marks the run PARTIAL on failed enrichment/export; close the file and repeat the same command. Successful completion restores the computed run status. No approval is needed to repeat an already authorized export.

```powershell
python -m k_melloddy select enrich-data --organ Liver --resume RUN_ID --observations-file PATH --render
python -m pytest -q tests/test_data_observations.py
python -m pytest -q
```

## Validation and tests

Validate IDs/PMIDs, quotation and evidence hashes, public/file claims and actual URL kinds. QC checks the observation references across the paper's immutable evidence history, including earlier revalidation evidence. Before export, existing scope, E/P, dataset mapping, JSON/PRISMA conservation and all-cell Excel checks still apply. Enrichment emits final-state events with unchanged scientific outcomes; it does not count as an extra revalidation pass.

Tests cover pending/excluded display, explicit unknown status, fabricated names/URLs, article URL rejection, overstated download level, observed repository links in pending papers, legacy source URL handling, atomic append-only enrichment and repeated-command idempotence. The real 20-paper check uses existing captured source material; no new scientific decision or network availability is inferred.

## Limitations

Automatic HTTP fetching does not identify every dataset or establish a scientific relation by itself. A reviewer/provider must supply evidence-backed descriptive facts; known cited source DB facts are converted conservatively. The seven-paper retrospective enrichment contains 11 named facts but no verified material URL. Therefore M legitimately remains `미확인` for this corpus. The observations do not resolve remaining P-codes or create confirmed DBs.


## P02 29-paper targeted revalidation

The explicit campaign preserves the other 71 records, checkpoints each paper in SQLite and retains prior JSON/PRISMA/Excel snapshots. Article access and data availability are recorded separately. See `src/k_melloddy/db_select/revalidation_campaign.README.md` and `revalidation_access.README.md` for the command, stage audit, units, validation, retries, resume, tests and access limitations. The final workbook still contains all 100 papers and the same five sheets.


## Full workflow update (2026-11-03)

The optional full_workflow entry point adds sequential per-paper stages 0/1/2/3. Source TI/AB absence records TIAB_ABSENT and missing fields; source E01/E02 exclusions do not require unnecessary Full Text requests. Official identifiers are still required before article access. First-pass uncertainty is first_pass_pending, never a final P code. A second-stage decision requires an evidence-hash-bound session reviewer answer; unavailable answers remain AWAITING_REVIEW.

Pending papers receive a separate deep round and terminal pending records have auto_retry=false. Each request and stage transition has immutable evidence plus atomic resume checkpoints. Workflow PRISMA projections use one latest outcome per paper/stage/round. Source inputs, previous runs and publications remain preserved. Existing five-sheet Excel and 16/15 columns are unchanged. Run-specific outputs are under Runs/SESSION/published/PUBLICATION_ID.

Validation/retries/resume/commands/tests/limitations: see src/k_melloddy/db_select/full_workflow.README.md and full_workflow_access.README.md. Offline coverage includes missing TI/AB, E01/E02, explicit review boundaries, one-paper-at-a-time deep review, terminal retry suppression, structured JSON sampling and existing identifier/access/decision tests. No unresolved scientific review is reported complete.


2026-11-09 공개 원문·보충자료 접근 보완: 검증된 PMID/DOI/PMCID/제목으로 공식 PMC 클라우드의 실제 버전 목록·메타데이터·파일 링크만 조회합니다. 원본 응답·재시도·해시를 보존하며, 큰 파일의 제한된 재수신이 끝난 뒤에도 실제 길이·SHA256·공식 MD5를 재검사합니다. ZIP 접근 성공만으로 데이터 구조나 포함 판정을 추정하지 않습니다. 선택한 멤버·시트·헤더와 화합물 노출 연결성을 검토자가 확인해야 합니다. 기존 완료 결과는 자동으로 다시 판정하지 않습니다. 입력·출력·상태·감사·검증·재시도·재개·명령·테스트·한계의 추가 계약은 src/k_melloddy/db_select/pmc_cloud.README.md 및 full_workflow.README.md를 따릅니다. 관련 오프라인 회귀 30개를 통과했습니다.


2026-11-09 보충 PDF 검수 보완: 실제 완전한 PDF의 바이트 길이·SHA256·공식 체크섬을 확인한 뒤 제한된 텍스트만 추출합니다. 파일 8 MiB·64쪽·250,000자 제한이며 원본 바이트와 접근 이력은 보존합니다. 텍스트 추출만으로 표 열·자료 건수·독립 재사용성 또는 확정을 추정하지 않습니다. 재개 시 미완료 자료만 새 검수 요청에 연결하며 기존 확정 판정은 바꾸지 않습니다. 상세 계약과 명령·상태·재시도·한계는 src/k_melloddy/db_select/full_workflow_access.README.md, 검증은 tests/test_pdf_material.py를 참조합니다. 관련 오프라인 회귀 56개 테스트가 통과했습니다.
## 실제 파일 검증 보완 (2026-11-09)

ZIP 안의 DOCX도 정확한 멤버 이름과 표 번호를 지정하여 이미 확보한 바이트에서 검증할 수 있습니다. 원본 ZIP·공식 체크섬·내부 파일 해시·선택한 표·파생 증거 ID를 함께 보존합니다. 병합 셀·불명확한 헤더는 임의로 정리하지 않으며, 표본 구조 확인만으로 자료 전체 다운로드나 확정을 선언하지 않습니다.

단일 약물 임상표에서 약물명이 파일 자체의 표 제목에만 명시된 경우에는 `drug_identifier: constant:약물명`으로 관찰된 문맥을 명시할 수 있습니다. 같은 실제 파일의 제목 인용이 필요하며, endpoint와 값은 실제 열이어야 합니다. 환자번호를 약물 식별자로 사용하거나 원본에 가상 열을 추가하지 않습니다. 기존 JSON·Excel 열 구성과 정책 파일은 변경하지 않습니다. 검증 실패는 적절한 보류·재검증 대상으로 유지하고 기존 판정은 자동 변경하지 않습니다.

관련 코드·한계·재개·테스트: `src/k_melloddy/db_select/archive_review.README.md`, `src/k_melloddy/db_select/dataset_verifier.README.md`. 회귀 검증: `python -m pytest tests/test_constant_drug_caption.py tests/test_docx_material.py tests/test_archive_review.py tests/test_select.py tests/test_verified_select.py tests/test_projection_streaming.py -q` — 84개 통과. 과거 중단 테스트의 오류 주입 대상도 실제 누적 JSON 작성 함수인 `atomic_json`에 맞췄습니다.


## Supplementary CSV structure verification (2026-11-09)

An explicitly selected CSV member inside a captured ZIP can be inspected through `archive_selections` using its exact member path, `sheet: null` and a one-based header row. Parent and member hashes, actual headers and sampled rows remain auditable; no network request, code execution, column synthesis or implicit row-order join occurs. Invalid UTF-8, quoting, widths, headers or formula cells fail validation. Sample structure does not establish whole-file completeness, compound counts, independence or cross-file links. Resume reuses immutable captured bytes. See `src/k_melloddy/db_select/archive_review.README.md` for limits and commands. The related archive/DOCX/verified-workflow tests and decision/projection/caption tests passed 92 cases in two offline groups; existing Windows pytest temporary-directory cleanup warnings occurred after successful exit.
# Selected clinical DOCX table context

The exposure paragraph must be the immediately preceding sibling of the exact selected table, preventing exposure attribution from a preceding case table's cells. Full workflow plus archive/caption/DOCX offline regression: 48 passed (`python -m pytest tests/test_full_workflow.py tests/test_docx_material.py tests/test_constant_drug_caption.py tests/test_archive_review.py -q`); the existing Windows pytest temporary-directory cleanup warning occurred after exit success.

For an explicitly selected patient table, `include_preceding_paragraph: true` retains its immediately preceding paragraph and exact original headers. This permits a cited `constant:<drug>` only when the same selected record supplies the exposure text and measured endpoint/value columns. It adds no source column, joins no cases and infers no compound/feature counts. Missing context or a mismatched drug fails validation. Original files, finalized records and prior default selections stay unchanged; selection IDs, parent hashes and accepted answers provide the audit/resume trail. Verify offline with `python -m pytest tests/test_docx_material.py tests/test_constant_drug_caption.py tests/test_archive_review.py -q` (31 passed). Clinical interpretation and independence still require manual review.
