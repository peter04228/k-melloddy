# schema.py

Optional evidence-backed data observation fields for TIAB, fulltext proposals and records; legacy compatibility.

Inputs, outputs, algorithm, states/units, audit, retries/resume, commands, tests and limitations: [data observation contract](data_observations.README.md).


## Liver v4 / isolated CSV review
Inputs: liver-v4 organ YAML and UTF-8 CSV with source numbering. Output: separate run namespace; existing research and finalized artifacts remain unchanged. Grouped endpoints and full organ criteria are passed to evidence-bound review; keywords are never automatic verdicts. Step 0 requires both title and abstract; either missing (including whitespace) excludes immediately with TIAB_ABSENT before Step 1. Step 1 E01/E02 or candidate/uncertain; Step 2 verifies data; Step 3 uses code-specific P tasks with one automatic round. Units: papers and datasets remain separate. Existing transitions, immutable revisions, URL attempts and PRISMA record each state. Resume requires identical source and policy hashes. CSV source is frozen as source.csv; no Excel conversion. Command: python -m k_melloddy.db_select.spreadsheet_workflow --source INPUT.csv --root NEW_RUN --prepare-only. Tests: tests/test_liver_v4_csv.py and existing workflow/decision tests. Limitation: verification: null supplies no additional rules; actual inclusion still requires the existing evidence and file-structure validators. No live review is implied by offline tests.
