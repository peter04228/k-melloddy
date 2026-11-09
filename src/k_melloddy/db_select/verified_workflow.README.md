# DB_Select verified workflow (2.0)

## Pending-pass audit update

The [revalidation contract](revalidator.README.md) distinguishes initial P-code/time, each paper-level attempt, URL access outcomes, current verdict, pass completion and scientific resolution. Independent BioStudies/Zenodo searches and official PMC XML supplement publisher discovery. Explicit `revalidate --additional-pass` performs one bounded extra sweep without resetting history. P01/P03/P04 are preserved on failed revalidation; evidence-backed TI/AB reclassification can end a pending case before full-text collection. Final PRISMA/JSON expose initial and post-revalidation counts; Excel format is unchanged.

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

See [stabilization contract](stabilization.README.md) for changed inputs/outputs, bounded automatic-pass configuration, start/end audit, transport/CSV handling, strict final checks, crash/resume and offline/live tests.


## Screening data columns

The evidence-backed [data observation contract](data_observations.README.md) defines response fields, extraction/validation, JSON persistence, J?M mapping, unknown/excluded states, audit, resume, tests and limitations. Verdict-independent observations never register confirmed datasets.


## Targeted P02 campaign update

Targeted campaigns carry the independent verification state into the paper revision and revalidation history, with previous/final decision and campaign ID. Official metadata supplies all article identifiers. See [campaign](revalidation_campaign.README.md) and [access](revalidation_access.README.md) for inputs, outputs, algorithm, states, units, audit, validation, retries, resume, commands, tests and limitations.


## Full workflow update (2026-11-03)

The optional full_workflow entry point adds sequential per-paper stages 0/1/2/3. Source TI/AB absence records TIAB_ABSENT and missing fields; source E01/E02 exclusions do not require unnecessary Full Text requests. Official identifiers are still required before article access. First-pass uncertainty is first_pass_pending, never a final P code. A second-stage decision requires an evidence-hash-bound session reviewer answer; unavailable answers remain AWAITING_REVIEW.

Pending papers receive a separate deep round and terminal pending records have auto_retry=false. Each request and stage transition has immutable evidence plus atomic resume checkpoints. Workflow PRISMA projections use one latest outcome per paper/stage/round. Source inputs, previous runs and publications remain preserved. Existing five-sheet Excel and 16/15 columns are unchanged. Run-specific outputs are under Runs/SESSION/published/PUBLICATION_ID.

Validation/retries/resume/commands/tests/limitations: see src/k_melloddy/db_select/full_workflow.README.md and full_workflow_access.README.md. Offline coverage includes missing TI/AB, E01/E02, explicit review boundaries, one-paper-at-a-time deep review, terminal retry suppression, structured JSON sampling and existing identifier/access/decision tests. No unresolved scientific review is reported complete.

The revalidation action includes prior_evidence_ref, bound to the same run and paper. The session collector merges prior evidence without replacing new attempts or mutating old documents. History access_results distinguishes reused_from_prior_round from new HTTP attempts. Test: tests/test_prior_evidence_merge.py.


## Liver v4 / isolated CSV review
Inputs: liver-v4 organ YAML and UTF-8 CSV with source numbering. Output: separate run namespace; existing research and finalized artifacts remain unchanged. Grouped endpoints and full organ criteria are passed to evidence-bound review; keywords are never automatic verdicts. Step 0 requires both title and abstract; either missing (including whitespace) excludes immediately with TIAB_ABSENT before Step 1. Step 1 E01/E02 or candidate/uncertain; Step 2 verifies data; Step 3 uses code-specific P tasks with one automatic round. Units: papers and datasets remain separate. Existing transitions, immutable revisions, URL attempts and PRISMA record each state. Resume requires identical source and policy hashes. CSV source is frozen as source.csv; no Excel conversion. Command: python -m k_melloddy.db_select.spreadsheet_workflow --source INPUT.csv --root NEW_RUN --prepare-only. Tests: tests/test_liver_v4_csv.py and existing workflow/decision tests. Limitation: verification: null supplies no additional rules; actual inclusion still requires the existing evidence and file-structure validators. No live review is implied by offline tests.


2026-11-06 presence correction: both Title and Abstract are required; missing fields are preserved in the TI/AB exclusion reason. No keyword or LLM inference fills missing source text. Tests: tests/test_liver_v4_csv.py and tests/test_full_workflow.py. Existing finalized runs remain immutable; the changed policy hash requires a separate run/revision rather than resuming an old policy.
