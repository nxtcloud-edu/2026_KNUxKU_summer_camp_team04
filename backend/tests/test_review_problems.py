"""복습 문제 생성 배선 테스트.

LLM도 judge도 부르지 않는다 -- 가짜 생성기(FakeGenerator)를 꽂아 **backend가
그 결과를 어떻게 다루는지**만 검증한다. 실제 생성 품질은 agent 쪽
tests/test_problem_generator.py의 책임이다.

이 파일이 지키는 계약:
  1. 요청은 즉시 PENDING으로 돌아온다 (생성이 25초짜리라 동기일 수 없다).
  2. 성공하면 문제가 **파일로** 저장되고 `repo.get()`으로 풀린다 -- 즉 세션 생성과
     채점이 큐레이션 문제와 똑같은 경로로 동작한다.
  3. 어떤 실패도 PENDING을 남기지 않는다 (남으면 프런트가 무한 폴링한다).
  4. 생성 문제는 `/problems` 전체 목록에 안 뜬다 (개인 것이므로).
"""
from __future__ import annotations

from typing import Any

import pytest
from sqlmodel import select

from app.db import get_engine
from app.enums import GeneratedProblemStatus
from app.main import app
from app.models import GeneratedProblem
from app.problems.service import ProblemRepository, get_problem_repository
from app.review.interface import GenerationResult, get_problem_generator

VALID_PROBLEM_JSON: dict[str, Any] = {
    "title": "리스트 곱 구하기",
    "description": "## 문제\n리스트의 모든 수를 곱한다.",
    "concept": ["loop"],
    "check_type": "function_call",
    "function_name": "mul_list",
    "code_template": "def mul_list(arr):\n    pass\n",
    "public_test_cases": [{"input": [[1, 2, 3]], "expected": 6, "category": "basic"}],
    "hidden_test_cases": [{"input": [[]], "expected": 1, "category": "empty"}],
}


class FakeGenerator:
    """호출을 기록하고 미리 정한 결과를 돌려준다 (judge/stub.py의 FakeJudge 패턴)."""

    name = "fake"

    def __init__(self, result: GenerationResult) -> None:
        self._result = result
        self.calls: list[dict[str, Any]] = []

    def generate(self, request: dict[str, Any]) -> GenerationResult:
        self.calls.append(request)
        return self._result


class ExplodingGenerator:
    """프로토콜을 어기고 예외를 던지는 구현. 방어 코드가 실제로 도는지 본다."""

    name = "boom"

    def generate(self, request: dict[str, Any]) -> GenerationResult:
        raise RuntimeError("agent 프로세스가 죽었다")


@pytest.fixture(name="repo")
def repo_fixture(tmp_path, monkeypatch):
    """생성 문제가 tmp_path에 떨어지는 저장소.

    실제 `generated_problems/`를 건드리면 테스트가 개발자의 로컬 상태를 오염시킨다.
    큐레이션 디렉터리는 실제 것을 그대로 써서 source_problem_id 검증이 진짜로 돈다.
    """
    from app.config import get_settings

    repo = ProblemRepository(get_settings().problems_path, tmp_path / "generated")
    app.dependency_overrides[get_problem_repository] = lambda: repo
    yield repo
    app.dependency_overrides.pop(get_problem_repository, None)


def _use(generator, engine) -> None:
    app.dependency_overrides[get_problem_generator] = lambda: generator
    # 백그라운드 태스크가 새 DB 세션을 열 때 테스트의 인메모리 엔진을 쓰게 한다.
    # 이걸 안 하면 실제 codetrace.db 파일을 건드린다.
    app.dependency_overrides[get_engine] = lambda: engine


# --------------------------------------------------------------------- 성공 경로


def test_generated_problem_becomes_playable_like_a_curated_one(client, db, engine, repo):
    """생성 성공 -> 파일 저장 -> repo.get()으로 풀림 -> 세션까지 만들어진다.

    이게 이 기능의 핵심 계약이다. 문제 내용을 DB에 넣지 않고 파일로 두는 이유가
    바로 이것 -- 세션/채점/agent context가 "생성된 문제인지"를 몰라도 된다.
    """
    gen = FakeGenerator(GenerationResult(is_valid=True, problem_json=VALID_PROBLEM_JSON))
    _use(gen, engine)

    r = client.post("/users/me/review-problems", json={"source_problem_id": "func_sum_list"})
    assert r.status_code == 201
    body = r.json()
    # TestClient는 응답 반환 후 BackgroundTasks를 동기로 돌린다 -- 그래서
    # 여기 도달한 시점엔 이미 생성이 끝나 있다. 상태 전이는 아래 GET으로 확인한다.
    assert body["status"] == GeneratedProblemStatus.PENDING.value
    assert body["problem_id"] is None

    listed = client.get("/users/me/review-problems").json()["items"]
    assert len(listed) == 1
    ready = listed[0]
    assert ready["status"] == GeneratedProblemStatus.READY.value
    assert ready["error_message"] is None
    problem_id = ready["problem_id"]
    assert problem_id

    # 큐레이션 문제와 **완전히 같은 경로**로 열린다.
    detail = client.get(f"/problems/{problem_id}")
    assert detail.status_code == 200
    assert detail.json()["title"] == "리스트 곱 구하기"

    # 세션도 만들어진다 = 실제로 풀 수 있다.
    session = client.post("/sessions", json={"problem_id": problem_id})
    assert session.status_code == 201

    # hidden test case는 응답에 실리지 않는다 (스키마에 담을 필드가 없다).
    assert "hidden_test_cases" not in detail.json()


def test_agent_receives_the_source_problem_content_not_just_its_id(client, engine, repo):
    """agent는 문제 뱅크에 접근할 수 없다 -- id만 주면 무슨 문제였는지 모른다.

    "비슷한 문제"를 만들려면 원본 본문이 실려 가야 한다.
    """
    gen = FakeGenerator(GenerationResult(is_valid=True, problem_json=VALID_PROBLEM_JSON))
    _use(gen, engine)

    client.post("/users/me/review-problems", json={"source_problem_id": "func_sum_list"})

    assert len(gen.calls) == 1
    sent = gen.calls[0]
    assert sent["missed_problem_ids"] == ["func_sum_list"]
    source = sent["source_problems"][0]
    assert source["problem_id"] == "func_sum_list"
    assert source["title"]
    assert source["description"]
    # 형식을 맞춰야 새 문제도 같은 입출력 방식이 된다.
    assert source["check_type"] == "function_call"
    assert source["function_name"] == "sum_list"


def test_generated_problem_is_hidden_from_the_public_problem_list(client, engine, repo):
    """복습 문제는 그 학생 개인의 것이다.

    전체 목록에 섞이면 교육자 대시보드의 진도율 분모(repo.list())까지 오염된다.
    """
    gen = FakeGenerator(GenerationResult(is_valid=True, problem_json=VALID_PROBLEM_JSON))
    _use(gen, engine)
    client.post("/users/me/review-problems", json={"source_problem_id": "func_sum_list"})

    generated_id = client.get("/users/me/review-problems").json()["items"][0]["problem_id"]
    listed_ids = [p["problem_id"] for p in client.get("/problems").json()]

    assert generated_id not in listed_ids
    assert "func_sum_list" in listed_ids  # 큐레이션 문제는 그대로 보인다


# --------------------------------------------------------------------- 실패 경로


def test_generation_failure_is_recorded_not_left_pending(client, engine, repo):
    """실패해도 PENDING을 남기면 프런트가 영원히 폴링한다."""
    gen = FakeGenerator(
        GenerationResult(is_valid=False, error_message="레퍼런스 코드가 틀렸습니다")
    )
    _use(gen, engine)

    client.post("/users/me/review-problems", json={"source_problem_id": "func_sum_list"})

    item = client.get("/users/me/review-problems").json()["items"][0]
    assert item["status"] == GeneratedProblemStatus.FAILED.value
    assert "레퍼런스 코드가 틀렸습니다" in item["error_message"]
    assert item["problem_id"] is None


def test_generator_exception_is_also_recorded_as_failed(client, engine, repo):
    """프로토콜은 예외를 금지하지만, 구현이 어기면 요청이 PENDING에 갇힌다."""
    _use(ExplodingGenerator(), engine)

    client.post("/users/me/review-problems", json={"source_problem_id": "func_sum_list"})

    item = client.get("/users/me/review-problems").json()["items"][0]
    assert item["status"] == GeneratedProblemStatus.FAILED.value
    assert item["error_message"]


def test_unknown_source_problem_is_404(client, engine, repo):
    _use(FakeGenerator(GenerationResult(is_valid=True)), engine)
    r = client.post("/users/me/review-problems", json={"source_problem_id": "no_such_problem"})
    assert r.status_code == 404


def test_default_generator_reports_unavailable_instead_of_crashing(client, engine, repo):
    """agent가 안 붙은 기본 상태에서도 500이 아니라 FAILED로 끝나야 한다."""
    app.dependency_overrides[get_engine] = lambda: engine  # 기본 생성기 그대로 사용

    r = client.post("/users/me/review-problems", json={"source_problem_id": "func_sum_list"})
    assert r.status_code == 201

    item = client.get("/users/me/review-problems").json()["items"][0]
    assert item["status"] == GeneratedProblemStatus.FAILED.value
    assert "연결되지 않았습니다" in item["error_message"]


# --------------------------------------------------------------------- 중복 방지 / 소유권


def test_repeated_clicks_do_not_queue_extra_generations(client, db, engine, repo):
    """생성 1건이 LLM + 도커 실행이라 버튼 연타가 그대로 비용이 된다."""

    class NeverFinishes:
        """PENDING을 그대로 두려고 아무것도 안 하는 생성기."""

        name = "pending"

        def __init__(self) -> None:
            self.calls = 0

        def generate(self, request: dict[str, Any]) -> GenerationResult:
            self.calls += 1
            # 행을 PENDING으로 남기기 위해 여기서 결과를 주지 않고 예외도 안 낸다.
            # -> run_generation이 FAILED로 바꾸므로, 대신 아래에서 직접 확인한다.
            return GenerationResult(is_valid=True, problem_json=VALID_PROBLEM_JSON)

    # PENDING 행을 직접 만들어 "이미 진행 중"인 상태를 재현한다.
    from app.models import User as UserModel

    user_id = db.exec(select(UserModel)).first().id
    db.add(
        GeneratedProblem(
            user_id=user_id,
            source_problem_id="func_sum_list",
            status=GeneratedProblemStatus.PENDING,
        )
    )
    db.commit()

    gen = NeverFinishes()
    _use(gen, engine)
    r = client.post("/users/me/review-problems", json={"source_problem_id": "func_sum_list"})

    assert r.status_code == 201
    # 이미 PENDING이 있었으므로 agent를 부르지 않았다.
    assert gen.calls == 0
    rows = db.exec(select(GeneratedProblem)).all()
    assert len(rows) == 1


def test_review_problems_require_login(anon_client):
    assert anon_client.get("/users/me/review-problems").status_code == 401
    assert (
        anon_client.post(
            "/users/me/review-problems", json={"source_problem_id": "func_sum_list"}
        ).status_code
        == 401
    )
