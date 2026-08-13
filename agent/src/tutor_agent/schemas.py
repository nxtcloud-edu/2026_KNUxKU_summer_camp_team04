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

    # --- 규칙 기반 진입 게이트(agents/state_agent.py)가 필요로 하는 신호들 ---
    # 프런트엔드에서 계산해서 넘겨줘야 하는 값은 각 필드에 명시했다.
    seconds_since_last_intervention: float | None = Field(
        default=None,
        description="마지막 개입 이후 경과 시간(초). 개입 이력이 없으면 None (쿨다운 미적용).",
    )
    session_ended: bool = Field(default=False, description="세션이 이미 종료되었는지 여부.")
    edit_churn_count: int = Field(
        default=0,
        description="같은 부분을 여러 번 작성→삭제한 횟수(churn). 프런트엔드에서 계산해 전달.",
    )
    cursor_stuck_seconds: float = Field(
        default=0.0,
        description="커서가 같은 함수/블록을 벗어나지 못한 시간(초). 프런트엔드에서 계산해 전달.",
    )
    paste_detected: bool = Field(
        default=False, description="최근 편집이 붙여넣기였는지 여부. 막힘 신호가 아니라 별도 분기로 처리한다.",
    )


class StudentState(BaseModel):
    """문제 풀이 중 학생 상태 파악 에이전트의 출력 (개입시점 결정 포함).

    과거에는 별도의 EntryAgent(LLM)가 파이프라인 진입 여부를 먼저 결정했지만,
    지금은 그 판단(규칙 기반 게이트)이 `state_agent.assess()` 안에 흡수되어
    이 모델 하나로 표현된다. `entry_branch`가 그 판단이 어떤 경로였는지를 보여준다.
    """

    state_summary: str
    struggle_signals: list[str] = Field(default_factory=list)
    should_intervene: bool
    urgency: Literal["low", "medium", "high"] = "low"
    entry_branch: Literal["struggle", "paste", "skip"] = Field(
        default="struggle",
        description=(
            "이 판단이 어떤 경로로 나왔는지: struggle(규칙 게이트 통과 후 LLM 평가) / "
            "paste(붙여넣기 감지, 규칙만으로 판단·LLM 미사용) / "
            "skip(규칙 게이트에서 조기 종료, LLM 미사용)"
        ),
    )


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
