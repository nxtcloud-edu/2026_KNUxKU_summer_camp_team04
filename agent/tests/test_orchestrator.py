"""오케스트레이터 분기 로직 스모크 테스트.

실제 LLM/Agent를 만들지 않도록 build_agent()와 각 결정 함수를 모두 mock 처리해서,
TutorPipeline.run()의 분기 조건만 검증한다. 진입 게이트(규칙 기반)와 붙여넣기
분기는 이제 state_agent.assess() 안에 흡수되어 있으므로, 여기서는
state_agent.assess()의 반환값만 패치해 오케스트레이터가 `should_intervene`
하나로 올바르게 분기하는지만 확인한다 (게이트 자체 로직은 test_state_agent.py 참고).

guidance_agent + action_agent는 guided_action_agent 하나로 합쳐졌다 (레이턴시
단축 — agent/README.md "지연 시간" 절 참고). 이 파일도 그에 맞춰 mock 대상을
guided_action_agent로 바꿨다.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tutor_agent.agents import guided_action_agent, state_agent  # noqa: E402
from tutor_agent.orchestrator import TutorPipeline  # noqa: E402
from tutor_agent.schemas import GuidedAction, SessionContext, StudentState  # noqa: E402


def _ctx() -> SessionContext:
    return SessionContext(student_id="s1", problem_id="p1", code="pass")


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
    assert result.evaluation is None


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

    assert result.student_state is not None
    assert result.student_state.should_intervene is False
    assert result.guidance_plan is None


@patch.object(guided_action_agent, "build_agent", return_value=None)
@patch.object(state_agent, "build_agent", return_value=None)
def test_pipeline_runs_guided_action_when_intervention_needed(*_mocks) -> None:
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
        patch.object(
            guided_action_agent,
            "plan",
            return_value=GuidedAction(
                approach="직접 힌트",
                message_draft="이 부분을 확인해보세요",
                action_type="send_message",
                payload={"message": "힌트"},
            ),
        ),
    ):
        result = TutorPipeline().run(_ctx())

    assert result.guidance_plan is not None
    assert result.guidance_plan.approach == "직접 힌트"
    assert result.action_plan is not None
    assert result.action_plan.action_type == "send_message"
    assert result.action_plan.payload == {"message": "힌트"}
    # evaluation은 이제 이 파이프라인이 동기로 안 부른다 (service.py가 백그라운드로 처리).
    assert result.evaluation is None


@patch.object(guided_action_agent, "build_agent", return_value=None)
@patch.object(state_agent, "build_agent", return_value=None)
def test_pipeline_paste_branch_never_calls_llm(*_mocks) -> None:
    """paste 분기는 LLM을 **한 번도** 부르지 않는다.

    예전에는 state_agent가 규칙만으로 판정해 놓고도 guided_action_agent(LLM)로
    이어갔다. 그 호출이 붙여넣기->힌트 표시 지연의 5~6초를 차지했다.
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
    ):
        result = TutorPipeline().run(paste_ctx)

    mock_plan.assert_not_called()
    assert result.guidance_plan is not None
    assert result.guidance_plan.approach == "이해도 확인"
    assert result.guidance_plan.hint_level == "nudge"
    assert result.action_plan is not None
    assert result.action_plan.action_type == "send_message"
    # 문구는 코드에서 실제로 뽑은 구조를 가리켜야 한다 (일반론이 아니라).
    assert "for" in result.guidance_plan.message_draft
    assert result.action_plan.payload["message"] == result.guidance_plan.message_draft


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
            return_value=GuidedAction(
                approach="직접 힌트",
                message_draft="지금 코드를 보니 이 부분이 막혔네요",
                action_type="send_message",
                payload={"message": "힌트"},
            ),
        ) as mock_plan,
    ):
        result = TutorPipeline().run(_ctx())

    mock_plan.assert_called_once()
    assert mock_plan.call_args.args[1].entry_branch == "help_requested"
    assert result.guidance_plan is not None
    assert result.guidance_plan.message_draft == "지금 코드를 보니 이 부분이 막혔네요"
