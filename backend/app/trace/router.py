from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy.engine import Engine
from sqlmodel import Session as DbSession

from app.agent import AgentProtocol, get_agent
from app.agent.context import build_context
from app.clock import to_naive_utc, utcnow
from app.config import get_settings
from app.auth.deps import get_current_user
from app.db import get_db, get_engine
from app.enums import AgentAction, SessionStatus
from app.models import User
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
            seconds_since_last_edit=f.seconds_since_last_edit,
            edits_since_last_trigger=f.edits_since_last_trigger,
            edits_since_last_result=f.edits_since_last_result,
            large_change_unverified=f.large_change_unverified,
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
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
) -> EventIngestResponse:
    session = store.require_session(db, session_id, user_id=user.id)
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


@router.post(
    "/sessions/{session_id}/heartbeat",
    response_model=ProcessStateResponse,
)
def heartbeat(
    session_id: str,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
    repo: ProblemRepository = Depends(get_problem_repository),
    agent: AgentProtocol = Depends(get_agent),
    engine: Engine = Depends(get_engine),
) -> ProcessStateResponse:
    """실시간 유휴 감지용 하트비트. 프론트가 활동 여부와 무관하게 몇 초마다 부른다.

    **왜 필요한가.** `POST /events`는 보낼 이벤트가 없으면 프론트가 아예 안 부른다
    (`traceClient.postEvents`가 빈 배치를 걸러낸다). 그래서 학생이 코드를 안 만지고
    가만히 있는 바로 그 상황(유휴 90초 = R7 NO_PROGRESS)에서는 Monitor가 재평가될
    계기 자체가 없었다 -- 다음 제출 때가 돼서야 "그동안 90초 지났네"를 계산했다.
    이 엔드포인트가 그 계기를 만든다.

    **`GET /process-state`와 다른 점.** 그건 읽기 전용(`evaluate()`만, cooldown을
    안 쓴다 -- monitor.py 상단 docstring 참고)이라 데모 패널이 자유롭게 폴링해도
    안전하지만, 트리거돼도 agent를 부르지 않는다. 이 엔드포인트는 POST라 실제로
    기록하고(`evaluate_and_record()`, AGENT_TRIGGER 이벤트 + cooldown 갱신) 트리거되면
    agent도 부른다 -- 그래서 하트비트 간격은 cooldown보다 촘촘하면 안 된다(같은
    트리거를 두 번 소진하지 않게).

    **agent 호출은 응답에 안 실린다.** `agent.decide()`가 최대 16~18초 걸리는데
    (agent/README.md "지연 시간" 참고), 몇 초마다 오는 하트비트를 그만큼씩 막으면
    하트비트가 무의미해진다. 트리거되면 `background_tasks`로 넘기고 즉시 응답한다.
    결과는 WAIT가 아닐 때만 `AGENT_INTERVENTION` 이벤트로 남으므로, 프론트는
    `GET /sessions/{id}/events?since_seq=...`를 폴링해서 새 이벤트로 힌트를 받는다.
    """
    session = store.require_session(db, session_id, user_id=user.id)
    now = utcnow()
    # cfg를 반드시 넘긴다 (judge/router.py의 같은 호출 참고). 생략하면
    # MONITOR_NO_PROGRESS_SECONDS 같은 환경변수가 조용히 무시된다.
    state = monitor.evaluate_and_record(db, session, now=now, cfg=get_settings().monitor)
    db.commit()

    if state.triggered:
        background_tasks.add_task(
            _run_agent_in_background, session_id, repo, agent, state, now, engine
        )

    return _state_response(session_id, state)


def _run_agent_in_background(
    session_id: str,
    repo: ProblemRepository,
    agent: AgentProtocol,
    state: monitor.ProcessState,
    now: datetime,
    engine: Engine,
) -> None:
    """하트비트가 트리거를 감지했을 때 agent를 부르고, WAIT가 아니면 기록한다.

    응답이 이미 나간 뒤 실행되므로 여기서 얼마나 걸리든(agent 서비스가 LLM
    파이프라인을 도는 중이라도) 학생은 기다리지 않는다.

    **새 DB 세션을 직접 연다.** `Depends(get_db)`로 받은 요청 스코프 세션은
    응답이 나가면 닫혀서(`app/db.py::get_db`) 백그라운드에서 재사용할 수 없다.
    `engine`은 (직접 `get_engine()`을 부르지 않고) `Depends(get_engine)`으로
    받는다 -- 테스트가 `app.dependency_overrides[get_db]`로 인메모리 DB를
    꽂아도, 이 함수가 `get_engine()`을 직접 호출하면 그 override를 못 보고
    **실제 DB 파일**에 접근해버린다 (`app.dependency_overrides`는 FastAPI의
    `Depends` 해석에만 적용되고, 일반 함수 호출은 안 거친다). `engine`도
    같은 방식으로 주입받으면 테스트에서 `get_engine`까지 override해서 완전히
    격리할 수 있다. `repo`/`agent`는 상태가 없거나(파일 읽기, httpx 연결 풀)
    재사용이 안전해서 그대로 넘겨 받는다.
    """
    try:
        with DbSession(engine) as db:
            ctx = build_context(db, session_id, repo, state=state, now=now)
            d = agent.decide(ctx)
            if d.action is not AgentAction.WAIT:
                trace_service.record_agent_intervention(
                    db,
                    session_id,
                    state=d.state,
                    concept=d.concept,
                    action=d.action.value,
                    reason=d.reason,
                    activity=d.activity,
                    trigger=state.trigger.value if state.trigger else None,
                    now=now,
                )
    except Exception:  # noqa: BLE001
        log.exception("하트비트 백그라운드 agent 처리 실패 (session=%s)", session_id)


@router.get("/sessions/{session_id}/events", response_model=EventListResponse)
def get_events(
    session_id: str,
    since_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
) -> EventListResponse:
    session = store.require_session(db, session_id, user_id=user.id)
    rows = trace_service.events_since(db, session_id, since_seq=since_seq, limit=limit)
    return EventListResponse(
        session_id=session_id,
        events=[EventRead.from_row(e) for e in rows],
        last_event_seq=session.last_event_seq,
        has_more=bool(rows) and rows[-1].seq < session.last_event_seq,
    )


# ------------------------------------------------------------------ Judge 결과
#
# POST /sessions/{id}/results 는 **제거됐다.**
#
# 클라이언트가 보고한 채점 결과를 그대로 기록하던 엔드포인트다. Pyodide가
# 브라우저에서 채점하던 시절의 입구였는데, 지금은 두 가지가 바뀌었다.
#
#   1. 프런트가 더 이상 쓰지 않는다. 채점은 POST /sessions/{id}/run|submit 로
#      가고 서버가 Docker judge 를 직접 돌린다.
#   2. 도토리가 정답 기준으로 지급된다. 클라이언트가 status 를 정할 수 있으면
#      curl 한 줄로 {"status":"ACCEPTED"} 를 보내 무한히 획득할 수 있다.
#
# "채점 결과를 프런트가 조작해 도토리를 요청할 수 없도록 서버의 ACCEPTED 결과를
# 기준으로 지급한다"는 요구사항은 **이 입구가 없어야** 성립한다.
# 클라이언트 채점을 다시 도입한다면 보상과 진행 상태 갱신을 반드시 분리할 것.


# ------------------------------------------------------------------ Process State


@router.get("/sessions/{session_id}/process-state", response_model=ProcessStateResponse)
def get_process_state(
    session_id: str,
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
) -> ProcessStateResponse:
    """읽기 전용. evaluate()만 부르고 evaluate_and_record()는 절대 부르지 않는다.

    데모 패널이 이걸 폴링한다. GET이 AGENT_TRIGGER를 쓰면 cooldown을 소진해
    정작 agent를 불러야 할 Run이 cooldown에 걸린다 (monitor.py 상단 참조).
    """
    # monitor.evaluate()가 내부에서 세션을 다시 조회하지만 소유권은 보지 않는다.
    # 여기서 먼저 막지 않으면 남의 session_id로 그 사람의 학습 상태(막힘 여부,
    # 근거 문자열, feature 전체)를 읽을 수 있다.
    store.require_session(db, session_id, user_id=user.id)
    return _state_response(
        session_id, monitor.evaluate(db, session_id, cfg=get_settings().monitor)
    )


# ------------------------------------------------------------------ Timeline


@router.get("/sessions/{session_id}/timeline", response_model=TimelineResponse)
def get_timeline(
    session_id: str,
    collapse: bool = Query(default=True),
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
) -> TimelineResponse:
    session = store.require_session(db, session_id, user_id=user.id)
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
    session_id: str,
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
) -> list[SnapshotSummary]:
    store.require_session(db, session_id, user_id=user.id)
    # code는 뺀다 -- 목록이 커지면 안 된다.
    return [_snapshot_summary(s) for s in store.all_snapshots(db, session_id)]


@router.get(
    "/sessions/{session_id}/snapshots/{version}", response_model=SnapshotRead
)
def get_snapshot(
    session_id: str,
    version: int,
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
) -> SnapshotRead:
    store.require_session(db, session_id, user_id=user.id)
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
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
) -> DiffRead:
    store.require_session(db, session_id, user_id=user.id)
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
