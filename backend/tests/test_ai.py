import asyncio
import json
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient
from groq import RateLimitError
import pymupdf

from app import ai
from app.comparison import compare
from app.main import app
from app.models import Requirement, TokenUsage
from app.pdf import PageText


def scenario():
    reference = [PageText(2, "Design pressure: 150 kPa.\n" + "Private unrelated text. " * 500)]
    submitted = [PageText(3, "Design pressure: 120 kPa.\nOther unrelated text.")]
    requirements = [Requirement(id="R-01", title="Pressure", reference_text="Design pressure: 150 kPa.")]
    return reference, submitted, requirements, compare(reference, submitted, requirements)


def response(findings, prompt_tokens=50, completion_tokens=20):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"findings": findings})))],
                           usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens))


def ai_item(excerpt="Design pressure: 120 kPa.", uncertain=False):
    return {"requirement_id": "R-01", "discrepancy_type": "value_mismatch", "severity": "unknown" if uncertain else "medium",
            "explanation": "The submitted pressure differs from the approved value.", "source_document": "submitted",
            "page_number": 3, "supporting_excerpt": excerpt, "uncertain": uncertain}


class FakeClient:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self):
        pass


def test_verified_citation_uncertainty_usage_and_bounded_prompt(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-only-key")
    monkeypatch.setenv("GROQ_INPUT_USD_PER_MILLION_TOKENS", "1")
    monkeypatch.setenv("GROQ_OUTPUT_USD_PER_MILLION_TOKENS", "2")
    fake = FakeClient([response([ai_item(uncertain=True)])])
    monkeypatch.setattr(ai, "create_client", lambda: fake)
    reference, submitted, requirements, findings = scenario()
    result, status, message, usage, cost = asyncio.run(ai.analyze(findings, requirements, reference, submitted))
    assert status == "completed" and message is None
    assert len(result) == 1 and result[0].citation_verified
    assert result[0].uncertain and result[0].review_status == "pending"
    assert usage == TokenUsage(prompt_tokens=50, completion_tokens=20, total_tokens=70)
    assert cost == 0.00009
    prompt = fake.calls[0]["messages"][1]["content"]
    assert "Private unrelated text" not in prompt
    assert len(prompt) < ai.MAX_BATCH_CHARS
    assert fake.calls[0]["response_format"]["json_schema"]["strict"] is True


def test_unsupported_citation_is_rejected(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-only-key")
    monkeypatch.delenv("GROQ_INPUT_USD_PER_MILLION_TOKENS", raising=False)
    monkeypatch.delenv("GROQ_OUTPUT_USD_PER_MILLION_TOKENS", raising=False)
    fake = FakeClient([response([ai_item(excerpt="Invented pressure: 999 kPa.")])])
    monkeypatch.setattr(ai, "create_client", lambda: fake)
    reference, submitted, requirements, findings = scenario()
    result, status, message, usage, cost = asyncio.run(ai.analyze(findings, requirements, reference, submitted))
    assert result == [] and status == "partial"
    assert "rejected" in message
    assert usage and usage.total_tokens == 70
    assert cost is None


def test_wrong_page_and_invalid_severity_are_rejected(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-only-key")
    wrong_page = {**ai_item(), "page_number": 2}
    invalid_severity = {**ai_item(), "severity": "critical"}
    fake = FakeClient([response([wrong_page, invalid_severity])])
    monkeypatch.setattr(ai, "create_client", lambda: fake)
    reference, submitted, requirements, findings = scenario()
    result, status, message, *_ = asyncio.run(ai.analyze(findings, requirements, reference, submitted))
    assert result == [] and status == "partial" and "2 unsupported" in message


def test_rate_limit_retries_then_returns_result(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-only-key")
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    rate_limit = RateLimitError("rate limited", response=httpx.Response(429, request=request), body=None)
    fake = FakeClient([rate_limit, response([ai_item()])])
    monkeypatch.setattr(ai, "create_client", lambda: fake)

    async def no_wait(_):
        return None
    monkeypatch.setattr(ai.asyncio, "sleep", no_wait)
    reference, submitted, requirements, findings = scenario()
    result, status, *_ = asyncio.run(ai.analyze(findings, requirements, reference, submitted))
    assert len(fake.calls) == 2 and status == "completed" and len(result) == 1


def test_exhausted_rate_limit_returns_deterministic_fallback(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-only-key")
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    errors = [RateLimitError("rate limited", response=httpx.Response(429, request=request), body=None) for _ in range(3)]
    fake = FakeClient(errors)
    monkeypatch.setattr(ai, "create_client", lambda: fake)

    async def no_wait(_):
        return None
    monkeypatch.setattr(ai.asyncio, "sleep", no_wait)
    reference, submitted, requirements, findings = scenario()
    result, status, message, usage, cost = asyncio.run(ai.analyze(findings, requirements, reference, submitted))
    assert len(fake.calls) == ai.MAX_ATTEMPTS
    assert result == [] and status == "unavailable" and "Deterministic results" in message
    assert usage is None and cost is None


def test_matching_clauses_do_not_call_groq(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    reference = [PageText(1, "Design pressure: 150 kPa.")]
    requirements = [Requirement(id="R-01", title="Pressure", reference_text="Design pressure: 150 kPa.")]
    findings = compare(reference, reference, requirements)
    result, status, message, usage, cost = asyncio.run(ai.analyze(findings, requirements, reference, reference))
    assert result == [] and status == "completed" and message is None and usage is None and cost is None


def test_missing_key_keeps_deterministic_results(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    def pdf(text):
        document = pymupdf.open()
        document.new_page().insert_text((72, 72), text)
        data = document.tobytes()
        document.close()
        return data
    result = TestClient(app).post("/api/compare", files={
        "reference": ("a.pdf", pdf("Design pressure: 150 kPa."), "application/pdf"),
        "submitted": ("b.pdf", pdf("Design pressure: 120 kPa."), "application/pdf")},
        data={"checklist": json.dumps([{"id": "R-01", "title": "Pressure", "reference_text": "Design pressure: 150 kPa."}]), "mode": "ai"})
    assert result.status_code == 200
    body = result.json()
    assert body["findings"][0]["status"] == "different"
    assert body["ai_status"] == "unavailable"
    assert body["ai_findings"] == []


def test_ai_endpoint_returns_separate_verified_findings(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-only-key")
    fake = FakeClient([response([{**ai_item(), "page_number": 1}])])
    monkeypatch.setattr(ai, "create_client", lambda: fake)

    def pdf(text):
        document = pymupdf.open()
        document.new_page().insert_text((72, 72), text)
        data = document.tobytes()
        document.close()
        return data

    result = TestClient(app).post("/api/compare", files={
        "reference": ("a.pdf", pdf("Design pressure: 150 kPa."), "application/pdf"),
        "submitted": ("b.pdf", pdf("Design pressure: 120 kPa."), "application/pdf")},
        data={"checklist": json.dumps([{"id": "R-01", "title": "Pressure", "reference_text": "Design pressure: 150 kPa."}]), "mode": "ai"})
    assert result.status_code == 200
    body = result.json()
    assert body["findings"][0]["status"] == "different"
    assert body["ai_status"] == "completed"
    assert body["ai_findings"][0]["supporting_excerpt"] == "Design pressure: 120 kPa."
    assert body["ai_findings"][0]["review_status"] == "pending"
    assert body["usage"]["total_tokens"] == 70
