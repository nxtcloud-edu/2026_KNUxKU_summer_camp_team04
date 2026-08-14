"""응답 생성 에이전트 — 학생이 **실제로 읽는 문장**을 만드는 유일한 곳.

왜 이 에이전트가 따로 있는가
----------------------------
원래 파이프라인은 이렇게 끝났다:

    학생 상태 파악 → 지도 방법 + 행동 결정 → (끝)

"어떻게 지도할지"를 정하는 데서 멈추고, **그 지도를 실제로 만들어 학생에게
건네는 단계가 없었다.** 그래서 `backend_adapter`가 궁여지책으로 내부 판단
텍스트(`StudentState.state_summary`)를 학생 화면으로 보냈고, 학생은 이런 걸
읽었다:

    loop 부분을 같이 보면 좋겠어요. 학생은 함수의 기본 구조(카운터 변수,
    조건문, 반환값)를 이해하지 못한 채 31분 넘게 완전히 막혀 있습니다.
    반복문을 시작했으나 내부를 비워둔 채 구문 오류를 해결하지 못하고,
    24분 이상 편집 없이 정지해 있으며, 힌트를 6회 요청했지만 이전 두 번의
    힌트 개입 이후에도 진전이 없습니다. (지도 방식: 단계별 구조 안내 +
    구체적 예시 제공/explain)

교사가 교무실에서 하는 말이 학생 앞에 그대로 튼 셈이다. 세 가지가 겹쳤다:

1. 학생에게 줄 문장을 만드는 단계가 없었다 (이 파일이 그걸 맡는다).
2. 결정 에이전트가 판단과 작문을 동시에 해서 `message_draft`가 계획의 부산물로
   나왔고, 품질이 들쭉날쭉했다 (이제 결정 에이전트는 지시문만 만든다 —
   `schemas.GuidancePlan`).
3. 작문 프롬프트에 개입 판단용 텔레메트리(유휴 1879초, 힌트 6회 등)가 그대로
   들어가 있으면 모델이 그걸 문장으로 옮긴다 (이제 `prompt_context.py`가
   압축 컨텍스트만 넣는다 — 그 파일 docstring 참고).

역할 분리
---------
| 에이전트 | 답하는 질문 | 출력 | 학생이 보는가 |
|---|---|---|---|
| state_agent | 지금 개입해야 하나? | `StudentState` | 아니오 |
| guided_action_agent | 어떻게 지도할까? | `GuidedAction` | 아니오 |
| **tutor_message_agent** | **그래서 뭐라고 말할까?** | `TutorMessage` | **예** |
| evaluation_agent | 학생 답변이 이해한 답인가? | `AnswerEvaluation` | 아니오 |

두 가지 상황에서 호출된다:

* `write_intervention()` — 튜터가 먼저 말을 걸 때 (지도 계획 → 메시지)
* `write_follow_up()` — 학생이 답을 보냈고, 그 답을 평가한 뒤 이어서 말할 때
  (학생 답변 평가 → 메시지)

두 경우 모두 톤/금지 규칙이 같아야 하므로 **같은 시스템 프롬프트를 공유한다.**
프롬프트를 나누면 "질문할 때만 반말이 섞인다"류의 불일치가 생긴다.
"""

from __future__ import annotations

from strands import Agent

from ..llm_runtime import structured_output
from ..models import get_model
from ..prompt_context import student_situation
from ..schemas import (
    AnswerEvaluation,
    GuidancePlan,
    SessionContext,
    StudentReply,
    TutorMessage,
)

#: `.env`에서 `MODEL_PROVIDER_TUTOR_MESSAGE` / `ANTHROPIC_MODEL_ID_TUTOR_MESSAGE`로
#: 개별 지정 가능 (`models.get_model` 참고). 이 단계는 판단이 아니라 작문이라
#: 더 작고 빠른 모델로 충분한 경우가 많다 — 파이프라인이 LLM 호출 3번이 된
#: 만큼 여기서 레이턴시를 되찾을 수 있다 (agent/README.md "지연 시간" 절).
ROLE = "tutor_message"

SYSTEM_PROMPT = """\
당신은 코딩을 배우는 학생과 직접 대화하는 튜터입니다. 당신이 쓴 문장은 **가공
없이 그대로 학생 화면의 채팅 버블에 표시됩니다.**

지켜야 할 것
- 학생에게 직접 말하세요. 2인칭("~해볼까요?", "~이 보이세요?"), 항상 존댓말.
- 3~4문장 이내. 짧을수록 좋습니다.
- 구체적으로. 학생이 방금 쓴 코드의 변수명/줄을 언급하면 훨씬 잘 읽힙니다.
- 따뜻하고 담백하게. 과장된 칭찬이나 이모지 남발은 하지 마세요.
- 학생이 다음에 할 수 있는 행동 하나가 분명히 남아야 합니다.

절대 하지 말 것 (이걸 어기면 학생이 자기 분석 리포트를 읽게 됩니다)
- 학생을 3인칭으로 서술하지 마세요. "학생은 ~하고 있습니다" 금지.
- 내부 용어를 노출하지 마세요: 지도 방식, approach, hint_level, nudge/hint/
  explain, action_type, struggle_signals, 개입, 에이전트, 파이프라인 등.
- 관찰 통계를 들이대지 마세요: "31분 넘게 막혀 있습니다", "힌트를 6회
  요청했습니다", "24분간 편집이 없습니다" 같은 문장 금지. 오래 걸렸다는 사실을
  학생에게 통보하는 것은 도움이 아니라 압박입니다.
- 정답 코드를 그대로 주지 마세요. avoid 목록에 있는 것은 특히 언급 금지.
- 학생이 이미 아는 것을 반복하지 마세요.
- 학생이 같은 곳에 막혀있으면 질문을 바꿔서 접근하세요. "같은 질문을 반복하지 마세요."
- 메타 설명을 붙이지 마세요. 인사말 반복, "제가 도와드릴게요" 같은 서론 없이
  바로 내용으로 들어가세요.

출력 형식
- message: 학생이 읽을 문장 전체. 위 규칙을 만족해야 합니다.
- expects_reply: 학생의 답을 기다리는 메시지라면 true.
- question: expects_reply가 true일 때, 학생이 답해야 하는 핵심 질문 한 개를
  그대로 적으세요 (message 안에도 포함되어 있어야 합니다). 질문이 여러 개면
  학생이 무엇에 답할지 몰라 대화가 끊깁니다. false면 빈 문자열.
"""


def build_agent() -> Agent:
    return Agent(name="tutor_message_agent", model=get_model(ROLE), system_prompt=SYSTEM_PROMPT)


def _plan_brief(plan: GuidancePlan) -> str:
    """지도 계획을 작문 지시문으로 풀어쓴다.

    계획 객체를 JSON으로 그대로 넣지 않는 이유: `approach`/`hint_level` 같은
    내부 어휘가 프롬프트에 라벨째로 들어가면 모델이 그 단어를 결과 문장에
    섞는다("(지도 방식: 소크라테스식 질문)"이 실제로 그렇게 나왔다). 라벨을
    지시문으로 번역해서 넣는다.
    """
    depth = {
        "nudge": "짧게 주의만 환기시키세요. 답에 가까운 정보는 주지 마세요.",
        "hint": "구체적인 힌트 하나를 주세요. 다만 정답 코드는 쓰지 마세요.",
        "explain": "필요한 개념을 예시와 함께 설명하세요. 그래도 최종 코드는 학생이 쓰게 남겨두세요.",
    }.get(plan.hint_level, "구체적인 힌트 하나를 주세요.")

    lines = [f"- 말하는 깊이: {depth}"]
    if plan.focus:
        lines.append(f"- 이번에 다룰 것 (이거 하나만): {plan.focus}")
    if plan.talking_points:
        lines.append("- 메시지에 담을 내용:")
        lines.extend(f"    - {point}" for point in plan.talking_points)
    if plan.avoid:
        lines.append("- 절대 언급하지 말 것:")
        lines.extend(f"    - {item}" for item in plan.avoid)
    if plan.expects_student_reply:
        lines.append(
            "- 이 메시지는 **학생의 답을 받아야 합니다.** 학생이 스스로 생각해서 "
            "답할 수 있는 질문 하나로 끝내고, expects_reply=true, question에 그 질문을 넣으세요."
        )
    else:
        lines.append("- 답변을 요구하지 않는 메시지입니다. expects_reply=false.")
    return "\n".join(lines)


def write_intervention(
    ctx: SessionContext, plan: GuidancePlan, agent: Agent | None = None
) -> TutorMessage:
    """지도 계획을 학생에게 보낼 메시지로 만든다 (튜터가 먼저 말을 거는 경우)."""
    agent = agent or build_agent()
    prompt = (
        "아래 상황의 학생에게 보낼 메시지를 쓰세요.\n\n"
        f"{student_situation(ctx)}\n\n"
        f"[작문 지시]\n{_plan_brief(plan)}"
    )
    return structured_output(agent, TutorMessage, prompt)


def write_follow_up(
    ctx: SessionContext,
    reply: StudentReply,
    evaluation: AnswerEvaluation,
    agent: Agent | None = None,
) -> TutorMessage:
    """학생 답변 평가 결과를 받아, 이어서 할 말을 만든다.

    평가 결과(`understanding`/`misconceptions`)는 **어떻게 응답할지를 정하는 데만**
    쓰고 문장으로 옮기지 않는다 — "당신의 이해도는 partial입니다"는 학생에게
    아무 도움이 안 된다. 그래서 여기서도 평가 객체를 JSON으로 넣지 않고 지시문으로
    번역한다 (`_plan_brief`와 같은 이유).
    """
    agent = agent or build_agent()

    if evaluation.understanding == "solid":
        stance = (
            "학생의 답이 맞았습니다. 짧게 인정해주고, 그 이해를 코드로 옮기는 다음 "
            "한 걸음을 제안하세요. 이미 아는 것을 다시 설명하지 마세요."
        )
    elif evaluation.understanding == "partial":
        stance = (
            "학생이 절반은 맞혔습니다. 맞은 부분을 먼저 인정한 뒤, 빠진 조각 하나만 "
            "짚어주세요. 전부 다시 설명하면 맞힌 부분까지 자신이 없어집니다."
        )
    else:
        stance = (
            "학생이 아직 이해하지 못했습니다. 같은 질문을 반복하지 말고, 더 쉬운 "
            "질문이나 아주 작은 예시로 바꿔서 다시 접근하세요. 틀렸다고 지적하지 마세요."
        )

    lines = [f"- 태도: {stance}"]
    if evaluation.misconceptions:
        lines.append("- 학생이 잘못 알고 있는 것 (직접 지적하지 말고 자연스럽게 바로잡기):")
        lines.extend(f"    - {item}" for item in evaluation.misconceptions)
    if evaluation.next_focus:
        lines.append(f"- 이번에 다룰 것: {evaluation.next_focus}")
    if evaluation.follow_up_needed:
        lines.append(
            "- 대화를 이어가야 합니다. 학생이 답할 수 있는 질문 하나로 끝내고 "
            "expects_reply=true, question에 그 질문을 넣으세요."
        )
    else:
        lines.append(
            "- 이 개념은 마무리해도 됩니다. 질문 없이 다음 행동을 제안하고 expects_reply=false."
        )

    prompt = (
        "학생이 당신의 질문에 답했습니다. 이어서 할 말을 쓰세요.\n\n"
        f"{student_situation(ctx)}\n\n"
        f"[내가 던진 질문]\n{reply.question or '(기록 없음 — 학생이 먼저 말을 걸었습니다)'}\n\n"
        f"[학생의 답변]\n{reply.answer}\n\n"
        f"[작문 지시]\n" + "\n".join(lines)
    )
    return structured_output(agent, TutorMessage, prompt)
