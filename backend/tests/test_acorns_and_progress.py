"""도토리 원장 · 진행 상태 · 정답 보상.

핵심 성질: **지급과 차감은 전부 서버가 정한다.** 프런트가 보낸 금액도,
프런트가 보고한 채점 결과도 근거가 되지 않는다.
"""
from __future__ import annotations

from app.enums import AcornTransactionType, JudgeStatus, ProgressStatus
from app.judge import get_judge
from app.judge.interface import JudgeResult
from app.judge.stub import FakeJudge
from app.main import app
from tests.fixtures_code import LOOP_V2, LOOP_V3


def use_judge(*results: JudgeResult) -> None:
    """이 테스트 동안 judge가 돌려줄 결과를 순서대로 정한다.

    **인스턴스를 하나만 만들어 공유한다.** `lambda: FakeJudge(...)`처럼 쓰면
    요청마다 새 큐가 생겨 항상 첫 결과만 돌아온다 -- 결과가 전부 같은
    테스트에서는 우연히 통과하므로 조용히 틀린다.
    """
    judge = FakeJudge(list(results))
    app.dependency_overrides[get_judge] = lambda: judge


def accepted(total: int = 5) -> JudgeResult:
    return JudgeResult(status=JudgeStatus.ACCEPTED, passed=total, total=total)


def wrong(passed: int = 3, total: int = 5) -> JudgeResult:
    return JudgeResult(status=JudgeStatus.WRONG_ANSWER, passed=passed, total=total)


def solve(client, problem_id: str = "func_sum_list", code: str = LOOP_V2, mode: str = "submit"):
    sid = client.post("/sessions", json={"problem_id": problem_id}).json()["session_id"]
    return client.post(f"/sessions/{sid}/{mode}", json={"code": code})


# --------------------------------------------------------------------- 보상


def test_first_accepted_awards_acorns(client):
    use_judge(accepted())
    solve(client)

    body = client.get("/users/me/acorns").json()
    assert body["balance"] == 3  # KUICS 30p → 도토리 3개
    assert body["total_earned"] == 3


def test_same_problem_solved_twice_awards_only_once(client):
    """멱등성 키가 DB 제약으로 막는다. 재통과는 지급 없음."""
    use_judge(accepted(), accepted())
    solve(client)
    solve(client)

    assert client.get("/users/me/acorns").json()["balance"] == 3


def test_wrong_answer_awards_nothing(client):
    use_judge(wrong())
    solve(client)
    assert client.get("/users/me/acorns").json()["balance"] == 0


def test_different_problems_award_separately(client):
    use_judge(accepted(), accepted())
    solve(client, "func_sum_list")
    solve(client, "func_find_max")
    assert client.get("/users/me/acorns").json()["balance"] == 6


def test_transaction_ledger_records_the_award(client):
    use_judge(accepted())
    solve(client)

    body = client.get("/users/me/acorns/transactions").json()
    assert body["total"] == 1
    tx = body["transactions"][0]
    assert tx["amount"] == 3
    assert tx["balance_after"] == 3
    assert tx["type"] == AcornTransactionType.PROBLEM_SOLVED.value
    assert tx["problem_id"] == "func_sum_list"


# --------------------------------------------------------------------- 진행 상태


def test_accepted_marks_problem_solved(client):
    use_judge(accepted())
    solve(client)

    row = client.get("/users/me/progress/func_sum_list").json()
    assert row["status"] == ProgressStatus.SOLVED.value
    assert row["solved_at"] is not None
    assert row["attempt_count"] == 1


def test_attempts_accumulate_and_best_passed_is_a_high_water_mark(client):
    use_judge(wrong(2), wrong(4), wrong(1))
    sid = client.post("/sessions", json={"problem_id": "func_sum_list"}).json()["session_id"]
    for code in (LOOP_V2, LOOP_V3, LOOP_V2):
        client.post(f"/sessions/{sid}/run", json={"code": code})

    row = client.get("/users/me/progress/func_sum_list").json()
    assert row["attempt_count"] == 3
    assert row["best_passed"] == 4  # 마지막이 1이어도 최고 기록은 유지된다
    assert row["status"] == ProgressStatus.IN_PROGRESS.value


def test_untouched_problem_returns_not_started_instead_of_404(client):
    row = client.get("/users/me/progress/func_find_max").json()
    assert row["status"] == ProgressStatus.NOT_STARTED.value
    assert row["attempt_count"] == 0


def test_progress_for_unknown_problem_is_404(client):
    assert client.get("/users/me/progress/nope").status_code == 404


def test_progress_list_omits_code_body(client):
    """홈이 26개를 한 번에 받으므로 코드 본문은 빼고 준다."""
    use_judge(accepted())
    solve(client)
    items = client.get("/users/me/progress").json()["items"]
    assert len(items) == 1
    assert items[0]["current_code"] is None


# --------------------------------------------------------------------- Checkpoint


def test_checkpoint_roundtrip(client):
    r = client.put(
        "/users/me/progress/func_sum_list/checkpoint",
        json={"student_code": "def sum_list(arr):\n    return 42"},
    )
    assert r.status_code == 200

    row = client.get("/users/me/progress/func_sum_list").json()
    assert row["current_code"] == "def sum_list(arr):\n    return 42"
    assert row["status"] == ProgressStatus.IN_PROGRESS.value


def test_checkpoint_is_per_user(client, anon_client):
    client.put(
        "/users/me/progress/func_sum_list/checkpoint",
        json={"student_code": "내 코드"},
    )
    token = anon_client.post(
        "/auth/signup",
        json={"name": "다른사람", "email": "other@example.com", "password": "password123"},
    ).json()["access_token"]

    row = anon_client.get(
        "/users/me/progress/func_sum_list", headers={"Authorization": f"Bearer {token}"}
    ).json()
    assert row["current_code"] != "내 코드"


# --------------------------------------------------------------------- 풀이 목록


def test_solved_problems_list(client):
    use_judge(accepted(), wrong())
    solve(client, "func_sum_list")
    solve(client, "func_find_max")

    body = client.get("/users/me/solved-problems").json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["problem_id"] == "func_sum_list"
    assert item["title"] == "리스트 합 구하기"
    assert item["acorns_earned"] == 3
    assert item["attempt_count"] == 1


# --------------------------------------------------------------------- 닉네임 차감


def test_nickname_change_costs_acorns(client):
    use_judge(accepted())
    solve(client, "stdout_bit_is_on")  # KUICS 80p → 도토리 8개 확보

    r = client.patch("/users/me/nickname", json={"nickname": "새이름"})
    assert r.status_code == 200
    assert r.json()["nickname"] == "새이름"
    assert r.json()["acorns_spent"] == 5
    assert r.json()["acorn_balance"] == 3


def test_nickname_change_without_enough_acorns_is_rejected(client):
    r = client.patch("/users/me/nickname", json={"nickname": "새이름"})
    assert r.status_code == 402
    assert r.json()["detail"]["code"] == "INSUFFICIENT_ACORNS"

    # **아무것도 바뀌지 않아야 한다.** 차감 실패인데 닉네임만 바뀌면 안 된다.
    assert client.get("/users/me/profile").json()["nickname"] != "새이름"


def test_same_nickname_is_free(client):
    current = client.get("/users/me/profile").json()["nickname"]
    r = client.patch("/users/me/nickname", json={"nickname": current})
    assert r.status_code == 200
    assert r.json()["acorns_spent"] == 0


def test_duplicate_nickname_is_rejected(client, anon_client):
    taken = client.get("/users/me/profile").json()["nickname"]
    token = anon_client.post(
        "/auth/signup",
        json={"name": "둘째", "email": "second@example.com", "password": "password123"},
    ).json()["access_token"]

    r = anon_client.patch(
        "/users/me/nickname",
        json={"nickname": taken},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "NICKNAME_TAKEN"


def test_banned_and_malformed_nicknames_are_rejected(client):
    for bad in ("관리자", "admin1", "a", "x" * 30, "공백 있음", "!@#$"):
        r = client.patch("/users/me/nickname", json={"nickname": bad})
        assert r.status_code in (409, 422), bad


# --------------------------------------------------------------------- 뱃지


def test_badge_reflects_total_earned(client):
    assert client.get("/users/me/profile").json()["current_badge"]["code"] == "SEED"

    use_judge(*[accepted()] * 3)
    for pid in ("func_sum_list", "func_find_max", "func_count_positive"):
        solve(client, pid)

    body = client.get("/users/me/profile").json()
    assert body["total_acorns_earned"] == 9
    assert body["current_badge"]["code"] == "SEED"  # 50 미만
    assert body["next_badge"]["code"] == "SPROUT"
