"""PostgreSQL persistence for comparison snapshots and human review history."""
import json
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from uuid import uuid4

import psycopg
from dotenv import load_dotenv
from psycopg import sql
from psycopg.rows import dict_row

from .models import (AIFinding, CompareResponse, CorrectionInput, CorrectionRecord,
                     CorrectionStatusUpdate, Finding, Requirement, RequirementReview, ReviewResponse,
                     ReviewUpdate, RevisionRecord)

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
_init_lock = Lock()
_initialized_urls: set[str] = set()
DOCWISE_TABLES = (
    "sessions", "documents", "requirements", "findings", "audit_events",
    "ai_cache", "corrections", "revisions", "requirement_reviews", "api_usage",
)
DOCWISE_SEQUENCES = ("audit_events_sequence_seq", "corrections_sequence_seq")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def database_url() -> str:
    url = os.getenv("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL is required")
    if not url.startswith(("postgresql://", "postgres://")):
        raise RuntimeError("DATABASE_URL must be a PostgreSQL connection URL")
    return url


@contextmanager
def database():
    # Short-lived connections work with Supabase's transaction/session poolers.
    with psycopg.connect(database_url(), connect_timeout=10, row_factory=dict_row) as connection:
        yield connection


def _secure_schema(connection) -> None:
    """Keep Docwise tables private to the direct PostgreSQL backend role."""
    for name in DOCWISE_TABLES:
        table = sql.Identifier("public", name)
        connection.execute(sql.SQL("ALTER TABLE {} ENABLE ROW LEVEL SECURITY").format(table))
        connection.execute(sql.SQL("REVOKE ALL PRIVILEGES ON TABLE {} FROM anon, authenticated").format(table))
    for name in DOCWISE_SEQUENCES:
        connection.execute(sql.SQL("REVOKE ALL PRIVILEGES ON SEQUENCE {} FROM anon, authenticated").format(
            sql.Identifier("public", name)))
    connection.execute("""ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
        REVOKE ALL ON TABLES FROM anon, authenticated""")
    connection.execute("""ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
        REVOKE ALL ON SEQUENCES FROM anon, authenticated""")


def _create_schema() -> None:
    with database() as connection:
        connection.execute("SELECT pg_advisory_xact_lock(hashtextextended('docwise:schema:v1', 0))")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, mode TEXT NOT NULL CHECK(mode IN ('deterministic','ai')),
                owner_id TEXT,
                reference_name TEXT NOT NULL, submitted_name TEXT NOT NULL,
                reference_pages INTEGER NOT NULL, submitted_pages INTEGER NOT NULL,
                ai_status TEXT NOT NULL, ai_message TEXT, ai_model TEXT, cache_hit INTEGER NOT NULL,
                prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER,
                estimated_cost_usd REAL, duration_ms INTEGER NOT NULL, ai_duration_ms INTEGER
            );
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK(role IN ('reference','submitted')),
                filename TEXT NOT NULL, sha256 TEXT NOT NULL, page_count INTEGER NOT NULL,
                UNIQUE(session_id, role)
            );
            CREATE TABLE IF NOT EXISTS requirements (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                requirement_id TEXT NOT NULL, title TEXT NOT NULL, reference_text TEXT NOT NULL,
                position INTEGER NOT NULL, UNIQUE(session_id, requirement_id)
            );
            CREATE TABLE IF NOT EXISTS findings (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                requirement_id TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('deterministic','ai')),
                payload_json TEXT NOT NULL, review_status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(review_status IN ('pending','accepted','rejected','needs_investigation')),
                review_comment TEXT NOT NULL DEFAULT '', position INTEGER NOT NULL,
                FOREIGN KEY(session_id, requirement_id) REFERENCES requirements(session_id, requirement_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_findings_session ON findings(session_id, kind, position);
            CREATE TABLE IF NOT EXISTS audit_events (
                id TEXT PRIMARY KEY, sequence BIGINT GENERATED ALWAYS AS IDENTITY,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                finding_id TEXT REFERENCES findings(id) ON DELETE CASCADE, action TEXT NOT NULL,
                old_status TEXT, new_status TEXT, comment TEXT, detail TEXT,
                occurred_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_audit_session ON audit_events(session_id, occurred_at);
            CREATE TABLE IF NOT EXISTS ai_cache (
                cache_key TEXT PRIMARY KEY, model TEXT NOT NULL, results_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS corrections (
                id TEXT PRIMARY KEY, sequence BIGINT GENERATED ALWAYS AS IDENTITY,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                finding_id TEXT NOT NULL REFERENCES findings(id) ON DELETE CASCADE, requirement_id TEXT NOT NULL,
                field_name TEXT NOT NULL, original_value TEXT NOT NULL,
                corrected_value TEXT NOT NULL, reason TEXT NOT NULL, supporting_notes TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('draft','pending_verification','verified','rejected')),
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, verified_at TEXT,
                verification_note TEXT NOT NULL DEFAULT '', superseded_at TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_correction_current
                ON corrections(session_id, requirement_id) WHERE superseded_at IS NULL;
            CREATE TABLE IF NOT EXISTS revisions (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                number INTEGER NOT NULL, status TEXT NOT NULL CHECK(status IN ('draft','verified')),
                created_at TEXT NOT NULL, snapshot_json TEXT NOT NULL,
                UNIQUE(session_id, number)
            );
            CREATE TABLE IF NOT EXISTS requirement_reviews (
                session_id TEXT NOT NULL, requirement_id TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending','accepted','rejected','needs_investigation')),
                comment TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
                PRIMARY KEY(session_id, requirement_id),
                FOREIGN KEY(session_id, requirement_id) REFERENCES requirements(session_id, requirement_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS api_usage (
                id TEXT PRIMARY KEY, visitor_id TEXT NOT NULL, ip_hash TEXT NOT NULL,
                action TEXT NOT NULL, occurred_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_api_usage_visitor ON api_usage(visitor_id, action, occurred_at);
            CREATE INDEX IF NOT EXISTS idx_api_usage_ip ON api_usage(ip_hash, action, occurred_at);
        """)
        connection.execute("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS owner_id TEXT")
        connection.execute("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS ai_duration_ms INTEGER")
        connection.execute("ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS sequence BIGINT GENERATED ALWAYS AS IDENTITY")
        connection.execute("ALTER TABLE corrections ADD COLUMN IF NOT EXISTS sequence BIGINT GENERATED ALWAYS AS IDENTITY")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_sessions_owner_created ON sessions(owner_id, created_at DESC)")
        _secure_schema(connection)


def init_db() -> None:
    url = database_url()
    if url in _initialized_urls:
        return
    with _init_lock:
        if url not in _initialized_urls:
            _create_schema()
            _initialized_urls.add(url)


def _event(connection, session_id: str, action: str, *, finding_id: str | None = None,
           old_status: str | None = None, new_status: str | None = None,
           comment: str | None = None, detail: str | None = None) -> None:
    connection.execute("""INSERT INTO audit_events
        (id, session_id, finding_id, action, old_status, new_status, comment, detail, occurred_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (str(uuid4()), session_id, finding_id, action, old_status, new_status, comment, detail, utc_now()))


def _requirement_review(connection, session_id: str, requirement_id: str) -> RequirementReview:
    explicit = connection.execute("""SELECT status, comment FROM requirement_reviews
        WHERE session_id=%s AND requirement_id=%s""", (session_id, requirement_id)).fetchone()
    if explicit:
        return RequirementReview(requirement_id=requirement_id, status=explicit["status"],
                                 comment=explicit["comment"], source="explicit")
    legacy = connection.execute("""SELECT review_status, review_comment FROM findings
        WHERE session_id=%s AND requirement_id=%s ORDER BY kind DESC, position, id""", (session_id, requirement_id)).fetchall()
    decided = [row for row in legacy if row["review_status"] != "pending"]
    distinct = {row["review_status"] for row in decided}
    if len(distinct) > 1:
        return RequirementReview(requirement_id=requirement_id, ambiguous_legacy=True, source="legacy")
    if len(distinct) == 1:
        return RequirementReview(requirement_id=requirement_id, status=decided[-1]["review_status"],
                                 comment=decided[-1]["review_comment"], source="legacy")
    return RequirementReview(requirement_id=requirement_id)


def get_requirement_reviews(session_id: str) -> list[RequirementReview]:
    init_db()
    with database() as connection:
        ids = [row["requirement_id"] for row in connection.execute("""SELECT requirement_id FROM requirements
            WHERE session_id=%s ORDER BY position""", (session_id,))]
        return [_requirement_review(connection, session_id, requirement_id) for requirement_id in ids]


def update_requirement_review(session_id: str, requirement_id: str, update: ReviewUpdate) -> RequirementReview | None:
    init_db()
    with database() as connection:
        connection.execute("SELECT id FROM sessions WHERE id=%s FOR UPDATE", (session_id,))
        requirement = connection.execute("""SELECT 1 FROM requirements
            WHERE session_id=%s AND requirement_id=%s FOR UPDATE""", (session_id, requirement_id)).fetchone()
        if requirement is None:
            return None
        before = _requirement_review(connection, session_id, requirement_id)
        finding = connection.execute("""SELECT payload_json FROM findings
            WHERE session_id=%s AND requirement_id=%s AND kind='deterministic'""", (session_id, requirement_id)).fetchone()
        ai_count = connection.execute("""SELECT COUNT(*) AS count FROM findings
            WHERE session_id=%s AND requirement_id=%s AND kind='ai'""", (session_id, requirement_id)).fetchone()["count"]
        clean = finding and json.loads(finding["payload_json"])["status"] == "match" and not ai_count
        if clean and not before.ambiguous_legacy:
            raise ValueError("A clean match does not need a review decision")
        comment = update.comment.strip()
        connection.execute("""INSERT INTO requirement_reviews
            (session_id, requirement_id, status, comment, updated_at) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT(session_id, requirement_id) DO UPDATE SET
            status=excluded.status, comment=excluded.comment, updated_at=excluded.updated_at""",
            (session_id, requirement_id, update.status, comment, utc_now()))
        _event(connection, session_id, "requirement_review_updated",
               old_status=before.status if not before.ambiguous_legacy else None,
               new_status=update.status, comment=comment, detail=requirement_id)
    return RequirementReview(requirement_id=requirement_id, status=update.status,
                             comment=comment, source="explicit")


def save_comparison(result: CompareResponse, requirements: list[Requirement], hashes: dict[str, str],
                    owner_id: str) -> CompareResponse:
    init_db()
    result.session_id = str(uuid4())
    result.created_at = utc_now()
    result.requirements = requirements
    with database() as connection:
        usage = result.usage
        connection.execute("""INSERT INTO sessions
            (id, created_at, mode, owner_id, reference_name, submitted_name, reference_pages, submitted_pages,
             ai_status, ai_message, ai_model, cache_hit, prompt_tokens, completion_tokens, total_tokens,
             estimated_cost_usd, duration_ms, ai_duration_ms)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (result.session_id, result.created_at, result.mode, owner_id, result.reference_name, result.submitted_name,
             result.reference_pages, result.submitted_pages, result.ai_status, result.ai_message, result.ai_model,
             int(result.cache_hit), usage.prompt_tokens if usage else None, usage.completion_tokens if usage else None,
             usage.total_tokens if usage else None, result.estimated_cost_usd, result.duration_ms or 0, result.ai_duration_ms))
        for role, name, pages in (("reference", result.reference_name, result.reference_pages),
                                  ("submitted", result.submitted_name, result.submitted_pages)):
            connection.execute("""INSERT INTO documents
                (id, session_id, role, filename, sha256, page_count) VALUES (%s, %s, %s, %s, %s, %s)""",
                (str(uuid4()), result.session_id, role, name, hashes[role], pages))
        for position, item in enumerate(requirements):
            connection.execute("""INSERT INTO requirements
                (id, session_id, requirement_id, title, reference_text, position) VALUES (%s, %s, %s, %s, %s, %s)""",
                (str(uuid4()), result.session_id, item.id, item.title, item.reference_text, position))
        for kind, items in (("deterministic", result.findings), ("ai", result.ai_findings)):
            for position, item in enumerate(items):
                item.id = str(uuid4())
                connection.execute("""INSERT INTO findings
                    (id, session_id, requirement_id, kind, payload_json, review_status, review_comment, position)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (item.id, result.session_id, item.requirement_id, kind, item.model_dump_json(), "pending", "", position))
        _event(connection, result.session_id, "comparison_created", detail=f"mode={result.mode}; cache_hit={result.cache_hit}")
    result.audit_events = get_audit_events(result.session_id)
    result.requirement_reviews = get_requirement_reviews(result.session_id)
    return result


def get_audit_events(session_id: str) -> list[dict]:
    init_db()
    with database() as connection:
        rows = connection.execute("""SELECT id, finding_id, action, old_status, new_status, comment, detail, occurred_at
            FROM audit_events WHERE session_id=%s ORDER BY occurred_at, sequence""", (session_id,)).fetchall()
    return [dict(row) for row in rows]


def get_comparison(session_id: str) -> CompareResponse | None:
    init_db()
    with database() as connection:
        row = connection.execute("SELECT * FROM sessions WHERE id=%s", (session_id,)).fetchone()
        if row is None:
            return None
        requirements = [Requirement(id=item["requirement_id"], title=item["title"], reference_text=item["reference_text"])
                        for item in connection.execute("SELECT * FROM requirements WHERE session_id=%s ORDER BY position", (session_id,))]
        deterministic: list[Finding] = []
        ai: list[AIFinding] = []
        for item in connection.execute("SELECT * FROM findings WHERE session_id=%s ORDER BY kind DESC, position", (session_id,)):
            payload = json.loads(item["payload_json"])
            payload["review_status"] = item["review_status"]
            payload["review_comment"] = item["review_comment"]
            (deterministic if item["kind"] == "deterministic" else ai).append(
                Finding.model_validate(payload) if item["kind"] == "deterministic" else AIFinding.model_validate(payload))
    usage = None
    if row["total_tokens"] is not None:
        from .models import TokenUsage
        usage = TokenUsage(prompt_tokens=row["prompt_tokens"], completion_tokens=row["completion_tokens"], total_tokens=row["total_tokens"])
    return CompareResponse(session_id=row["id"], created_at=row["created_at"], mode=row["mode"],
        reference_name=row["reference_name"], submitted_name=row["submitted_name"],
        reference_pages=row["reference_pages"], submitted_pages=row["submitted_pages"],
        findings=deterministic, ai_findings=ai, requirements=requirements,
        ai_status=row["ai_status"], ai_message=row["ai_message"], ai_model=row["ai_model"],
        cache_hit=bool(row["cache_hit"]), usage=usage, estimated_cost_usd=row["estimated_cost_usd"],
        duration_ms=row["duration_ms"], ai_duration_ms=row["ai_duration_ms"],
        audit_events=get_audit_events(session_id), requirement_reviews=get_requirement_reviews(session_id))


def owns_session(session_id: str, owner_id: str) -> bool:
    init_db()
    with database() as connection:
        row = connection.execute("SELECT 1 FROM sessions WHERE id=%s AND owner_id=%s",
                                 (session_id, owner_id)).fetchone()
    return row is not None


def list_comparisons(owner_id: str, limit: int = 20) -> list[dict]:
    init_db()
    with database() as connection:
        rows = connection.execute("""SELECT id AS session_id, created_at, mode, reference_name, submitted_name,
            ai_status, cache_hit FROM sessions WHERE owner_id=%s
            ORDER BY created_at DESC, id DESC LIMIT %s""", (owner_id, limit)).fetchall()
    return [dict(row) for row in rows]


def _record_limited_usage(visitor_id: str, ip_hash: str, action: str, visitor_limit: int,
                          ip_limit: int, window_seconds: int) -> bool:
    init_db()
    now = datetime.now(timezone.utc)
    occurred_at = now.isoformat(timespec="seconds")
    cutoff = (now - timedelta(seconds=window_seconds)).isoformat(timespec="seconds")
    with database() as connection:
        # Serialize overlapping visitor and IP windows across Render workers.
        for key in sorted((f"visitor:{visitor_id}:{action}", f"ip:{ip_hash}:{action}")):
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (key,))
        visitor_count = connection.execute("""SELECT COUNT(*) AS count FROM api_usage
            WHERE visitor_id=%s AND action=%s AND occurred_at>=%s""",
            (visitor_id, action, cutoff)).fetchone()["count"]
        ip_count = connection.execute("""SELECT COUNT(*) AS count FROM api_usage
            WHERE ip_hash=%s AND action=%s AND occurred_at>=%s""",
            (ip_hash, action, cutoff)).fetchone()["count"]
        if visitor_count >= visitor_limit or ip_count >= ip_limit:
            return False
        connection.execute("""INSERT INTO api_usage (id, visitor_id, ip_hash, action, occurred_at)
            VALUES (%s, %s, %s, %s, %s)""", (str(uuid4()), visitor_id, ip_hash, action, occurred_at))
    return True


def record_api_request(visitor_id: str, ip_hash: str, visitor_limit: int, ip_limit: int) -> bool:
    return _record_limited_usage(visitor_id, ip_hash, "request", visitor_limit, ip_limit, 60)


def consume_daily_quota(visitor_id: str, ip_hash: str, action: str,
                        visitor_limit: int, ip_limit: int) -> bool:
    return _record_limited_usage(visitor_id, ip_hash, action, visitor_limit, ip_limit, 24 * 60 * 60)


def cleanup_expired_data(retention_days: int) -> dict[str, int]:
    if retention_days < 1:
        raise ValueError("Retention must be at least one day")
    init_db()
    now = datetime.now(timezone.utc)
    session_cutoff = (now - timedelta(days=retention_days)).isoformat(timespec="seconds")
    usage_cutoff = (now - timedelta(days=1)).isoformat(timespec="seconds")
    with database() as connection:
        expired_sessions = connection.execute("SELECT COUNT(*) AS count FROM sessions WHERE created_at<%s",
                                              (session_cutoff,)).fetchone()["count"]
        expired_cache = connection.execute("SELECT COUNT(*) AS count FROM ai_cache WHERE created_at<%s",
                                           (session_cutoff,)).fetchone()["count"]
        connection.execute("DELETE FROM sessions WHERE created_at<%s", (session_cutoff,))
        connection.execute("DELETE FROM ai_cache WHERE created_at<%s", (session_cutoff,))
        connection.execute("DELETE FROM api_usage WHERE occurred_at<%s", (usage_cutoff,))
    return {"sessions": expired_sessions, "ai_cache": expired_cache}


def update_review(session_id: str, finding_id: str, update: ReviewUpdate) -> ReviewResponse | None:
    init_db()
    with database() as connection:
        row = connection.execute("SELECT review_status, review_comment FROM findings WHERE id=%s AND session_id=%s",
                                 (finding_id, session_id)).fetchone()
        if row is None:
            return None
        comment = update.comment.strip()
        connection.execute("UPDATE findings SET review_status=%s, review_comment=%s WHERE id=%s AND session_id=%s",
                           (update.status, comment, finding_id, session_id))
        _event(connection, session_id, "review_updated", finding_id=finding_id,
               old_status=row["review_status"], new_status=update.status, comment=comment)
    return ReviewResponse(finding_id=finding_id, session_id=session_id,
                          review_status=update.status, review_comment=comment)


def record_report(session_id: str, report_id: str) -> None:
    init_db()
    with database() as connection:
        _event(connection, session_id, "report_generated", detail=report_id)


def get_cached_ai(cache_key: str) -> list[AIFinding] | None:
    init_db()
    with database() as connection:
        row = connection.execute("SELECT results_json FROM ai_cache WHERE cache_key=%s", (cache_key,)).fetchone()
    return [AIFinding.model_validate(item) for item in json.loads(row["results_json"])] if row else None


def put_cached_ai(cache_key: str, model: str, findings: list[AIFinding]) -> None:
    init_db()
    with database() as connection:
        connection.execute("""INSERT INTO ai_cache(cache_key, model, results_json, created_at) VALUES (%s, %s, %s, %s)
            ON CONFLICT(cache_key) DO UPDATE SET results_json=excluded.results_json, created_at=excluded.created_at""",
            (cache_key, model, json.dumps([item.model_dump(exclude={"id", "review_status", "review_comment"}) for item in findings]), utc_now()))


def list_corrections(session_id: str, *, include_history: bool = False) -> list[CorrectionRecord]:
    init_db()
    with database() as connection:
        predicate = "" if include_history else "AND superseded_at IS NULL"
        rows = connection.execute(f"SELECT * FROM corrections WHERE session_id=%s {predicate} ORDER BY created_at, sequence",
                                  (session_id,)).fetchall()
    return [CorrectionRecord.model_validate(dict(row)) for row in rows]


def save_correction(session_id: str, data: CorrectionInput, previous_id: str | None = None) -> CorrectionRecord:
    """Create a new immutable value version; editing supersedes the previous version."""
    init_db()
    with database() as connection:
        connection.execute("SELECT id FROM sessions WHERE id=%s FOR UPDATE", (session_id,))
        finding = connection.execute("SELECT requirement_id, review_status, payload_json FROM findings WHERE id=%s AND session_id=%s",
                                     (data.finding_id, session_id)).fetchone()
        if finding is None:
            raise ValueError("Finding not found")
        if _requirement_review(connection, session_id, finding["requirement_id"]).status != "accepted":
            raise ValueError("Confirm the issue before entering a correction")
        deterministic = connection.execute("""SELECT payload_json FROM findings
            WHERE session_id=%s AND requirement_id=%s AND kind='deterministic'""",
            (session_id, finding["requirement_id"])).fetchone()
        ai_count = connection.execute("""SELECT COUNT(*) AS count FROM findings
            WHERE session_id=%s AND requirement_id=%s AND kind='ai'""",
            (session_id, finding["requirement_id"])).fetchone()["count"]
        if deterministic and json.loads(deterministic["payload_json"])["status"] == "match" and not ai_count:
            raise ValueError("A clean match does not need a correction")
        existing = connection.execute("SELECT * FROM corrections WHERE session_id=%s AND requirement_id=%s AND superseded_at IS NULL",
                                      (session_id, finding["requirement_id"])).fetchone()
        if (existing["id"] if existing else None) != previous_id:
            raise ValueError("Correction has changed; reload before saving")
        if existing and existing["finding_id"] != data.finding_id:
            raise ValueError("Correction belongs to another finding")
        submitted = connection.execute("SELECT payload_json FROM findings WHERE session_id=%s AND requirement_id=%s AND kind='deterministic'",
                                       (session_id, finding["requirement_id"])).fetchone()
        original = json.loads(submitted["payload_json"]).get("submitted") if submitted else None
        original_value = original.get("excerpt", "Missing") if original else "Missing"
        now = utc_now()
        if existing:
            connection.execute("UPDATE corrections SET superseded_at=%s, updated_at=%s WHERE id=%s", (now, now, existing["id"]))
        correction_id = str(uuid4())
        connection.execute("""INSERT INTO corrections
            (id, session_id, finding_id, requirement_id, field_name, original_value, corrected_value,
             reason, supporting_notes, status, created_at, updated_at, verified_at, verification_note, superseded_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'draft', %s, %s, NULL, '', NULL)""",
            (correction_id, session_id, data.finding_id, finding["requirement_id"], data.field_name,
             original_value, data.corrected_value, data.reason, data.supporting_notes, now, now))
        _event(connection, session_id, "correction_revised" if existing else "correction_created",
               finding_id=data.finding_id, detail=correction_id)
        row = connection.execute("SELECT * FROM corrections WHERE id=%s", (correction_id,)).fetchone()
    return CorrectionRecord.model_validate(dict(row))


def change_correction_status(session_id: str, correction_id: str, update: CorrectionStatusUpdate) -> CorrectionRecord:
    init_db()
    transitions = {"draft": {"pending_verification"},
                   "pending_verification": {"draft", "verified", "rejected"},
                   "verified": set(), "rejected": set()}
    with database() as connection:
        connection.execute("SELECT id FROM sessions WHERE id=%s FOR UPDATE", (session_id,))
        row = connection.execute("""SELECT c.*, f.review_status FROM corrections c JOIN findings f ON f.id=c.finding_id
            WHERE c.id=%s AND c.session_id=%s AND c.superseded_at IS NULL""", (correction_id, session_id)).fetchone()
        if row is None:
            raise ValueError("Current correction not found")
        if update.status not in transitions[row["status"]]:
            raise ValueError("Invalid correction status transition")
        if update.status == "verified" and _requirement_review(connection, session_id, row["requirement_id"]).status != "accepted":
            raise ValueError("The requirement must remain confirmed before verification")
        now = utc_now()
        verified_at = now if update.status == "verified" else None
        connection.execute("""UPDATE corrections SET status=%s, updated_at=%s, verified_at=%s, verification_note=%s
            WHERE id=%s""", (update.status, now, verified_at, update.note.strip(), correction_id))
        _event(connection, session_id, "correction_status_changed", finding_id=row["finding_id"],
               old_status=row["status"], new_status=update.status, comment=update.note.strip(), detail=correction_id)
        result = connection.execute("SELECT * FROM corrections WHERE id=%s", (correction_id,)).fetchone()
    return CorrectionRecord.model_validate(dict(result))


def create_revision(session_id: str) -> RevisionRecord:
    init_db()
    with database() as connection:
        session = connection.execute("SELECT id FROM sessions WHERE id=%s FOR UPDATE", (session_id,)).fetchone()
        if session is None:
            raise ValueError("Comparison not found")
        rows = connection.execute("""SELECT c.* FROM corrections c WHERE c.session_id=%s
            AND c.superseded_at IS NULL AND c.status!='rejected' ORDER BY c.requirement_id""", (session_id,)).fetchall()
        rows = [row for row in rows if _requirement_review(connection, session_id, row["requirement_id"]).status == "accepted"]
        if not rows:
            raise ValueError("Add a correction before generating a revision")
        corrections = [dict(row) for row in rows]
        required = {row["requirement_id"] for row in connection.execute("""SELECT requirement_id FROM requirements
            WHERE session_id=%s""", (session_id,)) if _requirement_review(connection, session_id, row["requirement_id"]).status == "accepted"}
        verified = (all(row["status"] == "verified" for row in corrections)
                    and required.issubset({row["requirement_id"] for row in corrections}))
        number = connection.execute("SELECT COALESCE(MAX(number),0)+1 AS next_number FROM revisions WHERE session_id=%s", (session_id,)).fetchone()["next_number"]
        revision_id = f"REV-{uuid4().hex[:16].upper()}"
        now = utc_now()
        snapshot = {"corrections": corrections, "requirements": [dict(row) for row in connection.execute(
            "SELECT requirement_id, title, reference_text FROM requirements WHERE session_id=%s ORDER BY position", (session_id,))]}
        connection.execute("""INSERT INTO revisions (id, session_id, number, status, created_at, snapshot_json)
            VALUES (%s, %s, %s, %s, %s, %s)""", (revision_id, session_id, number, "verified" if verified else "draft", now, json.dumps(snapshot)))
        _event(connection, session_id, "revision_generated", detail=f"{revision_id}; number={number}; status={'verified' if verified else 'draft'}")
    return RevisionRecord(id=revision_id, session_id=session_id, number=number,
                          status="verified" if verified else "draft", created_at=now,
                          correction_ids=[row["id"] for row in corrections])


def list_revisions(session_id: str) -> list[RevisionRecord]:
    init_db()
    with database() as connection:
        rows = connection.execute("SELECT * FROM revisions WHERE session_id=%s ORDER BY number DESC", (session_id,)).fetchall()
    return [RevisionRecord(id=row["id"], session_id=session_id, number=row["number"],
                           status=row["status"], created_at=row["created_at"],
                           correction_ids=[item["id"] for item in json.loads(row["snapshot_json"])["corrections"]]) for row in rows]


def get_revision(revision_id: str) -> tuple[RevisionRecord, dict] | None:
    init_db()
    with database() as connection:
        row = connection.execute("SELECT * FROM revisions WHERE id=%s", (revision_id,)).fetchone()
    if row is None:
        return None
    snapshot = json.loads(row["snapshot_json"])
    record = RevisionRecord(id=row["id"], session_id=row["session_id"], number=row["number"],
                            status=row["status"], created_at=row["created_at"],
                            correction_ids=[item["id"] for item in snapshot["corrections"]])
    return record, snapshot


if __name__ == "__main__":
    init_db()
    print("PostgreSQL schema initialized")
