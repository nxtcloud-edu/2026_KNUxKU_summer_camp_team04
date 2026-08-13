"""main.py(FastAPI 래퍼)의 엔드포인트 테스트.

/problems, /problems/{id}는 Docker 없이도 검증 가능. /judge는 실제 채점을
타므로 다른 테스트들처럼 Docker가 필요하다.
"""
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_get_problems_returns_list_without_test_cases():
    res = client.get("/problems")
    assert res.status_code == 200
    problems = res.json()
    assert len(problems) == 26
    assert "public_test_cases" not in problems[0]
    ids = {p["problem_id"] for p in problems}
    assert "func_sum_list" in ids
    assert "stdout_bigger_number" in ids


def test_get_problem_detail_excludes_hidden():
    res = client.get("/problems/func_sum_list")
    assert res.status_code == 200
    detail = res.json()
    assert detail["problem_id"] == "func_sum_list"
    assert "description" in detail
    assert "public_test_cases" in detail
    assert "hidden_test_cases" not in detail


def test_get_problem_detail_404_for_unknown_id():
    res = client.get("/problems/no_such_problem")
    assert res.status_code == 404


def test_judge_endpoint_accepted():
    res = client.post("/judge", json={
        "student_code": "def sum_list(arr):\n    return sum(arr)\n",
        "problem_id": "func_sum_list",
        "mode": "submit",
    })
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ACCEPTED"
    assert body["passed"] == body["total"]


def test_judge_endpoint_404_for_unknown_problem():
    res = client.post("/judge", json={
        "student_code": "pass",
        "problem_id": "no_such_problem",
        "mode": "run",
    })
    assert res.status_code == 404
