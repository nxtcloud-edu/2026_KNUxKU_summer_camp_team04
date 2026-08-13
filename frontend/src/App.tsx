import { useEffect, useRef, useState, type ReactNode } from 'react'
import Editor, { type OnMount } from '@monaco-editor/react'
import {
  BookOpen,
  Check,
  ChevronDown,
  CircleAlert,
  Code2,
  LoaderCircle,
  LogIn,
  LogOut,
  Monitor,
  Moon,
  MoreVertical,
  Play,
  RotateCcw,
  Send,
  Sun,
  Terminal,
  UserRound,
  Waypoints,
} from 'lucide-react'
import AiTutorPanel from './AiTutorPanel'
import LoginPage from './LoginPage'
import MyPage from './MyPage'
import { preparePython } from './pythonRunner'
import { TraceActivity } from './traceActivity'
import { ProblemList } from './problemList'
import {
  getProblemDetail,
  isJudgeApiConfigured,
  type JudgeResult,
  type ProblemDetail,
  type ProblemSummary,
  type PublicTestCase,
} from './problemService'
import { runJudge } from './traceClient'
import { useCodingTrace } from './useCodingTrace'
import SignupPage from './SignupPage'

type RunMode = 'run' | 'submit'
type RuntimeStatus = 'loading' | 'ready' | 'error'
type ThemeMode = 'system' | 'light' | 'dark'
type AuthView = 'login' | 'signup' | 'workspace'
type Activity = 'problem' | 'trace' | 'list' | 'mypage'

function App() {
  const [authView, setAuthView] = useState<AuthView>('workspace')
  const [isAuthenticated, setIsAuthenticated] = useState(false)

  if (authView === 'login') {
    return (
      <LoginPage
        onLogin={() => {
          setIsAuthenticated(true)
          setAuthView('workspace')
        }}
        onSignupClick={() => setAuthView('signup')}
      />
    )
  }

  if (authView === 'signup') {
    return (
      <SignupPage
        onSignup={() => {
          setIsAuthenticated(true)
          setAuthView('workspace')
        }}
        onLoginClick={() => setAuthView('login')}
      />
    )
  }

  return (
    <LearningWorkspace
      isAuthenticated={isAuthenticated}
      onLoginClick={() => setAuthView('login')}
      onLogout={() => {
        setIsAuthenticated(false)
        setAuthView('workspace')
      }}
    />
  )
}

function LearningWorkspace({
  isAuthenticated,
  onLoginClick,
  onLogout,
}: {
  isAuthenticated: boolean
  onLoginClick: () => void
  onLogout: () => void
}) {
  const [selectedProblemId, setSelectedProblemId] = useState('func_sum_list')
  const [problem, setProblem] = useState<ProblemDetail | null>(null)
  const [problemLoading, setProblemLoading] = useState(true)
  const [problemError, setProblemError] = useState('')
  const [code, setCode] = useState('')
  const [result, setResult] = useState<JudgeResult | null>(null)
  const [judgeError, setJudgeError] = useState('')
  const [mode, setMode] = useState<RunMode>('run')
  const [isRunning, setIsRunning] = useState(false)
  const [runtimeStatus, setRuntimeStatus] = useState<RuntimeStatus>('loading')
  const [problemOpen, setProblemOpen] = useState(true)
  const [menuOpen, setMenuOpen] = useState(false)
  const [themeMode, setThemeMode] = useState<ThemeMode>('system')
  const [isDark, setIsDark] = useState(false)
  const [activity, setActivity] = useState<Activity>('list')
  const [authModalOpen, setAuthModalOpen] = useState(false)
  const [profileAvatar, setProfileAvatar] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('tutory:profile') ?? '{}').avatar as string || ''
    } catch {
      return ''
    }
  })
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null)
  const menuRef = useRef<HTMLDivElement | null>(null)

  // Coding Trace 수집. 세션은 **첫 편집이나 첫 실행 때** 지연 생성된다 --
  // 아래 문제 로드 useEffect 가 마운트 즉시 1회 돌기 때문에, 여기서 세션을 만들면
  // 학생이 아직 목록 화면에 있는데도 세션이 생긴다.
  const trace = useCodingTrace(problem?.problem_id ?? null)

  useEffect(() => {
    const controller = new AbortController()
    setProblemLoading(true)
    setProblemError('')
    getProblemDetail(selectedProblemId, controller.signal)
      .then((detail) => {
        setProblem(detail)
        const checkpoint = localStorage.getItem(`codetrace:checkpoint:${detail.problem_id}`)
        setCode(checkpoint ?? detail.code_template)
        setResult(null)
        setJudgeError('')
      })
      .catch((caught) => {
        if (!(caught instanceof DOMException && caught.name === 'AbortError')) {
          setProblemError(caught instanceof Error ? caught.message : String(caught))
        }
      })
      .finally(() => setProblemLoading(false))
    return () => controller.abort()
  }, [selectedProblemId])

  useEffect(() => {
    preparePython()
      .then(() => setRuntimeStatus('ready'))
      .catch(() => setRuntimeStatus('error'))
  }, [])

  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const applyTheme = () => {
      const resolvedTheme = themeMode === 'system' ? (media.matches ? 'dark' : 'light') : themeMode
      document.documentElement.dataset.theme = resolvedTheme
      setIsDark(resolvedTheme === 'dark')
    }
    applyTheme()
    media.addEventListener('change', applyTheme)
    return () => media.removeEventListener('change', applyTheme)
  }, [themeMode])

  useEffect(() => {
    if (!menuOpen) return
    const closeMenu = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false)
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMenuOpen(false)
    }
    document.addEventListener('mousedown', closeMenu)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('mousedown', closeMenu)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [menuOpen])

  const requireLogin = () => {
    if (isAuthenticated) return true
    setAuthModalOpen(true)
    return false
  }

  const openActivity = (nextActivity: Activity) => {
    if (nextActivity !== 'list' && !requireLogin()) return
    setActivity(nextActivity)
  }

  // 코드 편집의 유일한 관측점. 여기서만 학생의 타이핑을 볼 수 있다 --
  // useEffect([code]) 로는 안 된다. 문제 전환 시의 setCode 와 구분이 안 되기 때문.
  const handleCodeChange = (value: string | undefined) => {
    const next = value ?? ''
    setCode(next)
    trace.recordEdit(next)
  }

  const execute = async (nextMode: RunMode) => {
    if (!requireLogin() || isRunning || !problem) return
    setMode(nextMode)
    setIsRunning(true)
    setResult(null)
    setJudgeError('')
    try {
      const sessionId = await trace.ensureSession()
      // 대기 중인 편집을 결과보다 **먼저** 도착시킨다. 백엔드는 "직전 결과 이후의
      // 편집"을 code_version 으로 자르므로, 스냅샷이 늦게 오면 그 편집이 다음
      // 결과의 창으로 밀려 same_region_edit_count 가 한 칸씩 어긋난다.
      await trace.flush()
      trace.recordEvent(nextMode === 'run' ? 'RUN' : 'SUBMIT')
      // 이 한 번의 호출이 스냅샷 생성 → 채점 → TEST_RESULT 기록 → monitor 평가를 전부 한다.
      setResult(await runJudge(sessionId, code, nextMode))
    } catch (caught) {
      setJudgeError(caught instanceof Error ? caught.message : String(caught))
    } finally {
      setIsRunning(false)
    }
  }

  const resetCode = () => {
    if (!requireLogin() || !problem) return
    if (code === problem.code_template || window.confirm('작성한 코드를 기본 코드로 되돌릴까요?')) {
      setCode(problem.code_template)
      setResult(null)
      trace.recordEvent('RESET')
      trace.recordEdit(problem.code_template)
      editorRef.current?.focus()
    }
  }

  const saveCheckpoint = () => {
    if (!requireLogin() || !problem) return
    localStorage.setItem(`codetrace:checkpoint:${problem.problem_id}`, code)
  }

  const restoreCheckpoint = () => {
    if (!requireLogin() || !problem) return
    const checkpoint = localStorage.getItem(`codetrace:checkpoint:${problem.problem_id}`)
    if (checkpoint !== null) {
      setCode(checkpoint)
      setResult(null)
      // 학생 입장에서 "되돌리기"다. 백엔드의 UNDO 이벤트가 이 의미를 갖는다.
      trace.recordEvent('UNDO')
      trace.recordEdit(checkpoint)
    }
  }

  const selectProblem = (selected: ProblemSummary) => {
    if (!requireLogin()) return
    setSelectedProblemId(selected.problem_id)
    setActivity('problem')
  }

  const handleEditorMount: OnMount = (editor) => {
    editorRef.current = editor
    editor.focus()
  }

  const handleLogout = () => {
    setMenuOpen(false)
    setActivity('list')
    onLogout()
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="topbar-left">
          <button className="brand" type="button" aria-label="TUTORY 홈" onClick={() => setActivity('list')}>
            <img src="/TUTORY_logo.svg" alt="" />
          </button>
          {!isAuthenticated && (
            <button className="login-top-button" type="button" onClick={onLoginClick}>
              <LogIn size={15} />
              로그인하기
            </button>
          )}
        </div>
        <div className="topbar-actions">
          <div className={`runtime-pill ${runtimeStatus}`}>
            <span className="status-dot" />
            {runtimeStatus === 'loading' && 'Python 준비 중'}
            {runtimeStatus === 'ready' && 'Python 준비됨'}
            {runtimeStatus === 'error' && '실행 환경 오류'}
          </div>
          <button className="profile-trigger" type="button" aria-label="마이페이지 열기" onClick={() => openActivity('mypage')}>
            {isAuthenticated && profileAvatar ? <img src={profileAvatar} alt="내 프로필" /> : <UserRound size={18} />}
          </button>
          <div className="settings" ref={menuRef}>
            <button
              className={`menu-trigger ${menuOpen ? 'active' : ''}`}
              aria-label="화면 설정 열기"
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen((open) => !open)}
            >
              <MoreVertical size={20} />
            </button>
            {menuOpen && (
              <div className="settings-menu" role="menu">
                <div className="theme-options" aria-label="화면 테마">
                  <ThemeButton icon={<Monitor />} label="System" selected={themeMode === 'system'} onClick={() => setThemeMode('system')} />
                  <ThemeButton icon={<Sun />} label="Light" selected={themeMode === 'light'} onClick={() => setThemeMode('light')} />
                  <ThemeButton icon={<Moon />} label="Dark" selected={themeMode === 'dark'} onClick={() => setThemeMode('dark')} />
                </div>
                <div className="menu-divider" />
                <button className="menu-row" role="menuitem" onClick={() => { resetCode(); setMenuOpen(false) }}>
                  <span>코드 초기화</span><RotateCcw size={16} />
                </button>
                {isAuthenticated ? (
                  <button className="menu-row logout" role="menuitem" onClick={handleLogout}>
                    <span>로그아웃하기</span><LogOut size={16} />
                  </button>
                ) : (
                  <button className="menu-row" role="menuitem" onClick={() => { setMenuOpen(false); onLoginClick() }}>
                    <span>로그인하기</span><LogIn size={16} />
                  </button>
                )}
                <div className="menu-divider" />
                <div className="menu-runtime">
                  <span className={`status-dot ${runtimeStatus}`} />
                  <span>{runtimeStatus === 'ready' ? 'Python 3.12 준비됨' : runtimeStatus === 'loading' ? 'Python 준비 중' : '실행 환경 오류'}</span>
                </div>
              </div>
            )}
          </div>
        </div>
      </header>

      {activity === 'trace' ? (
        <TraceActivity onExit={() => setActivity('problem')} />
      ) : activity === 'mypage' ? (
        <MyPage onAvatarChange={setProfileAvatar} />
      ) : activity === 'list' ? (
        <ProblemList onSelect={selectProblem} />
      ) : (
        <main className="workspace">
          <section className={`problem-panel panel ${problemOpen ? '' : 'collapsed'}`}>
            <button className="mobile-panel-toggle" onClick={() => setProblemOpen(!problemOpen)}>
              <span><BookOpen size={17} /> 문제</span>
              <ChevronDown size={17} />
            </button>
            {problemLoading ? (
              <div className="problem-load-state"><LoaderCircle className="spin" /> 문제를 불러오는 중...</div>
            ) : problemError || !problem ? (
              <div className="problem-load-state error"><CircleAlert /> {problemError || '문제를 불러오지 못했습니다.'}</div>
            ) : (
              <div className="problem-content">
                <div className="problem-meta" aria-label="문제 정보">
                  <span>Python</span><i />
                  <span>{problem.check_type === 'function_call' ? '함수형' : '입출력형'}</span><i />
                  <span>{problem.problem_id}</span>
                </div>
                <h1>{problem.title}</h1>
                <ProblemDescription description={problem.description} />
                {problem.function_name && <div className="callout"><span>함수</span><code>{problem.function_name}(...)</code></div>}
                <h2>공개 테스트</h2>
                <div className="public-tests">
                  {problem.public_test_cases.map((test, index) => (
                    <div key={index}><span>테스트 {index + 1}</span><code>{formatPublicTest(test)}</code></div>
                  ))}
                </div>
              </div>
            )}
          </section>

          <div className="center-workbench">
            <section className="editor-panel panel">
              <div className="panel-header">
                <div className="file-tab"><Code2 size={16} /><span>solution.py</span></div>
                <div className="editor-tools">
                  <button className="icon-text-button" onClick={saveCheckpoint}>Checkpoint</button>
                  <button className="icon-text-button" onClick={restoreCheckpoint}>Restore</button>
                  <button className="icon-text-button" onClick={resetCode} title="기본 코드로 되돌리기"><RotateCcw size={15} /> 초기화</button>
                </div>
              </div>
              <div className="editor-wrap">
                <Editor
                  height="100%"
                  defaultLanguage="python"
                  value={code}
                  onChange={handleCodeChange}
                  onMount={handleEditorMount}
                  theme={isDark ? 'vs-dark' : 'vs-light'}
                  loading={<EditorLoading />}
                  options={{
                    fontFamily: "'JetBrains Mono', 'SFMono-Regular', Consolas, monospace",
                    fontSize: 14,
                    lineHeight: 23,
                    minimap: { enabled: false },
                    padding: { top: 20 },
                    scrollBeyondLastLine: false,
                    automaticLayout: true,
                    tabSize: 4,
                    insertSpaces: true,
                    wordWrap: 'on',
                    lineNumbersMinChars: 3,
                    renderLineHighlight: 'line',
                    overviewRulerBorder: false,
                    hideCursorInOverviewRuler: true,
                  }}
                />
              </div>
              <div className="editor-footer">
                <span>Python 3.12</span>
                <span>{code.split('\n').length} lines</span>
              </div>
            </section>

            <section className="result-panel panel">
              <div className="panel-header result-header">
                <div className="file-tab"><Terminal size={16} /><span>실행 결과</span></div>
                <span className={`api-badge ${isJudgeApiConfigured ? 'connected' : ''}`}>{isJudgeApiConfigured ? 'Judge API' : 'API 미연결'}</span>
              </div>

              <div className="result-content">
                {isRunning ? (
                  <div className="empty-state"><LoaderCircle className="spin" /><strong>코드를 실행하고 있어요</strong><p>잠시만 기다려 주세요.</p></div>
                ) : judgeError ? (
                  <JudgeErrorView message={judgeError} />
                ) : !result ? (
                  <div className="empty-state"><Play /><strong>준비가 되었어요</strong><p>코드를 작성하고 실행해 보세요.</p></div>
                ) : (
                  <JudgeResultView result={result} mode={mode} />
                )}
              </div>

              <div className="action-bar">
                <button className="trace-button" onClick={() => { trace.recordEvent('ACTIVITY_OPENED', { activity_type: 'TRACE' }); openActivity('trace') }} disabled={isRunning || runtimeStatus !== 'ready'}>
                  <Waypoints size={17} /> TRACE 학습
                </button>
                <button
                  className="run-button"
                  onClick={() => execute('run')}
                  disabled={isRunning || !problem}
                >
                  {isRunning && mode === 'run' ? <LoaderCircle className="spin" size={17} /> : <Play size={17} fill="currentColor" />}
                  실행
                </button>
                <button
                  className="submit-button"
                  onClick={() => execute('submit')}
                  disabled={isRunning || !problem}
                >
                  {isRunning && mode === 'submit' ? <LoaderCircle className="spin" size={17} /> : <Send size={17} />}
                  제출하기
                </button>
                <p>실행은 공개 테스트만 확인해요. TRACE에서 코드의 실행 흐름을 연습할 수 있어요.</p>
              </div>
            </section>
          </div>

          <AiTutorPanel problem={problem} result={result} judgeError={judgeError} />
        </main>
      )}

      {authModalOpen && (
        <div className="auth-modal-backdrop" role="presentation">
          <div className="auth-modal" role="dialog" aria-modal="true" aria-labelledby="auth-required-title">
            <div className="auth-modal-icon"><LogIn size={22} /></div>
            <div>
              <strong id="auth-required-title">로그인이 필요한 서비스입니다.</strong>
              <p>문제 풀이, 마이페이지, 저장, 실행 기능은 로그인 후 사용할 수 있어요.</p>
            </div>
            <div className="auth-modal-actions">
              <button className="modal-secondary-button" type="button" onClick={() => setAuthModalOpen(false)}>
                닫기
              </button>
              <button
                className="modal-primary-button"
                type="button"
                onClick={() => {
                  setAuthModalOpen(false)
                  onLoginClick()
                }}
              >
                로그인하기
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function ThemeButton({ icon, label, selected, onClick }: { icon: ReactNode; label: string; selected: boolean; onClick: () => void }) {
  return (
    <button className={`theme-button ${selected ? 'selected' : ''}`} onClick={onClick} aria-pressed={selected}>
      {icon}<span>{label}</span>
    </button>
  )
}

function EditorLoading() {
  return <div className="editor-loading"><LoaderCircle className="spin" /> 에디터를 여는 중...</div>
}

function ProblemDescription({ description }: { description: string }) {
  const sections = description.split(/^##\s+/m).filter(Boolean)
  return (
    <div className="problem-description">
      {sections.map((section, index) => {
        const [heading, ...body] = section.trim().split('\n')
        return (
          <section key={`${heading}-${index}`}>
            <h2>{heading}</h2>
            {body.join('\n').split('\n\n').filter(Boolean).map((paragraph, paragraphIndex) => (
              <p key={paragraphIndex}>{renderInlineCode(paragraph)}</p>
            ))}
          </section>
        )
      })}
    </div>
  )
}

function renderInlineCode(text: string) {
  return text.split(/(`[^`]+`)/g).map((part, index) => (
    part.startsWith('`') && part.endsWith('`') ? <code key={index}>{part.slice(1, -1)}</code> : part
  ))
}

function formatPublicTest(test: PublicTestCase) {
  if (test.stdin !== undefined) return `입력 ${JSON.stringify(test.stdin.trim())} → 출력 ${JSON.stringify(test.expected_stdout?.trim())}`
  return `입력 ${JSON.stringify(test.input)} → 결과 ${JSON.stringify(test.expected)}`
}

function JudgeErrorView({ message }: { message: string }) {
  return (
    <div className="error-view">
      <div className="error-title"><CircleAlert size={19} /><strong>채점 서버에 연결할 수 없어요</strong></div>
      <p>{message}</p>
    </div>
  )
}

const JUDGE_LABELS: Record<JudgeResult['status'], string> = {
  ACCEPTED: '모든 테스트를 통과했어요',
  WRONG_ANSWER: '일부 테스트가 틀렸어요',
  RUNTIME_ERROR: '실행 중 오류가 발생했어요',
  SYNTAX_ERROR: '문법을 다시 확인해 주세요',
  TIME_LIMIT: '시간 제한을 초과했어요',
}

function JudgeResultView({ result, mode }: { result: JudgeResult; mode: RunMode }) {
  const accepted = result.status === 'ACCEPTED'
  const progress = result.total ? (result.passed / result.total) * 100 : 0
  return (
    <div className="tests-view">
      <div className={`summary-card ${accepted ? 'success' : ''}`}>
        <div className="summary-icon">{accepted ? <Check /> : <CircleAlert />}</div>
        <div>
          <strong>{JUDGE_LABELS[result.status]}</strong>
          <p>{result.passed} / {result.total} 테스트 통과 · {mode === 'run' ? '공개 테스트' : '전체 테스트'}</p>
        </div>
      </div>
      <div className="progress-track"><span style={{ width: `${progress}%` }} /></div>
      {result.message && <div className="judge-message"><strong>{result.status}</strong><pre>{result.message}</pre></div>}
      {result.failed_categories?.length ? (
        <div className="failed-categories">
          <strong>다시 해볼 유형</strong>
          <div>{result.failed_categories.map((category) => <span key={category}>{category}</span>)}</div>
        </div>
      ) : null}
    </div>
  )
}

export default App
