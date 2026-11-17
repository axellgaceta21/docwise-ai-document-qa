import sqlite3

from app.db import database_path, get_comparison, init_db, save_comparison
from app.models import Citation, CompareResponse, Finding, Requirement


def test_legacy_sessions_migrate_without_losing_rows_and_new_comparison_saves():
    path = database_path()
    with sqlite3.connect(path) as connection:
        connection.execute("""CREATE TABLE sessions (
            id TEXT PRIMARY KEY, created_at TEXT NOT NULL, mode TEXT NOT NULL,
            reference_name TEXT NOT NULL, submitted_name TEXT NOT NULL,
            reference_pages INTEGER NOT NULL, submitted_pages INTEGER NOT NULL,
            ai_status TEXT NOT NULL, ai_message TEXT, ai_model TEXT, cache_hit INTEGER NOT NULL,
            prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER,
            estimated_cost_usd REAL, duration_ms INTEGER NOT NULL)""")
        connection.execute("""INSERT INTO sessions
            (id, created_at, mode, reference_name, submitted_name, reference_pages, submitted_pages,
             ai_status, ai_message, ai_model, cache_hit, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("existing-session", "2026-01-01T00:00:00+00:00", "deterministic", "old-reference.pdf",
             "old-submission.pdf", 1, 1, "not_requested", None, None, 0, 25))

    init_db()
    init_db()  # Repeated startup must be safe.
    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(sessions)")}
        old = connection.execute("SELECT reference_name, duration_ms, ai_duration_ms, owner_id FROM sessions WHERE id=?",
                                 ("existing-session",)).fetchone()
    assert "ai_duration_ms" in columns
    assert "owner_id" in columns
    assert old == ("old-reference.pdf", 25, None, None)

    requirement = Requirement(id="R-01", title="Pressure", reference_text="Design pressure: 150 kPa.")
    finding = Finding(requirement_id="R-01", title="Pressure", status="missing",
                      explanation="Clause absent", reference=Citation(page=1, excerpt=requirement.reference_text))
    result = CompareResponse(reference_name="new-reference.pdf", submitted_name="new-submission.pdf",
                             reference_pages=1, submitted_pages=1, findings=[finding], duration_ms=30, ai_duration_ms=7)
    saved = save_comparison(result, [requirement], {"reference": "a" * 64, "submitted": "b" * 64},
                            owner_id="a" * 32)
    restored = get_comparison(saved.session_id)
    assert restored is not None
    assert restored.ai_duration_ms == 7
    assert restored.findings[0].requirement_id == "R-01"
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 2
        assert connection.execute("SELECT reference_name FROM sessions WHERE id='existing-session'").fetchone()[0] == "old-reference.pdf"
