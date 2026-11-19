import { useEffect, useMemo, useRef, useState } from 'react'
import { Activity, ArrowRight, CheckCircle2, ClipboardList, Clock3, FileClock, FilePlus2, FileText, History, Info, LayoutDashboard, RefreshCw, ShieldCheck } from 'lucide-react'
import { createComparison, downloadPdf, generateRevision, getComparison, listComparisons, listCorrections, listRevisions, reportUrl, revisionUrl } from './api'
import Brand from './components/Brand'
import ResultsTable from './components/ResultsTable'
import ReviewDrawer from './components/ReviewDrawer'
import SetupPanel from './components/SetupPanel'
import type { Comparison, Correction, Requirement, RequirementReviewUpdate, Revision, SessionSummary } from './types'
import { mergeRequirements, rowReviewStatus } from './types'
import { applyReviewUpdate } from './lib/reviewUpdate'
import { loadSamplePdf, matchesSampleRequirements, requiresSampleOverwriteConfirmation, SAMPLE_REQUIREMENTS } from './lib/samples'
import type { SampleRole } from './lib/samples'

type View = 'overview' | 'review' | 'history'
const navigation: { id: View; label: string; icon: typeof LayoutDashboard }[] = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'review', label: 'Document Review', icon: ClipboardList },
  { id: 'history', label: 'Comparison History', icon: History },
]
const dateLabel = (value: string | null) => value ? new Date(value).toLocaleString() : '—'

function App() {
  const [view, setView] = useState<View>('review')
  const [reference, setReference] = useState<File | null>(null)
  const [submitted, setSubmitted] = useState<File | null>(null)
  const [requirements, setRequirements] = useState<Requirement[]>(SAMPLE_REQUIREMENTS)
  const [referenceSource, setReferenceSource] = useState<'sample' | 'user' | null>(null)
  const [submittedSource, setSubmittedSource] = useState<'sample' | 'user' | null>(null)
  const [sampleLoading, setSampleLoading] = useState<SampleRole | 'both' | null>(null)
  const [sampleError, setSampleError] = useState('')
  const [lastSampleAction, setLastSampleAction] = useState<SampleRole | 'both' | null>(null)
  const sampleLoadingRef = useRef(false)
  const [mode, setMode] = useState<'deterministic' | 'ai'>('deterministic')
  const [forceRefresh, setForceRefresh] = useState(false)
  const [comparison, setComparison] = useState<Comparison | null>(null)
  const [corrections, setCorrections] = useState<Correction[]>([])
  const [revisions, setRevisions] = useState<Revision[]>([])
  const [revisionBusy, setRevisionBusy] = useState(false)
  const [revisionRefreshNeeded, setRevisionRefreshNeeded] = useState(false)
  const [openingSessionId, setOpeningSessionId] = useState<string | null>(null)
  const [failedSessionId, setFailedSessionId] = useState<string | null>(null)
  const [downloadBusy, setDownloadBusy] = useState<string | null>(null)
  const openingRef = useRef(false)
  const comparingRef = useRef(false)
  const revisionRef = useRef(false)
  const downloadRef = useRef(false)
  const [history, setHistory] = useState<SessionSummary[]>([])
  const [historyLoading, setHistoryLoading] = useState(true)
  const [historyError, setHistoryError] = useState('')
  const [historyQuery, setHistoryQuery] = useState('')
  const [busy, setBusy] = useState<'comparing' | 'loading' | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const selectedRow = useMemo(() => comparison && selectedKey ? mergeRequirements(comparison).find(row => row.key === selectedKey) ?? null : null, [comparison, selectedKey])
  const sampleReady = referenceSource === 'sample' && submittedSource === 'sample' && matchesSampleRequirements(requirements)

  const selectReference = (file: File | null) => { if (!sampleLoadingRef.current) { setReference(file); setReferenceSource(file ? 'user' : null); setSampleError('') } }
  const selectSubmitted = (file: File | null) => { if (!sampleLoadingRef.current) { setSubmitted(file); setSubmittedSource(file ? 'user' : null); setSampleError('') } }
  const loadSamples = async (action: SampleRole | 'both') => {
    if (sampleLoadingRef.current || comparingRef.current) return
    const replacesWork = requiresSampleOverwriteConfirmation(action, referenceSource, submittedSource, requirements)
    if (replacesWork && !window.confirm('This will replace your current document or checklist entries. Continue?')) return
    sampleLoadingRef.current = true; setSampleLoading(action); setSampleError(''); setLastSampleAction(action)
    try {
      if (action === 'both') {
        const [approved, submittedSample] = await Promise.all([loadSamplePdf('reference'), loadSamplePdf('submitted')])
        setReference(approved); setSubmitted(submittedSample)
        setReferenceSource('sample'); setSubmittedSource('sample')
        setRequirements(SAMPLE_REQUIREMENTS.map(item => ({ ...item })))
        setMode('ai'); setForceRefresh(false)
      } else {
        const file = await loadSamplePdf(action)
        if (action === 'reference') { setReference(file); setReferenceSource('sample') }
        else { setSubmitted(file); setSubmittedSource('sample') }
      }
    } catch (cause) { setSampleError(cause instanceof Error ? cause.message : 'Could not load the sample PDF. Please try again.') }
    finally { sampleLoadingRef.current = false; setSampleLoading(null) }
  }

  const reloadHistory = async () => {
    setHistoryLoading(true); setHistoryError('')
    try { setHistory(await listComparisons()) }
    catch (cause) { setHistoryError(cause instanceof Error ? cause.message : 'Could not load comparison history.') }
    finally { setHistoryLoading(false) }
  }
  useEffect(() => { void reloadHistory() }, [])
  const refreshRevisionData = async (sessionId: string) => {
    const [nextCorrections, nextRevisions] = await Promise.all([listCorrections(sessionId, true), listRevisions(sessionId)])
    setCorrections(nextCorrections); setRevisions(nextRevisions)
  }
  useEffect(() => {
    if (!comparison?.session_id) { setCorrections([]); setRevisions([]); return }
    void refreshRevisionData(comparison.session_id).catch(cause => setError(cause instanceof Error ? cause.message : 'Could not load corrections.'))
  }, [comparison?.session_id])

  const runComparison = async () => {
    if (comparingRef.current || sampleLoadingRef.current) return
    setError(''); setNotice('')
    if (!reference || !submitted) { setError('Upload both PDF documents.'); return }
    if (requirements.length === 0 || requirements.some(item => !item.id.trim() || !item.title.trim() || !item.reference_text.trim())) { setError('Complete at least one checklist requirement.'); return }
    if ([reference, submitted].some(file => file.size > 10 * 1024 * 1024 || !file.name.toLowerCase().endsWith('.pdf'))) { setError('Choose PDF files smaller than 10 MB.'); return }
    comparingRef.current = true; setBusy('comparing')
    try {
      const result = await createComparison(reference, submitted, requirements, mode, forceRefresh)
      setComparison(result); setSelectedKey(null); setRevisionRefreshNeeded(false); setView('review')
      setNotice(result.cache_hit ? 'Comparison saved. Validated AI analysis was reused from cache.' : 'Comparison completed and saved.')
      void reloadHistory()
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'The comparison could not be completed.') }
    finally { comparingRef.current = false; setBusy(null) }
  }
  const openSession = async (sessionId: string) => {
    if (openingRef.current) return
    openingRef.current = true; setOpeningSessionId(sessionId); setFailedSessionId(null); setError(''); setNotice('')
    try { const saved = await getComparison(sessionId); setComparison(saved); setSelectedKey(null); setRevisionRefreshNeeded(false); setView('review'); setNotice('Saved comparison loaded.') }
    catch (cause) { setFailedSessionId(sessionId); setError(cause instanceof Error ? cause.message : 'Could not open comparison.') }
    finally { openingRef.current = false; setOpeningSessionId(null) }
  }
  const refreshReview = async () => { if (comparison?.session_id) {
    const sessionId = comparison.session_id
    const [updated] = await Promise.all([getComparison(sessionId), refreshRevisionData(sessionId)])
    setComparison(updated)
  } }
  const onReviewSaved = (update: RequirementReviewUpdate) => {
    setComparison(current => current ? applyReviewUpdate(current, update) : current)
  }
  const createRevision = async () => {
    if (!comparison?.session_id || revisionRef.current) return
    revisionRef.current = true
    setRevisionBusy(true); setError(''); setRevisionRefreshNeeded(false)
    try {
      const revision = await generateRevision(comparison.session_id)
      try { await refreshReview() }
      catch { setRevisionRefreshNeeded(true); setError('The revised PDF was generated, but the list could not be refreshed. Retry refresh before generating another revision.'); return }
      setNotice((revision.status === 'verified' ? 'Verified' : 'Draft') + ' structured revision ' + revision.number + ' generated. Download it below.')
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not generate revision.') }
    finally { revisionRef.current = false; setRevisionBusy(false) }
  }
  const retryRevisionRefresh = async () => {
    if (revisionRef.current) return
    revisionRef.current = true; setRevisionBusy(true); setError('')
    try { await refreshReview(); setRevisionRefreshNeeded(false); setNotice('Revised document list updated.') }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not refresh revisions. Please try again.') }
    finally { revisionRef.current = false; setRevisionBusy(false) }
  }
  const startDownload = async (key: string, path: string, filename: string) => {
    if (downloadRef.current) return
    downloadRef.current = true; setDownloadBusy(key); setError(''); setNotice('')
    try { await downloadPdf(path, filename); setNotice('PDF download started.') }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not download the PDF. Please try again.') }
    finally { downloadRef.current = false; setDownloadBusy(null) }
  }
  const historyMatches = history.filter(item => [item.reference_name, item.submitted_name, item.session_id]
    .some(value => value.toLocaleLowerCase().includes(historyQuery.trim().toLocaleLowerCase())))
  const reviewRows = comparison ? mergeRequirements(comparison) : []
  const currentCounts = comparison ? {
    match: reviewRows.filter(row => rowReviewStatus(comparison, row) === 'no_review_needed').length,
    issues: reviewRows.filter(row => !['no_review_needed', 'rejected'].includes(rowReviewStatus(comparison, row))).length,
    pending: reviewRows.filter(row => ['pending', 'needs_review', 'legacy_conflict', 'needs_investigation'].includes(rowReviewStatus(comparison, row))).length,
  } : null

  return <div className="app-shell">
    <aside className="sidebar"><div className="sidebar-brand"><Brand/></div><div className="sidebar-section">WORKSPACE</div><nav className="side-nav" aria-label="Primary navigation">{navigation.map(item => {
      const Icon = item.icon
      return <button key={item.id} type="button" className={view === item.id ? 'active' : ''} aria-current={view === item.id ? 'page' : undefined} onClick={() => { setView(item.id); setError(''); setNotice('') }}><Icon size={18}/><span>{item.label}</span></button>
    })}</nav><div className="sidebar-bottom"><div className="sidebar-rule"/><div className="sidebar-support"><ShieldCheck size={17}/><span>Review support only<br/><small>Human verification required</small></span></div><small className="sidebar-version">DOCWISE · LOCAL WORKSPACE</small></div></aside>
    <div className="workspace"><header className="topbar"><div className="mobile-brand"><Brand compact/></div><div className="breadcrumbs"><span>Workspace</span><span aria-hidden="true">/</span><strong>{navigation.find(item => item.id === view)?.label}</strong></div><div className="topbar-right"><span className="workspace-indicator"><span/> Local workspace</span></div></header>
      <div className="mobile-nav" aria-label="Mobile navigation">{navigation.map(item => <button key={item.id} type="button" className={view === item.id ? 'active' : ''} onClick={() => setView(item.id)}>{item.label}</button>)}</div>
      <main className="main-content">
        <div className="page-heading"><div><div className="eyebrow">DOCUMENT QUALITY ASSURANCE</div><h1>{view === 'review' ? 'Document Review' : view === 'history' ? 'Comparison History' : 'Overview'}</h1><p>{view === 'review' ? 'Compare approved requirements with submitted documents and record human decisions.' : view === 'history' ? 'Reopen saved comparisons and review their current findings.' : 'Track recent document reviews and return to work.'}</p></div>{view !== 'review' && <button type="button" className="primary-button heading-action" onClick={() => setView('review')}><FilePlus2 size={17}/> New comparison</button>}</div>
        {error && <div className="message error" role="alert"><Info size={17}/>{error}{failedSessionId && <button type="button" className="message-retry" disabled={!!openingSessionId} onClick={() => void openSession(failedSessionId)}>Retry opening</button>}</div>}
        {view === 'overview' && <><div className="overview-metrics"><div><span><FileText size={17}/> Recent comparisons</span><strong>{history.length}</strong><small>Up to 100 saved sessions</small></div><div><span><Activity size={17}/> AI-assisted</span><strong>{history.filter(item => item.mode === 'ai').length}</strong><small>Among recent sessions</small></div><div><span><RefreshCw size={17}/> Cache reuses</span><strong>{history.filter(item => item.cache_hit).length}</strong><small>No new Groq usage on reuse</small></div></div>
          <section className="surface"><div className="panel-header"><div><h2>Recent activity</h2><p>Open a comparison to continue reviewing.</p></div><button className="quiet-button" type="button" onClick={() => setView('history')}>View history <ArrowRight size={15}/></button></div>
            {historyLoading ? <div className="state-panel" role="status">Loading recent comparisons…</div> : historyError ? <div className="state-panel error-text" role="alert">{historyError} <button type="button" onClick={() => void reloadHistory()}>Retry</button></div> : history.length ? <div className="activity-list">{history.slice(0, 5).map(item => <button key={item.session_id} type="button" disabled={!!openingSessionId} onClick={() => void openSession(item.session_id)}><span className="activity-icon"><FileClock size={18}/></span><span className="activity-title"><strong>{item.reference_name} → {item.submitted_name}</strong><small>{item.mode === 'ai' ? 'AI-Assisted' : 'Deterministic'}{item.cache_hit ? ' · Cache reused' : ''}</small></span><time>{dateLabel(item.created_at)}</time>{openingSessionId === item.session_id ? <span className="action-progress" role="status"><span className="spinner"/> Opening...</span> : <ArrowRight size={16}/>}</button>)}</div> : <div className="state-panel"><strong>No comparisons yet</strong><p>Create your first document review to see activity here.</p><button type="button" onClick={() => setView('review')}>Start a review</button></div>}</section>
        </>}
        {view === 'history' && <section className="surface"><div className="panel-header"><div><h2>Saved comparisons</h2><p>Previous sessions retain findings, reviews, and audit history.</p></div><span className="panel-meta">{history.length} recent sessions</span></div><div className="history-search"><input aria-label="Search comparison history" value={historyQuery} onChange={event => setHistoryQuery(event.target.value)} placeholder="Search document names or session ID"/></div>
          {historyLoading ? <div className="state-panel" role="status">Loading comparison history…</div> : historyError ? <div className="state-panel error-text" role="alert">{historyError} <button type="button" onClick={() => void reloadHistory()}>Retry</button></div> : historyMatches.length ? <div className="history-table-wrap"><table className="history-table"><thead><tr><th scope="col">Documents</th><th scope="col">Date</th><th scope="col">Mode</th><th scope="col">AI source</th><th scope="col">Action</th></tr></thead><tbody>{historyMatches.map(item => <tr key={item.session_id}><td><strong>{item.reference_name}</strong><small>Compared with {item.submitted_name}</small></td><td>{dateLabel(item.created_at)}</td><td>{item.mode === 'ai' ? 'AI-Assisted' : 'Deterministic'}</td><td>{item.mode === 'ai' ? (item.cache_hit ? 'Cached' : 'Fresh / unavailable') : '—'}</td><td><button type="button" className="row-action" disabled={!!openingSessionId} onClick={() => void openSession(item.session_id)}>{openingSessionId === item.session_id ? <span className="action-progress" role="status"><span className="spinner"/> Opening...</span> : 'Open review'}</button></td></tr>)}</tbody></table></div> : <div className="state-panel"><strong>No matching comparisons</strong><p>{history.length ? 'Try another search term.' : 'Run a comparison to create a saved session.'}</p></div>}</section>}
        {view === 'review' && <><SetupPanel reference={reference} submitted={submitted} onReference={selectReference} onSubmitted={selectSubmitted} requirements={requirements} onRequirements={setRequirements} mode={mode} onMode={setMode} forceRefresh={forceRefresh} onForceRefresh={setForceRefresh} loading={busy === 'comparing'} onCompare={() => void runComparison()} sampleLoading={sampleLoading} sampleError={sampleError} sampleReady={sampleReady} lastSampleAction={lastSampleAction} onLoadSample={action => void loadSamples(action)}/>
          {notice && <div className="message success" role="status"><CheckCircle2 size={17}/>{notice}</div>}
          {busy && <div className="state-panel progress" role="status"><span className="spinner"/>{busy === 'comparing' ? 'Comparing PDFs and saving results…' : 'Loading saved comparison…'}</div>}
          {comparison && !busy && <div className="comparison-area"><div className="comparison-header"><div><div className="eyebrow">SAVED COMPARISON</div><h2>{comparison.reference_name} <span>vs.</span> {comparison.submitted_name}</h2><p>{dateLabel(comparison.created_at)} · {comparison.mode === 'ai' ? 'AI-Assisted' : 'Deterministic'} · Session {comparison.session_id?.slice(0, 8)}</p></div>{comparison.session_id && <button type="button" className="secondary-button" disabled={!!downloadBusy} onClick={() => void startDownload('report', reportUrl(comparison.session_id!), `docwise-report-${comparison.session_id!.slice(0, 8)}.pdf`)}><FileText size={16}/>{downloadBusy === 'report' ? <span className="action-progress"><span className="spinner"/> Preparing PDF...</span> : 'Download PDF report'}</button>}</div>
            <div className="summary-strip"><div><strong>{comparison.requirements.length}</strong><span>Requirements</span></div><div><strong>{currentCounts?.match}</strong><span>Matches</span></div><div><strong>{currentCounts?.issues}</strong><span>Need attention</span></div><div><strong>{currentCounts?.pending}</strong><span>Open reviews</span></div></div>
            <div className="analysis-meta"><span>{comparison.cache_hit ? 'AI analysis reused from cache · no new API usage' : comparison.mode === 'ai' ? `AI status: ${comparison.ai_status.replaceAll('_', ' ')}` : 'Document comparison'}</span>{comparison.usage && <span>{comparison.usage.total_tokens.toLocaleString()} new Groq tokens{comparison.estimated_cost_usd === null ? '' : ` · Estimated $${comparison.estimated_cost_usd.toFixed(6)}`}</span>}</div>
            {comparison.ai_message && <div className="message info" role="status"><Info size={16}/>{comparison.ai_message}</div>}
            <ResultsTable comparison={comparison} corrections={corrections} onOpen={row => setSelectedKey(row.key)}/>
            {comparison.session_id && <section className="surface revision-section"><div className="panel-header"><div><h2>Structured revisions</h2><p>Generate a draft from entered corrections. A verified revision requires explicit human verification of all included corrections. Neither status is engineering approval.</p></div></div><div className="revision-actions"><button type="button" className="secondary-button" disabled={revisionBusy || revisionRefreshNeeded || !corrections.some(item => !item.superseded_at && item.status !== 'rejected')} onClick={() => void createRevision()}>{revisionBusy ? <span className="action-progress"><span className="spinner"/> {revisionRefreshNeeded ? 'Refreshing...' : 'Generating...'}</span> : 'Generate revised document'}</button>{revisionRefreshNeeded && <button type="button" className="row-action" disabled={revisionBusy} onClick={() => void retryRevisionRefresh()}>Retry refresh</button>}<span className="detail-muted">The uploaded PDF remains unchanged.</span></div><div className="revision-list">{revisions.map(item => <button key={item.id} type="button" className="secondary-button" disabled={!!downloadBusy} onClick={() => void startDownload(item.id, revisionUrl(comparison.session_id!, item.id), `docwise-revision-${item.number}.pdf`)}>{downloadBusy === item.id ? <span className="action-progress"><span className="spinner"/> Preparing PDF...</span> : `Revised Document ${item.number} · ${item.status === 'verified' ? 'Verified Revision' : 'Draft Revision'}`}</button>)}</div></section>}
            <p className="compliance-footer"><ShieldCheck size={16}/> Review decisions do not certify engineering compliance. AI findings require qualified human verification.</p>
          </div>}
          {!comparison && !busy && <div className="state-panel waiting"><Clock3 size={20}/><strong>No comparison selected</strong><p>Run a new comparison above or open a saved session from Comparison History.</p></div>}
        </>}
      </main>
    </div>
    {comparison && selectedRow && <ReviewDrawer comparison={comparison} row={selectedRow} corrections={corrections} revisions={revisions} onClose={() => setSelectedKey(null)} onSaved={refreshReview} onReviewSaved={onReviewSaved}/>}
  </div>
}

export default App
