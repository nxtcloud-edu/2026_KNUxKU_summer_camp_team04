from __future__ import annotations

from datetime import datetime

from sqlmodel import Session as DbSession

from app.clock import utcnow
from app.enums import EventSource, EventType, SessionStatus
from app.models import Session
from app.problems.service import ProblemRepository
from app.sessions import store
from app.sessions.schemas import SessionRead
from app.trace import service as trace_service


def create_session(
    db: DbSession,
    repo: ProblemRepository,
    *,
    problem_id: str,
    user_id: str,
    at: datetime | None = None,
) -> Session:
    """세션 생성. 한 트랜잭션에서 네 가지를 한다.

    1. problem_id 검증 (없으면 404)
    2. 세션 행 insert
    3. SESSION_START 이벤트 (seq=1)
    4. **스냅샷 v1 = 문제의 code_template**

    4번이 중요하다. 버전 번호가 템플릿에서 시작하므로 학생의 *첫 편집*이 v2가 되고
    starter code 대비 의미 있는 diff를 만든다. 이게 없으면 v1이
    "debounce가 처음 걸릴 때까지 학생이 친 무언가"가 되고 첫 diff는 쓰레기가 된다.
    GET /snapshots/1이 Process Replay의 기준점이 되는 것도 이 덕분이다.
    """
    problem = repo.get(problem_id)  # 없으면 ProblemNotFound(404)
    now = at or utcnow()

    session = Session(
        user_id=user_id,
        problem_id=problem_id,
        status=SessionStatus.SOLVING,
        started_at=now,
    )
    db.add(session)
    db.flush()

    trace_service.append_event(
        db,
        session_id=session.id,
        type=EventType.SESSION_START,
        source=EventSource.SERVER,
        payload={"problem_id": problem_id, "user_id": user_id},
        at=now,
    )
    trace_service.create_snapshot(
        db, session_id=session.id, code=problem.code_template, at=now
    )

    db.commit()
    db.refresh(session)
    return session


def finish_session(
    db: DbSession, session: Session, *, at: datetime | None = None
) -> Session:
    """세션 종료. **멱등하다.**

    두 번째 호출은 같은 body로 200을 반환하고 두 번째 SESSION_END를 쓰지 않는다.
    409를 반환하면 no-op에 대한 대가로 데모 중 빨간 에러 박스가 뜬다.
    """
    if session.status is SessionStatus.FINISHED or session.status == "FINISHED":
        return session

    now = at or utcnow()
    session.status = SessionStatus.FINISHED
    session.finished_at = now
    db.add(session)

    trace_service.append_event(
        db,
        session_id=session.id,
        type=EventType.SESSION_END,
        source=EventSource.SERVER,
        payload={"reason": "finished"},
        code_version=session.last_code_version or None,
        at=now,
    )
    db.commit()
    db.refresh(session)
    return session


def to_read(db: DbSession, session: Session) -> SessionRead:
    snap = store.latest_snapshot(db, session.id)
    return SessionRead(
        session_id=session.id,
        user_id=session.user_id,
        problem_id=session.problem_id,
        status=SessionStatus(session.status),
        started_at=session.started_at,
        finished_at=session.finished_at,
        last_code_version=session.last_code_version,
        last_event_seq=session.last_event_seq,
        current_code=snap.code if snap else "",
        current_code_version=snap.version if snap else 0,
    )
