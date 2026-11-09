# Independent revalidation discovery

## 명시적인 초록 검토와 본문 판별 (2026-11-09)

오프라인 회귀 결과: 71 passed (36.45s), exit code 0. 기존 Windows pytest 임시 폴더 정리 PermissionError는 테스트 성공 후 발생했다.

입력은 기존 `evidence_review.content_access_review`의 `abstract_only` 판정과 실제 인용 근거다. 접근·논문 식별·인용 검증을 통과하면 복사된 응답에 `reviewed_content`를 기록한다. 출판사 메뉴의 다른 책 제목에 나온 Methods 때문에 초록 페이지가 본문으로 집계되는 것을 막는다. 해당 응답의 본문 판별·접근 상태에만 반영하며, 별도 경로의 실제 본문은 계속 검토해야 한다. HTTP 상태·내용·URL·해시·원본 캐시와 완료된 판정은 보존한다. 자동 초록 판정이나 데이터 검증 성공을 생성하지 않는다.

단위는 응답 한 건이며 기존 답변 해시·검토 시각·증거 참조로 추적한다. 추가 네트워크 요청은 없고 기존 제한 재시도·논문별 저장/재개 절차를 사용한다. 검증: `python -m pytest tests/test_reviewed_abstract_content.py tests/test_full_workflow.py tests/test_verified_select.py tests/test_revalidation_campaign.py tests/test_select_stabilization.py -q`. 메뉴의 Methods 오인식, 실제 별도 본문 보호, 미인용 표시 거부, 검색·재시도 조건 및 원본 보존을 확인한다. 한계: 검토자가 실제 페이지 내용을 읽고 명시적으로 분류해야 한다.

PubMed and OpenAlex abstract/index pages cannot establish full-text access. PMC OCR prose in a `preformat` element is recognized as available text but is not automatically reviewed. Explicit hash-checked review of observed scan pages is supported by [captured review](captured_review.README.md). Each scan GET retains its original timestamp and URL. The human review and network pass are separately labelled in history.

Inputs: officially verified PMID/title/DOI/PMCID, policy, previously evidenced DB names and optional reviewer-observed discovery URLs. The collector uses only verified metadata for article routes. Inputs remain unchanged.

Algorithm: reuse the official PubMed/PMC/Europe PMC/DOI routes, inspect actual PubMed publisher linkouts, query OpenAlex by title and follow matching title/DOI locations, and independently search PMID, title and known DB names with dataset/download/access terms. Follow observed same-host article PDF links. Requests are bounded, and record the requested/final URL, timestamp, HTTP status, attempt, failure reason and response sample. Extra discovery is only enabled for an explicit targeted campaign. Search results are leads, not proof of paper identity or data availability.

Outputs: evidence bundle and separate tri-state verification fields. `true`, `false`, and `unknown` are distinct. Failed access never establishes that data do not exist. A named database does not establish public, accessible, downloadable or reusable data. An accessible paper PDF does not establish accessible research data. Text extraction does not mark Methods/Data Availability as reviewed. Scanned JATS containers with `<body>` but no article prose are not reported as read full text. Article PDFs are bounded at 8 MiB; textless scans require separate visual review/OCR. No paywall or authentication bypass is attempted.

States/audit: each HTTP attempt retains its status and evidence ID. Human review is separate from retrieval. P01 requires a cited concrete data clue; P02 requires unresolved access after alternate routes; P03 requires a cited observed material location; P04 requires cited actual file/API material. Confirmed/excluded decisions still require the existing scientific gates. Units are HTTP attempts in access logs and papers in PRISMA; they must not be summed together.

Retry/resume: bounded transport retries use the base collector; paper-level resume uses the campaign SQLite revision. No successful request is invented for cached or inaccessible content. Revalidation history records the old/new decision, attempt count, unresolved questions and verification state. Run the command in [campaign contract](revalidation_campaign.README.md). Tests: `python -m pytest -q tests/test_revalidation_campaign.py tests/test_verified_select.py tests/test_select_stabilization.py`. Limitations include search bot challenges, paywalls, scanned PDFs, stale indexes and missing repository links. Discovery completion is not scientific review completion.

PubMed linkouts must carry the official full_text category; login/mail/collection navigation links are excluded. Observed URLs with spaces are percent-encoded before requesting. Public file access does not by itself establish a reuse license; dataset_reusable remains unknown unless separately verified.

Independent DB-name search queries run with at most three separate HTTP clients within a single paper. Results are merged in input order. Paper review and SQLite commits remain strictly sequential; no next paper starts before the current paper is saved. Injected test openers use the sequential path. Request-level progress is available through campaign --trace-http.


## Full workflow update (2026-11-03)

The optional full_workflow entry point adds sequential per-paper stages 0/1/2/3. Source TI/AB absence records TIAB_ABSENT and missing fields; source E01/E02 exclusions do not require unnecessary Full Text requests. Official identifiers are still required before article access. First-pass uncertainty is first_pass_pending, never a final P code. A second-stage decision requires an evidence-hash-bound session reviewer answer; unavailable answers remain AWAITING_REVIEW.

Pending papers receive a separate deep round and terminal pending records have auto_retry=false. Each request and stage transition has immutable evidence plus atomic resume checkpoints. Workflow PRISMA projections use one latest outcome per paper/stage/round. Source inputs, previous runs and publications remain preserved. Existing five-sheet Excel and 16/15 columns are unchanged. Run-specific outputs are under Runs/SESSION/published/PUBLICATION_ID.

Validation/retries/resume/commands/tests/limitations: see src/k_melloddy/db_select/full_workflow.README.md and full_workflow_access.README.md. Offline coverage includes missing TI/AB, E01/E02, explicit review boundaries, one-paper-at-a-time deep review, terminal retry suppression, structured JSON sampling and existing identifier/access/decision tests. No unresolved scientific review is reported complete.

Access validation correction: Elsevier coredata-only XML is bibliographic metadata even when its journal title contains Methods. Actual XML body/rawtext is required by the body heuristic. Administrative blocked_verification records are not terminal scientific verdicts; resume can append a corrected revision while preserving the failed attempt. Tests: test_response_deadline.py, test_full_workflow.py, test_verified_select.py.
# Session access-state compatibility

The derived verification state accepts the explicit access-constraint explanation under `summary`, or the legacy `reason` field. Missing prose stays `unknown`; it never becomes a scientific verdict. Previously committed evidence, answers and record revisions remain unchanged. A validated web-tool excerpt counts as observed article access only after the reviewer attests full-text review. It remains an excerpt (`complete_body=false`), never a downloaded article or verified dataset. Its attempt action is `reviewed web-tool excerpt` and its HTTP status stays null. HTTP captures retain their actual request status and retry history. A session crash before saving a paper resumes that same paper from immutable requests and evidence; the next paper remains blocked until terminal save. Tests: `python -m pytest tests/test_supplement_access_review.py tests/test_revalidation_campaign.py tests/test_web_capture.py tests/test_full_workflow.py`. Tests cover both explanation fields, missing explanations, reviewed versus unreviewed excerpts and accurate transport labels. This is a projection compatibility change, with no change to P-code eligibility or inclusion requirements.

