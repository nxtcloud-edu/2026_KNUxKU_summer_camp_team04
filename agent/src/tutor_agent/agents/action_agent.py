"""지도 방침이 정해졌을 때, 실제로 무엇을 할지 결정하는 에이전트.

`guidance_agent`의 결정(어떻게 가르칠지)을 받아 구체적인 행동(action_type,
payload)으로 변환한다. 이 결과가 실제로 프런트엔드/backend에 전달되어 실행된다.
"""

from __future__ import annotations

from strands import Agent

from ..models import get_model
from ..schemas import ActionPlan, GuidancePlan, SessionContext

ROLE = "action"

SYSTEM_PROMPT = """\
당신은 코딩 학습 튜터 시스템의 '행동 결정 에이전트'입니다.
지도 방법이 정해지면, 그것을 시스템이 실행할 수 있는 구체적인 행동으로
변환하세요.

action_type은 다음 중 하나여야 합니다:
- send_message: 학생에게 메시지를 보낸다 (payload.message)
- highlight_code: 코드의 특정 줄/구간을 강조한다 (payload.line_start, payload.line_end, payload.reason)
- show_example: 관련 예시를 보여준다 (payload.example)
- no_op: 아무 행동도 하지 않는다 (드물게, 이미 충분히 개입했다고 판단될 때)
"""


def build_agent() -> Agent:
    return Agent(name="action_decision_agent", model=get_model(ROLE), system_prompt=SYSTEM_PROMPT)


def decide(ctx: SessionContext, guidance_plan: GuidancePlan, agent: Agent | None = None) -> ActionPlan:
    agent = agent or build_agent()
    prompt = (
        "다음 세션 상태와 지도 방법 결정을 보고, 실제로 실행할 행동을 결정하세요:\n\n"
        f"[세션 상태]\n{ctx.model_dump_json(indent=2)}\n\n"
        f"[지도 방법]\n{guidance_plan.model_dump_json(indent=2)}"
    )
    return agent.structured_output(ActionPlan, prompt)
