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

    # --- backend 연동에서만 채워지는 부가 신호 ---
    backend_signals: dict = Field(
        default_factory=dict,
        description=(
            "backend AgentContext에서 온, 위 필드로 표현되지 않는 신호들 "
            "(process_status, trigger, evidence, problem, judge_result, features 등). "
            "`backend_adapter.to_session_context()`가 채우며, 각 에이전트 프롬프트는 "
            "SessionContext를 그대로 직렬화하므로 이 내용이 LLM까지 전달된다. "
            "backend 없이 로컬로 돌릴 때는 빈 dict."
        ),
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
    """개입 시 어떻게 지도할지 결정하는 에이전트의 출력.

    **이건 "지도 계획"이지 학생에게 보여줄 문장이 아니다.** 여기에 담긴 값은
    전부 내부 지시문이며, 실제로 학생이 읽을 문장은 이 계획을 입력으로 받는
    `tutor_message_agent`가 따로 만든다 (`TutorMessage`).

    예전에는 이 모델에 `message_draft`가 있어서 결정 에이전트가 판단과 작문을
    동시에 했다. 그 결과 학생 화면에 "학생은 31분 넘게 막혀 있습니다
    (지도 방식: 단계별 구조 안내/explain)"처럼 **3인칭 내부 분석문**이 그대로
    노출됐다. 판단과 작문을 분리한 이유가 그거다 — 자세한 내용은
    `agents/tutor_message_agent.py` docstring 참고.

    지금은 LLM이 직접 이 모양으로 반환하지 않는다 — `GuidedAction`을 한 번에
    받아서 `orchestrator.py`가 이 모양으로 쪼갠다 (레이턴시 단축을 위해
    guidance+action을 LLM 호출 1번으로 합쳤다).
    """

    approach: str = Field(description="예: 소크라테스식 질문, 직접 힌트, 개념 재설명 등")
    hint_level: Literal["nudge", "hint", "explain"] = "nudge"
    focus: str = Field(
        default="",
        description="이번 개입에서 다룰 대상 하나 (예: '카운터 변수 초기화', 'while 조건식').",
    )
    talking_points: list[str] = Field(
        default_factory=list,
        description="응답 생성 에이전트가 메시지에 반드시 담아야 할 내용 (내부 지시문).",
    )
    avoid: list[str] = Field(
        default_factory=list,
        description="이번 메시지에서 알려주면 안 되는 것 (예: '완성된 for문 코드').",
    )
    expects_student_reply: bool = Field(
        default=False,
        description=(
            "학생의 답을 받아야 하는 개입인지. True면 응답 생성 에이전트가 질문 형태로 "
            "쓰고, 학생이 답하면 그 답을 evaluation_agent가 평가한다."
        ),
    )


class ActionPlan(BaseModel):
    """지도 방침이 정해졌을 때 무엇을 할지 결정하는 에이전트의 출력.

    `GuidancePlan`과 같은 사정 — 지금은 `GuidedAction`에서 쪼개져 나온다.
    """

    action_type: Literal["send_message", "highlight_code", "show_example", "no_op"]
    payload: dict = Field(default_factory=dict)


class GuidedAction(BaseModel):
    """지도 방법 + 구체적 행동을 한 번의 LLM 호출로 함께 결정하는 출력.

    이전에는 GuidancePlan(어떻게 가르칠지) -> ActionPlan(뭘 할지)을 LLM
    호출 2번으로 나눠 물었다. 둘은 강하게 결합된 하나의 판단이라("소크라테스식
    질문으로 가겠다"와 "그래서 화면에서 뭘 할지"를 따로 물을 이유가 약함)
    합쳤다 — 자세한 근거는 agent/README.md의 "지연 시간" 절 참고.

    **다만 "작문"은 여기서 하지 않는다.** 이 모델은 *어떻게 지도할지에 대한
    지시문*만 담고, 학생이 읽을 문장은 `TutorMessage`가 담는다. 판단하는
    에이전트와 말하는 에이전트를 나눈 이유는 `GuidancePlan` docstring 참고.

    `orchestrator.py`가 이 출력을 `GuidancePlan`/`ActionPlan`으로 쪼개서
    `PipelineResult`에 담는다 — `backend_adapter.to_agent_decision()`을
    포함한 하류 코드는 이 변경을 몰라도 된다.
    """

    approach: str = Field(description="예: 소크라테스식 질문, 직접 힌트, 개념 재설명 등")
    hint_level: Literal["nudge", "hint", "explain"] = "nudge"
    focus: str = Field(
        default="",
        description="이번 개입에서 다룰 대상 하나 (예: '카운터 변수 초기화').",
    )
    talking_points: list[str] = Field(
        default_factory=list, description="메시지에 반드시 담아야 할 내용 (내부 지시문)."
    )
    avoid: list[str] = Field(
        default_factory=list, description="이번 메시지에서 알려주면 안 되는 것."
    )
    expects_student_reply: bool = Field(
        default=False, description="학생의 답을 받아 이해도를 확인해야 하는 개입인지."
    )
    action_type: Literal["send_message", "highlight_code", "show_example", "no_op"]
    payload: dict = Field(default_factory=dict)


class TutorMessage(BaseModel):
    """응답 생성 에이전트(`tutor_message_agent`)의 출력 = **학생이 실제로 읽는 것.**

    파이프라인의 다른 모든 모델은 내부 판단이고, 학생에게 전달되는 텍스트는
    이 모델의 `message` **하나뿐이다.** `backend_adapter.to_agent_decision()`이
    이걸 `activity["message"]`에 넣고, 프런트엔드가 그걸 채팅 버블에 렌더한다.
    """

    message: str = Field(
        description="학생에게 그대로 보여줄 문장. 2인칭, 존댓말, 내부 분석 용어 금지."
    )
    question: str = Field(
        default="",
        description=(
            "학생의 답을 받아야 하는 경우 그 핵심 질문 하나. `message` 안에 이미 포함돼 "
            "있으며, 학생 답변을 평가할 때 '무엇을 물었는지'로 다시 쓰인다."
        ),
    )
    expects_reply: bool = Field(
        default=False, description="이 메시지가 학생의 답을 기다리는지 여부."
    )


class StudentReply(BaseModel):
    """튜터의 질문에 학생이 답한 내용. 학생 답변 평가 파이프라인의 입력.

    `question`은 학생이 보내주는 값이 아니라 **서버가 직전 개입 기록에서 찾아
    채운다** (`backend/app/agent/router.py` 참고). 학생 클라이언트가 "내가 받은
    질문은 이거였다"고 주장하는 걸 그대로 믿으면, 질문을 바꿔 보내서 평가를
    통과시킬 수 있다.
    """

    answer: str = Field(description="학생이 입력한 답변 원문.")
    question: str = Field(
        default="", description="튜터가 직전에 던진 질문 (없으면 자유 질문으로 취급)."
    )


class AnswerEvaluation(BaseModel):
    """평가 에이전트의 출력 = **학생 답변**에 대한 이해도 평가.

    예전에는 이 모델이 `effectiveness_score`/`notes`로 "AI가 방금 한 개입이
    적절했는지"를 담았다. 그건 학습 루프가 아니라 자기 채점이었다 — 튜터가
    질문을 던졌으면 평가해야 하는 대상은 **학생의 답**이다. 그래서 모델을
    학생 답변 평가로 바꿨다 (`agents/evaluation_agent.py` docstring 참고).
    """

    understanding: Literal["none", "partial", "solid"] = Field(
        description="학생이 물어본 개념을 이해했는지: none(못 함) / partial(일부) / solid(제대로)"
    )
    is_correct: bool = Field(description="답변 내용이 사실로서 맞는지.")
    evidence: str = Field(
        default="",
        description="그렇게 판단한 근거 (학생 답변 인용 등). **내부용** — 학생에게 보여주지 않는다.",
    )
    misconceptions: list[str] = Field(
        default_factory=list, description="답변에서 드러난 오개념 (내부용)."
    )
    follow_up_needed: bool = Field(
        default=True, description="추가 지도가 필요한지. False면 다음 단계로 넘어가도 좋다는 뜻."
    )
    next_focus: str = Field(
        default="",
        description="다음 메시지에서 다뤄야 할 것 (내부 지시문 — 응답 생성 에이전트의 입력).",
    )


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
