from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlmodel import Session as DbSession

from app.agent import AgentProtocol, get_agent
from app.agent.context import build_context, last_tutor_question
from app.agent.stub import AGENT_UNAVAILABLE_REPLY
from app.auth.deps import get_current_user
from app.db import get_db
from app.enums import AgentAction
from app.models import User
from app.sessions import store
from app.problems.service import ProblemRepository, get_problem_repository
from app.trace import service as trace_service
from app.trace.schemas import AgentDecisionRead, AgentReplyRead

log = logging.getLogger(__name__)

router = APIRouter(tags=["agent"])

#: 학생이 한 번에 보낼 수 있는 답변 길이 상한. 프롬프트에 그대로 실려 나가므로
#: 상한이 없으면 토큰 비용을 클라이언트가 정하게 된다.
MAX_ANSWER_CHARS = 2000


class AgentDecideRequest(BaseModel):
    session_id: str
    trigger: str | None = None


class AgentRespondRequest(BaseModel):
    """학생이 튜터에게 보낸 말.

    **튜터가 무엇을 물었는지는 받지 않는다.** 서버가
    `last_tutor_question()`으로 자기 개입 기록에서 직접 찾는다 (이유는 그 함수
    docstring 참고).
    """

    session_id: str
    answer: str = Field(min_length=1, max_length=MAX_ANSWER_CHARS)


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


@router.post("/agent/respond", response_model=AgentReplyRead)
def respond(
    body: AgentRespondRequest,
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
    repo: ProblemRepository = Depends(get_problem_repository),
    agent: AgentProtocol = Depends(get_agent),
) -> AgentReplyRead:
    """학생이 튜터에게 답변/질문을 보냈을 때 부른다.

    `POST /agent/decide`는 "튜터가 먼저 말을 걸까?"를 묻는 경로이고, 이쪽은
    학생이 이미 말을 건 뒤다. 그래서 개입 여부를 판단하지 않고 곧장
    학생 답변 평가 → 응답 생성으로 간다 (agent `orchestrator.respond_to_student`).

    **응답 본문에는 `message`/`expects_reply`/`question`만 담는다.** 평가
    결과(understanding, misconceptions, evidence)는 내부 판단이라 학생
    브라우저로 보내지 않고 trace에만 남긴다 -- 교육자 화면이 읽을 곳은
    거기이고, 학생에게 "이해도: none"을 보여줄 이유는 없다.
    """
    # 소유권 검사. build_context()가 학생의 코드와 trace를 통째로 담아 오므로
    # 빼먹으면 session_id만 알면 남의 학습 내용을 읽을 수 있다.
    store.require_session(db, body.session_id, user_id=user.id)

    answer = body.answer.strip()
    if not answer:
        return AgentReplyRead(message="어떤 부분이 어려운지 한 줄만 적어줄래요?")

    ctx = build_context(db, body.session_id, repo)
    question = last_tutor_question(db, body.session_id)

    respond_fn = getattr(agent, "respond", None)
    if respond_fn is None:
        # `AgentProtocol`에 respond가 있지만, 오래된 구현체가 꽂혀 있을 수 있다.
        # 그 경우 500을 내지 말고 말은 걸어준다.
        log.warning("agent %r에 respond()가 없습니다. 폴백 문구로 응답합니다.", agent.name)
        return AgentReplyRead(message=AGENT_UNAVAILABLE_REPLY)

    try:
        reply = respond_fn(ctx, answer=answer, question=question)
    except Exception:
        # agent 구현체는 예외를 던지지 않기로 약속했지만(interface.respond),
        # 그 약속이 깨져도 학생 화면이 500을 받아선 안 된다.
        log.exception("agent.respond() 실패. 폴백 문구로 응답합니다.")
        return AgentReplyRead(message=AGENT_UNAVAILABLE_REPLY)

    message = str(getattr(reply, "message", "") or "").strip() or AGENT_UNAVAILABLE_REPLY

    # 이 대화를 개입 기록으로 남긴다. 새 EventType을 만들지 않는 이유:
    #   * 튜터의 답장은 실제로 개입이다 -- 타임라인의 AGENT 항목으로 그대로 읽힌다.
    #   * `build_context()`의 `previous_interventions`가 이걸 주워가므로, 다음
    #     차례에 agent가 "내가 방금 뭐라고 했는지"를 안다.
    #   * HINT_REQUEST로 남기면 `features.hint_count`가 올라가서 Monitor의
    #     "힌트 요청 ×N" 근거와 R0 규칙이 학생의 대화 때문에 흔들린다.
    # 학생이 보낸 말과 평가 결과는 activity에 넣는다 (교육자 화면이 읽을 곳).
    trace_service.record_agent_intervention(
        db,
        body.session_id,
        state=ctx.process_status,
        concept=(ctx.problem.get("concepts") or [None])[0],
        action=AgentAction.HINT.value,
        reason=f"학생 답변에 응답했습니다. (이해도: {getattr(reply, 'understanding', '') or '미판정'})",
        activity={
            "kind": "chat",
            "message": message,
            "expects_reply": bool(getattr(reply, "expects_reply", False)),
            "question": str(getattr(reply, "question", "") or ""),
            # 학생이 무엇에 답했는지 / 무엇이라고 답했는지.
            "asked_question": question,
            "student_answer": answer,
            # 아래는 전부 내부 판단 (교육자 화면/분석용).
            "understanding": str(getattr(reply, "understanding", "") or ""),
            "is_correct": bool(getattr(reply, "is_correct", False)),
            "follow_up_needed": bool(getattr(reply, "follow_up_needed", True)),
            "misconceptions": list(getattr(reply, "misconceptions", []) or []),
            "evidence": str(getattr(reply, "evidence", "") or ""),
            "next_focus": str(getattr(reply, "next_focus", "") or ""),
        },
        trigger=None,
    )

    return AgentReplyRead(
        message=message,
        expects_reply=bool(getattr(reply, "expects_reply", False)),
        question=str(getattr(reply, "question", "") or ""),
    )
