/**
 * Coding Trace API 클라이언트.
 *
 * 학생이 코딩하는 **동안** 편집·실행 이력을 백엔드에 기록한다.
 * (같은 이름의 traceActivity.tsx 는 전혀 다른 것 -- 학생이 코드 실행을
 *  손으로 따라가는 학습 화면이다. 이 파일은 그것과 무관하다.)
 *
 * 계약 전문: plans/FRONTEND_INTEGRATION.md
 */
import { API_BASE_URL, isObject, type JudgeResult, type JudgeStatus } from './problemService'

/** 클라이언트가 보낼 수 있는 이벤트. 서버 전용 타입(SESSION_START, TEST_RESULT 등)을 보내면 422. */
export type TraceEventType =
  | 'CODE_SNAPSHOT'
  | 'RUN'
  | 'SUBMIT'
  | 'UNDO'
  | 'RESET'
  | 'HINT_REQUEST'
  | 'ACTIVITY_OPENED'
  | 'ACTIVITY_RESPONSE'
  | 'SESSION_END'

export type TraceEvent = {
  type: TraceEventType
  /** 멱등성 키. 없으면 서버가 중복을 못 걸러 재시도가 그대로 기록된다. */
  client_event_id: string
  client_timestamp?: string
  payload?: Record<string, unknown>
}

/** 백엔드 배치 상한. 넘으면 422. */
export const MAX_EVENTS_PER_BATCH = 50

export function newEventId(): string {
  // crypto.randomUUID 는 secure context(localhost 포함)에서만 있다.
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `evt-${Date.now()}-${Math.random().toString(36).slice(2, 11)}`
}

function requireBase(): string {
  if (!API_BASE_URL) throw new Error('VITE_API_BASE_URL 이 설정되지 않았습니다.')
  return API_BASE_URL
}

/** FastAPI 에러 봉투에서 사람이 읽을 메시지를 뽑는다. 우리 에러는 객체, 검증 실패(422)는 배열. */
function errorMessage(payload: unknown, status: number): string {
  if (isObject(payload)) {
    const detail = payload.detail
    if (typeof detail === 'string') return detail
    if (isObject(detail) && typeof detail.message === 'string') return detail.message
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0]
      if (isObject(first) && typeof first.msg === 'string') return first.msg
    }
  }
  return `요청이 실패했습니다 (${status})`
}

async function request(path: string, init?: RequestInit): Promise<unknown> {
  const response = await fetch(`${requireBase()}${path}`, {
    ...init,
    headers: { Accept: 'application/json', ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...init?.headers },
  })
  const payload: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const error = new Error(errorMessage(payload, response.status)) as Error & { status?: number }
    error.status = response.status
    throw error
  }
  return payload
}

export type SessionInfo = {
  session_id: string
  current_code: string
  current_code_version: number
}

export async function createSession(problemId: string, userId = 'demo-user'): Promise<SessionInfo> {
  const payload = await request('/sessions', {
    method: 'POST',
    body: JSON.stringify({ problem_id: problemId, user_id: userId }),
  })
  if (!isObject(payload) || typeof payload.session_id !== 'string') {
    throw new Error('세션 생성 응답이 올바르지 않습니다.')
  }
  return {
    session_id: payload.session_id,
    current_code: typeof payload.current_code === 'string' ? payload.current_code : '',
    current_code_version: typeof payload.current_code_version === 'number' ? payload.current_code_version : 0,
  }
}

/** 살아있는 세션이면 정보를, 없으면(404) null 을 준다. 새로고침 복구에 쓴다. */
export async function getSession(sessionId: string): Promise<SessionInfo | null> {
  try {
    const payload = await request(`/sessions/${encodeURIComponent(sessionId)}`)
    if (!isObject(payload) || typeof payload.session_id !== 'string') return null
    return {
      session_id: payload.session_id,
      current_code: typeof payload.current_code === 'string' ? payload.current_code : '',
      current_code_version: typeof payload.current_code_version === 'number' ? payload.current_code_version : 0,
    }
  } catch {
    return null
  }
}

/** 이벤트 배치 전송. 응답의 current_code_version 을 돌려준다. */
export async function postEvents(sessionId: string, events: TraceEvent[]): Promise<number | null> {
  if (events.length === 0) return null
  const payload = await request(`/sessions/${encodeURIComponent(sessionId)}/events`, {
    method: 'POST',
    body: JSON.stringify({ events: events.slice(0, MAX_EVENTS_PER_BATCH) }),
  })
  if (isObject(payload) && typeof payload.current_code_version === 'number') {
    return payload.current_code_version
  }
  return null
}

const JUDGE_STATUSES: readonly string[] = [
  'ACCEPTED',
  'WRONG_ANSWER',
  'RUNTIME_ERROR',
  'SYNTAX_ERROR',
  'TIME_LIMIT',
  'INTERNAL_ERROR',
]

/**
 * 채점. POST /sessions/{id}/run|submit 하나가
 * **스냅샷 생성 → 채점 → TEST_RESULT 기록 → monitor 평가**를 전부 한다.
 *
 * 응답(ResultIngestResponse)에서 기존 JudgeResult 모양만 뽑아 돌려준다.
 * 그래야 App.tsx 의 JudgeResultView 를 한 줄도 안 고친다.
 * process_state / agent_decision 은 이번 범위(기록만)에서는 쓰지 않는다.
 */
export async function runJudge(sessionId: string, code: string, mode: 'run' | 'submit'): Promise<JudgeResult> {
  const payload = await request(`/sessions/${encodeURIComponent(sessionId)}/${mode}`, {
    method: 'POST',
    body: JSON.stringify({ code }),
  })
  if (!isObject(payload) || !isObject(payload.event) || !isObject(payload.event.payload)) {
    throw new Error('채점 응답이 올바르지 않습니다.')
  }
  const result = payload.event.payload
  if (typeof result.passed !== 'number' || typeof result.total !== 'number' || typeof result.status !== 'string') {
    throw new Error('채점 응답이 올바르지 않습니다.')
  }
  if (!JUDGE_STATUSES.includes(result.status)) {
    throw new Error(`알 수 없는 채점 상태입니다: ${result.status}`)
  }
  return {
    passed: result.passed,
    total: result.total,
    status: result.status as JudgeStatus,
    message: typeof result.message === 'string' ? result.message : undefined,
    failed_categories: Array.isArray(result.failed_categories)
      ? result.failed_categories.filter((c): c is string => typeof c === 'string')
      : undefined,
  }
}

/**
 * 페이지 이탈 시 마지막 이벤트를 흘려보낸다.
 * sendBeacon 은 응답을 못 받지만 unload 중에도 전송이 보장된다.
 */
export function beaconEvents(sessionId: string, events: TraceEvent[]): void {
  if (!API_BASE_URL || events.length === 0) return
  if (typeof navigator === 'undefined' || typeof navigator.sendBeacon !== 'function') return
  const body = new Blob([JSON.stringify({ events: events.slice(0, MAX_EVENTS_PER_BATCH) })], {
    type: 'application/json',
  })
  navigator.sendBeacon(`${API_BASE_URL}/sessions/${encodeURIComponent(sessionId)}/events`, body)
}
