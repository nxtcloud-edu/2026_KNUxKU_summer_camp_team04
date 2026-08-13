import { LockKeyhole, Mail, Play } from 'lucide-react'

type LoginPageProps = {
  onLogin: () => void
  onSignupClick: () => void
}

function LoginPage({ onLogin, onSignupClick }: LoginPageProps) {
  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    onLogin()
  }

  return (
    <main className="auth-shell">
      <section className="auth-panel">
        <a className="auth-brand" href="#" aria-label="TUTORY 홈">
          <img src="/TUTORY_logo.svg" alt="" />
          <span>TUTORY</span>
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
              <input type="password" placeholder="비밀번호를 입력하세요" required />
            </div>
          </label>

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
