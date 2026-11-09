# Workbook renderer

Inputs: the exporter supplies five sheet definitions, fixed headers, saved paper rows, dataset rows and a run summary as JSON. Outputs: DB_Select_Final.xlsx plus optional inspection JSON and preview PNG files in the temporary build directory.

Algorithm: artifact-tool builds the existing five-sheet template, writes saved values, recalculates, inspects, optionally renders and exports. Units are papers and registered datasets. PARTIAL summaries display `검증 미완료: 저장된 현재 판정`; this does not change any scientific decision or mark a run completed.

Audit and validation: excel_export.py preserves earlier published artifacts and verifies every cell, IDs, headers and JSON/PRISMA totals before publication. The renderer does not write ledger events itself. Retry or resume by rerunning the calling exporter from committed SQLite records; no paper IDs are allocated here.

Command: invoked by excel_export.py as `node workbooks.mjs PAYLOAD_JSON RUNTIME_NODE_MODULES`. Use the configured artifact-tool runtime. Tests and limitations: the 2026-11-03 100-paper partial export passed cell-by-cell comparison, five-sheet checks and count validation. Preview images were inspected. Long text remains subject to Excel cell and row-height limits; detailed evidence stays in JSON. Rendering or successful export does not establish scientific verification of unresolved papers.


2026-11-07: row heights account for Korean screening states, reasons, grounds and reviewed-step descriptions (H and N:P), alongside J:M data facts, with the existing 409-point cap. New N:P previews expose the delivered decision text for visual QA. Headers, sheet order, column count and widths remain fixed. The exporter still verifies all saved cells against SQLite/JSON before publication; long abstracts remain fully available in JSON. Render with --render; no scientific decisions or counts are derived by the builder.
