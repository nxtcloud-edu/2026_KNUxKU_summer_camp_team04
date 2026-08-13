"""함정 회귀 테스트. 작고 값이 높다.

전부 "조용히 틀리는" 부류라서 명시적으로 잡아둔다.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.enums import EventSource, EventType
from app.models import CodeSnapshot, Event
from tests.factories import TraceBuilder
from tests.fixtures_code import LOOP_V2


def test_enum_is_stored_as_its_value_not_its_repr(db):
    """Python 3.11+에서 f"{EventType.RUN}"은 "RUN"이 아니라 "EventType.RUN"이다.

    payload를 만들 때 항상 .value를 써야 하는 이유. raw SQL로 실제 저장값을 본다.
    """
    b = TraceBuilder.start(db).tick(5).undo()
    rows = db.execute(
        text("SELECT type, source FROM events WHERE session_id = :sid"),
        {"sid": b.session_id},
    ).all()
    types = {r[0] for r in rows}
    sources = {r[1] for r in rows}

    assert types == {"SESSION_START", "UNDO"}
    assert sources == {"SERVER", "CLIENT"}
    assert not any(t.startswith("EventType.") for t in types)


def test_enum_read_back_compares_equal_to_member(db):
    b = TraceBuilder.start(db).tick(5).undo()
    row = db.exec(
        select(Event).where(Event.session_id == b.session_id).where(Event.seq == 2)
    ).one()
    assert row.type == EventType.UNDO
    assert EventType(row.type) is EventType.UNDO


def test_stored_datetimes_are_naive(db):
    """SQLite는 읽을 때 tzinfo를 버린다.

    aware를 저장하면 seconds_without_progress 안에서
    "can't subtract offset-naive and offset-aware"가 런타임에 터진다.
    """
    b = TraceBuilder.start(db).tick(5).undo()
    row = db.exec(
        select(Event).where(Event.session_id == b.session_id).where(Event.seq == 1)
    ).one()
    assert row.server_timestamp.tzinfo is None


def test_every_response_datetime_ends_with_z(client):
    """Pydantic은 naive datetime을 'Z' 없이 직렬화하고 JS는 그걸 로컬로 파싱한다.

    KST면 9시간이 조용히 밀려 타임라인이 무의미해진다.
    """
    sid = client.post("/sessions", json={"problem_id": "func_sum_list"}).json()[
        "session_id"
    ]
    client.post(
        f"/sessions/{sid}/events",
        json={"events": [{"type": "CODE_SNAPSHOT", "payload": {"code": LOOP_V2}}]},
    )
    client.post(
        f"/sessions/{sid}/results",
        json={"mode": "run", "status": "WRONG_ANSWER", "passed": 3, "total": 5},
    )
    client.post(f"/sessions/{sid}/finish")

    paths = [
        f"/sessions/{sid}",
        f"/sessions/{sid}/events",
        f"/sessions/{sid}/timeline",
        f"/sessions/{sid}/process-state",
        f"/sessions/{sid}/snapshots",
        f"/sessions/{sid}/snapshots/2",
    ]
    checked = 0
    for path in paths:
        for value in _iter_datetime_like(client.get(path).json()):
            assert value.endswith("Z"), f"{path}: {value}"
            checked += 1
    assert checked > 0


def _iter_datetime_like(node):
    """ISO 8601처럼 생긴 문자열만 골라낸다."""
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, str) and _looks_like_iso(v):
                yield v
            else:
                yield from _iter_datetime_like(v)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_datetime_like(item)


def _looks_like_iso(s: str) -> bool:
    return (
        len(s) >= 19
        and s[4] == "-"
        and s[7] == "-"
        and s[10] == "T"
        and s[13] == ":"
        and s[16] == ":"
    )


def test_json_column_round_trips_types(db):
    """Column(JSON)은 int를 int로 돌려줘야 한다 (문자열이 아니라)."""
    b = TraceBuilder.start(db).tick(5).run(3)
    row = db.exec(
        select(Event)
        .where(Event.session_id == b.session_id)
        .where(Event.type == EventType.TEST_RESULT.value)
    ).one()
    assert row.payload["passed"] == 3
    assert isinstance(row.payload["passed"], int)
    assert isinstance(row.payload["failed_categories"], list)


def test_duplicate_event_seq_raises(db):
    """seq 할당이 틀리면 조용한 뒤섞임이 아니라 IntegrityError가 나야 한다.

    (SQLite는 테이블 레벨 UNIQUE를 이름 없는 sqlite_autoindex_*로 구현하므로
     인덱스 이름이 아니라 동작으로 검증한다.)
    """
    b = TraceBuilder.start(db).tick(5).undo()
    db.add(
        Event(
            session_id=b.session_id,
            seq=2,  # 이미 UNDO가 쓴 seq
            type=EventType.RESET,
            source=EventSource.CLIENT,
            payload={},
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_duplicate_client_event_id_raises(db):
    b = TraceBuilder.start(db).tick(5)
    for seq in (2, 3):
        db.add(
            Event(
                session_id=b.session_id,
                seq=seq,
                type=EventType.UNDO,
                source=EventSource.CLIENT,
                payload={},
                client_event_id="dup",
            )
        )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_duplicate_snapshot_version_raises(db):
    b = TraceBuilder.start(db).tick(5)
    db.add(CodeSnapshot(session_id=b.session_id, version=1, code="x = 1"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
