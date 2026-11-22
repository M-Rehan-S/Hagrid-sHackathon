import { useEffect, useState } from 'react'
import { getBackendProfile, recordLogin } from '../api/auth'
import en from '../i18n/en.json'
import ur from '../i18n/ur.json'
import { supabase } from '../supabase'

export default function Login() {
  const [mode, setMode] = useState('login')
  const [language, setLanguage] = useState('ur')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [profile, setProfile] = useState(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const t = language === 'ur' ? ur : en

  useEffect(() => {
    document.documentElement.lang = language
    document.documentElement.dir = language === 'ur' ? 'rtl' : 'ltr'
  }, [language])

  function friendlyError(error, fallback) {
    if (error?.message === 'BACKEND_AUTH_FAILED') return t.backend_failed
    return fallback
  }

  useEffect(() => {
    if (!supabase) return
    let cancelled = false
    const { data: { subscription } } = supabase.auth.onAuthStateChange((event) => {
      if (event === 'PASSWORD_RECOVERY') {
        setProfile(null)
        setMode('reset')
        setMessage('')
        setError('')
      }
    })

    supabase.auth.getSession().then(async ({ data, error: sessionError }) => {
      if (cancelled || sessionError || !data.session) return
      try {
        const user = await getBackendProfile(data.session.access_token)
        if (!cancelled) setProfile(user)
      } catch (profileError) {
        if (!cancelled) setError(friendlyError(profileError, t.backend_failed))
      }
    })

    return () => {
      cancelled = true
      subscription.unsubscribe()
    }
  }, [language])

  function resetNotice() {
    setMessage('')
    setError('')
  }

  async function finishLogin(session) {
    if (!session?.access_token) throw new Error('Supabase did not return a sign-in session.')
    const user = await recordLogin(session.access_token)
    setProfile(user)
    setPassword('')
  }

  async function signInWithPasskey() {
    resetNotice()
    if (!supabase) return setError(t.missing_config)
    setBusy(true)
    try {
      const { data, error: authError } = await supabase.auth.signInWithPasskey()
      if (authError) throw authError
      await finishLogin(data.session)
    } catch (authError) {
      setError(friendlyError(authError, t.passkey_failed))
    } finally {
      setBusy(false)
    }
  }

  async function signInWithPassword(event) {
    event.preventDefault()
    resetNotice()
    if (!supabase) return setError(t.missing_config)
    setBusy(true)
    try {
      const { data, error: authError } = await supabase.auth.signInWithPassword({ email, password })
      if (authError) throw authError
      await finishLogin(data.session)
    } catch (authError) {
      setError(friendlyError(authError, t.login_failed))
    } finally {
      setBusy(false)
    }
  }

  async function createAccount(event) {
    event.preventDefault()
    resetNotice()
    if (!supabase) return setError(t.missing_config)
    setBusy(true)
    try {
      const { data, error: authError } = await supabase.auth.signUp({
        email,
        password,
        options: { data: { full_name: fullName, language: 'ur' } },
      })
      if (authError) throw authError
      if (data.session) {
        await finishLogin(data.session)
        setMessage(t.setup_done)
      } else {
        setMode('login')
        setMessage(t.confirm_email)
      }
    } catch (authError) {
      setError(friendlyError(authError, t.signup_failed))
    } finally {
      setBusy(false)
    }
  }

  async function sendPasswordReset(event) {
    event.preventDefault()
    resetNotice()
    if (!supabase) return setError(t.missing_config)
    setBusy(true)
    try {
      const { error: resetError } = await supabase.auth.resetPasswordForEmail(email, {
        redirectTo: window.location.origin,
      })
      if (resetError) throw resetError
      setMode('login')
      setMessage(t.reset_sent)
    } catch {
      setError(t.reset_failed)
    } finally {
      setBusy(false)
    }
  }

  async function updatePassword(event) {
    event.preventDefault()
    resetNotice()
    if (!supabase) return setError(t.missing_config)
    setBusy(true)
    try {
      const { error: updateError } = await supabase.auth.updateUser({ password })
      if (updateError) throw updateError
      const { data } = await supabase.auth.getSession()
      setMode('login')
      setMessage(t.password_updated)
      if (data.session) await finishLogin(data.session)
    } catch {
      setError(t.reset_failed)
    } finally {
      setBusy(false)
    }
  }

  async function addPasskey() {
    resetNotice()
    if (!supabase) return setError(t.missing_config)
    setBusy(true)
    try {
      const { error: passkeyError } = await supabase.auth.registerPasskey()
      if (passkeyError) throw passkeyError
      setMessage(t.passkey_added)
    } catch (passkeyError) {
      setError(friendlyError(passkeyError, t.passkey_setup_failed))
    } finally {
      setBusy(false)
    }
  }

  async function signOut() {
    if (!supabase) return
    await supabase.auth.signOut()
    setProfile(null)
    setMessage(t.signed_out)
    setError('')
  }

  if (profile && mode !== 'reset') {
    return (
      <main className="page-shell">
        <section className="card account-card" aria-labelledby="welcome-heading">
          <div className="brand-mark" aria-hidden="true">ر</div>
          <button className="language-button" onClick={() => setLanguage(language === 'ur' ? 'en' : 'ur')}>{t.language}</button>
          <p className="eyebrow">{t.product}</p>
          <h1 id="welcome-heading">{t.welcome.replace('{name}', profile.full_name)}</h1>
          <p className="account-role">{t.signed_in_as}: <strong>{profile.role}</strong></p>
          <button className="primary-button" onClick={addPasskey} disabled={busy}>
            {busy ? t.please_wait : t.add_passkey}
          </button>
          <p className="helper-text">{t.passkey_setup_help}</p>
          <button className="text-button" onClick={signOut}>{t.sign_out}</button>
          <Notice message={message} error={error} />
        </section>
      </main>
    )
  }

  return (
    <main className="page-shell">
      <section className="card login-card" aria-labelledby="login-heading">
        <div className="brand-mark" aria-hidden="true">ر</div>
        <button className="language-button" onClick={() => setLanguage(language === 'ur' ? 'en' : 'ur')}>{t.language}</button>
        <p className="eyebrow">{t.product}</p>
        <h1 id="login-heading">{mode === 'forgot' || mode === 'reset' ? (mode === 'forgot' ? t.forgot_password : t.set_new_password) : t.title}</h1>
        <p className="intro">{mode === 'reset' ? t.reset_intro : mode === 'forgot' ? t.forgot_intro : t.intro}</p>

        {mode === 'login' && (
          <>
            <button className="primary-button passkey-button" onClick={signInWithPasskey} disabled={busy}>
              {busy ? t.please_wait : t.passkey_button}
            </button>
            <p className="helper-text">{t.passkey_help}</p>
          </>
        )}

        {(mode === 'login' || mode === 'signup') && (
          <button className="text-button" type="button" onClick={() => { setMode(mode === 'login' ? 'signup' : 'login'); resetNotice() }}>
            {mode === 'login' ? t.first_time : t.existing_account}
          </button>
        )}
        {mode === 'forgot' && (
          <button className="text-button" type="button" onClick={() => { setMode('login'); resetNotice() }}>{t.existing_account}</button>
        )}

        <form className="password-form" onSubmit={mode === 'signup' ? createAccount : mode === 'forgot' ? sendPasswordReset : mode === 'reset' ? updatePassword : signInWithPassword}>
          {mode === 'signup' && (
            <label>
              {t.your_name}
              <input autoComplete="name" value={fullName} onChange={(event) => setFullName(event.target.value)} required />
            </label>
          )}
          {mode !== 'reset' && (
            <label>
              {t.email}
              <input type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
            </label>
          )}
          {mode !== 'forgot' && (
            <label>
              {mode === 'signup' ? t.setup_password : mode === 'reset' ? t.set_new_password : t.recovery_password}
              <input type="password" autoComplete={mode === 'signup' || mode === 'reset' ? 'new-password' : 'current-password'} value={password} onChange={(event) => setPassword(event.target.value)} required minLength={8} />
            </label>
          )}
          <button className="secondary-button" type="submit" disabled={busy}>
            {busy ? t.please_wait : mode === 'signup' ? t.create_account : mode === 'forgot' ? t.send_reset_link : mode === 'reset' ? t.set_new_password : t.sign_in_email}
          </button>
        </form>
        {mode === 'login' && (
          <button className="text-button" type="button" onClick={() => { setMode('forgot'); resetNotice() }}>{t.forgot_password}</button>
        )}

        <Notice message={message} error={error} />
        <p className="prototype-note">{t.prototype}</p>
      </section>
    </main>
  )
}

function Notice({ message, error }) {
  if (error) return <p className="notice error" role="alert">{error}</p>
  if (message) return <p className="notice" role="status">{message}</p>
  return null
}
