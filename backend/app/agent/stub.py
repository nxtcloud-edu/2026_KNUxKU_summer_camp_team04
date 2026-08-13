from __future__ import annotations

from app.agent.interface import AgentContext, AgentDecision
from app.enums import AgentAction


class WaitAgent:
    """오늘 기본값.

    backend_plan §14의 폴백과 같은 모양이다: Agent를 안정적으로 돌릴 수 없으면
    정답을 만들어내지 않고 WAIT한다.
    """

    name = "wait"

    def decide(self, ctx: AgentContext) -> AgentDecision:
        return AgentDecision(
            state=ctx.process_status,
            concept=None,
            action=AgentAction.WAIT,
            reason="Agent backend가 구성되지 않아 학생의 추가 시도를 기다립니다.",
        )
