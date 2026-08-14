"""Trace API 스키마. 전부 snake_case."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.enums import (
    ClientEventType,
    EventSource,
    EventType,
    JudgeStatus,
    ProcessStatus,
    SessionStatus,
    TriggerType,
)
from app.models import Event
from app.schemas_common import UtcDatetime

# ---------------------------------------------------------------- 이벤트 수집


class EventIn(BaseModel):
    # type이 ClientEventType이라 {"type": "TEST_RESULT"}는 핸들러 진입 전에 422가 된다.
    # 제약이 OpenAPI에 드러나므로 프론트의 생성 타입은 그걸 표현조차 못 한다.
    type: ClientEventType
    client_timestamp: datetime | None = None
    # 멱등성 키. 프론트는 crypto.randomUUID()로 만들어 **반드시** 보내야 한다.
    # 없으면 dedup이 불가능하고 이 엔드포인트는 best-effort가 된다.
    client_event_id: str | None = Field(default=None, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)


class EventBatchIn(BaseModel):
    """배치 전용. 단건은 1개짜리 배치다.

    EventIn | EventBatchIn union은 더 나쁜 API다: OpenAPI가 모호해지고,
    Pydantic union 에러가 흉하고, 코드 경로가 둘이 된다.
    frontend_plan §7이 어차피 최대 5개 배칭을 원한다.
    """

    events: list[EventIn] = Field(min_length=1, max_length=50)


class EventRead(BaseModel):
    event_id: str
    session_id: str
    seq: int
    type: EventType
    source: EventSource
    code_version: int | None
    payload: dict[str, Any]
    client_timestamp: UtcDatetime | None
    server_timestamp: UtcDatetime

    @classmethod
    def from_row(cls, e: Event) -> "EventRead":
        return cls(
            event_id=e.id,
            session_id=e.session_id,
            seq=e.seq,
            type=EventType(e.type),
            source=EventSource(e.source),
            code_version=e.code_version,
            payload=e.payload or {},
            client_timestamp=e.client_timestamp,
            server_timestamp=e.server_timestamp,
        )


class EventIngestResponse(BaseModel):
    accepted: list[EventRead]
    duplicate_client_event_ids: list[str]
    current_code_version: int
    last_event_seq: int
    session_finished: bool


class EventListResponse(BaseModel):
    session_id: str
    events: list[EventRead]
    last_event_seq: int
    has_more: bool


# ---------------------------------------------------------------- Judge 결과


class JudgeResultIn(BaseModel):
    """브라우저 Pyodide가 보내는 채점 결과 (오늘의 경로).

    인증이 없으므로 악의적 클라이언트가 조작된 5/5를 보낼 수 있다. MVP 범위 밖이고,
    POST /run(서버 judge)이 유일한 결과 경로가 되면 닫힌다.
    값싼 방어(범위 검증)는 지금 넣는다.
    """

    mode: Literal["run", "submit"]
    status: JudgeStatus
    passed: int = Field(ge=0, le=100)
    total: int = Field(ge=0, le=100)
    runtime_ms: int | None = Field(default=None, ge=0)
    message: str | None = Field(default=None, max_length=2000)
    failed_categories: list[str] = Field(default_factory=list)
    code_version: int | None = None
    client_event_id: str | None = Field(default=None, max_length=64)
    client_timestamp: datetime | None = None

    @model_validator(mode="after")
    def _check(self) -> "JudgeResultIn":
        if self.passed > self.total:
            raise ValueError("passed는 total을 넘을 수 없습니다.")
        return self


class JudgeResultRead(BaseModel):
    mode: str
    status: JudgeStatus
    passed: int
    total: int
    runtime_ms: int | None = None


class RunRequest(BaseModel):
    """POST /sessions/{id}/run 요청. 오늘은 503이지만 스키마는 지금 확정한다."""

    code: str | None = None
    code_version: int | None = None


# ---------------------------------------------------------------- Process State


class ProcessFeaturesRead(BaseModel):
    elapsed_seconds: int
    run_count: int
    submit_count: int
    attempt_count: int
    recent_scores: list[int]
    same_result_count: int
    progress_delta: int
    improved_recently: bool
    seconds_without_progress: int
    same_region_edit_count: int
    repeated_edit_region: str | None
    edits_since_progress: int
    undo_count: int
    hint_count: int
    large_change_detected: bool
    recent_error_types: list[str]
    consecutive_error_count: int
    snapshot_count: int
    # 편집만으로 발화하는 규칙(monitor R7b/R7c)이 읽는 값. 데모의 Process State
    # 패널이 "왜 지금 불렸는지"를 설명하려면 이 둘도 보여야 한다.
    seconds_since_last_edit: int = 0
    edits_since_last_trigger: int = 0
    # R7d(완전 무활동)가 읽는 값. 편집 시계와 별개다 -- Process State 패널이
    # "실행만 하다 멈춘" 경우와 "편집하다 멈춘" 경우를 구분해 보여줄 수 있어야 한다.
    seconds_since_last_activity: int = 0
    activity_since_last_trigger: int = 0
    edits_since_last_result: int = 0
    large_change_unverified: bool = False
    last_result: JudgeResultRead | None


class ProcessStateResponse(BaseModel):
    session_id: str
    status: ProcessStatus
    trigger: TriggerType | None
    triggered: bool
    reason: str
    evidence: list[str]
    cooldown_active: bool
    cooldown_remaining_seconds: int
    features: ProcessFeaturesRead
    evaluated_at: UtcDatetime


class AgentDecisionRead(BaseModel):
    state: str
    concept: str | None
    action: str
    reason: str
    activity: dict[str, Any] | None = None


class AgentReplyRead(BaseModel):
    """`POST /agent/respond` 응답 -- 학생이 보낸 말에 대한 튜터의 답장.

    **일부러 좁다.** agent 쪽 `AgentReply`에는 학생 답변 평가 결과
    (understanding, misconceptions, evidence, next_focus)가 같이 들어 있지만,
    그건 내부 판단이라 학생 브라우저로 내려보내지 않는다 -- 교육자 화면은
    trace 이벤트에서 읽고, 학생에게 "이해도: none"을 보여줄 이유는 없다.

    `expects_reply`가 true면 프런트엔드가 입력창을 열어 둔 채로 답을 기다린다.
    """

    message: str
    expects_reply: bool = False
    question: str = ""


class ResultIngestResponse(BaseModel):
    event: EventRead
    process_state: ProcessStateResponse
    agent_decision: AgentDecisionRead | None = None
    awarded_acorns: int = 0


# ---------------------------------------------------------------- Timeline

TimelineKind = Literal[
    "START", "EDIT", "RUN", "SUBMIT", "ERROR", "HINT", "UNDO", "RESET",
    "AGENT", "ACTIVITY", "END",
]


class TimelineEntry(BaseModel):
    seq: int
    at: UtcDatetime
    kind: TimelineKind
    label: str
    event_type: EventType
    code_version: int | None
    detail: dict[str, Any] = Field(default_factory=dict)


class TimelineSummary(BaseModel):
    edit_count: int
    run_count: int
    submit_count: int
    trigger_count: int
    best_passed: int | None
    total_seconds: int


class TimelineResponse(BaseModel):
    session_id: str
    problem_id: str
    status: SessionStatus
    entries: list[TimelineEntry]
    summary: TimelineSummary


# ---------------------------------------------------------------- Snapshot


class SnapshotSummary(BaseModel):
    version: int
    created_at: UtcDatetime
    parent_version: int | None
    change_size: int
    change_ratio: float
    changed_lines: list[int]
    region_tags: list[str]
    primary_region: str
    summary: str
    seconds_since_parent: int


class SnapshotRead(SnapshotSummary):
    session_id: str
    code: str


class DiffRead(BaseModel):
    session_id: str
    from_version: int | None
    to_version: int
    changed_lines: list[int]
    deleted_lines: list[int]
    added_line_count: int
    deleted_line_count: int
    change_size: int
    change_ratio: float
    region_tags: list[str]
    primary_region: str
    summary: str
    unified_diff: str
