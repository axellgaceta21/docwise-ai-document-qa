"""Requirement-level review keeps old finding decisions as evidence."""
import json
import sqlite3
from uuid import uuid4

import pymupdf
from fastapi.testclient import TestClient

from app.db import init_db
from app.main import app
from app.report import audit_label


client = TestClient(app)
CHECKLIST = [
    {"id": "R-01", "title": "Design pressure", "reference_text": "Design pressure: 150 kPa."},
    {"id": "R-02", "title": "Operating temperature", "reference_text": "Operating temperature: 80 C."},
]


def pdf(*lines):
    document = pymupdf.open()
    page = document.new_page()
    for index, line in enumerate(lines):
        page.insert_text((72, 72 + index * 20), line)
    data = document.tobytes()
    document.close()
    return data


def compare():
    response = client.post("/api/compare", files={
        "reference": ("approved.pdf", pdf(*(item["reference_text"] for item in CHECKLIST)), "application/pdf"),
        "submitted": ("submitted.pdf", pdf("Design pressure: 120 kPa.", CHECKLIST[1]["reference_text"]), "application/pdf")},
        data={"checklist": json.dumps(CHECKLIST), "mode": "deterministic"})
    assert response.status_code == 200, response.text
    return response.json()


def review(session, requirement, status, comment=""):
    return client.patch(f"/api/comparisons/{session}/requirements/{requirement}/review",
                        json={"status": status, "comment": comment})


def test_one_final_decision_persists_and_preserves_findings(tmp_path):
    result = compare()
    session = result["session_id"]
    assert [item["status"] for item in result["requirement_reviews"]] == ["pending", "pending"]
    assert review(session, "R-02", "accepted").status_code == 409  # clean match
    changed = review(session, "R-01", "accepted", "Checked specification.")
    assert changed.status_code == 200 and changed.json()["source"] == "explicit"
    reopened = client.get(f"/api/comparisons/{session}").json()
    assert reopened["requirement_reviews"][0]["status"] == "accepted"
    assert reopened["requirement_reviews"][0]["comment"] == "Checked specification."
    assert reopened["findings"][0]["review_status"] == "pending"  # evidence record untouched
    correction = client.post(f"/api/comparisons/{session}/corrections", json={
        "finding_id": reopened["findings"][0]["id"], "field_name": "Design pressure",
        "corrected_value": "150 kPa", "reason": "Checked against approved reference.",
        "supporting_notes": "Approved PDF, page 1"})
    assert correction.status_code == 200, correction.text
    correction_id = correction.json()["id"]
    for status in ("pending_verification", "verified"):
        assert client.patch(f"/api/comparisons/{session}/corrections/{correction_id}/status",
                            json={"status": status, "note": "Human checked"}).status_code == 200
    revision = client.post(f"/api/comparisons/{session}/revisions").json()
    assert revision["status"] == "verified"
    assert client.get(f"/api/comparisons/{session}/revisions/{revision['id']}/pdf").content.startswith(b"%PDF")
    verified_report = client.get(f"/api/comparisons/{session}/report")
    with pymupdf.open(stream=verified_report.content, filetype="pdf") as document:
        verified_text = "".join(page.get_text() for page in document)
    assert "Correction: Verified" in verified_text
    assert review(session, "R-01", "rejected", "False alarm.").status_code == 200
    assert client.post(f"/api/comparisons/{session}/revisions").status_code == 409
    reopened = client.get(f"/api/comparisons/{session}").json()
    assert reopened["requirement_reviews"][0]["status"] == "rejected"
    transitions = [event for event in reopened["audit_events"] if event["action"] == "requirement_review_updated"]
    assert [(item["old_status"], item["new_status"]) for item in transitions] == [
        ("pending", "accepted"), ("accepted", "rejected")]
    with sqlite3.connect(tmp_path / "qa.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM requirement_reviews").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM corrections").fetchone()[0] == 1
    report = client.get(f"/api/comparisons/{session}/report")
    with pymupdf.open(stream=report.content, filetype="pdf") as document:
        text = "".join(page.get_text() for page in document)
    assert "Not an issue" in text
    assert "Correction: Not Required" in text


def test_conflicting_legacy_decisions_are_flagged_and_not_overwritten(tmp_path):
    result = compare()
    session = result["session_id"]
    deterministic = result["findings"][0]["id"]
    ai_id = str(uuid4())
    payload = {
        "id": ai_id, "requirement_id": "R-01", "discrepancy_type": "value_mismatch",
        "severity": "medium", "explanation": "Pressure values differ.",
        "source_document": "reference", "page_number": 1,
        "supporting_excerpt": "Design pressure: 150 kPa.", "uncertain": False,
        "citation_verified": True, "review_status": "pending", "review_comment": "",
    }
    init_db()
    with sqlite3.connect(tmp_path / "qa.sqlite3") as db:
        db.execute("""INSERT INTO findings
            (id, session_id, requirement_id, kind, payload_json, review_status, review_comment, position)
            VALUES (?, ?, ?, 'ai', ?, 'pending', '', 0)""",
            (ai_id, session, "R-01", json.dumps(payload)))
    client.patch(f"/api/comparisons/{session}/findings/{deterministic}/review",
                 json={"status": "accepted", "comment": "Old document decision."})
    client.patch(f"/api/comparisons/{session}/findings/{ai_id}/review",
                 json={"status": "rejected", "comment": "Old AI decision."})
    before = client.get(f"/api/comparisons/{session}").json()
    state = before["requirement_reviews"][0]
    assert state["status"] == "pending" and state["ambiguous_legacy"] is True and state["source"] == "legacy"
    assert review(session, "R-01", "needs_investigation", "Resolve the conflict.").status_code == 200
    after = client.get(f"/api/comparisons/{session}").json()
    assert after["requirement_reviews"][0]["status"] == "needs_investigation"
    assert after["requirement_reviews"][0]["source"] == "explicit"
    assert after["findings"][0]["review_status"] == "accepted"
    assert after["ai_findings"][0]["review_status"] == "rejected"
    assert len([event for event in after["audit_events"] if event["action"] == "review_updated"]) == 2
    assert audit_label(after["audit_events"][-1]) == "Sent for further checking"


def test_ai_concern_on_deterministic_match_requires_one_final_review(tmp_path):
    result = compare()
    session = result["session_id"]
    ai_id = str(uuid4())
    payload = {
        "id": ai_id, "requirement_id": "R-02", "discrepancy_type": "unclear",
        "severity": "unknown", "explanation": "Meaning may differ despite matching text.",
        "source_document": "reference", "page_number": 1,
        "supporting_excerpt": CHECKLIST[1]["reference_text"], "uncertain": True,
        "citation_verified": True, "review_status": "pending", "review_comment": "",
    }
    with sqlite3.connect(tmp_path / "qa.sqlite3") as db:
        db.execute("""INSERT INTO findings
            (id, session_id, requirement_id, kind, payload_json, review_status, review_comment, position)
            VALUES (?, ?, ?, 'ai', ?, 'pending', '', 0)""",
            (ai_id, session, "R-02", json.dumps(payload)))
    response = review(session, "R-02", "needs_investigation", "AI concern needs checking.")
    assert response.status_code == 200
    reopened = client.get(f"/api/comparisons/{session}").json()
    assert reopened["requirement_reviews"][1]["status"] == "needs_investigation"
    assert reopened["findings"][1]["status"] == "match"
    assert reopened["ai_findings"][0]["review_status"] == "pending"
