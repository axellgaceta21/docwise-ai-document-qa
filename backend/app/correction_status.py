"""Derived correction labels; database lifecycle values remain unchanged."""
from .models import CorrectionRecord, Finding, RequirementReview


LABELS = {
    "not_required": "Not Required",
    "awaiting_review": "Awaiting Review",
    "needs_correction": "Needs Correction",
    "draft": "Draft",
    "pending_verification": "Pending Verification",
    "verified": "Verified",
    "correction_rejected": "Correction Rejected",
}


def correction_display(review: RequirementReview | None, finding: Finding | None,
                       ai_present: bool, correction: CorrectionRecord | None) -> str:
    if review and review.ambiguous_legacy:
        return "awaiting_review"
    if review and review.status == "rejected":
        return "not_required"
    if finding and finding.status == "match" and not ai_present:
        return "not_required"
    if not review or review.status != "accepted":
        return "awaiting_review"
    if correction is None:
        return "needs_correction"
    return "correction_rejected" if correction.status == "rejected" else correction.status
