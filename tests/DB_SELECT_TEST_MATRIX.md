# DB_Select requested test matrix

Offline tests use synthetic papers and mocked HTTP bytes. No fabricated fixture is exported as research evidence. Run `python -m pytest -q`; live tests remain skipped unless `KMELLODDY_LIVE_SELECT=1`.

| Requested check | Automated coverage |
|---|---|
| DOI / PMCID mismatch | test_official_identifiers_ignore_references_and_keep_original |
| Abstract absent | test_abstract_absence_vs_fetch_error |
| E01, E02, E03–E08 | test_exclusions_require_matching_evidence (parameterized) |
| CSV verified then included | test_csv_response_verified_before_inclusion |
| P02 → included; P03 → excluded | test_pending_pass_runs_after_initial_and_resolves_with_history (all four codes × both outcomes) |
| P maintained | test_pending_finite_revalidation; test_failed_revalidation_preserves_specific_pending_code |
| Forced process exit / resume | test_real_process_exit_after_sqlite_commit_resumes_without_reprocessing |
| Interrupted JSON publish | test_sqlite_commit_before_cumulative_json_failure |
| Duplicate PMID / missing ID | test_invalid_collect_identity_is_rejected_before_run |
| Excel/JSON mismatch; PRISMA mismatch | test_excel_json_and_prisma_disagreement_are_rejected |
| Full Text failure / wrong URL | test_wrong_article_page_is_retried_and_audited; test_xml_identity_uses_own_pmid_and_normalized_title |
| Repository download failure | test_actual_response_parser_and_repository_failures (404, timeout, IncompleteRead) |
| Multiple DBs from one paper | test_first_pass_then_revalidation_and_shared_dataset; fixture two_datasets |
| Configurable finite automatic passes / audit times | test_configured_automatic_passes_have_timestamps_and_are_finite |
| Corrupt final state / mappings / missing output | test_strict_qc_rejects_incomplete_or_corrupt_final_state and export checks |
| External integration (opt-in) | tests/test_select_live.py; real Liver 20-paper regression separately |

Existing five-sheet template and headers are validated after artifact-tool export. Openpyxl is used only to inspect/read, not author research workbooks. Tests write exclusively to temporary fixture roots. For Windows pytest temporary-directory permission problems, use a fresh uniquely named `--basetemp` below a pre-created workspace test parent; never point it at research data because pytest owns its temporary directory.
