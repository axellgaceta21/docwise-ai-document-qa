"""Content-addressed key for reusable, validated Groq analysis."""
import hashlib
import json

from .ai import (ANALYSIS_VERSION, MAX_AI_REQUIREMENTS, MAX_BATCH_CHARS,
                 MAX_BATCH_REQUIREMENTS, MAX_EXCERPT_CHARS, MAX_TOTAL_CHARS,
                 OUTPUT_SCHEMA, SYSTEM_PROMPT)
from .models import Requirement


def pdf_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def analysis_key(reference_hash: str, submitted_hash: str, requirements: list[Requirement], model: str,
                 visitor_id: str | None = None) -> str:
    payload = {
        "reference_sha256": reference_hash, "submitted_sha256": submitted_hash,
        "visitor_id": visitor_id,
        "requirements": [item.model_dump() for item in requirements], "model": model,
        "analysis_version": ANALYSIS_VERSION,
        "prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        "schema_sha256": hashlib.sha256(json.dumps(OUTPUT_SCHEMA, sort_keys=True).encode()).hexdigest(),
        "settings": {"max_ai_requirements": MAX_AI_REQUIREMENTS, "max_batch_requirements": MAX_BATCH_REQUIREMENTS,
                     "max_batch_chars": MAX_BATCH_CHARS, "max_total_chars": MAX_TOTAL_CHARS,
                     "max_excerpt_chars": MAX_EXCERPT_CHARS},
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
