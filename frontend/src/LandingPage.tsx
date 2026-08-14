/**
 * 랜딩 페이지.
 *
 * 레퍼런스(Apple / Meta / Stripe)의 공통 문법을 따랐다: 큰 타이포 + 넉넉한 여백 +
 * 섹션 단위 스크롤 + 색을 아끼고 한 곳(브랜드 CTA)에만 쓰기. 반응형은
 * 모바일 우선이고, 폰트/여백은 미디어쿼리 대신 clamp()로 연속적으로 커진다.
 *
 * 히어로의 다람쥐(assets/squirrel-tutor-v2.png)가 이 페이지의 주인공이고,
 * 말풍선이 코딩 튜터 말투로 몇 문장을 돌아가며 보여준다.
 */
import { useEffect, useRef, useState } from 'react'
import { Activity, ArrowRight, GraduationCap, Lightbulb, LineChart, Waypoints } from 'lucide-react'
import squirrelTutor from './assets/squirrel-tutor-v2.png'

/** 말풍선 문구. "정답을 주지 않는다"는 서비스 원칙이 말투에도 드러나야 한다.
 *  줄바꿈(\n)은 .lp-bubble의 white-space: pre-line 이 그대로 렌더한다. */
const BUBBLE_LINES = [
  '반복문에서 막혔구나? \n 같이 한 줄씩 따라가 볼까? 🌰',
  '정답은 안 알려줄 거야. \n 대신 다음 한 걸음만 콕 짚어줄게!',
  '같은 오류가 세 번째야. \n 이쯤에서 같이 볼까?',
  '방금 그거 왜 통과했는지 설명해줄 수 있어? \n 궁금해!',
  '도토리 모으듯 실력도 한 알씩 모아보자.',
]

const BUBBLE_INTERVAL_MS = 4200

const FEATURES = [
  {
    icon: Activity,
    title: '막힌 순간을 먼저 알아챕니다',
    body:
      '편집·실행·제출을 초 단위로 기록해 같은 오류 반복, 같은 영역만 고치는 정체, 진전 없는 시간을 신호로 바꿉니다. 학생이 도움을 요청하지 않아도 개입 시점을 찾아냅니다.',
  },
  {
    icon: Lightbulb,
    title: '정답 대신 다음 한 걸음',
    body:
      'AI 튜터는 코드를 대신 써주지 않습니다. 지금 무엇을 확인해야 하는지 질문과 힌트로 되돌려주고, 필요할 때만 개념을 다시 설명합니다.',
  },
  {
    icon: Waypoints,
    title: '코드가 흘러가는 길을 눈으로',
    body:
      '한 줄씩 실행되는 순서와 변수 변화를 따라가는 트레이스 활동으로, 왜 그 결과가 나왔는지 스스로 설명할 수 있게 만듭니다.',
  },
  {
    icon: LineChart,
    title: '결과가 아니라 과정의 기록',
    body:
      '맞았는지 틀렸는지가 아니라 어떻게 도달했는지가 남습니다. 도토리와 배지로 꾸준함을 보상하고, 타임라인으로 성장을 되돌아봅니다.',
  },
]

const STEPS = [
  { no: '01', title: '문제를 고르고 코드를 씁니다', body: '브라우저에서 바로 실행됩니다. 설치할 것은 없습니다.' },
  { no: '02', title: '과정이 신호로 쌓입니다', body: '편집과 실행 결과가 정체·반복 실패 같은 신호로 요약됩니다.' },
  { no: '03', title: '막히면 튜터가 먼저 옵니다', body: '정답이 아니라 다음 한 걸음을 짚어주는 힌트와 활동이 도착합니다.' },
]

export default function LandingPage({
  onStart,
}: {
  /** 시작하기 버튼. 로그인 여부에 따라 회원가입/문제 목록으로 보내는 판단은 호출측(App)이 한다. */
  onStart: () => void
}) {
  const [lineIndex, setLineIndex] = useState(0)
  const reducedMotion = useRef(false)

  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    reducedMotion.current = media.matches
    if (media.matches) return // 움직임을 줄이기로 한 사용자에게는 문구를 고정한다.

    const timer = window.setInterval(() => {
      setLineIndex((prev) => (prev + 1) % BUBBLE_LINES.length)
    }, BUBBLE_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [])

  return (
    <main className="lp">
      <section className="lp-hero">
        <div className="lp-hero-copy">
          <p className="lp-eyebrow">AI CODING TUTOR</p>
          <h1 className="lp-title">
            <span className="lp-title-accent">막혔을 때</span>
            <br />
            먼저 다가오는
            <br /><span className="lp-title-brand">TUT</span><span className="lp-title-ink">ORY</span>
          </h1>
          <p className="lp-lede">
            정답을 알려주는 도구는 이미 많습니다. TUTORY는 학생이 코드를 쓰는 <strong>과정</strong>을 읽고,
            지금 필요한 만큼만 도와줍니다.
          </p>
          <div className="lp-cta-row">
            <button className="lp-btn lp-btn-primary" type="button" onClick={onStart}>
              시작하기
              <ArrowRight size={18} aria-hidden />
            </button>
          </div>
          <p className="lp-note">설치 없이 브라우저에서 바로 실행됩니다.</p>
        </div>

        <div className="lp-hero-visual">
          <div className="lp-glow" aria-hidden />
          <div className="lp-bubble" aria-live="off">
            <span key={lineIndex} className="lp-bubble-text">
              {BUBBLE_LINES[lineIndex]}
            </span>
          </div>
          <img
            className="lp-squirrel"
            src={squirrelTutor}
            alt="도토리를 든 다람쥐 튜터 캐릭터"
            width={1236}
            height={1272}
            loading="eager"
            decoding="async"
          />
        </div>
      </section>

      <section className="lp-section" aria-labelledby="lp-features-title">
        <p className="lp-kicker">왜 다른가</p>
        <h2 className="lp-h2" id="lp-features-title">
          결과가 아니라 과정을 봅니다
        </h2>
        <div className="lp-grid">
          {FEATURES.map(({ icon: Icon, title, body }) => (
            <article className="lp-card" key={title}>
              <span className="lp-card-icon" aria-hidden>
                <Icon size={22} />
              </span>
              <h3 className="lp-card-title">{title}</h3>
              <p className="lp-card-body">{body}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="lp-section lp-section-soft" aria-labelledby="lp-steps-title">
        <p className="lp-kicker">어떻게 동작하나</p>
        <h2 className="lp-h2" id="lp-steps-title">
          세 단계면 충분합니다
        </h2>
        <ol className="lp-steps">
          {STEPS.map(({ no, title, body }) => (
            <li className="lp-step" key={no}>
              <span className="lp-step-no">{no}</span>
              <h3 className="lp-step-title">{title}</h3>
              <p className="lp-step-body">{body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="lp-section lp-educator" aria-labelledby="lp-educator-title">
        <div className="lp-educator-inner">
          <span className="lp-card-icon" aria-hidden>
            <GraduationCap size={22} />
          </span>
          <h2 className="lp-h2" id="lp-educator-title">
            가르치는 사람에게는 반 전체의 과정이 보입니다
          </h2>
          <p className="lp-lede">
            누가 어디서 막혀 있는지, 어떤 개념에서 반복해서 넘어지는지 한 화면에 모입니다. 코드 열람 범위는
            강의별로 교수자가 정합니다.
          </p>
        </div>
      </section>

      <section className="lp-final">
        <h2 className="lp-h2">오늘 한 문제부터 시작해볼까요?</h2>
        <div className="lp-cta-row lp-cta-center">
          <button className="lp-btn lp-btn-primary" type="button" onClick={onStart}>
            시작하기
            <ArrowRight size={18} aria-hidden />
          </button>
        </div>
      </section>

      <footer className="lp-footer">
        <p>TUTORY · 강원대 x 고려대 Summer Agentic AI 캠프 4팀</p>
      </footer>
    </main>
  )
}
