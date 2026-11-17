import { FileText, Plus, Trash2, Upload } from 'lucide-react'
import type { Requirement } from '../types'

type Props = {
  reference: File | null
  submitted: File | null
  onReference: (file: File | null) => void
  onSubmitted: (file: File | null) => void
  requirements: Requirement[]
  onRequirements: (items: Requirement[]) => void
  mode: 'deterministic' | 'ai'
  onMode: (mode: 'deterministic' | 'ai') => void
  forceRefresh: boolean
  onForceRefresh: (value: boolean) => void
  loading: boolean
  onCompare: () => void
}

function FileField({ id, title, file, onFile }: { id: string; title: string; file: File | null; onFile: (file: File | null) => void }) {
  return <div className="file-field">
    <div className="field-label">{title}</div>
    <label className="file-zone" htmlFor={id} onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); onFile(event.dataTransfer.files[0] ?? null) }}>
      <span className="file-icon"><FileText size={19}/></span>
      <span className="file-copy"><strong>{file?.name ?? 'Select a PDF document'}</strong><small>{file ? `${(file.size / 1024 / 1024).toFixed(2)} MB` : 'Click to browse or drag a file here · 10 MB maximum'}</small></span>
      <Upload size={17} className="file-upload-icon" aria-hidden="true"/>
      <input id={id} className="file-input" type="file" accept=".pdf,application/pdf" aria-label={title} onChange={event => onFile(event.target.files?.[0] ?? null)}/>
    </label>
  </div>
}

export default function SetupPanel(props: Props) {
  const update = (index: number, key: keyof Requirement, value: string) => props.onRequirements(props.requirements.map((item, i) => i === index ? { ...item, [key]: value } : item))
  const add = () => props.onRequirements([...props.requirements, { id: `R-${crypto.randomUUID().slice(0, 8).toUpperCase()}`, title: '', reference_text: '' }])
  const remove = (index: number) => props.onRequirements(props.requirements.filter((_, i) => i !== index))

  return <section className="setup-panel" aria-labelledby="setup-title">
    <div className="panel-header"><div><h2 id="setup-title">New comparison</h2><p>Upload two PDFs and define the approved clauses to check.</p></div><span className="panel-meta">PDF · 10 MB per file</span></div>
    <div className="setup-body">
      <div className="file-grid"><FileField id="reference-pdf" title="Approved reference" file={props.reference} onFile={props.onReference}/><FileField id="submitted-pdf" title="Submitted document" file={props.submitted} onFile={props.onSubmitted}/></div>
      <div className="checklist-heading"><div><h3>Requirements checklist</h3><p>Enter text from the approved reference. Up to 50 requirements.</p></div><span>{props.requirements.length} items</span></div>
      <div className="checklist-list">{props.requirements.map((item, index) => <div className="checklist-item" key={item.id + index}>
        <span className="checklist-number">{String(index + 1).padStart(2, '0')}</span>
        <div className="checklist-inputs"><label><span>Requirement name</span><input value={item.title} onChange={event => update(index, 'title', event.target.value)} placeholder="e.g. Design pressure"/></label><label><span>Approved clause</span><input value={item.reference_text} onChange={event => update(index, 'reference_text', event.target.value)} placeholder="Text or value from approved PDF"/></label></div>
        <button type="button" className="icon-action" aria-label={`Remove requirement ${index + 1}`} onClick={() => remove(index)}><Trash2 size={16}/></button>
      </div>)}</div>
      <button type="button" className="text-action" onClick={add} disabled={props.requirements.length >= 50}><Plus size={16}/> Add requirement</button>
    </div>
    <div className="setup-footer"><div className="setup-options"><fieldset><legend>Comparison mode</legend><div className="segmented"><label className={props.mode === 'deterministic' ? 'active' : ''}><input type="radio" name="mode" checked={props.mode === 'deterministic'} onChange={() => props.onMode('deterministic')}/> Deterministic</label><label className={props.mode === 'ai' ? 'active' : ''}><input type="radio" name="mode" checked={props.mode === 'ai'} onChange={() => props.onMode('ai')}/> AI-Assisted</label></div></fieldset>{props.mode === 'ai' && <label className="force-refresh"><input type="checkbox" checked={props.forceRefresh} onChange={event => props.onForceRefresh(event.target.checked)}/> Force fresh Groq analysis</label>}</div><button type="button" className="primary-button" onClick={props.onCompare} disabled={props.loading}>{props.loading ? 'Comparing…' : 'Run comparison'}</button></div>
  </section>
}
