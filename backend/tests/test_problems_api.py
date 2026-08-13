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
    "concept",  # 단수. 문제 JSON/judge/프론트가 전부 단수를 쓴다
    "difficulty",
    "function_name",
    "description",
    "code_template",
    "check_type",
    "public_test_cases",
    "hidden_test_case_count",
    "hidden_test_categories",
    "time_limit_sec",
    "memory_limit_mb",
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
    """hidden 입력이 응답 본문에 나타나면 안 된다.

    check_type에 따라 입력이 사는 필드가 다르다 -- function_call은 `input`(리스트),
    stdout_match는 `stdin`(문자열). **둘 다 검사한다.** 한쪽만 보면 stdout 문제
    23개의 hidden stdin이 검사 없이 통과한다.

    expected는 0이나 3 같은 스칼라라 설명문 안의 숫자와 우연히 겹친다 --
    substring 검사가 무의미하므로 위의 구조적 가드가 그 몫을 담당한다.
    """
    repo = get_problem_repository()
    checked = 0
    for record in repo.list():
        body = client.get(f"/problems/{record.problem_id}").text
        for tc in record.hidden_test_cases:
            if tc.input is not None:
                assert json.dumps(tc.input) not in body
                assert json.dumps(tc.input, ensure_ascii=False) not in body
                checked += 1
            if tc.stdin:
                assert tc.stdin not in body
                assert json.dumps(tc.stdin) not in body
                checked += 1
    assert checked > 0, "hidden 케이스를 하나도 검사하지 못했다 -- 가드가 무력하다"


def test_hidden_leak_guard_covers_judge_dataset():
    """위 가드는 현재 PROBLEMS_DIR(func 3개)만 훑는다.

    프로덕션은 judge/problems 26개를 쓰므로, stdout_match 쪽 hidden stdin도
    실제로 새지 않는지 여기서 직접 확인한다.

    **expected_stdout은 검사하지 않는다.** 값이 "0\\n" 같은 스칼라라 같은 문제의
    public 케이스 정답과 그대로 겹친다 -- substring 검사로는 유출과 우연을
    구분할 수 없다. 짧은 stdin도 같은 이유로 건너뛴다. 진짜 방어는 위의
    구조적 가드(ALLOWED_DETAIL_KEYS)이고, 이건 보조 확인이다.
    """
    from pathlib import Path

    from app.problems.schemas import ProblemDetail
    from app.problems.service import ProblemRepository

    judge_dir = Path(__file__).resolve().parents[2] / "judge" / "problems"
    repo = ProblemRepository(judge_dir)
    assert len(repo.list()) == 26

    stdout_checked = 0
    for record in repo.list():
        detail = ProblemDetail.from_record(record)
        body = detail.model_dump_json()

        # 구조적 보장: hidden을 담을 그릇이 애초에 없다
        assert "hidden_test_cases" not in detail.model_dump()

        for tc in record.hidden_test_cases:
            # 짧은 값은 public과 우연히 겹치므로 판별력이 있는 것만 검사한다
            if tc.stdin and len(tc.stdin.strip()) >= 8:
                assert tc.stdin not in body, record.problem_id
                stdout_checked += 1
    assert stdout_checked > 0, "판별력 있는 hidden stdin을 하나도 검사하지 못했다"


def test_unknown_problem_returns_404(client):
    r = client.get("/problems/nope")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "PROBLEM_NOT_FOUND"
    assert r.json()["detail"]["context"]["problem_id"] == "nope"
