import { useEffect, useState } from 'react'
import { recordLogin } from '../api/auth'
import { useT, Notice, Button, SpeakButton } from '../components/Shared'
import { supabase } from '../supabase'

export default function Login({ language, onLanguage, onAuthenticated }) {
  const t = useT(language)
  const [mode, setMode] = useState('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    document.documentElement.lang = language
    document.documentElement.dir = language === 'ur' ? 'rtl' : 'ltr'
  }, [language])

  const clearNotice = () => { setMessage(''); setError('') }

  async function finishLogin(session) {
    if (!session?.access_token) throw new Error('SESSION_MISSING')
    const profile = await recordLogin(session.access_token)
    onAuthenticated(profile)
  }

  async function runAuth(action, fallback) {
    clearNotice()
    if (!supabase) { setError(t('auth_config_error')); return }
    setBusy(true)
    try {
      const { data, error: authError } = await action()
      if (authError) throw authError
      if (data?.session) await finishLogin(data.session)
      else if (mode === 'signup') { setMode('login'); setMessage(t('confirm_email')) }
      else if (mode === 'forgot') { setMode('login'); setMessage(t('reset_sent')) }
      else if (mode === 'reset') {
        const { data: sessionData } = await supabase.auth.getSession()
        if (sessionData?.session) await finishLogin(sessionData.session)
        setMode('login'); setMessage(t('password_updated'))
      }
    } catch (authError) {
      setError(authError?.message === 'BACKEND_AUTH_FAILED' ? t('backend_error') : fallback)
    } finally { setBusy(false) }
  }

  function submit(event) {
    event.preventDefault()
    if (mode === 'forgot') {
      runAuth(() => supabase.auth.resetPasswordForEmail(email, { redirectTo: window.location.origin }), t('unknown_error'))
      return
    }
    if (mode === 'reset') {
      runAuth(() => supabase.auth.updateUser({ password }), t('unknown_error'))
      return
    }
    if (mode === 'signup') {
      runAuth(() => supabase.auth.signUp({ email, password, options: { data: { full_name: fullName, language } } }), t('login_error'))
      return
    }
    runAuth(() => supabase.auth.signInWithPassword({ email, password }), t('login_error'))
  }

  useEffect(() => {
    if (!supabase) return undefined
    const { data: { subscription } } = supabase.auth.onAuthStateChange((event) => {
      if (event === 'PASSWORD_RECOVERY') setMode('reset')
    })
    return () => subscription.unsubscribe()
  }, [])

  async function passkeyLogin() {
    runAuth(() => supabase.auth.signInWithPasskey(), t('login_error'))
  }

  const title = mode === 'signup' ? t('signup') : mode === 'forgot' ? t('forgot_password') : mode === 'reset' ? t('set_password') : t('sign_in')
  return (
    <main className="auth-screen">
      <section className="auth-card" aria-labelledby="auth-title">
        <div className="brand-lockup"><span className="brand-symbol" aria-hidden="true">ر</span><div><strong>{t('product')}</strong><small>{t('prototype')}</small></div></div>
        <button className="language-toggle" onClick={() => onLanguage(language === 'ur' ? 'en' : 'ur')}>{t('language')}</button>
        <h1 id="auth-title">{title}</h1>
        <SpeakButton language={language} t={t} text={`${title}. ${t('passkey_help')}`} />
        <p className="auth-intro">{t('passkey_help')}</p>
        {mode === 'login' && <Button className="full-width" onClick={passkeyLogin} disabled={busy}>🔐 {busy ? t('loading') : t('passkey')}</Button>}
        <form className="auth-form" onSubmit={submit}>
          {mode === 'signup' && <label className="field">{t('name')}<input autoComplete="name" value={fullName} onChange={(e) => setFullName(e.target.value)} required /></label>}
          {mode !== 'reset' && <label className="field">{t('email')}<input type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>}
          {mode !== 'forgot' && <label className="field">{t('password')}<input type="password" autoComplete={mode === 'signup' || mode === 'reset' ? 'new-password' : 'current-password'} value={password} onChange={(e) => setPassword(e.target.value)} required minLength={6} /></label>}
          <Button type="submit" kind="secondary" className="full-width" disabled={busy}>{busy ? t('loading') : mode === 'signup' ? t('signup') : mode === 'forgot' ? t('reset_password') : mode === 'reset' ? t('set_password') : t('email_signin')}</Button>
        </form>
        {mode === 'login' && <button className="quiet-link" onClick={() => { setMode('signup'); clearNotice() }}>{t('toggle_signup')}</button>}
        {mode === 'login' && <button className="quiet-link" onClick={() => { setMode('forgot'); clearNotice() }}>{t('forgot_password')}</button>}
        {(mode === 'signup' || mode === 'forgot' || mode === 'reset') && <button className="quiet-link" onClick={() => { setMode('login'); clearNotice() }}>{t('sign_in')}</button>}
        {error && <Notice kind="error">{error}</Notice>}
        {message && <Notice>{message}</Notice>}
      </section>
    </main>
  )
}
