import hashlib
import json
import sqlite3
from types import SimpleNamespace

import pymupdf
from fastapi.testclient import TestClient

from app import ai
from app.cache import analysis_key, pdf_hash
from app.main import app
from app.models import Requirement


client = TestClient(app)
CHECKLIST = [{"id": "R-04", "title": "Inspection method", "reference_text": "Inspection method: visual inspection and hydrostatic test."}]


def pdf(*lines: str) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    for index, line in enumerate(lines):
        page.insert_text((72, 72 + index * 20), line)
    data = document.tobytes()
    document.close()
    return data


def post(reference: bytes, submitted: bytes, *, mode="deterministic", force=False):
    return client.post("/api/compare", files={
        "reference": ("approved.pdf", reference, "application/pdf"),
        "submitted": ("revision.pdf", submitted, "application/pdf")},
        data={"checklist": json.dumps(CHECKLIST), "mode": mode, "force_refresh": str(force).lower()})


def ai_response(finding):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"findings": [finding]})))],
                           usage=SimpleNamespace(prompt_tokens=80, completion_tokens=30))


class FakeGroq:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.outputs.pop(0)

    async def close(self):
        pass


def reference_item():
    return {"requirement_id": "R-04", "discrepancy_type": "missing_clause", "severity": "medium",
            "explanation": "The approved inspection method has no corresponding submitted clause.",
            "source_document": "reference", "page_number": 1,
            "supporting_excerpt": CHECKLIST[0]["reference_text"], "uncertain": True}


def sample_documents():
    return pdf(CHECKLIST[0]["reference_text"]), pdf("Project: NS-042", "Operating temperature: 80 C.")


def test_database_persistence_review_audit_and_report(monkeypatch, tmp_path):
    reference, submitted = sample_documents()
    response = post(reference, submitted)
    assert response.status_code == 200
    body = response.json()
    session_id = body["session_id"]
    finding_id = body["findings"][0]["id"]
    assert session_id and finding_id and body["findings"][0]["review_status"] == "pending"
    assert body["findings"][0]["status"] == "missing"
    db = sqlite3.connect(tmp_path / "qa.sqlite3")
    rows = db.execute("SELECT role, sha256 FROM documents ORDER BY role").fetchall()
    assert rows == [("reference", hashlib.sha256(reference).hexdigest()),
                    ("submitted", hashlib.sha256(submitted).hexdigest())]
    assert db.execute("SELECT COUNT(*) FROM requirements").fetchone()[0] == 1
    db.close()
    reviewed = client.patch(f"/api/comparisons/{session_id}/findings/{finding_id}/review",
                            json={"status": "needs_investigation", "comment": "Check source drawing."})
    assert reviewed.status_code == 200
    revised = client.patch(f"/api/comparisons/{session_id}/findings/{finding_id}/review",
                           json={"status": "accepted", "comment": "Confirmed omission; not a compliance approval."})
    assert revised.status_code == 200
    restored = client.get(f"/api/comparisons/{session_id}")
    assert restored.status_code == 200
    data = restored.json()
    assert data["findings"][0]["review_status"] == "accepted"
    assert data["findings"][0]["review_comment"].startswith("Confirmed omission")
    assert [event["action"] for event in data["audit_events"]] == ["comparison_created", "review_updated", "review_updated"]
    assert client.get("/api/comparisons").json()[0]["session_id"] == session_id
    report = client.get(f"/api/comparisons/{session_id}/report")
    assert report.status_code == 200 and report.headers["content-type"] == "application/pdf"
    assert report.content.startswith(b"%PDF-")
    with pymupdf.open(stream=report.content, filetype="pdf") as document:
        text = "\n".join(page.get_text() for page in document)
    for expected in ("Document Comparison", "Executive summary", "R-04", "Confirmed omission", "qualified human reviewer", "Review and report history"):
        assert expected in text
    assert len(client.get(f"/api/comparisons/{session_id}").json()["audit_events"]) == 4


def test_cache_hit_force_refresh_and_no_double_count(monkeypatch, tmp_path):
    monkeypatch.setenv("GROQ_API_KEY", "test-only")
    fake = FakeGroq([ai_response(reference_item()), ai_response(reference_item())])
    monkeypatch.setattr(ai, "create_client", lambda: fake)
    reference, submitted = sample_documents()
    first = post(reference, submitted, mode="ai").json()
    second = post(reference, submitted, mode="ai").json()
    third = post(reference, submitted, mode="ai", force=True).json()
    assert len(fake.calls) == 2
    assert not first["cache_hit"] and first["usage"]["total_tokens"] == 110
    assert first["ai_duration_ms"] is not None
    assert second["cache_hit"] and second["usage"] is None and second["estimated_cost_usd"] is None
    assert second["ai_duration_ms"] is None
    assert second["ai_findings"][0]["id"] != first["ai_findings"][0]["id"]
    assert not third["cache_hit"] and third["usage"]["total_tokens"] == 110
    assert len({first["session_id"], second["session_id"], third["session_id"]}) == 3
    ai_id = first["ai_findings"][0]["id"]
    review = client.patch(f"/api/comparisons/{first['session_id']}/findings/{ai_id}/review",
                          json={"status": "rejected", "comment": "AI interpretation requires more evidence."})
    assert review.status_code == 200
    saved_ai = client.get(f"/api/comparisons/{first['session_id']}").json()["ai_findings"][0]
    assert saved_ai["review_status"] == "rejected" and saved_ai["severity"] == "medium"
    report = client.get(f"/api/comparisons/{first['session_id']}/report")
    with pymupdf.open(stream=report.content, filetype="pdf") as document:
        report_text = "\n".join(page.get_text() for page in document)
    assert "AI-assisted findings" in report_text
    assert "AI severity: medium" in report_text
    assert "Historical finding decision: Not an issue" in report_text
    assert "No corresponding submitted-document excerpt" in report_text
    assert "AI interpretation requires more evidence" in report_text
    db = sqlite3.connect(tmp_path / "qa.sqlite3")
    assert db.execute("SELECT COUNT(*) FROM ai_cache").fetchone()[0] == 1
    assert db.execute("SELECT SUM(total_tokens) FROM sessions").fetchone()[0] == 220
    db.close()


def test_cache_key_changes_with_each_relevant_input(monkeypatch):
    requirement = Requirement.model_validate(CHECKLIST[0])
    first = analysis_key(pdf_hash(b"reference"), pdf_hash(b"submitted"), [requirement], "openai/gpt-oss-20b")
    assert first != analysis_key(pdf_hash(b"other"), pdf_hash(b"submitted"), [requirement], "openai/gpt-oss-20b")
    assert first != analysis_key(pdf_hash(b"reference"), pdf_hash(b"other"), [requirement], "openai/gpt-oss-20b")
    changed = requirement.model_copy(update={"reference_text": "Inspection method: revised."})
    assert first != analysis_key(pdf_hash(b"reference"), pdf_hash(b"submitted"), [changed], "openai/gpt-oss-20b")
    assert first != analysis_key(pdf_hash(b"reference"), pdf_hash(b"submitted"), [requirement], "another-model")
    assert analysis_key(pdf_hash(b"reference"), pdf_hash(b"submitted"), [requirement],
                        "openai/gpt-oss-20b", "visitor-a") != analysis_key(
                            pdf_hash(b"reference"), pdf_hash(b"submitted"), [requirement],
                            "openai/gpt-oss-20b", "visitor-b")


def test_missing_clause_rejects_unrelated_submitted_header(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-only")
    bad = {**reference_item(), "source_document": "submitted", "supporting_excerpt": "Project: NS-042"}
    fake = FakeGroq([ai_response(bad)])
    monkeypatch.setattr(ai, "create_client", lambda: fake)
    reference, submitted = sample_documents()
    result = post(reference, submitted, mode="ai").json()
    assert result["findings"][0]["reference"]["excerpt"] == CHECKLIST[0]["reference_text"]
    assert result["findings"][0]["submitted"] is None
    assert result["ai_findings"] == [] and result["ai_status"] == "partial"
    prompt = json.loads(fake.calls[0]["messages"][1]["content"])
    assert prompt["items"][0]["no_corresponding_submitted_excerpt"] is True
    assert all(e["document"] == "reference" for e in prompt["items"][0]["evidence"])


def test_valid_missing_clause_cites_approved_reference_and_cache_not_created_on_invalid(monkeypatch, tmp_path):
    monkeypatch.setenv("GROQ_API_KEY", "test-only")
    bad = {**reference_item(), "source_document": "submitted", "supporting_excerpt": "Project: NS-042"}
    fake = FakeGroq([ai_response(bad), ai_response({**reference_item(), "uncertain": False})])
    monkeypatch.setattr(ai, "create_client", lambda: fake)
    reference, submitted = sample_documents()
    first = post(reference, submitted, mode="ai").json()
    second = post(reference, submitted, mode="ai").json()
    assert len(fake.calls) == 2 and first["ai_status"] == "partial" and not first["cache_hit"]
    assert second["ai_status"] == "completed" and not second["cache_hit"]
    finding = second["ai_findings"][0]
    assert finding["source_document"] == "reference" and finding["page_number"] == 1
    assert finding["supporting_excerpt"] == CHECKLIST[0]["reference_text"]
    assert finding["review_status"] == "pending" and finding["uncertain"]
    db = sqlite3.connect(tmp_path / "qa.sqlite3")
    assert db.execute("SELECT COUNT(*) FROM ai_cache").fetchone()[0] == 1
    db.close()
