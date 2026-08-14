"""Agent seam. 오늘은 LLM을 부르지 않는다."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.enums import AgentAction


@dataclass(frozen=True)
class AgentContext:
    """backend_plan §13이 정의한 Agent 입력.

    DB 전체를 넘기지 않는다. 최근 의미 있는 이벤트 10개까지만 넣어 토큰을 아낀다.
    """

    session_id: str
    problem: dict[str, Any]
    current_code: str
    current_code_version: int
    judge_result: dict[str, Any] | None
    recent_trace: list[str]
    features: dict[str, Any]
    process_status: str
    trigger: str | None
    evidence: list[str]
    previous_interventions: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class AgentDecision:
    state: str
    concept: str | None
    action: AgentAction
    reason: str
    activity: dict[str, Any] | None = None


@dataclass(frozen=True)
class AgentReply:
    """학생이 튜터에게 보낸 말에 대한 응답.

    `AgentDecision`("지금 개입할까?")과 다른 방향의 계약이다. 이쪽은 학생이
    먼저 말을 걸었으므로 개입 여부를 판단할 필요가 없고, 대신 **학생의 답변을
    평가한 결과**가 함께 온다.

    `message`만 학생에게 보여준다. `understanding` 이하는 내부 판단이며
    교육자 화면/분석용이다 -- "당신의 이해도는 partial입니다"는 학생에게
    도움이 되지 않고, 학습 의욕을 꺾는다.
    """

    message: str
    expects_reply: bool = False
    question: str = ""
    understanding: str = ""
    is_correct: bool = False
    follow_up_needed: bool = True
    misconceptions: list[str] = field(default_factory=list)
    evidence: str = ""
    next_focus: str = ""


@runtime_checkable
class AgentProtocol(Protocol):
    name: str

    def decide(self, ctx: AgentContext) -> AgentDecision: ...

    def respond(self, ctx: AgentContext, answer: str, question: str = "") -> AgentReply:
        """학생이 보낸 답변/질문에 응답한다.

        `decide()`가 "튜터가 먼저 말을 거는" 경로라면 이쪽은 "학생이 답했다"
        경로다. 구현체는 **예외를 던지지 않고** 최소한 사람이 읽을 수 있는
        문구를 돌려줘야 한다 -- 학생이 말을 걸었는데 아무 응답도 없는 것이
        최악의 경험이므로, 이 경로는 침묵으로 폴백하지 않는다.
        """
        ...
