# Explicit PDF grid review

Inputs: `evidence_review.pdf_grid_selections` in an answer, naming the complete public PDF evidence ID, zero-based page/table indices, observed header-cell coordinates, expected verbatim column names, explicit data row bounds and a caption quote actually present in the PDF text. Install the optional reader with `python -m pip install -c constraints.txt -e ".[review]"`.

Algorithm: validate actual HTTP response/hash/bytes, open the bounded PDF with PyMuPDF, locate its ruled table, select the specified real header/data cells and verify every selected row. The cited caption must also occur above this table's data on the same page, below any preceding table. A drug heading from another page/table cannot bind this selection. Merged headers require explicit coordinates; no automatic filling or synthetic Drug/Endpoint/Value columns. Keep NA, signs, significance marks and units as printed. A constant drug must independently satisfy the existing caption/context verifier, using only this selection's verified caption and headers.

Outputs/states/audit: a derived `file/sample_structure` record with stable selection hash, parent evidence ID, original PDF payload/hash, exact rows and selection coordinates. Original evidence is unchanged. Normal dataset verification still checks actual exposure, endpoint/value linkage, direct access and independent registration; this operation never confirms a paper by itself. Scientific counts remain unset unless independently observed.

Units/validation: page, table, row and column indices are zero-based; end row is exclusive. Maximum 8 MiB, 64 pages, 5,000 grid rows and 100 columns; reject wrong headers, empty/merged data cells, missing captions and invalid bounds. No graph digitization, OCR or inferred values.

Retries/resume: deterministic offline reinspection of preserved bytes; no HTTP request or overwrite. Incorrect selections stop answer validation and retain the unfinished paper. Submit a new immutable answer/request when evidence changes. Existing finalized artifacts remain untouched.

Commands/tests: `python -m pytest tests/test_form_material_capture.py tests/test_full_workflow.py -q`; offline fixture checks real PDF cell extraction, original NA/star strings, no invented drug column, header mismatch and unseen caption rejection. Limitations: requires optional PyMuPDF; scanned PDFs and ambiguous/unruled grids need a separate verified method. A selected subset must be described as a subset, not as the whole dataset.
