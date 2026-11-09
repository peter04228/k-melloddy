# db_download

Interface only. Calling its entry point raises NotImplementedError.

Inputs and outputs: see root README, core/contracts.py and project step READMEs. Algorithms and metric units: DB_Collect uses search_result, pmid_occurrence, unique_pmid and paper; later stages will use dataset/file/compound/measurement separately. State transitions: started/completed/partial/failed/retried in append-only audit events for collection. Later stages have no runtime events. Validation: input = forwarded + removed + pending; SHA-256 and schema/ID invariants. Retry/resume: run-scoped validated checkpoints and immutable attempt artifacts, no retries for unimplemented stages.

Run: `python -m k_melloddy collect demo --base demo_runs --project-name Example --count 12`. Test: `python -m pytest -q`. Limitations: no GUI, no ELink, no implementation of stages 2-4.
