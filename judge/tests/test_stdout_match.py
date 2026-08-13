"""stdout_match check_type 채점 테스트.

DMOJ 패키지 변환기(scripts/convert_dmoj_package.py)로 만들어진 실제 문제
(stdout_bigger_number)를 사용해 accepted/wrong_answer 시나리오를 검증한다.
SYNTAX_ERROR/TIME_LIMIT은 check_type과 무관하게 run_judge 공통 로직이라
test_judge_service.py에서 이미 검증됨.
"""
from judge_service import load_problem, run_judge

PROBLEM_ID = "stdout_bigger_number"


def test_accepted():
    code = "a, b = map(int, input().split())\nprint(1 if b > a else 0)\n"
    result = run_judge(code, PROBLEM_ID, mode="submit")
    assert result["status"] == "ACCEPTED"
    assert result["passed"] == result["total"]


def test_wrong_answer():
    code = "a, b = map(int, input().split())\nprint(0)\n"
    result = run_judge(code, PROBLEM_ID, mode="submit")
    assert result["status"] == "WRONG_ANSWER"
    assert result["passed"] < result["total"]
    assert "failed_categories" in result


def test_custom_time_limit_from_problem_json():
    """stdout_bigger_number는 DMOJ 원본의 time_limit_sec=1.0을 그대로 갖고
    있어야 하고, 무한루프는 그 값(테스트케이스 1개당) 안에서 TIME_LIMIT으로
    잡혀야 한다 (기본값 5초가 아니라 문제별 값이 실제로 적용되는지 확인)."""
    problem = load_problem(PROBLEM_ID)
    assert problem["time_limit_sec"] == 1.0

    code = "while True:\n    pass\n"
    result = run_judge(code, PROBLEM_ID, mode="run")
    assert result["status"] == "TIME_LIMIT"
    assert "1.0" in result["message"]
