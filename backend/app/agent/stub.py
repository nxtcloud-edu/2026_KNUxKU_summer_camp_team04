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


class FakeAgent:
    """테스트 전용. 미리 정한 결정 하나를 매번 돌려준다 (judge/stub.py의 FakeJudge와 같은 패턴).

    `calls`에 받은 `AgentContext`를 순서대로 쌓아두므로, "트리거 안 되면 agent
    자체를 안 부른다"처럼 호출 여부/횟수를 검증하는 테스트에 쓸 수 있다.
    """

    name = "fake"

    def __init__(self, decision: AgentDecision) -> None:
        self._decision = decision
        self.calls: list[AgentContext] = []

    def decide(self, ctx: AgentContext) -> AgentDecision:
        self.calls.append(ctx)
        return self._decision
