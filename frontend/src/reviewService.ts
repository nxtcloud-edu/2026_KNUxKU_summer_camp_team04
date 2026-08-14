/**
 * 복습 문제 생성 API 클라이언트.
 *
 * 생성은 LLM + judge 샌드박스라 실측 ~25초다. 그래서 POST 는 요청만 접수하고
 * 즉시 PENDING 을 돌려주며, 실제 결과는 GET 을 폴링해서 받는다 (실시간 개입이
 * `AGENT_INTERVENTION` 을 폴링하는 것과 같은 패턴).
 */
import { apiRequest, isApiConfigured } from './api'

export type ReviewProblemStatus = 'PENDING' | 'READY' | 'FAILED'

export type ReviewProblem = {
  id: string
  status: ReviewProblemStatus
  source_problem_id: string
  /** READY 일 때만 채워진다. 이 값으로 평범한 문제처럼 세션을 시작할 수 있다. */
  problem_id: string | null
  error_message: string | null
}

function normalizeStatus(value: unknown): ReviewProblemStatus {
  return value === 'READY' || value === 'FAILED' ? value : 'PENDING'
}

function normalizeItem(payload: unknown): ReviewProblem | null {
  if (!payload || typeof payload !== 'object') return null
  const p = payload as Record<string, unknown>
  if (typeof p.id !== 'string') return null
  return {
    id: p.id,
    status: normalizeStatus(p.status),
    source_problem_id: typeof p.source_problem_id === 'string' ? p.source_problem_id : '',
    problem_id: typeof p.problem_id === 'string' ? p.problem_id : null,
    error_message: typeof p.error_message === 'string' ? p.error_message : null,
  }
}

/**
 * 복습 문제 생성을 요청한다. 응답은 보통 PENDING 이다 (아직 만들어지지 않았다).
 *
 * 이미 진행 중인 요청이 있으면 서버가 **새로 만들지 않고 그걸 돌려준다** —
 * 버튼을 연타해도 LLM 호출이 쌓이지 않는다.
 */
export async function requestReviewProblem(sourceProblemId: string): Promise<ReviewProblem | null> {
  if (!isApiConfigured) return null
  return normalizeItem(
    await apiRequest<unknown>('/users/me/review-problems', {
      method: 'POST',
      body: JSON.stringify({ source_problem_id: sourceProblemId }),
    }),
  )
}

/** 내 복습 문제 요청 목록 (최신순). 폴링이 이걸 부른다. */
export async function listReviewProblems(): Promise<ReviewProblem[]> {
  if (!isApiConfigured) return []
  const payload = await apiRequest<unknown>('/users/me/review-problems')
  if (!payload || typeof payload !== 'object') return []
  const items = (payload as Record<string, unknown>).items
  if (!Array.isArray(items)) return []
  return items.flatMap((item) => {
    const normalized = normalizeItem(item)
    return normalized ? [normalized] : []
  })
}
