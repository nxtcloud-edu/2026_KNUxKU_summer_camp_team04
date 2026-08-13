from __future__ import annotations

import logging

from app.agent.interface import AgentContext, AgentDecision, AgentProtocol
from app.agent.stub import WaitAgent
from app.config import get_settings

__all__ = ["AgentContext", "AgentDecision", "AgentProtocol", "WaitAgent", "get_agent"]

log = logging.getLogger(__name__)


def get_agent() -> AgentProtocol:
    """FastAPI 의존성. AGENT_BACKEND=llm이 들어오면 여기서 분기한다.

    **여기서 예외를 던지면 안 된다.** 이 함수는 Depends로 평가되므로
    라우터 본문보다 먼저 실행되고, post_result()의 try/except 바깥이다.
    던지면 POST /results가 500이 되고 채점 결과까지 유실된다 --
    "Judge 결과는 Agent 실패와 무관하게 반드시 반환한다"(backend_plan §14)가 깨진다.

    미구현 백엔드를 만나면 WaitAgent로 폴백하고 경고만 남긴다.
    """
    backend = get_settings().agent_backend
    if backend != "none":  # pragma: no cover - LLM 백엔드는 아직 없다
        log.warning(
            "AGENT_BACKEND=%s 는 아직 구현되지 않았습니다. WaitAgent로 폴백합니다.", backend
        )
    return WaitAgent()
