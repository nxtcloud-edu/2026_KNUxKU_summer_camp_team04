"""POST /sessions/{id}/run|submit 이 도는 파이프라인 전체.

예전 test_results_api.py 를 대체한다. POST /results(클라이언트가 채점 결과를
보고하던 입구)가 제거되면서 같은 성질을 서버 judge 경로에서 검증한다 --
도토리가 정답 기준으로 지급되므로 클라이언트가 status 를 정할 수 있으면 안 된다.
"""
from __future__ import annotations

import pytest
from sqlmodel import select

from app.enums import EventType, JudgeStatus
from app.judge import get_judge
from app.judge.interface import JudgeResult
from app.judge.stub import FakeJudge
from app.main import app
from app.models import Event
from tests.fixtures_code import LOOP_V2, LOOP_V3, LOOP_V4


def use_judge(*results: JudgeResult) -> None:
    """이 테스트 동안 judge 가 돌려줄 결과를 순서대로 정한다.

    **인스턴스를 하나만 만들어 공유한다.** `lambda: FakeJudge(...)`로 쓰면
    요청마다 새 큐가 생겨 항상 첫 결과만 돌아온다.
    """
    judge = FakeJudge(list(results))
    app.dependency_overrides[get_judge] = lambda: judge


def wrong(passed: int = 3, total: int = 5) -> JudgeResult:
    return JudgeResult(status=JudgeStatus.WRONG_ANSWER, passed=passed, total=total, runtime_ms=21)


def accepted(total: int = 5) -> JudgeResult:
    return JudgeResult(status=JudgeStatus.ACCEPTED, passed=total, total=total, runtime_ms=12)


def create(client) -> str:
    return client.post("/sessions", json={"problem_id": "func_sum_list"}).json()["session_id"]


def run(client, sid: str, code: str, mode: str = "run"):
    return client.post(f"/sessions/{sid}/{mode}", json={"code": code})


def test_run_writes_exactly_one_test_result_event(client, db):
    use_judge(wrong(3))
    sid = create(client)
    r = run(client, sid, LOOP_V2)
    assert r.status_code == 201

    body = r.json()
    assert body["event"]["type"] == "TEST_RESULT"
    # 서버가 채점했다는 증거. CLIENT_JUDGE 가 아니다.
    assert body["event"]["source"] == "SERVER"
    assert body["event"]["payload"]["judge"] == "fake"
    assert body["event"]["payload"]["passed"] == 3
    assert body["event"]["payload"]["runtime_ms"] == 21

    rows = [
        e
        for e in db.exec(select(Event).where(Event.session_id == sid)).all()
        if EventType(e.type) is EventType.TEST_RESULT
    ]
    assert len(rows) == 1


def test_response_carries_process_state_and_null_agent_decision(client):
    use_judge(wrong(3))
    sid = create(client)
    body = run(client, sid, LOOP_V2).json()

    assert body["process_state"]["session_id"] == sid
    assert body["process_state"]["triggered"] is False
    assert body["agent_decision"] is None


def test_agent_decision_is_returned_when_triggered(client):
    use_judge(wrong(3), wrong(3), wrong(3))
    sid = create(client)
    for code in (LOOP_V2, LOOP_V3, LOOP_V4):
        body = run(client, sid, code).json()

    assert body["process_state"]["trigger"] == "REPEATED_FAILURE"
    assert body["agent_decision"] is not None
    assert body["agent_decision"]["action"] == "WAIT"


def test_trigger_writes_agent_trigger_event(client, db):
    use_judge(wrong(3), wrong(3), wrong(3))
    sid = create(client)
    for code in (LOOP_V2, LOOP_V3, LOOP_V4):
        run(client, sid, code)

    triggers = [
        e
        for e in db.exec(select(Event).where(Event.session_id == sid)).all()
        if EventType(e.type) is EventType.AGENT_TRIGGER
    ]
    assert len(triggers) == 1
    assert triggers[0].payload["trigger"] == "REPEATED_FAILURE"
    # 그 순간의 feature 를 통째로 남겨야 사후에 "왜 불렀는지"를 설명할 수 있다
    assert triggers[0].payload["features"]["same_result_count"] == 3


def test_run_on_unknown_session_returns_404(client):
    use_judge(wrong())
    r = run(client, "sess_nope", LOOP_V2)
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "SESSION_NOT_FOUND"


def test_process_state_get_is_read_only(client, db):
    """GET 을 여러 번 호출해도 AGENT_TRIGGER 가 하나만 있어야 한다.

    GET 이 cooldown 을 소진하면 정작 agent 를 불러야 할 Run 이 cooldown 에 걸린다.
    """
    use_judge(wrong(3), wrong(3), wrong(3))
    sid = create(client)
    for code in (LOOP_V2, LOOP_V3, LOOP_V4):
        run(client, sid, code)

    for _ in range(5):
        assert client.get(f"/sessions/{sid}/process-state").status_code == 200

    triggers = [
        e
        for e in db.exec(select(Event).where(Event.session_id == sid)).all()
        if EventType(e.type) is EventType.AGENT_TRIGGER
    ]
    assert len(triggers) == 1


def test_process_state_for_unknown_session_returns_404(client):
    r = client.get("/sessions/sess_nope/process-state")
    assert r.status_code == 404


@pytest.mark.parametrize("path", ["/results"])
def test_client_reported_results_endpoint_is_gone(client, path):
    """클라이언트가 채점 결과를 보고하던 입구는 제거됐다.

    남아 있으면 {"status":"ACCEPTED"} 한 줄로 도토리를 무한 획득할 수 있다.
    """
    sid = create(client)
    r = client.post(
        f"/sessions/{sid}{path}",
        json={"mode": "run", "status": "ACCEPTED", "passed": 5, "total": 5},
    )
    assert r.status_code == 405 or r.status_code == 404
