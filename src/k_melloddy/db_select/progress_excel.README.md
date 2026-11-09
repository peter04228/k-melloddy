# Progress Excel


## Per-paper progress Excel (2026-11-09)
Inputs: the frozen batch source and latest SQLite revisions; IDs and source values remain unchanged. Outputs: `Output/2026-11-07/liver-15860-batch1500/In_Progress/DB_Select_00001-01500.xlsx` and its `.progress.json` manifest. Other batches use their original number range. Five sheets and the existing headers remain fixed.

Algorithm/states: finish one paper, including immediate code-specific deep revalidation if required; commit SQLite and cumulative JSON/PRISMA; rebuild and verify the progress Excel; only then enter the next paper. The first sheet retains the complete batch input, with unfinished papers explicitly marked `미검수` / `검수 대기`. These rows are not final pending decisions. Terminal included + excluded + pending equals `processed_papers`; batch scope also includes unreviewed rows. Progress files are `IN_PROGRESS`, `downstream_ready=false`, and are replaceable projections, not finalized publications.

Audit/units: immutable per-update manifests under `Runs/review/progress_excel` bind source, policy, template, paper IDs, PMIDs, revisions, timestamps and workbook SHA-256. Counts are papers, never requests or retry attempts. SQLite revisions and events remain append-only. Existing finalized publications are preserved.

Validation/retries/resume: read back all five sheets, header order, values, identities, data links and counts before atomic replacement. Retry a locked workbook; if still blocked, stop before the next paper and retain the committed result and pending workbook bytes. Resume flushes this projection first, without repeating scientific review. Unknown user edits to the progress workbook are preserved and block replacement. A successful final batch still requires all normal final QC and immutable publication checks.

Commands: resume the existing `python -m k_melloddy.db_select.batch_workflow --source INPUT.csv --root RUN_ROOT --publish OUTPUT_ROOT --organ Liver --batch-size 1500`; this invokes the progress hook automatically. Offline tests: `python -m pytest tests/test_progress_excel.py tests/test_batch_workflow.py tests/test_full_workflow.py -q`. Tests cover sequential save-before-next, interruption, lock failure, cached resume, manual edits and unchanged finalized records. Limitations: rebuilding Excel needs the artifact-tool runtime; manual scientific review requires actual reviewer answers. Progress Excel is not a completed batch or an unattended LLM service.

