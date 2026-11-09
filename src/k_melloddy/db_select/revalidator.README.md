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

See [stabilization contract](stabilization.README.md) for changed inputs/outputs, bounded automatic-pass configuration, start/end audit, transport/CSV handling, strict final checks, crash/resume and offline/live tests.


## Full workflow update (2026-11-03)

The optional full_workflow entry point adds sequential per-paper stages 0/1/2/3. Source TI/AB absence records TIAB_ABSENT and missing fields; source E01/E02 exclusions do not require unnecessary Full Text requests. Official identifiers are still required before article access. First-pass uncertainty is first_pass_pending, never a final P code. A second-stage decision requires an evidence-hash-bound session reviewer answer; unavailable answers remain AWAITING_REVIEW.

Pending papers receive a separate deep round and terminal pending records have auto_retry=false. Each request and stage transition has immutable evidence plus atomic resume checkpoints. Workflow PRISMA projections use one latest outcome per paper/stage/round. Source inputs, previous runs and publications remain preserved. Existing five-sheet Excel and 16/15 columns are unchanged. Run-specific outputs are under Runs/SESSION/published/PUBLICATION_ID.

Validation/retries/resume/commands/tests/limitations: see src/k_melloddy/db_select/full_workflow.README.md and full_workflow_access.README.md. Offline coverage includes missing TI/AB, E01/E02, explicit review boundaries, one-paper-at-a-time deep review, terminal retry suppression, structured JSON sampling and existing identifier/access/decision tests. No unresolved scientific review is reported complete.
