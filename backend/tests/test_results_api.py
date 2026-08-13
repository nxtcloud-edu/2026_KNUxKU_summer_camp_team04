from __future__ import annotations

from sqlmodel import select

from app.enums import EventType
from app.models import Event
from tests.fixtures_code import LOOP_V2, LOOP_V3, LOOP_V4


def create(client) -> str:
    return client.post("/sessions", json={"problem_id": "func_sum_list"}).json()[
        "session_id"
    ]


def edit(client, sid: str, code: str):
    client.post(
        f"/sessions/{sid}/events",
        json={"events": [{"type": "CODE_SNAPSHOT", "payload": {"code": code}}]},
    )


def result(client, sid: str, passed: int, total: int = 5, **kw):
    body = {"mode": "run", "status": "WRONG_ANSWER", "passed": passed, "total": total}
    body.update(kw)
    return client.post(f"/sessions/{sid}/results", json=body)


def test_result_writes_exactly_one_test_result_event(client, db):
    sid = create(client)
    r = result(client, sid, 3, runtime_ms=21)
    assert r.status_code == 201

    body = r.json()
    assert body["event"]["type"] == "TEST_RESULT"
    assert body["event"]["source"] == "CLIENT_JUDGE"
    assert body["event"]["payload"]["judge"] == "pyodide"
    assert body["event"]["payload"]["passed"] == 3
    assert body["event"]["payload"]["runtime_ms"] == 21

    rows = [
        e
        for e in db.exec(select(Event).where(Event.session_id == sid)).all()
        if EventType(e.type) is EventType.TEST_RESULT
    ]
    assert len(rows) == 1


def test_response_carries_process_state_and_null_agent_decision(client):
    sid = create(client)
    body = result(client, sid, 3).json()

    assert body["process_state"]["session_id"] == sid
    assert body["process_state"]["status"] in (
        "PROGRESSING",
        "PRODUCTIVE_STRUGGLE",
        "POSSIBLE_STUCK",
        "STUCK",
        "UNDERSTANDING_UNCERTAIN",
        "HELP_REQUESTED",
    )
    assert body["process_state"]["features"]["run_count"] == 1
    # trigger가 없으면 agent를 아예 부르지 않는다
    assert body["agent_decision"] is None


def test_agent_decision_is_returned_when_triggered(client):
    """오늘의 stub은 WAIT이지만, trigger가 났을 때 실제로 호출된다는 것 자체가 seam이다."""
    sid = create(client)
    edit(client, sid, LOOP_V2)
    result(client, sid, 3)
    edit(client, sid, LOOP_V3)
    result(client, sid, 3)
    edit(client, sid, LOOP_V4)
    body = result(client, sid, 3).json()

    assert body["process_state"]["trigger"] == "REPEATED_FAILURE"
    assert body["process_state"]["triggered"] is True
    assert body["agent_decision"]["action"] == "WAIT"
    assert body["agent_decision"]["state"] == "STUCK"


def test_trigger_writes_agent_trigger_event(client, db):
    sid = create(client)
    edit(client, sid, LOOP_V2)
    result(client, sid, 3)
    edit(client, sid, LOOP_V3)
    result(client, sid, 3)
    edit(client, sid, LOOP_V4)
    result(client, sid, 3)

    triggers = [
        e
        for e in db.exec(select(Event).where(Event.session_id == sid)).all()
        if EventType(e.type) is EventType.AGENT_TRIGGER
    ]
    assert len(triggers) == 1
    assert triggers[0].payload["trigger"] == "REPEATED_FAILURE"
    assert triggers[0].payload["features"]["same_result_count"] == 3


def test_passed_greater_than_total_is_rejected(client):
    sid = create(client)
    assert result(client, sid, 7, 5).status_code == 422


def test_negative_passed_is_rejected(client):
    sid = create(client)
    assert result(client, sid, -1, 5).status_code == 422


def test_code_version_beyond_latest_is_rejected(client):
    sid = create(client)
    r = result(client, sid, 3, code_version=99)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "INVALID_CODE_VERSION"


def test_result_to_unknown_session_returns_404(client):
    assert result(client, "sess_missing", 3).status_code == 404


def test_process_state_get_is_read_only(client, db):
    """폴링해도 AGENT_TRIGGER가 생기면 안 된다.

    GET이 cooldown을 소진하면 trigger 직후 첫 폴링이 그걸 먹고
    정작 agent를 불러야 할 Run이 cooldown에 걸린다.
    """
    sid = create(client)
    edit(client, sid, LOOP_V2)
    result(client, sid, 3)
    edit(client, sid, LOOP_V3)
    result(client, sid, 3)
    edit(client, sid, LOOP_V4)

    before = len(db.exec(select(Event).where(Event.session_id == sid)).all())
    for _ in range(5):
        assert client.get(f"/sessions/{sid}/process-state").status_code == 200
    after = len(db.exec(select(Event).where(Event.session_id == sid)).all())
    assert before == after


def test_process_state_for_unknown_session_returns_404(client):
    r = client.get("/sessions/sess_missing/process-state")
    assert r.status_code == 404
