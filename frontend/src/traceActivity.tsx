import { useEffect, useMemo, useState } from 'react'
import { ArrowLeft, Bot, Check, CircleAlert, LoaderCircle, RotateCcw, Sparkles } from 'lucide-react'
import { runTrace, type TraceStep } from './pythonRunner'

const TRACE_CODE = `total = 0

for i in range(1, 4):
    total += i
`

type AnswerMap = Record<string, string>

export function TraceActivity({ onExit }: { onExit: () => void }) {
  const [steps, setSteps] = useState<TraceStep[]>([])
  const [answers, setAnswers] = useState<AnswerMap>({})
  const [checked, setChecked] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    runTrace(TRACE_CODE)
      .then(setSteps)
      .catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)))
      .finally(() => setLoading(false))
  }, [])

  const fields = useMemo(
    () => steps.flatMap((step) => ['i', 'total'].map((variable) => ({
      key: `${step.iteration}-${variable}`,
      expected: String(step.locals[variable]),
    }))),
    [steps],
  )
  const correctCount = checked
    ? fields.filter((field) => answers[field.key]?.trim() === field.expected).length
    : 0
  const allFilled = fields.length > 0 && fields.every((field) => answers[field.key]?.trim())
  const allCorrect = checked && correctCount === fields.length

  const reset = () => {
    setAnswers({})
    setChecked(false)
  }

  return (
    <main className="trace-workspace">
      <header className="trace-header">
        <button className="back-button" onClick={onExit}><ArrowLeft size={17} /> 원래 문제로</button>
        <div className="trace-heading">
          <span>TRACE ACTIVITY · 01</span>
          <h1>반복문의 값을 직접 따라가 보세요</h1>
          <p>각 반복이 끝난 뒤 변수에 저장된 값을 예상해 입력하세요.</p>
        </div>
        <div className="trace-progress"><span>진행도</span><strong>{checked ? correctCount : 0} / {fields.length || 6}</strong></div>
      </header>

      <div className="trace-layout">
        <section className="trace-code-card">
          <div className="trace-card-title"><span className="trace-step-number">1</span><div><strong>코드 살펴보기</strong><small>코드는 위에서 아래로 실행돼요.</small></div></div>
          <pre className="trace-code"><code>{TRACE_CODE}</code></pre>
          <div className="trace-guide">
            <Sparkles size={16} />
            <p><strong>생각해 보기</strong><br /><code>total += i</code>는 현재 total에 i를 더한 뒤 다시 저장해요.</p>
          </div>
        </section>

        <section className="trace-table-card">
          <div className="trace-card-title"><span className="trace-step-number">2</span><div><strong>실행 과정 완성하기</strong><small>숫자를 입력하고 정답을 확인하세요.</small></div></div>

          {loading ? (
            <div className="trace-status"><LoaderCircle className="spin" /> 실행 과정을 만들고 있어요</div>
          ) : error ? (
            <div className="trace-status error"><CircleAlert /> {error}</div>
          ) : (
            <div className="trace-table-wrap">
              <table className="trace-table">
                <thead><tr><th>Iteration</th><th>i</th><th>total</th></tr></thead>
                <tbody>
                  {steps.map((step) => (
                    <tr key={step.iteration}>
                      <th>{step.iteration}</th>
                      {['i', 'total'].map((variable) => {
                        const key = `${step.iteration}-${variable}`
                        const expected = String(step.locals[variable])
                        const correct = answers[key]?.trim() === expected
                        return (
                          <td key={variable}>
                            <div className={`trace-input-wrap ${checked ? (correct ? 'correct' : 'incorrect') : ''}`}>
                              <input
                                inputMode="numeric"
                                aria-label={`${step.iteration}번째 반복의 ${variable}`}
                                value={answers[key] ?? ''}
                                onChange={(event) => { setAnswers((current) => ({ ...current, [key]: event.target.value })); setChecked(false) }}
                                placeholder="?"
                              />
                              {checked && correct && <Check size={15} />}
                            </div>
                            {checked && !correct && <small>정답: {expected}</small>}
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="trace-actions">
            <button className="trace-reset" onClick={reset} disabled={!Object.keys(answers).length}><RotateCcw size={15} /> 다시 풀기</button>
            <button className="trace-check" onClick={() => setChecked(true)} disabled={!allFilled || loading || Boolean(error)}>정답 확인</button>
          </div>

          {checked && (
            <div className={`agent-feedback ${allCorrect ? 'success' : ''}`} aria-live="polite">
              <span><Bot size={20} /></span>
              <div>
                <strong>{allCorrect ? '실행 흐름을 정확히 이해했어요!' : 'Agent 피드백'}</strong>
                <p>{allCorrect
                  ? 'i가 1씩 바뀔 때마다 total이 누적되는 과정을 모두 맞혔습니다.'
                  : `${fields.length}개 중 ${correctCount}개를 맞혔어요. 각 행의 total은 바로 이전 total에 현재 i를 더한 값인지 확인해 보세요.`}</p>
              </div>
            </div>
          )}
        </section>
      </div>
    </main>
  )
}
