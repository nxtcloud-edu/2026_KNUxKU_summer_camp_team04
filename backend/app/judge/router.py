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
from app.enums import EventSource
from app.errors import InvalidCodeVersion, SnapshotNotFound
from app.judge import JudgeMode, JudgeProtocol, get_judge
from app.db import get_db
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
    db: DbSession,
    repo: ProblemRepository,
    judge: JudgeProtocol,
    agent: AgentProtocol,
) -> ResultIngestResponse:
    session = store.require_session(db, session_id)
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

    state = monitor.evaluate_and_record(db, session, now=now)

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
    db: DbSession = Depends(get_db),
    repo: ProblemRepository = Depends(get_problem_repository),
    judge: JudgeProtocol = Depends(get_judge),
    agent: AgentProtocol = Depends(get_agent),
) -> ResultIngestResponse:
    return _execute(session_id, body, "run", db, repo, judge, agent)


@router.post(
    "/sessions/{session_id}/submit",
    response_model=ResultIngestResponse,
    status_code=status.HTTP_201_CREATED,
    responses={503: {"description": "JUDGE_UNAVAILABLE — 서버 judge 미구성"}},
)
def submit(
    session_id: str,
    body: RunRequest,
    db: DbSession = Depends(get_db),
    repo: ProblemRepository = Depends(get_problem_repository),
    judge: JudgeProtocol = Depends(get_judge),
    agent: AgentProtocol = Depends(get_agent),
) -> ResultIngestResponse:
    return _execute(session_id, body, "submit", db, repo, judge, agent)
