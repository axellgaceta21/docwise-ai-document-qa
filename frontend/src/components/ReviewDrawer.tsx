import { useEffect, useRef, useState } from 'react'
import { FileText, X } from 'lucide-react'
import { saveCorrection, saveRequirementReview, setCorrectionStatus } from '../api'
import type { Comparison, Correction, RequirementRow, ReviewStatus, Revision } from '../types'
import { AI_TYPE_LABELS, approvedReferenceValue, auditActionLabel, auditTransitionLabel, CORRECTION_LABELS, correctionDisplay, RESULT_LABELS, REVIEW_LABELS, reviewForRequirement, rowReviewStatus } from '../types'

const outcome: Record<ReviewStatus, string> = {
  pending: 'This finding remains open for review.',
  accepted: 'The issue remains visible. You may enter a correction; the document is not changed automatically.',
  rejected: 'This finding stays in history and no longer counts as unresolved.',
  needs_investigation: 'The issue remains open while more information is checked.',
}

function currentFindingId(row: RequirementRow, corrections: Correction[]): string | null {
  const current = corrections.find(item => item.requirement_id === row.key && !item.superseded_at)
  if (current) return current.finding_id
  if (row.deterministic?.status === 'match' && row.ai[0]?.id) return row.ai[0].id
  return row.deterministic?.id ?? row.ai[0]?.id ?? null
}

export default function ReviewDrawer({ comparison, row, corrections, revisions, onClose, onSaved }: {
  comparison: Comparison; row: RequirementRow; corrections: Correction[]; revisions: Revision[]
  onClose: () => void; onSaved: () => Promise<void>
}) {
  const dialogRef = useRef<HTMLElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)
  const review = reviewForRequirement(comparison, row)
  const display = rowReviewStatus(comparison, row)
  const clean = display === 'no_review_needed'
  const hasDiscrepancy = row.deterministic?.status !== 'match' || row.ai.length > 0
  const correctionFindingId = currentFindingId(row, corrections)
  const current = corrections.find(item => item.requirement_id === row.key && !item.superseded_at)
  const correctionState = correctionDisplay(comparison, row, corrections)
  const [decision, setDecision] = useState<ReviewStatus>(review.status)
  const [comment, setComment] = useState(review.comment)
  const [fieldName, setFieldName] = useState(current?.field_name ?? row.requirement.title)
  const [correctedValue, setCorrectedValue] = useState(current?.corrected_value ?? '')
  const [reason, setReason] = useState(current?.reason ?? '')
  const [notes, setNotes] = useState(current?.supporting_notes ?? '')
  const [verificationNote, setVerificationNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  useEffect(() => { setMessage(''); setError('') }, [row.key])
  useEffect(() => { setDecision(review.status); setComment(review.comment) }, [row.key, review.status, review.comment, review.source, review.ambiguous_legacy])
  useEffect(() => {
    setFieldName(current?.field_name ?? row.requirement.title)
    setCorrectedValue(current?.corrected_value ?? '')
    setReason(current?.reason ?? '')
    setNotes(current?.supporting_notes ?? '')
  }, [current?.id, row.key])
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    closeRef.current?.focus()
    const keyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); onClose(); return }
      if (event.key !== 'Tab' || !dialogRef.current) return
      const focusable = [...dialogRef.current.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], select, textarea, input')]
      const first = focusable[0], last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
    }
    document.addEventListener('keydown', keyDown)
    return () => { document.removeEventListener('keydown', keyDown); document.body.style.overflow = overflow; previous?.focus() }
  }, [row.key])

  const act = async (action: () => Promise<unknown>, success: string) => {
    setSaving(true); setError(''); setMessage('')
    try { await action(); await onSaved(); setMessage(success) }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'The change could not be saved.') }
    finally { setSaving(false) }
  }
  const saveDecision = () => {
    if (comparison.session_id && !clean) void act(() => saveRequirementReview(comparison.session_id!, row.key, decision, comment), 'Requirement review decision saved.')
  }
  const saveValue = () => {
    if (comparison.session_id && correctionFindingId) void act(() => saveCorrection(comparison.session_id!, {
      finding_id: correctionFindingId, field_name: fieldName, corrected_value: correctedValue,
      reason, supporting_notes: notes,
    }, current?.id), 'Draft correction saved. Send it for verification when ready.')
  }
  const changeStatus = (status: Correction['status']) => {
    if (comparison.session_id && current) void act(
      () => setCorrectionStatus(comparison.session_id!, current.id, status, verificationNote),
      status === 'verified' ? 'Correction verified by human action.' : 'Correction status updated.')
  }
  const relevantIds = new Set([row.deterministic?.id, ...row.ai.map(item => item.id)])
  const relevantRevisionIds = new Set(revisions.filter(item => item.correction_ids.some(id =>
    corrections.some(correction => correction.id === id && correction.requirement_id === row.key))).map(item => item.id))
  const events = comparison.audit_events.filter(event =>
    (event.finding_id && relevantIds.has(event.finding_id))
    || (event.action === 'requirement_review_updated' && event.detail === row.key)
    || (event.action === 'revision_generated' && [...relevantRevisionIds].some(id => event.detail?.startsWith(id))))
  const original = row.deterministic?.submitted?.excerpt ?? 'Missing'
  const approved = approvedReferenceValue(row)

  return <div className="drawer-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}>
    <aside ref={dialogRef} className="details-drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title">
      <header className="drawer-header"><div><span className="drawer-kicker">REQUIREMENT {row.requirement.id}</span><h2 id="drawer-title">{row.requirement.title}</h2></div><button ref={closeRef} type="button" className="icon-button" aria-label="Close details" onClick={onClose}><X size={20}/></button></header>
      <div className="drawer-content">
        <section className="detail-section"><h3>What we found</h3>
          <p className="detail-plain"><b>Expected:</b> {row.requirement.reference_text}</p><p className="detail-plain"><b>Submitted:</b> {original}</p>
          <p className="detail-description">{row.deterministic?.explanation ?? 'No document comparison finding available.'}</p>
          <span className={'badge badge-result badge-' + (row.deterministic?.status ?? 'reference_missing')}>{RESULT_LABELS[row.deterministic?.status ?? 'reference_missing']}</span>
          {row.ai.map(item => <p key={item.id} className="detail-plain"><b>AI review — {AI_TYPE_LABELS[item.discrepancy_type]}:</b> {item.explanation}{item.uncertain && <span className="inline-error"> Needs manual checking.</span>}</p>)}
        </section>
        <section className="detail-section"><h3>Document evidence</h3><div className="evidence-grid">
          <div className="evidence-box"><span><FileText size={14}/> APPROVED REFERENCE {row.deterministic?.reference ? '· PAGE ' + row.deterministic.reference.page : ''}</span><p>{row.deterministic?.reference?.excerpt ?? 'No verified approved excerpt found.'}</p></div>
          <div className="evidence-box"><span><FileText size={14}/> SUBMITTED DOCUMENT {row.deterministic?.submitted ? '· PAGE ' + row.deterministic.submitted.page : ''}</span><p>{row.deterministic?.submitted?.excerpt ?? 'No corresponding submitted-document excerpt found.'}</p></div></div>
          {row.ai.length > 0 && <details className="technical-evidence"><summary>AI source details</summary>{row.ai.map(item => <div key={item.id} className="ai-detail"><p><b>{AI_TYPE_LABELS[item.discrepancy_type]}</b> · {item.severity} severity · {item.uncertain ? 'Needs manual checking' : 'Source verified'}</p><p>Source verified: {item.source_document} · page {item.page_number}</p><blockquote>{item.supporting_excerpt}</blockquote>{item.discrepancy_type === 'missing_clause' && <p>No submitted excerpt exists for this missing information. The approved reference supports the finding.</p>}</div>)}</details>}
        </section>
        <section className="detail-section review-section"><h3>Review decision</h3><p className="detail-muted">One final decision applies to this requirement. Automated findings and earlier decisions remain in the record. A decision does not certify engineering compliance.</p><p className="detail-plain">Correction: <span className={'badge badge-correction tone-' + correctionState.tone}>{correctionState.label}</span></p>
          {review.ambiguous_legacy && <div className="review-warning" role="alert">Older finding decisions conflict. No final decision was assumed. Review the history below and choose a decision for this requirement.<ul>{row.deterministic && <li>Document comparison: {REVIEW_LABELS[row.deterministic.review_status]}</li>}{row.ai.map((item, index) => <li key={item.id}>AI review {index + 1}: {REVIEW_LABELS[item.review_status]}</li>)}</ul></div>}
          {row.deterministic?.status === 'match' && row.ai.length > 0 && review.status === 'pending' && <p className="review-warning">AI raised a potential issue despite a matching document comparison. Human review is needed.</p>}
          {clean ? <p className="inline-success">No review needed. The documents match and AI raised no conflicting finding.</p> : <>
            <label className="form-label">Decision<select value={decision} onChange={event => setDecision(event.target.value as ReviewStatus)}><option value="pending">Pending Review</option><option value="accepted">Confirmed issue</option><option value="rejected">Not an issue</option><option value="needs_investigation">Needs checking</option></select></label>
            <p className="detail-muted">{outcome[decision]}</p>
            <label className="form-label">Reviewer comments<textarea value={comment} maxLength={2000} rows={3} placeholder="Record the basis for this decision" onChange={event => setComment(event.target.value)}/></label>
            <button type="button" className="primary-button save-button" disabled={saving} onClick={saveDecision}>{saving ? 'Saving…' : 'Save review'}</button>
          </>}
          {message && <p className="inline-success" role="status">{message}</p>}{error && <p className="inline-error" role="alert">{error}</p>}
        </section>
        {((review.status === 'accepted' && hasDiscrepancy) || current) && <section className="detail-section"><h3>Correction details</h3><p className="detail-muted">Entered values create a structured revision PDF after human verification. The uploaded PDF is never edited.</p>
          {current && <p className="correction-status">Current requirement status: {correctionState.label} · Correction updated {new Date(current.updated_at).toLocaleString()}</p>}
          {review.status === 'accepted' && hasDiscrepancy && <div className="correction-panel"><h4>{current ? 'Edit correction (creates a new draft)' : 'Enter a correction'}</h4>
            <p className="detail-plain"><b>Requirement:</b> {row.requirement.id} — {row.requirement.title}</p>
            <p className="detail-plain"><b>Original submitted value:</b> {original}</p>
            <p className="detail-plain"><b>Approved reference value:</b> {approved.value ?? 'No approved reference value available'}{approved.source === 'checklist' && <small> (checklist value; source excerpt unavailable)</small>}</p>
            <label className="form-label">Corrected value<textarea maxLength={2000} rows={3} value={correctedValue} onChange={event => setCorrectedValue(event.target.value)}/></label>
            <label className="form-label">Reason for correction<textarea maxLength={2000} rows={2} value={reason} onChange={event => setReason(event.target.value)}/></label>
            <label className="form-label">Supporting reference or notes<textarea maxLength={2000} rows={2} value={notes} onChange={event => setNotes(event.target.value)}/></label>
            <label className="form-label">Field or section name<input maxLength={120} value={fieldName} onChange={event => setFieldName(event.target.value)}/></label>
            <div className="correction-actions"><button type="button" className="secondary-button" disabled={saving || !fieldName.trim() || !correctedValue.trim() || !reason.trim()} onClick={saveValue}>Save draft correction</button></div></div>}
          {current && review.status === 'accepted' && <div className="correction-actions"><label className="form-label">Verification note<input maxLength={2000} value={verificationNote} onChange={event => setVerificationNote(event.target.value)}/></label>{current.status === 'draft' && <button type="button" className="secondary-button" disabled={saving} onClick={() => changeStatus('pending_verification')}>Send for verification</button>}{current.status === 'pending_verification' && <><button type="button" className="primary-button" disabled={saving} onClick={() => changeStatus('verified')}>Verify correction</button><button type="button" className="secondary-button" disabled={saving} onClick={() => changeStatus('rejected')}>Reject correction</button></>}</div>}
          {current?.status === 'verified' && <p className="inline-success">Verified {new Date(current.verified_at!).toLocaleString()}. This is a human verification record, not engineering approval.</p>}
        </section>}
        <section className="detail-section"><h3>Review and revision history</h3>{events.length ? <ol className="audit-list">{events.map(event => <li key={event.id}><time>{new Date(event.occurred_at).toLocaleString()}</time><strong>{auditActionLabel(event)}</strong>{auditTransitionLabel(event) && <p>{auditTransitionLabel(event)}</p>}{event.action === 'review_updated' && <p>Historical finding-level decision</p>}{event.comment && <p>{event.comment}</p>}</li>)}</ol> : <p className="detail-muted">No review or correction events recorded yet.</p>}
          {corrections.filter(item => item.requirement_id === row.key).map(item => <p key={item.id} className="detail-muted">Correction {new Date(item.created_at).toLocaleString()}: {item.corrected_value} · {CORRECTION_LABELS[item.status]}{item.superseded_at ? ' · replaced by a newer draft' : ''}</p>)}
          {revisions.filter(item => item.correction_ids.some(id => corrections.some(correction => correction.id === id && correction.requirement_id === row.key))).map(item => <p key={item.id} className="detail-muted">Revision {item.number} · {item.status === 'verified' ? 'Verified Revision' : 'Draft Revision'} · {new Date(item.created_at).toLocaleString()}</p>)}
        </section>
      </div>
    </aside>
  </div>
}
