import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { getBackendProfile } from './api/auth'
import { Notice, useT } from './components/Shared'
import Login from './pages/Login.jsx'
import Workspace from './pages/Workspace.jsx'
import { supabase } from './supabase'
import './style.css'

function App() {
  const [language, setLanguage] = useState(() => localStorage.getItem('relief-language') || 'ur')
  const [profile, setProfile] = useState(null)
  const [booting, setBooting] = useState(true)
  const [bootError, setBootError] = useState('')
  const t = useT(language)

  useEffect(() => {
    document.documentElement.lang = language
    document.documentElement.dir = language === 'ur' ? 'rtl' : 'ltr'
    localStorage.setItem('relief-language', language)
  }, [language])

  useEffect(() => {
    if ('serviceWorker' in navigator) navigator.serviceWorker.register('/service-worker.js').catch(() => {})
  }, [])

  useEffect(() => {
    let alive = true
    const loadProfile = async (accessToken, userId) => {
      try {
        const nextProfile = await getBackendProfile(accessToken)
        localStorage.setItem(`profile-cache:${userId || nextProfile.id}`, JSON.stringify(nextProfile))
        if (alive) { setProfile(nextProfile); setBootError('') }
      } catch (reason) {
        const cached = userId && (reason.status === 0 || !navigator.onLine)
          ? (() => { try { return JSON.parse(localStorage.getItem(`profile-cache:${userId}`)) } catch { return null } })()
          : null
        if (alive && cached?.id === userId) { setProfile(cached); setBootError('') }
        else if (alive) setBootError(t('backend_error'))
      }
    }
    if (!supabase) { setBooting(false); return undefined }
    supabase.auth.getSession().then(({ data, error }) => {
      if (!alive) return
      if (error) setBootError(t('backend_error'))
      if (data?.session?.access_token) loadProfile(data.session.access_token, data.session.user?.id).finally(() => alive && setBooting(false))
      else setBooting(false)
    })
    const { data: { subscription } } = supabase.auth.onAuthStateChange((event, session) => {
      if (event === 'SIGNED_OUT') { if (session?.user?.id) localStorage.removeItem(`profile-cache:${session.user.id}`); setProfile(null); setBootError('') }
      if (event === 'TOKEN_REFRESHED' && session?.access_token) loadProfile(session.access_token, session.user?.id)
    })
    return () => { alive = false; subscription.unsubscribe() }
  }, [])

  async function signOut() {
    const userId = profile?.id
    await supabase?.auth.signOut()
    if (userId) localStorage.removeItem(`profile-cache:${userId}`)
    setProfile(null)
  }

  if (booting) return <main className="boot-screen"><div className="brand-symbol">ر</div><span className="spinner" />{t('loading')}</main>
  if (!profile) return <>
    {bootError && <div className="boot-error"><Notice kind="error">{bootError}</Notice></div>}
    <Login language={language} onLanguage={setLanguage} onAuthenticated={(next) => { localStorage.setItem(`profile-cache:${next.id}`, JSON.stringify(next)); setProfile(next); setBootError('') }} />
  </>
  return <Workspace profile={profile} language={language} onLanguage={setLanguage} onSignOut={signOut} />
}

createRoot(document.getElementById('root')).render(<React.StrictMode><App /></React.StrictMode>)
