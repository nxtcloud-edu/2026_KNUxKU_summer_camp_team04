import localProblems from '../../judge/problems-index.json'
import localProblemDetails from '../../judge/problems-detail.json'
import { API_BASE_URL, apiRequest } from './api'

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
  hidden_test_case_count?: number
  hidden_test_categories?: string[]
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

export type LocalJudgePayload = {
  mode: 'run' | 'submit'
  status: JudgeStatus
  passed: number
  total: number
  runtime_ms?: number | null
  message?: string
  failed_categories?: string[]
}

export type ClientEventType = 'CODE_SNAPSHOT' | 'RUN' | 'SUBMIT' | 'UNDO' | 'RESET' | 'HINT_REQUEST' | 'ACTIVITY_OPENED' | 'ACTIVITY_RESPONSE' | 'SESSION_END'

export type EventIngestResponse = {
  accepted: unknown[]
  duplicate_client_event_ids: string[]
  current_code_version: number
  last_event_seq: number
  session_finished: boolean
}

export const isJudgeApiConfigured = Boolean(API_BASE_URL)

export async function getProblems(signal?: AbortSignal): Promise<ProblemListResult> {
  if (API_BASE_URL) {
    try {
      const problems = normalizeProblemList(await apiRequest<unknown>('/problems', { signal, auth: false }))
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
      return normalizeProblemDetail(await apiRequest<unknown>(`/problems/${encodeURIComponent(problemId)}`, { signal, auth: false }))
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
  return apiRequest<SessionInfo>('/sessions', {
    method: 'POST',
    body: JSON.stringify({ problem_id: problemId, user_id: 'demo-user' }),
    signal,
  })
}

export async function postSessionEvent(
  sessionId: string,
  type: ClientEventType,
  payload: Record<string, unknown> = {},
): Promise<EventIngestResponse | null> {
  if (!API_BASE_URL || !sessionId) return null
  return apiRequest<EventIngestResponse>(`/sessions/${encodeURIComponent(sessionId)}/events`, {
    method: 'POST',
    body: JSON.stringify({
      events: [{
        type,
        client_event_id: createClientEventId(),
        client_timestamp: new Date().toISOString(),
        payload,
      }],
    }),
  })
}

export async function postCodeSnapshot(sessionId: string, code: string): Promise<EventIngestResponse | null> {
  return postSessionEvent(sessionId, 'CODE_SNAPSHOT', { code })
}

export async function postJudgeResult(
  sessionId: string,
  result: LocalJudgePayload,
  codeVersion?: number | null,
): Promise<JudgeResult> {
  if (!API_BASE_URL || !sessionId) return result
  const payload = await apiRequest<unknown>(`/sessions/${encodeURIComponent(sessionId)}/results`, {
    method: 'POST',
    body: JSON.stringify({
      mode: result.mode,
      status: result.status,
      passed: result.passed,
      total: result.total,
      runtime_ms: result.runtime_ms ?? null,
      message: result.message ?? null,
      failed_categories: result.failed_categories ?? [],
      code_version: codeVersion ?? null,
      client_event_id: createClientEventId(),
      client_timestamp: new Date().toISOString(),
    }),
  })
  return normalizeJudgeResponse(payload)
}

export async function decideTutorHelp(sessionId: string): Promise<AgentDecision | null> {
  if (!API_BASE_URL || !sessionId) return null
  await postSessionEvent(sessionId, 'HINT_REQUEST')
  return normalizeAgentDecision(await apiRequest<unknown>('/agent/decide', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, trigger: 'HELP_REQUESTED' }),
  }))
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
    hidden_test_case_count: typeof payload.hidden_test_case_count === 'number' ? payload.hidden_test_case_count : undefined,
    hidden_test_categories: Array.isArray(payload.hidden_test_categories)
      ? payload.hidden_test_categories.filter((value): value is string => typeof value === 'string')
      : undefined,
  }
}

function normalizeConcepts(payload: Record<string, unknown>): string[] {
  const concepts = Array.isArray(payload.concepts) ? payload.concepts : payload.concept
  return Array.isArray(concepts) ? concepts.filter((value): value is string => typeof value === 'string') : []
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

function createClientEventId() {
  return crypto.randomUUID()
}

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === 'AbortError'
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}
