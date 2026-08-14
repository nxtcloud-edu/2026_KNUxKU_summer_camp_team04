export type LearningStatus = 'IN_PROGRESS' | 'COMPLETED'

export type LearningProgress = {
  problemId: string
  title: string
  code: string
  status: LearningStatus
  updatedAt: string
  completedAt?: string
}

export type RecentWrongHint = {
  problemId: string
  problemTitle: string
  status: string
  hint: string
  updatedAt: string
}

const STORAGE_KEY = 'tutory:learning-progress'
const RECENT_WRONG_HINT_KEY = 'tutory:recent-wrong-hint'

export function getLearningProgress(problemId: string) {
  return loadLearningProgress().find((item) => item.problemId === problemId) ?? null
}

export function getAllLearningProgress() {
  return loadLearningProgress().sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
}

export function saveInProgress(problemId: string, title: string, code: string) {
  const existing = getLearningProgress(problemId)
  return saveProgress({
    problemId,
    title,
    code,
    status: existing?.status === 'COMPLETED' ? 'COMPLETED' : 'IN_PROGRESS',
    updatedAt: new Date().toISOString(),
    completedAt: existing?.completedAt,
  })
}

export function saveCompleted(problemId: string, title: string, code: string) {
  const now = new Date().toISOString()
  return saveProgress({ problemId, title, code, status: 'COMPLETED', updatedAt: now, completedAt: now })
}

export function saveRecentWrongHint(problemId: string, problemTitle: string, status: string, hint: string) {
  const record: RecentWrongHint = {
    problemId,
    problemTitle,
    status,
    hint,
    updatedAt: new Date().toISOString(),
  }
  localStorage.setItem(RECENT_WRONG_HINT_KEY, JSON.stringify(record))
  return record
}

export function getRecentWrongHint() {
  try {
    const saved = JSON.parse(localStorage.getItem(RECENT_WRONG_HINT_KEY) ?? 'null') as unknown
    return isRecentWrongHint(saved) ? saved : null
  } catch {
    return null
  }
}

function saveProgress(progress: LearningProgress) {
  const records = loadLearningProgress().filter((item) => item.problemId !== progress.problemId)
  records.push(progress)
  localStorage.setItem(STORAGE_KEY, JSON.stringify(records))
  return progress
}

function loadLearningProgress(): LearningProgress[] {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]') as unknown
    if (!Array.isArray(saved)) return []
    return saved.filter(isLearningProgress)
  } catch {
    return []
  }
}

function isLearningProgress(value: unknown): value is LearningProgress {
  if (!value || typeof value !== 'object') return false
  const item = value as Partial<LearningProgress>
  return typeof item.problemId === 'string'
    && typeof item.title === 'string'
    && typeof item.code === 'string'
    && (item.status === 'IN_PROGRESS' || item.status === 'COMPLETED')
    && typeof item.updatedAt === 'string'
}

function isRecentWrongHint(value: unknown): value is RecentWrongHint {
  if (!value || typeof value !== 'object') return false
  const item = value as Partial<RecentWrongHint>
  return typeof item.problemId === 'string'
    && typeof item.problemTitle === 'string'
    && typeof item.status === 'string'
    && typeof item.hint === 'string'
    && typeof item.updatedAt === 'string'
}
