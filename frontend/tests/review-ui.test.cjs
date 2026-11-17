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
  assert.equal(types.auditActionLabel({ action: 'correction_status_changed', new_status: 'verified' }), 'Correction verified')
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
