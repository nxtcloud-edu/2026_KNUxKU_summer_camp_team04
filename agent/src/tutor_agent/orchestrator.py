"""에이전트들을 연결하는 오케스트레이터.

두 개의 파이프라인이 있다.

1. 개입 파이프라인 — 튜터가 **먼저 말을 걸** 때 (`run()`)
---------------------------------------------------------

    학생 상태 파악          → 개입할까?        (규칙 게이트 + [통과 시] LLM)
        ↓ should_intervene
    지도 방법 + 행동 결정    → 어떻게 지도할까?  (LLM)
        ↓ GuidancePlan (내부 지시문)
    응답 생성               → 뭐라고 말할까?    (LLM)
        ↓ TutorMessage.message  ← 학생이 읽는 유일한 텍스트

**세 번째 단계가 이번에 추가됐다.** 그전에는 "어떻게 지도할지"를 결정하는
데서 파이프라인이 끝났고, 학생에게 건넬 문장을 만드는 단계가 없었다. 그래서
`backend_adapter`가 내부 판단 텍스트(`StudentState.state_summary`)를 학생
화면으로 흘려보냈고, 학생은 "학생은 ... 31분 넘게 완전히 막혀 있습니다
(지도 방식: 단계별 구조 안내/explain)" 같은 3인칭 분석 리포트를 읽었다.
자세한 경위와 역할 분리 표는 `agents/tutor_message_agent.py` docstring 참고.

**붙여넣기(이해도 확인) 분기만은 LLM을 아예 안 부른다** (`comprehension_check.py`).
`state_agent`가 이미 규칙만으로 이 분기를 판정하는데도 뒤이어 판단·작문 LLM이
따라붙고 있었다 — 시스템 프롬프트가 approach/hint_level/action_type을 전부
못박아 둔 상태라 LLM에 남은 자유도는 문장 표현뿐이었는데, 그 때문에 학생이
5~6초를 더 기다렸다. 그래서 이 분기의 LLM 호출은 **0번**이고, 판단
(`GuidedAction`)과 작문(`TutorMessage`) 모두 `comprehension_check`가 규칙으로
만든다. 아래 `_comprehension_check()`를 별도 메서드로 둔 이유가 그것이다 —
분기 도중에 LLM 경로로 흘러 들어갈 여지를 구조적으로 없앤다.

2. 응답 파이프라인 — **학생이 답을 보냈을** 때 (`respond_to_student()`)
----------------------------------------------------------------------

    학생 답변 평가          → 이해했나?        (LLM)
        ↓ AnswerEvaluation (내부)
    응답 생성               → 뭐라고 말할까?    (LLM)
        ↓ TutorMessage.message

이게 학습 루프를 닫는다. 지도 결정이 "학생에게 질문하기"였다면 학생이 답을
할 것이고, 그 답을 평가해서 이해했는지 판단하고, 그 판단에 따라 다음 말을
바꾼다 (이해했으면 다음 단계로, 절반이면 빠진 조각만, 못 했으면 더 쉬운
질문으로). 평가 에이전트가 예전에 자기 개입을 자기가 채점하고 있었던 문제는
`agents/evaluation_agent.py` docstring 참고.

호출 비용
---------
`run()`은 LLM을 최대 3번 순차 호출한다 (state → guided_action →
tutor_message). 개입하지 않기로 하면 1번, `action_type="no_op"`이면 2번에서
멈춘다 — 아무 말도 안 할 건데 문장을 만들 이유가 없다. 작문 단계는 판단이
아니라 문장 생성이고 압축된 컨텍스트만 받으므로(`prompt_context.py`) 가장
빠르다. 더 줄이려면 `.env`에서 이 단계만 작은 모델로 내리면 된다
(`MODEL_PROVIDER_TUTOR_MESSAGE` / `ANTHROPIC_MODEL_ID_TUTOR_MESSAGE`).

`run(ctx, skip_gate=True)`는 backend 연동(`backend_adapter.TutorAgentAdapter`)이
쓴다 — backend Process Monitor가 이미 자체 규칙으로 "지금 부를 시점"이라고
판단해서 우리를 호출했을 때, 이 모듈의 게이트가 또 다른 기준으로 재판정하다가
신호가 어긋나 조용히 WAIT 처리해버리는 걸 막기 위해서다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .agents import (
    comprehension_check,
    evaluation_agent,
    guided_action_agent,
    state_agent,
    tutor_message_agent,
)
from .schemas import (
    ActionPlan,
    AnswerEvaluation,
    GuidancePlan,
    SessionContext,
    StudentReply,
    StudentState,
    TutorMessage,
)


@dataclass
class PipelineResult:
    """개입 파이프라인(`run()`)의 결과.

    `tutor_message`가 **학생에게 갈 문장을 담은 유일한 필드**다. 나머지는 전부
    내부 판단이며, 교육자 타임라인이나 로그용이다.
    """

    student_state: StudentState
    guidance_plan: GuidancePlan | None = None
    action_plan: ActionPlan | None = None
    tutor_message: TutorMessage | None = None


@dataclass
class ReplyResult:
    """응답 파이프라인(`respond_to_student()`)의 결과."""

    evaluation: AnswerEvaluation
    tutor_message: TutorMessage


class TutorPipeline:
    """네 에이전트를 잇는 파이프라인. 에이전트 인스턴스를 캐시해 재사용한다.

    캐시하는 이유: strands `Agent` 생성은 LLM 프로바이더 클라이언트(=httpx 연결
    풀)를 만드는 일이라, 요청마다 새로 만들면 커넥션과 파일 디스크립터가 계속
    늘어난다. 캐시된 클라이언트를 여러 이벤트 루프에서 쓰다가 터지던 문제
    (`RuntimeError: Event loop is closed`)는 `llm_runtime.py`가 해결했다 —
    모든 LLM 호출이 프로세스에 하나뿐인 영속 루프에서 돌아간다.

    지연 생성한다: 실제로 쓰이는 역할의 클라이언트만 만든다 (예: 학생 답변이
    한 번도 안 오면 evaluation 에이전트는 만들지 않는다).
    """

    def __init__(self) -> None:
        self._agents: dict[str, Any] = {}

    def _agent(self, role: str, build: Callable[[], Any]) -> Any:
        # `None`을 반환하는 mock도 캐시되어야 하므로 `in`으로 확인한다
        # (`self._agents.get(role) is None`으로 하면 매번 다시 만든다).
        if role not in self._agents:
            self._agents[role] = build()
        return self._agents[role]

    # --- 1. 개입 파이프라인 -------------------------------------------------

    def run(self, ctx: SessionContext, *, skip_gate: bool = False) -> PipelineResult:
        """개입 여부를 판단하고, 개입한다면 학생에게 보낼 메시지까지 만든다."""
        student_state = state_agent.assess(
            ctx, self._agent("state", state_agent.build_agent), skip_gate=skip_gate
        )
        if not student_state.should_intervene:
            return PipelineResult(student_state=student_state)

        # 붙여넣기 분기는 판단도 작문도 규칙으로 한다 (LLM 호출 0번, 위 docstring 참고).
        # `state_agent`가 이 분기를 LLM 없이 판정해 놓고도 여기서 다시 LLM을 부르면,
        # "규칙만으로 처리한다"는 설계가 파이프라인 전체로는 지켜지지 않는다.
        if student_state.entry_branch == "paste":
            return self._comprehension_check(ctx, student_state)

        guided = guided_action_agent.plan(
            ctx,
            student_state,
            self._agent("guided_action", guided_action_agent.build_agent),
        )
        guidance_plan = GuidancePlan(
            approach=guided.approach,
            hint_level=guided.hint_level,
            focus=guided.focus,
            talking_points=guided.talking_points,
            avoid=guided.avoid,
            expects_student_reply=guided.expects_student_reply,
        )
        action_plan = ActionPlan(action_type=guided.action_type, payload=guided.payload)

        if guided.action_type == "no_op":
            # 아무 말도 하지 않기로 했다 → 작문 LLM 호출을 건너뛴다.
            # (`to_agent_decision()`이 이걸 WAIT으로 바꾼다.)
            return PipelineResult(
                student_state=student_state,
                guidance_plan=guidance_plan,
                action_plan=action_plan,
            )

        tutor_message = tutor_message_agent.write_intervention(
            ctx, guidance_plan, self._agent("tutor_message", tutor_message_agent.build_agent)
        )

        return PipelineResult(
            student_state=student_state,
            guidance_plan=guidance_plan,
            action_plan=action_plan,
            tutor_message=tutor_message,
        )

    def _comprehension_check(
        self, ctx: SessionContext, student_state: StudentState
    ) -> PipelineResult:
        """붙여넣기 분기. LLM을 한 번도 부르지 않고 `PipelineResult`를 완성한다.

        LLM 경로와 **같은 모양**을 만든다 (`GuidancePlan` + `ActionPlan` +
        `TutorMessage`) — 그래서 `backend_adapter` 이하 하류는 이 분기가 있었는지
        조차 모른다.
        """
        guided = comprehension_check.plan(ctx)
        return PipelineResult(
            student_state=student_state,
            guidance_plan=GuidancePlan(
                approach=guided.approach,
                hint_level=guided.hint_level,
                focus=guided.focus,
                talking_points=guided.talking_points,
                avoid=guided.avoid,
                expects_student_reply=guided.expects_student_reply,
            ),
            action_plan=ActionPlan(
                action_type=guided.action_type, payload=guided.payload
            ),
            tutor_message=comprehension_check.write(ctx),
        )

    # --- 2. 응답 파이프라인 -------------------------------------------------

    def respond_to_student(self, ctx: SessionContext, reply: StudentReply) -> ReplyResult:
        """학생 답변을 평가하고, 그 평가에 맞춰 이어서 할 말을 만든다.

        여기서는 `state_agent`/`guided_action_agent`를 부르지 않는다 — 학생이
        직접 말을 걸었으므로 "개입할 시점인가"를 다시 물을 이유가 없다
        (그 판단은 학생의 의사표시로 이미 대체됐다).
        """
        evaluation = evaluation_agent.evaluate_answer(
            ctx, reply, self._agent("evaluation", evaluation_agent.build_agent)
        )
        tutor_message = tutor_message_agent.write_follow_up(
            ctx,
            reply,
            evaluation,
            self._agent("tutor_message", tutor_message_agent.build_agent),
        )
        return ReplyResult(evaluation=evaluation, tutor_message=tutor_message)
