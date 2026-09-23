/**
 * Тонкий клиент REST API: JWT в заголовке, прозрачное обновление access-токена по refresh,
 * ошибки API превращаются в ApiError с текстом от бэкенда.
 */

const ACCESS_KEY = 'cf.access'
const REFRESH_KEY = 'cf.refresh'

// Хранилище может быть недоступно (приватный режим) — тогда токены живут только в памяти
const memory: Record<string, string | null> = {}
const storage = {
  get(key: string): string | null {
    try {
      return window.localStorage.getItem(key)
    } catch {
      return memory[key] ?? null
    }
  },
  set(key: string, value: string | null) {
    memory[key] = value
    try {
      if (value === null) window.localStorage.removeItem(key)
      else window.localStorage.setItem(key, value)
    } catch {
      /* noop */
    }
  },
}

export class ApiError extends Error {
  readonly status: number
  readonly body: unknown

  constructor(status: number, body: unknown) {
    const detail =
      body && typeof body === 'object' && 'detail' in body ? String((body as { detail: unknown }).detail) : ''
    super(detail || `Ошибка запроса (${status})`)
    this.status = status
    this.body = body
  }
}

export const tokens = {
  get access() {
    return storage.get(ACCESS_KEY)
  },
  get refresh() {
    return storage.get(REFRESH_KEY)
  },
  save(access: string, refresh?: string) {
    storage.set(ACCESS_KEY, access)
    if (refresh) storage.set(REFRESH_KEY, refresh)
  },
  clear() {
    storage.set(ACCESS_KEY, null)
    storage.set(REFRESH_KEY, null)
  },
}

let refreshing: Promise<boolean> | null = null

async function refreshAccess(): Promise<boolean> {
  const refresh = tokens.refresh
  if (!refresh) return false
  refreshing ??= fetch('/api/v1/auth/token/refresh/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh }),
  })
    .then(async (r) => {
      if (!r.ok) return false
      const data = (await r.json()) as { access: string; refresh?: string }
      tokens.save(data.access, data.refresh)
      return true
    })
    .finally(() => {
      refreshing = null
    })
  return refreshing
}

type Query = Record<string, string | number | boolean | undefined | null | string[]>

function buildUrl(path: string, query?: Query): string {
  const url = new URL(path.startsWith('/api') ? path : `/api/v1${path}`, window.location.origin)
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === undefined || value === null || value === '') continue
    url.searchParams.set(key, Array.isArray(value) ? value.join(',') : String(value))
  }
  return url.pathname + url.search
}

export async function api<T>(
  path: string,
  options: { method?: string; body?: unknown; query?: Query } = {},
  retry = true,
): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  if (tokens.access) headers.Authorization = `Bearer ${tokens.access}`

  const response = await fetch(buildUrl(path, options.query), {
    method: options.method ?? 'GET',
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  })

  if (response.status === 401 && retry && (await refreshAccess())) {
    return api<T>(path, options, false)
  }
  if (response.status === 204) return undefined as T
  const body = response.headers.get('content-type')?.includes('json') ? await response.json() : null
  if (!response.ok) throw new ApiError(response.status, body)
  return body as T
}

export interface Page<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}
