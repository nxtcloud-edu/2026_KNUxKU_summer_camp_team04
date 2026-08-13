"""Trace 쓰기 경로: 이벤트 수집, 스냅샷 기록, judge 결과 기록.

불변 규칙 (깨지면 조용히 틀린다):
  * **모든 순서 읽기는 seq로 정렬한다. 절대 timestamp가 아니다.**
    배치 이벤트는 server_timestamp가 동일하고(microsecond 절삭), 클라이언트 시계는
    무의미하다. 여섯 시간 뒤에 누가 선의로 `ORDER BY server_timestamp`를 넣으면 깨진다.
  * event.payload는 insert 후 불변이다. JSON 컬럼은 in-place 변경을 추적하지 않아
    `payload["x"] = 1` 후 commit하면 아무것도 저장되지 않는다. 바꾸려면 dict를 통째로 재할당.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session as DbSession
from sqlmodel import select

from app.clock import seconds_between, to_naive_utc, utcnow
from app.enums import SERVER_ONLY_EVENT_TYPES, EventSource, EventType
from app.errors import (
    InvalidCodeVersion,
    MissingSnapshotCode,
    ServerOnlyEvent,
)
from app.models import CodeSnapshot, Event, Session
from app.sessions import store
from app.trace.diff import compute_diff

# --------------------------------------------------------------------- 읽기


def all_events(db: DbSession, session_id: str) -> list[Event]:
    """세션의 모든 이벤트를 seq 오름차순으로. (timestamp 아님 -- 위 주석 참조)"""
    return list(
        db.exec(
            select(Event)
            .where(Event.session_id == session_id)
            .order_by(Event.seq)  # type: ignore[arg-type]
        ).all()
    )


def events_since(
    db: DbSession, session_id: str, *, since_seq: int = 0, limit: int = 500
) -> list[Event]:
    return list(
        db.exec(
            select(Event)
            .where(Event.session_id == session_id)
            .where(Event.seq > since_seq)
            .order_by(Event.seq)  # type: ignore[arg-type]
            .limit(limit)
        ).all()
    )


# --------------------------------------------------------------------- 쓰기 helper


def append_event(
    db: DbSession,
    *,
    session_id: str,
    type: EventType,
    source: EventSource,
    payload: dict[str, Any] | None = None,
    code_version: int | None = None,
    client_event_id: str | None = None,
    client_timestamp: datetime | None = None,
    at: datetime | None = None,
    seq: int | None = None,
) -> Event:
    """이벤트 1건을 추가한다. flush까지만 하고 commit은 호출자가 한다."""
    if seq is None:
        seq = store.allocate_event_seqs(db, session_id, 1)[0]
    event = Event(
        session_id=session_id,
        seq=seq,
        type=type,
        source=source,
        code_version=code_version,
        # enum은 항상 .value로 넣는다. Python 3.11+에서 f"{EventType.RUN}"은
        # "RUN"이 아니라 "EventType.RUN"이다.
        payload=payload or {},
        server_timestamp=at or utcnow(),
        client_timestamp=to_naive_utc(client_timestamp),
        client_event_id=client_event_id,
    )
    db.add(event)
    db.flush()
    return event


def create_snapshot(
    db: DbSession,
    *,
    session_id: str,
    code: str,
    at: datetime | None = None,
    version: int | None = None,
) -> tuple[CodeSnapshot, bool]:
    """스냅샷을 만든다. 반환값 (snapshot, created).

    코드가 최신 스냅샷과 바이트 동일하면 새 버전을 만들지 않고 기존 행을 돌려준다
    (created=False). debounce + undo/redo는 동일 스냅샷을 끊임없이 만들어내는데,
    이걸 막지 않으면 no-op 편집으로 same_region_edit_count가 부풀려진다.
    """
    now = at or utcnow()
    prev = store.latest_snapshot(db, session_id)

    if prev is not None and prev.code == code:
        return prev, False

    if version is None:
        version = store.allocate_code_version(db, session_id)

    d = compute_diff(
        prev.code if prev else None,
        code,
        from_version=prev.version if prev else None,
        to_version=version,
    )
    snapshot = CodeSnapshot(
        session_id=session_id,
        version=version,
        code=code,
        created_at=now,
        parent_version=prev.version if prev else None,
        added_line_count=d.added_line_count,
        deleted_line_count=d.deleted_line_count,
        change_size=d.change_size,
        change_ratio=d.change_ratio,
        seconds_since_parent=seconds_between(prev.created_at, now) if prev else 0,
        changed_lines=d.changed_lines,
        region_tags=d.region_tags,
        primary_region=d.primary_region,
        summary=d.summary,
    )
    db.add(snapshot)
    db.flush()
    return snapshot, True


# --------------------------------------------------------------------- 이벤트 수집


def _existing_client_event_ids(
    db: DbSession, session_id: str, candidate_ids: list[str]
) -> set[str]:
    if not candidate_ids:
        return set()
    rows = db.exec(
        select(Event.client_event_id)
        .where(Event.session_id == session_id)
        .where(Event.client_event_id.in_(candidate_ids))  # type: ignore[union-attr]
    ).all()
    return {r for r in rows if r is not None}


def ingest_events(
    db: DbSession,
    session: Session,
    incoming: list[Any],
    *,
    now: datetime | None = None,
) -> tuple[list[Event], list[str]]:
    """배치 수집. 반환값 (accepted_events, duplicate_client_event_ids).

    멱등성은 선택이 아니다. frontend_plan §7이 실패 시 메모리 큐 재시도를 명시하는데,
    전형적 실패는 "서버는 커밋했는데 응답이 유실, 클라이언트가 재시도"다.
    dedup이 없으면 데모장 wifi가 한 번 끊길 때 RUN 3/5가 다섯 번 기록되고
    monitor가 한 번 실행한 학생에게 REPEATED_FAILURE를 외친다.
    """
    now = now or utcnow()

    candidate_ids = [e.client_event_id for e in incoming if e.client_event_id]
    known = _existing_client_event_ids(db, session.id, candidate_ids)

    duplicates: list[str] = []
    fresh: list[Any] = []
    seen_in_batch: set[str] = set()
    for e in incoming:
        cid = e.client_event_id
        if cid and (cid in known or cid in seen_in_batch):
            duplicates.append(cid)
            continue
        if cid:
            seen_in_batch.add(cid)
        fresh.append(e)

    if not fresh:
        return [], duplicates

    accepted: list[Event] = []
    try:
        for item in fresh:
            event_type = EventType(item.type.value)
            # 방어선 2 (1은 EventIn.type의 ClientEventType 타이핑).
            # 누가 나중에 요청 스키마를 넓히면 여기서 막힌다.
            if event_type in SERVER_ONLY_EVENT_TYPES:
                raise ServerOnlyEvent(event_type.value)

            if event_type is EventType.CODE_SNAPSHOT:
                accepted.append(_ingest_code_snapshot(db, session, item, now))
            else:
                accepted.append(
                    append_event(
                        db,
                        session_id=session.id,
                        type=event_type,
                        source=EventSource.CLIENT,
                        payload=dict(item.payload or {}),
                        code_version=session.last_code_version or None,
                        client_event_id=item.client_event_id,
                        client_timestamp=item.client_timestamp,
                        at=now,
                    )
                )
        db.commit()
    except IntegrityError:
        # backstop: 동일 배치의 동시 재시도가 UNIQUE 제약에 걸린 경우.
        # 롤백하고 다시 조회해 전부 중복으로 보고한다.
        db.rollback()
        known = _existing_client_event_ids(db, session.id, candidate_ids)
        return [], sorted(set(duplicates) | known)

    for e in accepted:
        db.refresh(e)
    db.refresh(session)
    return accepted, duplicates


def _ingest_code_snapshot(
    db: DbSession, session: Session, item: Any, now: datetime
) -> Event:
    code = (item.payload or {}).get("code")
    if not isinstance(code, str):
        raise MissingSnapshotCode()

    snapshot, created = create_snapshot(db, session_id=session.id, code=code, at=now)

    # raw code는 이벤트 payload에서 **제거한다.**
    # 안 그러면 events 테이블이 제2의 코드 저장소가 되고, GET /events가 메가바이트를
    # 뱉고, agent context builder가 "현재 코드"를 읽을 곳이 둘이 된다.
    # 코드는 code_snapshots에만 있고 code_version으로 참조한다.
    payload = {
        "code_length": len(code),
        "line_count": len(code.splitlines()),
        "change_ratio": snapshot.change_ratio,
        "changed_lines": snapshot.changed_lines,
        "region_tags": snapshot.region_tags,
        "primary_region": snapshot.primary_region,
        "summary": snapshot.summary,
        "deduplicated": not created,
    }
    return append_event(
        db,
        session_id=session.id,
        type=EventType.CODE_SNAPSHOT,
        source=EventSource.CLIENT,
        payload=payload,
        code_version=snapshot.version,
        client_event_id=item.client_event_id,
        client_timestamp=item.client_timestamp,
        at=now,
    )


# --------------------------------------------------------------------- Judge 결과


def record_judge_result(
    db: DbSession,
    session: Session,
    *,
    mode: str,
    status: str,
    passed: int,
    total: int,
    runtime_ms: int | None = None,
    message: str | None = None,
    failed_categories: list[str] | None = None,
    code_version: int | None = None,
    produced_by: EventSource = EventSource.CLIENT_JUDGE,
    judge_name: str = "pyodide",
    client_event_id: str | None = None,
    client_timestamp: datetime | None = None,
    now: datetime | None = None,
) -> Event:
    """TEST_RESULT를 쓰는 **유일한** 경로.

    오늘: 브라우저 Pyodide -> POST /results -> produced_by=CLIENT_JUDGE
    나중: POST /run -> get_judge().judge() -> produced_by=SERVER

    두 경로가 바이트 동일한 TEST_RESULT 행 모양을 쓴다. source와 payload.judge만 다르고,
    features.py와 monitor.py는 둘 다 읽지 않는다 -- 하나의 균일한 결과 스트림만 본다.
    결과적으로 client judge -> server judge 전환은 **프론트엔드만의 변경**이 된다.
    """
    now = now or utcnow()
    if code_version is None:
        code_version = session.last_code_version or None
    elif code_version > session.last_code_version:
        raise InvalidCodeVersion(code_version, session.last_code_version)

    payload = {
        "mode": mode,
        "status": status,
        "passed": passed,
        "total": total,
        "runtime_ms": runtime_ms,
        "message": message,
        "failed_categories": list(failed_categories or []),
        "judge": judge_name,
    }
    event = append_event(
        db,
        session_id=session.id,
        type=EventType.TEST_RESULT,
        source=produced_by,
        payload=payload,
        code_version=code_version,
        client_event_id=client_event_id,
        client_timestamp=client_timestamp,
        at=now,
    )
    db.commit()
    db.refresh(event)
    db.refresh(session)
    return event
