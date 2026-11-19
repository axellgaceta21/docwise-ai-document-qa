const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const Module = require('node:module')
const { buildSync } = require('esbuild')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')

const root = path.resolve(__dirname, '..')
function load(entry) {
  const filename = path.join(root, entry)
  const output = buildSync({ entryPoints: [filename], bundle: true, platform: 'node',
    format: 'cjs', write: false, external: ['react', 'react-dom', 'lucide-react'] }).outputFiles[0].text
  const loaded = new Module(filename, module)
  loaded.filename = filename
  loaded.paths = Module._nodeModulePaths(path.dirname(filename))
  loaded._compile(output, filename)
  return loaded.exports
}
const types = load('src/types.ts')
const ResultsTable = load('src/components/ResultsTable.tsx').default
const ReviewDrawer = load('src/components/ReviewDrawer.tsx').default
const SetupPanel = load('src/components/SetupPanel.tsx').default
const applyReviewUpdate = load('src/lib/reviewUpdate.ts').applyReviewUpdate
const api = load('src/api.ts')
const samples = load('src/lib/samples.ts')

function comparison(status = 'match', ai = []) {
  const requirement = { id: 'R-01', title: 'Design pressure', reference_text: 'Checklist: 150 kPa' }
  const finding = { id: 'finding-1', requirement_id: 'R-01', title: requirement.title,
    status, explanation: 'The values were compared.', reference: { page: 1, excerpt: 'Approved source: 150 kPa' },
    submitted: { page: 1, excerpt: 'Submitted source: 120 kPa' }, review_status: 'pending', review_comment: '' }
  return { session_id: 'session-1', created_at: '2026-01-01', reference_name: 'approved.pdf',
    submitted_name: 'submitted.pdf', reference_pages: 1, submitted_pages: 1,
    requirements: [requirement], findings: [finding], ai_findings: ai,
    requirement_reviews: [{ requirement_id: 'R-01', status: 'pending', comment: '',
      ambiguous_legacy: false, source: 'default' }], mode: 'deterministic',
    ai_status: 'not_requested', ai_message: null, ai_model: null, usage: null,
    estimated_cost_usd: null, cache_hit: false, audit_events: [] }
}
const aiIssue = { id: 'ai-1', requirement_id: 'R-01', discrepancy_type: 'semantic_difference',
  severity: 'medium', explanation: 'Potential interpretation issue.',
  source_document: 'reference', page_number: 1, supporting_excerpt: 'Approved source: 150 kPa',
  uncertain: true, citation_verified: true, review_status: 'pending', review_comment: '' }

test('clean matches show a green no-review-needed badge and no review control', () => {
  const data = comparison()
  const table = renderToStaticMarkup(React.createElement(ResultsTable, { comparison: data, corrections: [], onOpen() {} }))
  assert.match(table, /badge-review badge-no_review_needed[^>]*>No review needed/)
  const drawer = renderToStaticMarkup(React.createElement(ReviewDrawer, {
    comparison: data, row: types.mergeRequirements(data)[0], corrections: [], revisions: [],
    onClose() {}, async onSaved() {} }))
  assert.doesNotMatch(drawer, /<label class="form-label">Decision<select/)
})

test('AI evidence on a matching document still requests one human decision', () => {
  const data = comparison('match', [aiIssue])
  const table = renderToStaticMarkup(React.createElement(ResultsTable, { comparison: data, corrections: [], onOpen() {} }))
  assert.match(table, /badge-review badge-needs_review[^>]*>Needs review/)
  const drawer = renderToStaticMarkup(React.createElement(ReviewDrawer, {
    comparison: data, row: types.mergeRequirements(data)[0], corrections: [], revisions: [],
    onClose() {}, async onSaved() {} }))
  assert.equal((drawer.match(/<label class="form-label">Decision<select/g) || []).length, 1)
  assert.doesNotMatch(drawer, /<label class="form-label">Finding<select/)
})

test('legacy conflict is flagged and cannot appear as Mixed', () => {
  const data = comparison('different', [aiIssue])
  data.requirement_reviews[0].ambiguous_legacy = true
  data.requirement_reviews[0].source = 'legacy'
  const table = renderToStaticMarkup(React.createElement(ResultsTable, { comparison: data, corrections: [], onOpen() {} }))
  assert.match(table, /badge-review badge-legacy_conflict[^>]*>Needs review/)
  assert.doesNotMatch(table, />Mixed</)
})

test('correction form shows the read-only approved source value', () => {
  const data = comparison('different')
  data.requirement_reviews[0] = { requirement_id: 'R-01', status: 'accepted', comment: '',
    ambiguous_legacy: false, source: 'explicit' }
  const drawer = renderToStaticMarkup(React.createElement(ReviewDrawer, {
    comparison: data, row: types.mergeRequirements(data)[0], corrections: [], revisions: [],
    onClose() {}, async onSaved() {} }))
  assert.match(drawer, /Approved reference value:<\/b> Approved source: 150 kPa/)
  assert.match(drawer, /Corrected value<textarea/)
  assert.equal(types.approvedReferenceValue(types.mergeRequirements(data)[0]).source, 'document')
  data.findings[0].reference = null
  assert.equal(types.approvedReferenceValue(types.mergeRequirements(data)[0]).value, 'Checklist: 150 kPa')
})

test('review and audit terms have clear labels and color classes', () => {
  assert.equal(types.REVIEW_DISPLAY_LABELS.accepted, 'Confirmed issue')
  assert.equal(types.REVIEW_DISPLAY_LABELS.rejected, 'Not an issue')
  assert.equal(types.auditActionLabel({ action: 'review_updated', new_status: 'accepted' }), 'Issue confirmed')
  assert.equal(types.auditActionLabel({ action: 'review_updated', new_status: 'rejected' }), 'Marked as not an issue')
  assert.equal(types.auditActionLabel({ action: 'correction_status_changed', new_status: 'verified' }), 'Correction Approved by Reviewer')
  assert.equal(types.auditActionLabel({ action: 'revision_generated' }), 'Revised PDF generated')
  assert.equal(types.auditTransitionLabel({ action: 'review_updated', old_status: 'accepted', new_status: 'rejected' }),
    'Confirmed issue → Not an issue')
  const css = fs.readFileSync(path.join(root, 'src/styles.css'), 'utf8')
  assert.match(css, /badge-review\.badge-no_review_needed\{background:#eaf6f1/)
  assert.match(css, /badge-review\.badge-accepted\{background:#fff0ee/)
  assert.match(css, /badge-review\.badge-rejected\{background:#f1f3f7/)
  assert.match(css, /badge-review\.badge-pending[^\n]*background:#fff6e9/)
})

test('correction status follows final review and latest correction version', () => {
  const active = status => ({ id: 'c-new', requirement_id: 'R-01', status, superseded_at: null })
  const scenarios = [
    ['clean match', 'match', 'pending', [], 'not_required', 'success'],
    ['confirmed without correction', 'different', 'accepted', [], 'needs_correction', 'danger'],
    ['pending review', 'different', 'pending', [], 'awaiting_review', 'gray'],
    ['saved draft', 'different', 'accepted', [active('draft')], 'draft', 'neutral'],
    ['submitted correction', 'different', 'accepted', [active('pending_verification')], 'pending_verification', 'amber'],
    ['verified correction', 'different', 'accepted', [active('verified')], 'verified', 'success'],
    ['rejected correction', 'different', 'accepted', [active('rejected')], 'correction_rejected', 'danger'],
    ['edited verified correction', 'different', 'accepted',
      [{ ...active('verified'), id: 'c-old', superseded_at: '2026-01-02' }, active('draft')], 'draft', 'neutral'],
    ['dismissed finding', 'different', 'rejected', [active('verified')], 'not_required', 'neutral'],
  ]
  for (const [name, result, decision, corrections, status, tone] of scenarios) {
    const data = comparison(result)
    data.requirement_reviews[0].status = decision
    const display = types.correctionDisplay(data, types.mergeRequirements(data)[0], corrections)
    assert.equal(display.status, status, name)
    assert.equal(display.tone, tone, name)
    const table = renderToStaticMarkup(React.createElement(ResultsTable, {
      comparison: data, corrections, onOpen() {} }))
    assert.match(table, new RegExp('badge-correction tone-' + tone + '[^>]*>' + display.label), name)
  }
})

test('correction badge colors and filter use derived statuses', () => {
  const css = fs.readFileSync(path.join(root, 'src/styles.css'), 'utf8')
  for (const [tone, color] of [['success', '#eaf6f1'], ['neutral', '#f1f3f7'],
    ['gray', '#eef1f5'], ['amber', '#fff6e9'], ['danger', '#fff0ee']]) {
    assert.ok(css.includes('.badge-correction.tone-' + tone + '{background:' + color))
  }
  const table = renderToStaticMarkup(React.createElement(ResultsTable, {
    comparison: comparison(), corrections: [], onOpen() {} }))
  for (const label of Object.values(types.CORRECTION_DISPLAY_LABELS)) assert.ok(table.includes(label))
  assert.doesNotMatch(table, /Not started/)
})

test('confirmed save updates only the requirement decision and appends its persisted audit event', () => {
  const original = comparison('different')
  const event = { id: 'event-1', finding_id: null, action: 'requirement_review_updated',
    old_status: 'pending', new_status: 'accepted', comment: 'checked', detail: 'R-01', occurred_at: '2026-01-01' }
  const update = { requirement_id: 'R-01', status: 'accepted', comment: 'checked',
    source: 'explicit', ambiguous_legacy: false, audit_event: event }
  const saved = applyReviewUpdate(original, update)
  assert.equal(types.rowReviewStatus(saved, types.mergeRequirements(saved)[0]), 'accepted')
  assert.equal(saved.audit_events[0].id, event.id)
  assert.equal(saved.findings, original.findings)
  assert.equal(original.requirement_reviews[0].status, 'pending')
  assert.equal(applyReviewUpdate(saved, update).audit_events.length, 1)
})

test('review API sends one credentialed request and reports service errors for retry', async () => {
  const previous = global.fetch
  const previousInfo = console.info
  const calls = []
  console.info = () => {}
  try {
    global.fetch = async (url, options) => {
      calls.push({ url, options })
      return new Response(JSON.stringify({ requirement_id: 'R-01', status: 'accepted', comment: '',
        source: 'explicit', ambiguous_legacy: false, audit_event: { id: 'event-1' } }),
      { status: 200, headers: { 'Content-Type': 'application/json', 'Server-Timing': 'review_db;dur=12' } })
    }
    const saved = await api.saveRequirementReview('session-1', 'R-01', 'accepted', '')
    assert.equal(saved.status, 'accepted')
    assert.equal(calls.length, 1)
    assert.equal(calls[0].options.credentials, 'include')
    global.fetch = async () => new Response('Service unavailable', { status: 503 })
    await assert.rejects(api.saveRequirementReview('session-1', 'R-01', 'accepted', ''), /server could not complete/)
    global.fetch = async () => new Response('', { status: 429 })
    await assert.rejects(api.saveRequirementReview('session-1', 'R-01', 'accepted', ''), /Too many requests/)
  } finally { global.fetch = previous; console.info = previousInfo }
})

test('drawer keeps summary visible and collapses long evidence; table wraps on desktop', () => {
  const data = comparison('different', [aiIssue])
  data.findings[0].reference.excerpt = 'A'.repeat(500)
  const drawer = renderToStaticMarkup(React.createElement(ReviewDrawer, {
    comparison: data, row: types.mergeRequirements(data)[0], corrections: [], revisions: [],
    onClose() {}, async onSaved() {} }))
  assert.match(drawer, /drawer-header-badges/)
  assert.match(drawer, /<details class="evidence-collapse"/)
  assert.doesNotMatch(drawer, /<details class="evidence-collapse" open=""/)
  const css = fs.readFileSync(path.join(root, 'src/styles.css'), 'utf8')
  assert.match(css, /@media\(min-width:801px\)\{\s*\.results-table\{min-width:0/)
  assert.match(css, /\.results-table \.cell-truncate\{white-space:normal/)
})

test('centered modal is labelled, keeps the save action visible, and prepopulates an approved correction', () => {
  const data = comparison('different')
  data.requirement_reviews[0] = { requirement_id: 'R-01', status: 'accepted', comment: '',
    ambiguous_legacy: false, source: 'explicit' }
  const html = renderToStaticMarkup(React.createElement(ReviewDrawer, {
    comparison: data, row: types.mergeRequirements(data)[0], corrections: [], revisions: [],
    onClose() {}, async onSaved() {} }))
  assert.match(html, /class="review-modal" role="dialog" aria-modal="true" aria-labelledby="drawer-title" aria-describedby="review-modal-description"/)
  assert.match(html, /<strong>APPROVED REFERENCE<\/strong><\/div><p>Approved source: 150 kPa/)
  assert.match(html, /<strong>SUBMITTED VALUE<\/strong><span class="value-indicator">Different<\/span><\/div><p>Submitted source: 120 kPa/)
  assert.match(html, /<h3>Comparison<\/h3>/)
  assert.match(html, /<h3>Decision &amp; Correction<\/h3>/)
  assert.match(html, /<h3>History<\/h3>/)
  assert.match(html, /Corrected value<textarea[^>]*>Approved source: 150 kPa<\/textarea>/)
  assert.match(html, /class="review-modal-footer"/)
  assert.match(html, /<details class="history-details"/)
  const css = fs.readFileSync(path.join(root, 'src/styles.css'), 'utf8')
  assert.match(css, /\.review-modal\{width:min\(960px,100%\)/)
  assert.match(css, /@media\(max-width:800px\)\{\.review-modal-backdrop/)
})

test('results table keeps seven workflow columns and directs full values to the modal', () => {
  const table = renderToStaticMarkup(React.createElement(ResultsTable, {
    comparison: comparison('different'), corrections: [], onOpen() {} }))
  assert.equal((table.match(/<th scope="col">/g) || []).length, 7)
  assert.match(table, /Open details to see full approved and submitted values/)
  assert.doesNotMatch(table, /<th scope="col">Expected value<\/th>/)
  const css = fs.readFileSync(path.join(root, 'src/styles.css'), 'utf8')
  assert.match(css, /@media\(min-width:801px\)\{\.table-scroll\{overflow-x:visible/)
  assert.match(css, /@media\(max-width:800px\)\{\.review-modal-backdrop/)
})

test('comparison action exposes an immediate disabled loading state', () => {
  const html = renderToStaticMarkup(React.createElement(SetupPanel, {
    reference: null, submitted: null, onReference() {}, onSubmitted() {}, requirements: [],
    onRequirements() {}, mode: 'deterministic', onMode() {}, forceRefresh: false,
    onForceRefresh() {}, loading: true, onCompare() {} }))
  assert.match(html, /disabled=""[^>]*><span class="action-progress"><span class="spinner"><\/span> Comparing/)
  const appSource = fs.readFileSync(path.join(root, 'src/App.tsx'), 'utf8')
  assert.match(appSource, /openingRef\.current = true; setOpeningSessionId\(sessionId\)/)
  assert.match(appSource, /Opening\.\.\./)
  assert.match(appSource, /Retry opening/)
})

test('PDF download uses visitor credentials and returns a retryable service error', async () => {
  const previous = global.fetch
  try {
    global.fetch = async (_url, options) => {
      assert.equal(options.credentials, 'include')
      return new Response('temporarily unavailable', { status: 503 })
    }
    await assert.rejects(api.downloadPdf('/api/comparisons/session-1/report', 'report.pdf'), /server could not complete/)
  } finally { global.fetch = previous }
})

test('successful PDF download creates a named browser download', async () => {
  const previousFetch = global.fetch
  const previousDocument = global.document
  const previousWindow = global.window
  const previousCreate = URL.createObjectURL
  const previousRevoke = URL.revokeObjectURL
  const link = { href: '', download: '', clicked: false, click() { this.clicked = true }, remove() {} }
  try {
    global.fetch = async () => new Response(new Blob(['%PDF-1.4'], { type: 'application/pdf' }),
      { status: 200, headers: { 'Content-Type': 'application/pdf' } })
    global.document = { createElement() { return link }, body: { appendChild() {} } }
    global.window = { setTimeout() { return 1 } }
    URL.createObjectURL = () => 'blob:test-pdf'
    URL.revokeObjectURL = () => {}
    await api.downloadPdf('/api/comparisons/session-1/report', 'docwise-report.pdf')
    assert.equal(link.download, 'docwise-report.pdf')
    assert.equal(link.href, 'blob:test-pdf')
    assert.equal(link.clicked, true)
  } finally {
    global.fetch = previousFetch; global.document = previousDocument; global.window = previousWindow
    URL.createObjectURL = previousCreate; URL.revokeObjectURL = previousRevoke
  }
})

test('combined review and correction flow preserves ordered saves and partial-failure feedback', () => {
  const source = fs.readFileSync(path.join(root, 'src/components/ReviewDrawer.tsx'), 'utf8')
  const reviewSave = source.indexOf('await saveRequirementReview(')
  const correctionSave = source.indexOf('await saveCorrection(')
  assert.ok(reviewSave > 0 && correctionSave > reviewSave)
  assert.match(source, /decisionSaved = true[\s\S]*?await saveCorrection/)
  assert.match(source, /Decision saved, but the correction was not saved/)
  assert.match(source, /Decision and correction were saved, but the latest status could not be loaded/)
  assert.match(source, /refreshNeeded \|\|/)
  assert.match(source, /savingRef\.current = true/)
  assert.match(source, /decision === 'accepted' && hasDiscrepancy && <div className="correction-panel"/)
})

test('static sample PDFs preserve the original bytes and checklist clauses', () => {
  const source = path.resolve(root, '..', 'samples')
  const checklist = JSON.parse(fs.readFileSync(path.join(source, 'checklist.json'), 'utf8'))
  assert.deepEqual(samples.SAMPLE_REQUIREMENTS, checklist)
  for (const role of ['reference', 'submitted']) {
    const filename = samples.SAMPLE_PDFS[role].filename
    const original = fs.readFileSync(path.join(source, filename))
    const published = fs.readFileSync(path.join(root, 'public', 'samples', filename))
    assert.ok(original.subarray(0, 5).equals(Buffer.from('%PDF-')))
    assert.ok(original.equals(published), filename)
  }
})

test('each sample PDF loads independently without any comparison or Groq request', async () => {
  const previous = global.fetch
  const requested = []
  try {
    global.fetch = async url => {
      requested.push(url)
      return new Response(fs.readFileSync(path.join(root, 'public', url)),
        { status: 200, headers: { 'Content-Type': 'application/pdf' } })
    }
    const approved = await samples.loadSamplePdf('reference')
    const submitted = await samples.loadSamplePdf('submitted')
    assert.equal(approved.name, 'approved_reference.pdf')
    assert.equal(submitted.name, 'submitted_revision.pdf')
    assert.equal(approved.type, 'application/pdf')
    assert.equal(requested.length, 2)
    assert.deepEqual(requested, ['/samples/approved_reference.pdf', '/samples/submitted_revision.pdf'])
  } finally { global.fetch = previous }
})

test('sample loading rejects missing or invalid files and preserves overwrite confirmation rules', async () => {
  const previous = global.fetch
  try {
    global.fetch = async () => new Response('missing', { status: 404 })
    await assert.rejects(samples.loadSamplePdf('reference'), /Could not load/)
    global.fetch = async () => new Response('not a PDF', { status: 200 })
    await assert.rejects(samples.loadSamplePdf('submitted'), /not a valid PDF/)
  } finally { global.fetch = previous }
  const checklist = samples.SAMPLE_REQUIREMENTS
  assert.equal(samples.requiresSampleOverwriteConfirmation('reference', 'user', null, checklist), true)
  assert.equal(samples.requiresSampleOverwriteConfirmation('submitted', null, 'user', checklist), true)
  assert.equal(samples.requiresSampleOverwriteConfirmation('both', 'sample', 'sample', checklist), false)
  assert.equal(samples.requiresSampleOverwriteConfirmation('both', null, null,
    checklist.map((item, index) => index ? item : { ...item, reference_text: 'My custom clause' })), true)
})

test('sample onboarding shows loading and ready states without starting comparison', () => {
  const base = { reference: null, submitted: null, onReference() {}, onSubmitted() {},
    requirements: samples.SAMPLE_REQUIREMENTS, onRequirements() {}, mode: 'deterministic',
    onMode() {}, forceRefresh: false, onForceRefresh() {}, loading: false,
    onCompare() {}, sampleError: '', lastSampleAction: null, onLoadSample() {} }
  const loading = renderToStaticMarkup(React.createElement(SetupPanel,
    { ...base, sampleLoading: 'both', sampleReady: false }))
  assert.match(loading, /Loading samples\.\.\./)
  assert.doesNotMatch(loading, /Ready to compare!/)
  const ready = renderToStaticMarkup(React.createElement(SetupPanel,
    { ...base, sampleLoading: null, sampleReady: true }))
  assert.match(ready, /Ready to compare!/)
  assert.match(ready, /Click Run Comparison/)
  assert.equal((ready.match(/Use this sample PDF/g) || []).length, 2)
  const appSource = fs.readFileSync(path.join(root, 'src/App.tsx'), 'utf8')
  const loader = appSource.slice(appSource.indexOf('const loadSamples ='), appSource.indexOf('const reloadHistory ='))
  assert.doesNotMatch(loader, /createComparison|analyze|Groq/)
  assert.match(loader, /window\.confirm/)
})

test('comparison values use result and uncertainty states, with visible text indicators', () => {
  const render = data => renderToStaticMarkup(React.createElement(ReviewDrawer, {
    comparison: data, row: types.mergeRequirements(data)[0], corrections: [], revisions: [],
    onClose() {}, async onSaved() {} }))
  assert.match(render(comparison('match')), /submitted-value value-match[\s\S]*?value-indicator">Match/)
  assert.match(render(comparison('different')), /submitted-value value-different[\s\S]*?value-indicator">Different/)
  const missing = comparison('missing')
  missing.findings[0].submitted = { page: 1, excerpt: 'Unrelated project header' }
  assert.match(render(missing), /submitted-value value-missing[\s\S]*?value-indicator">Missing[\s\S]*?No corresponding submitted value found/)
  assert.doesNotMatch(render(missing), /Unrelated project header/)
  assert.match(render(comparison('match', [aiIssue])), /submitted-value value-review[\s\S]*?value-indicator">Needs review/)
  const css = fs.readFileSync(path.join(root, 'src/styles.css'), 'utf8')
  assert.match(css, /\.comparison-value\.submitted-value\.value-different/)
  assert.match(css, /\.comparison-value\.submitted-value\.value-missing/)
  assert.match(css, /@media\(max-width:800px\)\{\.sample-onboarding/)
})

test('approval wording maps verified data without changing the verification action', () => {
  const data = comparison('different')
  data.requirement_reviews[0] = { requirement_id: 'R-01', status: 'accepted', comment: '',
    ambiguous_legacy: false, source: 'explicit' }
  const correction = { id: 'c-1', finding_id: 'f-1', requirement_id: 'R-01',
    field_name: 'Design pressure', corrected_value: '150 kPa', reason: 'Approved value',
    supporting_notes: '', status: 'pending_verification', updated_at: '2026-01-01',
    superseded_at: null }
  const render = item => renderToStaticMarkup(React.createElement(ReviewDrawer, {
    comparison: data, row: types.mergeRequirements(data)[0], corrections: [item], revisions: [],
    onClose() {}, async onSaved() {} }))
  assert.match(render(correction), />Approve Correction<\/button>/)
  assert.match(render(correction), />Reject Correction<\/button>/)
  assert.match(render({ ...correction, status: 'verified', verified_at: '2026-01-02' }), /Correction Approved/)
  assert.equal(types.CORRECTION_LABELS.verified, 'Correction Approved')
  assert.equal(types.CORRECTION_DISPLAY_LABELS.verified, 'Correction Approved')
  const source = fs.readFileSync(path.join(root, 'src/components/ReviewDrawer.tsx'), 'utf8')
  assert.match(source, /onClick=\{\(\) => changeStatus\('verified'\)\}>Approve Correction/)
})
