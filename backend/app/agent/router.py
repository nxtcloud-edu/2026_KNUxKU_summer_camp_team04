from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session as DbSession

from app.agent import AgentProtocol, get_agent
from app.agent.context import build_context
from app.auth.deps import get_current_user
from app.db import get_db
from app.enums import TriggerType
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
    """학생이 SOS로 직접 도움을 요청했을 때 backend가 부르는 단일 진입점.

    `agent`가 `TutorAgentAdapter`/`HttpAgentClient`로 배선돼 있으면 진짜 LLM
    결정이 나온다 (기본 `WaitAgent`일 때만 오늘도 항상 WAIT다).
    """
    # **소유권을 반드시 본다.** build_context() 가 학생의 현재 코드와 trace 를
    # 통째로 담아 오므로, 이걸 빼먹으면 session_id 만 알면 남의 학습 내용을
    # 그대로 읽을 수 있다. 다른 세션 라우트는 전부 이 검사를 한다.
    store.require_session(db, body.session_id, user_id=user.id)
    ctx = build_context(db, body.session_id, repo)

    if body.trigger == TriggerType.HELP_REQUESTED.value:
        # **`body.trigger`를 실제로 쓰는 유일한 곳.** 이전에는 이 필드를 받기만
        # 하고 버렸다 -- ctx는 build_context() 안의 evaluate()가 계산한
        # Monitor의 *자체* 판정(R0~R9)만 반영했다.
        #
        # 이게 SOS를 조용히 무력화시킨다: Monitor의 R0(HELP_REQUESTED)는 서버에
        # 이미 커밋된 HINT_REQUEST 이벤트를 봐야 발화하는데, 프런트
        # (AiTutorPanel.confirmSos)는 그 이벤트를 큐에 넣기만 하고 flush를
        # 기다리지 않은 채 바로 이 엔드포인트를 부른다(useCodingTrace의 배치
        # 전송 주기 참고). 그러면 evaluate()는 방금 "직접 요청했다"는 사실을
        # 전혀 못 본 채 신호 없는 세션으로 판단하고, state_agent는 그 신호
        # 부족을 근거로 LLM에게 물어 **WAIT을 돌려받을 수 있다** -- 그 순간
        # 학생 눈에는 SOS 버튼을 눌러도 아무 반응이 없는 것으로 보인다.
        #
        # 그래서 요청 자체를 신호로 덮어써 Monitor의 이벤트 타이밍과 무관하게
        # 만든다. Monitor의 R0가 실제로 만들어냈을 값과 같은 값(trigger/
        # process_status = "HELP_REQUESTED")을 그대로 써서, 하류
        # (`backend_adapter._is_explicit_help_request`)가 두 경로를 구분할
        # 필요가 없게 한다.
        ctx = replace(
            ctx,
            trigger=TriggerType.HELP_REQUESTED.value,
            process_status=TriggerType.HELP_REQUESTED.value,
        )

    d = agent.decide(ctx)
    return AgentDecisionRead(
        state=d.state,
        concept=d.concept,
        action=d.action.value,
        reason=d.reason,
        activity=d.activity,
    )
