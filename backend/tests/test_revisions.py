"""Human correction and structured revision workflow; never calls Groq."""
import json
import os
import psycopg

import pymupdf
from fastapi.testclient import TestClient

from app.db import init_db
from app.main import app


client = TestClient(app)
CHECKLIST = [
    {"id": "R-01", "title": "Design pressure", "reference_text": "Design pressure: 150 kPa."},
    {"id": "R-04", "title": "Inspection method",
     "reference_text": "Inspection method: visual inspection and hydrostatic test."},
]


def pdf(*lines: str) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    for index, line in enumerate(lines):
        page.insert_text((72, 72 + index * 20), line)
    result = document.tobytes()
    document.close()
    return result


def comparison():
    reference = pdf(*(item["reference_text"] for item in CHECKLIST))
    submitted = pdf("Design pressure: 120 kPa.", "Project: NS-042")
    response = client.post("/api/compare", files={
        "reference": ("approved.pdf", reference, "application/pdf"),
        "submitted": ("submitted.pdf", submitted, "application/pdf")},
        data={"checklist": json.dumps(CHECKLIST), "mode": "deterministic"})
    assert response.status_code == 200, response.text
    return response.json(), submitted


def correction(session, finding, corrected="150 kPa", previous=None):
    payload = {"finding_id": finding["id"], "field_name": finding["title"],
               "corrected_value": corrected, "reason": "Checked against approved specification.",
               "supporting_notes": "Approved reference page 1"}
    path = f"/api/comparisons/{session}/corrections"
    return client.put(path + "/" + previous, json=payload) if previous else client.post(path, json=payload)


def status(session, correction_id, value, note="Reviewed by qualified person"):
    return client.patch(f"/api/comparisons/{session}/corrections/{correction_id}/status",
                        json={"status": value, "note": note})


def test_correction_migration_and_review_gate(tmp_path):
    result, _ = comparison()
    session = result["session_id"]
    finding = result["findings"][0]
    assert correction(session, finding).status_code == 409
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as db:
        before = db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    init_db()
    init_db()
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as db:
        tables = {row[0] for row in db.execute("SELECT tablename FROM pg_tables WHERE schemaname=current_schema()")}
        assert {"sessions", "findings", "ai_cache", "corrections", "revisions"} <= tables
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
    assert before == 1  # Existing data survives repeated initialization.
    assert client.patch(f"/api/comparisons/{session}/findings/{finding['id']}/review",
                        json={"status": "accepted", "comment": "Confirmed mismatch."}).status_code == 200
    assert correction(session, finding, corrected="   ").status_code == 422
    created = correction(session, finding).json()
    assert created["status"] == "draft" and created["original_value"].startswith("Design pressure: 120")
    assert status(session, created["id"], "verified").status_code == 409
    assert status(session, created["id"], "pending_verification").status_code == 200
    assert status(session, created["id"], "verified").status_code == 200
    assert status(session, created["id"], "draft").status_code == 409
    history = client.get(f"/api/comparisons/{session}").json()["audit_events"]
    assert {"correction_created", "correction_status_changed", "review_updated"} <= {event["action"] for event in history}


def test_revision_snapshot_numbering_and_original_preservation():
    result, original_pdf = comparison()
    session = result["session_id"]
    first, missing = result["findings"]
    for finding in (first, missing):
        assert client.patch(f"/api/comparisons/{session}/findings/{finding['id']}/review",
                            json={"status": "accepted", "comment": "Confirmed issue."}).status_code == 200
    pressure = correction(session, first).json()
    draft = client.post(f"/api/comparisons/{session}/revisions").json()
    assert draft["status"] == "draft" and draft["number"] == 1
    draft_pdf = client.get(f"/api/comparisons/{session}/revisions/{draft['id']}/pdf")
    assert draft_pdf.status_code == 200 and draft_pdf.content.startswith(b"%PDF")
    with pymupdf.open(stream=draft_pdf.content, filetype="pdf") as document:
        text = "".join(page.get_text() for page in document)
    assert "Draft Revision" in text and "150 kPa" in text
    assert "not an edited copy" in text
    assert status(session, pressure["id"], "pending_verification").status_code == 200
    assert status(session, pressure["id"], "verified").status_code == 200
    still_draft = client.post(f"/api/comparisons/{session}/revisions").json()
    assert still_draft["status"] == "draft"  # The other confirmed issue has no correction.
    inspection = correction(session, missing, corrected="Visual inspection and hydrostatic test.").json()
    assert inspection["original_value"] == "Missing"
    assert status(session, inspection["id"], "pending_verification").status_code == 200
    assert status(session, inspection["id"], "verified").status_code == 200
    verified = client.post(f"/api/comparisons/{session}/revisions").json()
    assert verified["status"] == "verified" and verified["number"] == 3
    with pymupdf.open(stream=client.get(f"/api/comparisons/{session}/revisions/{verified['id']}/pdf").content,
                      filetype="pdf") as document:
        text = "".join(page.get_text() for page in document)
    assert "Verified Revision" in text and "Visual inspection and hydrostatic test" in text
    assert "authorization for construction" in text
    edited = correction(session, first, corrected="155 kPa", previous=pressure["id"]).json()
    assert edited["status"] == "draft" and edited["original_value"] == pressure["original_value"]
    current_report = client.get(f"/api/comparisons/{session}/report")
    with pymupdf.open(stream=current_report.content, filetype="pdf") as document:
        report_text = "".join(page.get_text() for page in document)
    assert "Correction: Draft" in report_text
    all_versions = client.get(f"/api/comparisons/{session}/corrections?include_history=true").json()
    assert len(all_versions) == 3 and any(item["id"] == pressure["id"] and item["superseded_at"] for item in all_versions)
    with pymupdf.open(stream=client.get(f"/api/comparisons/{session}/revisions/{verified['id']}/pdf").content,
                      filetype="pdf") as document:
        old_text = "".join(page.get_text() for page in document)
    assert "155 kPa" not in old_text  # Published revision is an immutable snapshot.
    restored = client.get(f"/api/comparisons/{session}").json()
    assert restored["findings"][0]["submitted"]["excerpt"].startswith("Design pressure: 120")
    assert original_pdf.startswith(b"%PDF")
    assert len(client.get(f"/api/comparisons/{session}/revisions").json()) == 3


def test_rejected_and_unconfirmed_corrections_not_verified():
    result, _ = comparison()
    session = result["session_id"]
    finding = result["findings"][0]
    client.patch(f"/api/comparisons/{session}/findings/{finding['id']}/review",
                 json={"status": "accepted", "comment": "Confirmed."})
    item = correction(session, finding).json()
    status(session, item["id"], "pending_verification")
    status(session, item["id"], "rejected")
    assert client.post(f"/api/comparisons/{session}/revisions").status_code == 409
    replacement = correction(session, finding, corrected="150 kPa", previous=item["id"]).json()
    client.patch(f"/api/comparisons/{session}/findings/{finding['id']}/review",
                 json={"status": "rejected", "comment": "False positive after review."})
    assert status(session, replacement["id"], "pending_verification").status_code == 200
    assert status(session, replacement["id"], "verified").status_code == 409
    assert client.post(f"/api/comparisons/{session}/revisions").status_code == 409
