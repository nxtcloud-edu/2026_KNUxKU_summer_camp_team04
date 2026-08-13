"""평가 에이전트.

실행된 행동(ActionPlan)이 적절했는지 평가한다. 이 결과는 다음 진입시점/상태
판단에 참고 자료로 피드백될 수 있다 (현재 초안에서는 배선만 해두고, 실제
피드백 루프 연결은 TODO).
"""

from __future__ import annotations

from strands import Agent

from ..models import get_model
from ..schemas import ActionPlan, Evaluation, SessionContext

ROLE = "evaluation"

SYSTEM_PROMPT = """\
당신은 코딩 학습 튜터 시스템의 '평가 에이전트'입니다.
방금 실행된 행동이 이 시점의 학생에게 적절했는지 평가하세요.

- effectiveness_score: 0.0(부적절)~1.0(매우 적절) 사이 점수
- notes: 평가 근거를 짧게 서술
- follow_up_needed: 추가 개입이 곧 필요할 것으로 보이는지 여부
"""


def build_agent() -> Agent:
    return Agent(name="evaluation_agent", model=get_model(ROLE), system_prompt=SYSTEM_PROMPT)


def evaluate(ctx: SessionContext, action_plan: ActionPlan, agent: Agent | None = None) -> Evaluation:
    agent = agent or build_agent()
    prompt = (
        "다음 세션 상태와 실행된 행동을 보고 그 적절성을 평가하세요:\n\n"
        f"[세션 상태]\n{ctx.model_dump_json(indent=2)}\n\n"
        f"[실행된 행동]\n{action_plan.model_dump_json(indent=2)}"
    ) 
    return agent.structured_output(Evaluation, prompt)
