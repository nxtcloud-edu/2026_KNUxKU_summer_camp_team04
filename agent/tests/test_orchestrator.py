"""오케스트레이터 분기 로직 스모크 테스트.

실제 LLM/Agent를 만들지 않도록 build_agent()와 각 결정 함수를 모두 mock 처리해서,
TutorPipeline.run()의 분기 조건만 검증한다.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tutor_agent.agents import action_agent, entry_agent, evaluation_agent, guidance_agent, state_agent  # noqa: E402
from tutor_agent.orchestrator import TutorPipeline  # noqa: E402
from tutor_agent.schemas import (  # noqa: E402
    ActionPlan,
    EntryDecision,
    Evaluation,
    GuidancePlan,
    SessionContext,
    StudentState,
)


def _ctx() -> SessionContext:
    return SessionContext(student_id="s1", problem_id="p1", code="pass")


@patch.object(evaluation_agent, "build_agent", return_value=None)
@patch.object(action_agent, "build_agent", return_value=None)
@patch.object(guidance_agent, "build_agent", return_value=None)
@patch.object(state_agent, "build_agent", return_value=None)
@patch.object(entry_agent, "build_agent", return_value=None)
def test_pipeline_stops_when_entry_declines(*_mocks) -> None:
    with patch.object(
        entry_agent, "decide", return_value=EntryDecision(should_enter=False, reason="아직 이르다")
    ):
        result = TutorPipeline().run(_ctx())

    assert result.entry_decision.should_enter is False
    assert result.student_state is None
    assert result.action_plan is None


@patch.object(evaluation_agent, "build_agent", return_value=None)
@patch.object(action_agent, "build_agent", return_value=None)
@patch.object(guidance_agent, "build_agent", return_value=None)
@patch.object(state_agent, "build_agent", return_value=None)
@patch.object(entry_agent, "build_agent", return_value=None)
def test_pipeline_stops_when_no_intervention_needed(*_mocks) -> None:
    with (
        patch.object(entry_agent, "decide", return_value=EntryDecision(should_enter=True, reason="")),
        patch.object(
            state_agent,
            "assess",
            return_value=StudentState(state_summary="순조로움", should_intervene=False),
        ),
    ):
        result = TutorPipeline().run(_ctx())

    assert result.student_state is not None
    assert result.student_state.should_intervene is False
    assert result.guidance_plan is None


@patch.object(evaluation_agent, "build_agent", return_value=None)
@patch.object(action_agent, "build_agent", return_value=None)
@patch.object(guidance_agent, "build_agent", return_value=None)
@patch.object(state_agent, "build_agent", return_value=None)
@patch.object(entry_agent, "build_agent", return_value=None)
def test_pipeline_runs_full_chain_when_intervention_needed(*_mocks) -> None:
    with (
        patch.object(entry_agent, "decide", return_value=EntryDecision(should_enter=True, reason="")),
        patch.object(
            state_agent,
            "assess",
            return_value=StudentState(
                state_summary="같은 오류 반복", should_intervene=True, urgency="high"
            ),
        ),
        patch.object(
            guidance_agent,
            "plan",
            return_value=GuidancePlan(approach="직접 힌트", message_draft="이 부분을 확인해보세요"),
        ),
        patch.object(
            action_agent,
            "decide",
            return_value=ActionPlan(action_type="send_message", payload={"message": "힌트"}),
        ),
        patch.object(
            evaluation_agent,
            "evaluate",
            return_value=Evaluation(effectiveness_score=0.8, notes="적절함", follow_up_needed=False),
        ),
    ):
        result = TutorPipeline().run(_ctx())

    assert result.action_plan is not None
    assert result.action_plan.action_type == "send_message"
    assert result.evaluation is not None
    assert result.evaluation.effectiveness_score == 0.8
