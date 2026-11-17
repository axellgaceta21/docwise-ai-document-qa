export default function Brand({ compact = false }: { compact?: boolean }) {
  return <span className={compact ? 'brand-compact' : 'brand-full'} aria-label="Docwise Document Quality Assurance">
    <span className="brand-mark" aria-hidden="true" />
    <span className="brand-type"><strong>docwise<span className="brand-dot">.</span></strong><small>Document Quality Assurance</small></span>
  </span>
}
