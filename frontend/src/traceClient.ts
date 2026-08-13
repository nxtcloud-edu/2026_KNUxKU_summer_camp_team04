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
