import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api/client'
import { draftKey, newOperationId, queueKey, readLocal, writeLocal } from '../../offline/store'
import { Button, EmptyState, ErrorNotice, Field, Loading, Notice, SpeakButton, StatusPill, VoiceButton, formatDate } from '../../components/Shared'

const icons = { full_name: '👤', father_name: '🧑‍🤝‍🧑', cnic: '🪪', dob: '🎂', district: '📍', household_size: '🏠', monthly_income: '💰', is_widow: '🌸', phone: '📱', documents: '📎' }
const steps = ['cnic', 'full_name', 'father_name', 'dob', 'district', 'household_size', 'monthly_income', 'is_widow', 'phone', 'documents']
const labels = Object.fromEntries(steps.slice(0, -1).map((key) => [key, `step_${key === 'full_name' ? 'name' : key === 'father_name' ? 'father' : key === 'household_size' ? 'household' : key === 'monthly_income' ? 'income' : key === 'is_widow' ? 'widow' : key}`]))
const valueType = { cnic: 'text', dob: 'date', district: 'select', household_size: 'number', monthly_income: 'number', is_widow: 'boolean', phone: 'tel' }

export async function discoverCitizen(profile) {
  const key = `citizen-id:${profile.id}`
  const cachedCitizenKey = `citizen:${profile.id}`
  const stored = localStorage.getItem(key)
  if (stored) {
    try {
      const citizen = await api.citizen(stored)
      await writeLocal(cachedCitizenKey, citizen)
      return citizen
    } catch (error) {
      if (!navigator.onLine || error.status === 0) return await readLocal(cachedCitizenKey, { id: stored })
      localStorage.removeItem(key)
    }
  }
  let cases
  try {
    cases = await api.cases()
    await writeLocal(`cases:${profile.id}`, cases || [])
  } catch (error) {
    if (navigator.onLine && error.status !== 0) throw error
    cases = await readLocal(`cases:${profile.id}`, [])
    const cachedCitizen = await readLocal(cachedCitizenKey, null)
    if (cachedCitizen?.id) return cachedCitizen
  }
  if (cases?.[0]?.citizen_id) {
    localStorage.setItem(key, cases[0].citizen_id)
    try {
      const citizen = await api.citizen(cases[0].citizen_id)
      await writeLocal(cachedCitizenKey, citizen)
      return citizen
    } catch { return await readLocal(cachedCitizenKey, { id: cases[0].citizen_id }) }
  }
  return null
}

export function HomeView({ profile, language, t, onNavigate, schemeMode = false }) {
  const [cases, setCases] = useState([])
  const [summary, setSummary] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(!schemeMode)
  const role = profile.role
  const load = useCallback(async () => {
    if (schemeMode) return
    setLoading(true); setError(null)
    try {
      if (role === 'citizen' || role === 'helper' || role === 'officer') setCases(await api.cases())
      if (role === 'admin' || role === 'auditor' || role === 'officer') setSummary(await api.evaluation())
    } catch (reason) { setError(reason) } finally { setLoading(false) }
  }, [role, schemeMode])
  useEffect(() => { load() }, [load])

  if (schemeMode) return <section className="page-content">
    <div className="hero-card citizen-hero"><div><span className="eyebrow">{t('nav_schemes')}</span><h1>{t('scheme_title')}</h1><p>{t('scheme_intro')}</p><p className="subtle-copy">{t('scheme_amount')}</p><Button onClick={() => onNavigate('cases')}>📝 {t('start_application')}</Button></div><div className="hero-art" aria-hidden="true">🪙</div></div>
    <div className="callout-card"><span>🛡️</span><p>{t('prototype_note')}</p></div>
  </section>

  const stats = summary?.live
  const routeCounts = stats?.cases_by_route || {}
  const totalCases = Object.values(routeCounts).reduce((sum, count) => sum + count, 0)
  const counts = [
    [t('application_count'), cases.length || totalCases, '📄'],
    [t('pending_count'), cases.filter((item) => ['submitted', 'in_review'].includes(item.status)).length || stats?.human_handoffs || 0, '⏳'],
    [t('approved_count'), cases.filter((item) => item.status === 'approved').length || stats?.auto_approved_count || 0, '✅'],
    [t('human_count'), cases.filter((item) => item.route === 'human_review').length || stats?.human_handoffs || 0, '🧑‍⚖️'],
  ]
  return <section className="page-content">
    <div className="welcome-row"><div><span className="eyebrow">{t('product')}</span><h1>{t('welcome', { name: profile.full_name })}</h1><p>{t('home_intro')}</p></div><SpeakButton language={language} t={t} text={`${t('welcome', { name: profile.full_name })}. ${t('home_intro')}`} /></div>
    {loading ? <Loading t={t} /> : <>
      <ErrorNotice error={error} t={t} onRetry={load} />
      <div className="stats-grid">{counts.map(([label, value, icon]) => <article className="stat-card" key={label}><span className="stat-icon">{icon}</span><span className="stat-label">{label}</span><strong>{value}</strong></article>)}</div>
      {stats?.cases_by_route && <article className="panel"><h2>{t('cases_by_route')}</h2><div className="route-summary">{Object.entries(stats.cases_by_route).map(([route, count]) => <div key={route}><span>{t(`route_${route}`)}</span><strong>{count}</strong></div>)}</div></article>}
      <div className="action-grid">
        {(role === 'citizen' || role === 'helper') && <button className="action-card" onClick={() => onNavigate(role === 'citizen' ? 'schemes' : 'cases')}><span>🪙</span><strong>{t('start_application')}</strong><small>{t('scheme_intro')}</small></button>}
        {role === 'citizen' && <button className="action-card" onClick={() => onNavigate('cases')}><span>📄</span><strong>{t('view_status')}</strong><small>{t('application_title')}</small></button>}
        {role === 'helper' && <button className="action-card" onClick={() => onNavigate('citizens')}><span>🤝</span><strong>{t('nav_citizens')}</strong><small>{t('link_pending')}</small></button>}
        {role === 'officer' && <button className="action-card" onClick={() => onNavigate('queue')}><span>📥</span><strong>{t('queue_title')}</strong><small>{t('human_count')}: {stats?.human_handoffs ?? 0}</small></button>}
        {role === 'admin' && <button className="action-card" onClick={() => onNavigate('rules')}><span>⚖️</span><strong>{t('rules_title')}</strong><small>{t('create_draft')}</small></button>}
        {role === 'auditor' && <button className="action-card" onClick={() => onNavigate('audit')}><span>📜</span><strong>{t('audit_title')}</strong><small>{t('verify_chain')}</small></button>}
        <button className="action-card" onClick={() => onNavigate('scam')}><span>🛡️</span><strong>{t('quick_scam')}</strong><small>{t('check_message_help')}</small></button>
      </div>
      {cases.length > 0 && <article className="panel"><div className="panel-heading"><h2>{t('application_title')}</h2><button className="inline-link" onClick={() => onNavigate(role === 'officer' ? 'queue' : 'cases')}>{t('more')} →</button></div><CaseList items={cases.slice(0, 4)} t={t} language={language} /></article>}
      {role === 'admin' && <div className="callout-card"><span>ℹ️</span><p>{t('unsupported_users')}</p></div>}
    </>}
  </section>
}

function CaseList({ items, t, language, onOpen }) {
  if (!items.length) return <p className="empty-inline">{t('no_cases')}</p>
  return <div className="case-list">{items.map((item) => <button className="case-row" key={item.id} onClick={() => onOpen?.(item)}>
    <span className="case-symbol">📄</span><span className="case-main"><strong>{item.form_data?.full_name || t('case_details')}</strong><small>{t('case_updated')}: {formatDate(item.updated_at || item.created_at, language)}</small></span>
    <span className="case-meta">{item.route && <small>{t(`route_${item.route}`)}</small>}<StatusPill value={item.status} t={t} /></span><span className="row-arrow">›</span>
  </button>)}</div>
}

export function CasesView({ profile, language, t, selectedCitizen, onNavigate }) {
  const [citizen, setCitizen] = useState(null)
  const [cases, setCases] = useState([])
  const [activeCase, setActiveCase] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState('')
  const [setupBusy, setSetupBusy] = useState(false)

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const [caseRows, citizenProfile] = await Promise.all([
        api.cases().then(async (rows) => {
          const localRows = await readLocal(`cases:${profile.id}`, [])
          const pendingRows = localRows.filter((item) => item.id?.startsWith('local-'))
          const merged = [...pendingRows, ...(rows || [])]
          await writeLocal(`cases:${profile.id}`, merged)
          return merged
        }).catch(async (reason) => {
          if (navigator.onLine && reason.status !== 0) throw reason
          setNotice(t('save_offline'))
          return await readLocal(`cases:${profile.id}`, [])
        }),
        profile.role === 'citizen' ? discoverCitizen(profile) : Promise.resolve(selectedCitizen),
      ])
      setCases(caseRows || [])
      setCitizen(citizenProfile || (caseRows?.[0] ? { id: caseRows[0].citizen_id } : null))
    } catch (reason) { setError(reason) } finally { setLoading(false) }
  }, [profile, selectedCitizen])
  useEffect(() => { load() }, [load])
  useEffect(() => {
    const onSync = async (event) => {
      const mappings = event.detail?.local_mappings || []
      const currentMapping = mappings.find((item) => item.local_case_id === activeCase)
      setCases((current) => current.map((item) => {
        const mapping = mappings.find((entry) => entry.local_case_id === item.id)
        return mapping ? { ...item, id: mapping.case_id, pending_sync: false } : item
      }))
      const cached = await readLocal(`cases:${profile.id}`, [])
      await writeLocal(`cases:${profile.id}`, cached.map((item) => {
        const mapping = mappings.find((entry) => entry.local_case_id === item.id)
        return mapping ? { ...item, id: mapping.case_id, pending_sync: false } : item
      }))
      for (const mapping of mappings) {
        const draft = await readLocal(draftKey(profile.id, mapping.local_case_id), null)
        if (draft) await writeLocal(draftKey(profile.id, mapping.case_id), draft)
      }
      if (currentMapping) setActiveCase(currentMapping.case_id)
    }
    window.addEventListener('relief-sync-complete', onSync)
    return () => window.removeEventListener('relief-sync-complete', onSync)
  }, [activeCase, profile.id])

  async function createProfile(event) {
    event.preventDefault(); setSetupBusy(true); setError(null)
    const data = new FormData(event.currentTarget)
    try {
      const created = await api.createCitizen({
        full_name: data.get('full_name'),
      })
      setCitizen(created.citizen)
      localStorage.setItem(`citizen-id:${profile.id}`, created.citizen.id)
      await writeLocal(`citizen:${profile.id}`, created.citizen)
      setNotice(t('profile_saved'))
    } catch (reason) { setError(reason) } finally { setSetupBusy(false) }
  }

  async function startNew() {
    setError(null); setNotice('')
    try {
      if (!citizen?.id) throw new Error(t('no_citizen_id'))
      let created
      try {
        if (!navigator.onLine) throw Object.assign(new Error('offline'), { status: 0 })
        created = await api.createCase(citizen.id)
      } catch (reason) {
        if (navigator.onLine && reason.status !== 0) throw reason
        const localId = `local-${newOperationId()}`
        const clientOpId = newOperationId()
        const key = queueKey(profile.id)
        const pending = await readLocal(key, [])
        pending.push({ client_op_id: clientOpId, type: 'create_case', payload: { citizen_id: citizen.id, case_type: 'relief_claim' } })
        await writeLocal(key, pending)
        const mapping = await readLocal(`pending-create-map:${profile.id}`, {})
        mapping[clientOpId] = localId
        await writeLocal(`pending-create-map:${profile.id}`, mapping)
        created = { id: localId, citizen_id: citizen.id, status: 'draft', form_data: {}, pending_sync: true }
        setNotice(t('save_offline'))
      }
      setCases((current) => [created, ...current])
      await writeLocal(`cases:${profile.id}`, [created, ...cases])
      await writeLocal(`case:${profile.id}:${created.id}`, created)
      setActiveCase(created.id)
    } catch (reason) { setError(reason) }
  }

  if (loading) return <section className="page-content"><Loading t={t} /></section>
  if (profile.role === 'citizen' && !citizen?.id) return <section className="page-content narrow-content">
    <div className="panel setup-panel"><span className="large-icon">🪪</span><h1>{t('citizen_setup_title')}</h1><p>{t('citizen_setup_intro')}</p>
      <form className="stack-form" onSubmit={createProfile}>
        <Field label={t('full_name')}><input name="full_name" autoComplete="name" defaultValue={profile.full_name || ''} required maxLength={200} /></Field>
        <Button type="submit" disabled={setupBusy}>{setupBusy ? t('loading_data') : t('continue_application')}</Button>
      </form>
      <ErrorNotice error={error} t={t} />
    </div>
  </section>

  if (activeCase) return <CaseWorkspace key={activeCase} caseId={activeCase} initial={cases.find((item) => item.id === activeCase)} profile={profile} citizen={citizen} language={language} t={t} onBack={() => { setActiveCase(null); load() }} onNavigate={onNavigate} />

  return <section className="page-content">
    <div className="page-heading-row"><div><span className="eyebrow">{profile.role === 'officer' ? t('queue_title') : t('nav_cases')}</span><h1>{t('application_title')}</h1></div>{(profile.role === 'citizen' || profile.role === 'helper') && <Button onClick={startNew}>＋ {t('new_application')}</Button>}</div>
    <Notice>{notice}</Notice><ErrorNotice error={error} t={t} onRetry={load} />
    {cases.length ? <CaseList items={cases} t={t} language={language} onOpen={(item) => setActiveCase(item.id)} /> : <EmptyState icon="📄" title={t('no_cases')} detail={profile.role === 'citizen' ? t('scheme_intro') : t('link_pending')} action={profile.role === 'citizen' || profile.role === 'helper' ? <Button onClick={startNew}>{t('new_application')}</Button> : null} />}
  </section>
}

function CaseWorkspace({ caseId, initial, profile, citizen, language, t, onBack, onNavigate }) {
  const [caseData, setCaseData] = useState(initial)
  const [stepIndex, setStepIndex] = useState(() => Math.max(0, steps.indexOf(initial?.last_step)))
  const [form, setForm] = useState({ full_name: citizen?.full_name || '', ...(initial?.form_data || {}) })
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState('')
  const [fieldError, setFieldError] = useState('')
  const [decision, setDecision] = useState(null)
  const [complaintText, setComplaintText] = useState('')
  const [complaintReference, setComplaintReference] = useState('')
  const editing = ['draft', 'needs_info'].includes(caseData?.status)
  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      let next
      try {
        if (caseId.startsWith('local-')) throw Object.assign(new Error('local draft'), { status: 0 })
        next = await api.case(caseId)
        await writeLocal(`case:${profile.id}:${caseId}`, next)
      } catch (reason) {
        if (navigator.onLine && reason.status !== 0) throw reason
        next = await readLocal(`case:${profile.id}:${caseId}`, initial || null)
        if (!next) throw reason
      }
      const localDraft = await readLocal(draftKey(profile.id, caseId), null)
      const localLastStep = await readLocal(`${draftKey(profile.id, caseId)}:last-step`, null)
      setCaseData(next)
      setForm({ full_name: citizen?.full_name || '', ...(next.form_data || {}), ...(localDraft || {}) })
      const savedIndex = steps.indexOf(next.last_step)
      const localSavedIndex = steps.indexOf(localLastStep)
      const lastSavedIndex = localSavedIndex >= 0 ? localSavedIndex : savedIndex
      setStepIndex(lastSavedIndex >= 0 ? Math.min(lastSavedIndex + 1, steps.length - 1) : 0)
    } catch (reason) { setError(reason) } finally { setLoading(false) }
  }, [caseId, profile.id, citizen?.full_name])
  useEffect(() => { load() }, [load])

  async function saveStep(nextIndex = stepIndex) {
    const field = steps[nextIndex]
    if (field === 'documents') return
    const value = form[field]
    const partial = { [field]: value === '' ? null : value }
    const updated = { ...form, ...partial }
    setForm(updated)
    await writeLocal(draftKey(profile.id, caseId), updated)
    await writeLocal(`${draftKey(profile.id, caseId)}:last-step`, field)
    if (caseId.startsWith('local-')) {
      const localCase = { ...(caseData || initial || {}), form_data: updated, last_step: field }
      await writeLocal(`case:${profile.id}:${caseId}`, localCase)
      setNotice(t('save_offline'))
      return
    }
    const queuePatch = async () => {
      const key = queueKey(profile.id)
      const pending = await readLocal(key, [])
      pending.push({ client_op_id: newOperationId(), type: 'patch_form', case_id: caseId, payload: { form_data_partial: partial, last_step: field } })
      await writeLocal(key, pending)
      setNotice(t('save_offline'))
    }
    if (!navigator.onLine) {
      await queuePatch()
      return
    }
    try {
      const result = await api.patchForm(caseId, partial, field)
      setCaseData(result.case)
      setNotice(t('application_saved'))
    } catch (reason) {
      if (reason.status === 0) { await queuePatch(); return }
      throw reason
    }
  }

  async function next() {
    if (field === 'cnic' && !/^\d{13}$/.test(String(form.cnic || ''))) {
      setFieldError(t('cnic_invalid'))
      return
    }
    if (field === 'full_name' && !String(form.full_name || '').trim()) {
      setFieldError(t('name_required'))
      return
    }
    setFieldError('')
    setBusy(true); setError(null)
    try {
      await saveStep()
      if (stepIndex < steps.length - 1) setStepIndex((n) => n + 1)
    } catch (reason) { setError(reason) } finally { setBusy(false) }
  }

  async function upload(event) {
    const file = event.target.files?.[0]
    if (!file) return
    setBusy(true); setError(null)
    try {
      await api.uploadDocument(caseId, file, file.type.startsWith('image/') ? 'cnic_photo' : 'supporting_doc')
      setNotice(t('document_uploaded'))
    } catch (reason) { setError(reason) } finally { setBusy(false); event.target.value = '' }
  }

  async function submit() {
    setBusy(true); setError(null); setNotice('')
    try {
      const result = await api.submitCase(caseId)
      setCaseData(result.case)
      if (result.missing_fields?.length) {
        const missing = result.missing_fields.map((key) => t(key)).join(', ')
        setError(new Error(`${t('needs_fields')} ${missing}`))
        setStepIndex(Math.max(0, steps.findIndex((key) => result.missing_fields.includes(key))))
        return
      }
      setDecision(result.decision)
      setNotice(t('application_sent'))
    } catch (reason) {
      setError(reason)
      if (reason.code === 'CONSENT_REQUIRED' && profile.role === 'citizen') onNavigate('consent')
    } finally { setBusy(false) }
  }

  async function fileComplaint(event) {
    event.preventDefault(); setBusy(true); setError(null); setComplaintReference('')
    try {
      const result = await api.complaint(caseId, complaintText)
      setComplaintReference(result.complaint_reference)
      setComplaintText('')
    } catch (reason) { setError(reason) } finally { setBusy(false) }
  }

  if (loading) return <Loading t={t} />
  if (decision || ['submitted', 'in_review', 'approved', 'rejected', 'closed'].includes(caseData?.status)) return <div className="case-detail-view">
    <button className="back-link" onClick={onBack}>← {t('back')}</button>
    <div className="panel receipt-panel"><div className="receipt-icon">{caseData.status === 'approved' ? '✅' : '📨'}</div><h1>{t('case_details')}</h1><StatusPill value={caseData.status} t={t} /><p>{caseData.route ? t(`route_${caseData.route}`) : ''}</p>
      {decision?.reason_en && <p className="reason-card">{language === 'ur' ? decision.reason_ur : decision.reason_en}</p>}
      {['citizen', 'helper'].includes(profile.role) && <form className="stack-form complaint-form" onSubmit={fileComplaint}><Field label={t('complaint_text')}><textarea value={complaintText} onChange={(event) => setComplaintText(event.target.value)} maxLength={3000} required /></Field><Button type="submit" kind="secondary" disabled={busy}>{t('submit_complaint')}</Button>{complaintReference && <Notice>{t('complaint_reference', { reference: complaintReference })}</Notice>}</form>}
      <Button kind="secondary" onClick={load}>{t('refresh')}</Button>
    </div>
    <CaseHistory item={caseData} t={t} language={language} />
    <ErrorNotice error={error} t={t} onRetry={load} />
  </div>

  const field = steps[stepIndex]
  const currentLabel = field === 'documents' ? t('step_documents') : t(labels[field])
  const currentValue = form[field] ?? ''
  const voiceText = (text) => {
    setFieldError('')
    let value = text
    if (['household_size', 'monthly_income'].includes(field)) value = Number.parseInt(String(text).replace(/[^0-9]/g, ''), 10) || ''
    if (field === 'is_widow' && typeof text === 'string') {
      const normalized = text.trim().toLowerCase()
      if (['yes', 'y', 'true', 'ہاں', 'جی ہاں', 'جی'].includes(normalized)) value = true
      else if (['no', 'n', 'false', 'نہیں', 'نا'].includes(normalized)) value = false
    }
    setForm((f) => ({ ...f, [field]: value }))
  }
  return <div className="case-detail-view">
    <button className="back-link" onClick={onBack}>← {t('back')}</button>
    <div className="panel question-panel">
      <div className="question-icon">{icons[field]}</div>
      <SpeakButton language={language} t={t} text={currentLabel} />
      <h1>{currentLabel}</h1>
      {field === 'documents' ? <Field label={t('upload_document')}><input key={field} type="file" accept="image/*,.pdf" onChange={upload} disabled={!editing || busy} /></Field> : <Field label={t(field)}>
        {field === 'district' ? <select key={field} value={currentValue} onChange={(e) => voiceText(e.target.value)} disabled={!editing}><option value="">—</option><option>Karachi East</option><option>Karachi West</option><option>Karachi South</option><option>Thatta</option><option>Badin</option></select>
          : field === 'is_widow' ? <div className="choice-row">{[true, false].map((option) => <button key={String(option)} type="button" className={`choice-button ${currentValue === option ? 'choice-selected' : ''}`} onClick={() => voiceText(option)} disabled={!editing}>{option ? '🌸' : '👤'} {t(option ? 'yes' : 'no')}</button>)}</div>
            : <input key={field} type={valueType[field] || 'text'} inputMode={field === 'cnic' || field === 'phone' || field.includes('income') || field.includes('size') ? 'numeric' : undefined} pattern={field === 'cnic' ? '[0-9]{13}' : undefined} maxLength={field === 'cnic' ? 13 : undefined} min={field === 'household_size' ? 1 : 0} value={currentValue} onChange={(e) => { setFieldError(''); voiceText(valueType[field] === 'number' ? (e.target.value === '' ? '' : Number(e.target.value)) : e.target.value) }} disabled={!editing} autoComplete={field === 'full_name' ? 'name' : 'off'} />}
      </Field>}
      {field !== 'documents' && editing && <VoiceButton language={language} t={t} onText={voiceText} />}
      {!editing && <p className="subtle-copy">{t(`status_${caseData.status}`)}</p>}
      {fieldError && <Notice kind="error">{fieldError}</Notice>}<Notice>{notice}</Notice><ErrorNotice error={error} t={t} />
      <div className="form-actions">
        <Button kind="secondary" onClick={() => setStepIndex((n) => Math.max(0, n - 1))} disabled={stepIndex === 0 || busy}>{t('back')}</Button>
        {stepIndex < steps.length - 1 ? <Button onClick={next} disabled={!editing || busy}>{busy ? t('save') : t('next')} →</Button> : editing ? <Button onClick={submit} disabled={busy}>{busy ? t('submitting') : t('submit_application')}</Button> : <Button kind="secondary" onClick={onBack}>{t('back')}</Button>}
      </div>
    </div>
    <div className="form-progress"><div className="progress-label"><span>{t('question_progress', { current: stepIndex + 1, total: steps.length })}</span><span>{Math.round(((stepIndex + 1) / steps.length) * 100)}%</span></div><div className="progress-track"><span style={{ width: `${((stepIndex + 1) / steps.length) * 100}%` }} /></div><div className="progress-icons">{steps.map((key, index) => <span className={index <= stepIndex ? 'progress-current' : ''} key={key} title={t(labels[key] || 'upload_document')}>{icons[key]}</span>)}</div></div>
    <CaseHistory item={caseData} t={t} language={language} />
  </div>
}

function CaseHistory({ item, t, language }) {
  if (!item) return null
  const officerDecision = [...(item.events || [])].reverse().find((event) => event.event_type === 'decision' && event.note)
  return <div className="panel case-summary"><h2>{t('case_details')}</h2><div className="detail-grid"><div><small>{t('case_status')}</small><StatusPill value={item.status} t={t} /></div><div><small>{t('case_route')}</small><strong>{t(`route_${item.route || 'unrouted'}`)}</strong></div><div><small>{t('case_updated')}</small><strong>{formatDate(item.updated_at, language)}</strong></div></div>
    {item.status === 'rejected' && officerDecision && <article className="decision-card officer-reason"><h3>{t('officer_rejection_reason')}</h3><p>{officerDecision.note}</p></article>}
    {item.decisions?.map((decision) => <div className="decision-card" key={decision.id}><div className="panel-heading"><strong>{t('reason')}</strong><span>{decision.actor_type}</span></div><p>{language === 'ur' ? decision.reason_ur : decision.reason_en}</p>{decision.trace && <details><summary>{t('decisions')} · {t('case_confidence')} {Math.round((decision.confidence || 0) * 100)}%</summary><pre>{JSON.stringify(decision.trace, null, 2)}</pre></details>}</div>)}
    {!!item.events?.length && <details className="history-details"><summary>{t('activity')}</summary>{item.events.map((event) => <div key={event.id} className="history-row"><span>{event.event_type}</span><time>{formatDate(event.created_at, language)}</time>{event.note && <p>{event.note}</p>}</div>)}</details>}
  </div>
}

export function CitizenView({ profile, language, t }) {
  const [citizen, setCitizen] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState('')
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try { setCitizen(await discoverCitizen(profile)) } catch (reason) { setError(reason) } finally { setLoading(false) }
  }, [profile])
  useEffect(() => { load() }, [load])
  async function exportData() {
    if (!citizen?.id) return
    try {
      const data = await api.exportCitizen(citizen.id)
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a'); link.href = url; link.download = 'my-relief-data.json'; link.click(); URL.revokeObjectURL(url)
      setNotice(t('export_ready'))
    } catch (reason) { setError(reason) }
  }
  async function saveProfile(event) {
    event.preventDefault(); setSaving(true); setError(null); setNotice('')
    const fields = new FormData(event.currentTarget)
    try {
      const updated = await api.updateCitizen(citizen.id, {
        full_name: fields.get('full_name'), father_name: fields.get('father_name') || null,
        cnic: fields.get('cnic') || null, dob: fields.get('dob') || null,
        district: fields.get('district') || null, phone: fields.get('phone') || null,
      })
      setCitizen(updated); setEditing(false); setNotice(t('profile_saved'))
    } catch (reason) { setError(reason) } finally { setSaving(false) }
  }
  if (loading) return <Loading t={t} />
  if (!citizen?.id) return <EmptyState icon="🪪" title={t('citizen_setup_title')} detail={t('no_citizen_id')} />
  return <section className="page-content"><div className="page-heading-row"><div><span className="eyebrow">{t('nav_profile')}</span><h1>{citizen.full_name || profile.full_name}</h1></div><span className="profile-avatar">👤</span></div><ErrorNotice error={error} t={t} onRetry={load}/><Notice>{notice}</Notice>
    {editing ? <form className="panel stack-form" onSubmit={saveProfile}><Field label={t('full_name')}><input name="full_name" defaultValue={citizen.full_name || ''} required /></Field><Field label={t('father_name')}><input name="father_name" defaultValue={citizen.father_name || ''} /></Field><Field label={t('cnic')}><input name="cnic" inputMode="numeric" pattern="[0-9]{13}" maxLength="13" defaultValue={citizen.cnic || ''} /></Field><Field label={t('dob')}><input name="dob" type="date" defaultValue={citizen.dob || ''} /></Field><Field label={t('district')}><input name="district" defaultValue={citizen.district || ''} /></Field><Field label={t('phone')}><input name="phone" type="tel" inputMode="tel" pattern="03[0-9]{9}" maxLength="11" defaultValue={citizen.phone || ''} /></Field><div className="form-actions"><Button type="button" kind="secondary" onClick={() => setEditing(false)}>{t('back')}</Button><Button disabled={saving}>{saving ? t('loading_data') : t('save')}</Button></div></form>
      : <article className="panel profile-grid">{[['full_name', citizen.full_name], ['father_name', citizen.father_name], ['cnic', citizen.cnic], ['dob', citizen.dob], ['district', citizen.district], ['phone', citizen.phone]].map(([key, value]) => <div key={key}><small>{t(key)}</small><strong>{value || '—'}</strong></div>)}</article>}
    <div className="profile-actions"><Button kind="secondary" onClick={() => setEditing((value) => !value)}>{t(editing ? 'back' : 'edit_profile')}</Button><Button kind="secondary" onClick={exportData}>⬇️ {t('export_data')}</Button></div>
  </section>
}

export function ConsentView({ profile, t, onNavigate }) {
  const [citizenId, setCitizenId] = useState(null)
  const [consents, setConsents] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState('')
  const [grantee, setGrantee] = useState('officer')
  const scopes = ['claim_data', 'identity', 'documents', 'contact']
  const scopeTitle = { claim_data: 'consent_claim', identity: 'consent_identity', documents: 'consent_documents', contact: 'consent_contact' }
  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const citizen = await discoverCitizen(profile)
      if (!citizen?.id) { setCitizenId(null); setConsents([]); return }
      setCitizenId(citizen.id); setConsents(await api.consents(citizen.id))
    } catch (reason) { setError(reason) } finally { setLoading(false) }
  }, [profile])
  useEffect(() => { load() }, [load])
  async function save(scope, existing) {
    setBusy(scope); setError(null); setNotice('')
    try {
      if (existing?.status === 'granted') await api.withdrawConsent(existing.id)
      else await api.grantConsent({ citizen_id: citizenId, grantee_role: grantee, scope })
      setNotice(t('consent_saved')); await load()
    } catch (reason) { setError(reason) } finally { setBusy('') }
  }
  if (loading) return <Loading t={t} />
  if (!citizenId) return <section className="page-content"><EmptyState icon="🔐" title={t('consent_title')} detail={t('no_citizen_id')} action={<Button onClick={() => onNavigate('cases')}>{t('create_profile')}</Button>} /></section>
  return <section className="page-content"><div className="welcome-row"><div><span className="eyebrow">{t('nav_consent')}</span><h1>{t('consent_title')}</h1><p>{t('consent_intro')}</p></div><span className="large-icon">🔐</span></div><label className="field consent-grantee"><span>{t('consent_title')}</span><select value={grantee} onChange={(event) => setGrantee(event.target.value)}><option value="officer">{t('grantee_officer')}</option><option value="helper">{t('grantee_helper')}</option></select></label><Notice>{notice}</Notice><ErrorNotice error={error} t={t} onRetry={load}/><div className="consent-list">{scopes.map((scope) => {
      const record = consents.find((item) => item.scope === scope && item.grantee_role === grantee)
    const granted = record?.status === 'granted'
    return <article className="consent-card" key={scope}><div className="consent-icon">{scope === 'claim_data' ? '📄' : scope === 'identity' ? '🪪' : scope === 'documents' ? '📎' : '📞'}</div><div className="consent-copy"><strong>{t(scopeTitle[scope])}</strong><small>{grantee === 'officer' ? t('grantee_officer') : t('grantee_helper')} · {granted ? t('consent_granted') : record ? t('consent_withdrawn') : t('consent_pending')}</small></div><button className={`toggle ${granted ? 'toggle-on' : ''}`} role="switch" aria-checked={granted} aria-label={t(scopeTitle[scope])} onClick={() => save(scope, record)} disabled={busy === scope}><span /></button></article>
  })}</div><Notice>{grantee === 'officer' ? t('consent_required_notice') : t('link_pending')}</Notice></section>
}

export function ScamView({ language, t }) {
  const [text, setText] = useState('')
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  async function check(event) {
    event.preventDefault(); setBusy(true); setError(null); setResult(null)
    try { setResult(await api.scamCheck(text)) } catch (reason) { setError(reason) } finally { setBusy(false) }
  }
  return <section className="page-content narrow-content"><div className="panel scam-panel"><span className="large-icon">🛡️</span><span className="eyebrow">{t('nav_scam')}</span><h1>{t('check_message_title')}</h1><p>{t('check_message_help')}</p>
    <form className="stack-form" onSubmit={check}><Field label={t('message_text')}><textarea value={text} onChange={(e) => setText(e.target.value)} rows="6" maxLength="10000" required /></Field><Button type="submit" disabled={busy || !text.trim()}>{busy ? t('loading_data') : t('check_message')}</Button></form>
    <ErrorNotice error={error} t={t}/>
    {result && <div className={`scam-result scam-${result.label}`}><div className="result-symbol">{result.label === 'scam' ? '⚠️' : result.label === 'legit' ? '✅' : '❔'}</div><div><h2>{t(`label_${result.label}`)}</h2><p>{t('scam_advice')}</p><small>{t('confidence')}: {Math.round((result.confidence || 0) * 100)}%</small></div></div>}
  </div></section>
}

export function HelperView({ profile, language, t, selectedCitizen, setSelectedCitizen, onNavigate }) {
  const [people, setPeople] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [citizenId, setCitizenId] = useState('')
  const [notice, setNotice] = useState('')
  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try { setPeople(await api.helperCitizens()) } catch (reason) { setError(reason) } finally { setLoading(false) }
  }, [])
  useEffect(() => { load() }, [load])
  async function link(event) {
    event.preventDefault(); setError(null); setNotice('')
    try { await api.linkCitizen(citizenId.trim()); setCitizenId(''); setNotice(t('link_pending')); await load() } catch (reason) { setError(reason) }
  }
  if (loading) return <Loading t={t} />
  return <section className="page-content"><div className="page-heading-row"><div><span className="eyebrow">{t('role_helper')}</span><h1>{t('people_title')}</h1></div><span className="large-icon">🤝</span></div><ErrorNotice error={error} t={t} onRetry={load}/><Notice>{notice}</Notice>
    <form className="inline-form panel" onSubmit={link}><Field label={t('citizen_id_placeholder')}><input value={citizenId} onChange={(e) => setCitizenId(e.target.value)} placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" required /></Field><Button type="submit">{t('request_link')}</Button></form>
    <p className="subtle-copy">{t('link_pending')}</p>
    {people.length ? <div className="people-grid">{people.map((person) => <article className={`person-card ${selectedCitizen?.citizen_id === person.citizen_id ? 'person-selected' : ''}`} key={person.citizen_id}><span className="profile-avatar">👤</span><h2>{person.full_name || t('link_pending')}</h2><small>{person.status}</small><Button kind="secondary" onClick={() => {
      const message = t('switch_confirm', { name: person.full_name || t('role_citizen') })
      if (window.confirm(message)) { setSelectedCitizen({ id: person.citizen_id, citizen_id: person.citizen_id, full_name: person.full_name }); onNavigate('cases') }
    }}>{t('switch_person')}</Button></article>)}</div> : <EmptyState icon="🤝" title={t('no_data')} detail={t('link_pending')} />}
  </section>
}

export function HelpView({ language, t }) {
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  async function ask(event) {
    event.preventDefault(); setBusy(true); setError(null); setAnswer(null)
    try { setAnswer(await api.ask(question, language)) } catch (reason) { setError(reason) } finally { setBusy(false) }
  }
  return <section className="page-content narrow-content"><div className="panel"><span className="large-icon">💬</span><h1>{t('ask_title')}</h1><form className="stack-form" onSubmit={ask}><Field label={t('question')}><textarea rows="4" maxLength="5000" value={question} onChange={(e) => setQuestion(e.target.value)} required /></Field><VoiceButton language={language} t={t} onText={setQuestion}/><Button disabled={busy || !question.trim()}>{busy ? t('loading_data') : t('ask')}</Button></form><ErrorNotice error={error} t={t}/>{answer && <div className="answer-card">{answer.handoff || !answer.answer ? <p>{t('handoff')}</p> : <p>{answer.answer}</p>}{answer.sources?.length > 0 && <details><summary>{t('sources')}</summary>{answer.sources.map((source, index) => <div key={`${source.doc_name}-${index}`} className="source-row"><strong>{source.doc_name}</strong><p>{source.snippet}</p></div>)}</details>}</div>}</div></section>
}

