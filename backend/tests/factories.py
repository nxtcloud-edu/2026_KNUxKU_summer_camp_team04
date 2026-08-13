"""합성 Coding Trace를 산문처럼 쓰기 위한 DSL.

명시적 timestamp로 행을 직접 쓰므로 clock 패치도 sleep도 필요 없다.
경과 시간이 정확하고 테스트가 빠르다.

scripts/seed_demo.py가 이걸 그대로 재사용한다 -- 산출물 하나, 용도 둘.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlmodel import Session as DbSession

from sqlmodel import select

from app.enums import EventSource, EventType, JudgeStatus, SessionStatus, TriggerType
from app.models import Session, User
from app.trace import service as trace_service

TEST_USER_EMAIL = "builder@example.com"


def ensure_test_user(db: DbSession) -> User:
    """TraceBuilder 전용 회원. 이미 있으면 재사용한다."""
    found = db.exec(select(User).where(User.email == TEST_USER_EMAIL)).first()
    if found is not None:
        return found
    user = User(
        email=TEST_USER_EMAIL,
        password_hash="$2b$12$" + "x" * 53,
        name="빌더",
        nickname="빌더",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

T0 = datetime(2026, 8, 13, 12, 0, 0)
DEFAULT_TEMPLATE = "def sum_list(arr):\n    # 여기에 코드를 작성하세요\n    pass"


@dataclass
class TraceBuilder:
    db: DbSession
    session_id: str
    t: datetime
    total: int = 5
    _codes: list[str] = field(default_factory=list)

    @classmethod
    def start(
        cls,
        db: DbSession,
        *,
        problem_id: str = "func_sum_list",
        user_id: str | None = None,
        at: datetime = T0,
        code: str = DEFAULT_TEMPLATE,
        total: int = 5,
    ) -> "TraceBuilder":
        # sessions.user_id 가 users.id FK 가 되면서 실제 회원 행이 있어야 한다.
        # 지정하지 않으면 이 빌더가 하나 만들어 쓴다 -- 순수 trace 테스트가
        # 회원 준비 코드를 반복하지 않게 하기 위해서.
        if user_id is None:
            user_id = ensure_test_user(db).id

        session = Session(
            user_id=user_id,
            problem_id=problem_id,
            status=SessionStatus.SOLVING,
            started_at=at,
        )
        db.add(session)
        db.flush()
        trace_service.append_event(
            db,
            session_id=session.id,
            type=EventType.SESSION_START,
            source=EventSource.SERVER,
            payload={"problem_id": problem_id, "user_id": user_id},
            at=at,
        )
        trace_service.create_snapshot(db, session_id=session.id, code=code, at=at)
        db.commit()
        return cls(db=db, session_id=session.id, t=at, total=total, _codes=[code])

    # ---------------------------------------------------------------- 시간

    def tick(self, seconds: int) -> "TraceBuilder":
        self.t += timedelta(seconds=seconds)
        return self

    # ---------------------------------------------------------------- 행동

    def edit(self, code: str) -> "TraceBuilder":
        snapshot, created = trace_service.create_snapshot(
            self.db, session_id=self.session_id, code=code, at=self.t
        )
        trace_service.append_event(
            self.db,
            session_id=self.session_id,
            type=EventType.CODE_SNAPSHOT,
            source=EventSource.CLIENT,
            payload={
                "code_length": len(code),
                "line_count": len(code.splitlines()),
                "change_ratio": snapshot.change_ratio,
                "changed_lines": snapshot.changed_lines,
                "region_tags": snapshot.region_tags,
                "primary_region": snapshot.primary_region,
                "summary": snapshot.summary,
                "deduplicated": not created,
            },
            code_version=snapshot.version,
            at=self.t,
        )
        self.db.commit()
        self._codes.append(code)
        return self

    def run(
        self,
        passed: int,
        total: int | None = None,
        *,
        status: JudgeStatus | None = None,
        mode: str = "run",
    ) -> "TraceBuilder":
        total = self.total if total is None else total
        if status is None:
            status = (
                JudgeStatus.ACCEPTED if passed == total else JudgeStatus.WRONG_ANSWER
            )
        session = self.db.get(Session, self.session_id)
        assert session is not None
        trace_service.record_judge_result(
            self.db,
            session,
            mode=mode,
            status=status.value,
            passed=passed,
            total=total,
            runtime_ms=20,
            now=self.t,
        )
        return self

    def submit(self, passed: int, total: int | None = None) -> "TraceBuilder":
        return self.run(passed, total, mode="submit")

    def error(
        self, status: JudgeStatus = JudgeStatus.SYNTAX_ERROR, total: int | None = None
    ) -> "TraceBuilder":
        return self.run(0, total, status=status)

    def _simple(self, event_type: EventType, payload: dict | None = None) -> "TraceBuilder":
        trace_service.append_event(
            self.db,
            session_id=self.session_id,
            type=event_type,
            source=EventSource.CLIENT,
            payload=payload or {},
            at=self.t,
        )
        self.db.commit()
        return self

    def hint(self) -> "TraceBuilder":
        return self._simple(EventType.HINT_REQUEST)

    def undo(self) -> "TraceBuilder":
        return self._simple(EventType.UNDO)

    def reset(self) -> "TraceBuilder":
        return self._simple(EventType.RESET)

    def activity_response(self, result: str = "CORRECT") -> "TraceBuilder":
        return self._simple(EventType.ACTIVITY_RESPONSE, {"result": result})

    def trigger(self, trigger: TriggerType = TriggerType.REPEATED_FAILURE) -> "TraceBuilder":
        """AGENT_TRIGGER를 직접 넣는다 (cooldown 테스트용)."""
        trace_service.append_event(
            self.db,
            session_id=self.session_id,
            type=EventType.AGENT_TRIGGER,
            source=EventSource.SERVER,
            payload={"trigger": trigger.value, "status": "STUCK", "evidence": []},
            at=self.t,
        )
        self.db.commit()
        return self

    # ---------------------------------------------------------------- 조회

    @property
    def session(self) -> Session:
        s = self.db.get(Session, self.session_id)
        assert s is not None
        return s
