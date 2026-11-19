import { useEffect, useMemo, useState } from 'react'
import { ChevronLeft, ChevronRight, Search, SlidersHorizontal } from 'lucide-react'
import type { Comparison, Correction, RequirementRow, ReviewDisplay, ReviewStatus } from '../types'
import { CORRECTION_DISPLAY_LABELS, correctionDisplay, mergeRequirements, RESULT_LABELS, REVIEW_DISPLAY_LABELS, REVIEW_LABELS, rowReviewStatus, rowSeverity } from '../types'

const PAGE_SIZE = 10
const severityPriority = { high: 0, medium: 1, unknown: 2, low: 3, none: 4 }
const resultPriority = { missing: 0, different: 1, reference_missing: 2, match: 3 }

function badge(value: string, family: 'result' | 'severity' | 'review') {
  const label = family === 'result' ? RESULT_LABELS[value as keyof typeof RESULT_LABELS]
    : family === 'review' ? REVIEW_DISPLAY_LABELS[value as ReviewDisplay]
    : value === 'none' ? '—' : value.charAt(0).toUpperCase() + value.slice(1)
  return <span className={`badge badge-${family} badge-${value}`}>{label}</span>
}

export default function ResultsTable({ comparison, corrections, onOpen }: { comparison: Comparison; corrections: Correction[]; onOpen: (row: RequirementRow) => void }) {
  const [query, setQuery] = useState('')
  const [resultFilter, setResultFilter] = useState('all')
  const [severityFilter, setSeverityFilter] = useState('all')
  const [reviewFilter, setReviewFilter] = useState('all')
  const [workflowFilter, setWorkflowFilter] = useState('all')
  const [correctionFilter, setCorrectionFilter] = useState('all')
  const [sort, setSort] = useState('priority')
  const [page, setPage] = useState(1)
  useEffect(() => { setPage(1) }, [query, resultFilter, severityFilter, reviewFilter, workflowFilter, correctionFilter, sort, comparison.session_id])

  const rows = useMemo(() => {
    const term = query.trim().toLocaleLowerCase()
    return mergeRequirements(comparison).filter(row => {
      const result = row.deterministic?.status ?? 'reference_missing'
      const severity = rowSeverity(row) ?? 'none'
      const review = rowReviewStatus(comparison, row)
      const submitted = row.deterministic?.submitted?.excerpt ?? ''
      const correction = correctionDisplay(comparison, row, corrections)
      const workflowMatch = workflowFilter === 'all'
        || (workflowFilter === 'pending' && ['pending', 'needs_review', 'legacy_conflict'].includes(review))
        || (workflowFilter === 'confirmed' && review === 'accepted')
        || (workflowFilter === 'needs_correction' && ['needs_correction', 'correction_rejected'].includes(correction.status))
        || (workflowFilter === 'corrected' && correction.status === 'verified')
        || (workflowFilter === 'needs_checking' && review === 'needs_investigation')
      return (!term || [row.requirement.id, row.requirement.title, row.requirement.reference_text, submitted].some(text => text.toLocaleLowerCase().includes(term)))
        && workflowMatch
        && (correctionFilter === 'all' || correction.status === correctionFilter)
        && (resultFilter === 'all' || result === resultFilter)
        && (severityFilter === 'all' || severity === severityFilter)
        && (reviewFilter === 'all' || review === reviewFilter)
    }).sort((a, b) => {
      if (sort === 'name') return a.requirement.title.localeCompare(b.requirement.title)
      if (sort === 'id') return a.requirement.id.localeCompare(b.requirement.id)
      if (sort === 'result') return resultPriority[a.deterministic?.status ?? 'reference_missing'] - resultPriority[b.deterministic?.status ?? 'reference_missing']
      if (sort === 'review') return rowReviewStatus(comparison, a).localeCompare(rowReviewStatus(comparison, b))
      const priority = severityPriority[rowSeverity(a) ?? 'none'] - severityPriority[rowSeverity(b) ?? 'none']
      return priority || resultPriority[a.deterministic?.status ?? 'reference_missing'] - resultPriority[b.deterministic?.status ?? 'reference_missing'] || a.requirement.id.localeCompare(b.requirement.id)
    })
  }, [comparison, corrections, query, resultFilter, severityFilter, reviewFilter, workflowFilter, correctionFilter, sort])
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE))
  const shown = rows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  return <section className="results-panel" aria-labelledby="results-title">
    <div className="panel-header results-heading"><div><h2 id="results-title">Requirement results</h2><p>One row per requirement. Open details to see full approved and submitted values and AI evidence.</p></div><span className="panel-meta">{comparison.requirements.length} requirements</span></div>
    <div className="workflow-filter"><label>Show <select aria-label="Filter by workflow" value={workflowFilter} onChange={event => setWorkflowFilter(event.target.value)}><option value="all">All findings</option><option value="pending">Pending Review</option><option value="confirmed">Confirmed issues</option><option value="needs_correction">Needs correction</option><option value="corrected">Corrected</option><option value="needs_checking">Needs checking</option></select></label><label>Correction <select aria-label="Filter by correction status" value={correctionFilter} onChange={event => setCorrectionFilter(event.target.value)}><option value="all">All correction statuses</option>{Object.entries(CORRECTION_DISPLAY_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label></div>
    <div className="table-toolbar"><label className="search-field"><Search size={17} aria-hidden="true"/><input aria-label="Search requirements" value={query} onChange={event => setQuery(event.target.value)} placeholder="Search requirements or values"/></label><div className="filter-group"><SlidersHorizontal size={16} aria-hidden="true"/><select aria-label="Filter by result" value={resultFilter} onChange={event => setResultFilter(event.target.value)}><option value="all">All results</option><option value="missing">Missing</option><option value="different">Different</option><option value="match">Match</option><option value="reference_missing">Check reference</option></select><select aria-label="Filter by severity" value={severityFilter} onChange={event => setSeverityFilter(event.target.value)}><option value="all">All severities</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option><option value="unknown">Unknown</option><option value="none">No AI severity</option></select><select aria-label="Filter by review status" value={reviewFilter} onChange={event => setReviewFilter(event.target.value)}><option value="all">All review statuses</option>{(Object.keys(REVIEW_LABELS) as ReviewStatus[]).map(value => <option key={value} value={value}>{REVIEW_LABELS[value]}</option>)}<option value="no_review_needed">No review needed</option><option value="needs_review">Needs review</option><option value="legacy_conflict">Legacy decisions need review</option></select><select aria-label="Sort requirements" value={sort} onChange={event => setSort(event.target.value)}><option value="priority">High priority first</option><option value="id">Requirement ID</option><option value="name">Requirement name</option><option value="result">Comparison result</option><option value="review">Review status</option></select></div></div>
    {rows.length === 0 ? <div className="table-empty"><strong>No requirements match these filters.</strong><p>Adjust the search or filters to see more results.</p><button type="button" onClick={() => { setQuery(''); setResultFilter('all'); setSeverityFilter('all'); setReviewFilter('all'); setCorrectionFilter('all') }}>Clear filters</button></div> : <div className="table-scroll"><table className="results-table"><thead><tr><th scope="col">ID</th><th scope="col">Requirement</th><th scope="col">Result</th><th scope="col">Severity</th><th scope="col">Human review</th><th scope="col">Correction</th><th scope="col">Actions</th></tr></thead><tbody>{shown.map(row => {
      const finding = row.deterministic
      const review = rowReviewStatus(comparison, row)
      const correction = correctionDisplay(comparison, row, corrections)
      return <tr key={row.key} onClick={() => onOpen(row)}><td data-label="ID" className="table-id">{row.requirement.id}</td><td data-label="Requirement" className="table-name"><strong>{row.requirement.title}</strong>{row.ai.length > 0 && <small>{row.ai.length} AI review{row.ai.length > 1 ? 's' : ''}</small>}</td><td data-label="Result">{badge(finding?.status ?? 'reference_missing', 'result')}</td><td data-label="Severity">{badge(rowSeverity(row) ?? 'none', 'severity')}</td><td data-label="Human review">{badge(review, 'review')}</td><td data-label="Correction"><span className={'badge badge-correction tone-' + correction.tone}>{correction.label}</span></td><td data-label="Actions"><button type="button" className="row-action" aria-label={`View details for ${row.requirement.id}`} onClick={event => { event.stopPropagation(); onOpen(row) }}>View details</button></td></tr>
    })}</tbody></table></div>}
    <div className="table-footer"><span>{rows.length ? `${(page - 1) * PAGE_SIZE + 1}–${Math.min(page * PAGE_SIZE, rows.length)} of ${rows.length}` : '0 results'}</span><div className="pagination"><button type="button" aria-label="Previous page" disabled={page <= 1} onClick={() => setPage(value => value - 1)}><ChevronLeft size={16}/></button><span>Page {page} of {pages}</span><button type="button" aria-label="Next page" disabled={page >= pages} onClick={() => setPage(value => value + 1)}><ChevronRight size={16}/></button></div></div>
  </section>
}
