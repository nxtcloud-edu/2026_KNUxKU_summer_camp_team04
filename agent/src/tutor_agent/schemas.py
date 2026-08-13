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


# ---------------------------------------------------------------------------
# 오답/복습 기반 문제 생성 (기존 튜터 파이프라인과는 별개 기능).
#
# LLM 호출을 복습 횟수에 비례하지 않게 하기 위해 4계층으로 나뉜다: 문제 뱅크
# 검색(LLM 0회) -> 코스메틱 변주(LLM 1회, 저렴) -> 인스턴스 랜덤화(LLM 0회,
# 코드) -> 새 구조적 템플릿 생성(LLM, 다양성 예산 소진 시에만 드물게).
# 아래 스키마는 그중 가장 무거운 마지막 계층, ProblemTemplate 생성 + judge
# 검증에 쓰인다.
# ---------------------------------------------------------------------------


class ReviewRequest(BaseModel):
    """오답/복습 기반 새 문제 생성 요청.

    학생이 어떤 개념에서 반복 오답을 냈는지를 담아 problem_generator_agent에
    넘긴다. 이 요청 자체는 상위 정책(문제 뱅크 검색 등)이 이미 "새로 생성해야
    한다"고 판단한 뒤에만 만들어진다고 가정한다.
    """

    student_id: str
    concept: str = Field(description="복습 대상 개념 (예: 'loop', 'recursion')")
    missed_problem_ids: list[str] = Field(default_factory=list)
    difficulty_hint: Literal["easier", "same", "harder"] = "same"


class TestCaseInput(BaseModel):
    """검증 전 테스트케이스 입력.

    expected/expected_stdout을 일부러 갖지 않는다 — LLM이 계산한 값은
    신뢰하지 않고, judge가 reference_solution을 실제로 실행한 출력을 정답으로
    확정하기 때문 (judge_validator.validate_template 참고).
    """

    __test__ = False  # pytest가 이름이 Test로 시작한다고 테스트 클래스로 오인하는 것 방지

    category: str
    is_hidden: bool = False
    input: list | None = Field(default=None, description="function_call용 positional args")
    stdin: str | None = Field(default=None, description="stdout_match용 표준입력")


class ProblemTemplate(BaseModel):
    """LLM이 한 번의 구조화 출력으로 생성하는 문제 템플릿.

    problem_generator_agent가 반환하는 형태이며, judge_validator가 이걸 받아
    judge 샌드박스에서 reference_solution을 실행해 검증한다.
    """

    concept: list[str]
    title: str
    description: str
    check_type: Literal["function_call", "stdout_match"]
    function_name: str | None = None
    code_template: str
    reference_solution: str = Field(description="judge 샌드박스에서 실제로 실행해 정답을 확정할 코드")
    test_case_inputs: list[TestCaseInput]
    time_limit_sec: float | None = None
    memory_limit_mb: float | None = None


class ValidationReport(BaseModel):
    """judge_validator.validate_template()의 출력.

    problem_json은 judge의 problems/*.json과 동일한 스키마(problem_id 제외 —
    저장 시점에 호출자가 부여)이며, is_valid=True일 때만 채워진다.
    """

    is_valid: bool
    problem_json: dict | None = None
    error_message: str | None = None
    failed_categories: list[str] = Field(default_factory=list)
