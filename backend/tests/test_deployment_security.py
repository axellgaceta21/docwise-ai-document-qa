import asyncio
import io
import json

import pymupdf
from fastapi.testclient import TestClient

from app.db import cleanup_expired_data, database
from app.main import RequestBodyLimitMiddleware, app


def pdf(text: str) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    content = document.tobytes()
    document.close()
    return content


def compare(client: TestClient, mode: str = "deterministic", force_refresh: bool = False):
    return client.post("/api/compare", files={
        "reference": ("reference.pdf", io.BytesIO(pdf("Design pressure: 150 kPa.")), "application/pdf"),
        "submitted": ("submitted.pdf", io.BytesIO(pdf("Design pressure: 120 kPa.")), "application/pdf"),
    }, data={
        "checklist": json.dumps([{
            "id": "R-01", "title": "Pressure", "reference_text": "Design pressure: 150 kPa.",
        }]),
        "mode": mode,
        "force_refresh": str(force_refresh).lower(),
    })


def test_visitor_cookie_is_signed_http_only_and_owner_scoped():
    owner = TestClient(app)
    stranger = TestClient(app)
    response = compare(owner)
    result = response.json()
    session_id = result["session_id"]
    finding_id = result["findings"][0]["id"]

    cookie = owner.cookies.get("docwise_visitor")
    assert cookie and len(cookie.split(".")) == 3
    assert "httponly" in response.headers["set-cookie"].lower()
    assert owner.get("/api/comparisons").json()[0]["session_id"] == session_id
    assert stranger.get("/api/comparisons").json() == []

    protected_requests = [
        ("get", f"/api/comparisons/{session_id}", None),
        ("patch", f"/api/comparisons/{session_id}/findings/{finding_id}/review",
         {"json": {"status": "accepted", "comment": ""}}),
        ("patch", f"/api/comparisons/{session_id}/requirements/R-01/review",
         {"json": {"status": "accepted", "comment": ""}}),
        ("get", f"/api/comparisons/{session_id}/report", None),
        ("get", f"/api/comparisons/{session_id}/corrections", None),
        ("post", f"/api/comparisons/{session_id}/corrections",
         {"json": {"finding_id": finding_id, "field_name": "Pressure", "corrected_value": "150 kPa",
                   "reason": "Correction", "supporting_notes": ""}}),
        ("put", f"/api/comparisons/{session_id}/corrections/CORR-unknown",
         {"json": {"finding_id": finding_id, "field_name": "Pressure", "corrected_value": "150 kPa",
                   "reason": "Correction", "supporting_notes": ""}}),
        ("patch", f"/api/comparisons/{session_id}/corrections/CORR-unknown/status",
         {"json": {"status": "verified", "note": ""}}),
        ("get", f"/api/comparisons/{session_id}/revisions", None),
        ("post", f"/api/comparisons/{session_id}/revisions", None),
        ("get", f"/api/comparisons/{session_id}/revisions/REV-unknown/pdf", None),
    ]
    for method, path, kwargs in protected_requests:
        response = getattr(stranger, method)(path, **(kwargs or {}))
        assert response.status_code == 404, (method, path, response.text)
    stranger.cookies.set("docwise_visitor", cookie + "tampered")
    assert stranger.get(f"/api/comparisons/{session_id}").status_code == 404


def test_legacy_unowned_comparison_is_not_visible():
    client = TestClient(app)
    result = compare(client).json()
    with database() as connection:
        connection.execute("UPDATE sessions SET owner_id=NULL WHERE id=%s", (result["session_id"],))
    assert client.get(f"/api/comparisons/{result['session_id']}").status_code == 404
    assert all(item["session_id"] != result["session_id"] for item in client.get("/api/comparisons").json())


def test_retention_cleanup_removes_expired_sessions_and_related_records():
    client = TestClient(app)
    result = compare(client).json()
    session_id = result["session_id"]
    with database() as connection:
        connection.execute("UPDATE sessions SET created_at='2000-01-01T00:00:00+00:00' WHERE id=%s",
                           (session_id,))
    cleaned = cleanup_expired_data(30)
    assert cleaned["sessions"] == 1
    with database() as connection:
        assert connection.execute("SELECT COUNT(*) AS count FROM documents WHERE session_id=%s", (session_id,)).fetchone()["count"] == 0


def test_owner_can_download_report_and_revision_but_other_visitor_cannot():
    owner = TestClient(app)
    stranger = TestClient(app)
    result = compare(owner).json()
    session_id = result["session_id"]
    finding_id = result["findings"][0]["id"]
    assert owner.patch(f"/api/comparisons/{session_id}/requirements/R-01/review",
                       json={"status": "accepted", "comment": "Confirmed"}).status_code == 200
    correction = owner.post(f"/api/comparisons/{session_id}/corrections", json={
        "finding_id": finding_id, "field_name": "Design pressure", "corrected_value": "150 kPa",
        "reason": "Use the approved value", "supporting_notes": "",
    })
    assert correction.status_code == 200
    revision = owner.post(f"/api/comparisons/{session_id}/revisions")
    assert revision.status_code == 200

    assert owner.get(f"/api/comparisons/{session_id}/report").status_code == 200
    revision_url = f"/api/comparisons/{session_id}/revisions/{revision.json()['id']}/pdf"
    assert owner.get(revision_url).status_code == 200
    assert stranger.get(f"/api/comparisons/{session_id}/report").status_code == 404
    assert stranger.get(revision_url).status_code == 404


def test_daily_comparison_quota_is_per_visitor(monkeypatch):
    monkeypatch.setenv("DOCWISE_DAILY_COMPARISONS_PER_VISITOR", "1")
    client = TestClient(app)
    assert compare(client).status_code == 200
    assert compare(client).status_code == 429


def test_daily_comparison_ip_quota_cannot_be_bypassed_with_new_cookie(monkeypatch):
    monkeypatch.setenv("DOCWISE_DAILY_COMPARISONS_PER_VISITOR", "10")
    monkeypatch.setenv("DOCWISE_DAILY_COMPARISONS_PER_IP", "1")
    assert compare(TestClient(app)).status_code == 200
    assert compare(TestClient(app)).status_code == 429


def test_per_visitor_request_rate_limit_is_enforced(monkeypatch):
    monkeypatch.setenv("DOCWISE_RATE_LIMIT_PER_MINUTE", "1")
    client = TestClient(app)
    assert client.get("/api/comparisons").status_code == 200
    response = client.get("/api/comparisons")
    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"


def test_force_refresh_uses_groq_quota_without_live_api(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-used")
    monkeypatch.setenv("DOCWISE_DAILY_GROQ_PER_VISITOR", "1")
    calls = 0

    async def fake_analyze(*_args):
        nonlocal calls
        calls += 1
        return [], "completed", None, None, None

    monkeypatch.setattr("app.main.analyze", fake_analyze)
    client = TestClient(app)
    first = compare(client, mode="ai")
    assert first.status_code == 200
    assert calls == 1
    second = compare(client, mode="ai", force_refresh=True)
    assert second.status_code == 429
    assert calls == 1


def test_production_requires_secret_and_sets_secure_cross_origin_cookie(monkeypatch):
    monkeypatch.setenv("DOCWISE_ENV", "production")
    monkeypatch.setenv("DOCWISE_SESSION_SECRET", "s" * 48)
    monkeypatch.setenv("DOCWISE_CORS_ORIGINS", "https://docwise.vercel.app")
    with TestClient(app) as client:
        response = client.get("/api/health")
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=none" in cookie


def test_untrusted_browser_origin_is_rejected():
    client = TestClient(app)
    response = client.post("/api/compare", headers={"Origin": "https://attacker.example"}, files={
        "reference": ("reference.pdf", io.BytesIO(pdf("Design pressure: 150 kPa.")), "application/pdf"),
        "submitted": ("submitted.pdf", io.BytesIO(pdf("Design pressure: 120 kPa.")), "application/pdf"),
    }, data={"checklist": json.dumps([{
        "id": "R-01", "title": "Pressure", "reference_text": "Design pressure: 150 kPa.",
    }])})
    assert response.status_code == 403


def test_request_body_middleware_rejects_oversized_stream():
    async def run():
        sent = []
        messages = [{"type": "http.request", "body": b"12345", "more_body": False}]

        async def receive():
            return messages.pop(0)

        async def send(message):
            sent.append(message)

        async def downstream(_scope, _receive, _send):
            raise AssertionError("Oversized body reached the application")

        middleware = RequestBodyLimitMiddleware(downstream, max_bytes=4)
        await middleware({"type": "http", "path": "/api/compare", "method": "POST", "headers": []},
                         receive, send)
        assert sent[0]["status"] == 413

    asyncio.run(run())
