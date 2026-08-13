/**
 * Coding Trace 수집 훅.
 *
 * 세션 생명주기 · 편집 debounce · 전송 큐 · 재시도 · 강제 flush 를 전부 소유한다.
 * 호출부(App.tsx)는 "무슨 일이 일어났는지"만 알려주면 된다.
 *
 * 설계 원칙: **trace 기록은 학생의 코딩을 절대 막지 않는다.**
 * recordEdit / recordEvent 는 예외를 던지지 않고 내부에서 삼킨다.
 * 채점 경로(ensureSession)만 에러를 표면화한다 -- 그건 학생이 알아야 하니까.
 *
 * 세션은 **첫 편집이나 첫 실행 때 지연 생성된다.** 문제를 열자마자 만들면
 * 학생이 구경만 하고 떠난 세션이 쌓인다.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { isJudgeApiConfigured } from './problemService'
import {
  MAX_EVENTS_PER_BATCH,
  beaconEvents,
  createSession,
  getSession,
  isRetriable,
  isUnauthorized,
  newEventId,
  postEvents,
  type SessionInfo,
  type TraceEvent,
  type TraceEventType,
} from './traceClient'

/** 타이핑이 멈춘 뒤 이만큼 지나면 스냅샷 하나로 묶는다. */
const EDIT_DEBOUNCE_MS = 800
/** 큐를 비우는 주기. 이 안에 5개가 차면 더 일찍 나간다. */
const FLUSH_INTERVAL_MS = 2000
const FLUSH_BATCH_SIZE = 5
/** flush 가 이보다 오래 걸리면 그냥 진행한다. 학생을 기다리게 하지 않는다. */
const FLUSH_TIMEOUT_MS = 2000
const RETRY_DELAYS_MS = [1000, 2000, 4000]

const sessionKey = (problemId: string) => `codetrace:session:${problemId}`

export type CodingTrace = {
  /** 편집 1건. 800ms debounce 후 CODE_SNAPSHOT 으로 큐에 들어간다. */
  recordEdit: (code: string) => void
  /** 즉시 큐 적재. 전송은 배치 타이밍에 일어난다. */
  recordEvent: (type: TraceEventType, payload?: Record<string, unknown>) => void
  /** 대기 중인 편집과 큐를 강제로 내보낸다. 타임아웃되면 조용히 포기한다. */
  flush: () => Promise<void>
  /** 세션을 확보한다. 멱등. 실패하면 throw -- 채점이 여기에 의존한다. */
  ensureSession: () => Promise<string>
  /**
   * 저장된 세션이 아직 살아 있으면 이어받는다. **없으면 만들지 않는다.**
   *
   * 새로고침 복구용이다. 서버가 들고 있던 `current_code` 를 돌려주므로
   * 호출부가 에디터를 되살릴 수 있다. 실패는 조용히 null 이다.
   */
  resume: () => Promise<SessionInfo | null>
  /**
   * 현재 세션. 아직 안 만들었으면 빈 문자열.
   *
   * 렌더에 쓸 수 있는 값이다(AiTutorPanel 이 이걸로 /agent/decide 를 부른다).
   * 콜백 안에서 최신 값을 읽어야 하면 getSessionId() 를 쓴다.
   */
  sessionId: string
  getSessionId: () => string
}

export type CodingTraceOptions = {
  /**
   * 로그인 상태. `false` 면 아무것도 기록하지 않는다.
   *
   * 세션 · 이벤트 · 채점 엔드포인트는 전부 로그인을 요구하므로, 비로그인 상태로
   * 큐를 돌리면 401 을 무한히 재시도하게 된다.
   */
  enabled?: boolean
}

export function useCodingTrace(problemId: string | null, options: CodingTraceOptions = {}): CodingTrace {
  const { enabled = true } = options
  const active = enabled && isJudgeApiConfigured

  const [sessionId, setSessionId] = useState('')
  const sessionIdRef = useRef('')
  const inFlightSessionRef = useRef<Promise<string> | null>(null)
  const queueRef = useRef<TraceEvent[]>([])
  const pendingCodeRef = useRef<string | null>(null)
  const debounceTimerRef = useRef<number | null>(null)
  const flushTimerRef = useRef<number | null>(null)
  const sendingRef = useRef(false)
  const problemIdRef = useRef<string | null>(problemId)
  const activeRef = useRef(active)

  const adoptSession = useCallback((id: string) => {
    sessionIdRef.current = id
    setSessionId(id)
  }, [])

  const discardQueue = useCallback(() => {
    inFlightSessionRef.current = null
    queueRef.current = []
    pendingCodeRef.current = null
    if (debounceTimerRef.current !== null) {
      window.clearTimeout(debounceTimerRef.current)
      debounceTimerRef.current = null
    }
  }, [])

  // 문제가 바뀌면 세션과 큐를 갈아끼운다. 이전 문제의 이벤트가 새 세션에
  // 섞이면 안 되므로 큐를 버린다(이미 보낸 것은 서버에 남아 있다).
  useEffect(() => {
    if (problemIdRef.current === problemId) return
    problemIdRef.current = problemId
    adoptSession('')
    discardQueue()
  }, [problemId, adoptSession, discardQueue])

  // 로그아웃하면 남은 큐를 버린다. 다음 사용자의 세션에 섞이면 안 된다.
  useEffect(() => {
    activeRef.current = active
    if (active) return
    adoptSession('')
    discardQueue()
  }, [active, adoptSession, discardQueue])

  const enqueue = useCallback((type: TraceEventType, payload?: Record<string, unknown>) => {
    queueRef.current.push({
      type,
      client_event_id: newEventId(),
      client_timestamp: new Date().toISOString(),
      ...(payload ? { payload } : {}),
    })
  }, [])

  /** 대기 중인 편집을 큐로 옮긴다. 같은 코드가 연속이면 서버가 dedupe 하므로 그대로 보낸다. */
  const drainPendingEdit = useCallback(() => {
    if (debounceTimerRef.current !== null) {
      window.clearTimeout(debounceTimerRef.current)
      debounceTimerRef.current = null
    }
    const code = pendingCodeRef.current
    if (code === null) return
    pendingCodeRef.current = null
    enqueue('CODE_SNAPSHOT', { code })
  }, [enqueue])

  const ensureSession = useCallback(async (): Promise<string> => {
    if (sessionIdRef.current) return sessionIdRef.current
    if (inFlightSessionRef.current) return inFlightSessionRef.current

    const pid = problemIdRef.current
    if (!pid) throw new Error('문제가 선택되지 않았습니다.')
    if (!isJudgeApiConfigured) throw new Error('서버가 설정되지 않았습니다. VITE_API_BASE_URL 을 확인해 주세요.')
    if (!activeRef.current) throw new Error('로그인이 필요합니다.')

    const task = (async () => {
      // 새로고침 복구: 같은 문제의 세션이 살아 있으면 이어 쓴다.
      const saved = window.localStorage.getItem(sessionKey(pid))
      if (saved) {
        const alive = await getSession(saved)
        if (alive) {
          adoptSession(alive.session_id)
          return alive.session_id
        }
        window.localStorage.removeItem(sessionKey(pid))
      }
      const created = await createSession(pid)
      window.localStorage.setItem(sessionKey(pid), created.session_id)
      adoptSession(created.session_id)
      return created.session_id
    })()

    inFlightSessionRef.current = task
    try {
      return await task
    } finally {
      inFlightSessionRef.current = null
    }
  }, [adoptSession])

  const resume = useCallback(async (): Promise<SessionInfo | null> => {
    if (!activeRef.current) return null
    // 이미 세션을 쥐고 있으면 복구할 것이 없다.
    if (sessionIdRef.current) return null

    const pid = problemIdRef.current
    if (!pid) return null

    const saved = window.localStorage.getItem(sessionKey(pid))
    if (!saved) return null

    const alive = await getSession(saved)
    if (!alive) {
      window.localStorage.removeItem(sessionKey(pid))
      return null
    }
    // 문제가 그새 바뀌었으면 버린다. 남의 문제 세션을 붙이면 안 된다.
    if (problemIdRef.current !== pid) return null

    adoptSession(alive.session_id)
    return alive
  }, [adoptSession])

  /** 큐를 한 번 비운다. 실패하면 되돌려놓고 백오프 재시도. */
  const send = useCallback(async (): Promise<void> => {
    if (sendingRef.current) return
    if (queueRef.current.length === 0) return
    if (!activeRef.current) return

    sendingRef.current = true
    const batch = queueRef.current.splice(0, MAX_EVENTS_PER_BATCH)
    try {
      const sid = await ensureSession()
      let lastError: unknown = null
      for (let attempt = 0; attempt <= RETRY_DELAYS_MS.length; attempt += 1) {
        try {
          await postEvents(sid, batch)
          lastError = null
          break
        } catch (error) {
          lastError = error
          // 4xx 는 기다려서 낫지 않는다. 즉시 빠져나온다.
          if (!isRetriable(error)) break
          const delay = RETRY_DELAYS_MS[attempt]
          if (delay === undefined) break
          await new Promise((resolve) => window.setTimeout(resolve, delay))
        }
      }
      if (lastError) {
        if (isUnauthorized(lastError)) {
          // 세션이 죽었다. 되돌려놓으면 다음 주기에 또 401 을 받는다.
          // api.ts 가 이미 만료를 통보했고, App 이 enabled 를 끄면서 큐를 버린다.
          console.warn('trace 전송 중 세션이 만료됐습니다. 남은 이벤트를 버립니다.', lastError)
        } else {
          // 되돌려놓는다. client_event_id 가 있으므로 나중에 중복 전송돼도 서버가 거른다.
          queueRef.current.unshift(...batch)
          console.warn('trace 전송 실패. 큐에 보관하고 다음 주기에 재시도합니다.', lastError)
        }
      }
    } catch (error) {
      if (isUnauthorized(error)) {
        console.warn('trace 세션이 만료됐습니다. 남은 이벤트를 버립니다.', error)
      } else {
        queueRef.current.unshift(...batch)
        console.warn('trace 세션을 확보하지 못했습니다.', error)
      }
    } finally {
      sendingRef.current = false
    }
  }, [ensureSession])

  // 주기적 flush. 큐가 비어 있으면 아무 일도 하지 않는다.
  useEffect(() => {
    flushTimerRef.current = window.setInterval(() => {
      if (queueRef.current.length > 0) void send()
    }, FLUSH_INTERVAL_MS)
    return () => {
      if (flushTimerRef.current !== null) window.clearInterval(flushTimerRef.current)
    }
  }, [send])

  const recordEdit = useCallback(
    (code: string) => {
      if (!activeRef.current) return
      pendingCodeRef.current = code
      if (debounceTimerRef.current !== null) window.clearTimeout(debounceTimerRef.current)
      debounceTimerRef.current = window.setTimeout(() => {
        drainPendingEdit()
        if (queueRef.current.length >= FLUSH_BATCH_SIZE) void send()
      }, EDIT_DEBOUNCE_MS)
    },
    [drainPendingEdit, send],
  )

  const recordEvent = useCallback(
    (type: TraceEventType, payload?: Record<string, unknown>) => {
      if (!activeRef.current) return
      enqueue(type, payload)
      if (queueRef.current.length >= FLUSH_BATCH_SIZE) void send()
    },
    [enqueue, send],
  )

  const flush = useCallback(async (): Promise<void> => {
    if (!activeRef.current) return
    drainPendingEdit()
    if (queueRef.current.length === 0) return
    // 백엔드가 느려도 Run 버튼이 멈추면 안 된다. 타임아웃되면 그냥 진행한다 --
    // 큐는 남아 있으므로 다음 주기에 전송된다.
    await Promise.race([
      send(),
      new Promise<void>((resolve) => window.setTimeout(resolve, FLUSH_TIMEOUT_MS)),
    ])
  }, [drainPendingEdit, send])

  // 탭을 떠날 때 마지막 한 번. keepalive fetch 는 unload 중에도 전송된다.
  useEffect(() => {
    const onHidden = () => {
      if (document.visibilityState !== 'hidden') return
      if (!activeRef.current) return
      const sid = sessionIdRef.current
      if (!sid) return
      drainPendingEdit()
      if (queueRef.current.length === 0) return
      beaconEvents(sid, queueRef.current)
      queueRef.current = []
    }
    document.addEventListener('visibilitychange', onHidden)
    return () => document.removeEventListener('visibilitychange', onHidden)
  }, [drainPendingEdit])

  const getSessionId = useCallback(() => sessionIdRef.current, [])

  return { recordEdit, recordEvent, flush, ensureSession, resume, sessionId, getSessionId }
}
