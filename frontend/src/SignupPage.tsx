import { ArrowLeft, Check, Eye, EyeOff, GraduationCap, LockKeyhole, Mail, UserRound } from 'lucide-react'
import { useMemo, useState } from 'react'
import { signupUser, type UserRole } from './auth'

type SignupPageProps = {
  onSignup: (role: UserRole) => void
  onLoginClick: () => void
  onBack: () => void
}

function SignupPage({ onSignup, onLoginClick, onBack }: SignupPageProps) {
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [role, setRole] = useState<UserRole>('student')
  const [message, setMessage] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const passwordRules = useMemo(() => ({
    minLength: password.length >= 6,
    hasLetterAndNumber: /[A-Za-z]/.test(password) && /\d/.test(password),
  }), [password])
  const isPasswordValid = passwordRules.minLength && passwordRules.hasLetterAndNumber

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!isPasswordValid) {
      setMessage('비밀번호 조건을 모두 만족해야 회원가입할 수 있어요.')
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
            <span>비밀번호</span>
            <div>
              <LockKeyhole size={17} />
              <input
                type={showPassword ? 'text' : 'password'}
                placeholder="영문과 숫자를 포함해 입력하세요"
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
            <span className={passwordRules.minLength ? 'valid' : ''}><Check size={13} />6자리 이상</span>
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
