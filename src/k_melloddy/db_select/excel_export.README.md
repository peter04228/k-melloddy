# excel_export.py

Map validated observations and explicit verification states to J?M; preserve the fixed five-sheet contract.

Inputs, outputs, algorithm, states/units, audit, retries/resume, commands, tests and limitations: [data observation contract](data_observations.README.md).


## 2026-11-03 latest saved-results Excel export

At the user's request, Output/DB_Select_Final.xlsx now reflects all 100 saved records after the 29-paper network revalidation pass. Counts: 0 included, 71 excluded, 29 pending. The prior 71 excluded records are unchanged. Five records remain blocked (14, 76, 85, 88, 95); this is a PARTIAL export, not completed scientific review. The workbook subtitle explicitly states that verification is incomplete. Earlier workbooks are preserved in SQLite preserved_outputs and the campaign baseline.

Validation: cell-by-cell Excel comparison, fixed five-sheet layout and 16/15-column headers, unique IDs/PMIDs, cumulative JSON counts and stage PRISMA conservation passed. Updated scientific QC also passed; processing remains PARTIAL because five reviews are blocked. No manuscript decisions changed during export. Audit: Output/export_audits/39a47896b1494ee09255aab9fc011f03/saved_results_status.json. Reopened workbook hash, all 100 IDs, incomplete-status subtitle and five blocked reasons checked.


## Full workflow update (2026-11-03)

The optional full_workflow entry point adds sequential per-paper stages 0/1/2/3. Source TI/AB absence records TIAB_ABSENT and missing fields; source E01/E02 exclusions do not require unnecessary Full Text requests. Official identifiers are still required before article access. First-pass uncertainty is first_pass_pending, never a final P code. A second-stage decision requires an evidence-hash-bound session reviewer answer; unavailable answers remain AWAITING_REVIEW.

Pending papers receive a separate deep round and terminal pending records have auto_retry=false. Each request and stage transition has immutable evidence plus atomic resume checkpoints. Workflow PRISMA projections use one latest outcome per paper/stage/round. Source inputs, previous runs and publications remain preserved. Existing five-sheet Excel and 16/15 columns are unchanged. Run-specific outputs are under Runs/SESSION/published/PUBLICATION_ID.

Validation/retries/resume/commands/tests/limitations: see src/k_melloddy/db_select/full_workflow.README.md and full_workflow_access.README.md. Offline coverage includes missing TI/AB, E01/E02, explicit review boundaries, one-paper-at-a-time deep review, terminal retry suppression, structured JSON sampling and existing identifier/access/decision tests. No unresolved scientific review is reported complete.

The screening H column distinguishes first-pass uncertainty as 1? ?? from ??; it does not change the final I-column verdict or add columns. Final workbook validation checks all cells against committed records. Targeted workbook/PRISMA regression tests: 2 passed after this label correction.


2026-11-07: TIAB_ABSENT/ABSTRACT_ABSENT rows show Step 1 as not performed (TI/AB missing), rather than suggesting a completed relevance assessment. Fixed five-sheet headers and columns remain unchanged. Source and final reason remain in JSON; Korean reviewer reasons flow into Excel unchanged. Tests cover source exclusions and workbook projection.

Display correction: the review-level cell for source absence reads `TI/AB 존재 확인`, without the `0단계:` prefix. The presence gate, exclusion reason, first-pass-not-performed state and scientific decisions are unchanged. Re-export saved SQLite records; retain earlier publications. Regression: tests/test_liver_v4_csv.py.


## Per-paper progress Excel (2026-11-09)
Inputs: the frozen batch source and latest SQLite revisions; IDs and source values remain unchanged. Outputs: `Output/2026-11-07/liver-15860-batch1500/In_Progress/DB_Select_00001-01500.xlsx` and its `.progress.json` manifest. Other batches use their original number range. Five sheets and the existing headers remain fixed.

Algorithm/states: finish one paper, including immediate code-specific deep revalidation if required; commit SQLite and cumulative JSON/PRISMA; rebuild and verify the progress Excel; only then enter the next paper. The first sheet retains the complete batch input, with unfinished papers explicitly marked `미검수` / `검수 대기`. These rows are not final pending decisions. Terminal included + excluded + pending equals `processed_papers`; batch scope also includes unreviewed rows. Progress files are `IN_PROGRESS`, `downstream_ready=false`, and are replaceable projections, not finalized publications.

Audit/units: immutable per-update manifests under `Runs/review/progress_excel` bind source, policy, template, paper IDs, PMIDs, revisions, timestamps and workbook SHA-256. Counts are papers, never requests or retry attempts. SQLite revisions and events remain append-only. Existing finalized publications are preserved.

Validation/retries/resume: read back all five sheets, header order, values, identities, data links and counts before atomic replacement. Retry a locked workbook; if still blocked, stop before the next paper and retain the committed result and pending workbook bytes. Resume flushes this projection first, without repeating scientific review. Unknown user edits to the progress workbook are preserved and block replacement. A successful final batch still requires all normal final QC and immutable publication checks.

Commands: resume the existing `python -m k_melloddy.db_select.batch_workflow --source INPUT.csv --root RUN_ROOT --publish OUTPUT_ROOT --organ Liver --batch-size 1500`; this invokes the progress hook automatically. Offline tests: `python -m pytest tests/test_progress_excel.py tests/test_batch_workflow.py tests/test_full_workflow.py -q`. Tests cover sequential save-before-next, interruption, lock failure, cached resume, manual edits and unchanged finalized records. Limitations: rebuilding Excel needs the artifact-tool runtime; manual scientific review requires actual reviewer answers. Progress Excel is not a completed batch or an unattended LLM service.

