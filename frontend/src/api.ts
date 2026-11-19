import type { Comparison, Correction, CorrectionInput, CorrectionStatus, Requirement, RequirementReviewUpdate, ReviewStatus, Revision, SessionSummary } from './types'

const API_BASE_URL = ((globalThis as typeof globalThis & { __DOCWISE_API_BASE_URL__?: string })
  .__DOCWISE_API_BASE_URL__ ?? '').replace(/\/+$/, '')
const apiUrl = (path: string) => `${API_BASE_URL}${path}`
const requestOptions = { credentials: 'include' as const }

async function responseJson<T>(response: Response): Promise<T> {
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = body && typeof body.detail === 'string' ? body.detail : null
    throw new Error(detail ?? (response.status === 429 ? 'Too many requests. Wait a moment and try again.'
      : response.status >= 500 ? 'The server could not complete the request. Try again shortly.'
      : `The request could not be completed (${response.status}).`))
  }
  if (body === null) throw new Error('The server returned an unexpected response. Reopen this comparison to check whether the change was saved.')
  return body as T
}

export async function listComparisons(): Promise<SessionSummary[]> {
  return responseJson<SessionSummary[]>(await fetch(apiUrl('/api/comparisons?limit=100'), requestOptions))
}

export async function getComparison(sessionId: string): Promise<Comparison> {
  return responseJson<Comparison>(await fetch(apiUrl(`/api/comparisons/${encodeURIComponent(sessionId)}`), requestOptions))
}

export async function createComparison(reference: File, submitted: File, requirements: Requirement[], mode: 'deterministic' | 'ai', forceRefresh: boolean): Promise<Comparison> {
  const form = new FormData()
  form.append('reference', reference)
  form.append('submitted', submitted)
  form.append('checklist', JSON.stringify(requirements))
  form.append('mode', mode)
  form.append('force_refresh', String(forceRefresh))
  return responseJson<Comparison>(await fetch(apiUrl('/api/compare'), { ...requestOptions, method: 'POST', body: form }))
}

export async function saveReview(sessionId: string, findingId: string, status: ReviewStatus, comment: string): Promise<{ review_status: ReviewStatus; review_comment: string }> {
  return responseJson(await fetch(apiUrl(`/api/comparisons/${encodeURIComponent(sessionId)}/findings/${encodeURIComponent(findingId)}/review`), {
    ...requestOptions,
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status, comment }),
  }))
}

export async function saveRequirementReview(sessionId: string, requirementId: string, status: ReviewStatus, comment: string): Promise<RequirementReviewUpdate> {
  const started = performance.now()
  try {
    const response = await fetch(apiUrl(`/api/comparisons/${encodeURIComponent(sessionId)}/requirements/${encodeURIComponent(requirementId)}/review`), {
      ...requestOptions,
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status, comment }),
    })
    const result = await responseJson<RequirementReviewUpdate>(response)
    console.info('Docwise review save timing', { round_trip_ms: Math.round(performance.now() - started), server_timing: response.headers.get('Server-Timing') })
    return result
  } catch (cause) {
    console.info('Docwise review save failed', { round_trip_ms: Math.round(performance.now() - started) })
    if (cause instanceof TypeError) throw new Error('Network connection failed. Reopen the comparison to check whether your decision was saved, then try again.')
    throw cause
  }
}

export function reportUrl(sessionId: string): string {
  return apiUrl(`/api/comparisons/${encodeURIComponent(sessionId)}/report`)
}

export async function downloadPdf(path: string, filename: string): Promise<void> {
  const response = await fetch(path, requestOptions)
  if (!response.ok) await responseJson(response)
  const blob = await response.blob()
  if (!blob.size || !blob.type.includes('pdf')) throw new Error('The server did not return a PDF. Please try again.')
  const objectUrl = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = objectUrl
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000)
}

const comparisonUrl = (sessionId: string) => `/api/comparisons/${encodeURIComponent(sessionId)}`
export const listCorrections = async (sessionId: string, includeHistory = false): Promise<Correction[]> =>
  responseJson(await fetch(apiUrl(`${comparisonUrl(sessionId)}/corrections?include_history=${includeHistory}`), requestOptions))
export const saveCorrection = async (sessionId: string, input: CorrectionInput, previousId?: string): Promise<Correction> =>
  responseJson(await fetch(apiUrl(`${comparisonUrl(sessionId)}/corrections${previousId ? `/${encodeURIComponent(previousId)}` : ''}`), {
    ...requestOptions,
    method: previousId ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input),
  }))
export const setCorrectionStatus = async (sessionId: string, correctionId: string, status: CorrectionStatus, note = ''): Promise<Correction> =>
  responseJson(await fetch(apiUrl(`${comparisonUrl(sessionId)}/corrections/${encodeURIComponent(correctionId)}/status`), {
    ...requestOptions,
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status, note }),
  }))
export const listRevisions = async (sessionId: string): Promise<Revision[]> =>
  responseJson(await fetch(apiUrl(`${comparisonUrl(sessionId)}/revisions`), requestOptions))
export const generateRevision = async (sessionId: string): Promise<Revision> =>
  responseJson(await fetch(apiUrl(`${comparisonUrl(sessionId)}/revisions`), { ...requestOptions, method: 'POST' }))
export const revisionUrl = (sessionId: string, revisionId: string): string =>
  apiUrl(`${comparisonUrl(sessionId)}/revisions/${encodeURIComponent(revisionId)}/pdf`)
