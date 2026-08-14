"""problem_generator_agent / judge_validator 스모크 테스트.

실제 LLM이나 Docker는 쓰지 않는다 — judge_service를 가짜(fake) 모듈로
대체해서 judge_validator.validate_template()의 분기만 검증하고,
problem_generator_agent.generate()는 LLM 호출과 validate_template()을 모두
mock해서 재시도 루프만 검증한다.

에이전트 코드는 `agent.structured_output()`을 직접 부르지 않고
`llm_runtime.structured_output()`을 경유한다 (이유는 그 모듈 docstring 참고 —
캐시된 클라이언트를 매번 새 이벤트 루프에서 쓰다가 멈추거나 터지는 문제).
그래서 mock도 `structured_output_async` 쪽에 건다.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tutor_agent.agents import problem_generator_agent  # noqa: E402
from tutor_agent.schemas import ProblemTemplate, ReviewRequest, TestCaseInput, ValidationReport  # noqa: E402
from tutor_agent.tools import judge_validator  # noqa: E402


def _template(**overrides) -> ProblemTemplate:
    defaults = dict(
        concept=["loop"],
        title="정수 리스트 합",
        description="정수 리스트가 주어지면 합을 출력하세요.",
        check_type="stdout_match",
        code_template="# 여기에 코드를 작성하세요\n",
        reference_solution="print(sum(map(int, input().split())))",
        test_case_inputs=[
            TestCaseInput(category="c1", stdin="1 2 3\n"),
            TestCaseInput(category="c2", stdin="0\n", is_hidden=True),
        ],
    )
    defaults.update(overrides)
    return ProblemTemplate(**defaults)


def _fake_judge_service(capture_return: dict) -> SimpleNamespace:
    return SimpleNamespace(
        DEFAULT_TIME_LIMIT_SEC=5,
        DEFAULT_MEM_LIMIT_MB=128,
        capture_reference_outputs=MagicMock(return_value=capture_return),
    )


def test_validate_template_builds_problem_json_on_success():
    fake_judge = _fake_judge_service({
        "status": "OK",
        "outputs": [
            {"category": "c1", "output": "6"},
            {"category": "c2", "output": "0"},
        ],
    })

    with patch.object(judge_validator, "_import_judge_service", return_value=fake_judge):
        report = judge_validator.validate_template(_template())

    assert report.is_valid is True
    assert report.problem_json["public_test_cases"] == [
        {"stdin": "1 2 3\n", "expected_stdout": "6", "category": "c1"}
    ]
    assert report.problem_json["hidden_test_cases"] == [
        {"stdin": "0\n", "expected_stdout": "0", "category": "c2"}
    ]
    assert "problem_id" not in report.problem_json


def test_validate_template_rejects_when_reference_errors():
    fake_judge = _fake_judge_service({"status": "SYNTAX_ERROR", "message": "invalid syntax"})

    with patch.object(judge_validator, "_import_judge_service", return_value=fake_judge):
        report = judge_validator.validate_template(_template())

    assert report.is_valid is False
    assert "SYNTAX_ERROR" in report.error_message
    assert report.problem_json is None


def test_validate_template_rejects_when_some_inputs_error_out():
    fake_judge = _fake_judge_service({
        "status": "OK",
        "outputs": [
            {"category": "c1", "output": "6"},
            {"category": "c2", "error": "ZeroDivisionError"},
        ],
    })

    with patch.object(judge_validator, "_import_judge_service", return_value=fake_judge):
        report = judge_validator.validate_template(_template())

    assert report.is_valid is False
    assert report.failed_categories == ["c2"]


def test_validate_template_rejects_duplicate_categories_before_calling_judge():
    """회귀 테스트: category가 중복되면 Docker를 띄우지도 않고 즉시 반려한다.

    이전 구현은 category를 key로 쓰는 dict로 출력을 매칭했는데, category가
    중복되면 서로 다른 테스트케이스의 expected 값이 뒤섞이는 버그가 실제로
    있었다 (예: 입력 "AAA"인 public 케이스가 "BBB"의 출력을 expected로
    받아버림). 지금은 애초에 중복을 걸러내서 컨테이너도 안 띄운다."""
    template = _template(
        test_case_inputs=[
            TestCaseInput(category="dup", stdin="AAA\n"),
            TestCaseInput(category="dup", stdin="BBB\n", is_hidden=True),
        ]
    )

    with patch.object(judge_validator, "_import_judge_service") as mock_import:
        report = judge_validator.validate_template(template)

    assert report.is_valid is False
    assert "dup" in report.error_message
    mock_import.assert_not_called()


def test_generate_returns_first_success_without_retrying():
    request = ReviewRequest(student_id="s1", concept="loop")
    fake_agent = MagicMock()
    fake_agent.structured_output_async.return_value = _template()

    with patch.object(
        problem_generator_agent,
        "validate_template",
        return_value=ValidationReport(is_valid=True, problem_json={}),
    ) as mock_validate:
        report = problem_generator_agent.generate(request, fake_agent)

    assert report.is_valid is True
    assert fake_agent.structured_output_async.call_count == 1
    assert mock_validate.call_count == 1


def test_generate_retries_up_to_max_then_returns_last_failure():
    request = ReviewRequest(student_id="s1", concept="loop")
    fake_agent = MagicMock()
    fake_agent.structured_output_async.return_value = _template()

    with patch.object(
        problem_generator_agent,
        "validate_template",
        return_value=ValidationReport(is_valid=False, error_message="레퍼런스 코드 실행 실패"),
    ):
        report = problem_generator_agent.generate(request, fake_agent)

    assert report.is_valid is False
    assert fake_agent.structured_output_async.call_count == problem_generator_agent.MAX_RETRIES + 1


def test_generate_survives_structured_output_raising():
    """회귀 테스트: LLM이 스키마에 안 맞는 응답을 내면 agent.structured_output()
    자체가 예외를 던진다 (실제로 관찰됨 — test_case_inputs를 리스트가 아니라
    range() 표현식이 섞인 문자열로 반환한 사례). 이걸 못 잡으면 generate()가
    그냥 죽어서 재시도 루프가 통째로 무의미해진다."""
    request = ReviewRequest(student_id="s1", concept="loop")
    fake_agent = MagicMock()
    fake_agent.structured_output_async.side_effect = [
        ValueError("1 validation error for ProblemTemplate: test_case_inputs must be a list"),
        _template(),
    ]

    with patch.object(problem_generator_agent, "validate_template", return_value=ValidationReport(is_valid=True, problem_json={})):
        report = problem_generator_agent.generate(request, fake_agent)

    assert report.is_valid is True
    assert fake_agent.structured_output_async.call_count == 2


def test_generate_recovers_on_a_later_attempt():
    """1차 시도가 실패해도, 재시도에서 성공하면 거기서 멈추고 그 결과를 반환한다
    (항상 즉시 성공/항상 실패만 테스트하면 중간 회복 경로가 안 잡힘)."""
    request = ReviewRequest(student_id="s1", concept="loop")
    fake_agent = MagicMock()
    fake_agent.structured_output_async.return_value = _template()

    failure = ValidationReport(is_valid=False, error_message="레퍼런스 코드 실행 실패")
    success = ValidationReport(is_valid=True, problem_json={"title": "고쳐진 문제"})

    with patch.object(problem_generator_agent, "validate_template", side_effect=[failure, success]) as mock_validate:
        report = problem_generator_agent.generate(request, fake_agent)

    assert report.is_valid is True
    assert report.problem_json["title"] == "고쳐진 문제"
    assert fake_agent.structured_output_async.call_count == 2
    assert mock_validate.call_count == 2


def test_generate_feeds_failure_reason_back_into_retry_prompt():
    """재시도 루프의 핵심은 실패 이유를 다음 프롬프트에 실어 보내는 것이다 —
    호출 횟수만 맞아도 이 피드백이 실제로 안 들어가면 재시도가 무의미해진다."""
    request = ReviewRequest(student_id="s1", concept="loop")
    fake_agent = MagicMock()
    fake_agent.structured_output_async.return_value = _template()

    failure = ValidationReport(
        is_valid=False, error_message="레퍼런스 코드 실행 실패 (SYNTAX_ERROR)", failed_categories=["c2"]
    )
    with patch.object(problem_generator_agent, "validate_template", return_value=failure):
        problem_generator_agent.generate(request, fake_agent)

    second_call_prompt = fake_agent.structured_output_async.call_args_list[1].args[1]
    assert "SYNTAX_ERROR" in second_call_prompt
    assert "c2" in second_call_prompt
