import { apiRequest, isApiConfigured } from './api'

export type StudentStatus = '순조로움' | '관찰 필요' | '도움 필요'

export type EducatorStudent = {
  id: string
  name: string
  email: string
  progress: number
  solved: number
  attempts: number
  lastActive: string
  status: StudentStatus
  weakConcept: string
}

export type EducatorAssignment = {
  title: string
  due: string
  completed: number
  total: number
  average: number
}

export type EducatorDashboardData = {
  courseTitle: string
  courseSubtitle: string
  totalStudents: number
  averageProgress: number
  completionRate: number
  needsHelp: number
  students: EducatorStudent[]
  attentionStudents: EducatorStudent[]
  assignments: EducatorAssignment[]
}

type DashboardResponse = Partial<EducatorDashboardData> & Record<string, unknown>

const DEFAULT_COURSE_ID = 'demo-course'

export async function getEducatorDashboard(courseId = DEFAULT_COURSE_ID): Promise<EducatorDashboardData | null> {
  if (!isApiConfigured) return null

  const [dashboard, students, attention] = await Promise.all([
    apiRequest<DashboardResponse>(`/educator/courses/${encodeURIComponent(courseId)}/dashboard`),
    apiRequest<unknown>(`/educator/courses/${encodeURIComponent(courseId)}/students`),
    apiRequest<unknown>(`/educator/courses/${encodeURIComponent(courseId)}/attention`).catch(() => null),
  ])

  const normalizedStudents = normalizeStudents(students)
  const attentionStudents = normalizeStudents(attention).length ? normalizeStudents(attention) : normalizedStudents.filter((student) => student.status !== '순조로움')

  return {
    courseTitle: typeof dashboard.courseTitle === 'string' ? dashboard.courseTitle : typeof dashboard.course_title === 'string' ? dashboard.course_title : 'Python 기초 01',
    courseSubtitle: typeof dashboard.courseSubtitle === 'string' ? dashboard.courseSubtitle : typeof dashboard.course_subtitle === 'string' ? dashboard.course_subtitle : '2026 여름학기 · 수강생 현황',
    totalStudents: numberOr(dashboard.totalStudents, dashboard.total_students, normalizedStudents.length),
    averageProgress: numberOr(dashboard.averageProgress, dashboard.average_progress, average(normalizedStudents.map((student) => student.progress))),
    completionRate: numberOr(dashboard.completionRate, dashboard.completion_rate, 0),
    needsHelp: numberOr(dashboard.needsHelp, dashboard.needs_help, attentionStudents.filter((student) => student.status === '도움 필요').length),
    students: normalizedStudents,
    attentionStudents,
    assignments: normalizeAssignments(dashboard.assignments),
  }
}

function normalizeStudents(payload: unknown): EducatorStudent[] {
  const items = Array.isArray(payload)
    ? payload
    : isObject(payload) && Array.isArray(payload.students)
      ? payload.students
      : []

  return items.flatMap((item) => {
    if (!isObject(item)) return []
    const id = stringOr(item.id, item.user_id, item.student_id)
    const name = stringOr(item.name, item.nickname, item.email) || '이름 없음'
    return [{
      id: id || name,
      name,
      email: stringOr(item.email) || '',
      progress: numberOr(item.progress, item.progress_rate, item.progressPercent, 0),
      solved: numberOr(item.solved, item.solved_count, item.completed_problems, 0),
      attempts: numberOr(item.attempts, item.attempt_count, item.total_attempts, 0),
      lastActive: stringOr(item.lastActive, item.last_active, item.last_active_at) || '-',
      status: normalizeStatus(stringOr(item.status, item.learning_status) || ''),
      weakConcept: stringOr(item.weakConcept, item.weak_concept, item.concept) || '기초 문법',
    }]
  })
}

function normalizeAssignments(payload: unknown): EducatorAssignment[] {
  if (!Array.isArray(payload)) return []
  return payload.flatMap((item) => {
    if (!isObject(item)) return []
    return [{
      title: stringOr(item.title, item.name) || '과제',
      due: stringOr(item.due, item.due_at, item.deadline) || '-',
      completed: numberOr(item.completed, item.completed_count, 0),
      total: numberOr(item.total, item.total_count, 0),
      average: numberOr(item.average, item.average_score, 0),
    }]
  })
}

function normalizeStatus(status: string): StudentStatus {
  if (status === '도움 필요' || status === 'HELP_NEEDED' || status === 'needs_help') return '도움 필요'
  if (status === '관찰 필요' || status === 'WATCH' || status === 'watch') return '관찰 필요'
  return '순조로움'
}

function numberOr(...values: unknown[]) {
  for (const value of values) {
    if (typeof value === 'number' && Number.isFinite(value)) return value
  }
  return 0
}

function stringOr(...values: unknown[]) {
  for (const value of values) {
    if (typeof value === 'string') return value
  }
  return ''
}

function average(values: number[]) {
  if (!values.length) return 0
  return Math.round(values.reduce((sum, value) => sum + value, 0) / values.length)
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}
