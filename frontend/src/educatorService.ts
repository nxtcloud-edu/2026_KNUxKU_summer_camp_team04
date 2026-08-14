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
  id: string
  courseId: string
  courseTitle: string
  title: string
  description: string
  due: string
  completed: number
  total: number
  average: number
  problems: AssignmentProblem[]
  completedProblems: number
  totalProblems: number
}

export type AssignmentProblem = { problemId: string; title: string; status: string }

export type StudentProblemActivity = {
  problemId: string; title: string; status: string; attempts: number; bestPassed: number; totalTests: number
}

export type EducatorDashboardData = {
  courseId: string
  inviteCode: string
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

export type EducatorCourse = {
  id: string
  title: string
  term: string
  educatorName: string
  inviteCode: string
  studentCount: number
  assignedProblemCount: number
}

export type StudentCourse = {
  id: string
  title: string
  term: string
  educatorName: string
  assignedProblemCount: number
}

export async function getStudentCourses(): Promise<StudentCourse[]> {
  if (!isApiConfigured) return []
  return normalizeStudentCourses(await apiRequest<unknown>('/student/courses'))
}

export async function joinStudentCourse(inviteCode: string): Promise<StudentCourse> {
  const payload = await apiRequest<unknown>('/student/courses/join', {
    method: 'POST',
    body: JSON.stringify({ invite_code: inviteCode.trim() }),
  })
  const [course] = normalizeStudentCourses([payload])
  if (!course) throw new Error('강의 정보가 올바르지 않습니다.')
  return course
}

function normalizeStudentCourses(payload: unknown): StudentCourse[] {
  if (!Array.isArray(payload)) return []
  return payload.flatMap((item) => isObject(item) && typeof item.id === 'string' ? [{
    id: item.id,
    title: stringOr(item.title) || '강의',
    term: stringOr(item.term),
    educatorName: stringOr(item.educator_name) || '교수자',
    assignedProblemCount: numberOr(item.assigned_problem_count, 0),
  }] : [])
}

export async function getEducatorCourses(): Promise<EducatorCourse[]> {
  if (!isApiConfigured) return []
  const payload = await apiRequest<unknown>('/educator/courses')
  if (!Array.isArray(payload)) return []
  return payload.flatMap((item) => isObject(item) && typeof item.id === 'string' ? [{
    id: item.id,
    title: stringOr(item.title) || '새 강의',
    term: stringOr(item.term),
    educatorName: stringOr(item.educator_name) || '교수자',
    inviteCode: stringOr(item.invite_code),
    studentCount: numberOr(item.student_count, 0),
    assignedProblemCount: numberOr(item.assigned_problem_count, 0),
  }] : [])
}

export async function createEducatorCourse(title: string, term: string): Promise<EducatorCourse> {
  const item = await apiRequest<Record<string, unknown>>('/educator/courses', {
    method: 'POST',
    body: JSON.stringify({ title, term, problem_ids: [] }),
  })
  return {
    id: String(item.id), title: stringOr(item.title) || title, term: stringOr(item.term) || term,
    educatorName: stringOr(item.educator_name) || '교수자', inviteCode: stringOr(item.invite_code),
    studentCount: numberOr(item.student_count, 0), assignedProblemCount: numberOr(item.assigned_problem_count, 0),
  }
}

export async function getEducatorDashboard(course: EducatorCourse): Promise<EducatorDashboardData | null> {
  if (!isApiConfigured) return null
  const courseId = course.id

  const [dashboard, students, attention, assignments] = await Promise.all([
    apiRequest<Record<string, unknown>>(`/educator/courses/${encodeURIComponent(courseId)}/dashboard`),
    apiRequest<unknown>(`/educator/courses/${encodeURIComponent(courseId)}/students`),
    apiRequest<unknown>(`/educator/courses/${encodeURIComponent(courseId)}/attention`).catch(() => null),
    // 백엔드가 순차 배포되거나 개발 서버가 재시작되기 전이어도 기존
    // 강의 대시보드는 숨기지 않는다. 과제 영역만 빈 상태로 낮춰 표시한다.
    apiRequest<unknown>(`/educator/courses/${encodeURIComponent(courseId)}/assignments`).catch(() => []),
  ])

  const normalizedStudents = normalizeStudents(students)
  const attentionStudents = normalizeStudents(attention).length ? normalizeStudents(attention) : normalizedStudents.filter((student) => student.status !== '순조로움')

  const metrics = isObject(dashboard.metrics) ? dashboard.metrics : dashboard
  return {
    courseId,
    inviteCode: course.inviteCode,
    courseTitle: course.title,
    courseSubtitle: `${course.term || '학기 미정'} · 수강생 ${course.studentCount}명 · 담당 교수 ${course.educatorName}`,
    totalStudents: numberOr(metrics.student_count, normalizedStudents.length),
    averageProgress: numberOr(metrics.average_progress, average(normalizedStudents.map((student) => student.progress))),
    completionRate: numberOr(metrics.completion_rate, 0),
    needsHelp: numberOr(metrics.needs_attention_count, attentionStudents.filter((student) => student.status === '도움 필요').length),
    students: normalizedStudents,
    attentionStudents,
    assignments: normalizeAssignments(assignments),
  }
}

export async function createAssignment(courseId: string, input: { title: string; description: string; problemIds: string[]; dueAt: string }): Promise<EducatorAssignment> {
  const payload = await apiRequest<unknown>(`/educator/courses/${encodeURIComponent(courseId)}/assignments`, {
    method: 'POST', body: JSON.stringify({
      title: input.title, description: input.description, problem_ids: input.problemIds,
      due_at: input.dueAt ? new Date(input.dueAt).toISOString() : null,
    }),
  })
  return normalizeAssignments([payload])[0]
}

export async function getStudentAssignments(): Promise<EducatorAssignment[]> {
  if (!isApiConfigured) return []
  return normalizeAssignments(await apiRequest<unknown>('/student/assignments'))
}

export async function syncStoredStudentProgress(problemId: string, code: string, completed: boolean): Promise<void> {
  if (completed) {
    await apiRequest<unknown>(`/users/me/progress/${encodeURIComponent(problemId)}/local-result`, {
      method: 'POST', body: JSON.stringify({ student_code: code, status: 'ACCEPTED', passed: 1, total: 1, mode: 'submit' }),
    })
    return
  }
  await apiRequest<unknown>(`/users/me/progress/${encodeURIComponent(problemId)}/checkpoint`, {
    method: 'PUT', body: JSON.stringify({ student_code: code }),
  })
}

export async function getStudentProblemActivity(courseId: string, studentId: string): Promise<StudentProblemActivity[]> {
  const payload = await apiRequest<Record<string, unknown>>(`/educator/courses/${encodeURIComponent(courseId)}/students/${encodeURIComponent(studentId)}`)
  const rows = Array.isArray(payload.recent_activity) ? payload.recent_activity : []
  return rows.flatMap((item) => isObject(item) ? [{
    problemId: stringOr(item.problem_id), title: stringOr(item.title) || '문제', status: stringOr(item.status),
    attempts: numberOr(item.attempt_count, 0), bestPassed: numberOr(item.best_passed, 0), totalTests: numberOr(item.total_tests, 0),
  }] : [])
}

function normalizeStudents(payload: unknown): EducatorStudent[] {
  const items = Array.isArray(payload)
    ? payload
    : isObject(payload) && Array.isArray(payload.items)
      ? payload.items
      : isObject(payload) && Array.isArray(payload.students) ? payload.students : []

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
      id: stringOr(item.id) || stringOr(item.title),
      courseId: stringOr(item.course_id),
      courseTitle: stringOr(item.course_title),
      title: stringOr(item.title, item.name) || '과제',
      description: stringOr(item.description),
      due: stringOr(item.due, item.due_at, item.deadline) || '-',
      completed: numberOr(item.completed, item.completed_count, 0),
      total: numberOr(item.total, item.total_count, 0),
      average: numberOr(item.average, item.average_score, 0),
      problems: Array.isArray(item.problems) ? item.problems.flatMap((problem) => isObject(problem) ? [{ problemId: stringOr(problem.problem_id), title: stringOr(problem.title), status: stringOr(problem.status) }] : []) : [],
      completedProblems: numberOr(item.completed_problems, 0),
      totalProblems: numberOr(item.total_problems, Array.isArray(item.problems) ? item.problems.length : 0),
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
