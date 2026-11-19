"""Safe unit checks for the review save path; no database connection is made."""
from contextlib import contextmanager
from fastapi import Response

from app import db, main
from app.models import ReviewUpdate


def test_review_route_uses_transactional_owner_check_and_reports_timing(monkeypatch):
    calls = []
    event = dict(id="event-1", finding_id=None, action="requirement_review_updated",
                 old_status="pending", new_status="accepted", comment="checked",
                 detail="R-01", occurred_at="2026-01-01T00:00:00+00:00")

    def update(session_id, requirement_id, review, owner_id):
        calls.append((session_id, requirement_id, owner_id))
        return dict(requirement_id=requirement_id, status=review.status, comment=review.comment,
                    source="explicit", ambiguous_legacy=False, audit_event=event)

    monkeypatch.setattr(main, "update_requirement_review", update)
    monkeypatch.setattr(main, "require_session_owner", lambda *_: (_ for _ in ()).throw(
        AssertionError("separate owner connection used")))
    response = Response()
    saved = main.review_requirement("session-1", "R-01", ReviewUpdate(status="accepted", comment="checked"),
                                    response, visitor_id="visitor-1")
    assert calls == [("session-1", "R-01", "visitor-1")]
    assert saved.audit_event == event
    assert response.headers["Server-Timing"].startswith("review_db;dur=")


def test_audit_event_response_matches_persisted_record():
    class Connection:
        def execute(self, statement, values):
            self.values = values

    connection = Connection()
    event = db._event(connection, "session-1", "requirement_review_updated",
                      old_status="pending", new_status="accepted", comment="checked", detail="R-01")
    assert (event["id"], "session-1", event["finding_id"], event["action"],
            event["old_status"], event["new_status"], event["comment"],
            event["detail"], event["occurred_at"]) == connection.values


def test_non_owner_cannot_reach_review_writes(monkeypatch):
    class NoRow:
        def fetchone(self):
            return None

    class Connection:
        def execute(self, statement, values):
            assert "FROM sessions WHERE id=%s AND owner_id=%s FOR UPDATE" in statement
            assert values == ("session-1", "visitor-1")
            return NoRow()

    @contextmanager
    def fake_database():
        yield Connection()

    monkeypatch.setattr(db, "init_db", lambda: None)
    monkeypatch.setattr(db, "database", fake_database)
    assert db.update_requirement_review("session-1", "R-01", ReviewUpdate(status="accepted"),
                                        "visitor-1") is None
