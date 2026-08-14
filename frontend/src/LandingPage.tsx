/**
 * 랜딩 페이지.
 *
 * 레퍼런스(Apple / Meta / Stripe)의 공통 문법을 따랐다: 큰 타이포 + 넉넉한 여백 +
 * 섹션 단위 스크롤 + 색을 아끼고 한 곳(브랜드 CTA)에만 쓰기. 반응형은
 * 모바일 우선이고, 폰트/여백은 미디어쿼리 대신 clamp()로 연속적으로 커진다.
 *
 * 히어로의 다람쥐(assets/squirrel-tutor-v2.png)가 이 페이지의 주인공이고,
 * 말풍선이 코딩 튜터 말투로 몇 문장을 돌아가며 보여준다.
 *
 * 스크롤에 반응하는 두 가지 장치:
 *  1. useReveal -- 섹션/카드가 뷰포트에 들어오면 한 번만 페이드+슬라이드업.
 *     (다시 스크롤을 올려도 안 사라진다 -- 깜빡임은 세련돼 보이지 않는다.)
 *  2. ScrollSquirrel -- 화면 오른쪽 가장자리를 다람쥐가 스크롤 진행률만큼 내려온다.
 *     "스크롤할 때마다 뭔가 움직인다"는 인상을 페이지 전체에 걸쳐 준다.
 * 둘 다 prefers-reduced-motion을 존중한다 (모션을 줄이기로 한 사용자에겐 그냥 보여준다).
 */
import { Fragment, useEffect, useRef, useState, type CSSProperties, type ReactNode, type Ref } from 'react'
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
    title: [
      '막힌 순간을',
      '먼저 알아챕니다'
    ],
    body: [
      '편집·실행·제출을 초 단위로',
      '기록해 신호로 바꿉니다.',
      '학생이 도움을 요청하지 않아도 개입 시점을 찾아냅니다.',
    ],
  },
  {
    icon: Lightbulb,
    title: [
      '정답 대신',
      '다음 한 걸음',
    ],
    body: [
      '코드를 대신 써주지 않습니다.',
      '지금 무엇을 확인해야 하는지 질문과 힌트로 되돌려주고,',
      '필요할 때 개념을 설명합니다.',
    ],
  },
  {
    icon: Waypoints,
    title: '코드가 흘러가는 길을 눈으로',
    body: [
      '실행 순서와 변수 변화를 따라가는 트레이스 활동으로,',
      '왜 그 결과가 나왔는지 스스로 설명할 수 있게 만듭니다.',
    ],
  },
  {
    icon: LineChart,
    title: [
      '결과가 아니라',
      '과정의 기록',
    ],
    body: [
      '맞았는지 틀렸는지가 아니라',
      '어떻게 도달했는지가 남습니다.',
      '도토리로 꾸준함을 보상하고, 성장 과정을 기록합니다.',
    ],
  },
]

const STEPS = [
  { no: '01', title: '문제를 고르고 코드를 씁니다', body: ['브라우저에서 바로 실행됩니다.', '설치할 것은 없습니다.'] },
  { no: '02', title: '과정이 신호로 쌓입니다', body: ['편집과 실행 결과가', '정체·반복 실패 같은 신호로 요약됩니다.'] },
  { no: '03', title: '막히면 튜터가 먼저 옵니다', body: ['정답이 아니라 다음 한 걸음을 짚어주는', '힌트와 활동이 도착합니다.'] },
]

/** 교육자 대시보드 실제 화면(반 전체 진행률 + 막힌 학생 표시)의 축소 미리보기.
 *  실제 지표가 아니라 연출용 예시다 -- 오른쪽을 비워두는 대신 "무엇이 보이는지"를
 *  그림으로 먼저 보여준다. */
const EDUCATOR_PREVIEW = [
  { name: '이OO', tag: '순항 중', percent: 82, stuck: false },
  { name: '박OO', tag: '같은 오류 3회째', percent: 34, stuck: true },
  { name: '김OO', tag: '막 시작함', percent: 12, stuck: false },
]

/**
 * 뷰포트에 한 번 들어오면 visible=true로 고정한다.
 *
 * 스크롤을 올렸다 내렸다 할 때마다 카드가 사라졌다 나타나면 산만하고 "리액트가
 * 자꾸 리렌더한다"는 인상을 준다 -- observer.disconnect()로 최초 1회만 반응한다.
 * 모션을 줄이기로 한 사용자(prefers-reduced-motion)에게는 애니메이션 없이 바로 보여준다.
 */
function useReveal<T extends HTMLElement>() {
  const ref = useRef<T | null>(null)
  const [reduced] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches)
  const [visible, setVisible] = useState(reduced)

  useEffect(() => {
    if (reduced) return
    const el = ref.current
    if (!el) return
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return
        setVisible(true)
        observer.disconnect()
      },
      { threshold: 0.2, rootMargin: '0px 0px -10% 0px' },
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [reduced])

  return { ref, visible }
}

/** 스크롤 진행률(0~1)을 rAF로 쓰로틀링해서 준다. 넓은 화면에서만 쓰인다(CSS로 숨김). */
function useScrollProgress() {
  const [progress, setProgress] = useState(0)
  useEffect(() => {
    let raf = 0
    const update = () => {
      const max = document.documentElement.scrollHeight - window.innerHeight
      setProgress(max > 0 ? Math.min(1, Math.max(0, window.scrollY / max)) : 0)
    }
    const onScroll = () => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(update)
    }
    update()
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    return () => {
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
      cancelAnimationFrame(raf)
    }
  }, [])
  return progress
}

/** 화면 오른쪽 가장자리를 다람쥐가 스크롤한 만큼 내려온다 -- "스크롤할 때마다 움직임"을
 *  페이지 전체에 걸쳐 준다. 모션을 줄이기로 한 사용자에게는 아예 렌더하지 않는다. */
function ScrollSquirrel() {
  const [reduced] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches)
  const progress = useScrollProgress()
  if (reduced) return null
  return (
    <div className="lp-scroll-guide" aria-hidden>
      <span className="lp-scroll-track">
        <img
          className="lp-scroll-marker"
          src={squirrelTutor}
          alt=""
          style={{ '--progress': progress } as CSSProperties}
        />
      </span>
    </div>
  )
}

/** "결과가 아니라 과정을 봅니다"처럼, 문장을 한 단어씩 순서대로 떠오르게 한다
 *  (Apple 스타일 스크롤 리빌). 뷰포트에 들어온 뒤에는 CSS transition-delay가
 *  단어 인덱스만큼 밀려서 한 단어씩 나타나는 것처럼 보인다. */
function RevealHeading({ text, id }: { text: string; id?: string }) {
  const { ref, visible } = useReveal<HTMLHeadingElement>()
  const words = text.split(' ')
  return (
    <h2 className="lp-h2 lp-word-heading" id={id} ref={ref}>
      {words.map((word, i) => (
        // 공백을 span **밖**에 형제 텍스트 노드로 둔다 -- inline-block 안쪽 끝에 오는
        // 공백은 브라우저가 줄바꿈 트리밍 규칙으로 폭 0으로 접어버려서, span
        // 안에 넣으면 단어가 전부 붙어 렌더된다.
        <Fragment key={`${word}-${i}`}>
          <span className="lp-word" data-visible={visible} style={{ '--i': i } as CSSProperties}>
            {word}
          </span>
          {i < words.length - 1 ? ' ' : ''}
        </Fragment>
      ))}
    </h2>
  )
}

type Feature = (typeof FEATURES)[number]

function RevealCard({ icon: Icon, title, body, index }: Feature & { index: number }) {
  const { ref, visible } = useReveal<HTMLElement>()
  return (
    <article
      className="lp-card lp-reveal"
      data-visible={visible}
      ref={ref}
      style={{ '--reveal-i': index } as CSSProperties}
    >
      <span className="lp-card-icon" aria-hidden>
        <Icon size={22} />
      </span>
      <h3 className="lp-card-title">
        {Array.isArray(title) ? title.map((line) => <span key={line}>{line}</span>) : title}
      </h3>
      <p className="lp-card-body">{body.map((line) => <span key={line}>{line}</span>)}</p>
    </article>
  )
}

type Step = (typeof STEPS)[number]

function RevealStep({ no, title, body, index }: Step & { index: number }) {
  const { ref, visible } = useReveal<HTMLLIElement>()
  return (
    <li
      className="lp-step lp-reveal"
      data-visible={visible}
      ref={ref}
      style={{ '--reveal-i': index } as CSSProperties}
    >
      <span className="lp-step-no">{no}</span>
      <h3 className="lp-step-title">{title}</h3>
      <p className="lp-step-body">{body.map((line) => <span key={line}>{line}</span>)}</p>
    </li>
  )
}

function RevealMockRow({ name, tag, percent, stuck, index }: (typeof EDUCATOR_PREVIEW)[number] & { index: number }) {
  const { ref, visible } = useReveal<HTMLDivElement>()
  return (
    <div
      className="lp-mock-row lp-reveal"
      data-stuck={stuck}
      data-visible={visible}
      ref={ref}
      style={{ '--reveal-i': index } as CSSProperties}
    >
      <span className="lp-mock-avatar">{name.charAt(0)}</span>
      <div className="lp-mock-info">
        <strong>{name}</strong>
        <div className="lp-mock-progress">
          <i style={{ width: `${percent}%` }} />
        </div>
      </div>
      <span className="lp-mock-tag">
        {stuck && <span className="lp-mock-dot" aria-hidden />}
        {tag}
      </span>
    </div>
  )
}

/** 섹션 하나를 한 덩어리로 페이드+슬라이드업 시키고 싶을 때 쓰는 얕은 래퍼.
 *  (단어 단위 RevealHeading, 카드 단위 RevealCard와 달리 "블록" 단위 리빌.)
 *  div/section 둘 다 HTMLElement라 useReveal 하나로 충분하다. */
function RevealBlock({
  as: Tag = 'div',
  className,
  children,
}: {
  as?: 'div' | 'section'
  className?: string
  children: ReactNode
}) {
  const { ref, visible } = useReveal<HTMLElement>()
  return (
    <Tag className={`${className ?? ''} lp-reveal`.trim()} data-visible={visible} ref={ref as Ref<HTMLDivElement>}>
      {children}
    </Tag>
  )
}

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
      <ScrollSquirrel />

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
            <span>정답을 알려주는 도구는 이미 많습니다.</span>
            <span>TUTORY는 학생이 코드를 쓰는 <strong>과정</strong>을 읽고,</span>
            <span>지금 필요한 만큼만 도와줍니다.</span>
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
        <RevealHeading text="결과가 아니라 과정을 봅니다" id="lp-features-title" />
        <div className="lp-grid">
          {FEATURES.map((feature, i) => (
            <RevealCard key={Array.isArray(feature.title) ? feature.title.join(' ') : feature.title} index={i} {...feature} />
          ))}
        </div>
      </section>

      <section className="lp-section lp-section-soft lp-steps-section" aria-labelledby="lp-steps-title">
        <div className="lp-steps-inner">
          <p className="lp-kicker">어떻게 동작하나</p>
          <h2 className="lp-h2" id="lp-steps-title">
            세 단계면 충분합니다
          </h2>
          <ol className="lp-steps">
            {STEPS.map((step, i) => (
              <RevealStep key={step.no} index={i} {...step} />
            ))}
          </ol>
        </div>
      </section>

      <section className="lp-section lp-educator" aria-labelledby="lp-educator-title">
        <div className="lp-educator-grid">
          <RevealBlock className="lp-educator-inner">
            <span className="lp-card-icon" aria-hidden>
              <GraduationCap size={22} />
            </span>
            <h2 className="lp-h2" id="lp-educator-title">
              가르치는 사람에게는
              <br />
              반 전체의 과정이 보입니다
            </h2>
            <p className="lp-lede">
              <span>누가 어디서 막혀 있는지,</span>
              <span>어떤 개념에서 반복해서 넘어지는지 한 화면에 모입니다.</span>
              <span>코드 열람 범위는 강의별로 교수자가 정합니다.</span>
            </p>
          </RevealBlock>

          <div className="lp-mock-panel" aria-hidden>
            <div className="lp-mock-panel-head">
              <span>Python 기초 01 · 오늘</span>
            </div>
            {EDUCATOR_PREVIEW.map((row, i) => (
              <RevealMockRow key={row.name} index={i} {...row} />
            ))}
          </div>
        </div>
      </section>

      <RevealBlock as="section" className="lp-final">
        <h2 className="lp-h2">오늘 한 문제부터 시작해볼까요?</h2>
        <div className="lp-cta-row lp-cta-center">
          <button className="lp-btn lp-btn-primary" type="button" onClick={onStart}>
            시작하기
            <ArrowRight size={18} aria-hidden />
          </button>
        </div>
      </RevealBlock>

      <footer className="lp-footer">
        <p>TUTORY · 강원대 x 고려대 Summer Agentic AI 캠프 4팀</p>
      </footer>
    </main>
  )
}
