"""backend(`AgentProtocol`) ↔ tutor_agent 파이프라인 어댑터.

backend(`backend/app/agent/interface.py`)는 이미 아래 계약을 정의해 두었다:

    class AgentProtocol(Protocol):
        name: str
        def decide(self, ctx: AgentContext) -> AgentDecision: ...

이 모듈의 `TutorAgentAdapter`가 그 계약을 만족한다. backend 쪽에서는
`get_agent()`가 이 클래스의 인스턴스를 반환하도록 한 줄만 바꾸면 연결이 끝난다
(정확한 스니펫은 `agent/README.md`의 "backend 연결" 절 참고).

설계 원칙
---------
1. **backend 코드를 import하지 않는다.** agent/와 backend/는 별도 프로젝트(별도
   venv)다. 그래서 `AgentAction` / `AgentContext` / `AgentDecision`을 여기서
   *미러링*한다 — 필드명과 enum 값이 backend와 글자 그대로 같다. backend의
   라우터는 `decision.action.value`(str)만 읽으므로, 우리 enum이 backend의
   enum과 다른 클래스여도 그대로 동작한다.
2. **절대 예외를 던지지 않는다.** `decide()`는 어떤 실패(LLM 오류, 네트워크,
   필드 누락, 스키마 검증 실패, strands 미설치 등)에서도 `AgentAction.WAIT`로
   폴백한다. backend에서 이 값은 채점 응답(`POST /results`)과 같은 트랜잭션에
   실려 나가므로, 여기서 예외가 새면 Agent 실패가 채점 결과까지 깨뜨린다
   (backend_plan §14: "Judge 결과는 Agent 실패와 무관하게 반드시 반환한다").
3. **agent 자체 규칙 게이트를 건너뛴다** (`skip_gate=True`). backend Process
   Monitor가 자기 규칙으로 이미 "지금이 개입 시점"이라고 판단해서 우리를
   호출한 것이므로, `state_agent`의 게이트가 서로 다른 기준(예: backend의
   `same_region_edit_count` vs 우리 `edit_churn_count`)으로 재판정하다가
   Monitor의 판단을 조용히 WAIT로 덮어쓰는 일을 막는다.
4. **strands / LLM 의존성을 import 시점에 끌어오지 않는다.** `TutorPipeline`은
   첫 `decide()` 호출 때 lazy import한다. 덕분에 backend venv에
   `strands-agents`가 없어도 `import tutor_agent.backend_adapter` 자체는
   성공하고, 실패는 WAIT 폴백으로만 나타난다.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from .schemas import SessionContext

if TYPE_CHECKING:  # 타입 체크 전용. 런타임에는 strands를 끌어오지 않는다.
    from .orchestrator import PipelineResult

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# backend 계약 미러 (backend/app/enums.py, backend/app/agent/interface.py)
#
# 값/필드명이 backend와 한 글자라도 달라지면 연결이 조용히 깨진다.
# tests/test_backend_adapter.py가 backend 소스를 **텍스트로 읽어** 이 미러가
# 드리프트했는지 검사한다 (import는 하지 않는다).
# ---------------------------------------------------------------------------


class AgentAction(str, Enum):
    """`backend/app/enums.py::AgentAction` 미러."""

    WAIT = "WAIT"
    HINT = "HINT"
    TRACE = "TRACE"
    PREDICT = "PREDICT"
    DEBUG = "DEBUG"
    VERIFY = "VERIFY"


@dataclass(frozen=True)
class AgentContext:
    """`backend/app/agent/interface.py::AgentContext` 미러.

    실제 런타임에는 backend가 자기 dataclass 인스턴스를 넘기므로 이 클래스는
    쓰이지 않는다 (변환 함수들은 duck typing으로 동작하며 dict도 받는다).
    테스트 픽스처와 필드명 문서화를 위해 둔다.
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
    """`backend/app/agent/interface.py::AgentDecision` 미러."""

    state: str
    concept: str | None
    action: AgentAction
    reason: str
    activity: dict[str, Any] | None = None


@dataclass(frozen=True)
class AgentReply:
    """`backend/app/agent/interface.py::AgentReply` 미러.

    학생이 튜터에게 보낸 말에 대한 응답. `message`만 학생에게 보여주고, 나머지
    (학생 답변 평가 결과)는 backend가 trace에만 남긴다.
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


# ---------------------------------------------------------------------------
# 어휘 매핑
# ---------------------------------------------------------------------------

#: agent `ActionPlan.action_type` → backend `AgentAction`.
#:
#: 지금 agent/에는 TRACE/PREDICT/DEBUG/VERIFY 활동(Activity)을 만들어내는 로직이
#: 없다. 그래서 "아무것도 안 함"만 WAIT로 보내고 나머지 실제 개입은 전부 HINT로
#: 모은다. 활동 생성기가 붙으면 이 표만 넓히면 된다.
ACTION_TYPE_TO_AGENT_ACTION: dict[str, AgentAction] = {
    "no_op": AgentAction.WAIT,
    "send_message": AgentAction.HINT,
    "highlight_code": AgentAction.HINT,
    "show_example": AgentAction.HINT,
}

#: backend Monitor가 이 상태/트리거를 주면 "막힘"이 아니라 **이해도 확인** 상황이다
#: (R2: 대규모 변경 직후 통과). agent 쪽 `paste_detected` 분기와 같은 의미라서
#: 그 필드로 옮긴다 — `state_agent`가 LLM 없이 이해도 확인 경로로 보낸다.
COMPREHENSION_CHECK_SIGNAL = "UNDERSTANDING_UNCERTAIN"

#: judge 결과 중 "점수 없음(에러)"에 해당하는 status (backend/app/enums.py 참고).
JUDGE_ERROR_STATUSES = frozenset(
    {"RUNTIME_ERROR", "SYNTAX_ERROR", "TIME_LIMIT", "INTERNAL_ERROR"}
)

WAIT_REASON_FALLBACK = (
    "Agent 파이프라인을 신뢰할 수 있게 실행하지 못해 개입하지 않고 기다립니다."
)

#: 학생이 말을 걸었는데 파이프라인이 실패했을 때 보내는 문구.
#:
#: 자동 개입 경로는 실패하면 WAIT(=침묵)으로 떨어지는 게 맞다 — 학생은 애초에
#: 무언가를 기대하고 있지 않았다. 반면 학생이 직접 질문/답변을 보낸 경로에서
#: 침묵하면 "튜터가 내 말을 씹었다"가 된다. 그래서 이쪽은 항상 문장을 돌려준다.
REPLY_FALLBACK_MESSAGE = (
    "지금 답을 정리하지 못했어요. 잠시 뒤에 다시 물어봐 줄래요? "
    "그동안 코드를 한 줄씩 소리 내어 읽어보면 걸리는 지점이 보일 수 있어요."
)


def _fallback_reply(message: str) -> "AgentReply":
    """`respond()`의 실패 응답. 평가 결과 자리는 비워 둔다 (판정하지 못했으므로)."""
    return AgentReply(message=message, follow_up_needed=True)


# ---------------------------------------------------------------------------
# 필드 접근 헬퍼 (dataclass / pydantic / dict 아무거나 받는다)
# ---------------------------------------------------------------------------


def _field_of(ctx: Any, name: str, default: Any = None) -> Any:
    """`ctx`에서 `name`을 읽는다. 없거나 None이면 `default`.

    backend가 넘기는 frozen dataclass, 테스트가 넘기는 dict, 미래에 pydantic
    모델로 바뀌는 경우까지 같은 코드로 처리한다.
    """
    if isinstance(ctx, Mapping):
        value = ctx.get(name, default)
    else:
        value = getattr(ctx, name, default)
    return default if value is None else value


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_str_list(value: Any) -> list[str]:
    if isinstance(value, str) or not isinstance(value, (list, tuple, set)):
        return [str(value)] if value else []
    return [str(v) for v in value]


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


# ---------------------------------------------------------------------------
# backend AgentContext → agent SessionContext
# ---------------------------------------------------------------------------


def _judge_summary(judge_result: Mapping[str, Any]) -> str:
    """judge 결과를 `run_history` 한 줄로. "N/M" 형태를 유지해야 한다.

    `state_agent._is_failure()`가 "N/M" 패턴을 읽어 실패를 판별하므로, 여기서
    포맷을 바꾸면 (게이트를 켠 경로에서) 반복 실패 탐지가 조용히 망가진다.
    """
    mode = judge_result.get("mode", "run")
    status = judge_result.get("status", "")
    passed = _as_int(judge_result.get("passed", 0))
    total = _as_int(judge_result.get("total", 0))
    line = f"[{mode}] {status} {passed}/{total} tests passed"
    failed = _as_str_list(judge_result.get("failed_categories"))
    if failed:
        line += f" (실패 카테고리: {', '.join(failed)})"
    return line


def _run_history(ctx: Any) -> list[str]:
    history = _as_str_list(_field_of(ctx, "recent_trace", []))
    judge_result = _field_of(ctx, "judge_result")
    if isinstance(judge_result, Mapping):
        history.append(_judge_summary(judge_result))
    return history


def _last_error(ctx: Any) -> str | None:
    features = _as_dict(_field_of(ctx, "features", {}))
    error_types = _as_str_list(features.get("recent_error_types"))
    if error_types:
        return error_types[-1]
    judge_result = _field_of(ctx, "judge_result")
    if isinstance(judge_result, Mapping):
        status = str(judge_result.get("status", ""))
        if status in JUDGE_ERROR_STATUSES:
            return status
    return None


def _is_comprehension_check(ctx: Any) -> bool:
    trigger = str(_field_of(ctx, "trigger", "") or "")
    status = str(_field_of(ctx, "process_status", "") or "")
    return COMPREHENSION_CHECK_SIGNAL in (trigger, status)


def to_session_context(ctx: Any) -> SessionContext:
    """backend `AgentContext`(또는 같은 필드를 가진 dict) → agent `SessionContext`.

    필드 대응이 1:1이 아닌 곳(= 설계 결정이 들어간 곳)만 정리하면:

    | SessionContext | 출처 | 비고 |
    |---|---|---|
    | `student_id` | `session_id` | backend ctx에 학생 id가 없다 (세션 단위 계약) |
    | `problem_id` | `problem["problem_id"]` | |
    | `idle_seconds` | `features["seconds_without_progress"]` | 키 입력 유휴가 아니라 "결과 진전 없음" 시간 — backend가 주는 가장 가까운 신호 |
    | `edit_churn_count` | `features["same_region_edit_count"]` | 같은 영역 반복 수정 = churn |
    | `cursor_stuck_seconds` | 0.0 | backend는 커서 위치를 추적하지 않는다 |
    | `paste_detected` | `trigger`/`process_status == UNDERSTANDING_UNCERTAIN` | backend R2(대규모 변경 직후 통과) = 이해도 확인 분기 |
    | `session_ended` | False | backend는 세션이 살아 있을 때만 우리를 부른다 |
    | `seconds_since_last_intervention` | None | backend ctx는 개입 이력의 seq만 준다(초 없음). 쿨다운은 backend Monitor가 이미 적용한다 |
    | `backend_signals` | ctx 전체 요약 | 위 표로 표현되지 않는 신호(트리거/근거/문제 설명/features 전체)를 LLM 프롬프트까지 그대로 실어 보낸다 |

    `session_ended`/`seconds_since_last_intervention`을 고정값으로 두는 게
    안전한 이유: 어댑터는 `skip_gate=True`로 파이프라인을 돌리므로 이 두 필드는
    게이트 판정에 쓰이지 않는다 (쿨다운/세션 종료 판단은 backend 소관).
    """
    features = _as_dict(_field_of(ctx, "features", {}))
    problem = _as_dict(_field_of(ctx, "problem", {}))
    session_id = str(_field_of(ctx, "session_id", "") or "")

    return SessionContext(
        student_id=session_id,
        problem_id=str(problem.get("problem_id", "") or ""),
        code=str(_field_of(ctx, "current_code", "") or ""),
        run_history=_run_history(ctx),
        elapsed_seconds=_as_float(features.get("elapsed_seconds", 0.0)),
        idle_seconds=_as_float(features.get("seconds_without_progress", 0.0)),
        last_error=_last_error(ctx),
        seconds_since_last_intervention=None,
        session_ended=False,
        edit_churn_count=_as_int(features.get("same_region_edit_count", 0)),
        cursor_stuck_seconds=0.0,
        paste_detected=_is_comprehension_check(ctx),
        backend_signals={
            "process_status": str(_field_of(ctx, "process_status", "") or ""),
            "trigger": _field_of(ctx, "trigger"),
            "evidence": _as_str_list(_field_of(ctx, "evidence", [])),
            "problem": problem,
            "judge_result": _field_of(ctx, "judge_result"),
            "current_code_version": _as_int(_field_of(ctx, "current_code_version", 0)),
            "features": features,
            "previous_interventions": [
                _as_dict(item)
                for item in _field_of(ctx, "previous_interventions", []) or []
            ],
        },
    )


# ---------------------------------------------------------------------------
# agent PipelineResult → backend AgentDecision
# ---------------------------------------------------------------------------


def _state_label(ctx: Any, fallback: str = "") -> str:
    """`AgentDecision.state`는 backend 어휘(`ProcessStatus`)를 그대로 돌려준다.

    backend의 `WaitAgent`도 `ctx.process_status`를 반환한다. 여기서 agent 고유
    문장(예: "같은 오류를 반복하고 있습니다")을 넣으면 timeline/교육자 화면이
    상태값으로 파싱할 수 없는 문자열을 받게 된다. agent의 자연어 판단은
    `reason`과 `activity`로 전달한다.
    """
    return str(_field_of(ctx, "process_status", "") or "") or fallback


def _concept(ctx: Any) -> str | None:
    concepts = _as_str_list(_as_dict(_field_of(ctx, "problem", {})).get("concepts"))
    return concepts[0] if concepts else None


def _wait_decision(ctx: Any, reason: str) -> AgentDecision:
    """어떤 상황에서도 던지지 않는 WAIT 결정."""
    try:
        state = _state_label(ctx)
        concept = _concept(ctx)
    except Exception:  # ctx 필드 접근 자체가 터지는 경우까지 방어한다.
        state, concept = "", None
    return AgentDecision(
        state=state,
        concept=concept,
        action=AgentAction.WAIT,
        reason=reason,
        activity=None,
    )


def to_agent_decision(result: "PipelineResult", ctx: Any) -> AgentDecision:
    """agent `PipelineResult` → backend `AgentDecision`.

    - 파이프라인이 개입하지 않기로 했으면(`should_intervene=False`) WAIT.
    - `action_type == "no_op"`도 WAIT.
    - 학생에게 보낼 메시지가 비어 있으면 WAIT (아래 "무엇이 학생에게 가는가").
    - 그 밖의 실제 개입(`send_message`/`highlight_code`/`show_example`)은 HINT로
      모은다 (`ACTION_TYPE_TO_AGENT_ACTION`).

    무엇이 학생에게 가는가
    ----------------------
    **`activity["message"]` 하나뿐이다.** 그 값은 응답 생성
    에이전트(`agents/tutor_message_agent.py`)가 만든 문장이고, 프런트엔드가
    그것만 채팅 버블에 렌더한다.

    `reason`은 학생용이 아니다 — `StudentState.state_summary`(3인칭 내부 분석문)에
    지도 방식을 덧붙인 **교육자/타임라인용 근거**다. 이 함수가 한동안 그
    `reason`을 학생에게 보여줄 유일한 문구처럼 내보내고 있었고(프런트엔드가
    `reason`을 렌더했다), 그래서 학생이 이런 걸 읽었다:

        loop 부분을 같이 보면 좋겠어요. 학생은 함수의 기본 구조를 이해하지 못한
        채 31분 넘게 완전히 막혀 있습니다. ... 힌트를 6회 요청했지만 ...
        (지도 방식: 단계별 구조 안내 + 구체적 예시 제공/explain)

    지금은 (1) 파이프라인이 학생용 문장을 따로 만들고, (2) 그 문장이 없으면
    내부 판단문으로 폴백하지 않고 WAIT하며, (3) 프런트엔드가 `activity.message`를
    우선 렌더한다. 세 지점 중 하나만 고치면 재발하기 쉬우므로 셋 다 고쳐 뒀다.
    """
    student_state = getattr(result, "student_state", None)
    action_plan = getattr(result, "action_plan", None)
    guidance_plan = getattr(result, "guidance_plan", None)
    tutor_message = getattr(result, "tutor_message", None)

    summary = str(getattr(student_state, "state_summary", "") or "")
    state = _state_label(ctx, fallback=summary)
    concept = _concept(ctx)

    if student_state is None or not getattr(student_state, "should_intervene", False):
        return AgentDecision(
            state=state,
            concept=concept,
            action=AgentAction.WAIT,
            reason=summary or "지금은 개입이 필요하지 않다고 판단했습니다.",
        )

    if action_plan is None:
        # should_intervene=True인데 행동이 없다 = 파이프라인이 중간에 멈춤.
        return AgentDecision(
            state=state,
            concept=concept,
            action=AgentAction.WAIT,
            reason=summary or WAIT_REASON_FALLBACK,
        )

    action_type = str(getattr(action_plan, "action_type", "") or "")
    action = ACTION_TYPE_TO_AGENT_ACTION.get(action_type, AgentAction.HINT)
    if action is AgentAction.WAIT:
        return AgentDecision(
            state=state,
            concept=concept,
            action=AgentAction.WAIT,
            reason=summary or "이미 충분히 개입했다고 판단해 이번에는 기다립니다.",
        )

    approach = str(getattr(guidance_plan, "approach", "") or "")
    hint_level = str(getattr(guidance_plan, "hint_level", "") or "")
    payload = _as_dict(getattr(action_plan, "payload", {}))

    # 학생이 읽는 문구는 응답 생성 에이전트(`tutor_message_agent`)가 만든 것
    # **하나뿐이다.** 이게 비어 있으면 개입을 포기하고 WAIT으로 내려간다 (아래).
    message = str(getattr(tutor_message, "message", "") or "")
    if not message:
        message = str(payload.get("message", "") or "")

    if not message.strip():
        # 예전에는 이 자리에서 `state_summary`(3인칭 내부 분석문)로 폴백했다.
        # 그게 "학생은 31분 넘게 막혀 있습니다 (지도 방식: .../explain)"가 학생
        # 화면에 뜬 경로다. 보여줄 말이 없으면 아무 말도 하지 않는 게 맞다 —
        # 내부 판단문을 대신 내보내는 것보다 낫다.
        log.warning(
            "개입하기로 했지만 학생에게 보낼 메시지가 비어 있습니다. WAIT으로 폴백합니다. "
            "(approach=%r action_type=%r)",
            approach,
            action_type,
        )
        return AgentDecision(
            state=state,
            concept=concept,
            action=AgentAction.WAIT,
            reason="학생에게 전달할 메시지를 만들지 못해 개입하지 않고 기다립니다.",
        )

    # `reason`은 **교육자/타임라인용 내부 근거**다 (학생 화면에 렌더되지 않는다).
    # 학생에게 가는 것은 `activity["message"]`뿐이다 — frontend
    # `AiTutorPanel.formatAgentDecision()` 참고.
    reason = summary or "학생이 막혀 있다고 판단했습니다."
    if approach:
        reason = f"{reason} (지도 방식: {approach}"
        reason += f"/{hint_level})" if hint_level else ")"

    activity: dict[str, Any] = {
        "kind": "hint",
        # 학생에게 실제로 보여줄 문구. **이 값만 학생에게 노출된다.**
        "message": message,
        # 학생의 답을 기다리는 질문인지. frontend가 이 값으로 입력창을 열고,
        # backend가 학생 답변을 평가할 때 "무엇을 물었는지"로 `question`을 쓴다.
        "expects_reply": bool(getattr(tutor_message, "expects_reply", False)),
        "question": str(getattr(tutor_message, "question", "") or ""),
        "hint_level": hint_level,
        "approach": approach,
        # agent 쪽 원본 어휘도 같이 남긴다. HINT로 뭉갠 정보를 나중에 세분화
        # (TRACE/PREDICT/DEBUG/VERIFY)할 때 이 값이 근거가 된다.
        "action_type": action_type,
        "payload": payload,
        "urgency": str(getattr(student_state, "urgency", "") or ""),
        "entry_branch": str(getattr(student_state, "entry_branch", "") or ""),
        "struggle_signals": _as_str_list(
            getattr(student_state, "struggle_signals", [])
        ),
        # 내부 판단 근거. 교육자 화면/분석용이며 학생에게 보여주면 안 된다.
        "state_summary": summary,
    }

    return AgentDecision(
        state=state,
        concept=concept,
        action=action,
        reason=reason,
        activity=activity,
    )


# ---------------------------------------------------------------------------
# AgentProtocol 구현체
# ---------------------------------------------------------------------------


class TutorAgentAdapter:
    """backend `AgentProtocol`을 만족하는 tutor_agent 어댑터.

    ```python
    # backend/app/agent/__init__.py::get_agent() 안에서 (이 작업 범위 밖)
    from tutor_agent.backend_adapter import TutorAgentAdapter
    return TutorAgentAdapter()
    ```

    Args:
        pipeline: 테스트에서 mock을 꽂기 위한 주입 지점. None이면 첫
            `decide()` 호출 때 `TutorPipeline()`을 lazy 생성한다 (생성 자체가
            LLM 프로바이더/키를 건드리므로 import 시점에 하지 않는다).
        skip_gate: agent 자체 규칙 게이트를 건너뛸지. 기본값 True —
            backend Monitor가 이미 개입 시점을 판단해서 호출하기 때문이다.
    """

    #: backend가 로그/이벤트에 남기는 이름.
    name = "tutor_agent"

    def __init__(self, pipeline: Any | None = None, *, skip_gate: bool = True) -> None:
        self._pipeline = pipeline
        self._skip_gate = skip_gate

    def _get_pipeline(self) -> Any:
        if self._pipeline is None:
            # lazy import: strands가 없는 환경에서도 이 모듈 import는 성공해야 한다.
            from .orchestrator import TutorPipeline

            self._pipeline = TutorPipeline()
        return self._pipeline

    def decide(self, ctx: Any) -> AgentDecision:
        """backend가 부르는 단일 진입점. **어떤 경우에도 예외를 던지지 않는다.**"""
        decision, _result = self.decide_with_pipeline_result(ctx)
        return decision

    def decide_with_pipeline_result(self, ctx: Any) -> tuple[AgentDecision, Any | None]:
        """`decide()`와 완전히 같은 로직 + 중간 `PipelineResult`도 같이 반환한다.

        `service.py`가 evaluation을 백그라운드로 돌리려면(응답을 그걸로 늦추지
        않으려면) 이 결정이 어떤 `action_plan`/`SessionContext`에서 나왔는지가
        필요한데, `decide()`는 최종 `AgentDecision`만 반환해서 그 중간 값에
        접근할 수 없었다. `decide()`는 이 메서드를 감싸기만 하므로 동작은
        완전히 동일하다 (기존 테스트 그대로 통과).

        Returns:
            `(decision, session_ctx)` 튜플. 실패 지점에 따라 두 번째 값은
            `to_session_context()`가 성공했을 때만 채워지고, 그 전에 실패하면
            `None`이다 (그 경우 애초에 evaluation을 돌릴 근거 자체가 없다).
        """
        try:
            session_ctx = to_session_context(ctx)
        except Exception:
            log.exception("backend AgentContext 변환 실패. WAIT로 폴백합니다.")
            return (
                _wait_decision(ctx, "세션 컨텍스트를 해석하지 못해 개입하지 않고 기다립니다."),
                None,
            )

        try:
            result = self._get_pipeline().run(session_ctx, skip_gate=self._skip_gate)
        except Exception:
            log.exception("tutor_agent 파이프라인 실행 실패. WAIT로 폴백합니다.")
            return _wait_decision(ctx, WAIT_REASON_FALLBACK), None

        try:
            return to_agent_decision(result, ctx), (session_ctx, result)
        except Exception:
            log.exception("PipelineResult 변환 실패. WAIT로 폴백합니다.")
            return (
                _wait_decision(ctx, "Agent 결과를 해석하지 못해 개입하지 않고 기다립니다."),
                None,
            )

    def respond(self, ctx: Any, answer: str, question: str = "") -> AgentReply:
        """학생이 보낸 답변을 평가하고 이어서 할 말을 만든다. **예외를 던지지 않는다.**

        `decide()`가 "튜터가 먼저 말을 거는" 경로라면 이쪽은 "학생이 답했다"
        경로다. 학생 답변 평가(`evaluation_agent`) → 응답 생성
        (`tutor_message_agent`) 두 단계를 거친다.

        Args:
            ctx: backend `AgentContext`(또는 같은 필드를 가진 dict).
            answer: 학생이 입력한 답변 원문.
            question: 튜터가 직전에 던진 질문. **서버가 개입 기록에서 찾아
                채운다** — 학생 클라이언트가 주장하는 값을 그대로 믿으면 질문을
                바꿔 보내 평가를 통과시킬 수 있다.

        Returns:
            `AgentReply`. 실패 시 `message`에 사람이 읽을 수 있는 폴백 문구가
            담긴다 — 학생이 말을 걸었는데 아무 응답도 없는 것이 최악이므로,
            이 경로는 WAIT(=침묵)로 떨어지지 않는다.
        """
        answer = (answer or "").strip()
        if not answer:
            return _fallback_reply("답변이 비어 있어요. 어떤 부분이 어려운지 한 줄만 적어줄래요?")

        try:
            session_ctx = to_session_context(ctx)
        except Exception:
            log.exception("backend AgentContext 변환 실패 (학생 답변 경로).")
            return _fallback_reply(REPLY_FALLBACK_MESSAGE)

        try:
            from .schemas import StudentReply

            result = self._get_pipeline().respond_to_student(
                session_ctx, StudentReply(answer=answer, question=question or "")
            )
        except Exception:
            log.exception("학생 답변 응답 파이프라인 실행 실패.")
            return _fallback_reply(REPLY_FALLBACK_MESSAGE)

        message = str(getattr(result.tutor_message, "message", "") or "").strip()
        evaluation = result.evaluation
        return AgentReply(
            message=message or REPLY_FALLBACK_MESSAGE,
            expects_reply=bool(getattr(result.tutor_message, "expects_reply", False)),
            question=str(getattr(result.tutor_message, "question", "") or ""),
            # 아래는 전부 내부 판단이다 (교육자 화면/분석용). 학생에게 보여주지 않는다.
            understanding=str(getattr(evaluation, "understanding", "") or ""),
            is_correct=bool(getattr(evaluation, "is_correct", False)),
            follow_up_needed=bool(getattr(evaluation, "follow_up_needed", True)),
            misconceptions=_as_str_list(getattr(evaluation, "misconceptions", [])),
            evidence=str(getattr(evaluation, "evidence", "") or ""),
            next_focus=str(getattr(evaluation, "next_focus", "") or ""),
        )


@lru_cache(maxsize=1)
def get_backend_agent() -> TutorAgentAdapter:
    """`get_agent()`에서 한 줄로 쓰기 위한 팩토리. 예외를 던지지 않는다.

    **싱글턴이다.** backend의 `get_agent()`는 FastAPI `Depends`라 요청마다
    평가되는데, 매번 새 어댑터를 만들면 인스턴스에 캐시된 `TutorPipeline`도
    매번 다시 만들어진다 (= 요청마다 strands `Agent` 4개 재생성). 어댑터는
    상태를 갖지 않으므로(파이프라인 핸들만 캐시) 공유해도 안전하다.

    테스트에서 새 인스턴스가 필요하면 `get_backend_agent.cache_clear()`.
    """
    return TutorAgentAdapter()
