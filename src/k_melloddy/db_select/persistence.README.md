# persistence.py

Append-only SQLite scientific state and recoverable JSON projections.

Large cumulative projections use incremental JSON encoding for their generation hash and atomic output files. The bytes and SHA256 match the previous `dump()` format exactly, including Korean text, sorted keys and indentation. This avoids constructing several full-size Unicode and UTF-8 copies while saving each paper. SQLite records, evidence documents and finalized outputs remain unchanged. Each output is fsynced before replacement; a failed encoding or locked target leaves its prior file intact, cleans the temporary file and does not advance the multi-file checkpoint. Resume regenerates projections from committed SQLite. Replacement retries remain six attempts. `tests/test_projection_streaming.py` checks byte/hash compatibility, serialization failure and exhausted locked-file retries. This reduces temporary encoding memory only: the aggregate object and evidence remain in memory, and no 1,500-paper memory benchmark is claimed.

Inputs/outputs, algorithm and states, units, settings, audit/retries, resume, commands, validation, tests and limitations are specified in the shared [stabilization contract](stabilization.README.md) and [pending revalidation contract](revalidator.README.md).


## Targeted P02 campaign update

Cumulative revalidation_history adds revalidation_attempts derived from immutable documents. Missing legacy fields are null rather than invented. Original attempts and document hashes remain intact. See [campaign](revalidation_campaign.README.md) and [access](revalidation_access.README.md) for inputs, outputs, algorithm, states, units, audit, validation, retries, resume, commands, tests and limitations.
# Reviewed narrative amendments

`narrative_amendments.amend` appends corrected prose as new immutable evidence, history and record revisions. It never edits captured HTTP records or changes the decision code. A committed replacement history names `supersedes_document_id`; aggregate JSON retains the original under `superseded_attempts` and counts the corrected attempt once. Uncommitted replacements do not suppress the original attempt. Initial and final corrected reasons remain distinct. See narrative_amendments.README.md for inputs, audit, validation, resume and limitations.
