# access_workflow.py

Revalidation also searches official PMC XML, BioStudies by PMID/title and Zenodo by DOI/title independently of publisher page access. It follows only observed matching repository records and previously observed file/API locations; missing supplementary links are explicitly unresolved. See [P-code pass contract](revalidator.README.md) for code-specific tasks, states, audit, retry/resume and tests.

Input: an officially verified paper; unverified input is rejected. Output: evidence records, sampled response artifacts, ordered workflow states and unresolved actions. Unit: one URL attempt within one paper.

Algorithm: official PMC → publisher DOI → exact PMID/title Europe PMC lookup → verified article-specific alternative full text and observed supplementary/repository links. Actual sections, data files and features require subsequent review; network success does not mark them reviewed. Redirect/public URL guards remain active. Every attempt stores URL, final URL, status, error/restriction cause, retry number, UTC timestamp, response bytes/hash and identity match.

Default timeout is 12 seconds, one retry per failed/challenged/wrong-identity route, bounded response sample 1.5 MB. Wrong article pages and empty/JavaScript/interstitial responses cannot become valid full text. `access_pending` requires alternative search and multiple attempted paths, and refuses completed-access claims when accessible matching body text needs review. It never derives E03–E08 from HTTP failure.

States: accessible, access_restricted or fetch_error for attempts; reviewed/verified states require real review evidence. On interruption, previously committed paper evidence remains; pending revalidation gathers fresh evidence under the global attempt cap. Tests cover a single 403, wrong identity retry and the official metadata gate. Commands, P01–P04, final validation and limitations: [workflow README](verified_workflow.README.md).


## Stabilization update

See [stabilization contract](stabilization.README.md) for changed inputs/outputs, bounded automatic-pass configuration, start/end audit, transport/CSV handling, strict final checks, crash/resume and offline/live tests.


## Targeted P02 campaign update

Challenge detection uses visible challenge text. Merely loading a reCAPTCHA script in a normal article page is not an access block. Actual search challenge forms remain blocked. Regression coverage uses a normal article plus an unrelated captcha script.

PDF responses are text-extracted when possible; scan containers are not treated as reviewed prose. Search challenge pages are access failures. Existing retry/audit rules remain in effect. See [campaign](revalidation_campaign.README.md) and [access](revalidation_access.README.md) for inputs, outputs, algorithm, states, units, audit, validation, retries, resume, commands, tests and limitations.


## Full workflow update (2026-11-03)

The optional full_workflow entry point adds sequential per-paper stages 0/1/2/3. Source TI/AB absence records TIAB_ABSENT and missing fields; source E01/E02 exclusions do not require unnecessary Full Text requests. Official identifiers are still required before article access. First-pass uncertainty is first_pass_pending, never a final P code. A second-stage decision requires an evidence-hash-bound session reviewer answer; unavailable answers remain AWAITING_REVIEW.

Pending papers receive a separate deep round and terminal pending records have auto_retry=false. Each request and stage transition has immutable evidence plus atomic resume checkpoints. Workflow PRISMA projections use one latest outcome per paper/stage/round. Source inputs, previous runs and publications remain preserved. Existing five-sheet Excel and 16/15 columns are unchanged. Run-specific outputs are under Runs/SESSION/published/PUBLICATION_ID.

Validation/retries/resume/commands/tests/limitations: see src/k_melloddy/db_select/full_workflow.README.md and full_workflow_access.README.md. Offline coverage includes missing TI/AB, E01/E02, explicit review boundaries, one-paper-at-a-time deep review, terminal retry suppression, structured JSON sampling and existing identifier/access/decision tests. No unresolved scientific review is reported complete.

Europe PMC links labeled OA or F (Free) are both investigated after exact PMID/title matching. Free is a discovery hint, never proof of actual full-text or dataset access; HTTP/content/identity gates and explicit reviewer checks still apply. Regression coverage includes a Free link whose response is only an abstract.

BioStudies search hits may expose a numeric `links` count. The collector uses the observed accession to resolve the study page, and only treats dictionary `links.html` as a URL. This avoids interrupting a valid run on provider response shape. PMC's visible “Preparing to download ...” interstitial is an access restriction, not a successful DOCX/PDF download. Original cached responses remain unchanged; reviewer notes explain earlier ambiguous HTTP 200 responses. Tests cover the numeric-link response and explicit web-capture provenance separately.
# Explicit supplementary access review

When an institutional full text is reviewed but the DOI only redirects, a reviewer may cite its supplementary statement and name blocked_material_urls in access_constraints. P02 still requires alternative investigation, the cited captured evidence, and a matching captured access_restricted response on retry 2 or later. An invented URL, unsupported quote or single request cannot satisfy this gate. This preserves separate article access and supplementary access states; it does not certify dataset contents. Test: tests/test_supplement_access_review.py. Resume and audit use the immutable evidence-bound reviewer request and append a new paper revision when correcting prior workflow failures.


### Observed institutional download links
A reviewer-observed download can carry a Referer only when its exact URL was captured as a link on that page; cross-origin referers are rejected. HTTP evidence records the referer and caches use a distinct key. A complete PDF mislabeled HTML is parsed from magic bytes; title and official DOI must match (PDF DOI line breaks normalize as whitespace). No access success or full review is inferred from HTTP 200. Original attempts are preserved. Regression commands: pytest tests/test_observed_download_referer.py tests/test_pdf_mime_recovery.py.

Slow-stream protection: read response bodies in bounded chunks with a monotonic wall-time deadline equal to the configured socket timeout. A slow server cannot keep the stream alive indefinitely by sending occasional bytes. Deadline failures use the existing retry/audit path; partial bytes never establish verified access. Existing finalized evidence is unchanged.
