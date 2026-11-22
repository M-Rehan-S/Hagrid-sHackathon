import { apiBaseUrl, supabase } from '../supabase'

export class ApiError extends Error {
  constructor(message, { code = 'NETWORK_ERROR', status = 0, details = {} } = {}) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.details = details
  }
}

export async function request(path, { method = 'GET', body, file, formData, token, headers = {}, signal } = {}) {
  if (!apiBaseUrl) throw new ApiError('Backend API URL is not configured.', { code: 'CONFIG_ERROR' })
  const baseUrl = apiBaseUrl.replace(/\/$/, '')
  const accessToken = token || (await supabase?.auth.getSession())?.data?.session?.access_token
  const requestHeaders = { Accept: 'application/json', ...headers }
  if (accessToken) requestHeaders.Authorization = `Bearer ${accessToken}`
  let payload
  if (formData) {
    payload = formData
  } else if (file) {
    payload = new FormData()
    payload.append('file', file)
    payload.append('kind', body?.kind || 'supporting_doc')
  } else if (body !== undefined) {
    requestHeaders['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }

  let response
  try {
    response = await fetch(`${baseUrl}${path}`, {
      method,
      headers: requestHeaders,
      body: payload,
      signal,
    })
  } catch (cause) {
    if (cause?.name === 'AbortError') throw cause
    throw new ApiError('Could not reach the service. Check your connection and try again.', { cause })
  }

  const result = await response.json().catch(() => null)
  if (!response.ok) {
    throw new ApiError(
      result?.error?.message || `Request failed (${response.status}).`,
      {
        code: result?.error?.code || 'HTTP_ERROR',
        status: response.status,
        details: result?.error?.details || {},
      },
    )
  }
  if (result && Object.hasOwn(result, 'data')) return result.data
  return result
}

const query = (values = {}) => {
  const params = new URLSearchParams()
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') params.set(key, value)
  })
  return params.size ? `?${params}` : ''
}

export const api = {
  request,
  cases: (filters) => request(`/cases${query(filters)}`),
  case: (id) => request(`/cases/${id}`),
  createCase: (citizen_id, case_type = 'relief_claim') => request('/cases', { method: 'POST', body: { citizen_id, case_type } }),
  patchForm: (id, form_data_partial, last_step) => request(`/cases/${id}/form`, { method: 'PATCH', body: { form_data_partial, last_step } }),
  submitCase: (id) => request(`/cases/${id}/submit`, { method: 'POST', body: {} }),
  assignCase: (id, officer_id) => request(`/cases/${id}/assign`, { method: 'POST', body: { officer_id } }),
  escalateCase: (id, note) => request(`/cases/${id}/escalate`, { method: 'POST', body: { note } }),
  decideCase: (id, outcome, note) => request(`/cases/${id}/decision`, { method: 'POST', body: { outcome, note } }),
  closeCase: (id) => request(`/cases/${id}/close`, { method: 'POST', body: {} }),
  uploadDocument: (id, file, kind) => request(`/cases/${id}/documents`, { method: 'POST', file, body: { kind } }),
  createCitizen: (body) => request('/citizens', { method: 'POST', body }),
  citizen: (id) => request(`/citizens/${id}`),
  updateCitizen: (id, body) => request(`/citizens/${id}`, { method: 'PATCH', body }),
  exportCitizen: (id) => request(`/citizens/${id}/export`),
  helperCitizens: () => request('/helper/citizens'),
  linkCitizen: (id) => request(`/helper/citizens/${id}/link`, { method: 'POST', body: {} }),
  consents: (citizen_id) => request(`/consents${query({ citizen_id })}`),
  grantConsent: (body) => request('/consents', { method: 'POST', body }),
  withdrawConsent: (id) => request(`/consents/${id}/withdraw`, { method: 'POST', body: {} }),
  scamCheck: (text) => request('/ai/scam-check', { method: 'POST', body: { text } }),
  ask: (question, lang) => request('/ai/ask', { method: 'POST', body: { question, lang } }),
  rules: (rule_key) => request(`/rules${query({ rule_key })}`),
  createRule: (body) => request('/rules', { method: 'POST', body }),
  activateRule: (id) => request(`/rules/${id}/activate`, { method: 'POST', body: {} }),
  simulate: (body) => request('/twin/simulate', { method: 'POST', body }),
  apiKeys: () => request('/api-keys'),
  createApiKey: (body) => request('/api-keys', { method: 'POST', body }),
  revokeApiKey: (id) => request(`/api-keys/${id}/revoke`, { method: 'POST', body: {} }),
  evaluation: () => request('/eval/summary'),
  auditLogs: (params) => request(`/audit-logs${query(params)}`),
  myAuditLogs: () => request('/audit-logs/mine'),
  verifyAudit: () => request('/audit-logs/verify'),
  sync: (ops) => request('/sync/batch', { method: 'POST', body: { ops } }),
  transcribe: async (audio, lang) => {
    const form = new FormData()
    form.append('audio', audio)
    form.append('lang', lang)
    return request('/ai/transcribe', { method: 'POST', formData: form })
  },
  extractForm: (text, lang, existing_form) => request('/ai/extract-form', { method: 'POST', body: { text, lang, ...(existing_form ? { existing_form } : {}) } }),
  identityLookup: (body) => request('/mock/identity/lookup', { method: 'POST', body }),
  createPayment: (case_id, amount) => request('/mock/payments', { method: 'POST', body: { case_id, amount } }),
  payment: (id) => request(`/mock/payments/${id}`),
  complaint: (case_id, text) => request('/mock/complaints', { method: 'POST', body: { case_id, text } }),
  publicScamCheck: (text, apiKey) => request('/public/scam-check', { method: 'POST', body: { text }, headers: { 'X-API-Key': apiKey } }),
  publicCaseStatus: (id, apiKey) => request(`/public/cases/${id}/status`, { headers: { 'X-API-Key': apiKey } }),
}
