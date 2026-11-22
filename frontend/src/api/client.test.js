import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { getSession } = vi.hoisted(() => ({ getSession: vi.fn() }))
vi.mock('../supabase', () => ({
  apiBaseUrl: 'http://localhost:5000/api/v1/',
  supabase: { auth: { getSession } },
}))

import { ApiError, api, request } from './client'

describe('typed API client', () => {
  beforeEach(() => {
    getSession.mockResolvedValue({ data: { session: { access_token: 'session-token' } } })
    globalThis.fetch = vi.fn()
  })
  afterEach(() => vi.restoreAllMocks())

  it('uses the standard envelope, bearer token, and a normalized API base URL', async () => {
    fetch.mockResolvedValue({ ok: true, json: async () => ({ data: [{ id: 'case-1' }], error: null }) })
    const result = await api.cases({ status: 'in_review', route: '', page: 2 })

    expect(result).toEqual([{ id: 'case-1' }])
    expect(fetch).toHaveBeenCalledWith(
      'http://localhost:5000/api/v1/cases?status=in_review&page=2',
      expect.objectContaining({ headers: { Accept: 'application/json', Authorization: 'Bearer session-token' } }),
    )
  })

  it('surfaces structured API errors for frontend recovery and messaging', async () => {
    fetch.mockResolvedValue({ ok: false, status: 403, json: async () => ({ data: null, error: { code: 'CONSENT_REQUIRED', message: 'Consent is required.', details: { scope: 'claim_data' } } }) })

    await expect(api.submitCase('case-1')).rejects.toMatchObject({
      name: 'ApiError', code: 'CONSENT_REQUIRED', status: 403, message: 'Consent is required.', details: { scope: 'claim_data' },
    })
  })

  it('sends multipart uploads without overriding the browser content type boundary', async () => {
    fetch.mockResolvedValue({ ok: true, json: async () => ({ data: { id: 'document-1' }, error: null }) })
    const file = new File(['photo'], 'id.png', { type: 'image/png' })
    await api.uploadDocument('case-1', file, 'cnic_photo')

    const [, options] = fetch.mock.calls[0]
    expect(options.headers).toEqual({ Accept: 'application/json', Authorization: 'Bearer session-token' })
    expect(options.body.get('file')).toBe(file)
    expect(options.body.get('kind')).toBe('cnic_photo')
  })

  it('keeps staff decisions, assignment, and close actions on the proposal routes', async () => {
    fetch.mockResolvedValue({ ok: true, json: async () => ({ data: {}, error: null }) })
    await api.assignCase('case-1', 'officer-1')
    await api.escalateCase('case-1', 'Needs second review')
    await api.decideCase('case-1', 'rejected', 'Rule 4 was not met')
    await api.closeCase('case-1')

    expect(fetch.mock.calls.map(([url, options]) => [url, options.method, options.body && JSON.parse(options.body)])).toEqual([
      ['http://localhost:5000/api/v1/cases/case-1/assign', 'POST', { officer_id: 'officer-1' }],
      ['http://localhost:5000/api/v1/cases/case-1/escalate', 'POST', { note: 'Needs second review' }],
      ['http://localhost:5000/api/v1/cases/case-1/decision', 'POST', { outcome: 'rejected', note: 'Rule 4 was not met' }],
      ['http://localhost:5000/api/v1/cases/case-1/close', 'POST', {}],
    ])
  })

  it('sends mock complaint and identity lookup through Flask with their proposal payloads', async () => {
    fetch.mockResolvedValue({ ok: true, json: async () => ({ data: {}, error: null }) })
    await api.complaint('case-1', 'I need help with this decision')
    await api.identityLookup({ cnic: '4210112345671' })

    expect(fetch.mock.calls.map(([url, options]) => [url, JSON.parse(options.body)])).toEqual([
      ['http://localhost:5000/api/v1/mock/complaints', { case_id: 'case-1', text: 'I need help with this decision' }],
      ['http://localhost:5000/api/v1/mock/identity/lookup', { cnic: '4210112345671' }],
    ])
  })

  it('reports an offline network error with a retryable status marker', async () => {
    fetch.mockRejectedValue(new TypeError('Failed to fetch'))
    await expect(request('/cases')).rejects.toMatchObject({ name: 'ApiError', status: 0, code: 'NETWORK_ERROR' })
  })

  it('exports a typed error class', () => {
    expect(new ApiError('bad').name).toBe('ApiError')
  })
})
