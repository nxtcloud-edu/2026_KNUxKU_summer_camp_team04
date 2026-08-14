import { useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  AlertTriangle,
  ArrowRight,
  BarChart3,
  BookOpenCheck,
  CheckCircle2,
  ChevronDown,
  Copy,
  Clock3,
  Search,
  Plus,
  Send,
  Sparkles,
  TrendingUp,
  UserRound,
  UsersRound,
} from 'lucide-react'
import { createAssignment, createEducatorCourse, getEducatorCourses, getEducatorDashboard, getStudentProblemActivity, type EducatorCourse, type EducatorDashboardData, type EducatorStudent, type StudentProblemActivity, type StudentStatus } from './educatorService'
import { getProblems, type ProblemSummary } from './problemService'

export default function EducatorPage() {
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState<'전체' | StudentStatus>('전체')
  const [selectedStudent, setSelectedStudent] = useState<EducatorStudent | null>(null)
  const [courses, setCourses] = useState<EducatorCourse[]>([])
  const [selectedCourseId, setSelectedCourseId] = useState('')
  const [dashboard, setDashboard] = useState<EducatorDashboardData | null>(null)
  const [creating, setCreating] = useState(false)
  const [courseTitle, setCourseTitle] = useState('')
  const [courseTerm, setCourseTerm] = useState('')
  const [message, setMessage] = useState('')
  const [problems, setProblems] = useState<ProblemSummary[]>([])
  const [assignmentOpen, setAssignmentOpen] = useState(false)
  const [assignmentTitle, setAssignmentTitle] = useState('')
  const [assignmentDescription, setAssignmentDescription] = useState('')
  const [assignmentDue, setAssignmentDue] = useState('')
  const [assignmentProblems, setAssignmentProblems] = useState<string[]>([])

  useEffect(() => {
    getEducatorCourses().then((items) => {
      setCourses(items)
      if (items[0]) setSelectedCourseId(items[0].id)
    }).catch((error) => setMessage(error instanceof Error ? error.message : '강의를 불러오지 못했습니다.'))
  }, [])

  useEffect(() => { getProblems().then((result) => setProblems(result.problems)).catch(() => undefined) }, [])

  useEffect(() => {
    const course = courses.find((item) => item.id === selectedCourseId)
    if (!course) { setDashboard(null); return }
    setMessage('')
    getEducatorDashboard(course).then(setDashboard).catch((error) => setMessage(error instanceof Error ? error.message : '대시보드를 불러오지 못했습니다.'))
  }, [courses, selectedCourseId])

  const createCourse = async (event: React.FormEvent) => {
    event.preventDefault()
    setCreating(true); setMessage('')
    try {
      const course = await createEducatorCourse(courseTitle, courseTerm)
      setCourses((items) => [course, ...items]); setSelectedCourseId(course.id)
      setCourseTitle(''); setCourseTerm('')
    } catch (error) { setMessage(error instanceof Error ? error.message : '강의를 만들지 못했습니다.') }
    finally { setCreating(false) }
  }

  const filtered = useMemo(() => (dashboard?.students ?? []).filter((student) => {
    const keyword = query.trim().toLowerCase()
    return (status === '전체' || student.status === status)
      && (!keyword || `${student.name} ${student.email} ${student.weakConcept}`.toLowerCase().includes(keyword))
  }), [dashboard?.students, query, status])

  const submitAssignment = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!dashboard || !assignmentProblems.length) return
    try {
      const assignment = await createAssignment(dashboard.courseId, { title: assignmentTitle, description: assignmentDescription, problemIds: assignmentProblems, dueAt: assignmentDue })
      setDashboard({ ...dashboard, assignments: [assignment, ...dashboard.assignments] })
      setAssignmentOpen(false); setAssignmentTitle(''); setAssignmentDescription(''); setAssignmentDue(''); setAssignmentProblems([])
      setMessage('과제를 학생들에게 배정했습니다.')
    } catch (error) { setMessage(error instanceof Error ? error.message : '과제를 만들지 못했습니다.') }
  }

  return (
    <main className="educator-page">
      <div className="educator-container">
        <header className="educator-heading">
          <div>
            <span>EDUCATOR CONSOLE</span>
            <h1>{dashboard?.courseTitle ?? '새 강의를 시작하세요'}</h1>
            <p>{dashboard?.courseSubtitle ?? '강의를 만들면 학생 초대 코드가 자동으로 생성됩니다.'}</p>
          </div>
          {courses.length > 0 && <select className="course-selector" value={selectedCourseId} onChange={(event) => setSelectedCourseId(event.target.value)}>{courses.map((course) => <option key={course.id} value={course.id}>{course.title} · {course.term}</option>)}</select>}
        </header>

        <form className="course-create-bar" onSubmit={createCourse}>
          <input value={courseTitle} onChange={(event) => setCourseTitle(event.target.value)} placeholder="강의명 (예: Python 기초 01)" required />
          <input value={courseTerm} onChange={(event) => setCourseTerm(event.target.value)} placeholder="학기 (예: 2026 여름학기)" />
          <button className="educator-primary" disabled={creating}><Plus size={15} /> 강의 만들기</button>
        </form>
        {message && <p className="educator-message">{message}</p>}

        {dashboard && <div className="course-invite-banner"><div><strong>학생 초대 코드</strong><span>{dashboard.inviteCode}</span><small>학생이 회원가입할 때 이 코드를 입력하면 자동으로 강의에 참여합니다.</small></div><button type="button" onClick={async () => { await navigator.clipboard.writeText(dashboard.inviteCode); setMessage('초대 코드를 복사했습니다.') }}><Copy size={15} /> 복사</button></div>}

        {!dashboard ? <section className="educator-empty"><UsersRound /><h2>아직 운영 중인 강의가 없어요</h2><p>위에서 첫 강의를 만들고 생성된 코드를 학생들에게 공유해 주세요.</p></section> : <>

        <section className="educator-metrics" aria-label="수업 요약">
          <Metric icon={<UsersRound />} label="전체 수강생" value={`${dashboard.totalStudents}명`} note="현재 강의 기준" />
          <Metric icon={<TrendingUp />} label="평균 진도율" value={`${dashboard.averageProgress}%`} note="최근 학습 기록 반영" />
          <Metric icon={<CheckCircle2 />} label="문제 완료율" value={`${dashboard.completionRate}%`} note="전체 과제 기준" />
          <Metric icon={<AlertTriangle />} label="도움 필요" value={`${dashboard.needsHelp}명`} note="최근 3일 기준" alert />
        </section>

        <div className="educator-dashboard-grid">
          <section className="educator-panel educator-attention">
            <PanelTitle icon={<Sparkles />} title="지금 확인할 학생" caption="반복 실패와 학습 정체를 감지했어요" />
            <div className="attention-list">
              {dashboard.attentionStudents.length === 0 && <p className="panel-empty">현재 확인이 필요한 학생이 없습니다.</p>}
              {dashboard.attentionStudents.slice(0, 3).map((student) => (
                <button key={student.id} onClick={() => setSelectedStudent(student)}>
                  <span className={`student-avatar ${student.status === '도움 필요' ? 'alert' : ''}`}>{student.name.slice(-1)}</span>
                  <span><strong>{student.name}</strong><small>{student.weakConcept} · 진도 {student.progress}%</small></span>
                  <span className="attention-reason">{student.status}</span>
                  <ArrowRight size={15} />
                </button>
              ))}
            </div>
          </section>

          <section className="educator-panel assignment-overview">
            <PanelTitle icon={<BookOpenCheck />} title="과제 현황" caption="마감일과 평균 성취도를 확인하세요" />
            <button type="button" className="educator-primary assignment-create-button" onClick={() => setAssignmentOpen(true)}><Plus size={15} /> 새 과제</button>
            <div className="assignment-list">
              {dashboard.assignments.length === 0 && <p className="panel-empty">과제 데이터가 아직 없습니다.</p>}
              {dashboard.assignments.map((assignment) => (
                <div key={assignment.title}>
                  <div><strong>{assignment.title}</strong><small><Clock3 size={11} /> {assignment.due === '-' ? '마감 없음' : `${new Date(assignment.due).toLocaleString('ko-KR')} 마감`}</small></div>
                  <div className="assignment-progress"><span><i style={{ width: `${assignment.total ? (assignment.completed / assignment.total) * 100 : 0}%` }} /></span><small>{assignment.completed}/{assignment.total}명</small></div>
                  <strong className="assignment-score">{assignment.average}점</strong>
                </div>
              ))}
            </div>
          </section>
        </div>

        <section className="educator-panel student-management">
          <div className="student-management-heading">
            <PanelTitle icon={<BarChart3 />} title="수강생 학습 현황" caption="진도와 최근 학습 활동을 한눈에 둘러보세요" />
            <div className="student-controls">
              <label><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="이름 또는 취약 개념 검색" /></label>
              <div className="educator-filter">
                <select value={status} onChange={(event) => setStatus(event.target.value as typeof status)}>
                  <option>전체</option><option>순조로움</option><option>관찰 필요</option><option>도움 필요</option>
                </select><ChevronDown size={14} />
              </div>
            </div>
          </div>

          <div className="student-table-wrap">
            <table className="student-table">
              <thead><tr><th>수강생</th><th>진도율</th><th>완료 문제</th><th>시도</th><th>최근 활동</th><th>학습 상태</th><th /></tr></thead>
              <tbody>{filtered.map((student) => (
                <tr key={student.id}>
                  <td><span className="table-student"><i><UserRound size={15} /></i><span><strong>{student.name}</strong><small>{student.email}</small></span></span></td>
                  <td><span className="table-progress"><span><i style={{ width: `${student.progress}%` }} /></span><strong>{student.progress}%</strong></span></td>
                  <td>{student.solved}개</td><td>{student.attempts}회</td><td>{student.lastActive}</td>
                  <td><span className={`student-status status-${student.status.replace(' ', '-')}`}>{student.status}</span></td>
                  <td><button aria-label={`${student.name} 상세 보기`} onClick={() => setSelectedStudent(student)}><ArrowRight size={15} /></button></td>
                </tr>
              ))}{filtered.length === 0 && <tr><td colSpan={7} className="student-empty">초대 코드를 사용해 참여한 학생이 여기에 표시됩니다.</td></tr>}</tbody>
            </table>
          </div>
        </section>
        </>}
      </div>

      {selectedStudent && dashboard && <StudentDrawer courseId={dashboard.courseId} student={selectedStudent} onClose={() => setSelectedStudent(null)} />}
      {assignmentOpen && <div className="student-drawer-backdrop" onMouseDown={() => setAssignmentOpen(false)}><form className="assignment-modal" onSubmit={submitAssignment} onMouseDown={(event) => event.stopPropagation()}><button type="button" className="drawer-close" onClick={() => setAssignmentOpen(false)}>닫기</button><h2>새 과제 만들기</h2><p>학생들이 해결할 문제와 마감일을 지정하세요.</p><label>과제명<input required value={assignmentTitle} onChange={(event) => setAssignmentTitle(event.target.value)} placeholder="예: 반복문 기초 연습" /></label><label>설명<textarea value={assignmentDescription} onChange={(event) => setAssignmentDescription(event.target.value)} placeholder="학습 목표나 안내를 적어주세요." /></label><label>마감일<input type="datetime-local" value={assignmentDue} onChange={(event) => setAssignmentDue(event.target.value)} /></label><fieldset><legend>문제 선택 ({assignmentProblems.length}개)</legend>{problems.map((problem) => <label key={problem.problem_id}><input type="checkbox" checked={assignmentProblems.includes(problem.problem_id)} onChange={() => setAssignmentProblems((items) => items.includes(problem.problem_id) ? items.filter((id) => id !== problem.problem_id) : [...items, problem.problem_id])} /><span>{problem.title}</span></label>)}</fieldset><button className="educator-primary full" disabled={!assignmentProblems.length}><Send size={15} /> 과제 배정하기</button></form></div>}
    </main>
  )
}

function Metric({ icon, label, value, note, alert = false }: { icon: ReactNode; label: string; value: string; note: string; alert?: boolean }) {
  return <div className={`educator-metric ${alert ? 'alert' : ''}`}><span>{icon}</span><div><small>{label}</small><strong>{value}</strong><p>{note}</p></div></div>
}

function PanelTitle({ icon, title, caption }: { icon: ReactNode; title: string; caption: string }) {
  return <div className="educator-panel-title"><span>{icon}</span><div><strong>{title}</strong><small>{caption}</small></div></div>
}

function StudentDrawer({ courseId, student, onClose }: { courseId: string; student: EducatorStudent; onClose: () => void }) {
  const [activity, setActivity] = useState<StudentProblemActivity[]>([])
  useEffect(() => { getStudentProblemActivity(courseId, student.id).then(setActivity).catch(() => setActivity([])) }, [courseId, student.id])
  const solved = activity.filter((item) => item.status.includes('SOLVED')).length
  const inProgress = activity.filter((item) => !item.status.includes('SOLVED') && !item.status.includes('NOT_STARTED')).length
  return <div className="student-drawer-backdrop" onMouseDown={onClose}><aside className="student-drawer" onMouseDown={(event) => event.stopPropagation()}><button className="drawer-close" onClick={onClose}>닫기</button><span className="student-avatar large">{student.name.slice(-1)}</span><h2>{student.name}</h2><p>{student.email}</p><div className="drawer-summary"><div><span>진도율</span><strong>{student.progress}%</strong></div><div><span>해결 완료</span><strong>{solved}개</strong></div><div><span>해결 중</span><strong>{inProgress}개</strong></div></div><div className="student-problem-activity"><strong>문제별 학습 현황</strong>{activity.length === 0 ? <p>배정된 문제가 없습니다.</p> : activity.map((item) => { const isSolved = item.status.includes('SOLVED'); const notStarted = item.status.includes('NOT_STARTED'); return <div key={item.problemId}><span><b>{item.title}</b><small>{notStarted ? '아직 시도하지 않음' : `${item.attempts}회 시도 · ${item.bestPassed}/${item.totalTests} 통과`}</small></span><em className={isSolved ? 'solved' : notStarted ? 'not-started' : 'in-progress'}>{isSolved ? '해결 완료' : notStarted ? '시작 전' : '해결 중'}</em></div> })}</div><div className="drawer-insight"><Sparkles size={17} /><div><strong>학습 분석</strong><p><b>{student.weakConcept}</b> 개념에서 반복 실패가 관찰됩니다. 관련 기초 문제를 배정하거나 힌트를 보내보세요.</p></div></div></aside></div>
}
