"""judge_service.capture_reference_outputs()의 시나리오 테스트.

문제 생성 파이프라인이 레퍼런스 정답 코드를 실행해 실제 출력을 캡처하는
경로. run_judge()와 달리 expected와 비교하지 않고 실행 결과 자체를 반환한다.

Docker가 실행 중이어야 하고, 샌드박스 이미지가 미리 빌드돼 있어야 한다:
    docker build -t judge-sandbox .   (judge/ 디렉터리에서)
"""
from judge_service import capture_reference_outputs


def test_stdout_match_captures_actual_output():
    """stdout_match: 레퍼런스 코드를 실제로 실행해 나온 출력을 그대로 반환."""
    result = capture_reference_outputs(
        reference_code="a, b = map(int, input().split())\nprint(a + b)",
        check_type="stdout_match",
        test_case_inputs=[
            {"stdin": "2 3\n", "category": "c1"},
            {"stdin": "10 -4\n", "category": "c2"},
        ],
    )
    assert result["status"] == "OK"
    assert result["outputs"] == [
        {"category": "c1", "output": "5"},
        {"category": "c2", "output": "6"},
    ]


def test_function_call_captures_actual_return_value():
    """function_call: 레퍼런스 함수를 실제로 호출해 나온 리턴값을 그대로 반환."""
    result = capture_reference_outputs(
        reference_code="def sum_list(arr):\n    return sum(arr)\n",
        check_type="function_call",
        function_name="sum_list",
        test_case_inputs=[
            {"input": [[1, 2, 3]], "category": "basic"},
            {"input": [[-1, -2, 3]], "category": "negative_numbers"},
        ],
    )
    assert result["status"] == "OK"
    assert result["outputs"] == [
        {"category": "basic", "output": 6},
        {"category": "negative_numbers", "output": 0},
    ]


def test_syntax_error_short_circuits_before_container():
    """레퍼런스 코드에 문법 오류가 있으면 컨테이너를 띄우지 않고 즉시 반환."""
    result = capture_reference_outputs(
        reference_code="def f(:",
        check_type="stdout_match",
        test_case_inputs=[{"stdin": "", "category": "x"}],
    )
    assert result["status"] == "SYNTAX_ERROR"
    assert "message" in result


def test_time_limit():
    """레퍼런스 코드가 무한루프면 TIME_LIMIT으로 처리 (레퍼런스도 신뢰하지 않음)."""
    result = capture_reference_outputs(
        reference_code="while True:\n    pass\n",
        check_type="stdout_match",
        test_case_inputs=[{"stdin": "", "category": "x"}],
        time_limit_sec=1,
    )
    assert result["status"] == "TIME_LIMIT"


def test_function_call_missing_function_reports_runtime_error():
    """함수 이름이 실제 정의와 다르면 RUNTIME_ERROR로 명확히 알려준다
    (LLM이 code_template의 function_name과 다른 이름으로 정의한 경우를 잡아냄)."""
    result = capture_reference_outputs(
        reference_code="def not_sum_list(arr):\n    return sum(arr)\n",
        check_type="function_call",
        function_name="sum_list",
        test_case_inputs=[{"input": [[1, 2, 3]], "category": "basic"}],
    )
    assert result["status"] == "RUNTIME_ERROR"
    assert "찾을 수 없습니다" in result["message"]


def test_stdout_match_runtime_error_per_case_does_not_abort_batch():
    """stdout_match는 한 케이스가 런타임 오류여도 나머지 케이스는 계속 캡처한다
    (타임아웃만 전체 중단 — run_stdout_match.py와 동일한 정책)."""
    result = capture_reference_outputs(
        reference_code="x = int(input())\nprint(10 // x)",
        check_type="stdout_match",
        test_case_inputs=[
            {"stdin": "0\n", "category": "divide_by_zero"},
            {"stdin": "2\n", "category": "ok"},
        ],
    )
    assert result["status"] == "OK"
    assert result["outputs"][0]["category"] == "divide_by_zero"
    assert "error" in result["outputs"][0]
    assert result["outputs"][1] == {"category": "ok", "output": "5"}


def test_function_call_runtime_error_per_case_does_not_abort_batch():
    """function_call도 stdout_match와 동일한 정책이어야 한다 — 이전에는
    stdout_match만 테스트해서 두 check_type이 실제로 같은 정책인지 확인이
    안 돼 있었음 (run_capture_call.py는 run_capture_stdout.py와 별도 구현이라
    한쪽만 테스트하면 다른 쪽의 회귀를 못 잡음)."""
    result = capture_reference_outputs(
        reference_code="def divide(a, b):\n    return a // b\n",
        check_type="function_call",
        function_name="divide",
        test_case_inputs=[
            {"input": [10, 0], "category": "divide_by_zero"},
            {"input": [10, 2], "category": "ok"},
        ],
    )
    assert result["status"] == "OK"
    assert result["outputs"][0]["category"] == "divide_by_zero"
    assert "error" in result["outputs"][0]
    assert result["outputs"][1] == {"category": "ok", "output": 5}


def test_function_call_time_limit():
    """function_call도 무한루프 레퍼런스 코드에서 TIME_LIMIT으로 처리된다
    (지금까지 TIME_LIMIT은 stdout_match로만 확인했었음)."""
    result = capture_reference_outputs(
        reference_code="def loop_forever(x):\n    while True:\n        pass\n",
        check_type="function_call",
        function_name="loop_forever",
        test_case_inputs=[{"input": [1], "category": "x"}],
        time_limit_sec=1,
    )
    assert result["status"] == "TIME_LIMIT"
