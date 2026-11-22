import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const { auth } = vi.hoisted(() => ({
  auth: {
    signInWithPasskey: vi.fn(),
    signInWithPassword: vi.fn(),
    signUp: vi.fn(),
    registerPasskey: vi.fn(),
    signOut: vi.fn(),
    getSession: vi.fn(),
    onAuthStateChange: vi.fn(() => ({ data: { subscription: { unsubscribe: vi.fn() } } })),
  },
}))

vi.mock('../supabase', () => ({
  supabase: { auth },
  apiBaseUrl: 'http://localhost:5000/api/v1',
}))

import Login from './Login.jsx'

const session = { access_token: 'test-access-token' }
const profile = { id: 'user-1', full_name: 'Demo Citizen', role: 'citizen' }

function successfulApiResponse(data) {
  return { ok: true, json: async () => ({ data, error: null }) }
}

async function switchToEnglish(user) {
  await user.click(screen.getByRole('button', { name: 'English' }))
}

describe('passkey login flow', () => {
  afterEach(() => cleanup())

  beforeEach(() => {
    vi.clearAllMocks()
    auth.getSession.mockResolvedValue({ data: { session: null }, error: null })
    auth.onAuthStateChange.mockReturnValue({ data: { subscription: { unsubscribe: vi.fn() } } })
    globalThis.fetch = vi.fn().mockResolvedValue(successfulApiResponse({ user: profile }))
  })

  it('uses Supabase passkey auth and records the login with the existing Flask session route', async () => {
    const user = userEvent.setup()
    auth.signInWithPasskey.mockResolvedValue({ data: { session }, error: null })
    render(<Login />)
    await switchToEnglish(user)
    await user.click(screen.getByRole('button', { name: 'Sign in with passkey' }))

    expect(auth.signInWithPasskey).toHaveBeenCalledOnce()
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith(
      'http://localhost:5000/api/v1/auth/session',
      expect.objectContaining({
        method: 'POST',
        headers: { Authorization: 'Bearer test-access-token' },
      }),
    ))
    expect(await screen.findByRole('heading', { name: 'Welcome, Demo Citizen' })).toBeInTheDocument()
    expect(document.querySelector('.account-role strong')).toHaveTextContent('citizen')
  })

  it('shows account recovery guidance and does not call Flask if passkey auth fails', async () => {
    const user = userEvent.setup()
    auth.signInWithPasskey.mockResolvedValue({ data: null, error: new Error('passkey unavailable') })
    render(<Login />)
    await switchToEnglish(user)
    await user.click(screen.getByRole('button', { name: 'Sign in with passkey' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Passkey sign-in did not complete')
    expect(globalThis.fetch).not.toHaveBeenCalled()
  })

  it('allows password sign-in and passkey enrollment after backend verification', async () => {
    const user = userEvent.setup()
    auth.signInWithPassword.mockResolvedValue({ data: { session }, error: null })
    auth.registerPasskey.mockResolvedValue({ data: { id: 'passkey-1' }, error: null })
    render(<Login />)
    await switchToEnglish(user)
    await user.type(screen.getByLabelText('Email address'), 'demo@example.test')
    await user.type(screen.getByLabelText('Password recovery sign-in'), 'demo-password')
    await user.click(screen.getByRole('button', { name: 'Sign in with email' }))

    expect(await screen.findByRole('heading', { name: 'Welcome, Demo Citizen' })).toBeInTheDocument()
    expect(auth.signInWithPassword).toHaveBeenCalledWith({ email: 'demo@example.test', password: 'demo-password' })
    await user.click(screen.getByRole('button', { name: 'Add a passkey to this device' }))
    expect(auth.registerPasskey).toHaveBeenCalledOnce()
    expect(await screen.findByRole('status')).toHaveTextContent('Passkey added')
  })

  it('does not show a profile if the backend rejects the Supabase JWT', async () => {
    const user = userEvent.setup()
    auth.signInWithPasskey.mockResolvedValue({ data: { session }, error: null })
    globalThis.fetch.mockResolvedValue({
      ok: false,
      json: async () => ({ error: { code: 'UNAUTHENTICATED', message: 'bad token' } }),
    })
    render(<Login />)
    await switchToEnglish(user)
    await user.click(screen.getByRole('button', { name: 'Sign in with passkey' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Passkey sign-in did not complete')
    expect(globalThis.fetch).toHaveBeenCalledOnce()
    expect(screen.queryByRole('heading', { name: 'Welcome, Demo Citizen' })).not.toBeInTheDocument()
  })

  it('can switch to Urdu and renders RTL text', async () => {
    render(<Login />)
    expect(document.documentElement.dir).toBe('rtl')
    fireEvent.click(screen.getByRole('button', { name: 'English' }))
    await waitFor(() => expect(document.documentElement.dir).toBe('ltr'))
    expect(screen.getByRole('heading', { name: 'Sign in simply' })).toBeInTheDocument()
  })
})
