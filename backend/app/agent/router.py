from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session as DbSession

from app.agent import AgentProtocol, get_agent
from app.agent.context import build_context
from app.auth.deps import get_current_user
from app.db import get_db
from app.models import User
from app.sessions import store
from app.problems.service import ProblemRepository, get_problem_repository
from app.trace.schemas import AgentDecisionRead

router = APIRouter(tags=["agent"])


class AgentDecideRequest(BaseModel):
    session_id: str
    trigger: str | None = None


@router.post("/agent/decide", response_model=AgentDecisionRead)
def decide(
    body: AgentDecideRequest,
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
    repo: ProblemRepository = Depends(get_problem_repository),
    agent: AgentProtocol = Depends(get_agent),
) -> AgentDecisionRead:
    """오늘은 항상 action=WAIT을 반환한다 (WaitAgent).

    context builder는 실제로 동작하므로, 이 응답이 WAIT이어도
    build_context()가 trace에서 뽑아낸 실제 데이터를 기반으로 만들어진 결정이다.
    AGENT_BACKEND=llm이 붙으면 같은 context가 LLM에 들어간다.
    """
    # **소유권을 반드시 본다.** build_context() 가 학생의 현재 코드와 trace 를
    # 통째로 담아 오므로, 이걸 빼먹으면 session_id 만 알면 남의 학습 내용을
    # 그대로 읽을 수 있다. 다른 세션 라우트는 전부 이 검사를 한다.
    store.require_session(db, body.session_id, user_id=user.id)
    ctx = build_context(db, body.session_id, repo)
    d = agent.decide(ctx)
    return AgentDecisionRead(
        state=d.state,
        concept=d.concept,
        action=d.action.value,
        reason=d.reason,
        activity=d.activity,
    )
