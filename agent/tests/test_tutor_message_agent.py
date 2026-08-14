"""응답 생성 에이전트 테스트 (LLM 호출 없이 mock).

이 에이전트가 만드는 문장만 학생에게 노출되므로, 검증의 초점은 **프롬프트에
무엇이 들어가고 무엇이 들어가지 않는가**다. LLM 출력 품질은 여기서 검증할 수
없지만, "유출될 수 있는 재료를 애초에 프롬프트에 넣지 않았다"는 것은 검증할 수
있다 — 실제 사고가 그 재료(유휴 시간, 힌트 횟수, 3인칭 상태 요약)를 프롬프트에
넣은 데서 나왔기 때문이다.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tutor_agent.agents import tutor_message_agent  # noqa: E402
from tutor_agent.schemas import (  # noqa: E402
    AnswerEvaluation,
    GuidancePlan,
    SessionContext,
    StudentReply,
    TutorMessage,
)


def _ctx() -> SessionContext:
    """실제 backend 경로가 채우는 것과 같은 모양 — 텔레메트리까지 들어 있다."""
    return SessionContext(
        student_id="sess-1",
        problem_id="func_count_even",
        code="def count_even(xs):\n    for x in xs:\n",
        run_history=["[run] SYNTAX_ERROR 0/5 tests passed"],
        elapsed_seconds=1900.0,
        idle_seconds=1879.0,
        last_error="SYNTAX_ERROR",
        edit_churn_count=4,
        backend_signals={
            "process_status": "STUCK",
            "trigger": "NO_PROGRESS",
            "evidence": ["24분간 편집 없음", "동일 결과 0/5 ×3"],
            "problem": {
                "problem_id": "func_count_even",
                "title": "짝수 개수 세기",
                "concepts": ["loop"],
                "description_summary": "리스트에서 짝수의 개수를 반환하세요.",
                "function_name": "count_even",
            },
            "judge_result": {"status": "SYNTAX_ERROR", "passed": 0, "total": 5},
            "features": {"seconds_without_progress": 1879, "hint_count": 6},
        },
    )


def _plan(**overrides) -> GuidancePlan:
    data = {
        "approach": "단계별 구조 안내",
        "hint_level": "explain",
        "focus": "카운터 변수 초기화",
        "talking_points": ["count = 0을 반복문 앞에 두는 이유를 떠올리게 할 것"],
        "avoid": ["완성된 for문 코드"],
        "expects_student_reply": False,
    }
    data.update(overrides)
    return GuidancePlan(**data)


def _fake_agent(message: str = "좋아요, 다음 한 걸음만 볼까요?") -> MagicMock:
    agent = MagicMock()
    agent.structured_output_async.return_value = TutorMessage(message=message)
    return agent


def _prompt_of(agent: MagicMock) -> str:
    return agent.structured_output_async.call_args.args[1]


# --- write_intervention() ----------------------------------------------------


def test_write_intervention_returns_the_structured_output() -> None:
    agent = _fake_agent("count를 어떤 값으로 시작하면 좋을까요?")

    result = tutor_message_agent.write_intervention(_ctx(), _plan(), agent)

    assert isinstance(result, TutorMessage)
    assert result.message == "count를 어떤 값으로 시작하면 좋을까요?"
    assert agent.structured_output_async.call_args.args[0] is TutorMessage


def test_prompt_carries_the_problem_and_the_students_code() -> None:
    """학생 코드가 없으면 구체적인 문장을 쓸 수 없다."""
    agent = _fake_agent()

    tutor_message_agent.write_intervention(_ctx(), _plan(), agent)
    prompt = _prompt_of(agent)

    assert "짝수 개수 세기" in prompt
    assert "count_even" in prompt
    assert "for x in xs" in prompt
    assert "SYNTAX_ERROR" in prompt


def test_prompt_carries_the_plan_as_writing_instructions() -> None:
    agent = _fake_agent()

    tutor_message_agent.write_intervention(_ctx(), _plan(), agent)
    prompt = _prompt_of(agent)

    assert "카운터 변수 초기화" in prompt
    assert "count = 0을 반복문 앞에 두는 이유를 떠올리게 할 것" in prompt
    assert "완성된 for문 코드" in prompt


def test_prompt_excludes_the_telemetry_that_leaked_into_student_messages() -> None:
    """회귀 테스트 (핵심).

    실제 사고: 작문 컨텍스트에 개입 판단용 텔레메트리가 그대로 들어가 있어서
    모델이 그걸 문장으로 옮겼다 — "31분 넘게 완전히 막혀 있습니다 ... 힌트를
    6회 요청했지만 진전이 없습니다". 학생에게 필요한 정보가 아니고, 오래
    걸렸다는 통보는 도움이 아니라 압박이다.

    `prompt_context.student_situation()`이 이 값들을 의도적으로 뺀다.
    """
    agent = _fake_agent()

    tutor_message_agent.write_intervention(_ctx(), _plan(), agent)
    prompt = _prompt_of(agent)

    assert "1879" not in prompt  # 유휴 시간(초)
    assert "seconds_without_progress" not in prompt
    assert "hint_count" not in prompt
    assert "24분간 편집 없음" not in prompt  # Monitor evidence
    assert "edit_churn_count" not in prompt


def test_prompt_excludes_the_third_person_state_summary() -> None:
    """3인칭 분석문이 프롬프트에 있으면 모델이 그 톤을 그대로 베낀다.

    그 분석에서 뽑아낸 지도용 결론은 이미 plan.focus/talking_points로 전달되므로
    정보가 유실되지도 않는다.
    """
    agent = _fake_agent()

    tutor_message_agent.write_intervention(_ctx(), _plan(), agent)
    prompt = _prompt_of(agent)

    assert "학생은" not in prompt
    # 내부 어휘 라벨도 그대로 넣지 않는다 (넣으면 결과 문장에 섞여 나온다).
    assert "hint_level" not in prompt
    assert "approach" not in prompt
    assert "지도 방식" not in prompt


def test_system_prompt_forbids_the_observed_failure_modes() -> None:
    """관찰된 유출 유형을 프롬프트가 명시적으로 금지하고 있어야 한다."""
    system = tutor_message_agent.SYSTEM_PROMPT

    assert "3인칭" in system
    assert "지도 방식" in system
    assert "31분" in system  # 통계 들이대기 금지 예시
    assert "2인칭" in system


def test_expecting_a_reply_is_passed_through_to_the_writer() -> None:
    agent = _fake_agent()

    tutor_message_agent.write_intervention(_ctx(), _plan(expects_student_reply=True), agent)

    assert "expects_reply=true" in _prompt_of(agent)


# --- write_follow_up() -------------------------------------------------------


def _evaluation(**overrides) -> AnswerEvaluation:
    data = {
        "understanding": "partial",
        "is_correct": False,
        "evidence": "초기값은 맞혔지만 위치를 틀렸습니다.",
        "misconceptions": ["초기화를 반복문 안에서 해도 된다고 생각함"],
        "follow_up_needed": True,
        "next_focus": "초기화 위치",
    }
    data.update(overrides)
    return AnswerEvaluation(**data)


def test_follow_up_prompt_carries_the_question_and_the_answer() -> None:
    agent = _fake_agent()
    reply = StudentReply(answer="0으로요. 반복문 안에서요.", question="언제 초기화해야 할까요?")

    tutor_message_agent.write_follow_up(_ctx(), reply, _evaluation(), agent)
    prompt = _prompt_of(agent)

    assert "언제 초기화해야 할까요?" in prompt
    assert "0으로요. 반복문 안에서요." in prompt


def test_follow_up_stance_changes_with_understanding() -> None:
    """평가 결과가 실제로 응답 방식을 바꾸는지 — 이게 학습 루프가 닫히는 지점이다."""
    reply = StudentReply(answer="0으로요", question="언제 초기화해야 할까요?")

    prompts = {}
    for level in ("none", "partial", "solid"):
        agent = _fake_agent()
        tutor_message_agent.write_follow_up(
            _ctx(), reply, _evaluation(understanding=level), agent
        )
        prompts[level] = _prompt_of(agent)

    assert "더 쉬운" in prompts["none"]  # 못 이해했으면 더 쉬운 질문으로
    assert "맞은 부분을 먼저 인정" in prompts["partial"]  # 절반이면 빠진 조각만
    assert "다음 한 걸음" in prompts["solid"]  # 이해했으면 다음 단계로
    assert len(set(prompts.values())) == 3  # 세 경우가 실제로 다르다


def test_follow_up_does_not_expose_evaluation_labels_to_the_writer() -> None:
    """"당신의 이해도는 partial입니다"가 학생에게 가지 않도록, 라벨 자체를 넣지 않는다."""
    agent = _fake_agent()

    tutor_message_agent.write_follow_up(
        _ctx(), StudentReply(answer="0으로요"), _evaluation(), agent
    )
    prompt = _prompt_of(agent)

    assert "partial" not in prompt
    assert "understanding" not in prompt
    assert "is_correct" not in prompt


def test_follow_up_without_a_recorded_question_still_works() -> None:
    """학생이 질문 없는 힌트 뒤에 먼저 말을 건 경우 (question이 빈 문자열)."""
    agent = _fake_agent()

    result = tutor_message_agent.write_follow_up(
        _ctx(), StudentReply(answer="이거 왜 안 되나요?"), _evaluation(), agent
    )

    assert isinstance(result, TutorMessage)
    assert "이거 왜 안 되나요?" in _prompt_of(agent)
