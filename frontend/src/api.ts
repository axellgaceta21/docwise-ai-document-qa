import type { Comparison, Correction, CorrectionInput, CorrectionStatus, Requirement, RequirementReview, ReviewStatus, Revision, SessionSummary } from './types'

const API_BASE_URL = ((globalThis as typeof globalThis & { __DOCWISE_API_BASE_URL__?: string })
  .__DOCWISE_API_BASE_URL__ ?? '').replace(/\/+$/, '')
const apiUrl = (path: string) => `${API_BASE_URL}${path}`
const requestOptions = { credentials: 'include' as const }

async function responseJson<T>(response: Response): Promise<T> {
  const body = await response.json()
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'The request could not be completed.')
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

export async function saveRequirementReview(sessionId: string, requirementId: string, status: ReviewStatus, comment: string): Promise<RequirementReview> {
  return responseJson(await fetch(apiUrl(`/api/comparisons/${encodeURIComponent(sessionId)}/requirements/${encodeURIComponent(requirementId)}/review`), {
    ...requestOptions,
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status, comment }),
  }))
}

export function reportUrl(sessionId: string): string {
  return apiUrl(`/api/comparisons/${encodeURIComponent(sessionId)}/report`)
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
