export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '')
export const isApiConfigured = Boolean(API_BASE_URL)

export type ApiRequestOptions = RequestInit & {
  auth?: boolean
}

/**
 * HTTP 상태 코드를 들고 다니는 에러.
 *
 * 호출부가 "왜" 실패했는지로 분기해야 하는 경우가 있다. 대표적으로
 * `POST /sessions/{id}/run` 은 서버 judge 가 꺼져 있으면 503(JUDGE_UNAVAILABLE)
 * 을 주는데, 이건 학생 코드 문제가 아니므로 로컬 실행으로 넘어가야 한다.
 */
export class ApiError extends Error {
  readonly status: number
  readonly payload: unknown

  constructor(message: string, status: number, payload: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.payload = payload
  }
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

  if (!response.ok) {
    throw new ApiError(getApiErrorMessage(payload, `API returned ${response.status}`), response.status, payload)
  }
  return payload as T
}

/**
 * 페이지 이탈 중에 마지막 요청을 흘려보낸다.
 *
 * `navigator.sendBeacon` 이 아니라 `fetch(keepalive)` 를 쓴다. beacon 은
 * **커스텀 헤더를 붙일 수 없어서** `Authorization` 을 실을 방법이 없고,
 * 백엔드(`app/auth/deps.py`)는 Authorization 헤더만 읽으므로 전부 401 로 버려진다.
 * keepalive fetch 는 unload 중에도 전송을 이어가면서 헤더를 붙일 수 있다.
 */
export function apiKeepalive(path: string, body: unknown): void {
  if (!API_BASE_URL) return
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const token = getAccessToken()
  if (token) headers.Authorization = `Bearer ${token}`
  void fetch(`${API_BASE_URL}${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
    keepalive: true,
  }).catch(() => {
    // unload 중이다. 보고할 곳도 재시도할 시간도 없다.
  })
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
