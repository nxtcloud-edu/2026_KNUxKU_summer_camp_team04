import { ArrowLeft, Eye, EyeOff, LockKeyhole, Mail, Play, Send } from 'lucide-react'
import { useState } from 'react'

type LoginPageProps = {
  onLogin: () => void
  onSignupClick: () => void
}

function LoginPage({ onLogin, onSignupClick }: LoginPageProps) {
  const [isFindingPassword, setIsFindingPassword] = useState(false)
  const [resetRequested, setResetRequested] = useState(false)
  const [showPassword, setShowPassword] = useState(false)

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    onLogin()
  }

  const handlePasswordReset = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setResetRequested(true)
  }

  if (isFindingPassword) {
    return (
      <main className="auth-shell">
        <section className="auth-panel">
          <a className="auth-brand" href="#" aria-label="TUTORY 홈">
            <img src="/TUTORY_logo.svg" alt="" />
          </a>

          <div className="auth-heading">
            <span className="section-kicker">계정 도움</span>
            <h1>비밀번호를 찾을게요</h1>
            <p>가입한 이메일을 입력하면 비밀번호 재설정 안내를 받을 수 있습니다.</p>
          </div>

          <form className="auth-form" onSubmit={handlePasswordReset}>
            <label className="auth-field">
              <span>이메일</span>
              <div>
                <Mail size={17} />
                <input type="email" placeholder="name@example.com" required />
              </div>
            </label>

            {resetRequested && (
              <p className="auth-message">입력한 이메일로 재설정 안내를 보냈습니다.</p>
            )}

            <button className="auth-primary-button" type="submit">
              <Send size={17} />
              재설정 안내 받기
            </button>
          </form>

          <div className="auth-switch">
            <button
              className="auth-back-button"
              type="button"
              onClick={() => {
                setIsFindingPassword(false)
                setResetRequested(false)
              }}
            >
              <ArrowLeft size={15} />
              로그인으로 돌아가기
            </button>
          </div>
        </section>
      </main>
    )
  }

  return (
    <main className="auth-shell">
      <section className="auth-panel">
        <a className="auth-brand" href="#" aria-label="TUTORY 홈">
          <img src="/TUTORY_logo.svg" alt="" />
        </a>

        <div className="auth-heading">
          <span className="section-kicker">Python 학습 시작</span>
          <h1>다시 만나서 반가워요</h1>
          <p>계정으로 로그인하고 오늘의 코딩 문제를 이어서 풀어보세요.</p>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          <label className="auth-field">
            <span>이메일</span>
            <div>
              <Mail size={17} />
              <input type="email" placeholder="name@example.com" required />
            </div>
          </label>

          <label className="auth-field">
            <span>비밀번호</span>
            <div>
              <LockKeyhole size={17} />
              <input
                type={showPassword ? 'text' : 'password'}
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
            로그인
          </button>
        </form>

        <div className="auth-switch">
          <span>아직 계정이 없나요?</span>
          <button type="button" onClick={onSignupClick}>회원가입</button>
        </div>
      </section>
    </main>
  )
}

export default LoginPage
