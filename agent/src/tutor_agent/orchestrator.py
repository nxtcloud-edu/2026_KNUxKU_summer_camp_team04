"""4개 에이전트를 연결하는 오케스트레이터.

학생 상태 파악(규칙 기반 게이트 + [통과 시] LLM 평가) → [개입 시] 지도 방법 결정
→ 행동 결정 → 평가

과거에는 별도의 EntryAgent(LLM)가 파이프라인 진입 여부를 먼저 결정했지만,
StateAgent와 사실상 같은 질문("지금 뭔가 해야 하나?")을 LLM 호출 2번으로 나눠
묻는 구조였다. 지금은 그 판단(규칙 기반 게이트, 붙여넣기 분기 포함)이
`state_agent.assess()` 안에 흡수되어 있다 (`agents/state_agent.py` 참고) —
오케스트레이터는 `student_state.should_intervene`만 보고 분기하면 된다.

파이프라인이 중간에 멈추면(개입하지 않음) 이후 필드는 None으로 남는다. 실제
서비스 정책이 정해지면 분기 조건과 순서는 자유롭게 바꿔도 된다.

`run(ctx, skip_gate=True)`는 backend 연동(`backend_adapter.TutorAgentAdapter`)이 쓴다 —
backend Process Monitor가 이미 자체 규칙으로 "지금 부를 시점"이라고 판단해서 우리를
호출했을 때, 이 모듈의 게이트가 또 다른 기준으로 재판정하다가 신호가 어긋나
조용히 WAIT 처리해버리는 걸 막기 위해서다.
"""

from __future__ import annotations

from dataclasses import dataclass

from .agents import action_agent, evaluation_agent, guidance_agent, state_agent
from .schemas import ActionPlan, Evaluation, GuidancePlan, SessionContext, StudentState


@dataclass
class PipelineResult:
    student_state: StudentState
    guidance_plan: GuidancePlan | None = None
    action_plan: ActionPlan | None = None
    evaluation: Evaluation | None = None


class TutorPipeline:
    """상태 파악(진입 게이트 포함) → 지도 방법 → 행동 → 평가로 이어지는 튜터링 파이프라인."""

    def __init__(self) -> None:
        self._state = state_agent.build_agent()
        self._guidance = guidance_agent.build_agent()
        self._action = action_agent.build_agent()
        self._evaluation = evaluation_agent.build_agent()

    def run(self, ctx: SessionContext, *, skip_gate: bool = False) -> PipelineResult:
        student_state = state_agent.assess(ctx, self._state, skip_gate=skip_gate)
        if not student_state.should_intervene:
            return PipelineResult(student_state=student_state)

        guidance_plan = guidance_agent.plan(ctx, student_state, self._guidance)
        action_plan = action_agent.decide(ctx, guidance_plan, self._action)
        evaluation = evaluation_agent.evaluate(ctx, action_plan, self._evaluation)

        return PipelineResult(
            student_state=student_state,
            guidance_plan=guidance_plan,
            action_plan=action_plan,
            evaluation=evaluation,
        )
