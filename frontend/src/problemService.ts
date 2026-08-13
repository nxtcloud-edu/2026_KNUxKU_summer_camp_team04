import localProblems from '../../judge/problems-index.json'

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

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '')

export async function getProblems(signal?: AbortSignal): Promise<ProblemListResult> {
  if (API_BASE_URL) {
    try {
      const response = await fetch(`${API_BASE_URL}/problems`, {
        signal,
        headers: { Accept: 'application/json' },
      })
      if (!response.ok) throw new Error(`Problem API returned ${response.status}`)
      const payload: unknown = await response.json()
      const problems = normalizeProblemList(payload)
      return { problems, source: 'api' }
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') throw error
      console.warn('Problem API unavailable. Using the local problem index.', error)
    }
  }

  return { problems: normalizeProblemList(localProblems), source: 'local' }
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
      concept: Array.isArray(item.concept) ? item.concept.filter((value): value is string => typeof value === 'string') : [],
    }]
  })
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}
