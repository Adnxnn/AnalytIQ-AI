# AnalytIQ AI — Implementation blueprint

## User experience
- Dark, premium, mobile-first project workspace: upload files and ask a single natural-language question.
- Separate answer view with summary, KPI, chart, verified table, provenance and exports.
- Hide column, axis, worksheet and pivot settings unless requested; retain optional advanced diagnostics.
- Keep project/files/history persistent rather than browser session-only.

## Execution architecture
1. **Authenticate / authorize** — Supabase auth, owner/project RLS, private object storage and authenticated API.
2. **Ingest** — resumable uploads (TUS), virus/ZIP safety checks, file metadata and content hash, idempotent jobs.
3. **Inspect** — identify sheets, table boundaries, header rows, dates, formula fields, pivot versus raw tables; profile without loading 100MB workbooks in memory.
4. **Plan** — server-side LLM structured-output planner using minimal schema and samples, never raw secrets; constrained allowlisted plan schema and human clarification for materially ambiguous fields.
5. **Validate** — schema match, column existence, units, data coverage, joins, numeric filters, cost/row quotas, prohibited operations.
6. **Compute** — dedicated worker with 2–8 GB memory according to workload, queued tasks, cancellation and retry, DuckDB/Polars/PyArrow for columnar data, openpyxl streaming for Excel ingestion. Convert verified raw tables to versioned Parquet.
7. **Audit** — persist plan, code version, source files and sheet locations, warnings, SQL/query, validation results, totals and artifacts in Supabase.
8. **Present** — dedicated result page with narrative based *only* on computed results; independent chart/table export, workbook with editable formulas where supported.

## Production blockers, not yet complete
- The current rule-based question parser cannot interpret arbitrary instructions. **Requires LLM credentials**, provider integration, prompt-injection defenses, sandboxed execution and a schema-aware planner.
- Large-file calculations currently run on Vercel FastAPI, not a dedicated worker; very large tasks can still time out or exhaust memory.
- Files are not yet fully associated with projects in persistent metadata, and results/history are currently held in sessionStorage.
- Native refreshable Excel pivot tables need an appropriate Excel-capable engine; a static groupby is not a native pivot.
- PPTX/PDF/Word authoring/editing and broad file-format support remain to be built and tested.

## Acceptance tests (must pass before feature is called complete)
- User A cannot access User B's projects, files, API requests, results, or storage paths.
- Upload 1 MB CSV, 30 MB XLSX and 100 MB XLSM without Vercel request body limits, with visible progress and recoverable failures.
- Workbook with 23 sheets, blank first rows, merged titles, named tables and existing pivots selects the correct raw sheet for “Count opportunities by status”.
- Deterministic count reconciles to actual source rows, typed dates and filtered totals validated against a trusted fixture.
- Correct exports in XLSX and CSV; formulas editable and recalculated by Excel; no accidental macro removal.
- Complex assignment spanning sheets produces transparent provenance and explicit limitations.
- Mobile 375px, tablet, desktop layout audited for contrast, keyboard accessibility and no content overflow.

## Delivery order
1. Header/sheet discovery and accurate dataset metadata
2. Durable job records and worker hosting
3. Authenticated structured LLM planner with field mapping
4. Cross-sheet SQL and advanced aggregation
5. Editable Excel workbook outputs and pivot support
6. Multi-format reports and expanded source types
7. End-to-end security, performance and user acceptance tests
