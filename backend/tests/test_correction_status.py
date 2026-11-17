"""Derived correction status never replaces stored lifecycle or review history."""
from app.correction_status import LABELS, correction_display
from app.models import CorrectionRecord, Finding, RequirementReview


def finding(status="different"):
    return Finding(id="f-1", requirement_id="R-01", title="Pressure", status=status,
                   explanation="Compared values")


def review(status="pending", ambiguous=False):
    return RequirementReview(requirement_id="R-01", status=status, ambiguous_legacy=ambiguous)


def correction(status="draft", *, superseded=False):
    return CorrectionRecord(id="c-1", session_id="s-1", finding_id="f-1",
        requirement_id="R-01", field_name="Pressure", original_value="120 kPa",
        corrected_value="150 kPa", reason="Checked reference", supporting_notes="",
        status=status, created_at="2026-01-01", updated_at="2026-01-01",
        superseded_at="2026-01-02" if superseded else None)


def test_all_derived_correction_states():
    cases = [
        ("clean match", review(), finding("match"), False, None, "not_required"),
        ("confirmed without correction", review("accepted"), finding(), False, None, "needs_correction"),
        ("pending review", review(), finding(), False, None, "awaiting_review"),
        ("draft", review("accepted"), finding(), False, correction("draft"), "draft"),
        ("pending verification", review("accepted"), finding(), False, correction("pending_verification"), "pending_verification"),
        ("verified", review("accepted"), finding(), False, correction("verified"), "verified"),
        ("rejected correction", review("accepted"), finding(), False, correction("rejected"), "correction_rejected"),
        ("edited verified correction", review("accepted"), finding(), False, correction("draft"), "draft"),
        ("dismissed finding", review("rejected"), finding(), False, correction("verified"), "not_required"),
        ("AI concern on match", review(), finding("match"), True, None, "awaiting_review"),
        ("legacy conflict", review(ambiguous=True), finding(), False, None, "awaiting_review"),
    ]
    for name, decision, result, ai_present, current, expected in cases:
        assert correction_display(decision, result, ai_present, current) == expected, name
        assert LABELS[expected]
