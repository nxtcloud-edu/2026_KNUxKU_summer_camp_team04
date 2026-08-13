import { useEffect, useRef, useState, type ReactNode } from 'react'
import Editor, { type OnMount } from '@monaco-editor/react'
import {
  BookOpen,
  Archive,
  Check,
  ChevronDown,
  CircleAlert,
  Code2,
  LoaderCircle,
  LogOut,
  Monitor,
  Moon,
  MoreVertical,
  Play,
  RotateCcw,
  Send,
  Sun,
  Terminal,
  Waypoints,
} from 'lucide-react'
import LoginPage from './LoginPage'
import MyPage from './MyPage'
import { preparePython } from './pythonRunner'
import { TraceActivity } from './traceActivity'
import { ProblemList } from './problemList'
import { getProblemDetail, isJudgeApiConfigured, judgeCode, type JudgeResult, type ProblemDetail, type ProblemSummary, type PublicTestCase } from './problemService'
import SignupPage from './SignupPage'

type RunMode = 'run' | 'submit'
type RuntimeStatus = 'loading' | 'ready' | 'error'
type ThemeMode = 'system' | 'light' | 'dark'
type AuthView = 'login' | 'signup' | 'workspace'

function App() {
  const [authView, setAuthView] = useState<AuthView>('login')

  if (authView === 'login') {
    return (
      <LoginPage
        onLogin={() => setAuthView('workspace')}
        onSignupClick={() => setAuthView('signup')}
      />
    )
  }

  if (authView === 'signup') {
    return (
      <SignupPage
        onSignup={() => setAuthView('workspace')}
        onLoginClick={() => setAuthView('login')}
      />
    )
  }

  return <LearningWorkspace onLogout={() => setAuthView('login')} />
}

function LearningWorkspace({ onLogout }: { onLogout: () => void }) {
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
  const [activity, setActivity] = useState<'problem' | 'trace' | 'list' | 'mypage'>('list')
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null)
  const menuRef = useRef<HTMLDivElement | null>(null)

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
        if (!(caught instanceof DOMException && caught.name === 'AbortError')) setProblemError(caught instanceof Error ? caught.message : String(caught))
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

  const execute = async (nextMode: RunMode) => {
    if (isRunning || !problem) return
    setMode(nextMode)
    setIsRunning(true)
    setResult(null)
    setJudgeError('')
    try {
      setResult(await judgeCode(code, problem.problem_id, nextMode))
    } catch (caught) {
      setJudgeError(caught instanceof Error ? caught.message : String(caught))
    } finally {
      setIsRunning(false)
    }
  }

  const resetCode = () => {
    if (!problem) return
    if (code === problem.code_template || window.confirm('작성한 코드를 기본 코드로 되돌릴까요?')) {
      setCode(problem.code_template)
      setResult(null)
      editorRef.current?.focus()
    }
  }

  const saveCheckpoint = () => {
    if (!problem) return
    localStorage.setItem(`codetrace:checkpoint:${problem.problem_id}`, code)
  }

  const restoreCheckpoint = () => {
    if (!problem) return
    const checkpoint = localStorage.getItem(`codetrace:checkpoint:${problem.problem_id}`)
    if (checkpoint !== null) { setCode(checkpoint); setResult(null) }
  }

  const selectProblem = (selected: ProblemSummary) => {
    setSelectedProblemId(selected.problem_id)
    setActivity('problem')
  }

  const handleEditorMount: OnMount = (editor) => {
    editorRef.current = editor
    editor.focus()
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="topbar-left">
          <button className="brand" type="button" aria-label="TUTORY 홈" onClick={() => setActivity('list')}>
            <img src="/TUTORY_logo.svg" alt="" />
          </button>
        </div>
        <div className="topbar-actions">
          <div className={`runtime-pill ${runtimeStatus}`}>
            <span className="status-dot" />
            {runtimeStatus === 'loading' && 'Python 준비 중'}
            {runtimeStatus === 'ready' && 'Python 준비됨'}
            {runtimeStatus === 'error' && '실행 환경 오류'}
          </div>
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
                <div className="menu-divider" />
                <button className="menu-row" role="menuitem" onClick={() => { setMenuOpen(false); setActivity('mypage') }}>
                  <span>도토리창고</span><Archive size={16} />
                </button>
                <button className="menu-row logout" role="menuitem" onClick={() => { setMenuOpen(false); onLogout() }}>
                  <span>로그아웃</span><LogOut size={16} />
                </button>
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

      {activity === 'trace' ? <TraceActivity onExit={() => setActivity('problem')} />
        : activity === 'mypage' ? <MyPage />
        : activity === 'list' ? <ProblemList onSelect={selectProblem} /> : (

      <main className="workspace">
        <section className={`problem-panel panel ${problemOpen ? '' : 'collapsed'}`}>
          <button className="mobile-panel-toggle" onClick={() => setProblemOpen(!problemOpen)}>
            <span><BookOpen size={17} /> 문제</span>
            <ChevronDown size={17} />
          </button>
          {problemLoading ? <div className="problem-load-state"><LoaderCircle className="spin" /> 문제를 불러오는 중...</div>
          : problemError || !problem ? <div className="problem-load-state error"><CircleAlert /> {problemError || '문제를 불러오지 못했습니다.'}</div>
          : <div className="problem-content">
            <div className="problem-meta" aria-label="문제 정보">
              <span>Python</span><i />
              <span>{problem.check_type === 'function_call' ? '함수형' : '입출력형'}</span><i />
              <span>{problem.problem_id}</span>
            </div>
            <h1>{problem.title}</h1>
            <ProblemDescription description={problem.description} />
            {problem.function_name && <div className="callout"><span>함수</span><code>{problem.function_name}(...)</code></div>}
            <h2>공개 테스트</h2>
            <div className="public-tests">{problem.public_test_cases.map((test, index) => <div key={index}><span>테스트 {index + 1}</span><code>{formatPublicTest(test)}</code></div>)}</div>
          </div>}
        </section>

        <div className="center-workbench">
        <section className="editor-panel panel">
          <div className="panel-header">
            <div className="file-tab"><Code2 size={16} /><span>solution.py</span></div>
            <div className="editor-tools"><button className="icon-text-button" onClick={saveCheckpoint}>Checkpoint</button><button className="icon-text-button" onClick={restoreCheckpoint}>Restore</button><button className="icon-text-button" onClick={resetCode} title="기본 코드로 되돌리기"><RotateCcw size={15} /> 초기화</button></div>
          </div>
          <div className="editor-wrap">
            <Editor
              height="100%"
              defaultLanguage="python"
              value={code}
              onChange={(value) => setCode(value ?? '')}
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
            ) : judgeError ? <JudgeErrorView message={judgeError} /> : !result ? (
              <div className="empty-state"><Play /><strong>준비가 되었어요</strong><p>코드를 작성하고 실행해 보세요.</p></div>
            ) : <JudgeResultView result={result} mode={mode} />}
          </div>

          <div className="action-bar">
            <button className="trace-button" onClick={() => setActivity('trace')} disabled={isRunning || runtimeStatus !== 'ready'}>
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
            <p>실행은 공개 테스트만 확인해요. · TRACE에서 코드의 실행 흐름을 연습할 수 있어요.</p>
          </div>
        </section>
        </div>

        <aside className="tutor-panel panel">
          <div className="panel-header tutor-header">
            <div className="file-tab"><span className="tutor-status-dot" /><span>다람쥐 튜터</span></div>
            <span className="coming-soon-badge">준비 중</span>
          </div>
          <div className="tutor-empty-state">
            <div className="squirrel-avatar" aria-hidden="true">🐿️</div>
            <strong>다람쥐 튜터가 곧 찾아와요</strong>
            <p>코드를 함께 살펴보고, 막힌 부분에는 작은 힌트를 건네줄 예정이에요.</p>
            <div className="tutor-preview-message">
              <span>다람쥐 튜터</span>
              <p>문제를 풀다가 도움이 필요하면 언제든 불러주세요!</p>
            </div>
          </div>
        </aside>
      </main>
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
        return <section key={`${heading}-${index}`}><h2>{heading}</h2>{body.join('\n').split('\n\n').filter(Boolean).map((paragraph, paragraphIndex) => <p key={paragraphIndex}>{renderInlineCode(paragraph)}</p>)}</section>
      })}
    </div>
  )
}

function renderInlineCode(text: string) {
  return text.split(/(`[^`]+`)/g).map((part, index) => part.startsWith('`') && part.endsWith('`') ? <code key={index}>{part.slice(1, -1)}</code> : part)
}

function formatPublicTest(test: PublicTestCase) {
  if (test.stdin !== undefined) return `입력 ${JSON.stringify(test.stdin.trim())} → 출력 ${JSON.stringify(test.expected_stdout?.trim())}`
  return `입력 ${JSON.stringify(test.input)} → 결과 ${JSON.stringify(test.expected)}`
}

function JudgeErrorView({ message }: { message: string }) {
  return <div className="error-view"><div className="error-title"><CircleAlert size={19} /><strong>채점 서버에 연결할 수 없어요</strong></div><p>{message}</p></div>
}

const JUDGE_LABELS: Record<JudgeResult['status'], string> = {
  ACCEPTED: '모든 테스트를 통과했어요!',
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
      {result.failed_categories?.length ? <div className="failed-categories"><strong>다시 살펴볼 유형</strong><div>{result.failed_categories.map((category) => <span key={category}>{category}</span>)}</div></div> : null}
    </div>
  )
}

export default App
