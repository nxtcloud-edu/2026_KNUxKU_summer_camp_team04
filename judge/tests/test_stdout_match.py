"""stdout_match check_type 채점 테스트.

DMOJ 패키지 변환기(scripts/convert_dmoj_package.py)로 만들어진 실제 문제
(stdout_bigger_number)를 사용해 accepted/wrong_answer 시나리오를 검증한다.
SYNTAX_ERROR/TIME_LIMIT은 check_type과 무관하게 run_judge 공통 로직이라
test_judge_service.py에서 이미 검증됨.
"""
from judge_service import run_judge

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
