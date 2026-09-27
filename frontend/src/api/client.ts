/**
 * Тонкий клиент REST API: JWT в заголовке, прозрачное обновление access-токена по refresh,
 * ошибки API превращаются в ApiError с текстом от бэкенда.
 *
 * Запросы идут в API своей подсистемы (корень или /training/). Вход, обновление токена и выход — всегда
 * в основную систему: она выдаёт токены на всю платформу. Вики — одна база знаний платформы.
 */

import { BASE, prefixOf, type ContourCode } from '../contour'

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

// Общие для всей платформы разделы API — всегда основной системы
const PLATFORM = ['/auth/token/', '/auth/logout/', '/wiki/']

function apiPrefix(path: string, contour?: ContourCode): string {
  if (contour) return prefixOf(contour)
  return PLATFORM.some((p) => path.startsWith(p)) ? '' : BASE
}

function buildUrl(path: string, query?: Query, contour?: ContourCode): string {
  const url = new URL(path.startsWith('/api') ? path : `${apiPrefix(path, contour)}/api/v1${path}`, window.location.origin)
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === undefined || value === null || value === '') continue
    url.searchParams.set(key, Array.isArray(value) ? value.join(',') : String(value))
  }
  return url.pathname + url.search
}

export async function api<T>(
  path: string,
  // contour — запрос в другую подсистему тем же входом (например, учения из основной системы)
  options: { method?: string; body?: unknown; query?: Query; contour?: ContourCode } = {},
  retry = true,
): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  if (tokens.access) headers.Authorization = `Bearer ${tokens.access}`

  const response = await fetch(buildUrl(path, options.query, options.contour), {
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

/**
 * Загрузка файла с прогрессом передачи (fetch его не отдаёт) — для многогигабайтных журналов.
 * Перед отправкой обновляем access-токен, чтобы долгая загрузка не упёрлась в его истечение.
 */
export async function upload<T>(path: string, form: FormData, onProgress?: (fraction: number) => void): Promise<T> {
  await refreshAccess()
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', buildUrl(path))
    if (tokens.access) xhr.setRequestHeader('Authorization', `Bearer ${tokens.access}`)
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.(event.loaded / event.total)
    }
    xhr.onload = () => {
      let body: unknown = null
      try {
        body = xhr.responseText ? JSON.parse(xhr.responseText) : null
      } catch {
        body = null
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as T)
      else reject(new ApiError(xhr.status, body))
    }
    xhr.onerror = () => reject(new ApiError(0, { detail: 'Сеть недоступна' }))
    xhr.send(form)
  })
}

/** Скачивание файла с авторизацией: имя берётся из Content-Disposition (RFC 5987) или задаётся явно. */
export async function download(path: string, fallbackName: string, retry = true): Promise<void> {
  const headers: Record<string, string> = {}
  if (tokens.access) headers.Authorization = `Bearer ${tokens.access}`
  const response = await fetch(buildUrl(path), { headers })
  if (response.status === 401 && retry && (await refreshAccess())) return download(path, fallbackName, false)
  if (!response.ok) throw new ApiError(response.status, null)
  const disposition = response.headers.get('content-disposition') ?? ''
  const encoded = /filename\*=utf-8''([^;]+)/i.exec(disposition)?.[1]
  const name = encoded ? decodeURIComponent(encoded) : fallbackName
  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = url
  link.download = name
  link.click()
  URL.revokeObjectURL(url)
}

/** Двоичный ответ с авторизацией (кадр камеры): Blob для URL.createObjectURL. */
export async function apiBlob(path: string, query?: Query, retry = true): Promise<Blob> {
  const headers: Record<string, string> = {}
  if (tokens.access) headers.Authorization = `Bearer ${tokens.access}`
  const response = await fetch(buildUrl(path, query), { headers })
  if (response.status === 401 && retry && (await refreshAccess())) return apiBlob(path, query, false)
  if (!response.ok) {
    const body = response.headers.get('content-type')?.includes('json') ? await response.json() : null
    throw new ApiError(response.status, body)
  }
  return response.blob()
}
