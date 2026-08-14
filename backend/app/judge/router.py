"""서버 사이드 실행 엔드포인트.

**오늘은 503을 반환한다.** 그래도 지금 존재해야 한다: 최종 request/response 모양을 갖춘 채
OpenAPI 스키마에 올라가 있으므로 프론트가 오늘 코드를 짜고 404가 아닌 타입 있는 503을 받는다.
JUDGE_BACKEND=docker를 켜면 양쪽 다 코드 수정 없이 켜진다. 그게 seam이다.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, status
from sqlmodel import Session as DbSession

from app.agent import AgentProtocol, get_agent
from app.agent.context import build_context
from app.clock import utcnow
from app.config import get_settings
from app.enums import AgentAction, EventSource
from app.errors import InvalidCodeVersion, SnapshotNotFound
from app.judge import JudgeMode, JudgeProtocol, get_judge
from app.auth.deps import get_current_user
from app.db import get_db
from app.models import User
from app.educator import service as educator_service
from app.progress import service as progress_service
from app.problems.service import ProblemRepository, get_problem_repository
from app.sessions import store
from app.trace import monitor
from app.trace import service as trace_service
from app.trace.router import _state_response
from app.trace.schemas import (
    AgentDecisionRead,
    EventRead,
    ResultIngestResponse,
    RunRequest,
)

log = logging.getLogger(__name__)
router = APIRouter(tags=["judge"])


def _execute(
    session_id: str,
    body: RunRequest,
    mode: JudgeMode,
    user: User,
    db: DbSession,
    repo: ProblemRepository,
    judge: JudgeProtocol,
    agent: AgentProtocol,
) -> ResultIngestResponse:
    session = store.require_session(db, session_id, user_id=user.id)
    problem = repo.get(session.problem_id)
    now = utcnow()

    if body.code is not None:
        snapshot, _ = trace_service.create_snapshot(
            db, session_id=session_id, code=body.code, at=now
        )
        db.commit()
        db.refresh(session)
    elif body.code_version is not None:
        if body.code_version > session.last_code_version:
            raise InvalidCodeVersion(body.code_version, session.last_code_version)
        found = store.snapshot_at(db, session_id, body.code_version)
        if found is None:
            raise SnapshotNotFound(session_id, body.code_version)
        snapshot = found
    else:
        found = store.latest_snapshot(db, session_id)
        if found is None:
            raise SnapshotNotFound(session_id, 0)
        snapshot = found

    # judge가 없으면 여기서 JudgeUnavailable(503)이 난다.
    result = judge.judge(code=snapshot.code, problem=problem, mode=mode)

    # 클라이언트 경로(POST /results)와 **같은 함수**를 쓴다.
    # source와 payload.judge만 달라지고 행 모양은 바이트 동일하다.
    event = trace_service.record_judge_result(
        db,
        session,
        mode=mode,
        status=result.status.value,
        passed=result.passed,
        total=result.total,
        runtime_ms=result.runtime_ms,
        message=result.message,
        failed_categories=result.failed_categories,
        code_version=snapshot.version,
        produced_by=EventSource.SERVER,
        judge_name=judge.name,
        now=now,
    )

    # 진행 상태 갱신 + 최초 정답 시 도토리 지급.
    # **여기가 유일한 지급 지점이다.** 이 경로의 result 는 서버가 실행한 judge 에서
    # 왔으므로 클라이언트가 조작할 수 없다.
    course_ids = educator_service.course_ids_assigned(db, user.id, problem.problem_id, repo)
    progress_service.record_judge_result(
        db,
        user_id=user.id,
        problem=problem,
        status=result.status,
        passed=result.passed,
        total=result.total,
        code=snapshot.code,
        mode=mode,
        course_ids=course_ids,
    )
    # 교육자 대시보드가 읽는 요약을 갱신한다. 실패해도 채점은 반환된다.
    educator_service.recalculate_for_student(db, student=user, problem_id=problem.problem_id, repo=repo)
    db.commit()

    # cfg를 반드시 넘긴다. 생략하면 monitor가 DEFAULT_MONITOR_CONFIG(코드에 박힌
    # 기본값)로 떨어져서 MONITOR_* 환경변수가 통째로 무시된다 -- config.py의
    # Settings.monitor는 값으로 주입받으라고 만든 것이다.
    state = monitor.evaluate_and_record(db, session, now=now, cfg=get_settings().monitor)

    decision: AgentDecisionRead | None = None
    if state.triggered:
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
            # WAIT는 "안 함"이라 남길 이벤트가 없다. 실제 개입만 AGENT_INTERVENTION으로
            # 남겨서 (1) 프론트가 GET /events 폴링으로 힌트를 받을 수 있게 하고
            # (2) build_context()의 previous_interventions가 다음 판단에 참고할 수 있게 한다.
            # 여기서 실패해도 이미 만든 decision은 그대로 반환한다 -- 기록 실패가
            # 학생이 받는 힌트를 막으면 안 된다.
            if d.action is not AgentAction.WAIT:
                try:
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
                    log.exception("agent intervention 기록 실패 (session=%s)", session_id)
        except Exception:  # noqa: BLE001
            log.exception("agent decide 실패 (session=%s)", session_id)

    return ResultIngestResponse(
        event=EventRead.from_row(event),
        process_state=_state_response(session_id, state),
        agent_decision=decision,
    )


@router.post(
    "/sessions/{session_id}/run",
    response_model=ResultIngestResponse,
    status_code=status.HTTP_201_CREATED,
    responses={503: {"description": "JUDGE_UNAVAILABLE — 서버 judge 미구성"}},
)
def run(
    session_id: str,
    body: RunRequest,
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
    repo: ProblemRepository = Depends(get_problem_repository),
    judge: JudgeProtocol = Depends(get_judge),
    agent: AgentProtocol = Depends(get_agent),
) -> ResultIngestResponse:
    return _execute(session_id, body, "run", user, db, repo, judge, agent)


@router.post(
    "/sessions/{session_id}/submit",
    response_model=ResultIngestResponse,
    status_code=status.HTTP_201_CREATED,
    responses={503: {"description": "JUDGE_UNAVAILABLE — 서버 judge 미구성"}},
)
def submit(
    session_id: str,
    body: RunRequest,
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
    repo: ProblemRepository = Depends(get_problem_repository),
    judge: JudgeProtocol = Depends(get_judge),
    agent: AgentProtocol = Depends(get_agent),
) -> ResultIngestResponse:
    return _execute(session_id, body, "submit", user, db, repo, judge, agent)
