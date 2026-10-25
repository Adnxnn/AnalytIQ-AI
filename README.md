# AnalytIQ AI

Agentic, verified data analytics workspace. This repository is under active development.

## Architecture
- `web/`: Next.js frontend intended for Vercel.
- `api/`: Python FastAPI analytical compute service; requires separate secured runtime.
- `supabase/`: database migrations for persistence and row-level security.

## Status
Initial repository setup. Do not expose analytical uploads to the public until authentication, tenant-scoped storage, access control and API authorization are implemented. Development MVP is available as a separate project archive. Further modules are being integrated.

## Roadmap
1. Secure authenticated projects and isolated source files.
2. XLSX/CSV inspection, verified computations, visualizations and exports.
3. Agent orchestration with structured plans and provenance.
4. Safe multi-format adapters for PPTX, PDF, DOCX and images.
5. Assessment solver, dashboards, formula tools and professional reports.
6. Security review, end-to-end integration tests and production readiness.
