export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '')
export const isApiConfigured = Boolean(API_BASE_URL)

export type ApiRequestOptions = RequestInit & {
  auth?: boolean
  /**
   * 401 을 "세션 만료"로 취급할지. 기본 true.
   *
   * `false` 로 두는 경우는 하나다 -- **로그아웃.** 만료된 토큰으로 로그아웃을
   * 누르면 `/auth/logout` 이 401 을 주는데, 그걸 만료로 처리하면 방금 나가려던
   * 사용자를 "로그인이 만료되었어요" 화면으로 밀어넣는다.
   */
  notifyOnUnauthorized?: boolean
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

  // 실제로 토큰을 실었는지 기록해둔다. 아래 401 처리가 이 값에 의존한다.
  const sentToken = options.auth !== false ? getAccessToken() : ''
  if (sentToken) headers.set('Authorization', `Bearer ${sentToken}`)

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
  })
  const payload: unknown = await response.json().catch(() => null)

  if (!response.ok) {
    // 우리가 보낸 토큰이 거부됐다 = 세션이 죽었다. 토큰을 버리고 구독자에게 알린다.
    //
    // **`sentToken` 조건이 핵심이다.** `POST /auth/login` 은 비밀번호가 틀리면
    // 똑같이 401(INVALID_CREDENTIALS)을 주는데, 그건 세션 만료가 아니라 입력
    // 오류다. 로그인/회원가입은 `auth: false` 로 호출되므로 sentToken 이 비어
    // 있고, 따라서 이 분기를 타지 않는다. 조건 없이 status 만 보면 로그인
    // 실패가 "로그인이 만료되었어요" 화면을 띄우는 엉뚱한 동작이 된다.
    if (response.status === 401 && sentToken && options.notifyOnUnauthorized !== false) {
      notifyUnauthorized()
    }
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

type UnauthorizedListener = () => void
const unauthorizedListeners = new Set<UnauthorizedListener>()

/**
 * 세션 만료(401) 알림을 구독한다. 반환값은 구독 해지 함수.
 *
 * 토큰 만료는 720분 뒤에 조용히 찾아온다(`ACCESS_TOKEN_EXPIRE_MINUTES`).
 * 이 훅이 없으면 죽은 토큰이 localStorage 에 그대로 남아 세션 생성 · 이벤트
 * 전송 · 채점이 전부 401 로 실패하는데 화면에는 아무 설명도 나오지 않는다.
 *
 * 알림 시점에 토큰은 **이미 폐기되어 있다.** 구독자가 할 일은 화면 상태를
 * 비로그인으로 되돌리는 것뿐이다.
 */
export function onUnauthorized(listener: UnauthorizedListener): () => void {
  unauthorizedListeners.add(listener)
  return () => {
    unauthorizedListeners.delete(listener)
  }
}

function notifyUnauthorized() {
  // 토큰을 먼저 버린다. 구독자가 이 알림을 받고 다시 API 를 부를 수도 있는데
  // 그때 죽은 토큰이 남아 있으면 401 이 또 나서 알림이 재귀한다.
  if (!getAccessToken()) return
  setAccessToken('')
  for (const listener of unauthorizedListeners) {
    try {
      listener()
    } catch (error) {
      console.warn('세션 만료 처리 중 오류.', error)
    }
  }
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
