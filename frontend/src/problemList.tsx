import { useEffect, useMemo, useState } from 'react'
import { ArrowRight, Braces, CheckCircle2, ChevronRight, LoaderCircle, Search, Sparkles, Terminal } from 'lucide-react'
import { getProblems, type ProblemListSource, type ProblemSummary } from './problemService'

type ProblemFilter = 'all' | 'function_call' | 'stdout_match'

export function ProblemList({ onSelect }: { onSelect: (problem: ProblemSummary) => void }) {
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

  const recommendations = useMemo(() => {
    const unfinished = problems.filter((problem) => !localStorage.getItem(`codetrace:checkpoint:${problem.problem_id}`))
    const pool = unfinished.length >= 3 ? unfinished : problems
    const beginnerFirst = [...pool].sort((a, b) => Number(!a.problem_id.startsWith('func_')) - Number(!b.problem_id.startsWith('func_')))
    return beginnerFirst.slice(0, 3)
  }, [problems])

  return (
    <main className="problem-list-page">
      <div className="problem-list-container">
        <div className="home-utility"><span className={`data-source ${source}`}>{source === 'api' ? '학습 데이터 연결됨' : '로컬 학습 모드'}</span></div>
        <div className="problem-list-heading home-heading">
          <div><span>GOOD TO SEE YOU</span><h1>오늘도 한 문제씩,<br />차근차근 시작해 볼까요?</h1><p>현재 학습 흐름에 잘 맞는 문제부터 골라봤어요.</p></div>
          <div className="problem-count"><strong>{problems.length}</strong><span>개의 문제</span></div>
        </div>

        {!loading && !error && recommendations.length > 0 && (
          <section className="recommended-section">
            <div className="home-section-title"><div><Sparkles size={16} /><strong>추천 문제</strong></div><span>Checkpoint와 기초 학습 순서를 반영했어요</span></div>
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

        <div className="problem-list-meta"><span>{filtered.length}개 표시 중</span></div>

        {loading ? <div className="problem-list-state"><LoaderCircle className="spin" /> 문제를 불러오고 있어요</div>
          : error ? <div className="problem-list-state error">{error}</div>
          : filtered.length === 0 ? <div className="problem-list-state">검색 결과가 없습니다.</div>
          : <div className="problem-rows">{filtered.map((problem, index) => <ProblemRow key={problem.problem_id} problem={problem} number={problems.indexOf(problem) + 1 || index + 1} onClick={() => onSelect(problem)} />)}</div>}
        </section>
      </div>
    </main>
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
      <small>{functionType ? '함수와 반복문을 함께 연습해요' : '입력과 출력의 흐름을 익혀요'}</small>
      <span className="recommendation-action">문제 풀기 <ArrowRight size={15} /></span>
    </button>
  )
}

function ProblemRow({ problem, number, onClick }: { problem: ProblemSummary; number: number; onClick: () => void }) {
  const functionType = problem.problem_id.startsWith('func_')
  const checkpointed = Boolean(localStorage.getItem(`codetrace:checkpoint:${problem.problem_id}`))
  return (
    <button className="problem-row" onClick={onClick}>
      <span className="problem-row-number">{String(number).padStart(2, '0')}</span>
      <span className="problem-card-content">
        <strong>{problem.title}</strong>
        <small>{functionType ? '함수형' : '입출력형'} · {problem.concept.length ? problem.concept.join(' · ') : 'Python 기초'}</small>
      </span>
      {checkpointed && <span className="checkpoint-state"><CheckCircle2 size={14} /> 학습 중</span>}
      <ChevronRight className="problem-arrow" size={17} />
    </button>
  )
}
