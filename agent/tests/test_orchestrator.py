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
def test_pipeline_paste_branch_goes_straight_to_guided_action(*_mocks) -> None:
    """paste 분기(state_agent.assess가 이미 처리)는 should_intervene=True로 넘어오므로
    오케스트레이터는 그대로 guided_action_agent로 이어가면 된다."""
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
        patch.object(
            guided_action_agent,
            "plan",
            return_value=GuidedAction(
                approach="이해도 확인",
                message_draft="이 코드가 왜 이렇게 동작하는지 설명해볼래요?",
                action_type="send_message",
                payload={"message": "질문"},
            ),
        ) as mock_plan,
    ):
        result = TutorPipeline().run(_ctx())

    assert mock_plan.call_args.args[1].entry_branch == "paste"
    assert result.guidance_plan is not None
    assert result.guidance_plan.approach == "이해도 확인"
