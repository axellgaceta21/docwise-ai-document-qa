# AI Document Comparison & Quality Assurance System

Compare two text-based PDFs against editable checklist clauses. Deterministic mode uses Python matching. AI-Assisted mode runs the same comparison first, then asks Groq to review bounded excerpts for unresolved clauses. Results are review aids, not engineering compliance certification.

## Requirements

- Python 3.11 or newer
- Node.js 20 or newer

## Start the backend

From the project root (PowerShell):

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

The API is at `http://127.0.0.1:8000`, with interactive docs at `/docs`.

Set `DATABASE_URL` in `backend/.env` to a PostgreSQL URI. Supabase's Session Pooler URI (port 5432, `sslmode=require`) is supported; URL-encode special password characters. Use a separate PostgreSQL database for local development. Tables initialize automatically on startup, or with `python -m app.db` from `backend`. The database stores document names, hashes, page counts, checklist clauses, findings, review decisions, audit events, and execution metadata; it does not store PDF binaries.

Docwise uses the direct PostgreSQL `postgres` role through `DATABASE_URL`; browser clients never receive that credential. Schema initialization also enables RLS on all ten Docwise tables, revokes all table privileges from Supabase `anon` and `authenticated`, revokes their access to the two Docwise identity sequences, and revokes their default grants on future tables and sequences created by `postgres` in `public`. No public RLS policies are installed. Re-run `python -m app.db` from `backend` to reproduce these settings in a new Supabase project. The table owner retains direct database access; Supabase `service_role` grants are unchanged. Do not use Supabase Data API keys in the frontend for Docwise tables.

For AI-Assisted mode, copy `backend/.env.example` to `backend/.env` and set `GROQ_API_KEY`. The key stays in the backend and is never sent to the browser. `GROQ_MODEL` defaults to `openai/gpt-oss-20b`. Restart the backend after changing `.env`.

Optional cost display uses `GROQ_INPUT_USD_PER_MILLION_TOKENS` and `GROQ_OUTPUT_USD_PER_MILLION_TOKENS`. Supply both rates in USD per million tokens using prices verified for your account. If either is unset or Groq omits usage, the dashboard shows no cost estimate. Token counts come from Groq's response.

## Start the frontend

In another terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The Vite development server proxies `/api` to the backend.

## Try the sample

Upload `samples/approved_reference.pdf` and `samples/submitted_revision.pdf`. The dashboard starts with the checklist from `samples/checklist.json`. The sample should show one differing pressure clause, two matching clauses, and one missing inspection clause. All sample names and values are fictional.

Choose **AI-Assisted** before running the comparison to test Groq. The UI keeps Python findings visible and displays supported AI findings separately. The AI service sends only selected page excerpts for differing or missing clauses, up to 12 requirements, in batches of at most 3. It verifies every returned excerpt and page against both the sent evidence and extracted PDF text. Unsupported citations are discarded; uncertain findings remain marked for human review. Groq failures leave deterministic results available. This live mode uses API credits; automated tests use mocks.

Every comparison is saved with a stable session ID. Use **Comparison History** to reopen one, then use **Document Review** to inspect one row per requirement, set its final human review decision and comment, and download its current QA report. Human review starts at **Pending Review**; confirming an issue does not certify engineering compliance. The report includes the latest review decisions and audit history.

The current review workflow records **one final human decision per requirement**. Document comparison and AI findings remain separate evidence. A clean match with no AI concern shows **No review needed**. Existing finding-level decisions remain in the database and audit history. When older finding decisions disagree, Docwise marks the requirement **Needs review** and asks for an explicit final decision; it does not rewrite the older records. The PostgreSQL `requirement_reviews` table is created automatically on first use.

The Correction column is derived from that final review and the current correction version. Clean matches and dismissed findings show **Not Required**; pending decisions show **Awaiting Review**; confirmed issues move through **Needs Correction**, **Draft**, **Pending Verification**, and **Verified**. A rejected correction shows **Correction Rejected**. Editing a verified correction creates a new draft, so the current requirement no longer displays Verified until the new version is verified.

## Corrections and structured revisions

In Document Review, open a requirement, choose its finding, and mark a valid discrepancy **Confirmed issue**. Enter the corrected value and reason, save a draft correction, then send it for verification. A reviewer must explicitly select **Verify correction**; confirming the issue alone never verifies a correction. Rejected and unconfirmed corrections cannot be included in a generated revision. Editing a correction creates a new draft while retaining the earlier version and audit events.

Use **Generate revised document** below the results table. It creates a numbered **Draft Revision** if included corrections still need verification, or a **Verified Revision** if all included corrections are verified and confirmed issues have corrections. Download this structured PDF separately from the existing QA Report. It is not an edited copy of the uploaded engineering PDF, and neither status is engineering design approval or authorization for construction. PostgreSQL creates the `corrections` and `revisions` tables automatically on startup; existing comparison data and Groq cache entries are preserved.

Repeated AI requests from the same visitor for the same PDF bytes, checklist, model, prompt/schema version, and analysis limits reuse validated results from PostgreSQL. Cache entries are visitor-scoped. The dashboard marks cache hits and shows no new API token usage for them. Check **Force fresh Groq analysis** to bypass the cache safely; it uses the visitor's Groq quota. Failed or invalid AI responses are never cached. For a missing clause, the AI must cite the approved reference; an unrelated submitted header is rejected.

Core API endpoints: `POST /api/compare`, `GET /api/comparisons`, `GET /api/comparisons/{session_id}`, `PATCH /api/comparisons/{session_id}/requirements/{requirement_id}/review`, and `GET /api/comparisons/{session_id}/report`. The older finding-level review route remains available for compatibility.

To regenerate the PDFs, run `python samples/generate_pdfs.py` from the project root after installing backend requirements.

## Tests

Database integration tests require `TEST_DATABASE_URL` pointing to a **disposable, separate PostgreSQL database**; the fixture truncates its Docwise tables between tests. It rejects the production Supabase project before creating tables or truncating data. Without a test URL, database tests are skipped and pure tests still run. Automated tests mock Groq and never use live API credits.

```powershell
cd backend
python -m pytest -q
cd ..\frontend
npm run test:ui
npm run build
```

### Isolated PostgreSQL integration tests

The safest free-tier setup is a second Supabase **Free project** dedicated to tests. Supabase currently allows two active Free projects. A schema inside the production project is not supported by this test fixture: its SQL uses the default schema and unqualified `TRUNCATE`, so a misconfigured search path could touch production data.

1. In the [Supabase dashboard](https://supabase.com/dashboard/new), create a second Free project named `docwise-test` in a Free organization. Do not reuse the production project. Keep this project disposable; tests clear Docwise tables in it.
2. In the test project's **Connect** dialog, select **Session pooler** and copy its connection URI (port 5432). Replace the password placeholder, URL-encode reserved password characters, and append `?sslmode=require` if needed.
3. Put the URI in the gitignored `backend/.env` as `TEST_DATABASE_URL`. Keep the production `DATABASE_URL` as it is. The pooler username's project reference must differ; the test fixture checks this before any writes.
4. From `backend`, run `python -m pytest -q`. The 27 previously skipped database tests should now execute. If the second Free project slot is unavailable, install a local PostgreSQL server and use a separate database named with an `_test` suffix instead.

Creating a separate PostgreSQL database or schema inside the production Supabase project is not recommended for this test suite. The separate project provides a stronger isolation boundary. The production schema has been initialized separately; never point `TEST_DATABASE_URL` at that project.

## Existing SQLite data

PostgreSQL does not read the old SQLite file automatically. Back it up first. To transfer all existing tables, keep the old file outside Git, set `DATABASE_URL` to a **new, empty** PostgreSQL database, then run from `backend`:

```powershell
python migrate_sqlite_to_postgres.py .\data\document_qa.sqlite3
```

The script reads SQLite without modifying it, preserves IDs and ownership, and aborts if the target contains rows or an unsupported source column. It reports transferred row counts. Keep the same `DOCWISE_SESSION_SECRET` when moving existing visitor sessions, or their signed cookies cannot reopen saved comparisons. Records older than the configured retention period are removed at the next backend startup. No transfer has been run as part of this code change.

## Structure

- `backend/app/pdf.py`: PDF validation and page text extraction
- `backend/app/comparison.py`: deterministic clause matching and citation selection
- `backend/app/ai.py`: bounded Groq requests, retries, structured validation, citation checks, usage, and optional cost estimate
- `backend/app/cache.py`: SHA-256 cache key construction
- `backend/app/db.py`: PostgreSQL sessions, document hashes, findings, reviews, audit events, and cache
- `backend/app/report.py`: ReportLab QA report generation from saved state
- `backend/app/revision.py`: structured revision PDF from an immutable saved snapshot
- `backend/app/models.py`: request and response models
- `backend/app/main.py`: FastAPI routes
- `frontend/src/`: typed API integration, reusable dashboard components, and styles
- `frontend/public/branding/docwise-logo.png`: transparent supplied Docwise logo; the reusable `Brand` component crops its symbol and renders light sidebar lettering
- `frontend/public/favicon.svg`: document/check favicon; replace this asset to use a future official favicon
- `samples/`: fictional PDFs, generator, and checklist
- `DEVELOPMENT_PLAN.md`: phased roadmap

## Production deployment (Vercel + Render)

The application supports anonymous, cookie-bound visitor workspaces. The backend signs a random visitor ID in an `HttpOnly` cookie; comparisons, review data, corrections, revisions, and downloads are scoped to that ID. A lost/expired cookie cannot recover its history. Existing rows without an owner remain inaccessible rather than being assigned to the first visitor.

1. Create a Supabase PostgreSQL project and copy its Session Pooler URI. Set the backend-only `DATABASE_URL` in Render with `sslmode=require`. The `render.yaml` Blueprint uses Render Free, no persistent disk, and starts FastAPI on `$PORT`.
2. In Render, set `GROQ_API_KEY` to a secret from Groq and set `DOCWISE_CORS_ORIGINS` to the exact Vercel production origin (for example `https://docwise.vercel.app`, plus any custom frontend origin). Render generates `DOCWISE_SESSION_SECRET` from the Blueprint. Keep `DOCWISE_ENV=production`. Never put database credentials or the Groq key in a `VITE_` variable.
3. Import the `frontend` directory as the Vercel project root. Vercel uses `frontend/vercel.json` to build the Vite app and proxy `/api/*` to `https://docwise-api.onrender.com`; this same-origin proxy allows the visitor cookie to work without relying on third-party-cookie support. If the Render service gets a different public hostname, update that rewrite destination and redeploy. No `VITE_API_BASE_URL` is needed for the provided rewrite. An optional `VITE_API_BASE_URL` can target another public API; for direct cross-origin use, configure the exact frontend origin in Render and allow credentialed requests.
4. Verify `/api/health` reports both `status` and `database` as `ok`, then test a sample comparison, review, correction, and both downloads on the deployed frontend.

The backend environment variables and examples are listed in `backend/.env.example` and `render.yaml`. The default safeguards are: 22 MiB maximum API request body, 10 MiB per PDF, 100 pages per PDF, 120 requests/minute per visitor and 300/minute per IP, 10 comparisons/day per visitor and 30/IP, and 3 uncached Groq analyses/day per visitor and 10/IP. Force-refresh consumes the Groq quota; validated cache hits do not. Set these with `DOCWISE_MAX_REQUEST_BYTES`, `DOCWISE_RATE_LIMIT_PER_MINUTE`, `DOCWISE_IP_RATE_LIMIT_PER_MINUTE`, `DOCWISE_DAILY_COMPARISONS_PER_VISITOR`, `DOCWISE_DAILY_COMPARISONS_PER_IP`, `DOCWISE_DAILY_GROQ_PER_VISITOR`, and `DOCWISE_DAILY_GROQ_PER_IP`. Limits use PostgreSQL transaction locks across workers.

Visitor records (including extracted evidence, audit history, corrections, and revisions) and cached AI findings are deleted after `DOCWISE_RETENTION_DAYS` (30 by default); cleanup runs at startup and every 24 hours. Usage limits use rolling 24-hour windows and old counters are periodically pruned. Uploaded PDF bytes are processed from temporary upload storage and are not saved to the database. PostgreSQL stores document names, hashes, extracted evidence, and workflow data, so it still contains potentially sensitive document-derived information until retention cleanup.

The cookie provides anonymous workspace isolation, not identity verification or account recovery. A visitor who clears cookies loses access to their previous workspace; IP quotas reduce, but cannot eliminate, evasion through changing networks/devices. No OCR is provided for scanned PDFs, and comparisons/revisions remain review aids rather than engineering certification.

## Current limits

Text-based PDFs only; scanned pages require OCR in a later phase. Deterministic matching is line-oriented and may flag valid rewording. AI findings remain suggestions even when their citations are verified. There are no named reviewer accounts or identity recovery; the signed anonymous visitor cookie is the workspace boundary. Deterministic mode needs no API key.
