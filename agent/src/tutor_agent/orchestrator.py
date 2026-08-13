"""5개 에이전트를 연결하는 오케스트레이터.

진입시점 결정 → 학생 상태 파악(개입시점 결정) → [개입 시] 지도 방법 결정
→ 행동 결정 → 평가

파이프라인이 중간에 멈추면(진입하지 않음 / 개입하지 않음) 이후 필드는 None으로
남는다. 실제 서비스 정책이 정해지면 분기 조건과 순서는 자유롭게 바꿔도 된다.
"""

from __future__ import annotations

from dataclasses import dataclass

from .agents import action_agent, entry_agent, evaluation_agent, guidance_agent, state_agent
from .schemas import ActionPlan, EntryDecision, Evaluation, GuidancePlan, SessionContext, StudentState


@dataclass
class PipelineResult:
    entry_decision: EntryDecision
    student_state: StudentState | None = None
    guidance_plan: GuidancePlan | None = None
    action_plan: ActionPlan | None = None
    evaluation: Evaluation | None = None


class TutorPipeline:
    """진입 → 상태 파악 → 지도 방법 → 행동 → 평가로 이어지는 튜터링 파이프라인."""

    def __init__(self) -> None:
        self._entry = entry_agent.build_agent()
        self._state = state_agent.build_agent()
        self._guidance = guidance_agent.build_agent()
        self._action = action_agent.build_agent()
        self._evaluation = evaluation_agent.build_agent()

    def run(self, ctx: SessionContext) -> PipelineResult:
        entry_decision = entry_agent.decide(ctx, self._entry)
        if not entry_decision.should_enter:
            return PipelineResult(entry_decision=entry_decision)

        student_state = state_agent.assess(ctx, self._state)
        if not student_state.should_intervene:
            return PipelineResult(entry_decision=entry_decision, student_state=student_state)

        guidance_plan = guidance_agent.plan(ctx, student_state, self._guidance)
        action_plan = action_agent.decide(ctx, guidance_plan, self._action)
        evaluation = evaluation_agent.evaluate(ctx, action_plan, self._evaluation)

        return PipelineResult(
            entry_decision=entry_decision,
            student_state=student_state,
            guidance_plan=guidance_plan,
            action_plan=action_plan,
            evaluation=evaluation,
        )
