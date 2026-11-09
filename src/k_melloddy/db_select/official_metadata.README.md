# official_metadata.py

Input: a paper's stable PMID and original values. Output: official values, comparison differences, raw XML/hash and timed attempt records. The unit is one PubMed article. State is `verified` or `unverified`.

Fetch EFetch XML by PMID, require exactly one matching PubmedArticle and read only that article's PubmedData/ArticleIdList (ELocationID fallback). Never read reference-list identifiers. Publication year uses journal publication date, MedlineDate or ArticleDate. Compare all five requested fields and retain originals unchanged. `verified_paper` creates a copy and refuses unverified/mismatched PMID.

NCBI transient retries use the existing client with two retries and recorded status/reason/delay/time. Failure blocks original identifier use and is retried on resume/revalidation. XML/hash and comparison are immutable evidence documents. No inferred IDs or counts.

Commands, validation, audit/resume contract, offline tests and limitations: [workflow README](verified_workflow.README.md). Specific tests: `test_official_identifiers_ignore_references_and_keep_original`, `test_metadata_failure_retains_paper_and_blocks_completion`.


## Stabilization update

See [stabilization contract](stabilization.README.md) for changed inputs/outputs, bounded automatic-pass configuration, start/end audit, transport/CSV handling, strict final checks, crash/resume and offline/live tests.
