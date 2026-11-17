# Development plan

## Phase 1 - local comparison MVP

1. Create a FastAPI service with bounded PDF uploads, PDF text extraction with page numbers, and deterministic checklist comparison.
2. Create a React, TypeScript, and Tailwind dashboard for two uploads, editable requirements, and cited results.
3. Include fictional sample documents, a starter checklist, automated backend tests, and setup instructions.

## Phase 2 - AI-assisted comparison

4. Add Groq semantic analysis using only relevant excerpts. Validate model responses and verify every citation against extracted text. Complete.
5. Add a mode selector, bounded retries, token usage, optional configured cost estimate, and mocked tests. Complete.

## Phase 3 - saved review workflow

6. Add review decisions, SQLite persistence, hash-based AI caching, execution metadata, and PDF reports. Complete.
7. Require approved-reference citations for missing clauses and reject unrelated submitted evidence. Complete.

## Later phases

8. Harden deployment, add authentication and named reviewers, and prepare a PostgreSQL migration path.

The application is a reviewer aid and does not certify engineering compliance.
