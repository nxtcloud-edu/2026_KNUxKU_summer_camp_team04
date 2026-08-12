import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import Editor, { type OnMount } from '@monaco-editor/react'
import {
  BookOpen,
  Check,
  ChevronDown,
  CircleAlert,
  Clock3,
  Code2,
  LoaderCircle,
  LockKeyhole,
  Monitor,
  Moon,
  MoreVertical,
  Play,
  RotateCcw,
  Send,
  Sun,
  Terminal,
  X,
} from 'lucide-react'
import { STARTER_CODE, TESTS } from './problem'
import { preparePython, runPython, type ExecutionResult } from './pythonRunner'

type RunMode = 'run' | 'submit'
type RuntimeStatus = 'loading' | 'ready' | 'error'
type ThemeMode = 'system' | 'light' | 'dark'

function App() {
  const [code, setCode] = useState(STARTER_CODE)
  const [result, setResult] = useState<ExecutionResult | null>(null)
  const [mode, setMode] = useState<RunMode>('run')
  const [isRunning, setIsRunning] = useState(false)
  const [runtimeStatus, setRuntimeStatus] = useState<RuntimeStatus>('loading')
  const [problemOpen, setProblemOpen] = useState(true)
  const [menuOpen, setMenuOpen] = useState(false)
  const [themeMode, setThemeMode] = useState<ThemeMode>('system')
  const [isDark, setIsDark] = useState(false)
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null)
  const menuRef = useRef<HTMLDivElement | null>(null)

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

  const visibleTests = useMemo(
    () => TESTS.filter((test) => mode === 'submit' || !test.hidden),
    [mode],
  )

  const execute = async (nextMode: RunMode) => {
    if (isRunning || runtimeStatus === 'error') return
    setMode(nextMode)
    setIsRunning(true)
    setResult(null)
    const selectedTests = TESTS.filter((test) => nextMode === 'submit' || !test.hidden)
    try {
      setResult(await runPython(code, selectedTests))
    } finally {
      setIsRunning(false)
    }
  }

  const resetCode = () => {
    if (code === STARTER_CODE || window.confirm('작성한 코드를 기본 코드로 되돌릴까요?')) {
      setCode(STARTER_CODE)
      setResult(null)
      editorRef.current?.focus()
    }
  }

  const handleEditorMount: OnMount = (editor) => {
    editorRef.current = editor
    editor.focus()
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#" aria-label="TUTORY 홈">
          <img src="/TUTORY_logo.svg" alt="" />
        </a>
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
                <div className="menu-runtime">
                  <span className={`status-dot ${runtimeStatus}`} />
                  <span>{runtimeStatus === 'ready' ? 'Python 3.12 준비됨' : runtimeStatus === 'loading' ? 'Python 준비 중' : '실행 환경 오류'}</span>
                </div>
              </div>
            )}
          </div>
        </div>
      </header>

      <main className="workspace">
        <section className={`problem-panel panel ${problemOpen ? '' : 'collapsed'}`}>
          <button className="mobile-panel-toggle" onClick={() => setProblemOpen(!problemOpen)}>
            <span><BookOpen size={17} /> 문제</span>
            <ChevronDown size={17} />
          </button>
          <div className="problem-content">
            <div className="problem-meta" aria-label="문제 정보">
              <span>Python</span><i />
              <span>쉬움</span><i />
              <span>문제 01</span>
            </div>
            <h1>짝수의 합 구하기</h1>
            <p className="problem-lead">
              숫자 리스트에서 <strong>짝수만 골라 모두 더한 값</strong>을 반환하세요.
            </p>

            <div className="callout">
              <span>함수</span>
              <code>sum_even(numbers)</code>
            </div>

            <h2>입력</h2>
            <p>정수로 이루어진 리스트 <code>numbers</code>가 주어집니다.</p>
            <h2>출력</h2>
            <p>리스트에 들어 있는 짝수의 합을 반환합니다.</p>

            <h2>예시</h2>
            <div className="example-box">
              <div><span>입력</span><code>[1, 2, 3, 4]</code></div>
              <div><span>결과</span><code>6</code></div>
            </div>

            <div className="gentle-tip">
              <span>작은 힌트</span>
              <p><code>숫자 % 2 == 0</code>이면 짝수예요.</p>
            </div>
          </div>
        </section>

        <section className="editor-panel panel">
          <div className="panel-header">
            <div className="file-tab"><Code2 size={16} /><span>solution.py</span></div>
            <button className="icon-text-button" onClick={resetCode} title="기본 코드로 되돌리기">
              <RotateCcw size={15} /> 초기화
            </button>
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
            {result && !result.error && (
              <span className="duration"><Clock3 size={13} /> {(result.duration / 1000).toFixed(2)}s</span>
            )}
          </div>

          <div className="result-content">
            {isRunning ? (
              <div className="empty-state"><LoaderCircle className="spin" /><strong>코드를 실행하고 있어요</strong><p>잠시만 기다려 주세요.</p></div>
            ) : !result ? (
              <div className="empty-state"><Play /><strong>준비가 되었어요</strong><p>코드를 작성하고 실행해 보세요.</p></div>
            ) : result.error ? (
              <ErrorView result={result} />
            ) : (
              <TestView result={result} mode={mode} visibleTests={visibleTests} />
            )}

            {result?.stdout && (
              <div className="stdout-block">
                <span>출력</span>
                <pre>{result.stdout}</pre>
              </div>
            )}
          </div>

          <div className="action-bar">
            <button
              className="run-button"
              onClick={() => execute('run')}
              disabled={isRunning || runtimeStatus !== 'ready'}
            >
              {isRunning && mode === 'run' ? <LoaderCircle className="spin" size={17} /> : <Play size={17} fill="currentColor" />}
              실행
            </button>
            <button
              className="submit-button"
              onClick={() => execute('submit')}
              disabled={isRunning || runtimeStatus !== 'ready'}
            >
              {isRunning && mode === 'submit' ? <LoaderCircle className="spin" size={17} /> : <Send size={17} />}
              제출하기
            </button>
            <p>실행은 공개 테스트만 확인해요.</p>
          </div>
        </section>
      </main>
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

function ErrorView({ result }: { result: ExecutionResult }) {
  const syntax = result.error?.type === 'syntax'
  return (
    <div className="error-view">
      <div className="error-title"><CircleAlert size={19} /><strong>{syntax ? '문법을 다시 확인해 주세요' : '실행 중 오류가 발생했어요'}</strong></div>
      <p>{syntax ? '괄호나 들여쓰기처럼 작은 부분부터 천천히 살펴보세요.' : '오류 메시지의 마지막 줄을 먼저 확인해 보세요.'}</p>
      <pre>{result.error?.message}</pre>
    </div>
  )
}

function TestView({ result, mode, visibleTests }: { result: ExecutionResult; mode: RunMode; visibleTests: typeof TESTS }) {
  const passed = result.tests.filter((test) => test.passed).length
  const allPassed = passed === result.tests.length
  return (
    <div className="tests-view">
      <div className={`summary-card ${allPassed ? 'success' : ''}`}>
        <div className="summary-icon">{allPassed ? <Check /> : <Code2 />}</div>
        <div>
          <strong>{allPassed ? '모두 통과했어요!' : '거의 다 왔어요'}</strong>
          <p>{passed} / {result.tests.length} 테스트 통과</p>
        </div>
      </div>
      <div className="progress-track"><span style={{ width: `${(passed / result.tests.length) * 100}%` }} /></div>
      <div className="test-heading"><strong>테스트</strong><span>{mode === 'submit' ? '전체 결과' : '공개 테스트'}</span></div>
      <div className="test-list">
        {visibleTests.map((test, index) => {
          const testResult = result.tests[index]
          const passedTest = testResult?.passed
          return (
            <div className={`test-row ${passedTest ? 'passed' : 'failed'}`} key={test.id}>
              <span className="test-status">{passedTest ? <Check size={15} /> : <X size={15} />}</span>
              <div>
                <strong>{test.hidden ? `비공개 테스트 ${test.id - 3}` : `테스트 ${test.id}`}</strong>
                {!test.hidden && <small>입력: [{test.input.join(', ')}]</small>}
                {test.hidden && <small><LockKeyhole size={11} /> 테스트 내용은 비공개예요</small>}
                {!passedTest && testResult?.error && <small className="test-error">{testResult.error}</small>}
                {!passedTest && !testResult?.error && !test.hidden && <small className="test-error">기대값 {test.expected} · 결과 {String(testResult?.actual)}</small>}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default App
