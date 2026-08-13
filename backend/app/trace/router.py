from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, status
from sqlmodel import Session as DbSession

from app.agent import AgentProtocol, get_agent
from app.agent.context import build_context
from app.clock import to_naive_utc, utcnow
from app.db import get_db
from app.enums import SessionStatus
from app.errors import SnapshotNotFound
from app.problems.service import ProblemRepository, get_problem_repository
from app.sessions import store
from app.trace import monitor
from app.trace import service as trace_service
from app.trace.diff import compute_diff
from app.trace.schemas import (
    AgentDecisionRead,
    DiffRead,
    EventBatchIn,
    EventIngestResponse,
    EventListResponse,
    EventRead,
    JudgeResultIn,
    JudgeResultRead,
    ProcessFeaturesRead,
    ProcessStateResponse,
    ResultIngestResponse,
    SnapshotRead,
    SnapshotSummary,
    TimelineResponse,
)
from app.trace.timeline import build_timeline

log = logging.getLogger(__name__)
router = APIRouter(tags=["trace"])


def _state_response(session_id: str, state: monitor.ProcessState) -> ProcessStateResponse:
    f = state.features
    last = f.last_result
    return ProcessStateResponse(
        session_id=session_id,
        status=state.status,
        trigger=state.trigger,
        triggered=state.triggered,
        reason=state.reason,
        evidence=state.evidence,
        cooldown_active=state.cooldown_active,
        cooldown_remaining_seconds=state.cooldown_remaining_seconds,
        features=ProcessFeaturesRead(
            elapsed_seconds=f.elapsed_seconds,
            run_count=f.run_count,
            submit_count=f.submit_count,
            attempt_count=f.attempt_count,
            recent_scores=f.recent_scores,
            same_result_count=f.same_result_count,
            progress_delta=f.progress_delta,
            improved_recently=f.improved_recently,
            seconds_without_progress=f.seconds_without_progress,
            same_region_edit_count=f.same_region_edit_count,
            repeated_edit_region=f.repeated_edit_region,
            edits_since_progress=f.edits_since_progress,
            undo_count=f.undo_count,
            hint_count=f.hint_count,
            large_change_detected=f.large_change_detected,
            recent_error_types=f.recent_error_types,
            consecutive_error_count=f.consecutive_error_count,
            snapshot_count=f.snapshot_count,
            last_result=None
            if last is None
            else JudgeResultRead(
                mode=last.mode,
                status=last.status,
                passed=last.passed,
                total=last.total,
            ),
        ),
        evaluated_at=state.evaluated_at,
    )


# ------------------------------------------------------------------ 이벤트


@router.post(
    "/sessions/{session_id}/events",
    response_model=EventIngestResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_events(
    session_id: str,
    body: EventBatchIn,
    db: DbSession = Depends(get_db),
) -> EventIngestResponse:
    session = store.require_session(db, session_id)
    accepted, duplicates = trace_service.ingest_events(db, session, body.events)
    return EventIngestResponse(
        accepted=[EventRead.from_row(e) for e in accepted],
        duplicate_client_event_ids=duplicates,
        current_code_version=session.last_code_version,
        last_event_seq=session.last_event_seq,
        # FINISHED 세션의 이벤트도 **수락**한다 (409 아님).
        # 현실적인 원인은 /finish 직후 프론트가 큐를 flush하는 것뿐인데,
        # 아무도 안 볼 데이터 위생과 맞바꿔 무대에 빨간 배너를 띄울 이유가 없다.
        session_finished=SessionStatus(session.status) is SessionStatus.FINISHED,
    )


@router.get("/sessions/{session_id}/events", response_model=EventListResponse)
def get_events(
    session_id: str,
    since_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
    db: DbSession = Depends(get_db),
) -> EventListResponse:
    session = store.require_session(db, session_id)
    rows = trace_service.events_since(db, session_id, since_seq=since_seq, limit=limit)
    return EventListResponse(
        session_id=session_id,
        events=[EventRead.from_row(e) for e in rows],
        last_event_seq=session.last_event_seq,
        has_more=bool(rows) and rows[-1].seq < session.last_event_seq,
    )


# ------------------------------------------------------------------ Judge 결과


@router.post(
    "/sessions/{session_id}/results",
    response_model=ResultIngestResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_result(
    session_id: str,
    body: JudgeResultIn,
    db: DbSession = Depends(get_db),
    repo: ProblemRepository = Depends(get_problem_repository),
    agent: AgentProtocol = Depends(get_agent),
) -> ResultIngestResponse:
    """브라우저 Pyodide 채점 결과를 받는 입구. **파이프라인의 척추다.**

        TEST_RESULT 기록 -> feature 재계산 -> monitor.evaluate_and_record()
          -> (trigger 있으면) AGENT_TRIGGER 기록 -> agent.decide() -> 응답

    backend_plan §20 계약에는 없던 엔드포인트다. 오늘 Pyodide가 클라이언트에서 채점하므로
    결과가 들어올 입구가 필요하다. 서버 judge가 붙으면 POST /run이 같은 내부 함수를 쓴다.
    """
    session = store.require_session(db, session_id)
    now = utcnow()

    event = trace_service.record_judge_result(
        db,
        session,
        mode=body.mode,
        status=body.status.value,
        passed=body.passed,
        total=body.total,
        runtime_ms=body.runtime_ms,
        message=body.message,
        failed_categories=body.failed_categories,
        code_version=body.code_version,
        client_event_id=body.client_event_id,
        client_timestamp=to_naive_utc(body.client_timestamp),
        now=now,
    )

    state = monitor.evaluate_and_record(db, session, now=now)

    decision: AgentDecisionRead | None = None
    if state.triggered:
        # backend_plan §14: Judge 결과는 Agent 실패와 무관하게 반드시 반환한다.
        try:
            ctx = build_context(db, session_id, repo, state=state, now=now)
            d = agent.decide(ctx)
            decision = AgentDecisionRead(
                state=d.state,
                concept=d.concept,
                action=d.action.value,
                reason=d.reason,
                activity=d.activity,
            )
        except Exception:  # noqa: BLE001 - agent 실패가 채점 결과를 막으면 안 된다
            log.exception("agent decide 실패 (session=%s)", session_id)
            decision = None

    return ResultIngestResponse(
        event=EventRead.from_row(event),
        process_state=_state_response(session_id, state),
        agent_decision=decision,
    )


# ------------------------------------------------------------------ Process State


@router.get("/sessions/{session_id}/process-state", response_model=ProcessStateResponse)
def get_process_state(
    session_id: str, db: DbSession = Depends(get_db)
) -> ProcessStateResponse:
    """읽기 전용. evaluate()만 부르고 evaluate_and_record()는 절대 부르지 않는다.

    데모 패널이 이걸 폴링한다. GET이 AGENT_TRIGGER를 쓰면 cooldown을 소진해
    정작 agent를 불러야 할 Run이 cooldown에 걸린다 (monitor.py 상단 참조).
    """
    return _state_response(session_id, monitor.evaluate(db, session_id))


# ------------------------------------------------------------------ Timeline


@router.get("/sessions/{session_id}/timeline", response_model=TimelineResponse)
def get_timeline(
    session_id: str,
    collapse: bool = Query(default=True),
    db: DbSession = Depends(get_db),
) -> TimelineResponse:
    session = store.require_session(db, session_id)
    events = trace_service.all_events(db, session_id)
    return build_timeline(session, events, collapse=collapse)


# ------------------------------------------------------------------ Snapshot / Replay


def _snapshot_summary(s) -> SnapshotSummary:  # type: ignore[no-untyped-def]
    return SnapshotSummary(
        version=s.version,
        created_at=s.created_at,
        parent_version=s.parent_version,
        change_size=s.change_size,
        change_ratio=s.change_ratio,
        changed_lines=s.changed_lines or [],
        region_tags=s.region_tags or [],
        primary_region=s.primary_region,
        summary=s.summary,
        seconds_since_parent=s.seconds_since_parent,
    )


@router.get("/sessions/{session_id}/snapshots", response_model=list[SnapshotSummary])
def list_snapshots(
    session_id: str, db: DbSession = Depends(get_db)
) -> list[SnapshotSummary]:
    store.require_session(db, session_id)
    # code는 뺀다 -- 목록이 커지면 안 된다.
    return [_snapshot_summary(s) for s in store.all_snapshots(db, session_id)]


@router.get(
    "/sessions/{session_id}/snapshots/{version}", response_model=SnapshotRead
)
def get_snapshot(
    session_id: str, version: int, db: DbSession = Depends(get_db)
) -> SnapshotRead:
    store.require_session(db, session_id)
    s = store.snapshot_at(db, session_id, version)
    if s is None:
        raise SnapshotNotFound(session_id, version)
    return SnapshotRead(
        session_id=session_id, code=s.code, **_snapshot_summary(s).model_dump()
    )


@router.get(
    "/sessions/{session_id}/snapshots/{version}/diff", response_model=DiffRead
)
def get_snapshot_diff(
    session_id: str,
    version: int,
    from_version: int | None = Query(default=None, alias="from"),
    db: DbSession = Depends(get_db),
) -> DiffRead:
    store.require_session(db, session_id)
    target = store.snapshot_at(db, session_id, version)
    if target is None:
        raise SnapshotNotFound(session_id, version)

    # 직전 버전과의 diff는 저장된 컬럼을 그대로 쓴다 (재계산 0). 그게 흔한 경우다.
    if from_version is None or from_version == target.parent_version:
        base = (
            store.snapshot_at(db, session_id, target.parent_version)
            if target.parent_version
            else None
        )
        d = compute_diff(
            base.code if base else None,
            target.code,
            from_version=target.parent_version,
            to_version=version,
        )
        return DiffRead(session_id=session_id, **_diff_fields(d))

    base = store.snapshot_at(db, session_id, from_version)
    if base is None:
        raise SnapshotNotFound(session_id, from_version)
    d = compute_diff(
        base.code, target.code, from_version=from_version, to_version=version
    )
    return DiffRead(session_id=session_id, **_diff_fields(d))


def _diff_fields(d) -> dict:  # type: ignore[no-untyped-def]
    return {
        "from_version": d.from_version,
        "to_version": d.to_version,
        "changed_lines": d.changed_lines,
        "deleted_lines": d.deleted_lines,
        "added_line_count": d.added_line_count,
        "deleted_line_count": d.deleted_line_count,
        "change_size": d.change_size,
        "change_ratio": d.change_ratio,
        "region_tags": d.region_tags,
        "primary_region": d.primary_region,
        "summary": d.summary,
        "unified_diff": d.unified_diff,
    }
