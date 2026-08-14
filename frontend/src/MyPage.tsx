import { useEffect, useMemo, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import {
  Award,
  BadgeCheck,
  CalendarDays,
  Check,
  ChevronRight,
  Clock3,
  ImageUp,
  Lightbulb,
  Pencil,
  UserRound,
} from 'lucide-react'
import AcornIcon from './AcornIcon'
import { getAllLearningProgress, getRecentWrongHint, type LearningProgress } from './learningProgress'
import badgeSeed from './assets/badges/badge-seed.png'
import badgeSprout from './assets/badges/badge-sprout.png'
import badgeSapling from './assets/badges/badge-sapling.png'
import badgeOak from './assets/badges/badge-oak.png'
import badgeGuardian from './assets/badges/badge-guardian.png'
import badgeLegend from './assets/badges/badge-legend.png'
import squirrelTutor from './assets/squirrel-tutor-v2.png'

type Profile = {
  nickname: string
  avatar: string
  acorns: number
  totalAcorns: number
}

type Badge = {
  name: string
  minAcorns: number
  description: string
  image: string
}

type MyPageProps = {
  onAvatarChange?: (avatar: string) => void
  onProblemSelect?: (problemId: string) => void
}

type ProfileConfirmAction =
  | { type: 'nickname'; cost: number; nickname: string }
  | { type: 'avatar'; cost: number; file: File }

const PROFILE_KEY = 'tutory:profile'
const NICKNAME_COST = 5
const AVATAR_COST = 10
const LEARNING_LIST_PAGE_SIZE = 5

const DEFAULT_PROFILE: Profile = {
  nickname: '튜토리 학습자',
  avatar: '',
  acorns: 135,
  totalAcorns: 260,
}

const BADGES: Badge[] = [
  { name: '씨앗 뱃지', minAcorns: 0, description: '첫 문제 풀이를 시작한 학습자', image: badgeSeed },
  { name: '새싹 뱃지', minAcorns: 50, description: '꾸준히 기초 문제를 풀고 있어요', image: badgeSprout },
  { name: '묘목 뱃지', minAcorns: 150, description: '함수와 조건문에 익숙해졌어요', image: badgeSapling },
  { name: '참나무 뱃지', minAcorns: 300, description: '문제 해결 루틴이 단단해졌어요', image: badgeOak },
  { name: '숲지기 뱃지', minAcorns: 600, description: '고난도 문제에도 침착한 학습자', image: badgeGuardian },
  { name: '전설의 도토리', minAcorns: 1000, description: '튜토리 최고 레벨 학습자', image: badgeLegend },
]

function MyPage({ onAvatarChange, onProblemSelect }: MyPageProps) {
  const [profile, setProfile] = useState<Profile>(() => loadProfile())
  const [draftNickname, setDraftNickname] = useState(profile.nickname)
  const [message, setMessage] = useState('')
  const [confirmAction, setConfirmAction] = useState<ProfileConfirmAction | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const learningProgress = useMemo(() => getAllLearningProgress(), [])
  const inProgressProblems = learningProgress.filter((item) => item.status === 'IN_PROGRESS')
  const completedProblems = learningProgress.filter((item) => item.status === 'COMPLETED')
  const learningStreak = useMemo(() => calculateLearningStreak(learningProgress), [learningProgress])
  const recentWrongHint = useMemo(() => getRecentWrongHint(), [])

  const currentBadge = useMemo(
    () => [...BADGES].reverse().find((badge) => profile.totalAcorns >= badge.minAcorns) ?? BADGES[0],
    [profile.totalAcorns],
  )
  const nextBadge = BADGES.find((badge) => badge.minAcorns > profile.totalAcorns)
  const progress = nextBadge
    ? ((profile.totalAcorns - currentBadge.minAcorns) / (nextBadge.minAcorns - currentBadge.minAcorns)) * 100
    : 100

  const updateProfile = (nextProfile: Profile) => {
    setProfile(nextProfile)
    localStorage.setItem(PROFILE_KEY, JSON.stringify(nextProfile))
    onAvatarChange?.(nextProfile.avatar)
  }

  const canSpendAcorns = (cost: number) => {
    if (profile.acorns >= cost) return true
    setMessage(`도토리가 부족해요. ${cost}개가 필요합니다.`)
    return false
  }

  const saveNickname = () => {
    const nextNickname = draftNickname.trim()
    if (!nextNickname) {
      setMessage('닉네임을 입력해주세요.')
      return
    }
    if (nextNickname === profile.nickname) {
      setMessage('현재 닉네임과 같아요.')
      return
    }
    if (!canSpendAcorns(NICKNAME_COST)) return
    setConfirmAction({ type: 'nickname', cost: NICKNAME_COST, nickname: nextNickname })
  }

  const uploadAvatar = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return
    if (!canSpendAcorns(AVATAR_COST)) {
      event.target.value = ''
      return
    }
    setConfirmAction({ type: 'avatar', cost: AVATAR_COST, file })
    event.target.value = ''
  }

  const confirmProfileAction = () => {
    if (!confirmAction) return
    if (!canSpendAcorns(confirmAction.cost)) {
      setConfirmAction(null)
      return
    }
    if (confirmAction.type === 'nickname') {
      updateProfile({ ...profile, nickname: confirmAction.nickname, acorns: profile.acorns - confirmAction.cost })
      setMessage(`닉네임이 변경됐어요. 도토리 ${confirmAction.cost}개를 사용했습니다.`)
      setConfirmAction(null)
      return
    }

    const file = confirmAction.file
    const reader = new FileReader()
    reader.onload = () => {
      updateProfile({ ...profile, avatar: String(reader.result), acorns: profile.acorns - confirmAction.cost })
      setMessage(`프로필 사진이 변경됐어요. 도토리 ${confirmAction.cost}개를 사용했습니다.`)
      setConfirmAction(null)
    }
    reader.readAsDataURL(file)
  }

  const closeProfileConfirm = () => setConfirmAction(null)

  return (
    <main className="mypage">
      <div className="mypage-container">
        <section className="mypage-hero">
          <div className="profile-main">
            <div className="profile-avatar-frame">
              <div className="profile-avatar">
                {profile.avatar ? <img src={profile.avatar} alt="프로필" /> : <UserRound size={48} />}
              </div>
              <div className="profile-badge-chip" title={currentBadge.name} aria-label={`현재 뱃지: ${currentBadge.name}`}>
                <img src={currentBadge.image} alt="" />
              </div>
            </div>
            <div className="profile-copy">
              <span className="section-kicker">MY TUTORY</span>
              <div className="profile-name-row">
                <h1>{profile.nickname}</h1>
                <button className="profile-mini-button" type="button" onClick={saveNickname}>
                  <Pencil size={13} />
                  수정
                </button>
                <button className="profile-mini-button" type="button" onClick={() => fileInputRef.current?.click()}>
                  <ImageUp size={13} />
                  업로드
                </button>
              </div>
              <div className="profile-inline-edit">
                <input value={draftNickname} onChange={(event) => setDraftNickname(event.target.value)} aria-label="닉네임" />
                <span>변경 비용: 닉네임 도토리 {NICKNAME_COST}개 · 사진 도토리 {AVATAR_COST}개</span>
                <input ref={fileInputRef} type="file" accept="image/*" onChange={uploadAvatar} />
              </div>
              <p>도토리를 모아 뱃지를 성장시키고, 푼 문제 기록을 확인해보세요.</p>
              {message && <p className="profile-message">{message}</p>}
            </div>
          </div>
          <div className="acorn-wallet">
            <AcornIcon size={24} />
            <span>보유 도토리</span>
            <strong>{profile.acorns}</strong>
          </div>
        </section>

        <section className="mypage-panel badge-panel">
          <div className="mypage-panel-title">
            <Award size={17} />
            <strong>현재 뱃지 상태</strong>
          </div>
          <div className="current-badge">
            <div className="badge-mark">
              <img src={currentBadge.image} alt="" />
            </div>
            <div>
              <span>{currentBadge.name}</span>
              <p>{currentBadge.description}</p>
            </div>
          </div>
          <div className="badge-progress">
            <div>
              <span>누적 도토리</span>
              <strong>{profile.totalAcorns}</strong>
            </div>
            {nextBadge ? <small>다음: {nextBadge.name} ({nextBadge.minAcorns}개)</small> : <small>최고 뱃지 달성</small>}
            <div className="progress-track"><span style={{ width: `${progress}%` }} /></div>
          </div>
          <div className="badge-list">
            {BADGES.map((badge) => {
              const earned = profile.totalAcorns >= badge.minAcorns
              return (
                <div className={earned ? 'earned' : ''} key={badge.name}>
                  <img src={badge.image} alt="" />
                  <span>{badge.name}</span>
                  <small>{badge.minAcorns}개</small>
                  {earned && <BadgeCheck size={15} />}
                </div>
              )
            })}
          </div>
        </section>

        <section className="mypage-grid learning-grid">
          <div className="mypage-panel learning-card">
            <div className="mypage-panel-title">
              <CalendarDays size={17} />
              <strong>연속 학습일</strong>
            </div>
            <div className="learning-streak">
              <strong>{learningStreak.days}일</strong>
              <span>최고 기록 {learningStreak.bestDays}일</span>
              <p>{learningStreak.message}</p>
            </div>
          </div>

          <div className="mypage-panel learning-card">
            <div className="mypage-panel-title">
              <Lightbulb size={17} />
              <strong>최근 오답 힌트</strong>
            </div>
            <div className="wrong-hint">
              {recentWrongHint ? (
                <div className="wrong-hint-chat">
                  <img src={squirrelTutor} alt="" />
                  <div>
                    <span>{recentWrongHint.problemTitle}</span>
                    <p>{recentWrongHint.hint}</p>
                  </div>
                </div>
              ) : (
                <>
                  <span>최근 오답 기록 없음</span>
                  <p>틀린 실행이나 제출이 생기면 여기에서 가장 최근 힌트를 보여드릴게요.</p>
                </>
              )}
            </div>
          </div>
        </section>

        <section className="mypage-grid learning-history-grid">
          <div className="mypage-panel solved-panel">
            <div className="mypage-panel-title">
              <Clock3 size={17} />
              <strong>학습 중인 문제</strong>
            </div>
            <LearningProblemList problems={inProgressProblems} emptyMessage="임시저장한 문제가 아직 없어요." onSelect={onProblemSelect} />
          </div>
          <div className="mypage-panel solved-panel">
          <div className="mypage-panel-title">
            <Check size={17} />
              <strong>학습 완료한 문제</strong>
          </div>
            <LearningProblemList problems={completedProblems} emptyMessage="완료한 문제가 아직 없어요." onSelect={onProblemSelect} />
          </div>
        </section>
      </div>
      {confirmAction && (
        <div className="profile-confirm-backdrop" role="presentation" onMouseDown={closeProfileConfirm}>
          <div className="profile-confirm-modal" role="dialog" aria-modal="true" aria-labelledby="profile-confirm-title" onMouseDown={(event) => event.stopPropagation()}>
            <span className="profile-confirm-icon">
              <AcornIcon size={25} />
            </span>
            <span className="section-kicker">ACORN CHECK</span>
            <h2 id="profile-confirm-title">
              도토리 {confirmAction.cost}개를 사용해 {confirmAction.type === 'nickname' ? '닉네임을 수정' : '프로필 사진을 업로드'}하시겠습니까?
            </h2>
            <p>
              {confirmAction.type === 'nickname'
                ? `"${confirmAction.nickname}"으로 닉네임이 변경됩니다.`
                : `${confirmAction.file.name} 파일로 프로필 사진이 변경됩니다.`}
            </p>
            <div className="profile-confirm-wallet">
              <AcornIcon size={15} />
              <span>현재 보유 도토리 {profile.acorns}개</span>
            </div>
            <div className="profile-confirm-actions">
              <button className="modal-secondary-button" type="button" onClick={closeProfileConfirm}>아니요</button>
              <button className="modal-primary-button" type="button" onClick={confirmProfileAction}>네</button>
            </div>
          </div>
        </div>
      )}
    </main>
  )
}

function LearningProblemList({ problems, emptyMessage, onSelect }: { problems: LearningProgress[]; emptyMessage: string; onSelect?: (problemId: string) => void }) {
  const [page, setPage] = useState(1)
  const pageCount = Math.max(1, Math.ceil(problems.length / LEARNING_LIST_PAGE_SIZE))
  const currentPage = Math.min(page, pageCount)
  const visibleProblems = problems.slice((currentPage - 1) * LEARNING_LIST_PAGE_SIZE, currentPage * LEARNING_LIST_PAGE_SIZE)

  useEffect(() => {
    if (page !== currentPage) setPage(currentPage)
  }, [currentPage, page])

  if (!problems.length) return <p className="learning-history-empty">{emptyMessage}</p>
  return (
    <>
      <div className="solved-list">
        {visibleProblems.map((problem) => (
          <button className="solved-row" type="button" key={problem.problemId} onClick={() => onSelect?.(problem.problemId)}>
            <div><strong>{problem.title}</strong><span>{problem.problemId} · {formatLearningDate(problem.updatedAt)}</span></div>
            <small>{problem.status === 'COMPLETED' ? '학습 완료' : '이어 풀기'} <ChevronRight size={14} /></small>
          </button>
        ))}
      </div>
      {pageCount > 1 && (
        <div className="learning-pagination" aria-label="학습 기록 페이지">
          <button type="button" onClick={() => setPage((current) => Math.max(1, current - 1))} disabled={currentPage === 1}>이전</button>
          <span>{currentPage} / {pageCount}</span>
          <button type="button" onClick={() => setPage((current) => Math.min(pageCount, current + 1))} disabled={currentPage === pageCount}>다음</button>
        </div>
      )}
    </>
  )
}

function formatLearningDate(value: string) {
  return new Intl.DateTimeFormat('ko-KR', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(value))
}

function calculateLearningStreak(progress: LearningProgress[]) {
  const dayTimes = Array.from(new Set(progress.map((item) => toLearningDayTime(item.updatedAt)).filter((value): value is number => value !== null))).sort((a, b) => a - b)
  if (!dayTimes.length) {
    return { days: 0, bestDays: 0, message: '아직 학습 기록이 없어요. 오늘 한 문제부터 시작해볼까요?' }
  }

  let bestDays = 1
  let currentRun = 1
  for (let index = 1; index < dayTimes.length; index += 1) {
    if (dayTimes[index] - dayTimes[index - 1] === DAY_MS) {
      currentRun += 1
    } else {
      currentRun = 1
    }
    bestDays = Math.max(bestDays, currentRun)
  }

  const today = startOfTodayTime()
  const latest = dayTimes[dayTimes.length - 1]
  const canContinueToday = latest === today || latest === today - DAY_MS
  let days = 0
  if (canContinueToday) {
    days = 1
    for (let index = dayTimes.length - 1; index > 0; index -= 1) {
      if (dayTimes[index] - dayTimes[index - 1] !== DAY_MS) break
      days += 1
    }
  }

  return {
    days,
    bestDays,
    message: days > 0 ? '최근 학습 기록이 연속으로 이어지고 있어요.' : '오늘 학습하면 새로운 연속 기록을 시작할 수 있어요.',
  }
}

const DAY_MS = 24 * 60 * 60 * 1000

function startOfTodayTime() {
  const now = new Date()
  return new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
}

function toLearningDayTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()
}

function loadProfile() {
  const saved = localStorage.getItem(PROFILE_KEY)
  if (!saved) return DEFAULT_PROFILE
  try {
    return { ...DEFAULT_PROFILE, ...JSON.parse(saved) } as Profile
  } catch {
    return DEFAULT_PROFILE
  }
}

export default MyPage
