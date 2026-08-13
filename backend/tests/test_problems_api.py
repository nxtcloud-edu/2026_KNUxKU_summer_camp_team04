from __future__ import annotations

import json

from app.problems.service import get_problem_repository


def test_list_problems_returns_three_with_no_test_data(client):
    r = client.get("/problems")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 3
    assert {p["problem_id"] for p in body} == {
        "func_sum_list",
        "func_find_max",
        "func_count_positive",
    }
    # 목록에는 테스트 데이터가 아예 없어야 한다
    for p in body:
        assert "public_test_cases" not in p
        assert "hidden_test_cases" not in p


def test_problem_detail_exposes_public_and_hidden_metadata_only(client):
    r = client.get("/problems/func_sum_list")
    assert r.status_code == 200
    body = r.json()

    assert body["description"]
    assert body["code_template"].startswith("def sum_list(arr):")
    assert body["function_name"] == "sum_list"
    assert len(body["public_test_cases"]) == 1
    assert body["hidden_test_case_count"] == 3
    assert set(body["hidden_test_categories"]) == {
        "negative_numbers",
        "boundary_case",
        "empty_list",
    }
    assert "hidden_test_cases" not in body


ALLOWED_DETAIL_KEYS = {
    "problem_id",
    "title",
    "concepts",
    "difficulty",
    "function_name",
    "description",
    "code_template",
    "check_type",
    "public_test_cases",
    "hidden_test_case_count",
    "hidden_test_categories",
}


def test_problem_detail_has_no_field_capable_of_holding_hidden_data(client):
    """유출 방지가 절차가 아니라 구조라는 것을 실행 가능하게 만든 가드.

    응답 키를 allowlist와 정확히 대조한다. 나중에 누가 ProblemDetail에 필드를
    추가하면 -- 그게 hidden 데이터를 담든 안 담든 -- 이 테스트가 먼저 실패하고
    사람이 그 필드를 의식적으로 allowlist에 넣게 된다.
    """
    repo = get_problem_repository()
    for record in repo.list():
        body = client.get(f"/problems/{record.problem_id}").json()
        assert set(body.keys()) == ALLOWED_DETAIL_KEYS, record.problem_id


def test_hidden_test_inputs_never_reach_the_client(client):
    """hidden input(리스트라 충분히 특징적이다)이 응답 본문에 나타나면 안 된다.

    expected는 0이나 3 같은 스칼라라 설명문 안의 숫자와 우연히 겹친다 --
    substring 검사가 무의미하므로 위의 구조적 가드가 그 몫을 담당한다.
    """
    repo = get_problem_repository()
    for record in repo.list():
        body = client.get(f"/problems/{record.problem_id}").text
        for tc in record.hidden_test_cases:
            assert json.dumps(tc.input) not in body
            assert json.dumps(tc.input, ensure_ascii=False) not in body


def test_unknown_problem_returns_404(client):
    r = client.get("/problems/nope")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "PROBLEM_NOT_FOUND"
    assert r.json()["detail"]["context"]["problem_id"] == "nope"
