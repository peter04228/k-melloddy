# Explicit public web capture

Input: a session-review `web_captures` list of root-relative paths and SHA-256 hashes. Each JSON binds one paper ID and PMID to a reviewer-authored excerpt/summary of an actually inspected public article or repository/landing page. Output: additional evidence records; no replacement of original HTTP responses or source metadata. PMC article captures require the exact official PMCID URL. Other captures require an already observed route of the same evidence kind and `verified_identifiers` with the exact official DOI and title; the reviewer must check the article or repository's publication reference. A repository excerpt supports a documented location and P03, but never file verification or confirmed inclusion.

Algorithm and states: verify path containment, immutable bytes, paper identity and official PMCID URL; validate excerpt hash/size and append an accessible reviewer excerpt. HTTP status remains null because the web tool does not expose it. `complete_body` and `downloaded_full_dataset` remain false. Units: one capture and one paper, never a dataset count.

Audit: record actual tool source reference, URL, timestamp, reviewer note and capture file hash. No HTTP request or full document download is inferred. A changed evidence bundle receives a new request hash under the session workflow.

Validation: `tests/test_web_capture.py` covers accepted captures, tampering, identity mismatch, path escape and fabricated HTTP metadata. Captures cannot be file/API evidence and cannot satisfy dataset structure verification. Quoted excerpts and summaries must reflect actual tool observations.

Retries/resume: immutable captures are reused without repeating a network request; duplicate evidence IDs are not appended twice. Invalid captures fail before a final decision is saved. The ordinary workflow command resumes after an explicit answer to its new evidence-bound request.

Command: use `python -m k_melloddy.db_select.spreadsheet_workflow --help` for the isolated spreadsheet workflow. The provider remains unconfigured; a session reviewer must explicitly submit each conclusion. Limitations: web summaries do not substitute for inspecting supplementary files or proving absence of data. Identity binding prevents accidental cross-paper import but still requires honest human/session review of the actual page. Offline tests include mismatched DOI/title and unobserved routes.
