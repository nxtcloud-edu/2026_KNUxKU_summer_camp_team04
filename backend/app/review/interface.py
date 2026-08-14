"""복습 문제 생성 seam.

`app/agent/interface.py`(AgentProtocol)와 같은 패턴이다: backend는 프로토콜만
알고, 실제 구현은 `tutor_agent.backend_entry`가 `dependency_overrides`로
꽂아준다. 그래서 backend venv는 `strands-agents`를 몰라도 되고, agent 서비스가
꺼져 있어도 서버는 뜬다.

**왜 AgentProtocol에 메서드를 하나 더 얹지 않았나.** `decide()`는 채점 응답
경로에 실려 나가는 실시간 호출(타임아웃 30초)이고 이쪽은 학생이 기다리지 않는
백그라운드 생성(타임아웃 180초)이다. 성격도 배선 시점도 달라서 한 프로토콜로
묶으면 한쪽만 필요한 구현체가 나머지 절반을 더미로 채워야 한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class GenerationResult:
    """agent `ValidationReport`의 backend 쪽 미러.

    `problem_json`은 judge 검증을 **통과한** 문제 본문이다 (judge/problems/*.json과
    같은 스키마, `problem_id`만 빠져 있음 — 그건 저장할 때 우리가 붙인다).
    """

    is_valid: bool
    problem_json: dict[str, Any] | None = None
    error_message: str | None = None
    failed_categories: list[str] = field(default_factory=list)


@runtime_checkable
class ProblemGeneratorProtocol(Protocol):
    name: str

    def generate(self, request: dict[str, Any]) -> GenerationResult:
        """복습 문제를 하나 만든다. **예외를 던지지 않는다.**

        실패는 `GenerationResult(is_valid=False, error_message=...)`로 표현한다 —
        이 호출은 BackgroundTasks 안에서 일어나므로 예외가 새면 아무도 못 보는
        곳에서 조용히 죽고, 학생의 요청은 PENDING인 채로 영원히 남는다.
        """
        ...


class UnavailableProblemGenerator:
    """기본 구현. agent가 안 붙어 있으면 항상 실패를 돌려준다.

    `app/agent/stub.py::WaitAgent`와 같은 역할이다 — 미구성 상태에서 500을
    내는 대신 "지금은 안 된다"를 구조화된 값으로 알린다.
    """

    name = "unavailable"

    def generate(self, request: dict[str, Any]) -> GenerationResult:
        return GenerationResult(
            is_valid=False,
            error_message=(
                "문제 생성 agent가 연결되지 않았습니다. "
                "agent 서비스(8100)를 띄우고 backend를 tutor_agent.backend_entry로 실행하세요."
            ),
        )


def get_problem_generator() -> ProblemGeneratorProtocol:
    """FastAPI 의존성. `tutor_agent.backend_entry.install()`이 override한다."""
    return UnavailableProblemGenerator()
