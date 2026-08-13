"""세션 행 조회 + 카운터 원자 할당.

leaf 모듈이다. sessions.service와 trace.service가 **둘 다** 이걸 import하므로
여기서는 app.models / app.errors 외에 아무것도 import하지 않는다 (순환 방지).
"""
from __future__ import annotations

from sqlalchemy import text
from sqlmodel import Session as DbSession
from sqlmodel import select

from app.errors import SessionNotFound
from app.models import CodeSnapshot, Session


def get_session(db: DbSession, session_id: str) -> Session | None:
    return db.get(Session, session_id)


def require_session(db: DbSession, session_id: str) -> Session:
    row = db.get(Session, session_id)
    if row is None:
        raise SessionNotFound(session_id)
    return row


def allocate_code_version(db: DbSession, session_id: str) -> int:
    """다음 code_version을 원자적으로 할당한다.

    `UPDATE ... SET x = x + 1 ... RETURNING x`는 단일 원자 statement다 (SQLite 3.35+).
    Python 레벨의 read-modify-write가 없으므로 동시 요청 둘은 SQLite 쓰기 잠금에서
    직렬화되고 서로 다른 값을 받는다.

    요청 트랜잭션 안에서 돌기 때문에 이후 실패는 할당을 롤백한다. 재시도 시 번호에
    구멍이 날 수 있지만 무해하다 -- seq/version은 단조여야 하지 빈틈없을 필요는 없다.
    진짜 backstop은 UNIQUE(session_id, version) 제약이다: 할당이 틀리면
    조용한 뒤섞임이 아니라 IntegrityError가 난다.

    전제: uvicorn --workers 1. SQLite + 다중 워커 + 핫 카운터 행은 database-is-locked 생성기다.
    """
    row = db.execute(
        text(
            "UPDATE sessions SET last_code_version = last_code_version + 1 "
            "WHERE id = :sid RETURNING last_code_version"
        ),
        {"sid": session_id},
    ).first()
    if row is None:
        raise SessionNotFound(session_id)
    return int(row[0])


def allocate_event_seqs(db: DbSession, session_id: str, n: int) -> list[int]:
    """seq n개를 한 번에 예약한다.

    배치 할당이 중요하다: 5개짜리 배치를 루프로 한 개씩 할당하면 쓰기 statement가 5번이고
    끼어들 기회도 5번이다.
    """
    if n <= 0:
        return []
    row = db.execute(
        text(
            "UPDATE sessions SET last_event_seq = last_event_seq + :n "
            "WHERE id = :sid RETURNING last_event_seq"
        ),
        {"sid": session_id, "n": n},
    ).first()
    if row is None:
        raise SessionNotFound(session_id)
    last = int(row[0])
    return list(range(last - n + 1, last + 1))


def latest_snapshot(db: DbSession, session_id: str) -> CodeSnapshot | None:
    return db.exec(
        select(CodeSnapshot)
        .where(CodeSnapshot.session_id == session_id)
        .order_by(CodeSnapshot.version.desc())  # type: ignore[union-attr]
        .limit(1)
    ).first()


def snapshot_at(db: DbSession, session_id: str, version: int) -> CodeSnapshot | None:
    return db.exec(
        select(CodeSnapshot)
        .where(CodeSnapshot.session_id == session_id)
        .where(CodeSnapshot.version == version)
    ).first()


def all_snapshots(db: DbSession, session_id: str) -> list[CodeSnapshot]:
    return list(
        db.exec(
            select(CodeSnapshot)
            .where(CodeSnapshot.session_id == session_id)
            .order_by(CodeSnapshot.version)  # type: ignore[arg-type]
        ).all()
    )
