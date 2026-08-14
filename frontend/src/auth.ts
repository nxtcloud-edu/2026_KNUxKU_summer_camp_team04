import { apiRequest, isApiConfigured, setAccessToken } from './api'

const LOCAL_USER_KEY = 'tutory:local-user'

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
  if (!isApiConfigured) return persistLocalUser(normalizeUser(undefined, email, role))
  const response = await apiRequest<AuthResponse>('/auth/login', {
    method: 'POST',
    auth: false,
    body: JSON.stringify({ email, password, role: role.toUpperCase() }),
  })
  const user = normalizeUser(response.user, email, role)
  if (user.role !== role) {
    setAccessToken('')
    throw new Error(role === 'educator'
      ? '이 이메일은 학생 계정입니다. 학생으로 로그인하거나 교수자 계정을 확인해 주세요.'
      : '이 이메일은 교수자 계정입니다. 교수자로 로그인해 주세요.')
  }
  persistToken(response)
  return user
}

/**
 * 회원가입.
 *
 * `inviteCode` 는 **교수자 가입에 필수다.** 백엔드
 * `auth/service.resolve_organization` 이 role=EDUCATOR 인데 코드가 없으면
 * 422(INVALID_INVITE_CODE)를 던진다 -- 역할을 요청 body 로 받는 이상 가입
 * 자체에 게이트가 없으면 누구나 교수자가 되어 남의 강의 API를 두드릴 수 있다.
 *
 * 학생은 선택이다. 코드를 주면 그 기관에 붙고, 없으면 이메일 도메인으로
 * 자동 연결된다(제휴 기관이 없으면 소속 없이 가입).
 *
 * 빈 문자열은 **보내지 않는다.** 백엔드가 `if invite_code:` 로 판정하므로
 * 결과는 같지만, 요청 본문에 의미 없는 키를 남기지 않는다.
 */
export async function signupUser(
  name: string,
  email: string,
  password: string,
  role: UserRole,
  inviteCode = '',
): Promise<AuthUser> {
  // 백엔드를 붙이지 않은 데모 모드. loginUser 와 같은 방식으로 로컬 사용자를
  // 보관해야 새로고침 후에도 로그인 상태가 유지된다.
  if (!isApiConfigured) return persistLocalUser(normalizeUser(undefined, email, role, name))
  const trimmedInviteCode = inviteCode.trim()
  const response = await apiRequest<AuthResponse>('/auth/signup', {
    method: 'POST',
    auth: false,
    body: JSON.stringify({
      name,
      email,
      password,
      role: role.toUpperCase(),
      ...(trimmedInviteCode
        ? role === 'educator'
          ? { invite_code: trimmedInviteCode }
          : { course_invite_code: trimmedInviteCode }
        : {}),
    }),
  })
  persistToken(response)
  return normalizeUser(response.user, email, role, name)
}

export async function logoutUser() {
  if (isApiConfigured) {
    // 토큰을 그대로 실어 보낸다 -- 나중에 서버가 토큰 블랙리스트를 붙일 때
    // 프런트를 고치지 않아도 되게 하려는 것이 이 엔드포인트의 목적이다
    // (backend/app/auth/router.py 의 logout 독스트링).
    //
    // 단 401 은 세션 만료로 처리하지 않는다. 토큰이 이미 만료된 상태에서
    // 로그아웃을 누르면 "로그인이 만료되었어요" 화면으로 튕겨나가는데,
    // 사용자는 방금 나가려고 눌렀다.
    await apiRequest('/auth/logout', { method: 'POST', notifyOnUnauthorized: false }).catch((error) => {
      console.warn('Logout API unavailable. Clearing local auth state.', error)
    })
  }
  setAccessToken('')
  localStorage.removeItem(LOCAL_USER_KEY)
}

export async function getCurrentUser(): Promise<AuthUser | null> {
  if (!isApiConfigured) return getLocalUser()
  const response = await apiRequest<Partial<AuthUser> | AuthResponse>('/auth/me')
  if (isAuthResponse(response)) return normalizeUser(response.user, '', 'student')
  return normalizeUser(response, '', 'student')
}

/**
 * 비밀번호 재설정은 **아직 서버에 없다.**
 *
 * 여기 있던 `POST /auth/password-reset/request` 호출은 제거했다. 백엔드
 * `app/auth/router.py` 에 그 경로가 없어서 항상 404 였고, 그런데도 화면은
 * "입력한 이메일로 재설정 안내를 보냈습니다"를 띄우고 있었다 -- 학생은
 * 오지 않는 메일을 기다리게 된다.
 *
 * 켜려면 세 조각이 다 필요하다:
 *   1. `POST /auth/password-reset/request` -- 계정 열거 방지를 위해 성공/실패
 *      무관하게 204. `models.PasswordResetToken`(테이블은 이미 있다)에 토큰
 *      **해시**를 저장.
 *   2. 메일 발송 경로. 이게 없으면 1번만 만들어도 사용자에게 토큰이 도달하지 않는다.
 *   3. `POST /auth/password-reset/confirm {token, new_password}` + 새 비밀번호
 *      입력 화면.
 *
 * 1번만 먼저 만들면 "요청은 되는데 재설정은 안 되는" 상태가 되므로, 세 조각을
 * 한 번에 하기 전까지는 화면에서 기능을 약속하지 않는다(LoginPage 참고).
 */

function persistToken(response: AuthResponse) {
  setAccessToken(response.access_token ?? response.token ?? '')
}

function persistLocalUser(user: AuthUser) {
  localStorage.setItem(LOCAL_USER_KEY, JSON.stringify(user))
  return user
}

function getLocalUser(): AuthUser | null {
  try {
    const saved = localStorage.getItem(LOCAL_USER_KEY)
    return saved ? JSON.parse(saved) as AuthUser : null
  } catch {
    localStorage.removeItem(LOCAL_USER_KEY)
    return null
  }
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
