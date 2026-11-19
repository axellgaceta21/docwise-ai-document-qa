"""PostgreSQL schema and saved comparison regression checks."""
from app.db import database, get_comparison, init_db, save_comparison
from app.models import Citation, CompareResponse, Finding, Requirement


def test_schema_initialization_and_comparison_round_trip():
    init_db()
    init_db()
    with database() as connection:
        tables = {row["tablename"] for row in connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname=current_schema()")}
        assert {"sessions", "documents", "requirements", "findings", "audit_events",
                "ai_cache", "corrections", "revisions", "requirement_reviews", "api_usage"} <= tables

    requirement = Requirement(id="R-01", title="Pressure", reference_text="Design pressure: 150 kPa.")
    finding = Finding(requirement_id="R-01", title="Pressure", status="missing",
                      explanation="Clause absent", reference=Citation(page=1, excerpt=requirement.reference_text))
    result = CompareResponse(reference_name="reference.pdf", submitted_name="submission.pdf",
                             reference_pages=1, submitted_pages=1, findings=[finding],
                             duration_ms=30, ai_duration_ms=7)
    saved = save_comparison(result, [requirement], {"reference": "a" * 64, "submitted": "b" * 64},
                            owner_id="a" * 32)
    restored = get_comparison(saved.session_id)
    assert restored is not None
    assert restored.ai_duration_ms == 7
    assert restored.findings[0].requirement_id == "R-01"
    with database() as connection:
        row = connection.execute("SELECT owner_id FROM sessions WHERE id=%s", (saved.session_id,)).fetchone()
        assert row["owner_id"] == "a" * 32
