"""problem_generator 파이프라인의 실제(mock 아닌) 통합 테스트.

judge_validator가 judge_service를 실제로 import해서 Docker 샌드박스에서
레퍼런스 코드를 실행한다. 검증을 통과해 만들어진 problem_json을
run_judge_for_problem()에 다시 넣어서 실제로 채점까지 되는지 확인한다 —
"생성 -> 검증 -> 채점"이 실제로 하나의 파이프라인으로 이어지는지가 핵심.

사전 조건 (judge/tests/*와 동일):
  - Docker가 실행 중이어야 함
  - judge/ 디렉터리에서 `docker build -t judge-sandbox .`로 샌드박스 이미지이
    미리 빌드돼 있어야 함
  - `pip install "docker>=7.0"` (agent venv에는 opt-in 설치 필요 — pyproject.toml
    기본 의존성에는 없음. backend의 JUDGE_BACKEND=docker와 같은 이유,
    judge_validator.py 상단 설명 참고)
  - JUDGE_PATH가 실제 judge/ 디렉터리를 가리켜야 함 (.env.example 기본값
    "../judge"면 agent/ 에서 실행 시 그대로 맞음)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tutor_agent.schemas import ProblemTemplate, TestCaseInput  # noqa: E402
from tutor_agent.tools.judge_validator import _import_judge_service, validate_template  # noqa: E402


def test_stdout_match_full_loop_generate_validate_grade():
    """생성된 stdout_match 문제가 검증을 통과하고, 그 결과로 실제 채점까지 된다."""
    template = ProblemTemplate(
        concept=["conditional"],
        title="더 큰 수 찾기",
        description="두 정수 중 더 큰 수를 출력하세요.",
        check_type="stdout_match",
        code_template="# 여기에 코드를 작성하세요\n",
        reference_solution="a, b = map(int, input().split())\nprint(max(a, b))",
        test_case_inputs=[
            TestCaseInput(category="basic", stdin="3 7\n"),
            TestCaseInput(category="negative", stdin="-2 -8\n", is_hidden=True),
            TestCaseInput(category="equal", stdin="5 5\n", is_hidden=True),
        ],
    )

    report = validate_template(template)
    assert report.is_valid, report.error_message
    problem_json = report.problem_json
    assert problem_json["public_test_cases"] == [{"stdin": "3 7\n", "expected_stdout": "7", "category": "basic"}]
    assert {c["category"] for c in problem_json["hidden_test_cases"]} == {"negative", "equal"}

    judge_service = _import_judge_service()

    # 레퍼런스 코드 그대로 제출하면 당연히 만점.
    correct = judge_service.run_judge_for_problem(template.reference_solution, problem_json, mode="submit")
    assert correct["status"] == "ACCEPTED"
    assert correct["passed"] == correct["total"] == 3

    # abs()를 잘못 쓴 흔한 오답 -> 음수 케이스에서만 틀림 (부호를 없애버리는 실수).
    wrong_code = "a, b = map(int, input().split())\nprint(max(abs(a), abs(b)))"
    wrong = judge_service.run_judge_for_problem(wrong_code, problem_json, mode="submit")
    assert wrong["status"] == "WRONG_ANSWER"
    assert wrong["passed"] == 2
    assert wrong["failed_categories"] == ["negative"]

    # mode="run"은 hidden을 절대 채점에 포함하면 안 된다 (여태 "submit"만 테스트해서
    # public/hidden 분리가 실제로 지켜지는지는 검증이 안 돼 있었음).
    run_mode = judge_service.run_judge_for_problem(template.reference_solution, problem_json, mode="run")
    assert run_mode["total"] == 1
    assert run_mode["status"] == "ACCEPTED"


def test_function_call_full_loop_generate_validate_grade():
    """생성된 function_call 문제도 동일하게 생성 -> 검증 -> 채점이 이어진다."""
    template = ProblemTemplate(
        concept=["loop", "comparison"],
        title="리스트 최댓값",
        description="정수 리스트에서 최댓값을 반환하세요.",
        check_type="function_call",
        function_name="find_max",
        code_template="def find_max(arr):\n    # 여기에 코드를 작성하세요\n    pass\n",
        reference_solution="def find_max(arr):\n    return max(arr)",
        test_case_inputs=[
            TestCaseInput(category="basic", input=[[1, 5, 3]]),
            TestCaseInput(category="all_negative", input=[[-4, -1, -9]], is_hidden=True),
        ],
    )

    report = validate_template(template)
    assert report.is_valid, report.error_message
    problem_json = report.problem_json
    assert problem_json["public_test_cases"] == [{"input": [[1, 5, 3]], "expected": 5, "category": "basic"}]
    assert problem_json["hidden_test_cases"] == [
        {"input": [[-4, -1, -9]], "expected": -1, "category": "all_negative"}
    ]

    judge_service = _import_judge_service()

    correct = judge_service.run_judge_for_problem(template.reference_solution, problem_json, mode="submit")
    assert correct["status"] == "ACCEPTED"

    # 최댓값을 0으로 초기화하는 흔한 학생 실수 -> 전부 음수인 리스트에서만 틀림.
    wrong_code = "def find_max(arr):\n    m = 0\n    for x in arr:\n        if x > m:\n            m = x\n    return m"
    wrong = judge_service.run_judge_for_problem(wrong_code, problem_json, mode="submit")
    assert wrong["status"] == "WRONG_ANSWER"
    assert wrong["passed"] == 1
    assert wrong["failed_categories"] == ["all_negative"]


def test_capture_validates_execution_not_semantic_correctness():
    """알려진 한계를 문서화하는 테스트 (버그 아님).

    capture_reference_outputs는 "레퍼런스 코드가 안 죽고 돌아간다"만 확인하고,
    "그 결과가 문제 설명과 실제로 맞는 정답인가"는 검증하지 않는다. 레퍼런스
    코드 자체가 틀리면 그 틀린 값이 그대로 expected로 굳어진다 — 이걸 잡으려면
    교차검증(독립적으로 생성한 레퍼런스 코드 여러 개 비교)이나 mutation
    testing(테스트 판별력 확인)이 추가로 필요한데, 아직 구현 전이라 이 테스트로
    현재 경계를 명시해둔다.
    """
    template = ProblemTemplate(
        concept=["math"],
        title="두 수의 합",
        description="두 정수의 합을 출력하세요.",
        check_type="stdout_match",
        code_template="# 여기에 코드를 작성하세요\n",
        reference_solution="a, b = map(int, input().split())\nprint(a - b)",  # 일부러 틀린 "정답" (합이 아니라 차)
        test_case_inputs=[TestCaseInput(category="basic", stdin="2 3\n")],
    )

    report = validate_template(template)

    # 틀린 레퍼런스 코드인데도 "실행 중 안 죽었다"는 이유만으로 검증을 통과시킨다.
    assert report.is_valid is True
    assert report.problem_json["public_test_cases"][0]["expected_stdout"] == "-1"  # 2-3, 진짜 정답(5)이 아님
