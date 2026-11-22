import { apiBaseUrl } from '../supabase'

async function backendAuth(path, accessToken) {
  if (!apiBaseUrl) throw new Error('Backend API URL is not configured.')

  const response = await fetch(`${apiBaseUrl}${path}`, {
    method: path === '/auth/session' ? 'POST' : 'GET',
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  const body = await response.json().catch(() => null)

  if (!response.ok) {
    throw new Error(body?.error?.message || 'BACKEND_AUTH_FAILED')
  }
  return body.data.user
}

export const recordLogin = (accessToken) => backendAuth('/auth/session', accessToken)
export const getBackendProfile = (accessToken) => backendAuth('/auth/me', accessToken)
