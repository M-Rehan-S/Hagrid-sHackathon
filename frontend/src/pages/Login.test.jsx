import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const { auth } = vi.hoisted(() => ({ auth: {
  signInWithPasskey: vi.fn(), signInWithPassword: vi.fn(), signUp: vi.fn(), registerPasskey: vi.fn(),
  resetPasswordForEmail: vi.fn(), updateUser: vi.fn(), getSession: vi.fn(),
  onAuthStateChange: vi.fn(() => ({ data: { subscription: { unsubscribe: vi.fn() } } })),
} }))

vi.mock('../supabase', () => ({ supabase: { auth }, apiBaseUrl: 'http://localhost:5000/api/v1' }))

import Login from './Login.jsx'

const session = { access_token: 'test-access-token' }
const profile = { id: 'user-1', full_name: 'Demo Citizen', role: 'citizen' }
const onAuthenticated = vi.fn()
const onLanguage = vi.fn()
function successfulApiResponse(data) { return { ok: true, json: async () => ({ data, error: null }) } }

describe('Supabase sign-in and Flask profile verification', () => {
  afterEach(() => cleanup())
  beforeEach(() => {
    vi.clearAllMocks()
    auth.getSession.mockResolvedValue({ data: { session: null }, error: null })
    auth.onAuthStateChange.mockReturnValue({ data: { subscription: { unsubscribe: vi.fn() } } })
    globalThis.fetch = vi.fn().mockResolvedValue(successfulApiResponse({ user: profile }))
  })

  it('verifies a passkey session with Flask before notifying the app', async () => {
    const user = userEvent.setup()
    auth.signInWithPasskey.mockResolvedValue({ data: { session }, error: null })
    render(<Login language="en" onLanguage={onLanguage} onAuthenticated={onAuthenticated} />)
    await user.click(screen.getByRole('button', { name: /Sign in with passkey/ }))

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith(
      'http://localhost:5000/api/v1/auth/session',
      expect.objectContaining({ method: 'POST', headers: { Authorization: 'Bearer test-access-token' } }),
    ))
    expect(onAuthenticated).toHaveBeenCalledWith(profile)
  })

  it('does not call Flask when Supabase sign-in fails', async () => {
    const user = userEvent.setup()
    auth.signInWithPasskey.mockResolvedValue({ data: null, error: new Error('passkey unavailable') })
    render(<Login language="en" onLanguage={onLanguage} onAuthenticated={onAuthenticated} />)
    await user.click(screen.getByRole('button', { name: /Sign in with passkey/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent('We could not sign you in')
    expect(globalThis.fetch).not.toHaveBeenCalled()
    expect(onAuthenticated).not.toHaveBeenCalled()
  })

  it('supports email sign-in and reports the backend profile to the app', async () => {
    const user = userEvent.setup()
    auth.signInWithPassword.mockResolvedValue({ data: { session }, error: null })
    render(<Login language="en" onLanguage={onLanguage} onAuthenticated={onAuthenticated} />)
    await user.type(screen.getByLabelText('Email address'), 'demo@example.test')
    await user.type(screen.getByLabelText('Password'), 'demo-password')
    await user.click(screen.getByRole('button', { name: 'Sign in with email' }))

    await waitFor(() => expect(onAuthenticated).toHaveBeenCalledWith(profile))
    expect(auth.signInWithPassword).toHaveBeenCalledWith({ email: 'demo@example.test', password: 'demo-password' })
  })

  it('allows citizen account creation and sends only the supported Supabase metadata', async () => {
    const user = userEvent.setup()
    auth.signUp.mockResolvedValue({ data: { session }, error: null })
    render(<Login language="en" onLanguage={onLanguage} onAuthenticated={onAuthenticated} />)
    await user.click(screen.getByRole('button', { name: 'First time? Create an account' }))
    await user.type(screen.getByLabelText('Full name'), 'Fatima Bibi')
    await user.type(screen.getByLabelText('Email address'), 'fatima@example.test')
    expect(screen.getByLabelText('Password')).toHaveAttribute('minlength', '6')
    await user.type(screen.getByLabelText('Password'), '123456')
    await user.click(screen.getByRole('button', { name: 'Create citizen account' }))

    expect(auth.signUp).toHaveBeenCalledWith(expect.objectContaining({
      email: 'fatima@example.test', password: '123456',
      options: { data: { full_name: 'Fatima Bibi', language: 'en' } },
    }))
    await waitFor(() => expect(onAuthenticated).toHaveBeenCalledWith(profile))
  })

  it('keeps a rejected backend JWT out of the authenticated app', async () => {
    const user = userEvent.setup()
    auth.signInWithPasskey.mockResolvedValue({ data: { session }, error: null })
    globalThis.fetch.mockResolvedValue({ ok: false, json: async () => ({ error: { code: 'UNAUTHENTICATED', message: 'bad token' } }) })
    render(<Login language="en" onLanguage={onLanguage} onAuthenticated={onAuthenticated} />)
    await user.click(screen.getByRole('button', { name: /Sign in with passkey/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent('We could not sign you in')
    expect(onAuthenticated).not.toHaveBeenCalled()
  })

  it('uses the parent language setting and updates on request', async () => {
    render(<Login language="ur" onLanguage={onLanguage} onAuthenticated={onAuthenticated} />)
    expect(document.documentElement.dir).toBe('rtl')
    fireEvent.click(screen.getByRole('button', { name: 'English' }))
    expect(onLanguage).toHaveBeenCalledWith('en')
  })
})
