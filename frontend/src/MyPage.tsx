import { useMemo, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import {
  Award,
  BadgeCheck,
  CalendarDays,
  Check,
  Coins,
  ImageUp,
  Lightbulb,
  Pencil,
  UserRound,
} from 'lucide-react'
import badgeSeed from './assets/badges/badge-seed.png'
import badgeSprout from './assets/badges/badge-sprout.png'
import badgeSapling from './assets/badges/badge-sapling.png'
import badgeOak from './assets/badges/badge-oak.png'
import badgeGuardian from './assets/badges/badge-guardian.png'
import badgeLegend from './assets/badges/badge-legend.png'

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
}

const PROFILE_KEY = 'tutory:profile'
const NICKNAME_COST = 5
const AVATAR_COST = 10

const DEFAULT_PROFILE: Profile = {
  nickname: '튜토리 학습자',
  avatar: '',
  acorns: 135,
  totalAcorns: 260,
}

const SOLVED_PROBLEMS = [
  { id: 'func_sum_list', title: '리스트 합 구하기', date: '2026.08.13', acorns: 15 },
  { id: 'sum_even', title: '짝수의 합 구하기', date: '2026.08.12', acorns: 12 },
  { id: 'string_reverse', title: '문자열 뒤집기', date: '2026.08.11', acorns: 10 },
  { id: 'count_vowels', title: '모음 개수 세기', date: '2026.08.10', acorns: 8 },
]

const BADGES: Badge[] = [
  { name: '씨앗 뱃지', minAcorns: 0, description: '첫 문제 풀이를 시작한 학습자', image: badgeSeed },
  { name: '새싹 뱃지', minAcorns: 50, description: '꾸준히 기초 문제를 풀고 있어요', image: badgeSprout },
  { name: '묘목 뱃지', minAcorns: 150, description: '함수와 조건문에 익숙해졌어요', image: badgeSapling },
  { name: '참나무 뱃지', minAcorns: 300, description: '문제 해결 루틴이 단단해졌어요', image: badgeOak },
  { name: '숲지기 뱃지', minAcorns: 600, description: '고난도 문제에도 침착한 학습자', image: badgeGuardian },
  { name: '전설의 도토리', minAcorns: 1000, description: '튜토리 최고 레벨 학습자', image: badgeLegend },
]

const LEARNING_STREAK = {
  days: 4,
  bestDays: 9,
  message: '이번 주도 꾸준히 문제를 풀고 있어요.',
}

const RECENT_WRONG_HINT = {
  problemTitle: '짝수의 합 구하기',
  hint: '반복문에서 더하기 전에 짝수인지 먼저 확인해보세요.',
}

function MyPage({ onAvatarChange }: MyPageProps) {
  const [profile, setProfile] = useState<Profile>(() => loadProfile())
  const [draftNickname, setDraftNickname] = useState(profile.nickname)
  const [message, setMessage] = useState('')
  const fileInputRef = useRef<HTMLInputElement | null>(null)

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
    updateProfile({ ...profile, nickname: nextNickname, acorns: profile.acorns - NICKNAME_COST })
    setMessage(`닉네임이 변경됐어요. 도토리 ${NICKNAME_COST}개를 사용했습니다.`)
  }

  const uploadAvatar = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return
    if (!canSpendAcorns(AVATAR_COST)) {
      event.target.value = ''
      return
    }

    const reader = new FileReader()
    reader.onload = () => {
      updateProfile({ ...profile, avatar: String(reader.result), acorns: profile.acorns - AVATAR_COST })
      setMessage(`프로필 사진이 변경됐어요. 도토리 ${AVATAR_COST}개를 사용했습니다.`)
      event.target.value = ''
    }
    reader.readAsDataURL(file)
  }

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
            <Coins size={22} />
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
              <strong>{LEARNING_STREAK.days}일</strong>
              <span>최고 기록 {LEARNING_STREAK.bestDays}일</span>
              <p>{LEARNING_STREAK.message}</p>
            </div>
          </div>

          <div className="mypage-panel learning-card">
            <div className="mypage-panel-title">
              <Lightbulb size={17} />
              <strong>최근 오답 힌트</strong>
            </div>
            <div className="wrong-hint">
              <span>{RECENT_WRONG_HINT.problemTitle}</span>
              <p>{RECENT_WRONG_HINT.hint}</p>
            </div>
          </div>
        </section>

        <section className="mypage-panel solved-panel">
          <div className="mypage-panel-title">
            <Check size={17} />
            <strong>내가 푼 문제</strong>
          </div>
          <div className="solved-list">
            {SOLVED_PROBLEMS.map((problem) => (
              <div className="solved-row" key={problem.id}>
                <div>
                  <strong>{problem.title}</strong>
                  <span>{problem.id} · {problem.date}</span>
                </div>
                <small>+{problem.acorns} 도토리</small>
              </div>
            ))}
          </div>
        </section>
      </div>
    </main>
  )
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
