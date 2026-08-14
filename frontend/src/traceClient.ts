/**
 * Coding Trace + 채점 API 클라이언트.
 *
 * 학생이 코딩하는 **동안** 편집·실행 이력을 백엔드에 기록하고, 채점을 요청한다.
 * (같은 이름처럼 보이는 traceActivity.tsx 는 전혀 다른 것 -- 학생이 코드 실행을
 *  손으로 따라가는 학습 화면이다. 이 파일은 그것과 무관하다.)
 *
 * 계약 전문: plans/FRONTEND_INTEGRATION.md
 *
 * 모든 요청은 api.ts 의 apiRequest 를 통과한다. **세션·이벤트·채점 엔드포인트는
 * 전부 로그인을 요구하므로**(backend/app/auth/deps.py) Authorization 헤더를
 * 직접 fetch 로 우회하면 401 이 된다.
 */
import { API_BASE_URL, ApiError, apiKeepalive, apiRequest } from './api'
import { isObject, normalizeJudgeResponse, type JudgeResult } from './problemService'

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

export type SessionInfo = {
  session_id: string
  current_code: string
  current_code_version: number
}

function normalizeSession(payload: unknown): SessionInfo | null {
  if (!isObject(payload) || typeof payload.session_id !== 'string') return null
  return {
    session_id: payload.session_id,
    current_code: typeof payload.current_code === 'string' ? payload.current_code : '',
    current_code_version: typeof payload.current_code_version === 'number' ? payload.current_code_version : 0,
  }
}

export async function createSession(problemId: string, signal?: AbortSignal): Promise<SessionInfo> {
  const session = normalizeSession(await apiRequest<unknown>('/sessions', {
    method: 'POST',
    body: JSON.stringify({ problem_id: problemId }),
    signal,
  }))
  if (!session) throw new Error('세션 생성 응답이 올바르지 않습니다.')
  return session
}

/** 살아있는 세션이면 정보를, 없으면(404) null 을 준다. 새로고침 복구에 쓴다. */
export async function getSession(sessionId: string): Promise<SessionInfo | null> {
  try {
    return normalizeSession(await apiRequest<unknown>(`/sessions/${encodeURIComponent(sessionId)}`))
  } catch {
    return null
  }
}

/** 이벤트 배치 전송. 응답의 current_code_version 을 돌려준다. */
export async function postEvents(sessionId: string, events: TraceEvent[]): Promise<number | null> {
  if (events.length === 0) return null
  const payload = await apiRequest<unknown>(`/sessions/${encodeURIComponent(sessionId)}/events`, {
    method: 'POST',
    body: JSON.stringify({ events: events.slice(0, MAX_EVENTS_PER_BATCH) }),
  })
  if (isObject(payload) && typeof payload.current_code_version === 'number') {
    return payload.current_code_version
  }
  return null
}

/** 서버가 GET /events 로 돌려주는 이벤트 한 건. 클라이언트가 보내는 TraceEvent 와는 반대 방향. */
export type TraceEventRead = {
  seq: number
  type: string
  payload: Record<string, unknown>
}

export type EventListResult = {
  events: TraceEventRead[]
  last_event_seq: number
}

function normalizeEventListResult(payload: unknown): EventListResult {
  const events = isObject(payload) && Array.isArray(payload.events)
    ? payload.events.flatMap((item): TraceEventRead[] => {
      if (!isObject(item) || typeof item.seq !== 'number' || typeof item.type !== 'string') return []
      return [{ seq: item.seq, type: item.type, payload: isObject(item.payload) ? item.payload : {} }]
    })
    : []
  const last_event_seq = isObject(payload) && typeof payload.last_event_seq === 'number' ? payload.last_event_seq : 0
  return { events, last_event_seq }
}

/** `since_seq` 뒤에 쌓인 이벤트를 가져온다. 하트비트 폴링이 `AGENT_INTERVENTION` 을 찾는 용도. */
export async function getEvents(sessionId: string, sinceSeq: number): Promise<EventListResult> {
  return normalizeEventListResult(
    await apiRequest<unknown>(`/sessions/${encodeURIComponent(sessionId)}/events?since_seq=${sinceSeq}`),
  )
}

/**
 * 실시간 유휴 감지용 하트비트. 활동 여부와 무관하게 몇 초마다 호출한다.
 *
 * 응답에 agent 의 힌트는 안 실린다(트리거되면 서버가 백그라운드로 넘긴다) --
 * 힌트는 이후의 `getEvents` 폴링이 `AGENT_INTERVENTION` 이벤트로 받아온다.
 * 그래서 여기서는 성공 여부만 신경 쓰면 되고, 실패해도 학생 작업에 영향이 없다.
 */
export async function postHeartbeat(sessionId: string): Promise<void> {
  await apiRequest<unknown>(`/sessions/${encodeURIComponent(sessionId)}/heartbeat`, { method: 'POST' })
}

/**
 * 채점. `POST /sessions/{id}/run|submit` 하나가
 * **스냅샷 생성 → 채점 → TEST_RESULT 기록 → monitor 평가**를 전부 한다.
 *
 * `POST /sessions/{id}/results`(클라이언트가 채점 결과를 보고하던 경로)는 **제거됐다.**
 * 서버가 채점의 유일한 권위다.
 *
 * 서버 judge 가 꺼져 있으면(`JUDGE_BACKEND=none`) 503 JUDGE_UNAVAILABLE 이 온다.
 * 그 경우 호출부가 로컬 실행으로 폴백할 수 있도록 ApiError.status 를 그대로 흘린다.
 */
export async function runJudge(sessionId: string, code: string, mode: 'run' | 'submit'): Promise<JudgeResult> {
  return normalizeJudgeResponse(await apiRequest<unknown>(`/sessions/${encodeURIComponent(sessionId)}/${mode}`, {
    method: 'POST',
    body: JSON.stringify({ code }),
  }))
}

/** 서버 judge 가 미구성이라 채점을 수행할 수 없다는 뜻인가? */
export function isJudgeUnavailable(error: unknown): boolean {
  return error instanceof ApiError && error.status === 503
}

/** 토큰이 거부됐다(401). 세션이 죽었으므로 같은 요청을 다시 보낼 이유가 없다. */
export function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401
}

/**
 * 기다렸다 다시 보내면 나아질 수 있는 실패인가?
 *
 * 네트워크 오류(= ApiError 가 아닌 것)와 5xx 만 재시도한다. 4xx 는 요청이
 * 잘못됐거나 권한이 없다는 뜻이라 백오프를 태워도 같은 답이 온다 -- 특히
 * 401 에 4회 재시도를 돌리면 7초를 버리고 결과는 동일하다.
 */
export function isRetriable(error: unknown): boolean {
  if (!(error instanceof ApiError)) return true
  return error.status >= 500
}

/**
 * 페이지 이탈 시 마지막 이벤트를 흘려보낸다.
 * keepalive fetch 는 unload 중에도 전송되면서 Authorization 헤더를 실을 수 있다.
 */
export function beaconEvents(sessionId: string, events: TraceEvent[]): void {
  if (!API_BASE_URL || events.length === 0) return
  apiKeepalive(`/sessions/${encodeURIComponent(sessionId)}/events`, {
    events: events.slice(0, MAX_EVENTS_PER_BATCH),
  })
}
