import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, CheckCircle2, FileText, X } from 'lucide-react'
import { saveCorrection, saveRequirementReview, setCorrectionStatus } from '../api'
import type { Comparison, Correction, RequirementReviewUpdate, RequirementRow, ReviewStatus, Revision } from '../types'
import { AI_TYPE_LABELS, approvedReferenceValue, auditActionLabel, auditTransitionLabel, CORRECTION_LABELS, correctionDisplay, RESULT_LABELS, REVIEW_LABELS, reviewForRequirement, rowReviewStatus, rowSeverity } from '../types'

const outcome: Record<ReviewStatus, string> = {
  pending: 'This finding remains open for review.',
  accepted: 'Enter a correction below. A draft will still require separate human verification.',
  rejected: 'This finding stays in history and no longer counts as unresolved.',
  needs_investigation: 'The issue remains open while more information is checked.',
}

function currentFindingId(row: RequirementRow, corrections: Correction[]): string | null {
  const current = corrections.find(item => item.requirement_id === row.key && !item.superseded_at)
  if (current) return current.finding_id
  if (row.deterministic?.status === 'match' && row.ai[0]?.id) return row.ai[0].id
  return row.deterministic?.id ?? row.ai[0]?.id ?? null
}

function suggestedCorrection(row: RequirementRow): string {
  const value = approvedReferenceValue(row).value
  return value && value.length <= 2000 ? value : ''
}

export default function ReviewDrawer({ comparison, row, corrections, revisions, onClose, onSaved, onReviewSaved }: {
  comparison: Comparison; row: RequirementRow; corrections: Correction[]; revisions: Revision[]
  onClose: () => void; onSaved: () => Promise<void>; onReviewSaved?: (update: RequirementReviewUpdate) => void
}) {
  const dialogRef = useRef<HTMLElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)
  const savingRef = useRef(false)
  const review = reviewForRequirement(comparison, row)
  const display = rowReviewStatus(comparison, row)
  const clean = display === 'no_review_needed'
  const hasDiscrepancy = row.deterministic?.status !== 'match' || row.ai.length > 0
  const correctionFindingId = currentFindingId(row, corrections)
  const current = corrections.find(item => item.requirement_id === row.key && !item.superseded_at)
  const correctionState = correctionDisplay(comparison, row, corrections)
  const approved = approvedReferenceValue(row)
  const [decision, setDecision] = useState<ReviewStatus>(review.status)
  const [comment, setComment] = useState(review.comment)
  const [fieldName, setFieldName] = useState(current?.field_name ?? row.requirement.title)
  const [correctedValue, setCorrectedValue] = useState(current?.corrected_value ?? suggestedCorrection(row))
  const [reason, setReason] = useState(current?.reason ?? '')
  const [notes, setNotes] = useState(current?.supporting_notes ?? '')
  const [verificationNote, setVerificationNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [progress, setProgress] = useState('')
  const [refreshNeeded, setRefreshNeeded] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  useEffect(() => { setMessage(''); setError(''); setRefreshNeeded(false) }, [row.key])
  useEffect(() => { setDecision(review.status); setComment(review.comment) }, [row.key, review.status, review.comment, review.source, review.ambiguous_legacy])
  useEffect(() => {
    setFieldName(current?.field_name ?? row.requirement.title)
    setCorrectedValue(current?.corrected_value ?? suggestedCorrection(row))
    setReason(current?.reason ?? '')
    setNotes(current?.supporting_notes ?? '')
  }, [current?.id, row.key])
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    closeRef.current?.focus()
    const keyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); if (!savingRef.current) onClose(); return }
      if (event.key !== 'Tab' || !dialogRef.current) return
      const focusable = [...dialogRef.current.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], select, textarea, input, summary')]
      const first = focusable[0], last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
    }
    document.addEventListener('keydown', keyDown)
    return () => { document.removeEventListener('keydown', keyDown); document.body.style.overflow = overflow; previous?.focus() }
  }, [row.key])

  const act = async (action: () => Promise<unknown>, success: string, afterSaved: (result: unknown) => Promise<void> | void = onSaved) => {
    if (savingRef.current) return
    savingRef.current = true
    setSaving(true); setProgress('Saving change...'); setError(''); setMessage('')
    try {
      const result = await action()
      setProgress('Updating status...')
      try { await afterSaved(result); setMessage(success) }
      catch { setRefreshNeeded(true); setError('The change was saved, but the latest status could not be loaded. Retry refresh.') }
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'The change could not be saved. Please try again.') }
    finally { savingRef.current = false; setSaving(false); setProgress('') }
  }
  const reviewChanged = review.source !== 'explicit' || review.status !== decision || review.comment !== comment.trim()
  const correctionChanged = !current || [fieldName !== current.field_name, correctedValue !== current.corrected_value,
    reason !== current.reason, notes !== current.supporting_notes].some(Boolean)
  const wantsCorrection = decision === 'accepted' && hasDiscrepancy &&
    (current ? correctionChanged : Boolean(reason.trim() || notes.trim()))
  const correctionValid = !!correctionFindingId && !!fieldName.trim() && !!correctedValue.trim() && !!reason.trim()
  const saveDecision = async () => {
    if (!comparison.session_id || clean || savingRef.current || refreshNeeded || (!reviewChanged && !wantsCorrection)) return
    if (wantsCorrection && !correctionValid) { setError('Enter a corrected value and a reason before saving the draft correction.'); return }
    savingRef.current = true; setSaving(true); setError(''); setMessage(''); setRefreshNeeded(false)
    let decisionSaved = false
    try {
      if (reviewChanged) {
        setProgress('Saving decision...')
        const update = await saveRequirementReview(comparison.session_id, row.key, decision, comment)
        decisionSaved = true
        if (onReviewSaved) onReviewSaved(update)
        else await onSaved()
      }
      if (wantsCorrection) {
        setProgress('Saving draft correction...')
        await saveCorrection(comparison.session_id, {
          finding_id: correctionFindingId!, field_name: fieldName, corrected_value: correctedValue,
          reason, supporting_notes: notes,
        }, current?.id)
        setProgress('Updating status...')
        try { await onSaved() }
        catch { setRefreshNeeded(true); setError('Decision and correction were saved, but the latest status could not be loaded. Retry refresh.'); return }
        setMessage('Decision and draft correction saved. Next: send the correction for verification.')
      } else setMessage(decision === 'accepted' ? 'Issue confirmed. Next: enter a correction and explain why.' : 'Review decision saved.')
    } catch (cause) {
      const detail = cause instanceof Error ? cause.message : 'Please try again.'
      setError(decisionSaved ? `Decision saved, but the correction was not saved. ${detail} Retry saving the correction.` : detail)
    } finally { savingRef.current = false; setSaving(false); setProgress('') }
  }
  const retryRefresh = async () => {
    if (savingRef.current) return
    savingRef.current = true; setSaving(true); setProgress('Refreshing status...'); setError('')
    try { await onSaved(); setRefreshNeeded(false); setMessage('Latest status loaded.') }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not refresh status. Please try again.') }
    finally { savingRef.current = false; setSaving(false); setProgress('') }
  }
  const changeStatus = (status: Correction['status']) => {
    if (comparison.session_id && current) void act(
      () => setCorrectionStatus(comparison.session_id!, current.id, status, verificationNote),
      status === 'verified' ? 'Correction Approved.' : 'Correction status updated.')
  }
  const relevantIds = new Set([row.deterministic?.id, ...row.ai.map(item => item.id)])
  const relevantRevisionIds = new Set(revisions.filter(item => item.correction_ids.some(id =>
    corrections.some(correction => correction.id === id && correction.requirement_id === row.key))).map(item => item.id))
  const events = comparison.audit_events.filter(event =>
    (event.finding_id && relevantIds.has(event.finding_id))
    || (event.action === 'requirement_review_updated' && event.detail === row.key)
    || (event.action === 'revision_generated' && [...relevantRevisionIds].some(id => event.detail?.startsWith(id))))
  const result = row.deterministic?.status ?? 'reference_missing'
  const original = result === 'missing' ? 'No corresponding submitted excerpt' : row.deterministic?.submitted?.excerpt ?? 'Missing'
  const submittedTone = result === 'missing' ? 'missing'
    : result === 'reference_missing' || row.ai.some(item => item.uncertain) || (result === 'match' && row.ai.length > 0)
      ? 'review' : result
  const submittedLabel = submittedTone === 'missing' ? 'Missing' : submittedTone === 'review' ? 'Needs review'
    : submittedTone === 'match' ? 'Match' : 'Different'
  return <div className="review-modal-backdrop" onMouseDown={event => { if (event.target === event.currentTarget && !savingRef.current) onClose() }}>
    <section ref={dialogRef} className="review-modal" role="dialog" aria-modal="true" aria-labelledby="drawer-title" aria-describedby="review-modal-description">
      <header className="drawer-header"><div><span className="drawer-kicker">REQUIREMENT {row.requirement.id}</span><h2 id="drawer-title">{row.requirement.title}</h2><p id="review-modal-description" className="detail-muted">Compare the documents, record your decision, and verify any correction separately.</p><div className="drawer-header-badges"><span className={'badge badge-result badge-' + (row.deterministic?.status ?? 'reference_missing')}>{RESULT_LABELS[row.deterministic?.status ?? 'reference_missing']}</span>{rowSeverity(row) && <span className={'badge badge-severity badge-' + rowSeverity(row)}>{rowSeverity(row)} severity</span>}</div></div><button ref={closeRef} type="button" className="icon-button" aria-label="Close details" disabled={saving} onClick={onClose}><X size={20}/></button></header>
      <div className="drawer-content">
        <section className="detail-section"><h3>Comparison</h3><div className="modal-values">
          <div className={'comparison-value approved-value' + (approved.value ? '' : ' value-unavailable')}><div className="value-heading">{approved.value && <CheckCircle2 size={17} aria-hidden="true"/>}<strong>APPROVED REFERENCE</strong></div><p>{approved.value ?? 'No approved reference value available'}</p>{approved.source === 'checklist' && <small>Checklist value; a source excerpt was not found.</small>}</div>
          <div className={'comparison-value submitted-value value-' + submittedTone}><div className="value-heading">{submittedTone === 'match' ? <CheckCircle2 size={17} aria-hidden="true"/> : submittedTone !== 'review' ? <AlertTriangle size={17} aria-hidden="true"/> : null}<strong>SUBMITTED VALUE</strong><span className="value-indicator">{submittedLabel}</span></div><p>{submittedTone === 'missing' ? 'No corresponding submitted value found.' : original}</p></div></div>
          <p className="detail-description">{row.deterministic?.explanation ?? 'No document comparison finding available.'}</p>
          {row.ai.length > 0 && <p className="detail-plain ai-summary"><b>AI interpretation:</b> {row.ai.map(item => item.explanation).join(' ')}{row.ai.some(item => item.uncertain) && <span className="inline-error"> Needs manual checking.</span>}</p>}
          <details className="evidence-collapse" open={(row.deterministic?.reference?.excerpt?.length ?? 0) + (row.deterministic?.submitted?.excerpt?.length ?? 0) < 450}><summary>Document excerpts and page references</summary><div className="evidence-grid">
          <div className="evidence-box"><span><FileText size={14}/> APPROVED REFERENCE {row.deterministic?.reference ? '· PAGE ' + row.deterministic.reference.page : ''}</span><p>{row.deterministic?.reference?.excerpt ?? 'No verified approved excerpt found.'}</p></div>
          <div className="evidence-box"><span><FileText size={14}/> SUBMITTED DOCUMENT {result !== 'missing' && row.deterministic?.submitted ? '· PAGE ' + row.deterministic.submitted.page : ''}</span><p>{result === 'missing' ? 'No corresponding submitted-document excerpt found.' : row.deterministic?.submitted?.excerpt ?? 'No corresponding submitted-document excerpt found.'}</p></div></div></details>
          {row.ai.length > 0 && <details className="technical-evidence"><summary>AI source evidence</summary>{row.ai.map(item => <div key={item.id} className="ai-detail"><p><b>{AI_TYPE_LABELS[item.discrepancy_type]}</b> · {item.severity} severity · {item.uncertain ? 'Needs manual checking' : 'Source verified'}</p><p>Source verified: {item.source_document} · page {item.page_number}</p><blockquote>{item.supporting_excerpt}</blockquote>{item.discrepancy_type === 'missing_clause' && <p>No submitted excerpt exists for this missing information. The approved reference supports the finding.</p>}</div>)}</details>}
        </section>
        <div className="review-workflow"><section className="detail-section review-section"><h3>Decision &amp; Correction</h3><p className="detail-muted">One decision applies to this requirement. A decision does not certify engineering compliance.</p><p className="detail-plain">Correction: <span className={'badge badge-correction tone-' + correctionState.tone}>{correctionState.label}</span></p>
          {review.ambiguous_legacy && <div className="review-warning" role="alert">Older finding decisions conflict. No final decision was assumed. Review the history below and choose a decision for this requirement.<ul>{row.deterministic && <li>Document comparison: {REVIEW_LABELS[row.deterministic.review_status]}</li>}{row.ai.map((item, index) => <li key={item.id}>AI review {index + 1}: {REVIEW_LABELS[item.review_status]}</li>)}</ul></div>}
          {row.deterministic?.status === 'match' && row.ai.length > 0 && review.status === 'pending' && <p className="review-warning">AI raised a potential issue despite a matching document comparison. Human review is needed.</p>}
          {clean ? <p className="inline-success">No review needed. The documents match and AI raised no conflicting finding.</p> : <>
            <label className="form-label">Decision<select value={decision} onChange={event => setDecision(event.target.value as ReviewStatus)}><option value="pending">Pending Review</option><option value="accepted">Confirmed issue</option><option value="rejected">Not an issue</option><option value="needs_investigation">Needs checking</option></select></label>
            <p className="detail-muted">{outcome[decision]}</p>
            <label className="form-label">Reviewer comments<textarea value={comment} maxLength={2000} rows={3} placeholder="Record the basis for this decision" onChange={event => setComment(event.target.value)}/></label>
          </>}
        </section>
        {((decision === 'accepted' && hasDiscrepancy) || current) && <section className="detail-section correction-section"><h4>Correction details</h4><p className="detail-muted">Enter the value the submitted document should use. Saving creates a draft; a person must verify it separately.</p>
          {current && <p className="correction-status">Current requirement status: {correctionState.label} · Correction updated {new Date(current.updated_at).toLocaleString()}</p>}
          {decision === 'accepted' && hasDiscrepancy && <div className="correction-panel"><h4>{current ? 'Edit correction (creates a new draft)' : 'Enter a correction'}</h4>
            <p className="detail-plain"><b>Requirement:</b> {row.requirement.id} — {row.requirement.title}</p>
            <p className="detail-plain"><b>Original submitted value:</b> {original}</p>
            <p className="detail-plain"><b>Approved reference value:</b> {approved.value ?? 'No approved reference value available'}{approved.source === 'checklist' && <small> (checklist value; source excerpt unavailable)</small>}</p>
            <label className="form-label">Corrected value<textarea maxLength={2000} rows={3} value={correctedValue} onChange={event => setCorrectedValue(event.target.value)}/></label>
            <label className="form-label">Why is this correction needed?<textarea maxLength={2000} rows={2} value={reason} placeholder="Explain the difference from the approved requirement" onChange={event => setReason(event.target.value)}/></label>
            <label className="form-label">Supporting reference or notes<textarea maxLength={2000} rows={2} value={notes} onChange={event => setNotes(event.target.value)}/></label>
            <label className="form-label">Field or section name<input maxLength={120} value={fieldName} onChange={event => setFieldName(event.target.value)}/></label>
          </div>}
        </section>}</div>
        {current && decision === 'accepted' && <section className="detail-section verification-section"><h3>Correction approval</h3><p className="detail-muted">Approving a correction means you accept the proposed value. It does not certify engineering compliance. Approval is a separate human action.</p><label className="form-label">Reviewer note<input maxLength={2000} value={verificationNote} onChange={event => setVerificationNote(event.target.value)}/></label>{current.status === 'pending_verification' && <button type="button" className="secondary-button" disabled={saving} onClick={() => changeStatus('rejected')}>Reject Correction</button>}{current.status === 'rejected' && <p className="review-warning">This correction was rejected. Edit it above to create a new draft.</p>}{current.status === 'verified' && <p className="inline-success">Correction Approved{current.verified_at ? ' ' + new Date(current.verified_at).toLocaleString() : ''}. This is a human approval record, not engineering compliance certification.</p>}</section>}
        <section className="detail-section"><h3>History</h3><details className="history-details" open={events.length < 4}><summary>Review and revision history ({events.length} events)</summary>{events.length ? <ol className="audit-list">{events.map(event => <li key={event.id}><time>{new Date(event.occurred_at).toLocaleString()}</time><strong>{auditActionLabel(event)}</strong>{auditTransitionLabel(event) && <p>{auditTransitionLabel(event)}</p>}{event.action === 'review_updated' && <p>Historical finding-level decision</p>}{event.comment && <p>{event.comment}</p>}</li>)}</ol> : <p className="detail-muted">No review or correction events recorded yet.</p>}
          {corrections.filter(item => item.requirement_id === row.key).map(item => <p key={item.id} className="detail-muted">Correction {new Date(item.created_at).toLocaleString()}: {item.corrected_value} · {CORRECTION_LABELS[item.status]}{item.superseded_at ? ' · replaced by a newer draft' : ''}</p>)}
          {revisions.filter(item => item.correction_ids.some(id => corrections.some(correction => correction.id === id && correction.requirement_id === row.key))).map(item => <p key={item.id} className="detail-muted">Revision {item.number} · {item.status === 'verified' ? 'Verified Revision' : 'Draft Revision'} · {new Date(item.created_at).toLocaleString()}</p>)}
        </details></section>
      </div>
      <footer className="review-modal-footer"><div className="modal-feedback" aria-live="polite">{saving && <span className="action-progress"><span className="spinner"/> {progress}</span>}{message && <span className="inline-success">{message}</span>}{error && <span className="inline-error" role="alert">{error}</span>}{refreshNeeded && <button type="button" className="row-action" disabled={saving} onClick={() => void retryRefresh()}>Retry refresh</button>}</div>{!clean && !refreshNeeded && (reviewChanged || wantsCorrection) ? <button type="button" className="primary-button" disabled={saving} onClick={() => void saveDecision()}>{saving ? 'Saving...' : wantsCorrection ? reviewChanged ? 'Save decision and draft' : 'Save draft correction' : decision === 'accepted' ? 'Confirm issue' : 'Save decision'}</button> : !clean && !refreshNeeded && decision === 'accepted' && current?.status === 'draft' ? <button type="button" className="primary-button" disabled={saving} onClick={() => changeStatus('pending_verification')}>Send for verification</button> : !clean && !refreshNeeded && decision === 'accepted' && current?.status === 'pending_verification' ? <button type="button" className="primary-button" disabled={saving} onClick={() => changeStatus('verified')}>Approve Correction</button> : <button type="button" className="secondary-button" disabled={saving} onClick={onClose}>Close</button>}</footer>
    </section>
  </div>
}
