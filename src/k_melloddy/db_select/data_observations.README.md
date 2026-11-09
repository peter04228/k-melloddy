# Evidence-backed data observations and screening J–M

## Purpose and root cause

The old `paper_row()` read J/K from registered `datasets` or `source_databases`, but L/M only from `datasets`. Pending/excluded proposals cannot register datasets; automatic P02 proposals also had empty source lists. As a result, known DB mentions in title/abstract/full text never reached these columns. There was no fallback status for excluded rows. The confirmed-only condition in `workbook_payload()` belongs to the confirmed DB sheet and remains unchanged.

## Inputs, outputs and schema

TI/AB and Full Text proposals can now supply optional `data_observations`, independently of their verdict. Each observation has `name`, `relationship` (reuse/new/derived/unknown), `public_status` (unknown/reported_public/verified_public/restricted/not_public), `verification_level`, nullable `url` and cited `evidence_refs`. A mention is descriptive evidence, not dataset registration or an inclusion decision. Old proposals remain valid.

`validate_observations()` requires accessible source quotations, the named DB in the quotation, actual material response URLs for links, and evidence at least as strong as any claimed file verification level. Title/abstract uses evidence ID `tiab`; Full Text/repository evidence uses its immutable evidence ID. Article DOI/PMC URLs and search URLs cannot stand in for data links. A paper saying data is public is distinct from verified public access.

`source_observations()` converts cited legacy source DB information only when its name and claimed material URL are supported. Unsupported legacy labels remain legacy source information but do not gain a new verified data link. Explicit section-review submissions can include the same observations; normal LLM/provider responses use the same schema. The global provider is still unconfigured.

## Processing, states, units and Excel

Validate TI/AB facts before branch selection, preserving facts even for E01/E02. Validate Full Text facts against captured evidence and merge them independently of the final verdict. Preserve prior observations on pending revalidation. Evidence remains in SQLite documents and `evidence_log.json`; current descriptive facts are in `screening_results.json` records. Units are observations per paper; they do not increase confirmed dataset or PRISMA paper counts.

J = observed DB/dataset names. K = supported relationship. L = actual public-access/verification level. M = observed, validated material URL only. Unknown values display `미확인`. TI/AB exclusions explicitly show `해당 없음 — TI/AB 제외로 공개·다운로드 검증 미수행`; this means no screening download check was required, not proof that no database exists. An investigated Full Text exclusion without data facts shows `조사 범위 내 공개 데이터 미확인`, not absolute nonexistence.

Display-only access supersession: when a later validated observation for the same case-insensitive name and relationship explicitly confirms public, restricted or non-public access, Excel omits an earlier pathless `unknown` fact at `mentioned`/`unverified` level. This prevents an initial unknown from contradicting its later verified result. SQLite/JSON observations, citations, revisions, decisions, dataset mappings and PRISMA counts remain unchanged; no research record is overwritten. Distinct relationships, actual material URLs, merely reported-public claims and newer unknown findings are not merged away. The deterministic rendering applies on the next normal per-paper export/resume, keeps the fixed five sheets and 16/15 columns, and performs no requests or retries. Regression tests exercise pending rows, access findings, retained historical inputs, separate links/relationships and unverified claims with `python -m pytest tests/test_data_observations.py tests/test_verified_select.py tests/test_full_workflow.py -q`.

`reported_public` never becomes verified access/download. No data URL is synthesized from a DB name or accession. Different facts and levels remain separate in JSON. Same-level display text is deduplicated; row heights fit J–M without changing column order/count. Existing 5 sheets and fixed 16/15-column headers remain unchanged. Confirmed DB registration still requires the existing file/API and scientific eligibility checks.

## Existing records, audit, retries and resume

`enrich-data` adds reviewed facts to an existing run without rerunning science or changing verdicts. The input JSON identifies `run_id`, paper IDs, PMID and observations. Validate all submitted facts against the immutable input/evidence before writing. Each changed paper gets an append-only revision plus an evidence annotation document, then JSON regeneration. Original source, IDs, metadata, verdict, reasons and revalidation counters stay unchanged. Repeat execution is idempotent: unchanged observations create no extra revision. Existing finalized output snapshots remain in SQLite.

A failed/locked Excel export leaves committed observations intact. CLI marks the run PARTIAL on failed enrichment/export; close the file and repeat the same command. Successful completion restores the computed run status. No approval is needed to repeat an already authorized export.

```powershell
python -m k_melloddy select enrich-data --organ Liver --resume RUN_ID --observations-file PATH --render
python -m pytest -q tests/test_data_observations.py
python -m pytest -q
```

## Validation and tests

Validate IDs/PMIDs, quotation and evidence hashes, public/file claims and actual URL kinds. QC checks the observation references across the paper's immutable evidence history, including earlier revalidation evidence. Before export, existing scope, E/P, dataset mapping, JSON/PRISMA conservation and all-cell Excel checks still apply. Enrichment emits final-state events with unchanged scientific outcomes; it does not count as an extra revalidation pass.

Tests cover pending/excluded display, explicit unknown status, fabricated names/URLs, article URL rejection, overstated download level, observed repository links in pending papers, legacy source URL handling, atomic append-only enrichment and repeated-command idempotence. The real 20-paper check uses existing captured source material; no new scientific decision or network availability is inferred.

## Limitations

Automatic HTTP fetching does not identify every dataset or establish a scientific relation by itself. A reviewer/provider must supply evidence-backed descriptive facts; known cited source DB facts are converted conservatively. The seven-paper retrospective enrichment contains 11 named facts but no verified material URL. Therefore M legitimately remains `미확인` for this corpus. The observations do not resolve remaining P-codes or create confirmed DBs.


## Full workflow update (2026-11-03)

The optional full_workflow entry point adds sequential per-paper stages 0/1/2/3. Source TI/AB absence records TIAB_ABSENT and missing fields; source E01/E02 exclusions do not require unnecessary Full Text requests. Official identifiers are still required before article access. First-pass uncertainty is first_pass_pending, never a final P code. A second-stage decision requires an evidence-hash-bound session reviewer answer; unavailable answers remain AWAITING_REVIEW.

Pending papers receive a separate deep round and terminal pending records have auto_retry=false. Each request and stage transition has immutable evidence plus atomic resume checkpoints. Workflow PRISMA projections use one latest outcome per paper/stage/round. Source inputs, previous runs and publications remain preserved. Existing five-sheet Excel and 16/15 columns are unchanged. Run-specific outputs are under Runs/SESSION/published/PUBLICATION_ID.

Validation/retries/resume/commands/tests/limitations: see src/k_melloddy/db_select/full_workflow.README.md and full_workflow_access.README.md. Offline coverage includes missing TI/AB, E01/E02, explicit review boundaries, one-paper-at-a-time deep review, terminal retry suppression, structured JSON sampling and existing identifier/access/decision tests. No unresolved scientific review is reported complete.


## Explicit source access review takes precedence (2026-11-09)

When a new proposal supplies a validated `data_observations` entry for a source DB name, `source_observations()` does not append another inferred observation for that name (case-insensitive). An accessible source information page therefore cannot contradict an explicit restricted, non-public or unknown access finding. Legacy source references and explicit facts remain preserved; no existing finalized record is rewritten. JSON and Excel use the same preserved observation. Retry/resume applies this deterministic rule to the evidence-bound pending proposal. Run `python -m pytest tests/test_data_observations.py tests/test_verified_select.py -q`; regression cases verify access status, source URL, unchanged inputs and Excel display. This prevents duplicate inferred access claims; it does not itself verify access terms or resolve a scientific verdict.
