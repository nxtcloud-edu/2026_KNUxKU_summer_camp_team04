import { useEffect, useMemo, useState } from 'react'
import { MessageCircle, Send, Sparkles } from 'lucide-react'
import AcornIcon from './AcornIcon'
import squirrelTutor from './assets/squirrel-tutor.png'
import type { JudgeResult, ProblemDetail } from './problemService'

type AiTutorPanelProps = {
  problem: ProblemDetail | null
  result: JudgeResult | null
  judgeError: string
}

type ChatMessage = {
  id: number
  sender: 'tutor' | 'student'
  text: string
}

type TutorOffer = 'idle' | 'asking' | 'dismissed'

const PROFILE_KEY = 'tutory:profile'
const SOS_COST = 3

function AiTutorPanel({ problem, result, judgeError }: AiTutorPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [offerState, setOfferState] = useState<TutorOffer>('idle')
  const [nextMessageId, setNextMessageId] = useState(1)
  const [acorns, setAcorns] = useState(() => loadAcorns())
  const [sosConfirmOpen, setSosConfirmOpen] = useState(false)
  const [sosError, setSosError] = useState('')

  const shouldOfferHelp = Boolean(judgeError || (result && result.status !== 'ACCEPTED'))
  const tutorHint = useMemo(() => makeTutorHint(problem, result, judgeError), [problem, result, judgeError])

  useEffect(() => {
    if (shouldOfferHelp && offerState === 'idle') setOfferState('asking')
    if (!shouldOfferHelp && offerState !== 'idle') setOfferState('idle')
  }, [offerState, shouldOfferHelp])

  const addMessage = (sender: ChatMessage['sender'], text: string) => {
    setMessages((current) => [...current, { id: nextMessageId, sender, text }])
    setNextMessageId((current) => current + 1)
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
    setSosError('')
    setAcorns(loadAcorns())
    setSosConfirmOpen(true)
  }

  const confirmSos = () => {
    const latestAcorns = loadAcorns()
    if (latestAcorns < SOS_COST) {
      setAcorns(latestAcorns)
      setSosError('도토리가 부족해요. 문제를 더 풀어서 도토리를 모아보세요.')
      return
    }

    const nextAcorns = latestAcorns - SOS_COST
    saveAcorns(nextAcorns)
    setAcorns(nextAcorns)
    addMessage('student', 'SOS! 다람쥐 튜터의 도움이 필요해요.')
    addMessage('tutor', tutorHint)
    setOfferState('dismissed')
    setSosConfirmOpen(false)
    setSosError('')
  }

  return (
    <aside className="tutor-panel panel">
      <div className="panel-header tutor-header">
        <div className="file-tab"><span className="tutor-status-dot" /><span>다람쥐 AI 튜터</span></div>
        <button className="sos-button" type="button" onClick={requestSos}>
          <Sparkles size={14} />
          SOS
        </button>
      </div>

      <div className="tutor-chat">
        <div className="tutor-profile">
          <img src={squirrelTutor} alt="다람쥐 튜터" />
          <div>
            <strong>다람쥐 튜터</strong>
            <span><AcornIcon size={13} /> 보유 도토리 {acorns}개</span>
          </div>
        </div>

        {offerState === 'asking' && (
          <div className="tutor-help-offer">
            <img src={squirrelTutor} alt="" />
            <div>
              <p>도움이 필요한가요?</p>
              <div>
                <button type="button" onClick={acceptOffer}>네</button>
                <button type="button" onClick={declineOffer}>아니요</button>
              </div>
            </div>
          </div>
        )}

        <div className="chat-thread" aria-live="polite">
          {messages.length === 0 ? (
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
        </div>

        <div className="tutor-compose">
          <span>대화 입력은 준비 중이에요</span>
          <button type="button" disabled>
            <Send size={14} />
          </button>
        </div>
      </div>

      {sosConfirmOpen && (
        <div className="tutor-modal-backdrop" role="presentation">
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
      )}
    </aside>
  )
}

function makeTutorHint(problem: ProblemDetail | null, result: JudgeResult | null, judgeError: string) {
  if (judgeError) return '채점 서버 연결부터 확인해볼까요? 지금은 코드보다 실행 환경 문제일 수 있어요.'
  if (result?.status === 'SYNTAX_ERROR') return '문법 오류가 있어 보여요. 괄호, 콜론(:), 들여쓰기를 먼저 차근차근 확인해봐요.'
  if (result?.status === 'RUNTIME_ERROR') return '실행 중 오류가 났어요. 변수 이름이 맞는지, 리스트 인덱스를 벗어나지 않았는지 확인해봐요.'
  if (result?.status === 'WRONG_ANSWER') return '답이 조금 달라요. 예시 입력을 손으로 따라가며 중간값이 어떻게 변하는지 적어보면 좋아요.'
  if (problem?.function_name) return `${problem.function_name} 함수가 어떤 값을 받아서 어떤 값을 반환해야 하는지 먼저 정리해볼까요?`
  return '문제를 작은 단계로 나눠볼게요. 입력, 처리, 출력 순서로 생각하면 훨씬 쉬워져요.'
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
