from __future__ import annotations

from app.config import get_settings
from app.judge.interface import JudgeMode, JudgeProtocol, JudgeResult
from app.judge.stub import FakeJudge, UnavailableJudge

__all__ = [
    "FakeJudge",
    "JudgeMode",
    "JudgeProtocol",
    "JudgeResult",
    "UnavailableJudge",
    "get_judge",
]


def get_judge() -> JudgeProtocol:
    """FastAPI 의존성. 테스트는 app.dependency_overrides로 FakeJudge를 주입한다."""
    if get_settings().judge_backend == "docker":
        from app.judge.docker_judge import DockerJudge

        return DockerJudge()
    return UnavailableJudge()
