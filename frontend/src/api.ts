export type LoginResponse = {
  access_token: string
  token_type: string
  expires_in: number
}

export type Config = {
  industry: string
  location: string
  company_size_min: number
  daily_objective: number
  linkup_search_depth: 'standard' | 'deep'
  email_subject_template: string
  email_body_template: string
  alert_email: string
  run_mode: 'live' | 'dry_run'
}

export type BlacklistEntry = {
  id: number
  entry_type: 'company_name' | 'domain'
  value_raw: string
  value_norm: string
  created_at: string
}

export type Paginated<T> = {
  items: T[]
  page: number
  page_size: number
  total: number
}

export type ProviderLogItem = {
  id: number
  created_at: string
  run_id: string | null
  provider: string
  kind: string
  key: string | null
  request: Record<string, unknown>
  response: Record<string, unknown>
}

export type HistoryRow = {
  date_time: string
  company_name: string | null
  company_domain: string | null
  employee_count: number | null
  first_name: string | null
  last_name: string | null
  email: string | null
  job_title: string | null
  status_code: string
  status_detail: string | null
  run_id: string
}

export type RunResponse = {
  run_id: string
  created_drafts: number
  quota: number
  excluded_count: number
  enrich_failed_count: number
  pool_exhausted: boolean
  errors: Array<Record<string, unknown>>
}

export const API_BASE = (import.meta.env.VITE_API_BASE_URL as string) || 'http://localhost:8000'
const TOKEN_KEY = 'bakliz_token'
export const UNAUTHORIZED_EVENT = 'bakliz:unauthorized'

function notifyUnauthorized() {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
  notifyUnauthorized()
}

async function readErrorMessage(res: Response): Promise<string> {
  try {
    const text = (await res.text()).trim()
    if (!text) return res.statusText || `HTTP ${res.status}`

    const contentType = res.headers.get('content-type') || ''
    if (!contentType.includes('application/json')) return text

    const body = JSON.parse(text) as unknown
    if (!body || typeof body !== 'object' || !('detail' in body)) return text

    const detail = (body as { detail?: unknown }).detail
    if (typeof detail === 'string') return detail
    return JSON.stringify(detail)
  } catch {
    return res.statusText || `HTTP ${res.status}`
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken()
  const headers = new Headers(options.headers || {})
  headers.set('Content-Type', 'application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)

  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, { ...options, headers })
  } catch (e: unknown) {
    const hint = `Cannot reach API at ${API_BASE} (request: ${path})`
    throw new Error(e instanceof Error && e.message ? `${hint}: ${e.message}` : hint)
  }
  if (res.status === 401) {
    const msg = await readErrorMessage(res)
    clearToken()
    throw new Error(msg)
  }
  if (!res.ok) {
    const msg = await readErrorMessage(res)
    throw new Error(msg || `HTTP ${res.status}`)
  }
  return (await res.json()) as T
}

async function requestStream(
  path: string,
  options: RequestInit,
  onEvent: (ev: Record<string, unknown>) => void,
): Promise<void> {
  const token = getToken()
  const headers = new Headers(options.headers || {})
  headers.set('Content-Type', 'application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)

  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, { ...options, headers })
  } catch (e: unknown) {
    const hint = `Cannot reach API at ${API_BASE} (request: ${path})`
    throw new Error(e instanceof Error && e.message ? `${hint}: ${e.message}` : hint)
  }
  if (res.status === 401) {
    const msg = await readErrorMessage(res)
    clearToken()
    throw new Error(msg)
  }
  if (!res.ok || !res.body) {
    const msg = await readErrorMessage(res)
    throw new Error(msg || `HTTP ${res.status}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  // NDJSON: each line is a JSON object
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let idx = buffer.indexOf('\n')
    while (idx >= 0) {
      const line = buffer.slice(0, idx).trim()
      buffer = buffer.slice(idx + 1)
      if (line) {
        onEvent(JSON.parse(line) as Record<string, unknown>)
      }
      idx = buffer.indexOf('\n')
    }
  }
}

export const api = {
  ping() {
    return request<{ ok: boolean }>('/api/auth/ping')
  },
  login(username: string, password: string) {
    return request<LoginResponse>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
      headers: {},
    })
  },
  getConfig() {
    return request<Config>('/api/config')
  },
  updateConfig(cfg: Config) {
    return request<Config>('/api/config', { method: 'PUT', body: JSON.stringify(cfg) })
  },
  listBlacklist(page = 1, page_size = 50) {
    return request<Paginated<BlacklistEntry>>(
      `/api/blacklist?page=${page}&page_size=${page_size}`,
    )
  },
  listRuns(page = 1, page_size = 50) {
    return request<Paginated<{
      run_id: string
      started_at: string
      finished_at: string | null
      quota: number
      created_drafts: number
      excluded_count: number
      enrich_failed_count: number
      pool_exhausted: boolean
      run_mode: string
    }>>(`/api/runs?page=${page}&page_size=${page_size}`)
  },
  createBlacklist(payload: { entry_type: 'company_name' | 'domain'; value: string }) {
    return request<BlacklistEntry>('/api/blacklist', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  deleteBlacklist(id: number) {
    return request<{ deleted: boolean }>(`/api/blacklist/${id}`, { method: 'DELETE' })
  },
  listHistory(params: {
    page: number
    page_size: number
    from?: string
    to?: string
    status_code?: string
    company?: string
    domain?: string
    run_id?: string
  }) {
    const qs = new URLSearchParams()
    qs.set('page', String(params.page))
    qs.set('page_size', String(params.page_size))
    if (params.from) qs.set('from', params.from)
    if (params.to) qs.set('to', params.to)
    if (params.status_code) qs.set('status_code', params.status_code)
    if (params.company) qs.set('company', params.company)
    if (params.domain) qs.set('domain', params.domain)
    if (params.run_id) qs.set('run_id', params.run_id)
    return request<Paginated<HistoryRow>>(`/api/history?${qs.toString()}`)
  },
  clearHistory(params: { run_id?: string }) {
    const qs = new URLSearchParams()
    qs.set('confirm', 'DELETE')
    if (params.run_id) qs.set('run_id', params.run_id)
    return request<{ deleted: number }>(`/api/history?${qs.toString()}`, { method: 'DELETE' })
  },
  listProviderLogs(params: {
    page: number
    page_size: number
    provider?: 'linkup' | 'zeliq'
    kind?: string
    run_id?: string
    key?: string
  }) {
    const qs = new URLSearchParams()
    qs.set('page', String(params.page))
    qs.set('page_size', String(params.page_size))
    if (params.provider) qs.set('provider', params.provider)
    if (params.kind) qs.set('kind', params.kind)
    if (params.run_id) qs.set('run_id', params.run_id)
    if (params.key) qs.set('key', params.key)
    return request<Paginated<ProviderLogItem>>(`/api/provider-logs?${qs.toString()}`)
  },
  runNow(params: { dry_run: boolean; overrides?: Record<string, unknown> }) {
    const qs = params.dry_run ? '?dry_run=true' : ''
    return request<RunResponse>(`/api/run${qs}`, {
      method: 'POST',
      body: JSON.stringify({ overrides: params.overrides || {} }),
    })
  },
  async runNowStream(
    params: { dry_run: boolean; overrides?: Record<string, unknown>; signal?: AbortSignal },
    onEvent: (ev: Record<string, unknown>) => void,
  ) {
    const qs = params.dry_run ? '?dry_run=true' : ''
    return requestStream(
      `/api/run/stream${qs}`,
      {
        method: 'POST',
        body: JSON.stringify({ overrides: params.overrides || {} }),
        signal: params.signal,
      },
      onEvent,
    )
  },
}
