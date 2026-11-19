import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import TypeAdapter, ValidationError
import psycopg
from starlette.types import ASGIApp, Receive, Scope, Send

from .comparison import compare
from .ai import analyze, DEFAULT_MODEL
from .cache import analysis_key, pdf_hash
from .db import (change_correction_status, create_revision, get_cached_ai, get_comparison,
                 get_revision, list_comparisons, list_corrections, list_revisions, owns_session,
                 put_cached_ai, record_api_request, consume_daily_quota, cleanup_expired_data,
                 database, init_db, record_report, save_comparison, save_correction,
                 update_requirement_review, update_review)
from .models import (CompareResponse, CorrectionInput, CorrectionRecord, CorrectionStatusUpdate,
                     Requirement, RequirementReview, ReviewResponse, ReviewUpdate, RevisionRecord)
from .pdf import MAX_PDF_BYTES, extract_pdf
from .report import build_report
from .revision import build_revision
from .security import (COOKIE_MAX_AGE, COOKIE_NAME, hash_client_ip, new_visitor_id,
                       sign_visitor_id, validate_production_settings, verify_visitor_cookie)

logger = logging.getLogger(__name__)


def _positive_int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value < 1:
        raise RuntimeError(f"{name} must be a positive integer")
    return value


async def _retention_worker(retention_days: int) -> None:
    while True:
        await asyncio.sleep(24 * 60 * 60)
        try:
            await asyncio.to_thread(cleanup_expired_data, retention_days)
        except psycopg.Error:
            logger.error("Scheduled privacy-retention cleanup failed")
            raise


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_production_settings()
    retention_days = _positive_int("DOCWISE_RETENTION_DAYS", 30)
    init_db()
    cleanup_expired_data(retention_days)
    cleanup_task = asyncio.create_task(_retention_worker(retention_days))
    try:
        yield
    finally:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Document QA Engine", version="0.4.0", lifespan=lifespan)
cors_origins = [origin.strip() for origin in os.getenv(
    "DOCWISE_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if origin.strip()]
trusted_origins = set(cors_origins)


class RequestBodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api/") or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length:
            try:
                declared_size = int(content_length)
            except ValueError:
                declared_size = self.max_bytes + 1
            if declared_size > self.max_bytes:
                await self._reject(send)
                return

        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > self.max_bytes:
                await self._reject(send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break

        body = b"".join(chunks)
        replayed = False

        async def replay_receive():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay_receive, send)

    async def _reject(self, send: Send) -> None:
        body = b'{"detail":"Request body exceeds the configured size limit."}'
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


app.add_middleware(RequestBodyLimitMiddleware, max_bytes=_positive_int("DOCWISE_MAX_REQUEST_BYTES", 22 * 1024 * 1024))


def _set_visitor_cookie(response: Response, visitor_id: str) -> None:
    production = os.getenv("DOCWISE_ENV", "development").lower() == "production"
    response.set_cookie(COOKIE_NAME, sign_visitor_id(visitor_id), max_age=COOKIE_MAX_AGE,
                        httponly=True, secure=production or os.getenv("DOCWISE_COOKIE_SECURE", "").lower() == "true",
                        samesite="none" if production else "lax", path="/")


@app.middleware("http")
async def visitor_and_rate_limit(request: Request, call_next):
    visitor_id = verify_visitor_cookie(request.cookies.get(COOKIE_NAME))
    if visitor_id is None:
        visitor_id = new_visitor_id()
    request.state.visitor_id = visitor_id

    if request.url.path.startswith("/api/") and request.url.path != "/api/health":
        origin = request.headers.get("origin")
        if request.method in ("POST", "PUT", "PATCH") and origin and origin not in trusted_origins:
            response = JSONResponse({"detail": "Request origin is not allowed."}, status_code=403)
            _set_visitor_cookie(response, visitor_id)
            return response
        client_address = request.client.host if request.client else "unknown"
        allowed = record_api_request(
            visitor_id, hash_client_ip(client_address),
            _positive_int("DOCWISE_RATE_LIMIT_PER_MINUTE", 120),
            _positive_int("DOCWISE_IP_RATE_LIMIT_PER_MINUTE", 300))
        if not allowed:
            response = JSONResponse({"detail": "Request rate limit exceeded. Please try again shortly."},
                                    status_code=429, headers={"Retry-After": "60"})
            _set_visitor_cookie(response, visitor_id)
            return response

    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        _set_visitor_cookie(response, visitor_id)
    return response


def get_visitor_id(request: Request) -> str:
    return request.state.visitor_id


def require_session_owner(session_id: str, visitor_id: str) -> None:
    if not owns_session(session_id, visitor_id):
        raise HTTPException(404, "Comparison not found")


def enforce_quota(visitor_id: str, request: Request, action: str,
                  visitor_limit: int, ip_limit: int) -> None:
    client_address = request.client.host if request.client else "unknown"
    if not consume_daily_quota(visitor_id, hash_client_ip(client_address), action, visitor_limit, ip_limit):
        raise HTTPException(429, f"Daily {action.replace('_', ' ')} quota exceeded.",
                            headers={"Retry-After": "86400"})


app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_credentials=True,
                   allow_methods=["GET", "POST", "PATCH", "PUT", "OPTIONS"], allow_headers=["*"])


@app.get("/api/health")
def health() -> dict[str, str]:
    try:
        with database() as connection:
            connection.execute("SELECT 1").fetchone()
    except (psycopg.Error, RuntimeError) as exc:
        logger.error("Health check could not reach PostgreSQL")
        raise HTTPException(503, "Database is unavailable") from exc
    return {"status": "ok", "database": "ok"}


@app.post("/api/compare", response_model=CompareResponse)
async def compare_documents(request: Request, visitor_id: str = Depends(get_visitor_id),
                            reference: UploadFile = File(...), submitted: UploadFile = File(...), checklist: str = Form(...),
                            mode: Literal["deterministic", "ai"] = Form("deterministic"),
                            force_refresh: bool = Form(False)) -> CompareResponse:
    started = time.perf_counter()
    try:
        requirements = TypeAdapter(list[Requirement]).validate_python(json.loads(checklist))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(422, "Checklist must be a valid list of requirements") from exc
    if not 1 <= len(requirements) <= 50:
        raise HTTPException(422, "Checklist must contain 1 to 50 requirements")
    if len({item.id for item in requirements}) != len(requirements):
        raise HTTPException(422, "Requirement IDs must be unique")
    enforce_quota(visitor_id, request, "comparison", _positive_int("DOCWISE_DAILY_COMPARISONS_PER_VISITOR", 10),
                  _positive_int("DOCWISE_DAILY_COMPARISONS_PER_IP", 30))
    reference_hash = pdf_hash(await reference.read(MAX_PDF_BYTES + 1))
    submitted_hash = pdf_hash(await submitted.read(MAX_PDF_BYTES + 1))
    await reference.seek(0)
    await submitted.seek(0)
    reference_pages = await extract_pdf(reference)
    submitted_pages = await extract_pdf(submitted)
    findings = compare(reference_pages, submitted_pages, requirements)
    result = CompareResponse(reference_name=reference.filename or "reference.pdf", submitted_name=submitted.filename or "submitted.pdf",
        reference_pages=len(reference_pages), submitted_pages=len(submitted_pages),
        findings=findings, mode=mode)
    if mode == "ai":
        result.ai_model = os.getenv("GROQ_MODEL", DEFAULT_MODEL)
        key = analysis_key(reference_hash, submitted_hash, requirements, result.ai_model, visitor_id)
        cached = None if force_refresh else get_cached_ai(key)
        if cached is not None:
            result.ai_findings = cached
            result.ai_status = "completed"
            result.ai_message = "Reused validated AI analysis from cache."
            result.cache_hit = True
        else:
            if (os.getenv("GROQ_API_KEY") and any(item.status in ("different", "missing") for item in findings)):
                enforce_quota(visitor_id, request, "groq_analysis",
                              _positive_int("DOCWISE_DAILY_GROQ_PER_VISITOR", 3),
                              _positive_int("DOCWISE_DAILY_GROQ_PER_IP", 10))
            ai_started = time.perf_counter()
            result.ai_findings, result.ai_status, result.ai_message, result.usage, result.estimated_cost_usd = await analyze(
                findings, requirements, reference_pages, submitted_pages)
            result.ai_duration_ms = int((time.perf_counter() - ai_started) * 1000)
            if result.ai_status == "completed":
                put_cached_ai(key, result.ai_model, result.ai_findings)
    result.duration_ms = int((time.perf_counter() - started) * 1000)
    return save_comparison(result, requirements, {"reference": reference_hash, "submitted": submitted_hash}, visitor_id)


@app.get("/api/comparisons")
def previous_comparisons(visitor_id: str = Depends(get_visitor_id), limit: int = 20) -> list[dict]:
    if not 1 <= limit <= 100:
        raise HTTPException(422, "Limit must be between 1 and 100")
    return list_comparisons(visitor_id, limit)


@app.get("/api/comparisons/{session_id}", response_model=CompareResponse)
def previous_comparison(session_id: str, visitor_id: str = Depends(get_visitor_id)) -> CompareResponse:
    require_session_owner(session_id, visitor_id)
    result = get_comparison(session_id)
    if result is None:
        raise HTTPException(404, "Comparison not found")
    return result


@app.patch("/api/comparisons/{session_id}/findings/{finding_id}/review", response_model=ReviewResponse)
def review_finding(session_id: str, finding_id: str, update: ReviewUpdate,
                   visitor_id: str = Depends(get_visitor_id)) -> ReviewResponse:
    require_session_owner(session_id, visitor_id)
    result = update_review(session_id, finding_id, update)
    if result is None:
        raise HTTPException(404, "Finding not found")
    return result


@app.patch("/api/comparisons/{session_id}/requirements/{requirement_id}/review", response_model=RequirementReview)
def review_requirement(session_id: str, requirement_id: str, update: ReviewUpdate,
                       visitor_id: str = Depends(get_visitor_id)) -> RequirementReview:
    require_session_owner(session_id, visitor_id)
    try:
        result = update_requirement_review(session_id, requirement_id, update)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Requirement not found")
    return result


@app.get("/api/comparisons/{session_id}/report")
def download_report(session_id: str, visitor_id: str = Depends(get_visitor_id)) -> Response:
    require_session_owner(session_id, visitor_id)
    result = get_comparison(session_id)
    if result is None:
        raise HTTPException(404, "Comparison not found")
    from uuid import uuid4
    report_id = f"QA-{uuid4().hex[:12].upper()}"
    record_report(session_id, report_id)
    result.audit_events = get_comparison(session_id).audit_events
    content = build_report(result, report_id, list_corrections(session_id))
    return Response(content, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{report_id}.pdf"'})


@app.get("/api/comparisons/{session_id}/corrections", response_model=list[CorrectionRecord])
def corrections(session_id: str, visitor_id: str = Depends(get_visitor_id),
                include_history: bool = False) -> list[CorrectionRecord]:
    require_session_owner(session_id, visitor_id)
    if get_comparison(session_id) is None:
        raise HTTPException(404, "Comparison not found")
    return list_corrections(session_id, include_history=include_history)


@app.post("/api/comparisons/{session_id}/corrections", response_model=CorrectionRecord)
def add_correction(session_id: str, data: CorrectionInput, visitor_id: str = Depends(get_visitor_id)) -> CorrectionRecord:
    require_session_owner(session_id, visitor_id)
    try:
        return save_correction(session_id, data)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.put("/api/comparisons/{session_id}/corrections/{correction_id}", response_model=CorrectionRecord)
def edit_correction(session_id: str, correction_id: str, data: CorrectionInput,
                    visitor_id: str = Depends(get_visitor_id)) -> CorrectionRecord:
    require_session_owner(session_id, visitor_id)
    try:
        return save_correction(session_id, data, previous_id=correction_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.patch("/api/comparisons/{session_id}/corrections/{correction_id}/status", response_model=CorrectionRecord)
def correction_status(session_id: str, correction_id: str, update: CorrectionStatusUpdate,
                      visitor_id: str = Depends(get_visitor_id)) -> CorrectionRecord:
    require_session_owner(session_id, visitor_id)
    try:
        return change_correction_status(session_id, correction_id, update)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/comparisons/{session_id}/revisions", response_model=list[RevisionRecord])
def revisions(session_id: str, visitor_id: str = Depends(get_visitor_id)) -> list[RevisionRecord]:
    require_session_owner(session_id, visitor_id)
    if get_comparison(session_id) is None:
        raise HTTPException(404, "Comparison not found")
    return list_revisions(session_id)


@app.post("/api/comparisons/{session_id}/revisions", response_model=RevisionRecord)
def generate_revision(session_id: str, visitor_id: str = Depends(get_visitor_id)) -> RevisionRecord:
    require_session_owner(session_id, visitor_id)
    try:
        return create_revision(session_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/comparisons/{session_id}/revisions/{revision_id}/pdf")
def download_revision(session_id: str, revision_id: str,
                      visitor_id: str = Depends(get_visitor_id)) -> Response:
    require_session_owner(session_id, visitor_id)
    stored = get_revision(revision_id)
    result = get_comparison(session_id)
    if stored is None or result is None or stored[0].session_id != session_id:
        raise HTTPException(404, "Revision not found")
    content = build_revision(result, stored[0], stored[1], list_revisions(session_id))
    return Response(content, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{revision_id}.pdf"'})
