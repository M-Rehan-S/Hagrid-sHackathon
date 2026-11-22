import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api/client'
import { Button, EmptyState, ErrorNotice, Field, Loading, Notice, StatusPill, formatDate } from '../../components/Shared'

export function OfficerView({ language, t }) {
  const [cases, setCases] = useState([])
  const [active, setActive] = useState(null)
  const [note, setNote] = useState('')
  const [filter, setFilter] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState('')
  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const rows = await api.cases(filter ? { status: filter } : {})
      setCases(rows || [])
    } catch (reason) { setError(reason) } finally { setLoading(false) }
  }, [filter])
  useEffect(() => { load() }, [load])
  async function open(item) {
    setError(null); setActive(item); setNote('')
    try { setActive(await api.case(item.id)) } catch (reason) { setError(reason) }
  }
  async function decide(outcome) {
    if (!note.trim()) { setError(new Error(t('decision_note_help'))); return }
    setBusy(true); setError(null); setNotice('')
    try {
      await api.decideCase(active.id, outcome, note.trim())
      setNotice(t('decision_saved')); setActive(null); setNote(''); await load()
    } catch (reason) { setError(reason) } finally { setBusy(false) }
  }
  async function escalate() {
    if (!note.trim()) { setError(new Error(t('decision_note_help'))); return }
    setBusy(true); setError(null)
    try { await api.escalateCase(active.id, note.trim()); setNotice(t('decision_saved')); setActive(null); await load() }
    catch (reason) { setError(reason) } finally { setBusy(false) }
  }
  async function assign() {
    const officer_id = window.prompt(t('officer_id_prompt'), active?.assigned_to || '')
    if (!officer_id?.trim()) return
    setBusy(true); setError(null)
    try { await api.assignCase(active.id, officer_id.trim()); setNotice(t('assigned')); await open(active); await load() }
    catch (reason) { setError(reason) } finally { setBusy(false) }
  }
  async function close() {
    if (!window.confirm(t('close_case') + '?')) return
    setBusy(true); setError(null)
    try { await api.closeCase(active.id); setNotice(t('case_closed')); setActive(null); await load() }
    catch (reason) { setError(reason) } finally { setBusy(false) }
  }
  if (loading) return <Loading t={t} />
  const canDecide = ['submitted', 'in_review'].includes(active?.status)
  if (active) return <section className="page-content"><button className="back-link" onClick={() => setActive(null)}>← {t('back')}</button><div className="page-heading-row"><div><span className="eyebrow">{t('queue_title')}</span><h1>{active.form_data?.full_name || t('case_details')}</h1></div><StatusPill value={active.status} t={t}/></div><ErrorNotice error={error} t={t}/>
    <article className="panel profile-grid">{Object.entries(active.form_data || {}).filter(([key]) => key !== 'invalid_fields').map(([key, value]) => <div key={key}><small>{t(key)}</small><strong>{typeof value === 'boolean' ? t(value ? 'yes' : 'no') : String(value ?? '—')}</strong></div>)}</article>
    {active.decisions?.map((decision) => <article className="panel decision-card" key={decision.id}><h2>{t('decisions')}</h2><p>{language === 'ur' ? decision.reason_ur : decision.reason_en}</p><details><summary>{t('case_confidence')}: {Math.round((decision.confidence || 0) * 100)}% · {decision.model_version}</summary><pre>{JSON.stringify(decision.trace, null, 2)}</pre></details></article>)}
    {canDecide ? <article className="panel decision-panel"><h2>{t('decision_note')}</h2><p>{t('decision_note_help')}</p><textarea rows="4" value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000}/><ErrorNotice error={error} t={t}/><div className="decision-actions"><Button onClick={() => decide('approved')} disabled={busy}>✅ {t('decision_approve')}</Button><Button kind="danger" onClick={() => decide('rejected')} disabled={busy}>⛔ {t('decision_reject')}</Button><Button kind="secondary" onClick={() => decide('needs_more_proof')} disabled={busy}>📎 {t('decision_more')}</Button><Button kind="secondary" onClick={escalate} disabled={busy}>↗ {t('escalate')}</Button><Button kind="secondary" onClick={assign} disabled={busy}>👤 {t('assign_case')}</Button></div></article> : <article className="panel decision-panel"><h2>{t('decision_unavailable_title')}</h2><p>{t('decision_unavailable', { status: t(`status_${active.status}`) })}</p>{['approved', 'rejected'].includes(active.status) && <Button kind="danger" onClick={close} disabled={busy}>{t('close_case')}</Button>}</article>}
  </section>
  return <section className="page-content"><div className="page-heading-row"><div><span className="eyebrow">{t('nav_queue')}</span><h1>{t('queue_title')}</h1></div><label className="compact-filter"><span>{t('filter_status')}</span><select value={filter} onChange={(e) => setFilter(e.target.value)}><option value="">{t('more')}</option>{['submitted', 'in_review', 'needs_info', 'approved', 'rejected'].map((status) => <option key={status} value={status}>{t(`status_${status}`)}</option>)}</select></label></div><Notice>{notice}</Notice><ErrorNotice error={error} t={t} onRetry={load}/>
    {cases.length ? <div className="case-list">{cases.map((item) => <button className="case-row" key={item.id} onClick={() => open(item)}><span className="case-symbol">📄</span><span className="case-main"><strong>{item.form_data?.full_name || t('case_details')}</strong><small>{t('case_route')}: {t(`route_${item.route || 'unrouted'}`)}</small></span><span className="case-meta"><StatusPill value={item.status} t={t}/><small>{item.confidence == null ? '—' : `${Math.round(item.confidence * 100)}%`}</small></span><span className="row-arrow">›</span></button>)}</div> : <EmptyState icon="📥" title={t('no_data')} detail={t('queue_title')} />}
  </section>
}

export function RulesView({ t }) {
  const [rules, setRules] = useState([])
  const [definition, setDefinition] = useState('')
  const [ruleKey, setRuleKey] = useState('relief_eligibility')
  const [note, setNote] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState('')
  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const rows = await api.rules()
      setRules(rows || [])
      const activeRule = rows?.find((item) => item.status === 'active')
      if (activeRule && !definition) setDefinition(JSON.stringify(activeRule.definition, null, 2))
    } catch (reason) { setError(reason) } finally { setLoading(false) }
  }, [definition])
  useEffect(() => { load() }, [])
  let costPreview = null
  try {
    const parsed = JSON.parse(definition)
    const wrongApproval = Number(parsed.cost?.wrong_approval)
    const manualReview = Number(parsed.cost?.manual_review)
    const threshold = Number(parsed.thresholds?.auto_approve)
    if (wrongApproval > 0 && manualReview >= 0 && Number.isFinite(threshold)) {
      const minimum = 1 - manualReview / wrongApproval
      costPreview = { wrongApproval, manualReview, threshold, minimum, safe: threshold >= minimum }
    }
  } catch { /* The editor shows JSON validation when saving. */ }
  async function create(event) {
    event.preventDefault(); setBusy(true); setError(null); setNotice('')
    try {
      const parsed = JSON.parse(definition)
      await api.createRule({ rule_key: ruleKey, definition: parsed, note: note || null })
      setNotice(t('rule_created')); setNote(''); await load()
    } catch (reason) { setError(reason instanceof SyntaxError ? new Error(t('empty_rule_json')) : reason) } finally { setBusy(false) }
  }
  async function activate(id) {
    if (!window.confirm(t('activate_rule') + '?')) return
    setBusy(true); setError(null)
    try { await api.activateRule(id); setNotice(t('rule_activated')); await load() } catch (reason) { setError(reason) } finally { setBusy(false) }
  }
  if (loading) return <Loading t={t} />
  return <section className="page-content"><div className="page-heading-row"><div><span className="eyebrow">{t('nav_rules')}</span><h1>{t('rules_title')}</h1></div><span className="large-icon">⚖️</span></div><Notice>{notice}</Notice><ErrorNotice error={error} t={t} onRetry={load}/>
    <div className="rule-list">{rules.map((rule) => <article className="rule-card" key={rule.id}><div className="panel-heading"><div><strong>{rule.rule_key} · v{rule.version}</strong><small>{rule.note || '—'}</small></div><span className={`rule-status rule-${rule.status}`}>{rule.status}</span></div><pre>{JSON.stringify(rule.definition, null, 2)}</pre>{rule.status === 'draft' && <Button kind="secondary" disabled={busy} onClick={() => activate(rule.id)}>{t('activate_rule')}</Button>}</article>)}</div>
    <article className="panel rule-editor"><h2>{t('create_draft')}</h2>{costPreview && <Notice kind={costPreview.safe ? 'success' : 'error'}>{t('rule_cost_preview', { wrong: costPreview.wrongApproval, review: costPreview.manualReview, threshold: costPreview.threshold.toFixed(3), minimum: costPreview.minimum.toFixed(3) })}{!costPreview.safe && ` ${t('rule_cost_unsafe')}`}</Notice>}<form className="stack-form" onSubmit={create}><Field label={t('rule_key')}><input value={ruleKey} onChange={(e) => setRuleKey(e.target.value)} required /></Field><Field label={t('rule_note')}><input value={note} onChange={(e) => setNote(e.target.value)} /></Field><Field label={t('rule_json')}><textarea className="code-input" rows="18" value={definition} onChange={(e) => setDefinition(e.target.value)} required spellCheck="false" /></Field><Button disabled={busy}>{busy ? t('loading_data') : t('create_draft')}</Button></form></article>
  </section>
}

export function TwinView({ t }) {
  const [rules, setRules] = useState([])
  const [ruleId, setRuleId] = useState('')
  const [limit, setLimit] = useState('')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  useEffect(() => { api.rules().then((rows) => { const drafts = rows.filter((row) => row.status === 'draft'); setRules(drafts); setRuleId(drafts[0]?.id || '') }).catch(setError).finally(() => setLoading(false)) }, [])
  async function simulate(event) {
    event.preventDefault(); setBusy(true); setError(null); setResult(null)
    try { setResult(await api.simulate({ draft_rule_id: ruleId, ...(limit ? { limit: Number(limit) } : {}) })) } catch (reason) { setError(reason) } finally { setBusy(false) }
  }
  if (loading) return <Loading t={t} />
  return <section className="page-content"><div className="page-heading-row"><div><span className="eyebrow">{t('nav_twin')}</span><h1>{t('twin_title')}</h1></div><span className="large-icon">🧪</span></div><ErrorNotice error={error} t={t}/>
    <form className="panel inline-form" onSubmit={simulate}><Field label={t('draft_rule')}><select value={ruleId} onChange={(e) => setRuleId(e.target.value)} required><option value="">—</option>{rules.map((rule) => <option value={rule.id} key={rule.id}>{rule.rule_key} · v{rule.version}</option>)}</select></Field><Field label={t('application_count')}><input type="number" min="1" value={limit} onChange={(e) => setLimit(e.target.value)} placeholder={t('more')} /></Field><Button disabled={busy || !ruleId}>{busy ? t('loading_data') : t('simulate')}</Button></form>
    {!rules.length && <EmptyState icon="🧪" title={t('no_data')} detail={t('create_draft')} />}
    {result && <article className="panel"><h2>{t('simulation_results')}</h2><div className="stats-grid compact-stats"><Stat t={t} label={t('application_count')} value={result.total}/><Stat t={t} label={t('changed_cases')} value={result.changed}/><Stat t={t} label={t('more_approvals')} value={result.summary.more_approvals}/><Stat t={t} label={t('fewer_approvals')} value={result.summary.fewer_approvals}/><Stat t={t} label={t('more_reviews')} value={result.summary.more_human_reviews}/><Stat t={t} label={t('fewer_reviews')} value={result.summary.fewer_human_reviews}/></div><div className="simulation-list">{result.results?.map((row) => <div key={row.case_id}><code>{row.case_id}</code><span>{row.old_outcome || '—'} → {row.new_outcome}</span></div>)}</div></article>}
  </section>
}

export function KeysView({ t }) {
  const [keys, setKeys] = useState([])
  const [label, setLabel] = useState('')
  const [newKey, setNewKey] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState('')
  const load = useCallback(async () => { setLoading(true); setError(null); try { setKeys(await api.apiKeys()) } catch (reason) { setError(reason) } finally { setLoading(false) } }, [])
  useEffect(() => { load() }, [load])
  async function create(event) {
    event.preventDefault(); setBusy(true); setError(null); setNewKey('')
    try { const item = await api.createApiKey({ label }); setNewKey(item.api_key); setLabel(''); await load() } catch (reason) { setError(reason) } finally { setBusy(false) }
  }
  async function revoke(id) {
    if (!window.confirm(t('revoke_key') + '?')) return
    setBusy(true); setError(null)
    try { await api.revokeApiKey(id); setNotice(t('key_revoked')); await load() } catch (reason) { setError(reason) } finally { setBusy(false) }
  }
  async function copy() {
    try { await navigator.clipboard.writeText(newKey); setNotice(t('copy_key')) } catch { setError(new Error(t('unknown_error'))) }
  }
  if (loading) return <Loading t={t} />
  return <section className="page-content"><div className="page-heading-row"><div><span className="eyebrow">{t('nav_keys')}</span><h1>{t('keys_title')}</h1></div><span className="large-icon">🔑</span></div><Notice>{notice}</Notice><ErrorNotice error={error} t={t} onRetry={load}/>
    {newKey && <div className="new-key-banner"><strong>{t('key_created_once')}</strong><code>{newKey}</code><Button kind="secondary" onClick={copy}>{t('copy_key')}</Button></div>}
    <form className="panel inline-form" onSubmit={create}><Field label={t('key_label')}><input value={label} onChange={(e) => setLabel(e.target.value)} maxLength="120" required /></Field><Button disabled={busy}>{t('create_key')}</Button></form>
    <div className="panel table-panel"><div className="table-scroll"><table><thead><tr><th>{t('key_label')}</th><th>Prefix</th><th>{t('case_created')}</th><th>{t('case_status')}</th><th /></tr></thead><tbody>{keys.map((key) => <tr key={key.id}><td>{key.label}</td><td><code>{key.key_prefix}</code></td><td>{formatDate(key.created_at)}</td><td>{key.revoked_at ? t('key_revoked') : 'Active'}</td><td>{!key.revoked_at && <button className="inline-link danger-link" onClick={() => revoke(key.id)}>{t('revoke_key')}</button>}</td></tr>)}</tbody></table></div>{!keys.length && <p className="empty-inline">{t('no_data')}</p>}</div>
  </section>
}

export function AnalyticsView({ t }) {
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const load = useCallback(async () => { setLoading(true); setError(null); try { setSummary(await api.evaluation()) } catch (reason) { setError(reason) } finally { setLoading(false) } }, [])
  useEffect(() => { load() }, [load])
  if (loading) return <Loading t={t} />
  const live = summary?.live || {}
  return <section className="page-content"><div className="page-heading-row"><div><span className="eyebrow">{t('nav_analytics')}</span><h1>{t('analytics_title')}</h1></div><Button kind="secondary" onClick={load}>{t('refresh')}</Button></div><ErrorNotice error={error} t={t} onRetry={load}/>
    <div className="stats-grid"><Stat t={t} label={t('application_count')} value={live.total_cases ?? 0}/><Stat t={t} label={t('auto_approved')} value={live.auto_approved_count ?? 0}/><Stat t={t} label={t('human_count')} value={live.human_handoffs ?? 0}/><Stat t={t} label={t('latency')} value={live.avg_decision_latency_ms == null ? '—' : `${live.avg_decision_latency_ms} ms`}/></div>
    <article className="panel"><h2>{t('cases_by_route')}</h2><div className="route-summary">{Object.entries(live.cases_by_route || {}).map(([route, count]) => <div key={route}><span>{t(`route_${route}`)}</span><strong>{count}</strong><div className="bar-track"><i style={{ width: `${live.total_cases ? Math.min(100, (count / live.total_cases) * 100) : 0}%` }} /></div></div>)}</div></article>
    <article className="panel"><h2>{t('evaluation_runs')}</h2>{summary?.evaluation_runs?.length ? <div className="eval-grid">{summary.evaluation_runs.map((run) => <div className="eval-card" key={run.id}><strong>{run.name}</strong><small>{formatDate(run.created_at)}</small><MetricList metrics={run.metrics} /></div>)}</div> : <EmptyState icon="📊" title={t('no_data')} detail={t('evaluation_runs')} />}</article>
  </section>
}

function MetricList({ metrics }) {
  const keys = ['samples', 'accuracy', 'precision_macro', 'recall_macro', 'f1_macro', 'false_alarm_rate', 'abstention_rate', 'avg_latency_ms']
  return <div className="metric-list">{keys.filter((key) => metrics?.[key] != null).map((key) => <div key={key}><span>{key.replaceAll('_', ' ')}</span><strong>{typeof metrics[key] === 'number' && key !== 'samples' ? `${Math.round(metrics[key] * (key.includes('latency') ? 1 : 100))}${key.includes('latency') ? ' ms' : '%'}` : metrics[key]}</strong></div>)}</div>
}

export function AuditView({ t, consentMode = false }) {
  const [filters, setFilters] = useState({ actor_id: '', action: '', entity_type: '', from: '', to: '' })
  const [logs, setLogs] = useState(null)
  const [citizenId, setCitizenId] = useState('')
  const [consents, setConsents] = useState([])
  const [page, setPage] = useState(1)
  const [verification, setVerification] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState('')
  const load = useCallback(async (nextPage = 1) => {
    setLoading(true); setError(null)
    const queryFilters = {
      ...filters,
      from: filters.from ? `${filters.from}T00:00:00Z` : '',
      to: filters.to ? `${filters.to}T23:59:59Z` : '',
      page: nextPage,
      page_size: 25,
    }
    try { setLogs(await api.auditLogs(queryFilters)) } catch (reason) { setError(reason) } finally { setLoading(false) }
  }, [filters])
  useEffect(() => { if (!consentMode) load(1) }, [load, consentMode])
  async function verify() {
    setError(null); setVerification(null)
    try { setVerification(await api.verifyAudit()) } catch (reason) { setError(reason) }
  }
  async function fetchConsents(event) {
    event.preventDefault(); setLoading(true); setError(null)
    try { setConsents(await api.consents(citizenId.trim())) } catch (reason) { setError(reason) } finally { setLoading(false) }
  }
  if (loading && !consentMode) return <Loading t={t} />
  return <section className="page-content"><div className="page-heading-row"><div><span className="eyebrow">{consentMode ? t('nav_audit_consents') : t('nav_audit')}</span><h1>{consentMode ? t('nav_audit_consents') : t('audit_title')}</h1></div>{!consentMode && <Button kind="secondary" onClick={verify}>🔍 {t('verify_chain')}</Button>}</div><ErrorNotice error={error} t={t} onRetry={() => load(page)}/>
    {verification && <Notice kind={verification.valid ? 'success' : 'error'}>{verification.valid ? t('chain_valid') : `${t('chain_invalid')} ${verification.broken_at || ''}`}</Notice>}
    {consentMode ? <><form className="panel inline-form" onSubmit={fetchConsents}><Field label={t('citizen_id_placeholder')}><input value={citizenId} onChange={(e) => setCitizenId(e.target.value)} required /></Field><Button>{t('apply_filters')}</Button></form>{loading ? <Loading t={t}/> : <div className="panel consent-audit-list">{consents.map((consent) => <div className="history-row" key={consent.id}><strong>{consent.scope}</strong><span>{consent.grantee_role || consent.grantee_user_id}</span><StatusPill value={consent.status} t={t}/><time>{formatDate(consent.granted_at)}</time></div>)}{!consents.length && <p className="empty-inline">{t('no_data')}</p>}</div>}</>
      : <><form className="panel filter-grid" onSubmit={(event) => { event.preventDefault(); setPage(1); load(1) }}>{Object.entries(filters).map(([key, value]) => <Field key={key} label={t(`audit_${key}`) || key}><input type={key === 'from' || key === 'to' ? 'date' : 'text'} value={value} onChange={(e) => setFilters((current) => ({ ...current, [key]: e.target.value }))} /></Field>)}<Button>{t('apply_filters')}</Button></form>
        <div className="panel table-panel"><div className="table-scroll"><table><thead><tr><th>{t('case_created')}</th><th>{t('audit_actor')}</th><th>{t('audit_action')}</th><th>{t('audit_entity')}</th><th>Hash</th><th>Data</th></tr></thead><tbody>{logs?.items?.map((entry) => <tr key={entry.id}><td>{formatDate(entry.ts)}</td><td><code>{entry.actor_id || '—'}</code></td><td>{entry.action}</td><td>{entry.entity_type} {entry.entity_id && <small>{entry.entity_id}</small>}</td><td><code className="hash-code">{entry.hash}</code></td><td><details><summary>{t('more')}</summary><pre>{JSON.stringify(entry.payload, null, 2)}</pre></details></td></tr>)}</tbody></table></div>{!logs?.items?.length && <p className="empty-inline">{t('no_data')}</p>}<div className="pagination"><button className="inline-link" disabled={page <= 1} onClick={() => { const next = page - 1; setPage(next); load(next) }}>{t('previous')}</button><span>{t('page')} {logs?.page || page} · {logs?.total || 0}</span><button className="inline-link" disabled={page * (logs?.page_size || 25) >= (logs?.total || 0)} onClick={() => { const next = page + 1; setPage(next); load(next) }}>{t('more')}</button></div></div>
      </>}
  </section>
}

function Stat({ label, value }) {
  return <article className="stat-card"><span className="stat-label">{label}</span><strong>{value}</strong></article>
}
