from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session as DbSession

from app.agent import AgentProtocol, get_agent
from app.agent.context import build_context
from app.db import get_db
from app.problems.service import ProblemRepository, get_problem_repository
from app.trace.schemas import AgentDecisionRead

router = APIRouter(tags=["agent"])


class AgentDecideRequest(BaseModel):
    session_id: str
    trigger: str | None = None


@router.post("/agent/decide", response_model=AgentDecisionRead)
def decide(
    body: AgentDecideRequest,
    db: DbSession = Depends(get_db),
    repo: ProblemRepository = Depends(get_problem_repository),
    agent: AgentProtocol = Depends(get_agent),
) -> AgentDecisionRead:
    """오늘은 항상 action=WAIT을 반환한다 (WaitAgent).

    context builder는 실제로 동작하므로, 이 응답이 WAIT이어도
    build_context()가 trace에서 뽑아낸 실제 데이터를 기반으로 만들어진 결정이다.
    AGENT_BACKEND=llm이 붙으면 같은 context가 LLM에 들어간다.
    """
    ctx = build_context(db, body.session_id, repo)
    d = agent.decide(ctx)
    return AgentDecisionRead(
        state=d.state,
        concept=d.concept,
        action=d.action.value,
        reason=d.reason,
        activity=d.activity,
    )
