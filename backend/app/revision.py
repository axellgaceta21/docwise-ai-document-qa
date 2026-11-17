"""Structured revision PDF built from a saved, immutable revision snapshot."""
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .models import CompareResponse, RevisionRecord
from .report import clean
from .correction_status import LABELS as CORRECTION_DISPLAY_LABELS


def build_revision(result: CompareResponse, revision: RevisionRecord, snapshot: dict,
                   history: list[RevisionRecord]) -> bytes:
    stream = BytesIO()
    document = SimpleDocTemplate(stream, pagesize=A4, leftMargin=19 * mm, rightMargin=19 * mm,
                                 topMargin=20 * mm, bottomMargin=19 * mm,
                                 title=f"Docwise structured revision {revision.id}", author="Docwise")
    styles = getSampleStyleSheet()
    navy, muted = colors.HexColor("#14253D"), colors.HexColor("#526176")
    styles.add(ParagraphStyle(name="RevisionTitle", parent=styles["Title"], fontName="Helvetica-Bold",
                              fontSize=18, leading=22, textColor=navy, spaceAfter=9))
    styles.add(ParagraphStyle(name="RevisionSection", parent=styles["Heading2"], fontName="Helvetica-Bold",
                              fontSize=11, leading=15, textColor=navy, spaceBefore=13, spaceAfter=6))
    styles.add(ParagraphStyle(name="RevisionBody", parent=styles["BodyText"], fontSize=9,
                              leading=13, textColor=navy, spaceAfter=5))
    styles.add(ParagraphStyle(name="RevisionMeta", parent=styles["BodyText"], fontSize=8,
                              leading=11, textColor=muted, spaceAfter=4))
    body, meta = styles["RevisionBody"], styles["RevisionMeta"]
    by_requirement = {item["requirement_id"]: item for item in snapshot["corrections"]}
    submitted = {item.requirement_id: item for item in result.findings}
    story = [Paragraph("DOCWISE  |  Document Quality Assurance", meta),
             Paragraph("Structured Document Revision", styles["RevisionTitle"]),
             Paragraph(f"Document title: {clean(result.submitted_name)} — structured revision", body),
             Paragraph(f"Status: <b>{'Verified Revision' if revision.status == 'verified' else 'Draft Revision'}</b>"
                       f"  |  Revision {revision.number}  |  ID {clean(revision.id)}", body),
             Paragraph(f"Generated: {clean(revision.created_at)}  |  Original comparison: {clean(result.session_id)}", meta),
             Paragraph(f"Approved reference: {clean(result.reference_name)}<br/>"
                       f"Original submitted document: {clean(result.submitted_name)}", body),
             Paragraph("Updated requirements and values", styles["RevisionSection"])]
    rows = [[Paragraph("Requirement", body), Paragraph("Value in this structured revision", body), Paragraph("Source / state", body)]]
    for req in snapshot["requirements"]:
        correction = by_requirement.get(req["requirement_id"])
        finding = submitted.get(req["requirement_id"])
        if correction:
            value = correction["corrected_value"]
            source = f"Correction {CORRECTION_DISPLAY_LABELS[correction['status']]}; approved reference p. "
            source += str(finding.reference.page) if finding and finding.reference else "not located"
        elif finding and finding.status == "match" and finding.submitted:
            value = finding.submitted.excerpt
            source = f"Unchanged matched value; submitted p. {finding.submitted.page}"
        else:
            value = "No verified revised value supplied"
            source = "Unresolved; original submission was not changed"
        rows.append([Paragraph(f"{clean(req['requirement_id'])}<br/>{clean(req['title'])}", body),
                     Paragraph(clean(value), body), Paragraph(clean(source), meta)])
    table = Table(rows, colWidths=[43 * mm, 82 * mm, 47 * mm], repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E9EFF5")),
                               ("GRID", (0, 0), (-1, -1), .3, colors.HexColor("#DCE3EB")),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 6),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                               ("TOPPADDING", (0, 0), (-1, -1), 6),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story.append(table)
    story.append(Paragraph("Correction summary", styles["RevisionSection"]))
    for correction in snapshot["corrections"]:
        story.extend([Paragraph(f"<b>{clean(correction['requirement_id'])} — {clean(correction['field_name'])}</b>"
                                f"  |  {clean(CORRECTION_DISPLAY_LABELS[correction['status']])}", body),
                      Paragraph(f"Original submitted value: {clean(correction['original_value'])}<br/>"
                                f"Corrected value: {clean(correction['corrected_value'])}<br/>"
                                f"Reason: {clean(correction['reason'])}", body)])
        if correction["supporting_notes"]:
            story.append(Paragraph(f"Supporting reference / notes: {clean(correction['supporting_notes'])}", meta))
        if correction["verified_at"]:
            story.append(Paragraph(f"Human verification: {clean(correction['verified_at'])}; "
                                   f"note: {clean(correction['verification_note']) or 'No note recorded'}", meta))
    story.append(Paragraph("Revision history", styles["RevisionSection"]))
    for item in sorted(history, key=lambda entry: entry.number):
        if item.number <= revision.number:
            story.append(Paragraph(f"Revision {item.number}: {clean(item.id)} — {clean(item.status)} — "
                                   f"{clean(item.created_at)}", meta))
    story.extend([Spacer(1, 8), Paragraph("This is a structured PDF generated from reviewer-entered values. "
                  "It is not an edited copy of the uploaded engineering PDF. Qualified personnel remain "
                  "responsible for technical validation. Neither Draft nor Verified Revision constitutes "
                  "engineering design approval, certification, or authorization for construction.", body)])
    document.build(story)
    return stream.getvalue()
