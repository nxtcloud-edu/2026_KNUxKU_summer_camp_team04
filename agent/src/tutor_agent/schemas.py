"""파이프라인 전체가 공유하는 데이터 모델.

각 에이전트는 Strands의 `Agent.structured_output()`을 통해 아래 Pydantic 모델
중 하나를 직접 반환한다. 필드/기준은 초안이며 팀 논의로 계속 다듬어야 한다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SessionContext(BaseModel):
    """한 학생의 문제 풀이 세션 스냅샷. 파이프라인 전체에서 공유된다.

    backend가 프런트엔드 이벤트(코드 변경/실행/제출 등)를 받아 이 형태로
    채워서 넘겨준다고 가정한다.
    """

    student_id: str
    problem_id: str
    code: str = ""
    run_history: list[str] = Field(
        default_factory=list, description="최근 실행/제출 결과 로그 요약 (예: '0/5 tests passed')"
    )
    elapsed_seconds: float = 0.0
    idle_seconds: float = 0.0
    last_error: str | None = None


class EntryDecision(BaseModel):
    """진입시점 결정 에이전트의 출력."""

    should_enter: bool
    reason: str


class StudentState(BaseModel):
    """문제 풀이 중 학생 상태 파악 에이전트의 출력 (개입시점 결정 포함)."""

    state_summary: str
    struggle_signals: list[str] = Field(default_factory=list)
    should_intervene: bool
    urgency: Literal["low", "medium", "high"] = "low"


class GuidancePlan(BaseModel):
    """개입 시 어떻게 지도할지 결정하는 에이전트의 출력."""

    approach: str = Field(description="예: 소크라테스식 질문, 직접 힌트, 개념 재설명 등")
    hint_level: Literal["nudge", "hint", "explain"] = "nudge"
    message_draft: str


class ActionPlan(BaseModel):
    """지도 방침이 정해졌을 때 무엇을 할지 결정하는 에이전트의 출력."""

    action_type: Literal["send_message", "highlight_code", "show_example", "no_op"]
    payload: dict = Field(default_factory=dict)


class Evaluation(BaseModel):
    """평가 에이전트의 출력."""

    effectiveness_score: float = Field(ge=0.0, le=1.0)
    notes: str
    follow_up_needed: bool
