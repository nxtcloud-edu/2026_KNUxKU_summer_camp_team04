import { apiRequest, isApiConfigured, setAccessToken } from './api'

export type UserRole = 'student' | 'educator'

export type AuthUser = {
  id: string
  email: string
  name: string
  nickname?: string
  role: UserRole
  avatar_url?: string
  acorn_balance?: number
  total_acorns_earned?: number
}

type AuthResponse = {
  access_token?: string
  token?: string
  user?: Partial<AuthUser> & { role?: UserRole | 'STUDENT' | 'EDUCATOR' }
}

export async function loginUser(email: string, password: string, role: UserRole): Promise<AuthUser> {
  requireAuthApi()
  const response = await apiRequest<AuthResponse>('/auth/login', {
    method: 'POST',
    auth: false,
    body: JSON.stringify({ email, password, role: role.toUpperCase() }),
  })
  persistToken(response)
  return normalizeUser(response.user, email, role)
}

export async function signupUser(name: string, email: string, password: string, role: UserRole): Promise<AuthUser> {
  requireAuthApi()
  const response = await apiRequest<AuthResponse>('/auth/signup', {
    method: 'POST',
    auth: false,
    body: JSON.stringify({ name, email, password, role: role.toUpperCase() }),
  })
  persistToken(response)
  return normalizeUser(response.user, email, role, name)
}

export async function logoutUser() {
  if (isApiConfigured) {
    await apiRequest('/auth/logout', { method: 'POST' }).catch((error) => {
      console.warn('Logout API unavailable. Clearing local auth state.', error)
    })
  }
  setAccessToken('')
}

export async function getCurrentUser(): Promise<AuthUser | null> {
  if (!isApiConfigured) return null
  const response = await apiRequest<Partial<AuthUser> | AuthResponse>('/auth/me')
  if (isAuthResponse(response)) return normalizeUser(response.user, '', 'student')
  return normalizeUser(response, '', 'student')
}

export async function requestPasswordReset(email: string) {
  requireAuthApi()
  await apiRequest('/auth/password-reset/request', {
    method: 'POST',
    auth: false,
    body: JSON.stringify({ email }),
  })
}

function requireAuthApi() {
  if (!isApiConfigured) {
    throw new Error('인증 API가 연결되지 않았습니다. frontend/.env의 VITE_API_BASE_URL을 확인해 주세요.')
  }
}

function persistToken(response: AuthResponse) {
  setAccessToken(response.access_token ?? response.token ?? '')
}

function normalizeUser(payload: (Partial<AuthUser> & { role?: string }) | undefined, email: string, fallbackRole: UserRole, fallbackName = ''): AuthUser {
  const rawRole = String(payload?.role ?? '').toLowerCase()
  const role = rawRole === 'educator'
    ? 'educator'
    : rawRole === 'student'
      ? 'student'
      : fallbackRole

  return {
    id: payload?.id ?? 'demo-user',
    email: payload?.email ?? email,
    name: payload?.name ?? (fallbackName || email.split('@')[0] || 'Tutory User'),
    nickname: payload?.nickname,
    role,
    avatar_url: payload?.avatar_url,
    acorn_balance: payload?.acorn_balance,
    total_acorns_earned: payload?.total_acorns_earned,
  }
}

function isAuthResponse(value: Partial<AuthUser> | AuthResponse): value is AuthResponse {
  return 'user' in value || 'access_token' in value || 'token' in value
}

