"""guided_action_agent 스모크 테스트 (LLM 호출 없이 mock).

guidance_agent + action_agent를 합친 모듈이라, `plan()`이 `GuidedAction`을
그대로 돌려주는지와 프롬프트에 필요한 컨텍스트가 들어가는지만 확인한다.
판단 내용 자체(좋은 힌트인지)는 여기서 검증할 수 없다 — 실제 LLM 품질은
agent/README.md에 적어둔 대로 수동/통합 테스트로 확인한다.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tutor_agent.agents import guided_action_agent  # noqa: E402
from tutor_agent.schemas import GuidedAction, SessionContext, StudentState  # noqa: E402


def test_plan_returns_the_agents_structured_output() -> None:
    expected = GuidedAction(
        approach="소크라테스식 질문",
        hint_level="hint",
        message_draft="리스트를 어떻게 순회할까요?",
        action_type="send_message",
        payload={"message": "리스트를 어떻게 순회할까요?"},
    )
    fake_agent = MagicMock()
    fake_agent.structured_output.return_value = expected

    result = guided_action_agent.plan(
        SessionContext(student_id="s1", problem_id="p1"),
        StudentState(state_summary="막힘", should_intervene=True),
        fake_agent,
    )

    assert result is expected
    call_args = fake_agent.structured_output.call_args
    assert call_args.args[0] is GuidedAction


def test_plan_prompt_includes_session_context_and_student_state() -> None:
    """프롬프트에 두 입력이 실제로 실려가는지 — 빠지면 LLM이 맹목적으로 판단한다."""
    fake_agent = MagicMock()
    fake_agent.structured_output.return_value = GuidedAction(
        approach="a", message_draft="m", action_type="no_op"
    )

    guided_action_agent.plan(
        SessionContext(student_id="s1", problem_id="p1", code="def f(): pass"),
        StudentState(state_summary="반복된 실패", should_intervene=True, urgency="high"),
        fake_agent,
    )

    prompt = fake_agent.structured_output.call_args.args[1]
    assert "def f(): pass" in prompt
    assert "반복된 실패" in prompt
