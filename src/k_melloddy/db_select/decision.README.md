# decision.py

Validate quoted data facts independently of eligibility decisions and promote only verified source URLs.

Inputs, outputs, algorithm, states/units, audit, retries/resume, commands, tests and limitations: [data observation contract](data_observations.README.md).


## Targeted P02 campaign update

P01 can cite a concrete data clue without claiming a completed full-text review. P03/P04 must cite an accessible location/file of the appropriate kind. These pending states do not relax confirmed/excluded evidence gates. See [campaign](revalidation_campaign.README.md) and [access](revalidation_access.README.md) for inputs, outputs, algorithm, states, units, audit, validation, retries, resume, commands, tests and limitations.


## Full workflow update (2026-11-03)

The optional full_workflow entry point adds sequential per-paper stages 0/1/2/3. Source TI/AB absence records TIAB_ABSENT and missing fields; source E01/E02 exclusions do not require unnecessary Full Text requests. Official identifiers are still required before article access. First-pass uncertainty is first_pass_pending, never a final P code. A second-stage decision requires an evidence-hash-bound session reviewer answer; unavailable answers remain AWAITING_REVIEW.

Pending papers receive a separate deep round and terminal pending records have auto_retry=false. Each request and stage transition has immutable evidence plus atomic resume checkpoints. Workflow PRISMA projections use one latest outcome per paper/stage/round. Source inputs, previous runs and publications remain preserved. Existing five-sheet Excel and 16/15 columns are unchanged. Run-specific outputs are under Runs/SESSION/published/PUBLICATION_ID.

Validation/retries/resume/commands/tests/limitations: see src/k_melloddy/db_select/full_workflow.README.md and full_workflow_access.README.md. Offline coverage includes missing TI/AB, E01/E02, explicit review boundaries, one-paper-at-a-time deep review, terminal retry suppression, structured JSON sampling and existing identifier/access/decision tests. No unresolved scientific review is reported complete.
