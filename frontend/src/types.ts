export type ReviewStatus = 'pending' | 'accepted' | 'rejected' | 'needs_investigation'
export type Requirement = { id: string; title: string; reference_text: string }
export type Citation = { page: number; excerpt: string }
export type Reviewable = { id: string | null; review_status: ReviewStatus; review_comment: string }
export type RequirementReview = { requirement_id: string; status: ReviewStatus; comment: string; ambiguous_legacy: boolean; source: 'explicit' | 'legacy' | 'default' }
export type ReviewDisplay = ReviewStatus | 'no_review_needed' | 'needs_review' | 'legacy_conflict'
export type CorrectionStatus = 'draft' | 'pending_verification' | 'verified' | 'rejected'
export type CorrectionDisplayStatus = 'not_required' | 'awaiting_review' | 'needs_correction' | 'draft' | 'pending_verification' | 'verified' | 'correction_rejected'
export type Correction = {
  id: string; session_id: string; finding_id: string; requirement_id: string
  field_name: string; original_value: string; corrected_value: string; reason: string
  supporting_notes: string; status: CorrectionStatus; created_at: string; updated_at: string
  verified_at: string | null; verification_note: string; superseded_at: string | null
}
export type CorrectionInput = Pick<Correction, 'finding_id' | 'field_name' | 'corrected_value' | 'reason' | 'supporting_notes'>
export type Revision = { id: string; session_id: string; number: number; status: 'draft' | 'verified'; created_at: string; correction_ids: string[] }
export type DeterministicFinding = Reviewable & {
  requirement_id: string
  title: string
  status: 'match' | 'different' | 'missing' | 'reference_missing'
  explanation: string
  reference: Citation | null
  submitted: Citation | null
}
export type AiFinding = Reviewable & {
  requirement_id: string
  discrepancy_type: string
  severity: 'high' | 'medium' | 'low' | 'unknown'
  explanation: string
  source_document: 'reference' | 'submitted'
  page_number: number
  supporting_excerpt: string
  uncertain: boolean
  citation_verified: boolean
}
export type AuditEvent = {
  id: string
  finding_id: string | null
  action: string
  old_status: string | null
  new_status: string | null
  comment: string | null
  detail: string | null
  occurred_at: string
}
export type Comparison = {
  session_id: string | null
  created_at: string | null
  reference_name: string
  submitted_name: string
  reference_pages: number
  submitted_pages: number
  findings: DeterministicFinding[]
  requirements: Requirement[]
  mode: 'deterministic' | 'ai'
  ai_findings: AiFinding[]
  ai_status: 'not_requested' | 'completed' | 'partial' | 'unavailable'
  ai_message: string | null
  ai_model: string | null
  usage: { prompt_tokens: number; completion_tokens: number; total_tokens: number } | null
  estimated_cost_usd: number | null
  cache_hit: boolean
  audit_events: AuditEvent[]
  requirement_reviews: RequirementReview[]
}
export type SessionSummary = {
  session_id: string
  created_at: string
  mode: 'deterministic' | 'ai'
  reference_name: string
  submitted_name: string
  ai_status: string
  cache_hit: boolean
}
export type RequirementRow = {
  key: string
  requirement: Requirement
  deterministic: DeterministicFinding | null
  ai: AiFinding[]
}

export const REVIEW_LABELS: Record<ReviewStatus, string> = {
  pending: 'Pending Review',
  accepted: 'Confirmed issue',
  rejected: 'Not an issue',
  needs_investigation: 'Needs checking',
}

export const CORRECTION_LABELS: Record<CorrectionStatus, string> = {
  draft: 'Draft correction', pending_verification: 'Pending verification',
  verified: 'Verified', rejected: 'Rejected correction',
}
export const CORRECTION_DISPLAY_LABELS: Record<CorrectionDisplayStatus, string> = {
  not_required: 'Not Required', awaiting_review: 'Awaiting Review',
  needs_correction: 'Needs Correction', draft: 'Draft',
  pending_verification: 'Pending Verification', verified: 'Verified',
  correction_rejected: 'Correction Rejected',
}
export const AI_TYPE_LABELS: Record<AiFinding['discrepancy_type'], string> = {
  value_mismatch: 'Different values', semantic_difference: 'Different meaning',
  missing_clause: 'Missing information', unclear: 'Needs checking',
}

export const RESULT_LABELS: Record<DeterministicFinding['status'], string> = {
  match: 'Match',
  different: 'Different',
  missing: 'Missing',
  reference_missing: 'Check reference',
}

export function mergeRequirements(comparison: Comparison): RequirementRow[] {
  const deterministic = new Map(comparison.findings.map(item => [item.requirement_id, item]))
  const ai = new Map<string, AiFinding[]>()
  for (const finding of comparison.ai_findings) {
    const group = ai.get(finding.requirement_id) ?? []
    group.push(finding)
    ai.set(finding.requirement_id, group)
  }
  return comparison.requirements.map(requirement => ({
    key: requirement.id,
    requirement,
    deterministic: deterministic.get(requirement.id) ?? null,
    ai: ai.get(requirement.id) ?? [],
  }))
}

export function rowSeverity(row: RequirementRow): AiFinding['severity'] | null {
  const order: AiFinding['severity'][] = ['high', 'medium', 'unknown', 'low']
  return order.find(value => row.ai.some(item => item.severity === value)) ?? null
}

export function reviewForRequirement(comparison: Comparison, row: RequirementRow): RequirementReview {
  return comparison.requirement_reviews?.find(item => item.requirement_id === row.key)
    ?? { requirement_id: row.key, status: 'pending', comment: '', ambiguous_legacy: false, source: 'default' }
}

export function rowReviewStatus(comparison: Comparison, row: RequirementRow): ReviewDisplay {
  const review = reviewForRequirement(comparison, row)
  if (review.ambiguous_legacy) return 'legacy_conflict'
  if (row.deterministic?.status === 'match' && row.ai.length === 0 && review.source !== 'explicit') return 'no_review_needed'
  if (row.deterministic?.status === 'match' && row.ai.length > 0 && review.status === 'pending') return 'needs_review'
  return review.status
}

export function correctionDisplay(comparison: Comparison, row: RequirementRow, corrections: Correction[]): {
  status: CorrectionDisplayStatus; label: string; tone: 'success' | 'neutral' | 'gray' | 'amber' | 'danger'
} {
  const review = reviewForRequirement(comparison, row)
  const clean = row.deterministic?.status === 'match' && row.ai.length === 0
  let status: CorrectionDisplayStatus
  let tone: 'success' | 'neutral' | 'gray' | 'amber' | 'danger'
  if (review.ambiguous_legacy) { status = 'awaiting_review'; tone = 'gray' }
  else if (review.status === 'rejected') { status = 'not_required'; tone = 'neutral' }
  else if (clean) { status = 'not_required'; tone = 'success' }
  else if (review.status !== 'accepted') { status = 'awaiting_review'; tone = 'gray' }
  else {
    const current = corrections.find(item => item.requirement_id === row.key && !item.superseded_at)
    status = current?.status === 'verified' ? 'verified'
      : current?.status === 'pending_verification' ? 'pending_verification'
      : current?.status === 'draft' ? 'draft'
      : current?.status === 'rejected' ? 'correction_rejected' : 'needs_correction'
    tone = status === 'verified' ? 'success' : status === 'draft' ? 'neutral'
      : status === 'pending_verification' ? 'amber' : 'danger'
  }
  return { status, label: CORRECTION_DISPLAY_LABELS[status], tone }
}

export const REVIEW_DISPLAY_LABELS: Record<ReviewDisplay, string> = {
  ...REVIEW_LABELS, no_review_needed: 'No review needed', needs_review: 'Needs review',
  legacy_conflict: 'Needs review',
}

export function approvedReferenceValue(row: RequirementRow): { value: string | null; source: 'document' | 'checklist' | 'none' } {
  if (row.deterministic?.reference?.excerpt) return { value: row.deterministic.reference.excerpt, source: 'document' }
  if (row.requirement.reference_text) return { value: row.requirement.reference_text, source: 'checklist' }
  return { value: null, source: 'none' }
}

export function auditActionLabel(event: AuditEvent): string {
  if (event.action === 'review_updated' || event.action === 'requirement_review_updated') {
    return event.new_status === 'accepted' ? 'Issue confirmed'
      : event.new_status === 'rejected' ? 'Marked as not an issue'
      : event.new_status === 'needs_investigation' ? 'Sent for further checking'
      : 'Returned to Pending Review'
  }
  if (event.action === 'correction_created' || event.action === 'correction_revised') return 'Correction saved'
  if (event.action === 'correction_status_changed') {
    return event.new_status === 'verified' ? 'Correction verified'
      : event.new_status === 'rejected' ? 'Correction rejected'
      : event.new_status === 'pending_verification' ? 'Sent for verification' : 'Correction returned to draft'
  }
  if (event.action === 'revision_generated') return 'Revised PDF generated'
  if (event.action === 'comparison_created') return 'Comparison created'
  if (event.action === 'report_generated') return 'QA report generated'
  return event.action.replaceAll('_', ' ')
}

export function auditTransitionLabel(event: AuditEvent): string | null {
  if (!event.new_status) return null
  const labels = event.action === 'correction_status_changed' ? CORRECTION_LABELS : REVIEW_LABELS
  const before = event.old_status && labels[event.old_status as keyof typeof labels]
  const after = labels[event.new_status as keyof typeof labels]
  return after ? (before ? before + ' → ' + after : after) : null
}
