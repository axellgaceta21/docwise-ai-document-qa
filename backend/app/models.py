from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator


class Requirement(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=120)
    reference_text: str = Field(min_length=3, max_length=1000)

    @field_validator("id", "title", "reference_text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Value cannot be blank")
        return value


class Citation(BaseModel):
    page: int
    excerpt: str


class Finding(BaseModel):
    id: str | None = None
    requirement_id: str
    title: str
    status: Literal["match", "different", "missing", "reference_missing"]
    explanation: str
    reference: Citation | None = None
    submitted: Citation | None = None
    review_status: Literal["pending", "accepted", "rejected", "needs_investigation"] = "pending"
    review_comment: str = ""


class AIFinding(BaseModel):
    id: str | None = None
    requirement_id: str
    discrepancy_type: Literal["value_mismatch", "semantic_difference", "missing_clause", "unclear"]
    severity: Literal["low", "medium", "high", "unknown"]
    explanation: str
    source_document: Literal["reference", "submitted"]
    page_number: int = Field(ge=1)
    supporting_excerpt: str
    uncertain: bool
    citation_verified: bool = True
    review_status: Literal["pending", "accepted", "rejected", "needs_investigation"] = "pending"
    review_comment: str = ""


class TokenUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class CompareResponse(BaseModel):
    session_id: str | None = None
    created_at: str | None = None
    reference_name: str
    submitted_name: str
    reference_pages: int
    submitted_pages: int
    findings: list[Finding]
    requirements: list[Requirement] = Field(default_factory=list)
    mode: Literal["deterministic", "ai"] = "deterministic"
    ai_findings: list[AIFinding] = Field(default_factory=list)
    ai_status: Literal["not_requested", "completed", "partial", "unavailable"] = "not_requested"
    ai_message: str | None = None
    ai_model: str | None = None
    usage: TokenUsage | None = None
    estimated_cost_usd: float | None = None
    cache_hit: bool = False
    duration_ms: int | None = None
    ai_duration_ms: int | None = None
    audit_events: list[dict] = Field(default_factory=list)
    requirement_reviews: list["RequirementReview"] = Field(default_factory=list)


class ReviewUpdate(BaseModel):
    status: Literal["pending", "accepted", "rejected", "needs_investigation"]
    comment: str = Field(default="", max_length=2000)


class ReviewResponse(BaseModel):
    finding_id: str
    session_id: str
    review_status: Literal["pending", "accepted", "rejected", "needs_investigation"]
    review_comment: str


class RequirementReview(BaseModel):
    requirement_id: str
    status: Literal["pending", "accepted", "rejected", "needs_investigation"] = "pending"
    comment: str = ""
    ambiguous_legacy: bool = False
    source: Literal["explicit", "legacy", "default"] = "default"


CorrectionStatus = Literal["draft", "pending_verification", "verified", "rejected"]


class CorrectionInput(BaseModel):
    finding_id: str
    field_name: str = Field(min_length=1, max_length=120)
    corrected_value: str = Field(min_length=1, max_length=2000)
    reason: str = Field(min_length=1, max_length=2000)
    supporting_notes: str = Field(default="", max_length=2000)

    @field_validator("field_name", "corrected_value", "reason", "supporting_notes")
    @classmethod
    def trim_correction(cls, value: str, info: ValidationInfo) -> str:
        value = value.strip()
        if not value and info.field_name != "supporting_notes":
            raise ValueError("Value cannot be blank")
        return value


class CorrectionStatusUpdate(BaseModel):
    status: CorrectionStatus
    note: str = Field(default="", max_length=2000)


class CorrectionRecord(BaseModel):
    id: str
    session_id: str
    finding_id: str
    requirement_id: str
    field_name: str
    original_value: str
    corrected_value: str
    reason: str
    supporting_notes: str
    status: CorrectionStatus
    created_at: str
    updated_at: str
    verified_at: str | None = None
    verification_note: str = ""
    superseded_at: str | None = None


class RevisionRecord(BaseModel):
    id: str
    session_id: str
    number: int
    status: Literal["draft", "verified"]
    created_at: str
    correction_ids: list[str]
