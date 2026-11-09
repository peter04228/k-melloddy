# Isolated spreadsheet screening

Input: a user-supplied XLSX with one sheet and Internal_Number, PMID, Title, Abstract, DOI and PMCID columns. Output: frozen original workbook, lossless original row values, normalized papers, a separate SQLite identity namespace and the same per-paper 0/1/2/3 workflow. This is not a fabricated DB_Collect run. The legacy collect_run_id field identifies the source as xlsx:SHA256 explicitly.

Algorithm/states/units: validate unique numeric source numbers and PMIDs, freeze input bytes, sort by original number, require explicit session review under the current organ policy. Unit is paper. Source sheet/row/headers and raw values remain auditable. No results are copied by matching row numbers from another input collection.

Validation: reject formulas, duplicate identifiers, missing required columns, multiple sheets, empty input and changed source hashes. No inferred abstracts or replacement IDs. Retries/resume reuse the full workflow's immutable request cache and SQLite checkpoints. Missing reviewer answers stop at AWAITING_REVIEW; they are not scientific pending decisions. Source file and policy must remain unchanged on resume.

Commands: python -m k_melloddy.db_select.spreadsheet_workflow --source SOURCE.xlsx --root projects/Liver/DB_Select/Runs/BATCH --organ Liver --prepare-only. Remove --prepare-only to execute with Input/session_review.json. Use --render --publish projects/Liver/DB_Select/Output/YYYY-MM-DD for final dated five-sheet Excel and JSON/PRISMA publication after all scoped papers pass QC. Publication is immutable and never replaces a previous batch silently.

Tests: tests/test_spreadsheet_workflow.py exercises row identity preservation, missing abstracts, invalid inputs and changed-source detection; existing full-workflow tests cover sequential review/resume and scientific validation. Limitations: an explicit reviewer/provider is required; no automatic keyword-based verdicts. Prior Collect results and independent spreadsheet identity namespaces are not merged. DB_Download and DB_Preprocessing remain contracts.

Completed dated publication includes nested PRISMA files and Runs/review/PRISMA/round_N stage records under PRISMA/round_N. Temporary Excel lock files are excluded. Publication is byte-idempotent and refuses conflicting existing artifacts. Tests: tests/test_spreadsheet_publication.py. This publication helper does not run for AWAITING_REVIEW or PARTIAL states.


## Liver v4 / isolated CSV review
Inputs: liver-v4 organ YAML and UTF-8 CSV with source numbering. Output: separate run namespace; existing research and finalized artifacts remain unchanged. Grouped endpoints and full organ criteria are passed to evidence-bound review; keywords are never automatic verdicts. Step 0 requires both title and abstract; either missing (including whitespace) excludes immediately with TIAB_ABSENT before Step 1. Step 1 E01/E02 or candidate/uncertain; Step 2 verifies data; Step 3 uses code-specific P tasks with one automatic round. Units: papers and datasets remain separate. Existing transitions, immutable revisions, URL attempts and PRISMA record each state. Resume requires identical source and policy hashes. CSV source is frozen as source.csv; no Excel conversion. Command: python -m k_melloddy.db_select.spreadsheet_workflow --source INPUT.csv --root NEW_RUN --prepare-only. Tests: tests/test_liver_v4_csv.py and existing workflow/decision tests. Limitation: verification: null supplies no additional rules; actual inclusion still requires the existing evidence and file-structure validators. No live review is implied by offline tests.


## Range workbooks for large CSV inputs

Use python -m k_melloddy.db_select.batch_workflow with --batch-size 1500 to review consecutive source ranges and publish one fixed five-sheet workbook per range. Global source numbering is preserved; completed batches and interrupted publications resume without re-rendering. Explicit review is still required. The 15,860-paper source is prepared as 11 batches; no scientific run was started by preparation. See src/k_melloddy/db_select/batch_workflow.README.md and projects/Liver/DB_Select/Output/2026-11-07/liver-15860-batch1500/README.md for the exact command.
