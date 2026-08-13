import localProblems from '../../judge/problems-index.json'
import localProblemDetails from '../../judge/problems-detail.json'

export type ProblemSummary = {
  problem_id: string
  title: string
  concept: string[]
}

export type ProblemListSource = 'api' | 'local'

export type ProblemListResult = {
  problems: ProblemSummary[]
  source: ProblemListSource
}

export type PublicTestCase = {
  input?: unknown[]
  expected?: unknown
  stdin?: string
  expected_stdout?: string
  category?: string
}

export type ProblemDetail = ProblemSummary & {
  description: string
  check_type: 'function_call' | 'stdout_match'
  function_name?: string
  code_template: string
  public_test_cases: PublicTestCase[]
  time_limit_sec?: number
  memory_limit_mb?: number
}

export type JudgeStatus = 'ACCEPTED' | 'WRONG_ANSWER' | 'RUNTIME_ERROR' | 'SYNTAX_ERROR' | 'TIME_LIMIT'

export type JudgeResult = {
  passed: number
  total: number
  status: JudgeStatus
  message?: string
  failed_categories?: string[]
}

// traceClient.ts 가 같은 값을 써야 하므로 export 한다.
// 백엔드 하나가 문제 조회 · 채점 · trace 수집을 전부 담당한다.
export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '')
export const isJudgeApiConfigured = Boolean(API_BASE_URL)

export async function getProblems(signal?: AbortSignal): Promise<ProblemListResult> {
  if (API_BASE_URL) {
    try {
      const response = await fetch(`${API_BASE_URL}/problems`, {
        signal,
        headers: { Accept: 'application/json' },
      })
      if (!response.ok) throw new Error(`Problem API returned ${response.status}`)
      const payload: unknown = await response.json()
      const problems = normalizeProblemList(payload)
      return { problems, source: 'api' }
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') throw error
      console.warn('Problem API unavailable. Using the local problem index.', error)
    }
  }

  return { problems: normalizeProblemList(localProblems), source: 'local' }
}

export async function getProblemDetail(problemId: string, signal?: AbortSignal): Promise<ProblemDetail> {
  if (API_BASE_URL) {
    try {
      const response = await fetch(`${API_BASE_URL}/problems/${encodeURIComponent(problemId)}`, {
        signal,
        headers: { Accept: 'application/json' },
      })
      if (!response.ok) throw new Error(`Problem detail API returned ${response.status}`)
      return normalizeProblemDetail(await response.json())
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') throw error
      console.warn('Problem detail API unavailable. Using local details.', error)
    }
  }

  const detail = (localProblemDetails as unknown[]).find((item) => isObject(item) && item.problem_id === problemId)
  if (!detail) throw new Error('문제를 찾을 수 없습니다.')
  return normalizeProblemDetail(detail)
}

export async function judgeCode(studentCode: string, problemId: string, mode: 'run' | 'submit'): Promise<JudgeResult> {
  if (!API_BASE_URL) throw new Error('Judge API가 연결되지 않았습니다. VITE_API_BASE_URL을 설정해 주세요.')
  const response = await fetch(`${API_BASE_URL}/judge`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ student_code: studentCode, problem_id: problemId, mode }),
  })
  const payload: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const message = isObject(payload) && typeof payload.detail === 'string' ? payload.detail : `Judge API returned ${response.status}`
    throw new Error(message)
  }
  if (!isObject(payload) || typeof payload.passed !== 'number' || typeof payload.total !== 'number' || typeof payload.status !== 'string') {
    throw new Error('Invalid judge response')
  }
  return payload as JudgeResult
}

function normalizeProblemList(payload: unknown): ProblemSummary[] {
  const items = Array.isArray(payload)
    ? payload
    : isObject(payload) && Array.isArray(payload.problems)
      ? payload.problems
      : null

  if (!items) throw new Error('Invalid problem list response')

  return items.flatMap((item) => {
    if (!isObject(item) || typeof item.problem_id !== 'string' || typeof item.title !== 'string') return []
    return [{
      problem_id: item.problem_id,
      title: item.title,
      concept: Array.isArray(item.concept) ? item.concept.filter((value): value is string => typeof value === 'string') : [],
    }]
  })
}

function normalizeProblemDetail(payload: unknown): ProblemDetail {
  if (!isObject(payload) || typeof payload.problem_id !== 'string' || typeof payload.title !== 'string'
    || typeof payload.description !== 'string' || typeof payload.code_template !== 'string'
    || (payload.check_type !== 'function_call' && payload.check_type !== 'stdout_match')) {
    throw new Error('Invalid problem detail response')
  }
  return {
    problem_id: payload.problem_id,
    title: payload.title,
    description: payload.description,
    concept: Array.isArray(payload.concept) ? payload.concept.filter((value): value is string => typeof value === 'string') : [],
    check_type: payload.check_type,
    function_name: typeof payload.function_name === 'string' ? payload.function_name : undefined,
    code_template: payload.code_template,
    public_test_cases: Array.isArray(payload.public_test_cases) ? payload.public_test_cases as PublicTestCase[] : [],
    time_limit_sec: typeof payload.time_limit_sec === 'number' ? payload.time_limit_sec : undefined,
    memory_limit_mb: typeof payload.memory_limit_mb === 'number' ? payload.memory_limit_mb : undefined,
  }
}

export function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}
