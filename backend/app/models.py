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
from app.enums import (
    AcornTransactionType,
    CodeVisibility,
    EnrollmentStatus,
    EventSource,
    EventType,
    GeneratedProblemStatus,
    LearningStatus,
    ProgressStatus,
    SessionStatus,
    UserRole,
)


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


class Organization(SQLModel, table=True):
    """제휴 교육기관. users 보다 먼저 정의해야 FK 등록 순서가 맞는다."""

    __tablename__ = "organizations"

    id: str = Field(default_factory=_id("org"), primary_key=True, max_length=64)
    name: str = Field(max_length=128, nullable=False)
    # 허용 이메일 도메인. "univ.ac.kr" 형태. 비어 있으면 도메인 검사를 하지 않는다.
    domain: str = Field(default="", max_length=128, index=True)
    # 교수자 가입에 쓰는 코드. 이게 없으면 아무나 EDUCATOR로 가입할 수 있다.
    invite_code: str = Field(
        sa_column=Column(String(64), nullable=False, unique=True, index=True)
    )
    is_active: bool = Field(default=True, nullable=False)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: str = Field(default_factory=_id("user"), primary_key=True, max_length=64)
    # 소문자로 정규화해서 저장한다. 대소문자만 다른 중복 가입을 막는 유일한 방법이
    # UNIQUE 제약이므로, 정규화를 서비스 계층에만 두면 언젠가 새어 나간다.
    email: str = Field(sa_column=Column(String(255), nullable=False, unique=True, index=True))
    password_hash: str = Field(sa_column=Column(String(255), nullable=False))
    name: str = Field(max_length=64, nullable=False)
    nickname: str = Field(sa_column=Column(String(32), nullable=False, unique=True, index=True))
    avatar_url: str | None = Field(default=None, max_length=512)
    # 권한의 유일한 근거. 요청 body의 role을 신뢰하지 않는다.
    role: UserRole = Field(
        sa_column=Column(String(16), nullable=False, index=True, default=UserRole.STUDENT.value)
    )
    # 교수자는 가입 시 기관 초대 코드를 요구한다. 학생은 비어 있을 수 있다.
    organization_id: str | None = Field(
        default=None, foreign_key="organizations.id", index=True, max_length=64
    )

    # 잔액은 acorn_transactions 의 **캐시**다. 원장이 진실이고 이건 빠른 조회용이다.
    # 둘은 같은 트랜잭션 안에서만 함께 움직인다 (acorns/service.py 참조).
    acorn_balance: int = Field(default=0, nullable=False)
    total_acorns_earned: int = Field(default=0, nullable=False)

    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)
    last_login_at: datetime | None = Field(default=None)
    is_active: bool = Field(default=True, nullable=False)


class AcornTransaction(SQLModel, table=True):
    """도토리 원장. **잔액을 직접 증감하지 않고 여기에 한 줄을 쓴다.**

    users.acorn_balance 만 고치면 "왜 135개지?"에 답할 수 없고, 중복 지급을
    사후에 찾아낼 방법도 없다. balance_after 를 함께 적어두면 원장을 되짚어
    잔액이 어디서 어긋났는지 정확히 짚을 수 있다.
    """

    __tablename__ = "acorn_transactions"

    id: str = Field(default_factory=_id("acorn_tx"), primary_key=True, max_length=64)
    user_id: str = Field(foreign_key="users.id", index=True, max_length=64)
    amount: int = Field(nullable=False)  # 양수=획득, 음수=사용
    balance_after: int = Field(nullable=False)
    transaction_type: AcornTransactionType = Field(
        sa_column=Column(String(32), nullable=False, index=True)
    )
    reference_type: str | None = Field(default=None, max_length=32)
    reference_id: str | None = Field(default=None, max_length=64)
    description: str = Field(default="", max_length=200)
    # 중복 지급 방지의 **전부**다. "이 사용자가 이 문제를 처음 풀었다"를
    # 애플리케이션 로직이 아니라 DB 제약이 보장한다.
    idempotency_key: str | None = Field(
        sa_column=Column(String(128), nullable=True, unique=True, index=True)
    )
    created_at: datetime = Field(default_factory=utcnow, index=True)


class Course(SQLModel, table=True):
    __tablename__ = "courses"

    id: str = Field(default_factory=_id("course"), primary_key=True, max_length=64)
    organization_id: str = Field(foreign_key="organizations.id", index=True, max_length=64)
    title: str = Field(max_length=128, nullable=False)
    term: str = Field(default="", max_length=64)
    educator_id: str = Field(foreign_key="users.id", index=True, max_length=64)
    # 학생이 강의에 스스로 들어올 때 쓰는 코드. 기관 코드와는 별개다.
    invite_code: str = Field(
        sa_column=Column(String(64), nullable=False, unique=True, index=True)
    )
    # **교수자가 강의별로 정한다.** 학생 코드를 어디까지 보여줄지.
    code_visibility: CodeVisibility = Field(
        sa_column=Column(String(24), nullable=False, default=CodeVisibility.SUBMITTED_ONLY.value)
    )
    start_at: datetime | None = Field(default=None)
    end_at: datetime | None = Field(default=None)
    is_active: bool = Field(default=True, nullable=False)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


class CourseProblem(SQLModel, table=True):
    """강의에 배정된 문제.

    진도율의 **분모**다. 비어 있으면 저장소의 전체 문제를 기준으로 계산한다
    (educator/service.py 참조) -- 강의를 막 만들었을 때 진도율이 0/0이 되어
    ZeroDivisionError 나 NaN 이 화면에 뜨는 것을 막는다.
    """

    __tablename__ = "course_problems"

    id: str = Field(default_factory=_id("cprob"), primary_key=True, max_length=64)
    course_id: str = Field(foreign_key="courses.id", index=True, max_length=64)
    problem_id: str = Field(index=True, max_length=64)
    order: int = Field(default=0, nullable=False)

    __table_args__ = (
        UniqueConstraint("course_id", "problem_id", name="uq_course_problem"),
    )


class Assignment(SQLModel, table=True):
    """교수자가 강의에 배정한 문제 묶음."""

    __tablename__ = "assignments"

    id: str = Field(default_factory=_id("assign"), primary_key=True, max_length=64)
    course_id: str = Field(foreign_key="courses.id", index=True, max_length=64)
    title: str = Field(max_length=128, nullable=False)
    description: str = Field(default="", max_length=500)
    problem_ids: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    due_at: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


class Enrollment(SQLModel, table=True):
    __tablename__ = "enrollments"

    id: str = Field(default_factory=_id("enroll"), primary_key=True, max_length=64)
    course_id: str = Field(foreign_key="courses.id", index=True, max_length=64)
    student_id: str = Field(foreign_key="users.id", index=True, max_length=64)
    status: EnrollmentStatus = Field(
        sa_column=Column(String(16), nullable=False, index=True)
    )
    enrolled_at: datetime = Field(default_factory=utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("course_id", "student_id", name="uq_enrollment_course_student"),
    )


class StudentCourseStats(SQLModel, table=True):
    """학생×강의 요약. 대시보드와 학생 목록이 읽는다.

    실시간으로 전부 계산하면 학생 28명 × 문제 26개마다 events 를 훑어야 한다.
    채점이 끝날 때마다 해당 학생 행 하나만 갱신하는 편이 훨씬 싸다.
    **파생 데이터이므로 진실은 언제나 user_problem_progress 와 events 다** --
    어긋나면 여기를 다시 계산한다.
    """

    __tablename__ = "student_course_stats"

    id: str = Field(default_factory=_id("stats"), primary_key=True, max_length=64)
    course_id: str = Field(foreign_key="courses.id", index=True, max_length=64)
    student_id: str = Field(foreign_key="users.id", index=True, max_length=64)
    progress_rate: int = Field(default=0, nullable=False)  # 0~100
    solved_count: int = Field(default=0, nullable=False)
    assigned_count: int = Field(default=0, nullable=False)
    attempt_count: int = Field(default=0, nullable=False)
    last_active_at: datetime | None = Field(default=None, index=True)
    learning_status: LearningStatus = Field(
        sa_column=Column(String(16), nullable=False, index=True)
    )
    primary_weak_concept: str | None = Field(default=None, max_length=64)
    risk_score: int = Field(default=0, nullable=False, index=True)
    # 왜 이 점수인지. 교육자 화면이 그대로 렌더한다.
    reasons: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    calculated_at: datetime = Field(default_factory=utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("course_id", "student_id", name="uq_stats_course_student"),
        Index("ix_stats_course_risk", "course_id", "risk_score"),
    )


class UserProblemProgress(SQLModel, table=True):
    """사용자별 문제 진행 요약.

    sessions/events 로도 계산할 수 있지만, 홈에서 26개 문제 상태를 한 번에
    조회하려면 세션 전체를 훑어야 한다. 이건 그 조회를 위한 요약 테이블이다.
    Checkpoint(작성 중인 코드)도 여기 산다 -- 기기가 바뀌어도 이어서 풀 수 있게.
    """

    __tablename__ = "user_problem_progress"

    id: str = Field(default_factory=_id("prog"), primary_key=True, max_length=64)
    user_id: str = Field(foreign_key="users.id", index=True, max_length=64)
    problem_id: str = Field(index=True, max_length=64)
    # 강의 맥락. **NULL이 아니라 빈 문자열이 "개인 학습"이다.**
    # SQLite(및 표준 SQL)는 UNIQUE에서 NULL을 서로 다른 값으로 취급하므로,
    # nullable로 두면 course_id=NULL 행이 같은 (user, problem)에 대해
    # 몇 개든 생긴다 -- 제약이 있으나 마나 해진다.
    course_id: str = Field(default="", index=True, max_length=64)
    status: ProgressStatus = Field(sa_column=Column(String(16), nullable=False, index=True))
    current_code: str = Field(default="", sa_column=Column(Text, nullable=False))
    best_passed: int = Field(default=0, nullable=False)
    total_tests: int = Field(default=0, nullable=False)
    attempt_count: int = Field(default=0, nullable=False)
    last_judge_status: str | None = Field(default=None, max_length=32)
    # submit 으로 채점된 마지막 코드. current_code(작성 중)와 별개다 --
    # 교수자가 SUBMITTED_ONLY 를 고르면 이쪽만 보여준다.
    last_submitted_code: str = Field(default="", sa_column=Column(Text, nullable=False))
    last_submitted_at: datetime | None = Field(default=None)
    first_started_at: datetime = Field(default_factory=utcnow, nullable=False)
    last_attempted_at: datetime | None = Field(default=None)
    solved_at: datetime | None = Field(default=None)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "user_id", "course_id", "problem_id", name="uq_progress_user_course_problem"
        ),
        Index("ix_progress_user_status", "user_id", "status"),
        Index("ix_progress_course_student", "course_id", "user_id"),
    )


class PasswordResetToken(SQLModel, table=True):
    """비밀번호 재설정 토큰.

    **원문이 아니라 해시를 저장한다.** DB가 유출돼도 토큰을 쓸 수 없어야 한다.
    재설정 API 자체는 이번 범위 밖이지만, 테이블을 지금 만들어두면
    나중에 스키마 변경(= DB 파일 삭제)을 한 번 덜 하게 된다.
    """

    __tablename__ = "password_reset_tokens"

    id: str = Field(default_factory=_id("prt"), primary_key=True, max_length=64)
    user_id: str = Field(foreign_key="users.id", index=True, max_length=64)
    token_hash: str = Field(sa_column=Column(String(128), nullable=False, unique=True, index=True))
    expires_at: datetime = Field(nullable=False)
    used_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


class Session(SQLModel, table=True):
    __tablename__ = "sessions"

    id: str = Field(default_factory=_id("sess"), primary_key=True, max_length=64)
    # 실제 users.id 를 가리키는 FK. 예전에는 "demo-user" 문자열이었다.
    user_id: str = Field(foreign_key="users.id", index=True, max_length=64)
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


class GeneratedProblem(SQLModel, table=True):
    """복습 문제 생성 요청 1건. **문제 내용은 여기 담지 않는다.**

    이 파일 상단의 원칙("문제는 JSON 파일이 진실이다. DB에도 두면 반드시
    drift한다")을 생성 문제에도 그대로 적용한다. 검증을 통과한 문제 본문은
    `Settings.generated_problems_path`에 `*.json`으로 떨어지고, 이 행은
    **누가 언제 무엇으로부터 요청했는지와 그 결과가 어느 problem_id인지만**
    가리킨다. 그래서 여기엔 description도 test case도 없다.

    덕분에 `ProblemRepository.get()` 하나로 큐레이션 문제와 생성 문제가 똑같이
    풀린다 — 세션/채점/agent context는 이 테이블의 존재조차 몰라도 된다.
    """

    __tablename__ = "generated_problems"

    id: str = Field(default_factory=_id("genp"), primary_key=True, max_length=64)
    user_id: str = Field(foreign_key="users.id", index=True, max_length=64)
    # 이 복습의 바탕이 된 문제. 학생이 방금 틀린/막힌 문제다.
    source_problem_id: str = Field(max_length=64, index=True)
    # 생성이 끝나야 정해지므로 PENDING 동안은 None이다. READY면 이 값으로
    # ProblemRepository.get()이 풀린다.
    problem_id: str | None = Field(default=None, max_length=64, index=True)
    status: GeneratedProblemStatus = Field(
        # 다른 테이블과 같은 이유로 sa.Enum이 아니라 String이다 (Event.type 주석 참고):
        # sa.Enum은 CHECK 제약을 구워버려서 나중에 상태를 하나 추가하는 순간
        # 기존 codetrace.db의 insert가 전부 IntegrityError로 죽는다.
        sa_column=Column(String(16), nullable=False, index=True)
    )
    # FAILED일 때 학생/개발자에게 보여줄 이유. judge 검증 실패 사유가 여기 담긴다.
    error_message: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(default_factory=utcnow, index=True)
    completed_at: datetime | None = Field(default=None)
