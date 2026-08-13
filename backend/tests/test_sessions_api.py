from __future__ import annotations

from sqlmodel import select

from app.enums import EventType
from app.models import CodeSnapshot, Event


def create(client, problem_id: str = "func_sum_list"):
    r = client.post("/sessions", json={"problem_id": problem_id})
    assert r.status_code == 201, r.text
    return r.json()


def test_create_session_seeds_start_event_and_template_snapshot(client, db):
    body = create(client)
    sid = body["session_id"]

    assert sid.startswith("sess_")
    assert body["status"] == "SOLVING"
    assert body["current_code_version"] == 1
    assert body["current_code"].startswith("def sum_list(arr):")

    events = db.exec(select(Event).where(Event.session_id == sid)).all()
    assert len(events) == 1
    assert EventType(events[0].type) is EventType.SESSION_START
    assert events[0].seq == 1
    assert events[0].source == "SERVER"

    # 스냅샷 v1 = 문제 템플릿. 학생의 첫 편집이 v2가 되어야 첫 diff가 의미 있다.
    snaps = db.exec(select(CodeSnapshot).where(CodeSnapshot.session_id == sid)).all()
    assert len(snaps) == 1
    assert snaps[0].version == 1
    assert snaps[0].parent_version is None


def test_create_session_with_unknown_problem_returns_404(client):
    r = client.post("/sessions", json={"problem_id": "nope"})
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "PROBLEM_NOT_FOUND"


def test_get_session_tracks_latest_snapshot(client):
    sid = create(client)["session_id"]
    client.post(
        f"/sessions/{sid}/events",
        json={"events": [{"type": "CODE_SNAPSHOT", "payload": {"code": "x = 1"}}]},
    )
    body = client.get(f"/sessions/{sid}").json()
    assert body["current_code"] == "x = 1"
    assert body["current_code_version"] == 2


def test_get_unknown_session_returns_404(client):
    r = client.get("/sessions/sess_missing")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "SESSION_NOT_FOUND"


def test_finish_is_idempotent(client, db):
    sid = create(client)["session_id"]

    first = client.post(f"/sessions/{sid}/finish")
    assert first.status_code == 200
    assert first.json()["status"] == "FINISHED"
    assert first.json()["finished_at"] is not None

    second = client.post(f"/sessions/{sid}/finish")
    assert second.status_code == 200
    assert second.json() == first.json()

    ends = [
        e
        for e in db.exec(select(Event).where(Event.session_id == sid)).all()
        if EventType(e.type) is EventType.SESSION_END
    ]
    assert len(ends) == 1


def test_events_after_finish_are_accepted_with_flag(client):
    """409가 아니라 플래그와 함께 수락한다.

    현실적인 원인은 /finish 직후 프론트가 큐를 flush하는 것뿐인데,
    아무도 안 볼 데이터 위생과 맞바꿔 무대에 빨간 배너를 띄울 이유가 없다.
    """
    sid = create(client)["session_id"]
    client.post(f"/sessions/{sid}/finish")

    r = client.post(
        f"/sessions/{sid}/events",
        json={"events": [{"type": "UNDO"}]},
    )
    assert r.status_code == 201
    assert r.json()["session_finished"] is True
