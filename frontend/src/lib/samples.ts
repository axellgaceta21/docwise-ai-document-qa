import type { Requirement } from '../types'

export type SampleRole = 'reference' | 'submitted'
export type SampleSource = 'sample' | 'user' | null

export const SAMPLE_PDFS: Record<SampleRole, { filename: string; url: string; title: string; description: string }> = {
  reference: {
    filename: 'approved_reference.pdf', url: '/samples/approved_reference.pdf', title: 'Approved Reference',
    description: 'Example engineering requirements covering design pressure, operating temperature, materials, and inspection methods.',
  },
  submitted: {
    filename: 'submitted_revision.pdf', url: '/samples/submitted_revision.pdf', title: 'Submitted Revision',
    description: 'Example revised document containing matching, changed, and missing requirements.',
  },
}

export const SAMPLE_REQUIREMENTS: Requirement[] = [
  { id: 'R-01', title: 'Design pressure', reference_text: 'Design pressure: 150 kPa.' },
  { id: 'R-02', title: 'Operating temperature', reference_text: 'Operating temperature: 80 C.' },
  { id: 'R-03', title: 'Pipe material', reference_text: 'Pipe material: ASTM A106 Grade B carbon steel.' },
  { id: 'R-04', title: 'Inspection method', reference_text: 'Inspection method: visual inspection and hydrostatic test.' },
]

export function matchesSampleRequirements(items: Requirement[]): boolean {
  return items.length === SAMPLE_REQUIREMENTS.length && items.every((item, index) => {
    const sample = SAMPLE_REQUIREMENTS[index]
    return item.id === sample.id && item.title === sample.title && item.reference_text === sample.reference_text
  })
}

export function requiresSampleOverwriteConfirmation(action: SampleRole | 'both',
  referenceSource: SampleSource, submittedSource: SampleSource, requirements: Requirement[]): boolean {
  if (action === 'both') return referenceSource === 'user' || submittedSource === 'user' || !matchesSampleRequirements(requirements)
  return action === 'reference' ? referenceSource === 'user' : submittedSource === 'user'
}

export async function loadSamplePdf(role: SampleRole): Promise<File> {
  const sample = SAMPLE_PDFS[role]
  const response = await fetch(sample.url)
  if (!response.ok) throw new Error(`Could not load ${sample.filename} (${response.status}). Please try again.`)
  const bytes = await response.arrayBuffer()
  if (!bytes.byteLength || bytes.byteLength > 10 * 1024 * 1024 ||
      new TextDecoder().decode(bytes.slice(0, 5)) !== '%PDF-') {
    throw new Error(`${sample.filename} is not a valid PDF under 10 MB.`)
  }
  return new File([bytes], sample.filename, { type: 'application/pdf' })
}
