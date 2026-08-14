import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { MessageCircle, Send, Sparkles } from 'lucide-react'
import AcornIcon from './AcornIcon'
import squirrelTutor from './assets/squirrel-tutor-v2.png'
import { decideTutorHelp, sendTutorMessage, type AgentDecision, type JudgeResult, type ProblemDetail } from './problemService'
import type { AgentIntervention } from './useCodingTrace'

type AiTutorPanelProps = {
  problem: ProblemDetail | null
  result: JudgeResult | null
  judgeError: string
  sessionId?: string
  isAuthenticated: boolean
  onRequireLogin: () => void
  /**
   * 학생이 제출 없이 가만히 있어서(유휴) 하트비트가 백그라운드로 받아온 개입.
   *
   * `seq` 가 바뀔 때만 새 채팅 메시지로 추가한다 -- useCodingTrace 의 하트비트
   * 폴링이 몇 초마다 도므로, 같은 개입을 매 폴링마다 다시 쌓으면 안 된다.
   */
  intervention?: AgentIntervention | null
  /**
   * 서버가 개입 트리거를 감지했고 아직 힌트가 안 온 상태.
   *
   * 여기서 타이핑 인디케이터를 띄우는 게 체감 지연을 줄이는 핵심이다 -- 실제
   * 힌트까지는 LLM 왕복이 남아 있지만, 학생은 그때부터 "튜터가 반응했다" 를 본다.
   */
  tutorPending?: boolean
}

type ChatMessage = {
  id: number
  sender: 'tutor' | 'student'
  text: string
}

type TutorOffer = 'idle' | 'asking' | 'dismissed'

const PROFILE_KEY = 'tutory:profile'
const SOS_COST = 3

// `onHintRequest`는 사라졌다. 예전에는 SOS를 누를 때 프런트가 HINT_REQUEST를
// 따로 기록했는데, 그러면 하트비트가 그 이벤트를 보고 agent를 한 번 더 불러
// 같은 답이 두 번째 버블로 렌더됐다 (origin/main의 SOS 중복 응답 수정).
// 지금은 `/agent/decide`에 trigger를 실어 보내고 backend가 개입을 한 번만 기록한다
// (`backend/app/agent/router.py`).
function AiTutorPanel({ problem, result, judgeError, sessionId, isAuthenticated, onRequireLogin, intervention, tutorPending = false }: AiTutorPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [offerState, setOfferState] = useState<TutorOffer>('idle')
  const [acorns, setAcorns] = useState(() => loadAcorns())
  const [sosConfirmOpen, setSosConfirmOpen] = useState(false)
  const [sosError, setSosError] = useState('')
  const [sosIntroVisible, setSosIntroVisible] = useState(false)
  const [draft, setDraft] = useState('')
  const [isSending, setIsSending] = useState(false)
  // 튜터가 질문을 던져 답을 기다리는 중인지. 입력창 placeholder 만 바꾼다 --
  // 입력 자체는 항상 열어 둔다 (학생이 먼저 묻고 싶을 수도 있다).
  const [awaitingAnswer, setAwaitingAnswer] = useState(false)
  const chatThreadRef = useRef<HTMLDivElement | null>(null)
  const nextMessageIdRef = useRef(1)
  const sosInFlightRef = useRef(false)

  const shouldOfferHelp = Boolean(judgeError || (result && result.status !== 'ACCEPTED'))
  const tutorHint = useMemo(() => makeTutorHint(problem, result, judgeError), [problem, result, judgeError])

  useEffect(() => {
    if (shouldOfferHelp && offerState === 'idle') setOfferState('asking')
    if (!shouldOfferHelp && offerState !== 'idle') setOfferState('idle')
  }, [offerState, shouldOfferHelp])

  useEffect(() => {
    const chatThread = chatThreadRef.current
    if (!chatThread) return
    chatThread.scrollTo({ top: chatThread.scrollHeight, behavior: 'smooth' })
  }, [messages, offerState, sosIntroVisible, tutorPending])

  /**
   * 채팅 메시지 추가.
   *
   * id 를 state 가 아니라 ref 로 센다. state 로 세면 한 tick 안에서 두 번 부를 때
   * (예: 학생 메시지 + 튜터 답장을 연달아 얹을 때) 두 메시지가 같은 id 를 받아
   * React key 가 중복된다 -- 그러면 리렌더에서 메시지가 뒤섞이거나 사라진다.
   */
  const addMessage = (sender: ChatMessage['sender'], text: string) => {
    const id = nextMessageIdRef.current
    nextMessageIdRef.current += 1
    setMessages((current) => [...current, { id, sender, text }])
  }

  // 유휴 하트비트가 받아온 개입을 튜터가 먼저 말 거는 것처럼 채팅에 얹는다.
  // seq 로 dedupe 한다 -- intervention 객체 참조는 폴링마다 새로 만들어지지만
  // 같은 개입이면 seq 가 같으므로, ref 로 "이미 보여준 seq"를 기억해 중복을 막는다.
  // 같은 trace 개입을 즉시 응답과 이벤트 폴링 양쪽에서 받을 수 있다. 즉시
  // 화면에 그린 문구만 기억해, 같은 이벤트가 도착했을 때 한 번 건너뛴다.
  const immediateInterventionMessageRef = useRef<string | null>(null)
  const shownInterventionSeqRef = useRef<number | null>(null)
  useEffect(() => {
    if (!intervention) return
    if (shownInterventionSeqRef.current === intervention.seq) return
    // 학생용 문구가 없는 개입은 채팅에 얹지 않는다. 내부 근거(reason)로 폴백하면
    // 학생이 자기 분석 리포트를 읽게 된다 (studentFacingMessage 참고).
    const message = studentFacingMessage(intervention)
    if (!message) return
    shownInterventionSeqRef.current = intervention.seq
    if (immediateInterventionMessageRef.current === message) {
      immediateInterventionMessageRef.current = null
      return
    }
    addMessage('tutor', message)
    setAwaitingAnswer(intervention.activity?.expects_reply === true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervention])

  /**
   * 학생이 입력창에서 보낸 말을 튜터에게 전달하고 답장을 채팅에 얹는다.
   *
   * 낙관적으로 학생 메시지를 먼저 그린다 -- 응답에 LLM 두 번(답변 평가 → 응답
   * 생성)이 걸려 몇 초가 지나므로, 그동안 자기가 보낸 말이 안 보이면 전송이
   * 안 된 것처럼 느껴진다.
   */
  const submitDraft = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const answer = draft.trim()
    if (!answer || isSending) return

    if (!isAuthenticated) {
      onRequireLogin()
      return
    }

    setDraft('')
    setIsSending(true)
    addMessage('student', answer)
    setOfferState('dismissed')

    try {
      const reply = await sendTutorMessage(sessionId ?? '', answer)
      if (reply) {
        // /agent/respond가 이 답장을 trace에도 남긴다. 폴링으로 받은 같은 문구는
        // 여기서 이미 표시했으므로 한 번만 건너뛴다.
        immediateInterventionMessageRef.current = reply.message
        addMessage('tutor', reply.message)
        setAwaitingAnswer(reply.expects_reply)
      } else {
        // 서버/agent 미연결. 학생이 말을 걸었으니 침묵하지는 않는다.
        addMessage('tutor', '지금은 튜터가 답할 수 없어요. 잠시 뒤에 다시 물어봐 줄래요?')
        setAwaitingAnswer(false)
      }
    } catch (error) {
      console.warn('튜터 응답을 받지 못했습니다.', error)
      addMessage('tutor', '답을 가져오지 못했어요. 잠시 뒤에 다시 보내줄래요?')
    } finally {
      setIsSending(false)
    }
  }

  const acceptOffer = () => {
    addMessage('student', '네, 도움이 필요해요.')
    addMessage('tutor', tutorHint)
    setOfferState('dismissed')
  }

  const declineOffer = () => {
    addMessage('student', '아니요. 조금 더 해볼게요.')
    setOfferState('dismissed')
  }

  const requestSos = () => {
    if (!isAuthenticated) {
      onRequireLogin()
      return
    }
    setSosError('')
    setAcorns(loadAcorns())
    setSosConfirmOpen(true)
  }

  const confirmSos = async () => {
    if (sosInFlightRef.current) return

    const latestAcorns = loadAcorns()
    if (latestAcorns < SOS_COST) {
      setAcorns(latestAcorns)
      setSosError('도토리가 부족해요. 문제를 더 풀어서 도토리를 모아보세요.')
      return
    }

    sosInFlightRef.current = true
    try {
      const nextAcorns = latestAcorns - SOS_COST
      saveAcorns(nextAcorns)
      setAcorns(nextAcorns)
      setSosIntroVisible(true)
      addMessage('student', 'SOS! 다람쥐 튜터의 도움이 필요해요.')

      // /agent/decide가 실제 개입을 trace에 한 번 기록한다. 여기서 별도
      // HINT_REQUEST를 큐에 넣으면 heartbeat가 agent를 다시 호출해 중복된다.
      const help = await getTutorHelpMessage(sessionId, tutorHint)
      if (help.interventionMessage) immediateInterventionMessageRef.current = help.interventionMessage
      addMessage('tutor', help.message)
      setAwaitingAnswer(help.expectsReply)
      setOfferState('dismissed')
      setSosConfirmOpen(false)
      setSosError('')
    } finally {
      sosInFlightRef.current = false
    }
  }

  const renderTutorOffer = () => offerState === 'asking' ? (
    <div className="tutor-help-offer hero-squirrel">
      <img src={squirrelTutor} alt="" />
      <div>
        <p>도움이 필요한가요?</p>
        <div>
          <button type="button" onClick={isAuthenticated ? acceptOffer : onRequireLogin}>네</button>
          <button type="button" onClick={declineOffer}>아니요</button>
        </div>
      </div>
    </div>
  ) : null

  return (
    <aside className="tutor-panel panel">
      <div className="panel-header tutor-header">
        <div className="file-tab"><span className="tutor-status-dot" /><span>다람쥐 AI 튜터</span></div>
        <div className="tutor-header-actions">
          <span className="tutor-acorn-balance" aria-label={`보유 도토리 ${acorns}개`}><AcornIcon size={15} />{acorns}</span>
          <button className="sos-button" type="button" onClick={requestSos}>
            <Sparkles size={14} />
            SOS
          </button>
        </div>
      </div>

      <div className="tutor-chat">
        <div className="chat-thread" aria-live="polite" ref={chatThreadRef}>
          {!sosIntroVisible && !sosConfirmOpen && renderTutorOffer()}

          {sosIntroVisible && (
            <div className="tutor-help-offer sos-intro">
              <img src={squirrelTutor} alt="" />
              <div>
                <p>다람쥐 튜터가 도착했어요!</p>
                <span>도토리 {SOS_COST}개를 받고 지금 막 도와주러 왔어요.</span>
              </div>
            </div>
          )}

          {messages.length === 0 && offerState !== 'asking' && !sosIntroVisible && !tutorPending ? (
            <div className="tutor-empty-chat">
              <MessageCircle size={25} />
              <strong>다람쥐 튜터가 기다리고 있어요</strong>
              <p>막히면 SOS를 누르거나, 튜터가 먼저 말을 걸 때 도움을 받아보세요.</p>
            </div>
          ) : (
            messages.map((message) => (
              <div className={`chat-message ${message.sender}`} key={message.id}>
                {message.sender === 'tutor' && <img src={squirrelTutor} alt="" />}
                <p>{message.text}</p>
              </div>
            ))
          )}

          {/*
            서버가 트리거를 감지한 순간부터 실제 힌트가 도착할 때까지의 공백을 메운다.
            이 공백이 5~10초라 인디케이터가 없으면 학생은 시스템이 아무 반응도 안 한
            것으로 읽는다 -- 실제 지연은 그대로여도 체감은 여기서 갈린다.
          */}
          {tutorPending && (
            <div className="chat-message tutor tutor-typing">
              <img src={squirrelTutor} alt="" />
              <p>
                <span className="tutor-typing-dots" aria-hidden="true"><i /><i /><i /></span>
                코드를 살펴보고 있어요
              </p>
            </div>
          )}

          {sosIntroVisible && !sosConfirmOpen && renderTutorOffer()}
        </div>

        <form className="tutor-compose" onSubmit={submitDraft}>
          <input
            type="text"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder={awaitingAnswer ? '답을 적어보세요' : '무엇이든 물어보세요'}
            aria-label="튜터에게 보낼 메시지"
            disabled={isSending}
          />
          <button type="submit" disabled={isSending || !draft.trim()} aria-label="보내기">
            <Send size={14} />
          </button>
        </form>
      </div>

      {sosConfirmOpen && (
        <div className="tutor-modal-backdrop" role="presentation">
          <div className="tutor-modal-stack">
            <div className="tutor-modal" role="dialog" aria-modal="true" aria-labelledby="sos-dialog-title">
              <div className="tutor-modal-character">
                <img src={squirrelTutor} alt="" />
                <div className="tutor-modal-bubble">
                  <strong id="sos-dialog-title">다람쥐 튜터를 부를까요?</strong>
                  <p>도토리 {SOS_COST}개를 사용해 다람쥐 튜터의 도움을 받겠습니까?</p>
                </div>
              </div>
              <div className="tutor-modal-wallet">
                <AcornIcon size={16} />
                <span>현재 보유 도토리 {acorns}개</span>
              </div>
              {sosError && <p className="tutor-modal-error">{sosError}</p>}
              <div className="tutor-modal-actions">
                <button className="modal-secondary-button" type="button" onClick={() => setSosConfirmOpen(false)}>
                  아니요
                </button>
                <button className="modal-primary-button" type="button" onClick={confirmSos}>
                  예
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </aside>
  )
}

function makeTutorHint(problem: ProblemDetail | null, result: JudgeResult | null, judgeError: string) {
  if (result?.agent_decision && result.agent_decision.action !== 'WAIT') {
    const message = studentFacingMessage(result.agent_decision)
    if (message) return message
  }
  if (judgeError) return '채점 서버 연결부터 확인해볼까요? 지금은 코드보다 실행 환경 문제일 수 있어요.'
  if (result?.status === 'SYNTAX_ERROR') return '문법 오류가 있어 보여요. 괄호, 콜론(:), 들여쓰기를 먼저 차근차근 확인해봐요.'
  if (result?.status === 'RUNTIME_ERROR') return '실행 중 오류가 났어요. 변수 이름이 맞는지, 리스트 인덱스를 벗어나지 않았는지 확인해봐요.'
  if (result?.status === 'WRONG_ANSWER') return '답이 조금 달라요. 예시 입력을 손으로 따라가며 중간값이 어떻게 변하는지 적어보면 좋아요.'
  if (problem?.function_name) return `${problem.function_name} 함수가 어떤 값을 받아서 어떤 값을 반환해야 하는지 먼저 정리해볼까요?`
  return '문제를 작은 단계로 나눠볼게요. 입력, 처리, 출력 순서로 생각하면 훨씬 쉬워져요.'
}

async function getTutorHelpMessage(sessionId: string | undefined, fallback: string) {
  if (!sessionId) return { message: fallback, expectsReply: false, interventionMessage: null }
  try {
    const decision = await decideTutorHelp(sessionId)
    if (!decision || decision.action === 'WAIT') {
      return { message: fallback, expectsReply: false, interventionMessage: null }
    }
    const interventionMessage = studentFacingMessage(decision)
    return {
      message: interventionMessage ?? fallback,
      expectsReply: decision.activity?.expects_reply === true,
      interventionMessage,
    }
  } catch (error) {
    console.warn('Agent API unavailable. Using local tutor hint.', error)
    return { message: fallback, expectsReply: false, interventionMessage: null }
  }
}

/**
 * 학생에게 보여줄 문구를 고른다.
 *
 * **`activity.message` 가 유일한 학생용 텍스트다.** agent 파이프라인의 응답 생성
 * 에이전트(`tutor_message_agent`)가 2인칭으로 쓴 문장이고, 그것만 여기로 온다.
 *
 * `decision.reason` 은 학생용이 아니다 -- 교육자 타임라인용 내부 근거
 * (`StudentState.state_summary` + 지도 방식)다. 예전에는 이 함수가 `reason` 을
 * 그대로 렌더해서 학생이 자기 분석 리포트를 읽었다:
 *
 *   "loop 부분을 같이 보면 좋겠어요. 학생은 함수의 기본 구조를 이해하지 못한 채
 *    31분 넘게 완전히 막혀 있습니다. ... 힌트를 6회 요청했지만 ...
 *    (지도 방식: 단계별 구조 안내 + 구체적 예시 제공/explain)"
 *
 * concept 접두사("loop 부분을 같이 보면 좋겠어요.")도 붙이지 않는다. 응답 생성
 * 에이전트가 이미 완결된 인사/도입을 포함한 문장을 쓰므로, 접두사를 덧대면
 * 위처럼 두 문장이 어색하게 겹친다.
 *
 * `activity.message` 가 없으면(= agent 미연결이거나 구버전 응답) `reason` 으로
 * 폴백하지 않고 `null` 을 돌려준다. 내부 판단문을 보여주는 것보다 아무 말도
 * 하지 않는 게 낫다 -- 호출부가 로컬 폴백 힌트로 대체한다.
 */
function studentFacingMessage(decision: AgentDecision | AgentIntervention): string | null {
  const message = decision.activity?.message
  return typeof message === 'string' && message.trim() ? message : null
}

function loadAcorns() {
  const saved = localStorage.getItem(PROFILE_KEY)
  if (!saved) return 135
  try {
    const profile = JSON.parse(saved) as { acorns?: number }
    return typeof profile.acorns === 'number' ? profile.acorns : 135
  } catch {
    return 135
  }
}

function saveAcorns(acorns: number) {
  const saved = localStorage.getItem(PROFILE_KEY)
  let profile = {}
  try {
    profile = saved ? JSON.parse(saved) : {}
  } catch {
    profile = {}
  }
  localStorage.setItem(PROFILE_KEY, JSON.stringify({ ...profile, acorns }))
}

export default AiTutorPanel
