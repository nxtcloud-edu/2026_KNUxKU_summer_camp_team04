"""오케스트레이터 분기 로직 스모크 테스트.

실제 LLM/Agent를 만들지 않도록 build_agent()와 각 결정 함수를 모두 mock 처리해서,
파이프라인의 분기 조건만 검증한다. 진입 게이트(규칙 기반)와 붙여넣기 분기는
state_agent.assess() 안에 흡수되어 있으므로, 여기서는 state_agent.assess()의
반환값만 패치해 오케스트레이터가 `should_intervene` 하나로 올바르게 분기하는지만
확인한다 (게이트 자체 로직은 test_state_agent.py 참고).

파이프라인이 두 개다 (`orchestrator.py` docstring 참고):

* `run()` — 튜터가 먼저 말을 건다: state → guided_action → **tutor_message**
* `respond_to_student()` — 학생이 답을 보냈다: evaluation → **tutor_message**

`tutor_message` 단계가 새로 생긴 것이 이 파일의 주된 변경점이다. 그전에는
"어떻게 지도할지"까지만 정하고 학생에게 줄 문장을 만드는 단계가 없어서,
`backend_adapter`가 내부 판단문(`StudentState.state_summary`)을 학생 화면으로
흘려보냈다.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tutor_agent.agents import (  # noqa: E402
    evaluation_agent,
    guided_action_agent,
    state_agent,
    tutor_message_agent,
)
from tutor_agent.orchestrator import TutorPipeline  # noqa: E402
from tutor_agent.schemas import (  # noqa: E402
    AnswerEvaluation,
    GuidedAction,
    SessionContext,
    StudentReply,
    StudentState,
    TutorMessage,
)


def _ctx() -> SessionContext:
    return SessionContext(student_id="s1", problem_id="p1", code="pass")


def _guided(**overrides) -> GuidedAction:
    data = {
        "approach": "직접 힌트",
        "hint_level": "hint",
        "focus": "카운터 초기화",
        "talking_points": ["초기값을 스스로 떠올리게 할 것"],
        "action_type": "send_message",
        "payload": {},
    }
    data.update(overrides)
    return GuidedAction(**data)


def _message(text: str = "이 부분을 확인해볼까요?") -> TutorMessage:
    return TutorMessage(message=text)


# --- 개입 파이프라인 run() ----------------------------------------------------


@patch.object(tutor_message_agent, "build_agent", return_value=None)
@patch.object(guided_action_agent, "build_agent", return_value=None)
@patch.object(state_agent, "build_agent", return_value=None)
def test_pipeline_stops_when_gate_skips(*_mocks) -> None:
    """게이트가 막은 경우(신호 부족/쿨다운/세션 종료 등) — LLM 호출 없이 종료."""
    with patch.object(
        state_agent,
        "assess",
        return_value=StudentState(
            state_summary="막힘 신호가 1개뿐이라 개입하지 않습니다.",
            should_intervene=False,
            entry_branch="skip",
        ),
    ):
        result = TutorPipeline().run(_ctx())

    assert result.student_state.should_intervene is False
    assert result.guidance_plan is None
    assert result.action_plan is None
    assert result.tutor_message is None


@patch.object(tutor_message_agent, "build_agent", return_value=None)
@patch.object(guided_action_agent, "build_agent", return_value=None)
@patch.object(state_agent, "build_agent", return_value=None)
def test_pipeline_stops_when_no_intervention_needed(*_mocks) -> None:
    """게이트는 통과했지만(신호 2개+) LLM이 순조롭다고 판단한 경우."""
    with patch.object(
        state_agent,
        "assess",
        return_value=StudentState(
            state_summary="순조로움", should_intervene=False, entry_branch="struggle"
        ),
    ):
        result = TutorPipeline().run(_ctx())

    assert result.student_state.should_intervene is False
    assert result.guidance_plan is None
    assert result.tutor_message is None


@patch.object(tutor_message_agent, "build_agent", return_value=None)
@patch.object(guided_action_agent, "build_agent", return_value=None)
@patch.object(state_agent, "build_agent", return_value=None)
def test_pipeline_writes_a_student_message_when_intervening(*_mocks) -> None:
    """개입하면 지도 계획으로 끝나지 않고 학생에게 줄 문장까지 만든다."""
    with (
        patch.object(
            state_agent,
            "assess",
            return_value=StudentState(
                state_summary="같은 오류 반복",
                should_intervene=True,
                urgency="high",
                entry_branch="struggle",
            ),
        ),
        patch.object(guided_action_agent, "plan", return_value=_guided()),
        patch.object(
            tutor_message_agent,
            "write_intervention",
            return_value=_message("합을 담는 변수는 어떤 값으로 시작할까요?"),
        ) as mock_write,
    ):
        result = TutorPipeline().run(_ctx())

    assert result.guidance_plan is not None
    assert result.guidance_plan.approach == "직접 힌트"
    assert result.action_plan is not None
    assert result.action_plan.action_type == "send_message"
    assert result.tutor_message is not None
    assert result.tutor_message.message == "합을 담는 변수는 어떤 값으로 시작할까요?"

    # 작문 에이전트는 **지도 계획**을 받는다 (원본 GuidedAction이 아니라 쪼갠 것).
    written_plan = mock_write.call_args.args[1]
    assert written_plan.focus == "카운터 초기화"
    assert written_plan.talking_points == ["초기값을 스스로 떠올리게 할 것"]


@patch.object(tutor_message_agent, "build_agent", return_value=None)
@patch.object(guided_action_agent, "build_agent", return_value=None)
@patch.object(state_agent, "build_agent", return_value=None)
def test_pipeline_skips_writing_when_action_is_no_op(*_mocks) -> None:
    """아무 말도 안 할 건데 문장을 만들 이유가 없다 (LLM 호출 1번 절약)."""
    with (
        patch.object(
            state_agent,
            "assess",
            return_value=StudentState(
                state_summary="이미 충분히 개입함", should_intervene=True, entry_branch="struggle"
            ),
        ),
        patch.object(guided_action_agent, "plan", return_value=_guided(action_type="no_op")),
        patch.object(tutor_message_agent, "write_intervention") as mock_write,
    ):
        result = TutorPipeline().run(_ctx())

    mock_write.assert_not_called()
    assert result.action_plan is not None
    assert result.action_plan.action_type == "no_op"
    assert result.tutor_message is None


@patch.object(tutor_message_agent, "build_agent", return_value=None)
@patch.object(guided_action_agent, "build_agent", return_value=None)
@patch.object(state_agent, "build_agent", return_value=None)
def test_pipeline_paste_branch_never_calls_llm(*_mocks) -> None:
    """paste 분기는 LLM을 **한 번도** 부르지 않는다.

    예전에는 state_agent가 규칙만으로 판정해 놓고도 guided_action_agent(LLM)로
    이어갔다. 그 호출이 붙여넣기->힌트 표시 지연의 5~6초를 차지했다.

    판단/작문이 분리된 뒤에는 막아야 할 LLM 호출이 **둘**이다 — 판단
    (`guided_action_agent.plan`)과 작문(`tutor_message_agent.write_intervention`).
    둘 다 `comprehension_check`가 규칙으로 대신한다.
    """
    paste_ctx = SessionContext(
        student_id="s1",
        problem_id="p1",
        code="def solution(nums):\n    for n in nums:\n        print(n)\n",
    )
    with (
        patch.object(
            state_agent,
            "assess",
            return_value=StudentState(
                state_summary="붙여넣기가 감지되어 이해도 확인이 필요합니다.",
                struggle_signals=["paste_detected"],
                should_intervene=True,
                urgency="medium",
                entry_branch="paste",
            ),
        ),
        patch.object(guided_action_agent, "plan") as mock_plan,
        patch.object(tutor_message_agent, "write_intervention") as mock_write,
    ):
        result = TutorPipeline().run(paste_ctx)

    mock_plan.assert_not_called()
    mock_write.assert_not_called()
    assert result.guidance_plan is not None
    assert result.guidance_plan.approach == "이해도 확인"
    assert result.guidance_plan.hint_level == "nudge"
    # 이해도 확인은 답을 받아야 의미가 있다 -> 학생 답변 평가 루프로 이어진다.
    assert result.guidance_plan.expects_student_reply is True
    assert result.action_plan is not None
    assert result.action_plan.action_type == "send_message"
    # 문구는 코드에서 실제로 뽑은 구조를 가리켜야 한다 (일반론이 아니라).
    assert result.tutor_message is not None
    assert "for" in result.tutor_message.message
    assert result.tutor_message.expects_reply is True
    # payload는 backend_adapter의 폴백 경로다. 어긋나면 학생이 보는 문구가
    # 경로에 따라 달라진다.
    assert result.action_plan.payload["message"] == result.tutor_message.message


@patch.object(guided_action_agent, "build_agent", return_value=None)
@patch.object(state_agent, "build_agent", return_value=None)
def test_pipeline_help_requested_branch_still_uses_llm(*_mocks) -> None:
    """help_requested는 paste와 달리 **LLM을 그대로 부른다.**

    should_intervene 여부는 state_agent가 이미 고정해서 넘기지만("직접
    요청했으니 무조건 개입"), 실제로 뭘 어떻게 도와줄지는 학생의 실제
    코드/문맥을 봐야 쓸모 있는 답이 나온다 — paste처럼 정해진 템플릿으로
    대신할 수 없다.
    """
    with (
        patch.object(
            state_agent,
            "assess",
            return_value=StudentState(
                state_summary="학생이 직접 도움을 요청했습니다.",
                struggle_signals=["help_requested"],
                should_intervene=True,
                urgency="high",
                entry_branch="help_requested",
            ),
        ),
        patch.object(
            guided_action_agent,
            "plan",
            return_value=_guided(
                approach="이해도 확인", hint_level="nudge", expects_student_reply=True
            ),
        ) as mock_plan,
        patch.object(
            tutor_message_agent,
            "write_intervention",
            return_value=TutorMessage(
                message="이 코드가 왜 이렇게 동작하는지 설명해볼래요?",
                question="이 코드가 왜 이렇게 동작하는지 설명해볼래요?",
                expects_reply=True,
            ),
        ),
    ):
        result = TutorPipeline().run(_ctx())

    mock_plan.assert_called_once()
    assert mock_plan.call_args.args[1].entry_branch == "help_requested"
    assert result.guidance_plan is not None
    assert result.guidance_plan.approach == "이해도 확인"
    assert result.guidance_plan.expects_student_reply is True
    assert result.tutor_message is not None
    assert result.tutor_message.expects_reply is True


# --- 응답 파이프라인 respond_to_student() -------------------------------------


@patch.object(tutor_message_agent, "build_agent", return_value=None)
@patch.object(evaluation_agent, "build_agent", return_value=None)
def test_respond_evaluates_the_answer_then_writes_a_follow_up(*_mocks) -> None:
    """평가 결과가 로그로 끝나지 않고 **다음 응답의 입력**이 되어야 한다."""
    evaluation = AnswerEvaluation(
        understanding="partial",
        is_correct=False,
        misconceptions=["초기화를 반복문 안에서 해도 된다고 생각함"],
        follow_up_needed=True,
        next_focus="초기화 위치",
    )
    reply = StudentReply(answer="0으로요. 반복문 안에서요.", question="언제 초기화해야 할까요?")

    with (
        patch.object(evaluation_agent, "evaluate_answer", return_value=evaluation) as mock_eval,
        patch.object(
            tutor_message_agent,
            "write_follow_up",
            return_value=_message("0으로 두는 건 맞아요! 그 줄이 반복문 안에 있으면 어떻게 될까요?"),
        ) as mock_write,
    ):
        result = TutorPipeline().respond_to_student(_ctx(), reply)

    # 평가는 학생의 답변을 받았다.
    assert mock_eval.call_args.args[1] is reply
    # 그 평가 결과가 작문 단계로 전달됐다 (이게 루프를 닫는 지점이다).
    assert mock_write.call_args.args[2] is evaluation
    assert result.evaluation is evaluation
    assert result.tutor_message.message.startswith("0으로 두는 건 맞아요")


@patch.object(tutor_message_agent, "build_agent", return_value=None)
@patch.object(evaluation_agent, "build_agent", return_value=None)
def test_respond_does_not_re_ask_whether_to_intervene(*_mocks) -> None:
    """학생이 직접 말을 걸었으므로 개입 시점 판단(state/guided_action)을 다시 하지 않는다."""
    with (
        patch.object(
            evaluation_agent,
            "evaluate_answer",
            return_value=AnswerEvaluation(understanding="solid", is_correct=True),
        ),
        patch.object(tutor_message_agent, "write_follow_up", return_value=_message()),
        patch.object(state_agent, "assess") as mock_assess,
        patch.object(guided_action_agent, "plan") as mock_plan,
    ):
        TutorPipeline().respond_to_student(_ctx(), StudentReply(answer="0으로요"))

    mock_assess.assert_not_called()
    mock_plan.assert_not_called()


# --- 에이전트 캐시 ------------------------------------------------------------


def test_agents_are_built_once_and_reused() -> None:
    """에이전트 생성은 LLM 클라이언트(=httpx 연결 풀) 생성이라 매번 하면 안 된다."""
    with (
        patch.object(state_agent, "build_agent", return_value=None) as mock_build,
        patch.object(
            state_agent,
            "assess",
            return_value=StudentState(state_summary="", should_intervene=False),
        ),
    ):
        pipeline = TutorPipeline()
        pipeline.run(_ctx())
        pipeline.run(_ctx())
        pipeline.run(_ctx())

    assert mock_build.call_count == 1


def test_agents_are_not_built_until_used() -> None:
    """쓰이지 않는 역할의 클라이언트는 만들지 않는다 (학생 답변이 안 오면 evaluation 불필요)."""
    with (
        patch.object(state_agent, "build_agent", return_value=None),
        patch.object(
            state_agent,
            "assess",
            return_value=StudentState(state_summary="", should_intervene=False),
        ),
        patch.object(evaluation_agent, "build_agent", return_value=None) as mock_eval_build,
        patch.object(tutor_message_agent, "build_agent", return_value=None) as mock_msg_build,
    ):
        TutorPipeline().run(_ctx())

    mock_eval_build.assert_not_called()
    mock_msg_build.assert_not_called()
