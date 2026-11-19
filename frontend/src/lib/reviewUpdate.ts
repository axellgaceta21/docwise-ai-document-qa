import type { Comparison, RequirementReviewUpdate } from '../types'

export function applyReviewUpdate(comparison: Comparison, update: RequirementReviewUpdate): Comparison {
  const { audit_event, ...review } = update
  return {
    ...comparison,
    requirement_reviews: [
      ...comparison.requirement_reviews.filter(item => item.requirement_id !== review.requirement_id),
      review,
    ],
    audit_events: comparison.audit_events.some(item => item.id === audit_event.id)
      ? comparison.audit_events
      : [...comparison.audit_events, audit_event],
  }
}
