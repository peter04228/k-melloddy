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
