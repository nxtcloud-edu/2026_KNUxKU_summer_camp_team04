/**
 * "비슷한 문제 하나 더" 카드.
 *
 * 채점 결과 아래에 붙어, 방금 푼 문제와 같은 유형의 복습 문제를 만들어 준다.
 *
 * 왜 폴링인가: 생성이 LLM + judge 샌드박스라 실측 ~25초다. 버튼을 누른 채
 * 25초를 기다리게 하면 브라우저/프록시 타임아웃에도 걸리고 화면도 멈춘 것처럼
 * 보인다. 서버는 요청만 접수(PENDING)하고 백그라운드로 만들며, 여기서 몇 초마다
 * 상태를 확인한다.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { LoaderCircle, RefreshCw, Sparkles } from 'lucide-react'
import { listReviewProblems, requestReviewProblem, type ReviewProblem } from './reviewService'

type ReviewProblemCardProps = {
  /** 복습의 바탕이 될 문제 = 방금 푼 문제. 없으면 카드를 그리지 않는다. */
  sourceProblemId: string | null
  isAuthenticated: boolean
  onRequireLogin: () => void
  /** 생성된 문제로 이동. 부모가 문제 선택 상태를 갖고 있다. */
  onOpenProblem: (problemId: string) => void
}

/** 폴링 주기. 생성이 ~25초라 촘촘할 필요가 없다. */
const POLL_INTERVAL_MS = 3000
/**
 * 이만큼 지나도 PENDING 이면 폴링을 멈춘다.
 *
 * **이 상한이 없으면 탭을 열어둔 내내 3초마다 GET 이 나간다.** 서버가 죽거나
 * 백그라운드 태스크가 유실되면 PENDING 이 영원히 안 바뀌기 때문이다.
 * agent 쪽 생성 타임아웃(180초)보다 넉넉히 크게 잡는다 — 그 안에 서버가
 * FAILED 로 바꿔주는 게 정상 경로다.
 */
const POLL_TIMEOUT_MS = 240000

function ReviewProblemCard({
  sourceProblemId,
  isAuthenticated,
  onRequireLogin,
  onOpenProblem,
}: ReviewProblemCardProps) {
  const [request, setRequest] = useState<ReviewProblem | null>(null)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  // 폴링 대상 id. state 가 아니라 ref 인 이유: 폴링 타이머 안에서 최신 값을
  // 읽어야 하는데, state 를 클로저로 잡으면 첫 렌더의 값에 고정된다.
  const pendingIdRef = useRef<string | null>(null)

  const start = useCallback(async () => {
    if (!isAuthenticated) {
      onRequireLogin()
      return
    }
    if (!sourceProblemId) return

    setSubmitting(true)
    setError('')
    try {
      const created = await requestReviewProblem(sourceProblemId)
      if (created) {
        setRequest(created)
        pendingIdRef.current = created.status === 'PENDING' ? created.id : null
      }
    } catch (err) {
      console.warn('복습 문제 생성 요청 실패.', err)
      setError('복습 문제를 요청하지 못했어요. 잠시 후 다시 시도해 주세요.')
    } finally {
      setSubmitting(false)
    }
  }, [isAuthenticated, onRequireLogin, sourceProblemId])

  // PENDING 인 동안만 폴링한다.
  useEffect(() => {
    if (!request || request.status !== 'PENDING') return

    let cancelled = false
    const startedAt = Date.now()

    const poll = async () => {
      try {
        const items = await listReviewProblems()
        if (cancelled) return
        const mine = items.find((item) => item.id === pendingIdRef.current)
        if (mine && mine.status !== 'PENDING') {
          setRequest(mine)
          pendingIdRef.current = null
          return
        }
        if (Date.now() - startedAt > POLL_TIMEOUT_MS) {
          setError('생성이 너무 오래 걸려요. 잠시 후 다시 시도해 주세요.')
          setRequest(null)
          pendingIdRef.current = null
        }
      } catch (err) {
        // 폴링 실패는 다음 주기에 다시 시도한다. 사용자에게 알리지 않는다 --
        // 일시적인 네트워크 오류로 "실패했어요"를 띄우면 곧 성공할 요청까지 포기시킨다.
        console.warn('복습 문제 상태 확인 실패. 다음 주기에 재시도합니다.', err)
      }
    }

    const timer = window.setInterval(() => void poll(), POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [request])

  if (!sourceProblemId) return null

  const pending = request?.status === 'PENDING'

  return (
    <div className="review-card">
      <div className="review-card-head">
        <Sparkles size={15} />
        <div>
          <strong>비슷한 문제 하나 더 풀어볼까요?</strong>
          <span>방금 푼 문제와 같은 유형으로 새 문제를 만들어 드려요.</span>
        </div>
      </div>

      {request?.status === 'READY' && request.problem_id ? (
        <button
          className="review-card-primary"
          type="button"
          onClick={() => onOpenProblem(request.problem_id as string)}
        >
          새 문제 풀러 가기
        </button>
      ) : (
        <button
          className="review-card-primary"
          type="button"
          onClick={() => void start()}
          disabled={submitting || pending}
        >
          {submitting || pending ? (
            <>
              <LoaderCircle className="spin" size={14} />
              문제를 만들고 있어요…
            </>
          ) : (
            <>
              <RefreshCw size={14} />
              복습 문제 만들기
            </>
          )}
        </button>
      )}

      {pending && (
        <p className="review-card-note">
          문제를 만들고 정답까지 검증하는 중이라 20~30초쯤 걸려요. 그동안 다른 걸 하셔도 돼요.
        </p>
      )}
      {request?.status === 'FAILED' && (
        <p className="review-card-error">
          {request.error_message || '문제를 만들지 못했어요.'}
        </p>
      )}
      {error && <p className="review-card-error">{error}</p>}
    </div>
  )
}

export default ReviewProblemCard
