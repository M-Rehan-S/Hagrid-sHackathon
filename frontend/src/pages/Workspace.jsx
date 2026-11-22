import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { draftKey, newOperationId, queueKey, readLocal, writeLocal } from '../offline/store'
import { SpeakButton, useOnline, useT } from '../components/Shared'
import { HomeView, CasesView, CitizenView, ConsentView, ScamView, HelperView, OfficerView, RulesView, TwinView, KeysView, AnalyticsView, AuditView, HelpView } from './views'

const navByRole = {
  citizen: [['schemes', '🪙'], ['cases', '📄'], ['consent', '🔐'], ['profile', '👤'], ['scam', '🛡️'], ['help', '💬']],
  helper: [['home', '🏠'], ['citizens', '🤝'], ['cases', '📄'], ['scam', '🛡️']],
  officer: [['home', '🏠'], ['queue', '📥'], ['analytics', '📊'], ['scam', '🛡️']],
  admin: [['home', '🏠'], ['rules', '⚖️'], ['twin', '🧪'], ['keys', '🔑'], ['analytics', '📊'], ['audit', '📜']],
  auditor: [['home', '🏠'], ['audit', '📜'], ['audit_consents', '🔐'], ['analytics', '📊']],
}

const roleLabel = { citizen: 'role_citizen', helper: 'role_helper', officer: 'role_officer', admin: 'role_admin', auditor: 'role_auditor' }
const titleByPage = {
  home: 'nav_home', schemes: 'nav_schemes', cases: 'nav_cases', consent: 'nav_consent', scam: 'nav_scam',
  profile: 'nav_profile', citizens: 'nav_citizens', queue: 'nav_queue', rules: 'nav_rules', twin: 'nav_twin',
  keys: 'nav_keys', analytics: 'nav_analytics', audit: 'nav_audit', audit_consents: 'nav_audit_consents', help: 'nav_help',
}

export default function Workspace({ profile, language, onLanguage, onSignOut }) {
  const t = useT(language)
  const online = useOnline()
  const [page, setPage] = useState(profile.role === 'citizen' ? 'schemes' : 'home')
  const [selectedCitizen, setSelectedCitizen] = useState(null)
  const [syncMessage, setSyncMessage] = useState('')
  const [syncError, setSyncError] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [installPrompt, setInstallPrompt] = useState(null)
  const nav = navByRole[profile.role] || navByRole.citizen

  useEffect(() => {
    const capture = (event) => { event.preventDefault(); setInstallPrompt(event) }
    window.addEventListener('beforeinstallprompt', capture)
    return () => window.removeEventListener('beforeinstallprompt', capture)
  }, [])

  async function installApp() {
    if (!installPrompt) return
    await installPrompt.prompt()
    setInstallPrompt(null)
  }

  useEffect(() => {
    if (!online) return undefined
    let stopped = false
    async function flush() {
      const key = queueKey(profile.id)
      const pending = await readLocal(key, [])
      if (!pending.length) return
      setSyncMessage(t('syncing'))
      setSyncError(false)
      try {
        const batch = pending.slice(0, 100)
        const { results = [] } = await api.sync(batch)
        if (stopped) return
        const failed = results.filter((result) => result.status === 'error')
        const completedIds = new Set(results.filter((result) => result.status !== 'error').map((result) => result.client_op_id))
        const remaining = pending.filter((op) => !completedIds.has(op.client_op_id))
        const createMap = await readLocal(`pending-create-map:${profile.id}`, {})
        const localMappings = []
        for (const result of results.filter((item) => item.status !== 'error')) {
          const localCaseId = createMap[result.client_op_id]
          const serverCaseId = result.result?.case_id
          if (!localCaseId || !serverCaseId) continue
          localMappings.push({ local_case_id: localCaseId, case_id: serverCaseId })
          const draft = await readLocal(draftKey(profile.id, localCaseId), null)
          if (draft && Object.keys(draft).length) {
            const lastStep = await readLocal(`${draftKey(profile.id, localCaseId)}:last-step`, 'full_name')
            const patchOp = { client_op_id: newOperationId(), type: 'patch_form', case_id: serverCaseId, payload: { form_data_partial: draft, last_step: lastStep } }
            try {
              const patchResponse = await api.sync([patchOp])
              const patchResult = patchResponse.results?.[0]
              if (patchResult?.status === 'error') { failed.push(patchResult); remaining.push(patchOp) }
            } catch { remaining.push(patchOp); failed.push({ status: 'error' }) }
          }
          delete createMap[result.client_op_id]
        }
        const latestPending = await readLocal(key, [])
        const batchIds = new Set(pending.map((op) => op.client_op_id))
        const newlyQueued = latestPending.filter((op) => !batchIds.has(op.client_op_id))
        await writeLocal(key, [...remaining, ...newlyQueued])
        await writeLocal(`pending-create-map:${profile.id}`, createMap)
        setSyncError(failed.length > 0)
        setSyncMessage(failed.length ? t('sync_error') : t('sync_done'))
        window.dispatchEvent(new CustomEvent('relief-sync-complete', { detail: { results, local_mappings: localMappings } }))
        if (pending.length > batch.length && completedIds.size > 0 && !failed.length) window.setTimeout(flush, 0)
      } catch {
        if (!stopped) { setSyncError(true); setSyncMessage(t('sync_error')) }
      }
    }
    flush()
    return () => { stopped = true }
  }, [online, profile.id])

  function openPage(next) { setPage(next); setDrawerOpen(false) }
  const body = (() => {
    const shared = { profile, language, t, selectedCitizen, setSelectedCitizen, onNavigate: openPage }
    switch (page) {
      case 'schemes': return <HomeView {...shared} schemeMode />
      case 'cases': return <CasesView {...shared} />
      case 'consent': return <ConsentView {...shared} />
      case 'scam': return <ScamView {...shared} />
      case 'profile': return <CitizenView {...shared} />
      case 'help': return <HelpView {...shared} />
      case 'citizens': return <HelperView {...shared} />
      case 'queue': return <OfficerView {...shared} />
      case 'rules': return <RulesView {...shared} />
      case 'twin': return <TwinView {...shared} />
      case 'keys': return <KeysView {...shared} />
      case 'analytics': return <AnalyticsView {...shared} />
      case 'audit': return <AuditView {...shared} />
      case 'audit_consents': return <AuditView {...shared} consentMode />
      default: return <HomeView {...shared} />
    }
  })()

  return <div className={`app-frame role-${profile.role}`}>
    <aside className={`sidebar ${drawerOpen ? 'sidebar-open' : ''}`}>
      <div className="sidebar-brand"><span className="brand-symbol">ر</span><div><strong>{t('product')}</strong><small>{t(roleLabel[profile.role] || 'role_citizen')}</small></div></div>
      <nav aria-label={t('product')}>
        {nav.map(([key, icon], index) => <button key={key} className={`nav-item ${page === key ? 'nav-active' : ''}`} onClick={() => openPage(key)}>
          <span className="nav-icon" aria-hidden="true">{icon}</span><span className="nav-label">{t(titleByPage[key])}</span>
          {profile.role === 'citizen' && <span className="nav-number">{index + 1}</span>}
        </button>)}
      </nav>
      <div className="sidebar-bottom"><div className="sidebar-user"><span className="avatar">{profile.full_name?.slice(0, 1) || '•'}</span><div><strong>{profile.full_name}</strong><small>{profile.email}</small></div></div><button className="signout-link" onClick={onSignOut}>↪ {t('sign_out')}</button></div>
    </aside>
    <nav className="mobile-navigation" aria-label={t('product')}>
      {nav.map(([key, icon], index) => <button key={key} className={`nav-item ${page === key ? 'nav-active' : ''}`} onClick={() => openPage(key)}>
        <span className="nav-icon" aria-hidden="true">{icon}</span><span className="nav-label">{t(titleByPage[key])}</span>
        {profile.role === 'citizen' && <span className="nav-number">{index + 1}</span>}
      </button>)}
    </nav>
    <div className="main-column">
      <header className="topbar">
        <button className="mobile-menu" onClick={() => setDrawerOpen(!drawerOpen)} aria-label="Menu">☰</button>
        <div className="topbar-title"><span className="topbar-kicker">{t(roleLabel[profile.role] || 'role_citizen')}</span><strong>{t(titleByPage[page] || 'nav_home')}</strong></div>
        <div className="topbar-actions"><SpeakButton language={language} t={t} text={`${t(titleByPage[page] || 'nav_home')}. ${t('prototype')}`} /><span className={`connection ${online ? 'is-online' : 'is-offline'}`}><i />{online ? t('status_online') : t('status_offline')}</span>{installPrompt && <button className="language-toggle" onClick={installApp}>{t('install_app')}</button>}<button className="language-toggle" onClick={() => onLanguage(language === 'ur' ? 'en' : 'ur')}>{t('language')}</button></div>
      </header>
      {syncMessage && <div className={`sync-banner ${syncError ? 'sync-warning' : ''}`}>{syncMessage}</div>}
      <div className="prototype-banner"><span>ℹ️</span>{t('prototype')}</div>
      <main className="workspace-main" key={`${page}:${selectedCitizen?.id || ''}`}>{body}</main>
      <footer className="mobile-footer"><span>{t('prototype')}</span><button onClick={onSignOut}>{t('sign_out')}</button></footer>
    </div>
  </div>
}
