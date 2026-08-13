import { ArrowLeft, Eye, EyeOff, GraduationCap, Info, LockKeyhole, Mail, Play, UserRound } from 'lucide-react'
import { useState } from 'react'
import { loginUser, type UserRole } from './auth'

type LoginPageProps = {
  onLogin: (role: UserRole) => void
  onSignupClick: () => void
  onBack: () => void
  /** 로그인 화면으로 보내진 이유. 세션 만료 안내 등. 입력 오류(message)와 구분한다. */
  notice?: string
}

function LoginPage({ onLogin, onSignupClick, onBack, notice = '' }: LoginPageProps) {
  const [isFindingPassword, setIsFindingPassword] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [role, setRole] = useState<UserRole>('student')
  const [message, setMessage] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    setMessage('')
    setIsSubmitting(true)
    try {
      const user = await loginUser(String(form.get('email') ?? ''), String(form.get('password') ?? ''), role)
      onLogin(user.role)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '로그인에 실패했습니다.')
    } finally {
      setIsSubmitting(false)
    }
  }

  // 비밀번호 재설정 안내.
  //
  // 예전에는 여기에 이메일 입력 폼이 있었고 `POST /auth/password-reset/request`
  // 를 불렀다. **백엔드에 그 경로가 없어서 항상 404 였는데도** 화면은
  // "재설정 안내를 보냈습니다"를 띄웠다. 오지 않는 메일을 기다리게 하는 것보다
  // 지금 할 수 있는 방법을 알려주는 게 낫다. 서버가 준비되면 폼을 되살린다
  // (필요한 조각 목록은 auth.ts 주석에 있다).
  if (isFindingPassword) {
    return (
      <main className="auth-shell">
        <section className="auth-panel">
          <a className="auth-brand" href="#" aria-label="TUTORY 홈">
            <img src="/TUTORY_logo.svg" alt="" />
          </a>

          <div className="auth-heading">
            <span className="section-kicker">계정 도움</span>
            <h1>비밀번호 재설정은 준비 중이에요</h1>
            <p>아직 이메일로 재설정 링크를 보내드릴 수 없습니다. 담당 교수자나 운영자에게 문의하면 계정을 초기화해 드릴 수 있어요.</p>
          </div>

          <p className="auth-message notice">
            <Info size={15} /> 계정을 새로 만들어도 괜찮다면 회원가입으로 바로 시작할 수 있습니다.
          </p>

          <div className="auth-switch">
            <button
              className="auth-back-button"
              type="button"
              onClick={() => setIsFindingPassword(false)}
            >
              <ArrowLeft size={15} />
              로그인으로 돌아가기
            </button>
          </div>

          <div className="auth-switch">
            <span>아직 계정이 없나요?</span>
            <button type="button" onClick={onSignupClick}>회원가입</button>
          </div>
        </section>
      </main>
    )
  }

  return (
    <main className="auth-shell">
      <section className="auth-panel">
        <button className="auth-home-button" type="button" onClick={onBack}><ArrowLeft size={15} /> 홈으로</button>
        <a className="auth-brand" href="#" aria-label="TUTORY 홈">
          <img src="/TUTORY_logo.svg" alt="" />
        </a>

        <div className="auth-heading">
          <span className="section-kicker">Python 학습 시작</span>
          <h1>다시 만나서 반가워요</h1>
          <p>계정으로 로그인하고 오늘의 코딩 문제를 이어서 풀어보세요.</p>
        </div>

        {notice && <p className="auth-message notice"><Info size={15} /> {notice}</p>}

        <form className="auth-form" onSubmit={handleSubmit}>
          <RoleSelector value={role} onChange={setRole} />
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
                name="password"
                placeholder="비밀번호를 입력하세요"
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

          <button
            className="forgot-password-button"
            type="button"
            onClick={() => setIsFindingPassword(true)}
          >
            비밀번호를 잊으셨나요?
          </button>

          <button className="auth-primary-button" type="submit">
            <Play size={17} fill="currentColor" />
            {isSubmitting ? '로그인 중...' : '로그인'}
          </button>
          {message && <p className="auth-message error">{message}</p>}
        </form>

        <div className="auth-switch">
          <span>아직 계정이 없나요?</span>
          <button type="button" onClick={onSignupClick}>회원가입</button>
        </div>
      </section>
    </main>
  )
}

function RoleSelector({ value, onChange }: { value: UserRole; onChange: (role: UserRole) => void }) {
  return <fieldset className="role-selector"><legend>이용 유형</legend><div><button type="button" className={value === 'student' ? 'selected' : ''} onClick={() => onChange('student')}><UserRound size={17} /><span><strong>학생</strong><small>문제를 풀고 튜터링을 받아요</small></span></button><button type="button" className={value === 'educator' ? 'selected' : ''} onClick={() => onChange('educator')}><GraduationCap size={17} /><span><strong>교수자</strong><small>수강생과 과제를 관리해요</small></span></button></div></fieldset>
}

export default LoginPage
