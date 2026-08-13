from __future__ import annotations

from app.agent.interface import AgentContext, AgentDecision, AgentProtocol
from app.agent.stub import WaitAgent
from app.config import get_settings

__all__ = ["AgentContext", "AgentDecision", "AgentProtocol", "WaitAgent", "get_agent"]


def get_agent() -> AgentProtocol:
    """FastAPI 의존성. AGENT_BACKEND=llm이 들어오면 여기서 분기한다."""
    if get_settings().agent_backend == "llm":  # pragma: no cover - 아직 구현 없음
        raise NotImplementedError("LLM agent backend는 아직 구현되지 않았습니다.")
    return WaitAgent()
