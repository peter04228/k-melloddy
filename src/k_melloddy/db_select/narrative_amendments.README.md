# Narrative amendments

Input: explicit reviewer corrections keyed by stable paper ID and PMID, for a terminal pending record with one deep attempt. Output: appended evidence/history documents and a new SQLite record revision; aggregate JSON is rebuilt. Unit: paper, not a new scientific review attempt.

Algorithm: validate identity and readable prose, copy the existing evidence, preserve every captured HTTP record and decision code, add an amendment note and corrected reviewer prose, append a replacement history document referencing the superseded immutable document. Original requests, answers, evidence, revisions and history documents remain intact. Cumulative history exposes superseded_attempts separately and counts the corrected committed attempt once. This is an explicit reviewed correction, not recovery of lost text or a new network check.

States/audit: terminal pending and auto_retry remain unchanged; phase narrative_amendment records the new revision and timestamp. Scientific inclusion/exclusion, datasets, identifiers and HTTP evidence cannot be changed through this function. Initial versus final corrected reasons remain separate.

Validation/retries/resume: all entry identities and terminal states are checked before writing. Repeating identical corrections skips already-amended records. Each save is atomic; a resumed call completes remaining records. Commands: invoke amend(store, run_id, corrections) from the Python API after acquiring the project lock. Tests: tests/test_full_workflow.py exercises immutable history, one-attempt counts, exact HTTP preservation and idempotence. Limits: reviewed prose only; original damaged text remains available as superseded evidence.
