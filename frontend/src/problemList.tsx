import { useEffect, useMemo, useState } from 'react'
import { ArrowLeft, BookOpen, Braces, ChevronRight, LoaderCircle, Search, Terminal } from 'lucide-react'
import { getProblems, type ProblemListSource, type ProblemSummary } from './problemService'

type ProblemFilter = 'all' | 'function_call' | 'stdout_match'

export function ProblemList({ onExit, onSelect }: { onExit: () => void; onSelect: (problem: ProblemSummary) => void }) {
  const [problems, setProblems] = useState<ProblemSummary[]>([])
  const [source, setSource] = useState<ProblemListSource>('local')
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<ProblemFilter>('all')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

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

  const filtered = useMemo(() => problems.filter((problem) => {
    const type = problem.problem_id.startsWith('func_') ? 'function_call' : 'stdout_match'
    const matchesFilter = filter === 'all' || type === filter
    const keyword = query.trim().toLocaleLowerCase()
    const matchesQuery = !keyword || `${problem.title} ${problem.problem_id} ${problem.concept.join(' ')}`.toLocaleLowerCase().includes(keyword)
    return matchesFilter && matchesQuery
  }), [filter, problems, query])

  return (
    <main className="problem-list-page">
      <div className="problem-list-container">
        <button className="back-button" onClick={onExit}><ArrowLeft size={17} /> 학습 화면으로</button>
        <div className="problem-list-heading">
          <div><span>PYTHON PROBLEMS</span><h1>문제 목록</h1><p>기초부터 차근차근 풀며 Python 실행 흐름을 익혀보세요.</p></div>
          <div className="problem-count"><strong>{problems.length}</strong><span>개의 문제</span></div>
        </div>

        <div className="problem-toolbar">
          <label className="problem-search"><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="문제 제목이나 개념 검색" /></label>
          <div className="problem-filters" aria-label="문제 유형">
            <FilterButton active={filter === 'all'} onClick={() => setFilter('all')}>전체</FilterButton>
            <FilterButton active={filter === 'function_call'} onClick={() => setFilter('function_call')}>함수형</FilterButton>
            <FilterButton active={filter === 'stdout_match'} onClick={() => setFilter('stdout_match')}>입출력형</FilterButton>
          </div>
        </div>

        <div className="problem-list-meta"><span>{filtered.length}개 표시 중</span><span className={`data-source ${source}`}>{source === 'api' ? 'API 연결됨' : '로컬 데이터'}</span></div>

        {loading ? <div className="problem-list-state"><LoaderCircle className="spin" /> 문제를 불러오고 있어요</div>
          : error ? <div className="problem-list-state error">{error}</div>
          : filtered.length === 0 ? <div className="problem-list-state">검색 결과가 없습니다.</div>
          : <div className="problem-grid">{filtered.map((problem, index) => <ProblemCard key={problem.problem_id} problem={problem} number={problems.indexOf(problem) + 1 || index + 1} onClick={() => onSelect(problem)} />)}</div>}
      </div>
    </main>
  )
}

function FilterButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: string }) {
  return <button className={active ? 'active' : ''} onClick={onClick}>{children}</button>
}

function ProblemCard({ problem, number, onClick }: { problem: ProblemSummary; number: number; onClick: () => void }) {
  const functionType = problem.problem_id.startsWith('func_')
  return (
    <button className="problem-card" onClick={onClick}>
      <span className={`problem-type-icon ${functionType ? 'function' : ''}`}>{functionType ? <Braces /> : <Terminal />}</span>
      <span className="problem-card-content">
        <small>문제 {String(number).padStart(2, '0')} · {functionType ? '함수형' : '입출력형'}</small>
        <strong>{problem.title}</strong>
        <span className="concept-tags">{problem.concept.length ? problem.concept.map((concept) => <i key={concept}>{concept}</i>) : <i>python</i>}</span>
      </span>
      <ChevronRight className="problem-arrow" size={18} />
    </button>
  )
}
