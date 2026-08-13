"""개입 시 어떻게 지도할지 결정하는 에이전트.

`state_agent`가 개입이 필요하다고 판단했을 때만 호출된다. 무엇을 가르칠지가
아니라 '어떤 방식으로' 가르칠지(직접 힌트 vs 질문 유도 등)를 결정한다.
"""

from __future__ import annotations

from strands import Agent

from ..models import get_model
from ..schemas import GuidancePlan, SessionContext, StudentState

ROLE = "guidance"

SYSTEM_PROMPT = """\
당신은 코딩 학습 튜터 시스템의 '지도 방법 결정 에이전트'입니다.
학생 상태 파악 결과를 받아, 지금 어떤 방식으로 지도할지 결정하세요.

- approach: 어떤 접근을 쓸지 (예: 소크라테스식 질문, 직접 힌트, 개념 재설명, 예시 제공)
- hint_level: nudge(가벼운 주의 환기) / hint(구체적 힌트) / explain(개념 설명) 중 선택
- message_draft: 학생에게 보여줄 메시지 초안 (짧고 격려하는 톤)

정답을 그대로 알려주지 말고, 학생이 스스로 다음 단계를 밟도록 유도하는 것을
우선하세요.

예외: struggle_signals에 'paste_detected'가 있으면 이것은 "막힘"이 아니라
외부에서 코드를 그대로 붙여넣었을 수 있다는 신호입니다. 이 경우 힌트를 주지
말고, approach를 "이해도 확인"으로 하고 hint_level은 nudge로 두되,
message_draft는 학생이 방금 작성/붙여넣은 코드가 왜 그렇게 동작하는지
스스로 생각해보도록 작성하세요 (예: "이 코드가 왜 이렇게
동작하는지 생각해볼래요?").
"""


def build_agent() -> Agent:
    return Agent(name="guidance_agent", model=get_model(ROLE), system_prompt=SYSTEM_PROMPT)


def plan(ctx: SessionContext, student_state: StudentState, agent: Agent | None = None) -> GuidancePlan:
    agent = agent or build_agent()
    prompt = (
        "다음 세션 상태와 학생 상태 판단 결과를 보고 지도 방법을 결정하세요:\n\n"
        f"[세션 상태]\n{ctx.model_dump_json(indent=2)}\n\n"
        f"[학생 상태 판단]\n{student_state.model_dump_json(indent=2)}"
    )
    return agent.structured_output(GuidancePlan, prompt)
