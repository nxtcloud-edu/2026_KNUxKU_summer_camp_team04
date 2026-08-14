import { useEffect, useMemo, useState } from 'react'
import { ArrowRight, BookOpenCheck, Braces, CheckCircle2, ChevronLeft, ChevronRight, LoaderCircle, Plus, Search, Terminal } from 'lucide-react'
import { getLearningProgress } from './learningProgress'
import { getProblems, type ProblemListSource, type ProblemSummary } from './problemService'
import AcornIcon from './AcornIcon'
import { getStudentAssignments, getStudentCourses, joinStudentCourse, syncStoredStudentProgress, type EducatorAssignment, type StudentCourse } from './educatorService'
import squirrelTutor from './assets/squirrel-tutor-v2.png'

type ProblemFilter = 'all' | 'function_call' | 'stdout_match'
const PROBLEMS_PER_PAGE = 10

export function ProblemList({ onSelect, canJoinCourse = false }: { onSelect: (problem: ProblemSummary) => void; canJoinCourse?: boolean }) {
  const [problems, setProblems] = useState<ProblemSummary[]>([])
  const [source, setSource] = useState<ProblemListSource>('local')
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<ProblemFilter>('all')
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [courses, setCourses] = useState<StudentCourse[]>([])
  const [inviteCode, setInviteCode] = useState('')
  const [courseMessage, setCourseMessage] = useState('')
  const [joiningCourse, setJoiningCourse] = useState(false)
  const [assignments, setAssignments] = useState<EducatorAssignment[]>([])
  const [selectedCourseId, setSelectedCourseId] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    getProblems(controller.signal)
      .then((result) => { setProblems(result.problems); setSource(result.source) })
      .catch((caught) => {
        if (!(caught instanceof DOMException && caught.name === 'AbortError')) setError('문제 목록을 불러오지 못했습니다.')
      })
      .finally(() => setLoading(false))
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (!canJoinCourse) return
    Promise.all([getStudentCourses(), getStudentAssignments().catch(() => [])]).then(([courseItems, assignmentItems]) => { setCourses(courseItems); setAssignments(assignmentItems) }).catch((caught) => setCourseMessage(caught instanceof Error ? caught.message : '참여 강의를 불러오지 못했습니다.'))
  }, [canJoinCourse])

  useEffect(() => {
    if (!canJoinCourse || problems.length === 0) return
    const stored = problems.flatMap((problem) => {
      const progress = getLearningProgress(problem.problem_id)
      return progress ? [{ problem, progress }] : []
    })
    if (!stored.length) return
    Promise.allSettled(stored.map(({ problem, progress }) => syncStoredStudentProgress(
      problem.problem_id, progress.code, progress.status === 'COMPLETED',
    ))).then(() => getStudentAssignments().then(setAssignments).catch(() => undefined))
  }, [canJoinCourse, problems])

  const joinCourse = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!inviteCode.trim()) return
    setJoiningCourse(true)
    setCourseMessage('')
    try {
      const course = await joinStudentCourse(inviteCode)
      setCourses((items) => items.some((item) => item.id === course.id) ? items : [...items, course])
      setInviteCode('')
      setCourseMessage(`${course.title} 강의에 참여했습니다.`)
    } catch (caught) {
      setCourseMessage(caught instanceof Error ? caught.message : '강의에 참여하지 못했습니다.')
    } finally {
      setJoiningCourse(false)
    }
  }

  const filtered = useMemo(() => problems
    .filter((problem) => {
      const type = problem.problem_id.startsWith('func_') ? 'function_call' : 'stdout_match'
      const matchesFilter = filter === 'all' || type === filter
      const keyword = query.trim().toLocaleLowerCase()
      const matchesQuery = !keyword || `${problem.title} ${problem.problem_id} ${problem.concept.join(' ')}`.toLocaleLowerCase().includes(keyword)
      return matchesFilter && matchesQuery
    })
    .sort((a, b) => {
      const aInProgress = getLearningProgress(a.problem_id)?.status === 'IN_PROGRESS'
      const bInProgress = getLearningProgress(b.problem_id)?.status === 'IN_PROGRESS'
      return Number(bInProgress) - Number(aInProgress)
    }), [filter, problems, query])

  const pageCount = Math.max(1, Math.ceil(filtered.length / PROBLEMS_PER_PAGE))
  const visibleProblems = useMemo(() => {
    const start = (page - 1) * PROBLEMS_PER_PAGE
    return filtered.slice(start, start + PROBLEMS_PER_PAGE)
  }, [filtered, page])

  useEffect(() => {
    setPage(1)
  }, [filter, query])

  useEffect(() => {
    if (page > pageCount) setPage(pageCount)
  }, [page, pageCount])

  const recommendations = useMemo(() => {
    const unfinished = problems.filter((problem) => getLearningProgress(problem.problem_id)?.status !== 'COMPLETED')
    const pool = unfinished.length >= 3 ? unfinished : problems
    const beginnerFirst = [...pool].sort((a, b) => Number(!a.problem_id.startsWith('func_')) - Number(!b.problem_id.startsWith('func_')))
    return beginnerFirst.slice(0, 3)
  }, [problems])

  const selectedAssignments = assignments.filter((assignment) => assignment.courseId === selectedCourseId)
  const problemState = (problemId: string, serverStatus: string) => {
    if (serverStatus.includes('SOLVED')) return 'completed' as const
    const local = getLearningProgress(problemId)?.status
    if (local === 'COMPLETED') return 'completed' as const
    if (serverStatus.includes('IN_PROGRESS') || local === 'IN_PROGRESS') return 'in-progress' as const
    return 'not-started' as const
  }
  const completedCount = (assignment: EducatorAssignment) => assignment.problems.filter((item) => problemState(item.problemId, item.status) === 'completed').length

  return (
    <main className="problem-list-page">
      <div className="problem-list-container">
        <div className="home-utility"><span className={`data-source ${source}`}>{source === 'api' ? '학습 데이터 연결됨' : '로컬 학습 모드'}</span></div>
        <div className="problem-list-heading home-heading">
          <div className="home-squirrel-message">
            <img src={squirrelTutor} alt="" />
            <div className="home-speech-bubble">
              <span>GOOD TO SEE YOU</span>
              <h1>오늘도 한 문제씩,<br />차근차근 시작해 볼까요?</h1>
              <p>현재 학습 흐름에 잘 맞는 문제부터 골라봤어요.</p>
            </div>
          </div>
          <div className="problem-count"><strong>{problems.length}</strong><span>개의 문제</span></div>
        </div>

        {canJoinCourse && <section className="student-course-section">
          <div className="student-course-heading"><div><BookOpenCheck size={17} /><strong>내 강의</strong></div><span>교수자에게 받은 코드로 다른 강의에도 참여할 수 있어요.</span></div>
          {courses.length > 0 && <div className="student-course-chips">{courses.map((course) => {
            const courseAssignments = assignments.filter((assignment) => assignment.courseId === course.id)
            const hasRemaining = courseAssignments.some((assignment) => completedCount(assignment) < assignment.totalProblems)
            return <button type="button" key={course.id} className={selectedCourseId === course.id ? 'active' : ''} onClick={() => setSelectedCourseId((current) => current === course.id ? '' : course.id)}>{hasRemaining && <i className="course-task-dot" aria-label="미완료 과제 있음" />}<strong>{course.title}</strong><small>{course.term || '학기 미정'} · {course.educatorName}</small></button>
          })}</div>}
          {selectedCourseId && <div className="course-assignment-detail">
            <div className="course-assignment-title"><strong>{courses.find((course) => course.id === selectedCourseId)?.title} 과제</strong><button type="button" onClick={() => setSelectedCourseId('')}>접기</button></div>
            {selectedAssignments.length === 0 ? <p className="course-assignment-empty">아직 배정된 과제가 없습니다.</p> : selectedAssignments.map((assignment) => {
              const done = completedCount(assignment)
              const assignmentComplete = assignment.totalProblems > 0 && done === assignment.totalProblems
              return <article key={assignment.id} className={assignmentComplete ? 'completed' : ''}><header><span><strong>{assignment.title}</strong><small>{assignment.due === '-' ? '마감 없음' : `${new Date(assignment.due).toLocaleString('ko-KR')} 마감`}</small></span><b className={assignmentComplete ? 'complete' : ''}>{assignmentComplete ? '과제 완료' : `${done}/${assignment.totalProblems}문제 완료`}</b></header>{assignment.description && <p>{assignment.description}</p>}<div className="assignment-problem-links">{assignment.problems.map((item) => {
                const state = problemState(item.problemId, item.status)
                return <button key={item.problemId} type="button" onClick={() => { const target = problems.find((problem) => problem.problem_id === item.problemId); if (target) onSelect(target) }}><span>{item.title}</span><em className={state === 'completed' ? 'solved' : state === 'in-progress' ? 'in-progress' : ''}>{state === 'completed' ? '해결 완료' : state === 'in-progress' ? '해결 중' : '시작하기'}</em><ArrowRight size={14} /></button>
              })}</div></article>
            })}
          </div>}
          <form onSubmit={joinCourse}><input value={inviteCode} onChange={(event) => setInviteCode(event.target.value)} placeholder="강의 초대 코드 입력" aria-label="강의 초대 코드" /><button type="submit" disabled={joiningCourse || !inviteCode.trim()}>{joiningCourse ? <LoaderCircle className="spin" size={15} /> : <Plus size={15} />} 강의 참여</button></form>
          {courseMessage && <p>{courseMessage}</p>}
        </section>}

        {!loading && !error && recommendations.length > 0 && (
          <section className="recommended-section">
            <div className="home-section-title"><div><strong>추천 문제</strong></div><span>Checkpoint와 기초 학습 순서를 반영했어요</span></div>
            <div className="recommended-grid">
              {recommendations.map((problem, index) => <RecommendedProblem key={problem.problem_id} problem={problem} rank={index + 1} onClick={() => onSelect(problem)} />)}
            </div>
          </section>
        )}

        <section className="all-problems-section">
          <div className="home-section-title"><div><strong>모든 문제</strong></div><span>원하는 문제를 검색하거나 유형별로 살펴보세요</span></div>

        <div className="problem-toolbar">
          <label className="problem-search"><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="문제 제목이나 개념 검색" /></label>
          <div className="problem-filters" aria-label="문제 유형">
            <FilterButton active={filter === 'all'} onClick={() => setFilter('all')}>전체</FilterButton>
            <FilterButton active={filter === 'function_call'} onClick={() => setFilter('function_call')}>함수형</FilterButton>
            <FilterButton active={filter === 'stdout_match'} onClick={() => setFilter('stdout_match')}>입출력형</FilterButton>
          </div>
        </div>

        <div className="problem-list-meta"><span>전체 {filtered.length}개 · {page}/{pageCount} 페이지</span></div>

        {loading ? <div className="problem-list-state"><LoaderCircle className="spin" /> 문제를 불러오고 있어요</div>
          : error ? <div className="problem-list-state error">{error}</div>
          : filtered.length === 0 ? <div className="problem-list-state">검색 결과가 없습니다.</div>
          : <>
            <div className="problem-rows">{visibleProblems.map((problem, index) => <ProblemRow key={problem.problem_id} problem={problem} number={problems.indexOf(problem) + 1 || (page - 1) * PROBLEMS_PER_PAGE + index + 1} onClick={() => onSelect(problem)} />)}</div>
            {pageCount > 1 && <Pagination page={page} pageCount={pageCount} onChange={setPage} />}
          </>}
        </section>
      </div>
    </main>
  )
}

function Pagination({ page, pageCount, onChange }: { page: number; pageCount: number; onChange: (page: number) => void }) {
  return (
    <nav className="problem-pagination" aria-label="문제 목록 페이지">
      <button type="button" aria-label="이전 페이지" disabled={page === 1} onClick={() => onChange(page - 1)}><ChevronLeft size={16} /></button>
      {Array.from({ length: pageCount }, (_, index) => index + 1).map((pageNumber) => (
        <button key={pageNumber} type="button" className={pageNumber === page ? 'active' : ''} aria-current={pageNumber === page ? 'page' : undefined} onClick={() => onChange(pageNumber)}>{pageNumber}</button>
      ))}
      <button type="button" aria-label="다음 페이지" disabled={page === pageCount} onClick={() => onChange(page + 1)}><ChevronRight size={16} /></button>
    </nav>
  )
}

function FilterButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: string }) {
  return <button className={active ? 'active' : ''} onClick={onClick}>{children}</button>
}

function RecommendedProblem({ problem, rank, onClick }: { problem: ProblemSummary; rank: number; onClick: () => void }) {
  const functionType = problem.problem_id.startsWith('func_')
  return (
    <button className={`recommended-problem recommendation-${rank}`} onClick={onClick}>
      <span className="recommendation-label">{rank === 1 ? '지금 풀기 좋아요' : rank === 2 ? '이어서 도전' : '기초 다지기'}</span>
      <span className="recommendation-icon">{functionType ? <Braces /> : <Terminal />}</span>
      <strong>{problem.title}</strong>
      <small>{rank === 1 ? '최근 학습 흐름과 딱 맞아요' : functionType ? '함수와 반복문을 함께 연습해요' : '입력과 출력의 흐름을 익혀요'}</small>
      <span className="problem-reward"><AcornIcon /> 도토리 {problem.acorn_reward}개</span>
      <span className="recommendation-action">{rank === 1 ? '지금 풀기' : '문제 풀기'} <ArrowRight size={15} /></span>
    </button>
  )
}

function ProblemRow({ problem, number, onClick }: { problem: ProblemSummary; number: number; onClick: () => void }) {
  const functionType = problem.problem_id.startsWith('func_')
  const progress = getLearningProgress(problem.problem_id)
  return (
    <button className="problem-row" onClick={onClick}>
      <span className="problem-row-number">{String(number).padStart(2, '0')}</span>
      <span className="problem-card-content">
        <strong>{problem.title}</strong>
        <small>{functionType ? '함수형' : '입출력형'} · {problem.concept.length ? problem.concept.join(' · ') : 'Python 기초'}</small>
      </span>
      <span className="problem-reward row"><AcornIcon /> {problem.acorn_reward}개</span>
      {progress && <span className={`checkpoint-state ${progress.status === 'COMPLETED' ? 'completed' : ''}`}><CheckCircle2 size={14} /> {progress.status === 'COMPLETED' ? '학습 완료' : '학습 중'}</span>}
      <ChevronRight className="problem-arrow" size={17} />
    </button>
  )
}
