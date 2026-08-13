import { Check, Eye, EyeOff, LockKeyhole, Mail, UserRound } from 'lucide-react'
import { useState } from 'react'

type SignupPageProps = {
  onSignup: () => void
  onLoginClick: () => void
}

function SignupPage({ onSignup, onLoginClick }: SignupPageProps) {
  const [showPassword, setShowPassword] = useState(false)

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    onSignup()
  }

  return (
    <main className="auth-shell">
      <section className="auth-panel signup-panel">
        <a className="auth-brand" href="#" aria-label="TUTORY 홈">
          <img src="/TUTORY_logo.svg" alt="" />
          <span>TUTORY</span>
        </a>

        <div className="auth-heading">
          <span className="section-kicker">새 학습자 등록</span>
          <h1>튜토리와 함께 시작해요</h1>
          <p>간단한 정보만 입력하면 바로 Python 문제 풀이 화면으로 이동합니다.</p>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          <label className="auth-field">
            <span>이름</span>
            <div>
              <UserRound size={17} />
              <input type="text" placeholder="이름을 입력하세요" required />
            </div>
          </label>

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
                placeholder="8자 이상 입력하세요"
                minLength={8}
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

          <button className="auth-primary-button" type="submit">
            <Check size={17} />
            회원가입
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
