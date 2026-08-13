import { useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  AlertTriangle,
  ArrowRight,
  BarChart3,
  BookOpenCheck,
  CheckCircle2,
  ChevronDown,
  Clock3,
  Search,
  Send,
  Sparkles,
  TrendingUp,
  UserRound,
  UsersRound,
} from 'lucide-react'
import { getEducatorDashboard, type EducatorAssignment, type EducatorDashboardData, type EducatorStudent, type StudentStatus } from './educatorService'

const DEMO_STUDENTS: EducatorStudent[] = [
  { id: 'STU-001', name: '김민서', email: 'minseo@univ.ac.kr', progress: 82, solved: 21, attempts: 31, lastActive: '12분 전', status: '순조로움', weakConcept: '반복문' },
  { id: 'STU-002', name: '박지훈', email: 'jihoon@univ.ac.kr', progress: 46, solved: 12, attempts: 38, lastActive: '34분 전', status: '도움 필요', weakConcept: '조건문' },
  { id: 'STU-003', name: '이서연', email: 'seoyeon@univ.ac.kr', progress: 73, solved: 19, attempts: 27, lastActive: '1시간 전', status: '순조로움', weakConcept: '함수' },
  { id: 'STU-004', name: '최현우', email: 'hyunwoo@univ.ac.kr', progress: 58, solved: 15, attempts: 33, lastActive: '어제', status: '관찰 필요', weakConcept: '리스트' },
  { id: 'STU-005', name: '정하린', email: 'harin@univ.ac.kr', progress: 31, solved: 8, attempts: 29, lastActive: '3일 전', status: '도움 필요', weakConcept: '입출력' },
  { id: 'STU-006', name: '오도현', email: 'dohyun@univ.ac.kr', progress: 65, solved: 17, attempts: 25, lastActive: '2시간 전', status: '관찰 필요', weakConcept: '중첩 반복' },
]

const DEMO_ASSIGNMENTS: EducatorAssignment[] = [
  { title: 'Python 기초 · 조건문', due: '8월 16일', completed: 21, total: 28, average: 78 },
  { title: '반복문 집중 연습', due: '8월 20일', completed: 14, total: 28, average: 64 },
  { title: '함수와 리스트', due: '8월 25일', completed: 6, total: 28, average: 51 },
]

const DEMO_DASHBOARD: EducatorDashboardData = {
  courseTitle: 'Python 기초 01',
  courseSubtitle: '2026 여름학기 · 수강생 28명 · 담당 교수 김튜토리',
  totalStudents: 28,
  averageProgress: 64,
  completionRate: 71,
  needsHelp: DEMO_STUDENTS.filter((student) => student.status === '도움 필요').length,
  students: DEMO_STUDENTS,
  attentionStudents: DEMO_STUDENTS.filter((student) => student.status !== '순조로움'),
  assignments: DEMO_ASSIGNMENTS,
}

export default function EducatorPage() {
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState<'전체' | StudentStatus>('전체')
  const [selectedStudent, setSelectedStudent] = useState<EducatorStudent | null>(null)
  const [dashboard, setDashboard] = useState(DEMO_DASHBOARD)

  useEffect(() => {
    getEducatorDashboard()
      .then((data) => {
        if (data) setDashboard({
          ...data,
          students: data.students.length ? data.students : DEMO_STUDENTS,
          attentionStudents: data.attentionStudents.length ? data.attentionStudents : DEMO_DASHBOARD.attentionStudents,
          assignments: data.assignments.length ? data.assignments : DEMO_ASSIGNMENTS,
        })
      })
      .catch((error) => console.warn('Educator dashboard API unavailable. Using demo data.', error))
  }, [])

  const filtered = useMemo(() => dashboard.students.filter((student) => {
    const keyword = query.trim().toLowerCase()
    return (status === '전체' || student.status === status)
      && (!keyword || `${student.name} ${student.email} ${student.weakConcept}`.toLowerCase().includes(keyword))
  }), [dashboard.students, query, status])

  return (
    <main className="educator-page">
      <div className="educator-container">
        <header className="educator-heading">
          <div>
            <span>EDUCATOR CONSOLE</span>
            <h1>{dashboard.courseTitle}</h1>
            <p>{dashboard.courseSubtitle}</p>
          </div>
          <button className="educator-primary"><Send size={15} /> 공지 보내기</button>
        </header>

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
            <div className="assignment-list">
              {dashboard.assignments.map((assignment) => (
                <div key={assignment.title}>
                  <div><strong>{assignment.title}</strong><small><Clock3 size={11} /> {assignment.due} 마감</small></div>
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
              ))}</tbody>
            </table>
          </div>
        </section>
      </div>

      {selectedStudent && <StudentDrawer student={selectedStudent} onClose={() => setSelectedStudent(null)} />}
    </main>
  )
}

function Metric({ icon, label, value, note, alert = false }: { icon: ReactNode; label: string; value: string; note: string; alert?: boolean }) {
  return <div className={`educator-metric ${alert ? 'alert' : ''}`}><span>{icon}</span><div><small>{label}</small><strong>{value}</strong><p>{note}</p></div></div>
}

function PanelTitle({ icon, title, caption }: { icon: ReactNode; title: string; caption: string }) {
  return <div className="educator-panel-title"><span>{icon}</span><div><strong>{title}</strong><small>{caption}</small></div></div>
}

function StudentDrawer({ student, onClose }: { student: EducatorStudent; onClose: () => void }) {
  return <div className="student-drawer-backdrop" onMouseDown={onClose}><aside className="student-drawer" onMouseDown={(event) => event.stopPropagation()}><button className="drawer-close" onClick={onClose}>닫기</button><span className="student-avatar large">{student.name.slice(-1)}</span><h2>{student.name}</h2><p>{student.email}</p><div className="drawer-summary"><div><span>진도율</span><strong>{student.progress}%</strong></div><div><span>완료 문제</span><strong>{student.solved}개</strong></div><div><span>총 시도</span><strong>{student.attempts}회</strong></div></div><div className="drawer-insight"><Sparkles size={17} /><div><strong>학습 분석</strong><p><b>{student.weakConcept}</b> 개념에서 반복 실패가 관찰됩니다. 관련 기초 문제를 배정하거나 힌트를 보내보세요.</p></div></div><button className="educator-primary full"><Send size={15} /> 개별 메시지 보내기</button></aside></div>
}
