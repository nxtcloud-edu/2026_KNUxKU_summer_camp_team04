"""guided_action_agent 스모크 테스트 (LLM 호출 없이 mock).

`plan()`이 `GuidedAction`을 그대로 돌려주는지와, 프롬프트에 필요한 컨텍스트가
들어가는지만 확인한다. 판단 내용 자체(좋은 지도 계획인지)는 여기서 검증할 수
없다 — 실제 LLM 품질은 agent/README.md에 적어둔 대로 수동/통합 테스트로 확인한다.

이 에이전트는 **학생에게 보낼 문장을 만들지 않는다.** 내부 지시문(focus /
talking_points / avoid / expects_student_reply)만 만들고, 실제 문장은
`tutor_message_agent`가 쓴다 (test_tutor_message_agent.py 참고).
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
        focus="리스트 순회",
        talking_points=["리스트를 어떻게 순회할지 스스로 떠올리게 할 것"],
        avoid=["완성된 for문 코드"],
        expects_student_reply=True,
        action_type="send_message",
        payload={},
    )
    fake_agent = MagicMock()
    fake_agent.structured_output_async.return_value = expected

    result = guided_action_agent.plan(
        SessionContext(student_id="s1", problem_id="p1"),
        StudentState(state_summary="막힘", should_intervene=True),
        fake_agent,
    )

    assert result is expected
    assert fake_agent.structured_output_async.call_args.args[0] is GuidedAction


def test_plan_prompt_includes_session_context_and_student_state() -> None:
    """프롬프트에 두 입력이 실제로 실려가는지 — 빠지면 LLM이 맹목적으로 판단한다."""
    fake_agent = MagicMock()
    fake_agent.structured_output_async.return_value = GuidedAction(
        approach="a", action_type="no_op"
    )

    guided_action_agent.plan(
        SessionContext(student_id="s1", problem_id="p1", code="def f(): pass"),
        StudentState(state_summary="반복된 실패", should_intervene=True, urgency="high"),
        fake_agent,
    )

    prompt = fake_agent.structured_output_async.call_args.args[1]
    assert "def f(): pass" in prompt
    assert "반복된 실패" in prompt


def test_plan_does_not_ask_the_model_to_write_the_student_message() -> None:
    """회귀 방지: 이 에이전트가 다시 작문을 겸하면 내부 어휘가 학생 화면으로 샌다.

    예전 프롬프트에는 `message_draft`("학생에게 보여줄 메시지 초안")가 있었고,
    그 결과 "(지도 방식: 단계별 구조 안내/explain)"처럼 계획용 라벨이 붙은
    문장이 학생에게 그대로 갔다.
    """
    assert "message_draft" not in guided_action_agent.SYSTEM_PROMPT
    assert "message_draft" not in set(GuidedAction.model_fields)
    # 작문은 다음 단계라는 사실이 프롬프트에 명시돼 있어야 한다.
    assert "응답 생성" in guided_action_agent.SYSTEM_PROMPT
