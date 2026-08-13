"""2개 에이전트를 연결하는 오케스트레이터.

학생 상태 파악(규칙 기반 게이트 + [통과 시] LLM 평가) → [개입 시] 지도 방법 +
행동 결정 (한 번의 LLM 호출)

과거에는 별도의 EntryAgent(LLM)가 파이프라인 진입 여부를 먼저 결정했지만,
StateAgent와 사실상 같은 질문("지금 뭔가 해야 하나?")을 LLM 호출 2번으로 나눠
묻는 구조였다. 지금은 그 판단(규칙 기반 게이트, 붙여넣기 분기 포함)이
`state_agent.assess()` 안에 흡수되어 있다 (`agents/state_agent.py` 참고) —
오케스트레이터는 `student_state.should_intervene`만 보고 분기하면 된다.

**guidance_agent + action_agent도 하나로 합쳤다** (`guided_action_agent.py`).
"어떻게 가르칠지"와 "그래서 뭘 할지"는 강하게 결합된 하나의 판단이라 LLM
호출 2번으로 나눠 물을 이유가 약했고, 파이프라인 전체가 LLM을 순차로 4번
호출해 실측 28~30초가 걸리는 문제(agent/README.md "지연 시간" 절)의 직접적인
원인이었다. 지금은 2번(state, guided_action)이라 절반으로 준다.

**evaluation_agent는 더 이상 이 파이프라인이 동기로 호출하지 않는다.**
`PipelineResult.evaluation`은 이제 항상 `None`이다 (필드는 하류 호환을 위해
남겨둠 — `backend_adapter.to_agent_decision()`이 `None`을 이미 정상 처리한다).
evaluation 결과는 학생에게 보여줄 결정(action/reason)에 전혀 영향을 주지
않고 로깅/분석용 메타데이터일 뿐이었으므로, 응답을 그만큼 늦출 이유가
없었다. 필요하면 `service.py`가 응답을 반환한 뒤 백그라운드로
`evaluation_agent.evaluate()`를 따로 부르면 된다 (`service.py`의
`/decide` 핸들러 참고).

파이프라인이 중간에 멈추면(개입하지 않음) 이후 필드는 None으로 남는다. 실제
서비스 정책이 정해지면 분기 조건과 순서는 자유롭게 바꿔도 된다.

`run(ctx, skip_gate=True)`는 backend 연동(`backend_adapter.TutorAgentAdapter`)이 쓴다 —
backend Process Monitor가 이미 자체 규칙으로 "지금 부를 시점"이라고 판단해서 우리를
호출했을 때, 이 모듈의 게이트가 또 다른 기준으로 재판정하다가 신호가 어긋나
조용히 WAIT 처리해버리는 걸 막기 위해서다.
"""

from __future__ import annotations

from dataclasses import dataclass

from .agents import guided_action_agent, state_agent
from .schemas import ActionPlan, Evaluation, GuidancePlan, SessionContext, StudentState


@dataclass
class PipelineResult:
    student_state: StudentState
    guidance_plan: GuidancePlan | None = None
    action_plan: ActionPlan | None = None
    #: 항상 None. 하류 호환을 위해 필드만 남겨둠 (모듈 docstring 참고).
    evaluation: Evaluation | None = None


class TutorPipeline:
    """상태 파악(진입 게이트 포함) → 지도 방법+행동(한 번의 LLM 호출)으로 이어지는 파이프라인."""

    def __init__(self) -> None:
        self._state = state_agent.build_agent()
        self._guided_action = guided_action_agent.build_agent()

    def run(self, ctx: SessionContext, *, skip_gate: bool = False) -> PipelineResult:
        student_state = state_agent.assess(ctx, self._state, skip_gate=skip_gate)
        if not student_state.should_intervene:
            return PipelineResult(student_state=student_state)

        guided = guided_action_agent.plan(ctx, student_state, self._guided_action)

        return PipelineResult(
            student_state=student_state,
            guidance_plan=GuidancePlan(
                approach=guided.approach,
                hint_level=guided.hint_level,
                message_draft=guided.message_draft,
            ),
            action_plan=ActionPlan(action_type=guided.action_type, payload=guided.payload),
        )
