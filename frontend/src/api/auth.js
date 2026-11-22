import { apiBaseUrl } from '../supabase'

async function backendAuth(path, accessToken) {
  if (!apiBaseUrl) throw new Error('Backend API URL is not configured.')

  let response
  try {
    response = await fetch(`${apiBaseUrl.replace(/\/$/, '')}${path}`, {
      method: path === '/auth/session' ? 'POST' : 'GET',
      headers: { Authorization: `Bearer ${accessToken}` },
    })
  } catch (cause) {
    const error = new Error('Could not reach the service.')
    error.status = 0
    error.cause = cause
    throw error
  }
  const body = await response.json().catch(() => null)

  if (!response.ok) {
    const error = new Error(body?.error?.message || 'BACKEND_AUTH_FAILED')
    error.status = response.status
    throw error
  }
  return body.data.user
}

export const recordLogin = (accessToken) => backendAuth('/auth/session', accessToken)
export const getBackendProfile = (accessToken) => backendAuth('/auth/me', accessToken)
