/**
 * 문제 조회와 채점 결과 타입.
 *
 * 이 파일은 **세션이나 이벤트를 다루지 않는다.** 세션 생명주기 · trace 이벤트 ·
 * 채점 호출은 전부 traceClient.ts 가 소유한다 (그쪽이 배치 큐와 재시도를 갖고 있다).
 * 여기 남은 것은 "문제를 가져오는 일"과 "응답을 우리 타입으로 정규화하는 일"뿐이다.
 */
import localProblems from '../../judge/problems-index.json'
import localProblemDetails from '../../judge/problems-detail.json'
import { API_BASE_URL, apiRequest } from './api'
import { getProblemReward } from './problemRewards'

export type ProblemSummary = {
  problem_id: string
  title: string
  concept: string[]
  points: number
  acorn_reward: number
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
  awarded_acorns?: number
}

/**
 * 브라우저(Pyodide)에서 만든 채점 결과.
 *
 * 서버 judge 가 꺼져 있을 때(`JUDGE_BACKEND=none` → 503)의 폴백 경로에서 쓴다.
 * 서버가 채점할 때는 이 타입이 등장하지 않는다.
 */
export type LocalJudgePayload = {
  mode: 'run' | 'submit'
  status: JudgeStatus
  passed: number
  total: number
  runtime_ms?: number | null
  message?: string
  failed_categories?: string[]
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

/**
 * 학생이 직접 도움을 요청했을 때의 개입 판단.
 *
 * `HINT_REQUEST` 이벤트 기록은 **여기서 하지 않는다.** trace 큐를 소유한 쪽
 * (App 의 useCodingTrace)이 기록해야 순서가 보장되고 재시도도 얻는다.
 */
export async function decideTutorHelp(sessionId: string): Promise<AgentDecision | null> {
  if (!API_BASE_URL || !sessionId) return null
  return normalizeAgentDecision(await apiRequest<unknown>('/agent/decide', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, trigger: 'HELP_REQUESTED' }),
  }))
}

/**
 * 튜터의 답장. 학생이 보낸 말에 대한 응답이다.
 *
 * `AgentDecision` 과 다른 타입인 이유: 이건 "개입할까?"의 결과가 아니라 이미
 * 시작된 대화의 다음 턴이다. `action`/`state` 같은 개입 판단 필드가 없다.
 *
 * 학생 답변에 대한 이해도 평가(understanding, misconceptions 등)는 **여기로
 * 내려오지 않는다.** 서버가 trace 에만 남긴다 (교육자 화면이 읽을 곳) --
 * 학생에게 "이해도: none" 을 보여줄 이유가 없다.
 */
export type TutorReply = {
  message: string
  /** true 면 튜터가 학생의 답을 기다리는 중이다 (입력창을 열어 둔다). */
  expects_reply: boolean
  question: string
}

/**
 * 학생이 입력창에 쓴 말을 튜터에게 보낸다.
 *
 * **튜터가 무엇을 물었는지는 보내지 않는다.** 서버가 자기 개입 기록에서 직접
 * 찾는다 -- 클라이언트가 "내가 받은 질문은 이거였다"고 주장하는 값을 그대로
 * 믿으면 평가를 우회할 수 있다 (backend `last_tutor_question()` 참고).
 */
export async function sendTutorMessage(sessionId: string, answer: string): Promise<TutorReply | null> {
  if (!API_BASE_URL || !sessionId || !answer.trim()) return null
  return normalizeTutorReply(await apiRequest<unknown>('/agent/respond', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, answer }),
  }))
}

function normalizeTutorReply(payload: unknown): TutorReply | null {
  if (!isObject(payload) || typeof payload.message !== 'string' || !payload.message.trim()) return null
  return {
    message: payload.message,
    expects_reply: payload.expects_reply === true,
    question: typeof payload.question === 'string' ? payload.question : '',
  }
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
      points: typeof item.points === 'number' ? item.points : getProblemReward(item.problem_id).points,
      acorn_reward: typeof item.acorn_reward === 'number' ? item.acorn_reward : getProblemReward(item.problem_id).acorns,
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
    points: typeof payload.points === 'number' ? payload.points : getProblemReward(payload.problem_id).points,
    acorn_reward: typeof payload.acorn_reward === 'number' ? payload.acorn_reward : getProblemReward(payload.problem_id).acorns,
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

/** 백엔드는 `concepts`, 로컬 인덱스는 `concept` 를 쓴다. 둘 다 받는다. */
function normalizeConcepts(payload: Record<string, unknown>): string[] {
  const concepts = Array.isArray(payload.concepts) ? payload.concepts : payload.concept
  return Array.isArray(concepts) ? concepts.filter((value): value is string => typeof value === 'string') : []
}

/**
 * `POST /sessions/{id}/run|submit` 의 ResultIngestResponse 를 JudgeResult 로 좁힌다.
 *
 * 채점 결과는 `event.payload` 안에, 개입 판단은 최상위 `agent_decision` 에 있다.
 * **둘 다 필요하다** -- AiTutorPanel 이 agent_decision 으로 힌트를 만든다.
 */
export function normalizeJudgeResponse(payload: unknown): JudgeResult {
  const judgePayload = isObject(payload) && isObject(payload.event) && isObject(payload.event.payload)
    ? payload.event.payload
    : payload

  if (!isObject(judgePayload) || typeof judgePayload.status !== 'string') {
    throw new Error('채점 응답이 올바르지 않습니다.')
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
    awarded_acorns: isObject(payload) && typeof payload.awarded_acorns === 'number' ? payload.awarded_acorns : undefined,
  }
}

/** Agent 호출이 실패해도 채점 결과는 돌아온다. `null` 은 정상 케이스다. */
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

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === 'AbortError'
}

export function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}
