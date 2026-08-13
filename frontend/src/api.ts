export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '')
export const isApiConfigured = Boolean(API_BASE_URL)

export type ApiRequestOptions = RequestInit & {
  auth?: boolean
}

export async function apiRequest<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  if (!API_BASE_URL) throw new Error('API 서버가 연결되지 않았습니다. VITE_API_BASE_URL을 설정해 주세요.')

  const headers = new Headers(options.headers)
  if (!headers.has('Accept')) headers.set('Accept', 'application/json')
  if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')

  if (options.auth !== false) {
    const token = getAccessToken()
    if (token) headers.set('Authorization', `Bearer ${token}`)
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
  })
  const payload: unknown = await response.json().catch(() => null)

  if (!response.ok) throw new Error(getApiErrorMessage(payload, `API returned ${response.status}`))
  return payload as T
}

export function getAccessToken() {
  return localStorage.getItem('tutory:access-token') ?? ''
}

export function setAccessToken(token: string) {
  if (token) localStorage.setItem('tutory:access-token', token)
  else localStorage.removeItem('tutory:access-token')
}

export function getApiErrorMessage(payload: unknown, fallback: string) {
  if (!isObject(payload)) return fallback
  if (typeof payload.detail === 'string') return payload.detail
  if (isObject(payload.detail) && typeof payload.detail.message === 'string') return payload.detail.message
  if (Array.isArray(payload.detail)) {
    const messages = payload.detail
      .map((item) => isObject(item) && typeof item.msg === 'string' ? item.msg : null)
      .filter(Boolean)
    return messages.join(', ') || fallback
  }
  if (typeof payload.message === 'string') return payload.message
  return fallback
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}
