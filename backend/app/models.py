"""모든 SQLModel 테이블.

왜 한 파일인가 (backend_plan §4의 패키지별 배치에서 의도적으로 벗어남):
SQLModel/SQLAlchemy는 create_all 전에 모든 테이블 클래스가 같은 MetaData에
등록되어 있어야 하고, FK를 "sessions.id" 문자열로 참조한다.
패키지별 모델 파일은 2일 빌드에서 순환 import 아니면 NoReferencedTableError를 낳는다.
150줄짜리 파일 하나가 둘 다 피한다.

problems / test_cases 테이블은 **없다**. 문제는 app/problems/data/*.json이 진실이다.
origin/judge의 load_problem()이 이미 JSON 파일을 읽으므로, DB에도 문제를 두면
병합 시점에 judge는 파일로 채점하고 API는 DB를 서빙하며 반드시 drift한다.
채점 대상에 대해 진실이 둘인 것이 여기서 가능한 최악의 실패 모드다.
부수 효과: hidden test가 ORM 모델에 실리지 않으므로 어떤 response_model 실수도
hidden input을 내보낼 수 없다.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy import JSON, Column, Float, Index, String, Text, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.clock import utcnow
from app.enums import EventSource, EventType, SessionStatus


def _id(prefix: str) -> Callable[[], str]:
    """sess_/evt_/snap_ 접두어를 붙인 UUID.

    autoincrement 대신 쓰는 이유:
    1. int PK는 flush 전엔 존재하지 않아 "이벤트 5개 insert하고 5개 다 id와 함께 반환"이
       행마다 flush를 강요한다.
    2. 접두어 덕분에 curl 출력과 데모 로그가 self-describing해진다.
    3. 순서는 PK가 아니라 seq가 명시적으로 운반한다. autoincrement PK는 *순서처럼 보여서*
       사람들이 의존하기 시작하고, 그러면 out-of-band insert 한 번에 깨진다.
    """
    return lambda: f"{prefix}_{uuid4().hex}"


class Session(SQLModel, table=True):
    __tablename__ = "sessions"

    id: str = Field(default_factory=_id("sess"), primary_key=True, max_length=64)
    user_id: str = Field(default="demo-user", index=True, max_length=64)
    # FK 없음: 문제는 DB가 아니라 JSON 파일에 산다. 세션 생성 시 repository로 검증한다.
    problem_id: str = Field(index=True, max_length=64)
    status: SessionStatus = Field(
        sa_column=Column(String(16), nullable=False, index=True)
    )
    started_at: datetime = Field(default_factory=utcnow, index=True)
    finished_at: datetime | None = Field(default=None)

    # 서버가 원자적으로 **할당**하는 카운터. denormalize하는 건 이 둘뿐이다.
    # last_progress_at / best_passed / last_intervention_at은 일부러 없다 --
    # 전부 events에서 파생 가능하고, 세션당 이벤트는 O(10^2)라 full scan이 sub-ms다.
    # denormalize된 파생 상태는 "패널은 STUCK인데 타임라인은 5/5"류 버그의 1순위 원인이다.
    last_code_version: int = Field(default=0, nullable=False)
    last_event_seq: int = Field(default=0, nullable=False)


class CodeSnapshot(SQLModel, table=True):
    """코드 스냅샷 + 직전 버전 대비 diff (insert 시점에 1회 계산해 denormalize).

    diff를 여기 붙이는 이유: insert마다 1회 계산되지만 feature 추출과 timeline 렌더
    **매번** 읽힌다. 요청마다 difflib을 N쌍 돌리는 건 순수 낭비이고,
    same_region_edit_count가 primary_region 인덱스 스캔 한 번이 된다.
    별도 code_diffs 테이블은 이 테이블과 정확히 1:1이라 join 값어치가 없다.
    """

    __tablename__ = "code_snapshots"

    id: str = Field(default_factory=_id("snap"), primary_key=True, max_length=64)
    session_id: str = Field(foreign_key="sessions.id", index=True, max_length=64)
    version: int = Field(nullable=False)
    code: str = Field(sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(default_factory=utcnow, index=True)

    parent_version: int | None = Field(default=None)
    added_line_count: int = Field(default=0)
    deleted_line_count: int = Field(default=0)
    change_size: int = Field(default=0)  # added + deleted
    change_ratio: float = Field(sa_column=Column(Float, nullable=False, default=0.0))
    seconds_since_parent: int = Field(default=0)
    changed_lines: list[int] = Field(default_factory=list, sa_column=Column(JSON))
    region_tags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    primary_region: str = Field(
        sa_column=Column(String(24), nullable=False, default="other", index=True)
    )
    summary: str = Field(default="", max_length=200)

    __table_args__ = (
        UniqueConstraint("session_id", "version", name="uq_snapshot_session_version"),
        Index("ix_snapshot_session_version", "session_id", "version"),
    )


class Event(SQLModel, table=True):
    __tablename__ = "events"

    id: str = Field(default_factory=_id("evt"), primary_key=True, max_length=64)
    session_id: str = Field(foreign_key="sessions.id", index=True, max_length=64)
    # 세션 내 1-based 단조 증가. 시스템의 **모든** 순서 읽기가 이걸 쓴다.
    seq: int = Field(nullable=False)
    # enum은 sa.Enum이 아니라 String으로 저장한다:
    # sa.Enum은 CHECK (type IN (...)) 제약을 테이블에 구워버리고 create_all은 ALTER를 못 한다.
    # agent 브랜치가 ACTIVITY_EVALUATED를 추가하는 순간 기존 codetrace.db의 모든 insert가
    # 불투명한 IntegrityError로 죽는다. String은 sa.Enum이 .name을 저장하는 함정도 피한다.
    # (EventType이 str을 상속하므로 저장은 그대로 되고, 읽으면 평범한 str이 나오는데
    #  이건 여전히 EventType 멤버와 == 비교가 되고 Pydantic이 응답에서 다시 enum으로 강제한다.)
    type: EventType = Field(sa_column=Column(String(32), nullable=False, index=True))
    source: EventSource = Field(sa_column=Column(String(16), nullable=False))
    code_version: int | None = Field(default=None)
    payload: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    server_timestamp: datetime = Field(default_factory=utcnow, index=True)
    client_timestamp: datetime | None = Field(default=None)
    # 멱등성 키. 프론트가 crypto.randomUUID()로 만들어 보낸다.
    # SQLite는 UNIQUE에서 NULL을 서로 다른 값으로 취급하므로 NULL 행은 무제한 공존한다
    # -- dedup은 이벤트별 opt-in이다.
    client_event_id: str | None = Field(default=None, max_length=64)

    __table_args__ = (
        UniqueConstraint("session_id", "seq", name="uq_event_session_seq"),
        UniqueConstraint(
            "session_id", "client_event_id", name="uq_event_session_client_id"
        ),
        Index("ix_event_session_seq", "session_id", "seq"),
        Index("ix_event_session_type_seq", "session_id", "type", "seq"),
    )
