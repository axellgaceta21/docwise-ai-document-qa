import re
from difflib import SequenceMatcher

from .models import Citation, Finding, Requirement
from .pdf import PageText


def normalize(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def lines(pages: list[PageText]) -> list[Citation]:
    return [Citation(page=page.page, excerpt=line.strip()) for page in pages for line in page.text.splitlines() if line.strip()]


def best_line(target: str, candidates: list[Citation]) -> tuple[Citation | None, float]:
    needle = normalize(target)
    if not needle:
        return None, 0.0
    best: Citation | None = None
    score = 0.0
    for candidate in candidates:
        current = normalize(candidate.excerpt)
        similarity = 1.0 if needle in current else SequenceMatcher(None, needle, current).ratio()
        if similarity > score:
            best, score = candidate, similarity
    return best, score


def compare(reference: list[PageText], submitted: list[PageText], requirements: list[Requirement]) -> list[Finding]:
    reference_lines = lines(reference)
    submitted_lines = lines(submitted)
    findings: list[Finding] = []
    for requirement in requirements:
        source, source_score = best_line(requirement.reference_text, reference_lines)
        if source is None or source_score < 0.80:
            findings.append(Finding(requirement_id=requirement.id, title=requirement.title,
                status="reference_missing", explanation="Checklist clause was not found in the approved reference. Review the checklist or source PDF."))
            continue
        candidate, candidate_score = best_line(source.excerpt, submitted_lines)
        if candidate is None or candidate_score < 0.50:
            status, explanation, candidate = "missing", "No corresponding clause was found in the submitted document.", None
        elif normalize(source.excerpt) == normalize(candidate.excerpt):
            status, explanation = "match", "The clause matches the approved reference."
        else:
            status, explanation = "different", "A related clause was found, but its wording or values differ. Review both excerpts."
        findings.append(Finding(requirement_id=requirement.id, title=requirement.title,
            status=status, explanation=explanation, reference=source, submitted=candidate))
    return findings
