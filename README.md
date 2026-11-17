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

SQLite initializes automatically on first use at `backend/data/document_qa.sqlite3`. To initialize it explicitly, run `python -m app.db` from `backend`. Set `DOCUMENT_QA_DB_PATH` in `backend/.env` to use another local path. The database stores document names, hashes, page counts, checklist clauses, findings, review decisions, audit events, and execution metadata; it does not store PDF binaries.

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

The current review workflow records **one final human decision per requirement**. Document comparison and AI findings remain separate evidence. A clean match with no AI concern shows **No review needed**. Existing finding-level decisions remain in the database and audit history. When older finding decisions disagree, Docwise marks the requirement **Needs review** and asks for an explicit final decision; it does not rewrite the older records. The SQLite `requirement_reviews` table is created automatically on first use.

The Correction column is derived from that final review and the current correction version. Clean matches and dismissed findings show **Not Required**; pending decisions show **Awaiting Review**; confirmed issues move through **Needs Correction**, **Draft**, **Pending Verification**, and **Verified**. A rejected correction shows **Correction Rejected**. Editing a verified correction creates a new draft, so the current requirement no longer displays Verified until the new version is verified.

## Corrections and structured revisions

In Document Review, open a requirement, choose its finding, and mark a valid discrepancy **Confirmed issue**. Enter the corrected value and reason, save a draft correction, then send it for verification. A reviewer must explicitly select **Verify correction**; confirming the issue alone never verifies a correction. Rejected and unconfirmed corrections cannot be included in a generated revision. Editing a correction creates a new draft while retaining the earlier version and audit events.

Use **Generate revised document** below the results table. It creates a numbered **Draft Revision** if included corrections still need verification, or a **Verified Revision** if all included corrections are verified and confirmed issues have corrections. Download this structured PDF separately from the existing QA Report. It is not an edited copy of the uploaded engineering PDF, and neither status is engineering design approval or authorization for construction. SQLite creates the `corrections` and `revisions` tables automatically on startup; existing comparison data and Groq cache entries are preserved.

Repeated AI requests from the same visitor for the same PDF bytes, checklist, model, prompt/schema version, and analysis limits reuse validated results from SQLite. Cache entries are visitor-scoped. The dashboard marks cache hits and shows no new API token usage for them. Check **Force fresh Groq analysis** to bypass the cache safely; it uses the visitor's Groq quota. Failed or invalid AI responses are never cached. For a missing clause, the AI must cite the approved reference; an unrelated submitted header is rejected.

Core API endpoints: `POST /api/compare`, `GET /api/comparisons`, `GET /api/comparisons/{session_id}`, `PATCH /api/comparisons/{session_id}/requirements/{requirement_id}/review`, and `GET /api/comparisons/{session_id}/report`. The older finding-level review route remains available for compatibility.

To regenerate the PDFs, run `python samples/generate_pdfs.py` from the project root after installing backend requirements.

## Tests

```powershell
cd backend
python -m pytest -q
cd ..\frontend
npm run test:ui
npm run build
```

## Structure

- `backend/app/pdf.py`: PDF validation and page text extraction
- `backend/app/comparison.py`: deterministic clause matching and citation selection
- `backend/app/ai.py`: bounded Groq requests, retries, structured validation, citation checks, usage, and optional cost estimate
- `backend/app/cache.py`: SHA-256 cache key construction
- `backend/app/db.py`: SQLite sessions, document hashes, findings, reviews, audit events, and cache
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

1. Deploy the repository's `render.yaml` Blueprint. It configures the `docwise-api` FastAPI service, `/api/health`, a 1 GB persistent disk mounted at `/var/data`, and the SQLite file `/var/data/docwise.sqlite3`. Keep the Render service at one instance; SQLite on a mounted disk is not shared multi-instance storage. The persistent disk requires a paid Render plan; do not use ephemeral storage for real user data.
2. In Render, set `GROQ_API_KEY` to a secret from Groq and set `DOCWISE_CORS_ORIGINS` to the exact Vercel production origin (for example `https://docwise.vercel.app`, plus any custom frontend origin). Render generates `DOCWISE_SESSION_SECRET` from the Blueprint. Keep `DOCWISE_ENV=production` and the configured database path. Never put the Groq key in a `VITE_` variable.
3. Import the `frontend` directory as the Vercel project root. Vercel uses `frontend/vercel.json` to build the Vite app and proxy `/api/*` to `https://docwise-api.onrender.com`; this same-origin proxy allows the visitor cookie to work without relying on third-party-cookie support. If the Render service gets a different public hostname, update that rewrite destination and redeploy. No `VITE_API_BASE_URL` is needed for the provided rewrite. An optional `VITE_API_BASE_URL` can target another public API; for direct cross-origin use, configure the exact frontend origin in Render and allow credentialed requests.
4. Verify `/api/health` reports both `status` and `database` as `ok`, then test a sample comparison, review, correction, and both downloads on the deployed frontend.

The backend environment variables and examples are listed in `backend/.env.example` and `render.yaml`. The default safeguards are: 22 MiB maximum API request body, 10 MiB per PDF, 100 pages per PDF, 120 requests/minute per visitor and 300/minute per IP, 10 comparisons/day per visitor and 30/IP, and 3 uncached Groq analyses/day per visitor and 10/IP. Force-refresh consumes the Groq quota; validated cache hits do not. Set these with `DOCWISE_MAX_REQUEST_BYTES`, `DOCWISE_RATE_LIMIT_PER_MINUTE`, `DOCWISE_IP_RATE_LIMIT_PER_MINUTE`, `DOCWISE_DAILY_COMPARISONS_PER_VISITOR`, `DOCWISE_DAILY_COMPARISONS_PER_IP`, `DOCWISE_DAILY_GROQ_PER_VISITOR`, and `DOCWISE_DAILY_GROQ_PER_IP`. Limits use SQLite and therefore assume one Render instance.

Visitor records (including extracted evidence, audit history, corrections, and revisions) and cached AI findings are deleted after `DOCWISE_RETENTION_DAYS` (30 by default); cleanup runs at startup and every 24 hours. Usage limits use rolling 24-hour windows and old counters are periodically pruned. Uploaded PDF bytes are processed from temporary upload storage and are not saved to the database or persistent disk. SQLite stores document names, hashes, extracted evidence, and workflow data, so it still contains potentially sensitive document-derived information until retention cleanup. Back up or delete the entire mounted database deliberately; do not copy it into source control.

The cookie provides anonymous workspace isolation, not identity verification or account recovery. A visitor who clears cookies loses access to their previous workspace; IP quotas reduce, but cannot eliminate, evasion through changing networks/devices. SQLite deployment is appropriate only for a single backend instance; migrate to a shared database before horizontal scaling. No OCR is provided for scanned PDFs, and comparisons/revisions remain review aids rather than engineering certification.

## Current limits

Text-based PDFs only; scanned pages require OCR in a later phase. Deterministic matching is line-oriented and may flag valid rewording. AI findings remain suggestions even when their citations are verified. There are no named reviewer accounts or identity recovery; the signed anonymous visitor cookie is the workspace boundary. SQLite is configured for a single-instance deployment, not multi-instance scaling. Deterministic mode needs no API key.
