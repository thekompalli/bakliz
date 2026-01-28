import './App.css'
import { useEffect, useState } from 'react'
import {
  api,
  clearToken,
  getToken,
  setToken,
  type BlacklistEntry,
  type Config,
  type HistoryRow,
  type ProviderLogItem,
  type RunResponse,
} from './api'

function App() {
  const [token, setTokenState] = useState<string | null>(() => getToken())
  const [tab, setTab] = useState<'config' | 'blacklist' | 'history' | 'linkup' | 'zeliq'>(
    'config',
  )

  const onLogout = () => {
    clearToken()
    setTokenState(null)
  }

  if (!token) return <Login onLoggedIn={setTokenState} />

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">BAKLIZ</div>
        <nav className="tabs">
          <button
            className={tab === 'config' ? 'tab active' : 'tab'}
            onClick={() => setTab('config')}
          >
            Tab A: Configuration
          </button>
          <button
            className={tab === 'blacklist' ? 'tab active' : 'tab'}
            onClick={() => setTab('blacklist')}
          >
            Tab B: Blacklist
          </button>
          <button
            className={tab === 'history' ? 'tab active' : 'tab'}
            onClick={() => setTab('history')}
          >
            Tab C: History
          </button>
          <button
            className={tab === 'linkup' ? 'tab active' : 'tab'}
            onClick={() => setTab('linkup')}
          >
            Linkup Raw
          </button>
          <button className={tab === 'zeliq' ? 'tab active' : 'tab'} onClick={() => setTab('zeliq')}>
            Zeliq Raw
          </button>
        </nav>
        <button className="btn secondary" onClick={onLogout}>
          Logout
        </button>
      </header>

      <main className="content">
        {tab === 'config' && <ConfigTab />}
        {tab === 'blacklist' && <BlacklistTab />}
        {tab === 'history' && <HistoryTab />}
        {tab === 'linkup' && <ProviderLogsTab provider="linkup" />}
        {tab === 'zeliq' && <ProviderLogsTab provider="zeliq" />}
      </main>
    </div>
  )
}

function Login({ onLoggedIn }: { onLoggedIn: (token: string) => void }) {
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const res = await api.login(username, password)
      setToken(res.access_token)
      onLoggedIn(res.access_token)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="center">
      <div className="card">
        <h1>BAKLIZ Admin</h1>
        <p className="muted">Sign in to manage configuration, blacklist, and history.</p>
        <form onSubmit={submit} className="form">
          <label>
            Username
            <input value={username} onChange={(e) => setUsername(e.target.value)} />
          </label>
          <label>
            Password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          {error && <div className="error">{error}</div>}
          <button className="btn" type="submit" disabled={loading}>
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
        <p className="muted small">
          API: <code>{import.meta.env.VITE_API_BASE_URL}</code>
        </p>
      </div>
    </div>
  )
}

function ConfigTab() {
  const [cfg, setCfg] = useState<Config | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [forceDryRun, setForceDryRun] = useState(true)
  const [runLoading, setRunLoading] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)
  const [runResult, setRunResult] = useState<RunResponse | null>(null)
  const [runStartedAtMs, setRunStartedAtMs] = useState<number | null>(null)
  const [runElapsedMs, setRunElapsedMs] = useState(0)
  const [runLast, setRunLast] = useState<Record<string, unknown> | null>(null)
  const [runStats, setRunStats] = useState<{
    companies_total: number
    companies_seen: number
    contacts_tried: number
    contact_searches: number
  } | null>(null)
  const [runAbort, setRunAbort] = useState<AbortController | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .getConfig()
      .then((c) => {
        if (!cancelled) setCfg(c)
        if (!cancelled) setForceDryRun(c.run_mode === 'dry_run')
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load config')
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!runLoading || !runStartedAtMs) return
    const t = setInterval(() => setRunElapsedMs(Date.now() - runStartedAtMs), 500)
    return () => clearInterval(t)
  }, [runLoading, runStartedAtMs])

  const save = async () => {
    if (!cfg) return
    setSaving(true)
    setSaved(false)
    setError(null)
    try {
      const updated = await api.updateConfig(cfg)
      setCfg(updated)
      setSaved(true)
      setTimeout(() => setSaved(false), 1500)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  if (!cfg) return <div>Loading configuration…</div>

  const runNow = async () => {
    setRunLoading(true)
    setRunError(null)
    setRunResult(null)
    setRunLast(null)
    setRunStats(null)
    setRunElapsedMs(0)
    const ctrl = new AbortController()
    setRunAbort(ctrl)
    setRunStartedAtMs(Date.now())
    try {
      await api.runNowStream(
        { dry_run: forceDryRun, overrides: {}, signal: ctrl.signal },
        (ev) => {
          const type = String(ev.type || '')
          if (type === 'start') {
            setRunResult({
              run_id: String(ev.run_id || ''),
              created_drafts: 0,
              quota: Number(ev.quota || 0),
              excluded_count: 0,
              enrich_failed_count: 0,
              pool_exhausted: false,
              errors: [],
            })
            setRunStats({
              companies_total: Number(ev.companies_total || 0),
              companies_seen: Number(ev.companies_seen || 0),
              contacts_tried: Number(ev.contacts_tried || 0),
              contact_searches: Number(ev.contact_searches || 0),
            })
            return
          }
          if (type === 'progress') {
            setRunLast((ev.last as Record<string, unknown>) || null)
            setRunStats({
              companies_total: Number(ev.companies_total || 0),
              companies_seen: Number(ev.companies_seen || 0),
              contacts_tried: Number(ev.contacts_tried || 0),
              contact_searches: Number(ev.contact_searches || 0),
            })
            setRunResult((prev) => ({
              run_id: String(ev.run_id || prev?.run_id || ''),
              created_drafts: Number(ev.created_drafts || 0),
              quota: Number(ev.quota || prev?.quota || 0),
              excluded_count: Number(ev.excluded_count || 0),
              enrich_failed_count: Number(ev.enrich_failed_count || 0),
              pool_exhausted: Boolean(ev.pool_exhausted),
              errors: (prev?.errors || []) as Array<Record<string, unknown>>,
            }))
            return
          }
          if (type === 'done') {
            setRunResult({
              run_id: String(ev.run_id || ''),
              created_drafts: Number(ev.created_drafts || 0),
              quota: Number(ev.quota || 0),
              excluded_count: Number(ev.excluded_count || 0),
              enrich_failed_count: Number(ev.enrich_failed_count || 0),
              pool_exhausted: Boolean(ev.pool_exhausted),
              errors: (ev.errors as Array<Record<string, unknown>>) || [],
            })
            setRunStats({
              companies_total: Number(ev.companies_total || 0),
              companies_seen: Number(ev.companies_seen || 0),
              contacts_tried: Number(ev.contacts_tried || 0),
              contact_searches: Number(ev.contact_searches || 0),
            })
          }
        },
      )
    } catch (e: unknown) {
      if (e instanceof DOMException && e.name === 'AbortError') {
        setRunError('Run cancelled')
      } else {
        setRunError(e instanceof Error ? e.message : 'Run failed')
      }
    } finally {
      setRunLoading(false)
      setRunAbort(null)
    }
  }

  const cancelRun = () => {
    runAbort?.abort()
  }

  return (
    <section>
      <h2>Configuration</h2>
      <div className="grid2">
        <label>
          Industry
          <input
            value={cfg.industry}
            onChange={(e) => setCfg({ ...cfg, industry: e.target.value })}
          />
        </label>
        <label>
          Location
          <input
            value={cfg.location}
            onChange={(e) => setCfg({ ...cfg, location: e.target.value })}
          />
        </label>
        <label>
          Company size min
          <input
            type="number"
            min={1}
            value={cfg.company_size_min}
            onChange={(e) => setCfg({ ...cfg, company_size_min: Number(e.target.value) })}
          />
        </label>
        <label>
          Daily objective (quota)
          <input
            type="number"
            min={0}
            value={cfg.daily_objective}
            onChange={(e) => setCfg({ ...cfg, daily_objective: Number(e.target.value) })}
          />
        </label>
        <label className="colspan2">
          Email subject template
          <input
            value={cfg.email_subject_template}
            onChange={(e) => setCfg({ ...cfg, email_subject_template: e.target.value })}
          />
        </label>
        <label className="colspan2">
          Email body template (supports <code>{'{{FirstName}}'}</code>,{' '}
          <code>{'{{Company}}'}</code>)
          <textarea
            rows={8}
            value={cfg.email_body_template}
            onChange={(e) => setCfg({ ...cfg, email_body_template: e.target.value })}
          />
        </label>
        <label>
          Alert email
          <input
            value={cfg.alert_email}
            onChange={(e) => setCfg({ ...cfg, alert_email: e.target.value })}
          />
        </label>
        <label>
          Run mode
          <select
            value={cfg.run_mode}
            onChange={(e) => setCfg({ ...cfg, run_mode: e.target.value as Config['run_mode'] })}
          >
            <option value="dry_run">dry_run</option>
            <option value="live">live</option>
          </select>
        </label>
      </div>

      {error && <div className="error">{error}</div>}
      <div className="actions">
        <button className="btn" onClick={save} disabled={saving}>
          {saving ? 'Saving…' : 'Save'}
        </button>
        {saved && <span className="ok">Saved</span>}
      </div>

      <h2 style={{ marginTop: 22 }}>Run</h2>
      <div className="row wrap">
        <label style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <input
            type="checkbox"
            checked={forceDryRun}
            onChange={(e) => setForceDryRun(e.target.checked)}
          />
          Force dry-run
        </label>
        <button className="btn" onClick={runNow} disabled={runLoading}>
          {runLoading ? 'Running…' : 'Run now'}
        </button>
        {runLoading && (
          <button className="btn secondary" onClick={cancelRun}>
            Stop
          </button>
        )}
      </div>
      {runError && <div className="error">{runError}</div>}
      {runResult && (
        <div className="card" style={{ width: '100%', marginTop: 10 }}>
          <div className="mono">run_id: {runResult.run_id}</div>
          <div>
            created_drafts: <b>{runResult.created_drafts}</b> / quota: <b>{runResult.quota}</b>
          </div>
          {runStats && (
            <div className="muted small">
              companies: {runStats.companies_seen}/{runStats.companies_total} · contacts_tried:{' '}
              {runStats.contacts_tried} · contact_searches: {runStats.contact_searches}
            </div>
          )}
          <div className="muted">
            elapsed: {(runElapsedMs / 1000).toFixed(0)}s · excluded: {runResult.excluded_count} ·
            enrich_failed: {runResult.enrich_failed_count} · pool_exhausted:{' '}
            {String(runResult.pool_exhausted)}
          </div>
          {runLast && (
            <div className="muted small" style={{ marginTop: 6 }}>
              last: <span className="mono">{String(runLast.status_code || '')}</span>{' '}
              {runLast.company_name ? `· ${String(runLast.company_name)}` : ''}
              {runLast.company_domain ? ` (${String(runLast.company_domain)})` : ''}
              {runLast.status_detail ? ` · ${String(runLast.status_detail)}` : ''}
            </div>
          )}
        </div>
      )}
    </section>
  )
}

function BlacklistTab() {
  const [items, setItems] = useState<BlacklistEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [entryType, setEntryType] = useState<'company_name' | 'domain'>('domain')
  const [value, setValue] = useState('')

  const refresh = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await api.listBlacklist(1, 200)
      setItems(res.items)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load blacklist')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const add = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!value.trim()) return
    setError(null)
    try {
      await api.createBlacklist({ entry_type: entryType, value })
      setValue('')
      await refresh()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to add')
    }
  }

  const del = async (id: number) => {
    if (!confirm('Delete this blacklist entry?')) return
    setError(null)
    try {
      await api.deleteBlacklist(id)
      await refresh()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to delete')
    }
  }

  return (
    <section>
      <h2>Blacklist</h2>
      <form onSubmit={add} className="row">
        <select value={entryType} onChange={(e) => setEntryType(e.target.value as any)}>
          <option value="domain">domain</option>
          <option value="company_name">company_name</option>
        </select>
        <input
          placeholder={entryType === 'domain' ? 'example.com' : 'Company Name'}
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        <button className="btn" type="submit">
          Add
        </button>
      </form>
      {error && <div className="error">{error}</div>}
      {loading ? (
        <div>Loading…</div>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Type</th>
              <th>Value</th>
              <th>Normalized</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {items.map((it) => (
              <tr key={it.id}>
                <td>{it.id}</td>
                <td>{it.entry_type}</td>
                <td>{it.value_raw}</td>
                <td className="mono">{it.value_norm}</td>
                <td>
                  <button className="btn danger" onClick={() => del(it.id)}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr>
                <td colSpan={5} className="muted">
                  No entries
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </section>
  )
}

function HistoryTab() {
  const [items, setItems] = useState<HistoryRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [statusCode, setStatusCode] = useState('')
  const [company, setCompany] = useState('')
  const [domain, setDomain] = useState('')
  const [runId, setRunId] = useState('')
  const [total, setTotal] = useState(0)
  const [clearing, setClearing] = useState(false)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await api.listHistory({
        page,
        page_size: 50,
        status_code: statusCode || undefined,
        company: company || undefined,
        domain: domain || undefined,
        run_id: runId || undefined,
      })
      setItems(res.items)
      setTotal(res.total)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load history')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page])

  const onApply = (e: React.FormEvent) => {
    e.preventDefault()
    setPage(1)
    load()
  }

  const useLatestRun = async () => {
    setError(null)
    try {
      const runs = await api.listRuns(1, 1)
      const latest = runs.items[0]?.run_id
      if (!latest) {
        setError('No runs yet')
        return
      }
      setRunId(latest)
      setPage(1)
      await load()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load latest run')
    }
  }

  const clear = async () => {
    const target = runId ? `this run (${runId})` : 'ALL history'
    const ok = window.confirm(`Delete ${target}? This cannot be undone.`)
    if (!ok) return
    setClearing(true)
    setError(null)
    try {
      await api.clearHistory({ run_id: runId || undefined })
      setPage(1)
      await load()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to clear history')
    } finally {
      setClearing(false)
    }
  }

  return (
    <section>
      <h2>History</h2>
      <div className="muted small" style={{ marginBottom: 10 }}>
        Newest first · total rows: {total}
      </div>
      <form onSubmit={onApply} className="row wrap">
        <input
          placeholder="status_code"
          value={statusCode}
          onChange={(e) => setStatusCode(e.target.value)}
        />
        <input
          placeholder="company contains…"
          value={company}
          onChange={(e) => setCompany(e.target.value)}
        />
        <input
          placeholder="domain contains…"
          value={domain}
          onChange={(e) => setDomain(e.target.value)}
        />
        <input placeholder="run_id" value={runId} onChange={(e) => setRunId(e.target.value)} />
        <button className="btn" type="submit">
          Apply
        </button>
        <button className="btn secondary" type="button" onClick={useLatestRun}>
          Latest run
        </button>
        <button className="btn danger" type="button" disabled={clearing} onClick={clear}>
          {clearing ? 'Clearing…' : runId ? 'Clear this run' : 'Clear all'}
        </button>
      </form>
      {error && <div className="error">{error}</div>}
      {loading ? (
        <div>Loading…</div>
      ) : (
        <>
          <table className="table small">
            <thead>
              <tr>
                <th>Date</th>
                <th>Company</th>
                <th>Domain</th>
                <th>Employees</th>
                <th>Name</th>
                <th>Email</th>
                <th>Title</th>
                <th>Status</th>
                <th>Run</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it, idx) => (
                <tr key={idx}>
                  <td className="mono">{it.date_time}</td>
                  <td>{it.company_name}</td>
                  <td className="mono">{it.company_domain}</td>
                  <td>{it.employee_count ?? ''}</td>
                  <td>
                    {it.first_name} {it.last_name}
                  </td>
                  <td className="mono">{it.email}</td>
                  <td>{it.job_title}</td>
                  <td className="mono">
                    {it.status_code}
                    {it.status_detail ? ` (${it.status_detail})` : ''}
                  </td>
                  <td className="mono">{it.run_id}</td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={9} className="muted">
                    No rows
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          <div className="pager">
            <button
              className="btn secondary"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
            >
              Prev
            </button>
            <span className="mono">Page {page}</span>
            <button
              className="btn secondary"
              onClick={() => setPage((p) => p + 1)}
              disabled={items.length < 50}
            >
              Next
            </button>
          </div>
        </>
      )}
    </section>
  )
}

function ProviderLogsTab({ provider }: { provider: 'linkup' | 'zeliq' }) {
  const [items, setItems] = useState<ProviderLogItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [kind, setKind] = useState('')
  const [runId, setRunId] = useState('')
  const [key, setKey] = useState('')

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await api.listProviderLogs({
        page,
        page_size: 25,
        provider,
        kind: kind || undefined,
        run_id: runId || undefined,
        key: key || undefined,
      })
      setItems(res.items)
      setTotal(res.total)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load logs')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page])

  const onApply = (e: React.FormEvent) => {
    e.preventDefault()
    setPage(1)
    load()
  }

  const useLatestRun = async () => {
    setError(null)
    try {
      const runs = await api.listRuns(1, 1)
      const latest = runs.items[0]?.run_id
      if (!latest) {
        setError('No runs yet')
        return
      }
      setRunId(latest)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to fetch latest run')
    }
  }

  const totalPages = Math.max(1, Math.ceil(total / 25))

  return (
    <section>
      <h2>{provider === 'linkup' ? 'Linkup Raw Outputs' : 'Zeliq Raw Outputs'}</h2>
      <form onSubmit={onApply} className="row wrap" style={{ alignItems: 'flex-end' }}>
        <label className="muted small" style={{ display: 'flex', flexDirection: 'column' }}>
          Kind
          <input
            placeholder={provider === 'linkup' ? 'company_search / contacts / enrich_email' : 'email_enrich / email_callback'}
            value={kind}
            onChange={(e) => setKind(e.target.value)}
          />
        </label>
        <label className="muted small" style={{ display: 'flex', flexDirection: 'column' }}>
          Run ID
          <input placeholder="optional" value={runId} onChange={(e) => setRunId(e.target.value)} />
        </label>
        <label className="muted small" style={{ display: 'flex', flexDirection: 'column' }}>
          Key
          <input placeholder="optional" value={key} onChange={(e) => setKey(e.target.value)} />
        </label>
        <button className="btn" type="submit">
          Apply
        </button>
        <button className="btn secondary" type="button" onClick={useLatestRun}>
          Latest run
        </button>
      </form>
      {error && <div className="error">{error}</div>}
      <div className="muted small" style={{ marginTop: 6 }}>
        total: {total} · page {page}/{totalPages}
      </div>
      <div className="row" style={{ marginTop: 8 }}>
        <button className="btn secondary" disabled={page <= 1 || loading} onClick={() => setPage((p) => p - 1)}>
          Prev
        </button>
        <button
          className="btn secondary"
          disabled={page >= totalPages || loading}
          onClick={() => setPage((p) => p + 1)}
        >
          Next
        </button>
      </div>
      {loading ? (
        <div style={{ marginTop: 12 }}>Loading…</div>
      ) : (
        <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 12 }}>
          {items.map((it) => (
            <div key={it.id} className="card">
              <div className="muted small">
                {it.created_at} · kind: <span className="mono">{it.kind}</span>
                {it.key ? (
                  <>
                    {' '}
                    · key: <span className="mono">{it.key}</span>
                  </>
                ) : null}
                {it.run_id ? (
                  <>
                    {' '}
                    · run: <span className="mono">{it.run_id}</span>
                  </>
                ) : null}
              </div>
              <details style={{ marginTop: 8 }}>
                <summary className="muted">Request</summary>
                <pre className="mono" style={{ whiteSpace: 'pre-wrap' }}>
                  {JSON.stringify(it.request || {}, null, 2)}
                </pre>
              </details>
              <details style={{ marginTop: 8 }} open>
                <summary className="muted">Response</summary>
                <pre className="mono" style={{ whiteSpace: 'pre-wrap' }}>
                  {JSON.stringify(it.response || {}, null, 2)}
                </pre>
              </details>
            </div>
          ))}
          {items.length === 0 && <div className="muted">No logs</div>}
        </div>
      )}
    </section>
  )
}

export default App
