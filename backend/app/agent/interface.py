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


@runtime_checkable
class AgentProtocol(Protocol):
    name: str

    def decide(self, ctx: AgentContext) -> AgentDecision: ...
