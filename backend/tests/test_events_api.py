from __future__ import annotations

from sqlmodel import select

from app.models import CodeSnapshot, Event
from tests.fixtures_code import LOOP_V2

TEMPLATE = "def sum_list(arr):\n    # 여기에 코드를 작성하세요\n    pass"


def create(client) -> str:
    return client.post("/sessions", json={"problem_id": "func_sum_list"}).json()[
        "session_id"
    ]


def post(client, sid: str, events: list[dict]):
    return client.post(f"/sessions/{sid}/events", json={"events": events})


def test_batch_seqs_are_contiguous_and_monotonic(client):
    sid = create(client)
    r = post(
        client,
        sid,
        [
            {"type": "UNDO", "client_event_id": "a"},
            {"type": "RESET", "client_event_id": "b"},
            {"type": "HINT_REQUEST", "client_event_id": "c"},
        ],
    )
    assert r.status_code == 201
    seqs = [e["seq"] for e in r.json()["accepted"]]
    assert seqs == [2, 3, 4]  # seq=1은 SESSION_START
    assert r.json()["last_event_seq"] == 4


def test_retried_batch_is_deduplicated(client, db):
    """프론트가 실패로 판단하고 재전송했을 때 중복 행이 생기면 안 된다.

    dedup이 없으면 wifi 한 번 끊길 때 RUN 3/5가 다섯 번 기록되고
    monitor가 한 번 실행한 학생에게 REPEATED_FAILURE를 외친다.
    """
    sid = create(client)
    batch = [
        {"type": "UNDO", "client_event_id": "e1"},
        {"type": "RESET", "client_event_id": "e2"},
    ]

    first = post(client, sid, batch)
    assert len(first.json()["accepted"]) == 2
    assert first.json()["duplicate_client_event_ids"] == []

    second = post(client, sid, batch)
    assert second.status_code == 201
    assert second.json()["accepted"] == []
    assert sorted(second.json()["duplicate_client_event_ids"]) == ["e1", "e2"]

    rows = db.exec(select(Event).where(Event.session_id == sid)).all()
    assert len(rows) == 3  # SESSION_START + 2건


def test_duplicate_within_a_single_batch_is_collapsed(client):
    sid = create(client)
    r = post(
        client,
        sid,
        [
            {"type": "UNDO", "client_event_id": "same"},
            {"type": "UNDO", "client_event_id": "same"},
        ],
    )
    assert len(r.json()["accepted"]) == 1
    assert r.json()["duplicate_client_event_ids"] == ["same"]


def test_same_client_event_id_in_two_sessions_both_accepted(client):
    """UNIQUE 제약이 (session_id, client_event_id)라 세션 간에는 충돌하지 않는다."""
    a, b = create(client), create(client)
    assert len(post(client, a, [{"type": "UNDO", "client_event_id": "x"}]).json()["accepted"]) == 1
    assert len(post(client, b, [{"type": "UNDO", "client_event_id": "x"}]).json()["accepted"]) == 1


def test_events_without_client_event_id_are_never_deduplicated(client):
    """SQLite는 UNIQUE에서 NULL을 서로 다른 값으로 본다 -- dedup은 opt-in이다."""
    sid = create(client)
    post(client, sid, [{"type": "UNDO"}])
    r = post(client, sid, [{"type": "UNDO"}])
    assert len(r.json()["accepted"]) == 1
    assert r.json()["duplicate_client_event_ids"] == []


def test_code_snapshot_allocates_version_and_strips_code(client, db):
    """이벤트 payload에서 raw code가 제거되어야 한다.

    안 그러면 events 테이블이 제2의 코드 저장소가 되고 GET /events가 메가바이트를 뱉는다.
    """
    sid = create(client)
    r = post(client, sid, [{"type": "CODE_SNAPSHOT", "payload": {"code": LOOP_V2}}])
    accepted = r.json()["accepted"][0]

    assert accepted["code_version"] == 2
    assert "code" not in accepted["payload"]
    assert accepted["payload"]["code_length"] == len(LOOP_V2)
    assert accepted["payload"]["primary_region"] in ("loop", "accumulator", "other")
    assert accepted["payload"]["deduplicated"] is False
    assert r.json()["current_code_version"] == 2

    snaps = db.exec(select(CodeSnapshot).where(CodeSnapshot.session_id == sid)).all()
    assert [s.version for s in snaps] == [1, 2]
    assert snaps[1].code == LOOP_V2  # 코드는 스냅샷에만 있다


def test_identical_code_does_not_create_a_new_version(client, db):
    """debounce + undo/redo가 동일 스냅샷을 끊임없이 만든다.

    막지 않으면 no-op 편집으로 same_region_edit_count가 부풀려진다.
    """
    sid = create(client)
    post(client, sid, [{"type": "CODE_SNAPSHOT", "payload": {"code": LOOP_V2}}])
    r = post(client, sid, [{"type": "CODE_SNAPSHOT", "payload": {"code": LOOP_V2}}])

    accepted = r.json()["accepted"][0]
    assert accepted["code_version"] == 2  # 그대로
    assert accepted["payload"]["deduplicated"] is True

    snaps = db.exec(select(CodeSnapshot).where(CodeSnapshot.session_id == sid)).all()
    assert len(snaps) == 2


def test_code_snapshot_without_code_is_rejected(client):
    sid = create(client)
    r = post(client, sid, [{"type": "CODE_SNAPSHOT", "payload": {}}])
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "MISSING_SNAPSHOT_CODE"


def test_client_cannot_forge_server_only_events(client):
    """EventIn.type이 ClientEventType이라 핸들러 진입 전에 Pydantic이 막는다.

    런타임 403보다 나은 이유: 선언적이고, OpenAPI에 제약이 드러나
    프론트의 생성 타입이 이걸 표현조차 못 한다.
    """
    sid = create(client)
    for forged in ("TEST_RESULT", "AGENT_TRIGGER", "SESSION_START", "AGENT_INTERVENTION"):
        r = post(client, sid, [{"type": forged}])
        assert r.status_code == 422, forged


def test_openapi_does_not_expose_server_only_types_in_request_schema(client):
    schema = client.get("/openapi.json").json()
    allowed = schema["components"]["schemas"]["ClientEventType"]["enum"]
    assert "TEST_RESULT" not in allowed
    assert "AGENT_TRIGGER" not in allowed
    assert "CODE_SNAPSHOT" in allowed


def test_empty_batch_is_rejected(client):
    sid = create(client)
    assert post(client, sid, []).status_code == 422


def test_events_to_unknown_session_returns_404(client):
    assert post(client, "sess_missing", [{"type": "UNDO"}]).status_code == 404


def test_get_events_paging(client):
    sid = create(client)
    post(client, sid, [{"type": "UNDO"} for _ in range(5)])

    first = client.get(f"/sessions/{sid}/events", params={"limit": 3}).json()
    assert [e["seq"] for e in first["events"]] == [1, 2, 3]
    assert first["has_more"] is True

    rest = client.get(f"/sessions/{sid}/events", params={"since_seq": 3}).json()
    assert [e["seq"] for e in rest["events"]] == [4, 5, 6]
    assert rest["has_more"] is False
