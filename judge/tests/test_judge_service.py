"""judge_service.run_judge()의 4대 시나리오 + 런타임에러 테스트.

Docker가 실행 중이어야 하고, 샌드박스 이미지가 미리 빌드돼 있어야 한다:
    docker build -t judge-sandbox .   (judge/ 디렉터리에서)
"""
import pytest

from judge_service import get_problem_detail, run_judge

PROBLEM_ID = "func_sum_list"


def test_get_problem_detail_excludes_hidden_test_cases():
    """프론트에 노출되는 상세 정보에 hidden_test_cases(정답)가 절대 섞이면 안 됨."""
    detail = get_problem_detail(PROBLEM_ID)
    assert "hidden_test_cases" not in detail
    assert "public_test_cases" in detail
    assert "description" in detail
    assert detail["problem_id"] == PROBLEM_ID


def test_accepted():
    """정상 코드 -> 모든 테스트 통과."""
    code = "def sum_list(arr):\n    return sum(arr)\n"
    result = run_judge(code, PROBLEM_ID, mode="submit")
    assert result["status"] == "ACCEPTED"
    assert result["passed"] == result["total"]


def test_wrong_answer():
    """오답 코드 -> 일부 테스트만 통과, failed_categories 포함."""
    code = "def sum_list(arr):\n    return 0\n"
    result = run_judge(code, PROBLEM_ID, mode="submit")
    assert result["status"] == "WRONG_ANSWER"
    assert result["passed"] < result["total"]
    assert "failed_categories" in result


def test_syntax_error():
    """문법 오류 -> 컨테이너를 띄우지 않고 즉시 SYNTAX_ERROR."""
    code = "def sum_list(arr)\n    return sum(arr)\n"  # 콜론 누락
    result = run_judge(code, PROBLEM_ID, mode="run")
    assert result["status"] == "SYNTAX_ERROR"
    assert result["passed"] == 0
    assert "message" in result


def test_time_limit():
    """무한루프 -> 5초 타임아웃으로 TIME_LIMIT."""
    code = "def sum_list(arr):\n    while True:\n        pass\n"
    result = run_judge(code, PROBLEM_ID, mode="run")
    assert result["status"] == "TIME_LIMIT"
    assert result["passed"] == 0


def test_runtime_error():
    """함수 내부에서 예외 발생 -> 해당 테스트는 실패 처리(런타임 오류는
    문법상 유효한 코드라 함수 자체는 정상 정의되므로 WRONG_ANSWER로 집계됨).
    함수 자체가 없는 경우는 RUNTIME_ERROR로 별도 처리된다."""
    code = "def not_sum_list(arr):\n    return sum(arr)\n"  # 함수명이 다름
    result = run_judge(code, PROBLEM_ID, mode="run")
    assert result["status"] == "RUNTIME_ERROR"
    assert "찾을 수 없습니다" in result["message"]


def test_runtime_error_reports_specific_exception():
    """회귀 테스트: 모듈 최상위(exec 단계)에서 예외가 나면, 뭉뚱그린 메시지가
    아니라 실제 예외 타입/메시지가 그대로 나와야 한다 (Agent가 last_error로
    구체적인 힌트를 만들 때 필요 — 자식 프로세스 격리 리팩터링 과정에서
    한 번 뭉개졌던 정보라 회귀 방지용으로 추가함)."""
    code = "def sum_list(arr):\n    return sum(arr)\nundefined_variable_boom\n"
    result = run_judge(code, PROBLEM_ID, mode="run")
    assert result["status"] == "RUNTIME_ERROR"
    assert "NameError" in result["message"]
    assert "undefined_variable_boom" in result["message"]


def test_cannot_forge_result_via_sys_exit():
    """회귀 테스트: 학생 코드가 가짜 채점 결과를 stdout에 출력하고
    sys.exit()으로 강제 종료해도 결과를 조작할 수 없어야 한다.

    (하네스가 학생 코드를 자기 프로세스에서 직접 exec하던 시절엔, 학생이
    가짜 JSON을 찍고 sys.exit(0)하면 하네스의 진짜 결과 print()가 실행되지
    못해 그 가짜 결과가 그대로 채점 결과로 둔갑했음 — 실제로 ACCEPTED 4/4를
    받아내는 것까지 재현된 적 있는 취약점.)
    """
    code = (
        "import json, sys\n"
        "def sum_list(arr):\n"
        "    print(json.dumps({'results': [\n"
        "        {'category': 'basic', 'passed': True},\n"
        "        {'category': 'negative_numbers', 'passed': True},\n"
        "        {'category': 'boundary_case', 'passed': True},\n"
        "        {'category': 'empty_list', 'passed': True},\n"
        "    ]}))\n"
        "    sys.exit(0)\n"
    )
    result = run_judge(code, PROBLEM_ID, mode="submit")
    assert result["status"] == "WRONG_ANSWER"
    assert result["passed"] == 0
