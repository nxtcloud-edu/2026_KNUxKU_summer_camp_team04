import { useMemo, useRef, useState } from 'react'
import {
  Award,
  BadgeCheck,
  Camera,
  Check,
  Coins,
  ImageUp,
  Pencil,
  Trophy,
  UserRound,
} from 'lucide-react'

type Profile = {
  nickname: string
  avatar: string
  acorns: number
  totalAcorns: number
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

const BADGES = [
  { name: '씨앗 뱃지', minAcorns: 0, description: '첫 문제 풀이를 시작한 학습자' },
  { name: '새싹 뱃지', minAcorns: 50, description: '꾸준히 기초 문제를 풀고 있어요' },
  { name: '묘목 뱃지', minAcorns: 150, description: '함수와 조건문에 익숙해졌어요' },
  { name: '참나무 뱃지', minAcorns: 300, description: '문제 해결 루틴이 단단해졌어요' },
  { name: '숲지기 뱃지', minAcorns: 600, description: '고난도 문제에도 침착한 학습자' },
  { name: '전설의 도토리', minAcorns: 1000, description: '튜토리 최고 레벨 학습자' },
]

function MyPage() {
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

  const uploadAvatar = (event: React.ChangeEvent<HTMLInputElement>) => {
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
            <div className="profile-avatar">
              {profile.avatar ? <img src={profile.avatar} alt="프로필" /> : <UserRound size={48} />}
            </div>
            <div>
              <span className="section-kicker">MY TUTORY</span>
              <h1>{profile.nickname}</h1>
              <p>도토리를 모아 뱃지를 성장시키고, 푼 문제 기록을 확인해보세요.</p>
            </div>
          </div>
          <div className="acorn-wallet">
            <Coins size={22} />
            <span>보유 도토리</span>
            <strong>{profile.acorns}</strong>
          </div>
        </section>

        <section className="mypage-grid">
          <div className="mypage-panel profile-editor">
            <div className="mypage-panel-title">
              <Pencil size={17} />
              <strong>프로필 수정</strong>
            </div>
            <label className="mypage-field">
              <span>닉네임</span>
              <div>
                <input value={draftNickname} onChange={(event) => setDraftNickname(event.target.value)} />
                <button type="button" onClick={saveNickname}>수정</button>
              </div>
              <small>닉네임 변경 시 도토리 {NICKNAME_COST}개가 필요합니다.</small>
            </label>

            <div className="profile-upload-row">
              <button type="button" onClick={() => fileInputRef.current?.click()}>
                <ImageUp size={16} />
                프로필 사진 업로드
              </button>
              <span>등록 및 변경 시 도토리 {AVATAR_COST}개</span>
              <input ref={fileInputRef} type="file" accept="image/*" onChange={uploadAvatar} />
            </div>

            {message && <p className="profile-message">{message}</p>}
          </div>

          <div className="mypage-panel badge-panel">
            <div className="mypage-panel-title">
              <Award size={17} />
              <strong>현재 뱃지 상태</strong>
            </div>
            <div className="current-badge">
              <div className="badge-mark"><Trophy size={30} /></div>
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
              {BADGES.map((badge) => (
                <div className={profile.totalAcorns >= badge.minAcorns ? 'earned' : ''} key={badge.name}>
                  <BadgeCheck size={15} />
                  <span>{badge.name}</span>
                  <small>{badge.minAcorns}개</small>
                </div>
              ))}
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

        <section className="mypage-panel recommendation-panel">
          <div className="mypage-panel-title">
            <Camera size={17} />
            <strong>추가하면 좋은 기능</strong>
          </div>
          <div className="recommendation-list">
            <span>연속 학습일</span>
            <span>최근 오답 노트</span>
            <span>선호 문제 유형</span>
            <span>다음 추천 문제</span>
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
