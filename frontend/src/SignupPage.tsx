import { ArrowLeft, Check, Eye, EyeOff, GraduationCap, KeyRound, LockKeyhole, Mail, UserRound } from 'lucide-react'
import { useMemo, useState } from 'react'
import { signupUser, type UserRole } from './auth'

type SignupPageProps = {
  onSignup: (role: UserRole) => void
  onLoginClick: () => void
  onBack: () => void
}

/**
 * 비밀번호 최소 길이. **백엔드와 같은 값이어야 한다.**
 *
 * 백엔드는 `SignupRequest.password = Field(min_length=8)`(app/auth/schemas.py)
 * 이다. 여기가 6이었을 때는 6~7자를 입력하면 화면상 모든 조건이 초록색인데
 * 서버가 422 를 돌려줬다 -- 학생 입장에서는 이유를 알 수 없는 실패였다.
 */
const PASSWORD_MIN_LENGTH = 8

function SignupPage({ onSignup, onLoginClick, onBack }: SignupPageProps) {
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [role, setRole] = useState<UserRole>('student')
  const [inviteCode, setInviteCode] = useState('')
  const [message, setMessage] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const passwordRules = useMemo(() => ({
    minLength: password.length >= PASSWORD_MIN_LENGTH,
    hasLetterAndNumber: /[A-Za-z]/.test(password) && /\d/.test(password),
  }), [password])
  const isPasswordValid = passwordRules.minLength && passwordRules.hasLetterAndNumber
  // 교수자는 기관 초대 코드가 필수다 (백엔드 auth/service.resolve_organization).
  // 학생은 선택 -- 코드가 없으면 이메일 도메인으로 자동 연결된다.
  const isInviteCodeRequired = role === 'educator'

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!isPasswordValid) {
      setMessage('비밀번호 조건을 모두 만족해야 회원가입할 수 있어요.')
      return
    }
    // 서버도 막지만(422), 여기서 먼저 걸러 학생에게 이유를 정확히 알려준다.
    if (isInviteCodeRequired && !inviteCode.trim()) {
      setMessage('교수자 가입에는 기관 초대 코드가 필요해요. 소속 기관 담당자에게 코드를 받아주세요.')
      return
    }

    const form = new FormData(event.currentTarget)
    setMessage('')
    setIsSubmitting(true)
    try {
      const user = await signupUser(
        String(form.get('name') ?? ''),
        String(form.get('email') ?? ''),
        password,
        role,
        inviteCode,
      )
      onSignup(user.role)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '회원가입에 실패했습니다.')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <main className="auth-shell">
      <section className="auth-panel">
        <button className="auth-home-button" type="button" onClick={onBack}><ArrowLeft size={15} /> 홈으로</button>
        <a className="auth-brand" href="#" aria-label="TUTORY 홈">
          <img src="/TUTORY_logo.svg" alt="" />
        </a>

        <div className="auth-heading">
          <span className="section-kicker">새 학습자 등록</span>
          <h1>튜토리와 함께 시작해요</h1>
          <p>간단한 정보만 입력하면 바로 Python 문제 풀이 화면으로 이동합니다.</p>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          <fieldset className="role-selector">
            <legend>이용 유형</legend>
            <div>
              <button type="button" className={role === 'student' ? 'selected' : ''} onClick={() => setRole('student')}>
                <UserRound size={17} />
                <span><strong>학생</strong><small>문제를 풀고 튜터링을 받아요</small></span>
              </button>
              <button type="button" className={role === 'educator' ? 'selected' : ''} onClick={() => setRole('educator')}>
                <GraduationCap size={17} />
                <span><strong>교수자</strong><small>수강생과 과제를 관리해요</small></span>
              </button>
            </div>
          </fieldset>

          <label className="auth-field">
            <span>이름</span>
            <div>
              <UserRound size={17} />
              <input name="name" type="text" placeholder="이름을 입력하세요" required />
            </div>
          </label>

          <label className="auth-field">
            <span>이메일</span>
            <div>
              <Mail size={17} />
              <input name="email" type="email" placeholder="name@example.com" required />
            </div>
          </label>

          <label className="auth-field">
            <span>{isInviteCodeRequired ? '기관 초대 코드' : '강의 초대 코드 (선택)'}</span>
            <div>
              <KeyRound size={17} />
              <input
                type="text"
                name="invite_code"
                placeholder={isInviteCodeRequired ? '소속 기관에서 받은 코드' : '교수자에게 받은 강의 코드'}
                value={inviteCode}
                onChange={(event) => setInviteCode(event.target.value)}
                autoComplete="off"
                required={isInviteCodeRequired}
              />
            </div>
          </label>
          <p className="auth-hint">
            {isInviteCodeRequired
              ? '교수자 계정은 기관 확인이 필요해요. 코드는 소속 기관 담당자에게 받을 수 있습니다.'
              : '교수자에게 받은 강의 코드를 입력하면 가입과 동시에 수강 등록돼요. 없어도 가입할 수 있습니다.'}
          </p>

          <label className="auth-field">
            <span>비밀번호</span>
            <div>
              <LockKeyhole size={17} />
              <input
                type={showPassword ? 'text' : 'password'}
                placeholder={`${PASSWORD_MIN_LENGTH}자 이상, 영문과 숫자를 포함해 입력하세요`}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
              <button
                className="password-toggle"
                type="button"
                aria-label={showPassword ? '비밀번호 숨기기' : '비밀번호 보기'}
                onClick={() => setShowPassword((visible) => !visible)}
              >
                {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
              </button>
            </div>
          </label>

          <div className="password-rules" aria-live="polite">
            <span className={passwordRules.minLength ? 'valid' : ''}><Check size={13} />{PASSWORD_MIN_LENGTH}자리 이상</span>
            <span className={passwordRules.hasLetterAndNumber ? 'valid' : ''}><Check size={13} />영문, 숫자 조합</span>
          </div>
          {message && <p className="auth-message error">{message}</p>}

          <button className="auth-primary-button" type="submit" disabled={isSubmitting}>
            <Check size={17} />
            {isSubmitting ? '가입 중...' : '회원가입'}
          </button>
        </form>

        <div className="auth-switch">
          <span>이미 계정이 있나요?</span>
          <button type="button" onClick={onLoginClick}>로그인</button>
        </div>
      </section>
    </main>
  )
}

export default SignupPage
