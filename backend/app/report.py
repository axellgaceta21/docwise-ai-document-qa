"""Professional PDF snapshot of a saved comparison and its current review state."""
from io import BytesIO
from html import escape
import re

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .models import CompareResponse, CorrectionRecord
from .correction_status import LABELS as CORRECTION_DISPLAY_LABELS, correction_display


NAVY = colors.HexColor("#102a4c")
BLUE = colors.HexColor("#2872ce")
MUTED = colors.HexColor("#687a91")
PALE = colors.HexColor("#eef4fb")


def clean(value: object) -> str:
    safe = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(value or ""))
    return escape(safe).replace("\n", "<br/>")


REVIEW_LABELS = {"pending": "Pending Review", "accepted": "Confirmed issue",
                 "rejected": "Not an issue", "needs_investigation": "Needs checking"}
CORRECTION_LABELS = {"draft": "Draft correction", "pending_verification": "Pending verification",
                     "verified": "Verified", "rejected": "Rejected correction"}


def audit_label(event: dict) -> str:
    action, status = event["action"], event.get("new_status")
    if action in ("review_updated", "requirement_review_updated"):
        return {"accepted": "Issue confirmed", "rejected": "Marked as not an issue",
                "needs_investigation": "Sent for further checking", "pending": "Returned to Pending Review"}.get(status, "Review updated")
    if action in ("correction_created", "correction_revised"):
        return "Correction saved"
    if action == "correction_status_changed":
        return {"verified": "Correction verified", "rejected": "Correction rejected",
                "pending_verification": "Sent for verification", "draft": "Correction returned to draft"}.get(status, "Correction updated")
    return {"revision_generated": "Revised PDF generated", "report_generated": "QA report generated",
            "comparison_created": "Comparison created"}.get(action, action.replace("_", " "))


def build_report(result: CompareResponse, report_id: str,
                 corrections: list[CorrectionRecord] | None = None) -> bytes:
    stream = BytesIO()
    document = SimpleDocTemplate(stream, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                                 topMargin=23 * mm, bottomMargin=20 * mm,
                                 title=f"Document QA Report {report_id}", author="Document QA Engine")
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ReportTitle", parent=styles["Title"], fontName="Helvetica-Bold",
                              fontSize=20, leading=25, textColor=NAVY, spaceAfter=7))
    styles.add(ParagraphStyle(name="SectionTitle", parent=styles["Heading2"], fontName="Helvetica-Bold",
                              fontSize=12, leading=16, textColor=NAVY, spaceBefore=18, spaceAfter=8))
    styles.add(ParagraphStyle(name="BodySmall", parent=styles["BodyText"], fontName="Helvetica",
                              fontSize=9, leading=13, textColor=NAVY, spaceAfter=5))
    styles.add(ParagraphStyle(name="MetaSmall", parent=styles["BodyText"], fontName="Helvetica",
                              fontSize=8, leading=11, textColor=MUTED, spaceAfter=4))
    styles.add(ParagraphStyle(name="Disclaimer", parent=styles["BodyText"], fontName="Helvetica-Bold",
                              fontSize=9, leading=13, textColor=NAVY, backColor=PALE,
                              borderPadding=9, spaceBefore=14, spaceAfter=12))
    body, meta = styles["BodySmall"], styles["MetaSmall"]
    story = [Paragraph("Document Comparison &amp; QA Report", styles["ReportTitle"]),
             Paragraph(f"Report ID: <b>{clean(report_id)}</b>  |  Comparison date: {clean(result.created_at)}", meta),
             Paragraph(f"Approved reference: <b>{clean(result.reference_name)}</b> ({result.reference_pages} pages)", body),
             Paragraph(f"Submitted document: <b>{clean(result.submitted_name)}</b> ({result.submitted_pages} pages)", body),
             HRFlowable(width="100%", thickness=1, color=colors.HexColor("#d8e3ef")),
             Paragraph("Executive summary", styles["SectionTitle"])]
    counts = {name: sum(item.status == name for item in result.findings)
              for name in ("match", "different", "missing", "reference_missing")}
    story.append(Paragraph(
        f"{len(result.requirements)} requirements checked. {counts['match']} matching, {counts['different']} different, "
        f"{counts['missing']} missing, and {counts['reference_missing']} not located in the approved reference. "
        f"AI-assisted findings: {len(result.ai_findings)}. Review decisions do not certify compliance.", body))
    story.append(Paragraph(f"Comparison mode: {clean(result.mode)}  |  AI status: {clean(result.ai_status)}  |  "
                           f"AI cache: {'reused' if result.cache_hit else 'not reused'}", meta))
    if result.usage:
        story.append(Paragraph(f"New Groq usage: {result.usage.prompt_tokens} input, "
                               f"{result.usage.completion_tokens} output, {result.usage.total_tokens} total tokens.", meta))
    if result.estimated_cost_usd is not None:
        story.append(Paragraph(f"Estimated API cost: USD {result.estimated_cost_usd:.6f} (configured rates).", meta))
    story.append(Paragraph("Requirements checked", styles["SectionTitle"]))
    rows = [[Paragraph("ID", body), Paragraph("Requirement", body), Paragraph("Approved clause", body)]]
    for requirement in result.requirements:
        rows.append([Paragraph(clean(requirement.id), body), Paragraph(clean(requirement.title), body),
                     Paragraph(clean(requirement.reference_text), body)])
    table = Table(rows, colWidths=[24 * mm, 43 * mm, 103 * mm], repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PALE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d8e3ef")),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.append(table)
    story.append(Paragraph("Final requirement review decisions", styles["SectionTitle"]))
    reviews = {item.requirement_id: item for item in result.requirement_reviews}
    current_corrections = {item.requirement_id: item for item in (corrections or []) if not item.superseded_at}
    for requirement in result.requirements:
        review = reviews.get(requirement.id)
        finding = next((item for item in result.findings if item.requirement_id == requirement.id), None)
        ai_present = any(item.requirement_id == requirement.id for item in result.ai_findings)
        if review and review.ambiguous_legacy:
            label = "Needs review - conflicting historical decisions"
        elif finding and finding.status == "match" and not ai_present and (not review or review.source != "explicit"):
            label = "No review needed"
        else:
            label = {"pending": "Pending Review", "accepted": "Confirmed issue", "rejected": "Not an issue",
                     "needs_investigation": "Needs checking"}.get(review.status if review else "pending", "Pending Review")
        correction_status = correction_display(review, finding, ai_present, current_corrections.get(requirement.id))
        story.append(Paragraph(f"{clean(requirement.id)} - {clean(requirement.title)}: <b>{clean(label)}</b>"
                               f" | Correction: {clean(CORRECTION_DISPLAY_LABELS[correction_status])}", body))
        if review and review.comment:
            story.append(Paragraph(f"Reviewer comment: {clean(review.comment)}", meta))
    story.append(Paragraph("Document comparison findings and historical finding-level decisions", styles["SectionTitle"]))
    for finding in result.findings:
        story.append(Paragraph(f"<b>{clean(finding.requirement_id)} - {clean(finding.title)}</b> "
                               f"| {clean(finding.status).replace('_', ' ')} | Historical finding decision: {clean(REVIEW_LABELS[finding.review_status])}", body))
        story.append(Paragraph(clean(finding.explanation), body))
        story.append(Paragraph(f"Approved reference: {('p. ' + str(finding.reference.page) + ' - ' + clean(finding.reference.excerpt)) if finding.reference else 'No verified excerpt'}", meta))
        story.append(Paragraph(f"Submitted document: {('p. ' + str(finding.submitted.page) + ' - ' + clean(finding.submitted.excerpt)) if finding.submitted else 'No corresponding excerpt found'}", meta))
        if finding.review_comment:
            story.append(Paragraph(f"Reviewer comment: {clean(finding.review_comment)}", body))
        story.append(Spacer(1, 5))
    story.append(Paragraph("AI-assisted findings", styles["SectionTitle"]))
    if not result.ai_findings:
        story.append(Paragraph("No verified AI findings saved for this comparison.", body))
    for finding in result.ai_findings:
        story.append(Paragraph(f"<b>{clean(finding.requirement_id)} - {clean(finding.discrepancy_type).replace('_', ' ')}</b> "
                               f"| AI severity: {clean(finding.severity)} | Historical finding decision: {clean(REVIEW_LABELS[finding.review_status])}", body))
        story.append(Paragraph(clean(finding.explanation), body))
        story.append(Paragraph(f"Verified source: {clean(finding.source_document)} p. {finding.page_number} - "
                               f"{clean(finding.supporting_excerpt)}", meta))
        if finding.discrepancy_type == "missing_clause":
            story.append(Paragraph("No corresponding submitted-document excerpt was found; the cited clause is from the approved reference.", meta))
        if finding.uncertain:
            story.append(Paragraph("AI marked this finding uncertain. Qualified human review is required.", meta))
        if finding.review_comment:
            story.append(Paragraph(f"Reviewer comment: {clean(finding.review_comment)}", body))
        story.append(Spacer(1, 5))
    story.append(Paragraph("Review and report history", styles["SectionTitle"]))
    for event in result.audit_events:
        label = clean(audit_label(event))
        labels = CORRECTION_LABELS if event["action"] == "correction_status_changed" else REVIEW_LABELS
        old_label = labels.get(event.get("old_status"))
        new_label = labels.get(event.get("new_status"))
        status = f" ({clean(old_label)} to {clean(new_label)})" if old_label and new_label else (f" ({clean(new_label)})" if new_label else "")
        detail = f" - {clean(event['detail'])}" if event.get("detail") else ""
        comment = f" - Comment: {clean(event['comment'])}" if event.get("comment") else ""
        story.append(Paragraph(f"{clean(event['occurred_at'])}: {label}{status}{detail}{comment}", meta))
    story.append(Paragraph("AI findings and severity are advisory and require verification by a qualified human reviewer. "
                           "Accepting a finding records a review decision only; it does not certify engineering compliance.",
                           styles["Disclaimer"]))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#d8e3ef"))
        canvas.line(20 * mm, 16 * mm, A4[0] - 20 * mm, 16 * mm)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(20 * mm, 11 * mm, report_id)
        canvas.drawRightString(A4[0] - 20 * mm, 11 * mm, f"Page {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return stream.getvalue()
