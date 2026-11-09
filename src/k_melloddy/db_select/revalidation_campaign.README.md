# Targeted pending-paper campaigns

Inputs: an existing run, frozen policy, original Collect manifest, explicit `{paper_id: PMID}` scope and reviewer submission. The first invocation requires the scope to equal all current P02 records. Other papers are compared byte-for-byte as JSON objects before and after processing. IDs and Collect inputs never change.

Algorithm and states: archive existing JSON/PRISMA/Output aliases and all baseline records, then process the selected papers in numeric ID order. Write an immutable start event and `in_progress` checkpoint, review one paper, commit its revision to SQLite, then write the saved checkpoint. Each baseline target is its prior attempt count plus one. On resume SQLite determines which papers have already committed, including a crash before checkpoint/aggregate publication. A failed run remains PARTIAL; no retry exhaustion becomes scientific exclusion.

Outputs: `Revalidation/<campaign>/baseline/`, immutable `events/` and `results/`, replaceable `checkpoint.json` and `summary.json`, cumulative JSON and optional full-run Excel. The campaign ID identifies the incremental revalidation; the parent run ID preserves the original 100-paper scope. Unit is paper, never URL or dataset. Validate selected = converted included + converted excluded + other pending + retained P02 and full input = included + excluded + pending. Existing PRISMA snapshots are retained in the baseline; current step JSON is regenerated from the ledger.

Command (resume uses exactly the same command):

```powershell
python -m k_melloddy.db_select.revalidation_campaign --root projects/Liver/DB_Select --run f64319fc9221485e9942befed4b97e60 --campaign p02-29-20261103-v1 --scope projects/Liver/DB_Select/Input/p02_29_scope.json --review-file projects/Liver/DB_Select/Input/pilot100_p02_29_review_v2.json --render
```

Network execution is explicit. The global LLM provider stays unconfigured. Submitted decisions are reviewer-authored; discovery cannot manufacture decisions. Offline tests in `tests/test_revalidation_campaign.py` inject failure after a committed paper and check resume, idempotence, scope validation and unchanged excluded records. A different campaign is a new attempt subject to the policy cap. Do not edit the baseline or reset attempt counts. Export preserves five existing sheets and their headers. Unresolved verification remains reported even when all 29 transport attempts have run.
