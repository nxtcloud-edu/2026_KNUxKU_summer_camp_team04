"""학생 답변 평가 에이전트 테스트 (LLM 호출 없이 mock).

이 에이전트는 원래 "AI가 방금 한 개입이 적절했는지"를 스스로 채점하고 있었고,
결과는 로그 한 줄로 끝나 아무 동작도 바꾸지 않았다. 지금은 **학생의 답변**을
평가하고, 그 결과가 다음 응답을 실제로 바꾼다 (`evaluation_agent.py` docstring).

여기서 검증하는 것은 평가 품질이 아니라 배선이다: 평가에 필요한 재료(질문,
학생 답변, 문제/코드 맥락)가 프롬프트에 실제로 들어가는가.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tutor_agent.agents import evaluation_agent  # noqa: E402
from tutor_agent.schemas import (  # noqa: E402
    AnswerEvaluation,
    SessionContext,
    StudentReply,
)


def _ctx() -> SessionContext:
    return SessionContext(
        student_id="sess-1",
        problem_id="func_count_even",
        code="def count_even(xs):\n    for x in xs:\n        count = 0\n",
        backend_signals={
            "problem": {
                "problem_id": "func_count_even",
                "title": "짝수 개수 세기",
                "function_name": "count_even",
            }
        },
    )


def _fake_agent(**overrides) -> MagicMock:
    data = {"understanding": "partial", "is_correct": False}
    data.update(overrides)
    agent = MagicMock()
    agent.structured_output_async.return_value = AnswerEvaluation(**data)
    return agent


def test_evaluate_answer_returns_the_structured_output() -> None:
    agent = _fake_agent(understanding="solid", is_correct=True, follow_up_needed=False)

    result = evaluation_agent.evaluate_answer(
        _ctx(), StudentReply(answer="0으로요", question="어떤 값으로 시작할까요?"), agent
    )

    assert isinstance(result, AnswerEvaluation)
    assert result.understanding == "solid"
    assert result.follow_up_needed is False
    assert agent.structured_output_async.call_args.args[0] is AnswerEvaluation


def test_prompt_contains_the_question_and_the_answer() -> None:
    """둘 중 하나라도 빠지면 평가가 불가능하다 — "0으로요"가 정답인지는 질문을 봐야 안다."""
    agent = _fake_agent()

    evaluation_agent.evaluate_answer(
        _ctx(),
        StudentReply(answer="0으로요", question="count는 어떤 값으로 시작할까요?"),
        agent,
    )
    prompt = agent.structured_output_async.call_args.args[1]

    assert "count는 어떤 값으로 시작할까요?" in prompt
    assert "0으로요" in prompt


def test_prompt_contains_the_problem_and_code_context() -> None:
    """짧은 답이 맞는지 판단하려면 학생 코드도 봐야 한다."""
    agent = _fake_agent()

    evaluation_agent.evaluate_answer(_ctx(), StudentReply(answer="0으로요"), agent)
    prompt = agent.structured_output_async.call_args.args[1]

    assert "짝수 개수 세기" in prompt
    assert "count_even" in prompt
    assert "for x in xs" in prompt


def test_prompt_marks_a_missing_question_instead_of_pretending_one_exists() -> None:
    """학생이 먼저 말을 건 경우(직전 질문 없음)를 평가자가 알 수 있어야 한다."""
    agent = _fake_agent()

    evaluation_agent.evaluate_answer(_ctx(), StudentReply(answer="이거 왜 안 되나요?"), agent)
    prompt = agent.structured_output_async.call_args.args[1]

    assert "기록 없음" in prompt


def test_it_no_longer_grades_the_ai_s_own_intervention() -> None:
    """회귀 방지: 자기 개입 채점(effectiveness_score) 시절의 계약이 남아 있지 않아야 한다."""
    assert not hasattr(evaluation_agent, "evaluate")  # 옛 함수명
    assert "effectiveness_score" not in set(AnswerEvaluation.model_fields)
    # 평가 대상이 학생 답변이라는 사실이 프롬프트에 명시돼 있다.
    assert "학생 답변 평가" in evaluation_agent.SYSTEM_PROMPT
    assert "그 답변을 평가하세요" in evaluation_agent.SYSTEM_PROMPT


def test_system_prompt_keeps_the_grader_out_of_the_students_view() -> None:
    """평가 결과는 내부용이다. 평가자가 학생에게 할 말을 쓰기 시작하면 톤 규칙이 두 곳으로 갈린다."""
    assert "내부용" in evaluation_agent.SYSTEM_PROMPT
    assert "학생에게 할 말을 쓰지 말고" in evaluation_agent.SYSTEM_PROMPT
