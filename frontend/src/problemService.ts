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

export type JudgeStatus = 'ACCEPTED' | 'WRONG_ANSWER' | 'RUNTIME_ERROR' | 'SYNTAX_ERROR' | 'TIME_LIMIT' | 'INTERNAL_ERROR'

export type SessionInfo = {
  session_id: string
  user_id: string
  problem_id: string
  status: string
  started_at: string
  finished_at?: string | null
  last_code_version: number
  last_event_seq: number
  current_code: string
  current_code_version: number
}

export type AgentDecision = {
  state: string
  concept?: string | null
  action: string
  reason: string
  activity?: Record<string, unknown> | null
}

export type JudgeResult = {
  passed: number
  total: number
  status: JudgeStatus
  message?: string
  failed_categories?: string[]
  agent_decision?: AgentDecision | null
}

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '')
export const isJudgeApiConfigured = Boolean(API_BASE_URL)

export async function getProblems(signal?: AbortSignal): Promise<ProblemListResult> {
  if (API_BASE_URL) {
    try {
      const response = await fetch(`${API_BASE_URL}/problems`, {
        signal,
        headers: { Accept: 'application/json' },
      })
      if (!response.ok) throw new Error(`Problem API returned ${response.status}`)
      const problems = normalizeProblemList(await response.json())
      return { problems, source: 'api' }
    } catch (error) {
      if (isAbortError(error)) throw error
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
      if (isAbortError(error)) throw error
      console.warn('Problem detail API unavailable. Using local details.', error)
    }
  }

  const detail = (localProblemDetails as unknown[]).find((item) => isObject(item) && item.problem_id === problemId)
  if (!detail) throw new Error('문제를 찾을 수 없습니다.')
  return normalizeProblemDetail(detail)
}

export async function createSession(problemId: string, signal?: AbortSignal): Promise<SessionInfo | null> {
  if (!API_BASE_URL) return null
  const response = await fetch(`${API_BASE_URL}/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ problem_id: problemId, user_id: 'demo-user' }),
    signal,
  })
  const payload: unknown = await response.json().catch(() => null)
  if (!response.ok) throw new Error(getApiErrorMessage(payload, `Session API returned ${response.status}`))
  return normalizeSession(payload)
}

export async function judgeCode(
  studentCode: string,
  problemId: string,
  mode: 'run' | 'submit',
  sessionId?: string,
): Promise<JudgeResult> {
  if (!API_BASE_URL) throw new Error('Judge API가 연결되지 않았습니다. VITE_API_BASE_URL을 설정해 주세요.')
  const session = sessionId ?? (await createSession(problemId))?.session_id
  if (!session) throw new Error('학습 세션을 만들 수 없습니다.')

  const response = await fetch(`${API_BASE_URL}/sessions/${encodeURIComponent(session)}/${mode}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ code: studentCode }),
  })
  const payload: unknown = await response.json().catch(() => null)
  if (!response.ok) throw new Error(getApiErrorMessage(payload, `Judge API returned ${response.status}`))
  return normalizeJudgeResponse(payload)
}

export async function decideTutorHelp(sessionId: string): Promise<AgentDecision | null> {
  if (!API_BASE_URL || !sessionId) return null
  const response = await fetch(`${API_BASE_URL}/agent/decide`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ session_id: sessionId, trigger: 'HELP_REQUESTED' }),
  })
  const payload: unknown = await response.json().catch(() => null)
  if (!response.ok) throw new Error(getApiErrorMessage(payload, `Agent API returned ${response.status}`))
  return normalizeAgentDecision(payload)
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
      concept: normalizeConcepts(item),
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
    concept: normalizeConcepts(payload),
    check_type: payload.check_type,
    function_name: typeof payload.function_name === 'string' ? payload.function_name : undefined,
    code_template: payload.code_template,
    public_test_cases: Array.isArray(payload.public_test_cases) ? payload.public_test_cases as PublicTestCase[] : [],
    time_limit_sec: typeof payload.time_limit_sec === 'number' ? payload.time_limit_sec : undefined,
    memory_limit_mb: typeof payload.memory_limit_mb === 'number' ? payload.memory_limit_mb : undefined,
  }
}

function normalizeConcepts(payload: Record<string, unknown>): string[] {
  const concepts = Array.isArray(payload.concepts) ? payload.concepts : payload.concept
  return Array.isArray(concepts) ? concepts.filter((value): value is string => typeof value === 'string') : []
}

function normalizeSession(payload: unknown): SessionInfo {
  if (!isObject(payload) || typeof payload.session_id !== 'string' || typeof payload.problem_id !== 'string') {
    throw new Error('Invalid session response')
  }
  return {
    session_id: payload.session_id,
    user_id: typeof payload.user_id === 'string' ? payload.user_id : 'demo-user',
    problem_id: payload.problem_id,
    status: typeof payload.status === 'string' ? payload.status : 'active',
    started_at: typeof payload.started_at === 'string' ? payload.started_at : '',
    finished_at: typeof payload.finished_at === 'string' || payload.finished_at === null ? payload.finished_at : null,
    last_code_version: typeof payload.last_code_version === 'number' ? payload.last_code_version : 0,
    last_event_seq: typeof payload.last_event_seq === 'number' ? payload.last_event_seq : 0,
    current_code: typeof payload.current_code === 'string' ? payload.current_code : '',
    current_code_version: typeof payload.current_code_version === 'number' ? payload.current_code_version : 0,
  }
}

function normalizeJudgeResponse(payload: unknown): JudgeResult {
  const judgePayload = isObject(payload) && isObject(payload.event) && isObject(payload.event.payload)
    ? payload.event.payload
    : payload

  if (!isObject(judgePayload) || typeof judgePayload.status !== 'string') {
    throw new Error('Invalid judge response')
  }

  return {
    passed: typeof judgePayload.passed === 'number' ? judgePayload.passed : 0,
    total: typeof judgePayload.total === 'number' ? judgePayload.total : 0,
    status: normalizeJudgeStatus(judgePayload.status),
    message: typeof judgePayload.message === 'string' ? judgePayload.message : undefined,
    failed_categories: Array.isArray(judgePayload.failed_categories)
      ? judgePayload.failed_categories.filter((value): value is string => typeof value === 'string')
      : undefined,
    agent_decision: isObject(payload) ? normalizeAgentDecision(payload.agent_decision) : null,
  }
}

function normalizeAgentDecision(payload: unknown): AgentDecision | null {
  if (!isObject(payload) || typeof payload.action !== 'string' || typeof payload.reason !== 'string') return null
  return {
    state: typeof payload.state === 'string' ? payload.state : '',
    concept: typeof payload.concept === 'string' || payload.concept === null ? payload.concept : null,
    action: payload.action,
    reason: payload.reason,
    activity: isObject(payload.activity) ? payload.activity : null,
  }
}

function normalizeJudgeStatus(status: string): JudgeStatus {
  const knownStatuses: JudgeStatus[] = ['ACCEPTED', 'WRONG_ANSWER', 'RUNTIME_ERROR', 'SYNTAX_ERROR', 'TIME_LIMIT', 'INTERNAL_ERROR']
  return knownStatuses.includes(status as JudgeStatus) ? status as JudgeStatus : 'INTERNAL_ERROR'
}

function getApiErrorMessage(payload: unknown, fallback: string) {
  if (!isObject(payload)) return fallback
  if (typeof payload.detail === 'string') return payload.detail
  if (Array.isArray(payload.detail)) {
    const messages = payload.detail
      .map((item) => isObject(item) && typeof item.msg === 'string' ? item.msg : null)
      .filter(Boolean)
    return messages.join(', ') || fallback
  }
  return fallback
}

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === 'AbortError'
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}
