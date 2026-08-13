"""backend 어댑터 테스트. LLM/네트워크/backend import 전부 없음.

- 파이프라인은 MagicMock으로 주입한다 (`TutorAgentAdapter(pipeline=...)`) — 그래서
  strands Agent도, API 키도, 실제 LLM 호출도 필요 없다.
- backend 계약 미러(enum 값/필드명)는 backend 소스를 **텍스트로 파싱해서**
  비교한다 (`ast` 사용, import 없음). backend가 계약을 바꾸면 이 테스트가 깨져서
  어댑터 드리프트를 알려준다. backend 폴더가 없는 환경에서는 skip한다.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tutor_agent.backend_adapter import (  # noqa: E402
    ACTION_TYPE_TO_AGENT_ACTION,
    AgentAction,
    AgentContext,
    AgentDecision,
    TutorAgentAdapter,
    get_backend_agent,
    to_agent_decision,
    to_session_context,
)
from tutor_agent.orchestrator import PipelineResult  # noqa: E402
from tutor_agent.schemas import (  # noqa: E402
    ActionPlan,
    Evaluation,
    GuidancePlan,
    SessionContext,
    StudentState,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_APP = REPO_ROOT / "backend" / "app"


# --- 픽스처 ------------------------------------------------------------------


def _backend_ctx(**overrides) -> AgentContext:
    """backend가 넘겨줄 AgentContext와 같은 모양(미러 dataclass)."""
    data = {
        "session_id": "sess-1",
        "problem": {
            "problem_id": "func_sum_list",
            "title": "리스트 합",
            "concepts": ["loop", "accumulator"],
            "description_summary": "정수 리스트의 합을 구하세요.",
            "function_name": "sum_list",
        },
        "current_code": "def sum_list(xs):\n    pass\n",
        "current_code_version": 7,
        "judge_result": {
            "mode": "run",
            "status": "WRONG_ANSWER",
            "passed": 1,
            "total": 4,
            "failed_categories": ["empty", "negative"],
        },
        "recent_trace": ["loop 영역 수정 ×3", "실행: 1/4 통과"],
        "features": {
            "elapsed_seconds": 420,
            "seconds_without_progress": 190,
            "same_region_edit_count": 4,
            "recent_error_types": ["RUNTIME_ERROR"],
            "same_result_count": 3,
        },
        "process_status": "STUCK",
        "trigger": "REPEATED_FAILURE",
        "evidence": ["같은 결과 3회", "loop 영역 4회 수정"],
        "previous_interventions": [{"seq": 11, "action": "HINT", "reason": "이전 힌트"}],
    }
    data.update(overrides)
    return AgentContext(**data)


def _intervening_result() -> PipelineResult:
    return PipelineResult(
        student_state=StudentState(
            state_summary="같은 오류를 반복하고 있습니다.",
            struggle_signals=["repeated_failure"],
            should_intervene=True,
            urgency="high",
            entry_branch="struggle",
        ),
        guidance_plan=GuidancePlan(
            approach="소크라테스식 질문",
            hint_level="hint",
            message_draft="합을 담는 변수는 언제 초기화해야 할까요?",
        ),
        action_plan=ActionPlan(action_type="send_message", payload={"line_start": 2}),
        evaluation=Evaluation(
            effectiveness_score=0.8, notes="적절함", follow_up_needed=False
        ),
    )


# --- AgentContext → SessionContext ------------------------------------------


def test_to_session_context_maps_backend_fields() -> None:
    ctx = to_session_context(_backend_ctx())

    assert isinstance(ctx, SessionContext)
    assert ctx.student_id == "sess-1"  # backend ctx에 학생 id가 없어 세션 id를 쓴다
    assert ctx.problem_id == "func_sum_list"
    assert ctx.code.startswith("def sum_list")
    assert ctx.elapsed_seconds == 420.0
    assert ctx.idle_seconds == 190.0  # seconds_without_progress
    assert ctx.edit_churn_count == 4  # same_region_edit_count
    assert ctx.cursor_stuck_seconds == 0.0  # backend는 커서를 추적하지 않는다
    assert ctx.last_error == "RUNTIME_ERROR"
    assert ctx.session_ended is False
    assert ctx.seconds_since_last_intervention is None  # 쿨다운은 backend 소관


def test_run_history_keeps_parsable_score_format() -> None:
    """`state_agent._is_failure()`가 읽는 "N/M" 포맷이 유지되어야 한다."""
    from tutor_agent.agents import state_agent

    ctx = to_session_context(_backend_ctx())

    assert ctx.run_history[:2] == ["loop 영역 수정 ×3", "실행: 1/4 통과"]
    judge_line = ctx.run_history[-1]
    assert "1/4 tests passed" in judge_line
    assert "empty" in judge_line  # failed_categories도 실려 있다
    assert state_agent._is_failure(judge_line) is True


def test_backend_signals_carry_trigger_and_evidence_to_the_prompt() -> None:
    ctx = to_session_context(_backend_ctx())

    assert ctx.backend_signals["process_status"] == "STUCK"
    assert ctx.backend_signals["trigger"] == "REPEATED_FAILURE"
    assert ctx.backend_signals["evidence"] == ["같은 결과 3회", "loop 영역 4회 수정"]
    assert ctx.backend_signals["problem"]["title"] == "리스트 합"
    assert ctx.backend_signals["current_code_version"] == 7
    assert ctx.backend_signals["previous_interventions"][0]["action"] == "HINT"
    # 프롬프트는 SessionContext를 그대로 직렬화하므로 LLM까지 전달된다.
    assert "REPEATED_FAILURE" in ctx.model_dump_json()


def test_understanding_uncertain_becomes_comprehension_check_branch() -> None:
    """backend R2(대규모 변경 직후 통과)는 agent의 paste 분기와 같은 의미다."""
    from_trigger = to_session_context(
        _backend_ctx(process_status="UNDERSTANDING_UNCERTAIN", trigger="UNDERSTANDING_UNCERTAIN")
    )
    from_status_only = to_session_context(
        _backend_ctx(process_status="UNDERSTANDING_UNCERTAIN", trigger=None)
    )

    assert from_trigger.paste_detected is True
    assert from_status_only.paste_detected is True
    assert to_session_context(_backend_ctx()).paste_detected is False  # STUCK은 아니다


def test_to_session_context_accepts_dict_and_partial_context() -> None:
    """dict도, 필드가 빠진 컨텍스트도 예외 없이 변환된다."""
    ctx = to_session_context({"session_id": "sess-2"})

    assert ctx.student_id == "sess-2"
    assert ctx.problem_id == ""
    assert ctx.code == ""
    assert ctx.run_history == []
    assert ctx.last_error is None


def test_to_session_context_survives_garbage_field_types() -> None:
    ctx = to_session_context(
        {
            "session_id": 12345,  # str이 아님
            "problem": "not-a-dict",
            "features": {"elapsed_seconds": "??", "same_region_edit_count": None},
            "recent_trace": "한 줄짜리 문자열",
            "judge_result": "dict가 아님",
        }
    )

    assert ctx.student_id == "12345"
    assert ctx.problem_id == ""
    assert ctx.elapsed_seconds == 0.0
    assert ctx.edit_churn_count == 0
    assert ctx.run_history == ["한 줄짜리 문자열"]


# --- PipelineResult → AgentDecision -----------------------------------------


def test_decision_uses_backend_vocabulary_for_state_and_concept() -> None:
    decision = to_agent_decision(_intervening_result(), _backend_ctx())

    assert isinstance(decision, AgentDecision)
    # state는 backend ProcessStatus 어휘를 그대로 돌려준다 (WaitAgent와 동일).
    assert decision.state == "STUCK"
    assert decision.concept == "loop"
    assert decision.action is AgentAction.HINT
    assert decision.action.value == "HINT"  # backend 라우터가 읽는 값


def test_hint_activity_carries_message_and_agent_vocabulary() -> None:
    decision = to_agent_decision(_intervening_result(), _backend_ctx())

    assert decision.activity is not None
    assert decision.activity["message"] == "합을 담는 변수는 언제 초기화해야 할까요?"
    assert decision.activity["hint_level"] == "hint"
    assert decision.activity["action_type"] == "send_message"  # 원본 어휘 보존
    assert decision.activity["payload"] == {"line_start": 2}
    assert decision.activity["urgency"] == "high"
    assert decision.activity["evaluation"]["effectiveness_score"] == 0.8
    assert "소크라테스식 질문" in decision.reason


@pytest.mark.parametrize(
    ("action_type", "expected"),
    [
        ("no_op", AgentAction.WAIT),
        ("send_message", AgentAction.HINT),
        ("highlight_code", AgentAction.HINT),
        ("show_example", AgentAction.HINT),
        ("어휘에 없는 값", AgentAction.HINT),  # 미지의 action_type도 HINT로 수렴
    ],
)
def test_action_type_mapping(action_type: str, expected: AgentAction) -> None:
    result = _intervening_result()
    result.action_plan = ActionPlan.model_construct(action_type=action_type, payload={})

    decision = to_agent_decision(result, _backend_ctx())

    assert decision.action is expected


def test_action_mapping_table_covers_every_action_plan_vocabulary() -> None:
    """`ActionPlan.action_type` Literal에 값이 추가되면 표도 갱신해야 한다."""
    literal_values = set(ActionPlan.model_fields["action_type"].annotation.__args__)

    assert literal_values == set(ACTION_TYPE_TO_AGENT_ACTION)


def test_no_op_yields_wait_without_activity() -> None:
    result = _intervening_result()
    result.action_plan = ActionPlan(action_type="no_op", payload={})

    decision = to_agent_decision(result, _backend_ctx())

    assert decision.action is AgentAction.WAIT
    assert decision.activity is None


def test_no_intervention_yields_wait() -> None:
    result = PipelineResult(
        student_state=StudentState(
            state_summary="순조롭게 진행 중입니다.",
            should_intervene=False,
            entry_branch="struggle",
        )
    )

    decision = to_agent_decision(result, _backend_ctx())

    assert decision.action is AgentAction.WAIT
    assert decision.reason == "순조롭게 진행 중입니다."
    assert decision.activity is None


def test_intervene_without_action_plan_yields_wait() -> None:
    """파이프라인이 중간에 멈춘 비정상 결과도 WAIT으로 안전하게 떨어진다."""
    result = PipelineResult(
        student_state=StudentState(
            state_summary="개입 필요", should_intervene=True, entry_branch="struggle"
        )
    )

    decision = to_agent_decision(result, _backend_ctx())

    assert decision.action is AgentAction.WAIT


# --- TutorAgentAdapter.decide() ---------------------------------------------


def test_adapter_satisfies_agent_protocol_shape() -> None:
    adapter = get_backend_agent()

    assert adapter.name == "tutor_agent"
    assert callable(adapter.decide)


def test_get_backend_agent_is_a_singleton() -> None:
    """backend `get_agent()`는 요청마다 평가된다. 매번 새 어댑터를 만들면
    인스턴스에 캐시된 TutorPipeline(strands Agent 4개)도 매번 재생성된다."""
    assert get_backend_agent() is get_backend_agent()

    get_backend_agent.cache_clear()  # 테스트용 탈출구
    assert get_backend_agent() is get_backend_agent()


def test_adapter_runs_pipeline_with_skip_gate_true() -> None:
    """backend Monitor가 이미 개입 시점을 판단했으므로 agent 게이트는 건너뛴다."""
    pipeline = MagicMock()
    pipeline.run.return_value = _intervening_result()

    decision = TutorAgentAdapter(pipeline=pipeline).decide(_backend_ctx())

    pipeline.run.assert_called_once()
    assert pipeline.run.call_args.kwargs == {"skip_gate": True}
    assert isinstance(pipeline.run.call_args.args[0], SessionContext)
    assert decision.action is AgentAction.HINT


def test_adapter_can_opt_into_the_local_gate() -> None:
    pipeline = MagicMock()
    pipeline.run.return_value = _intervening_result()

    TutorAgentAdapter(pipeline=pipeline, skip_gate=False).decide(_backend_ctx())

    assert pipeline.run.call_args.kwargs == {"skip_gate": False}


def test_adapter_falls_back_to_wait_when_pipeline_raises() -> None:
    """LLM 실패/네트워크 오류가 채점 응답을 깨뜨리지 않아야 한다."""
    pipeline = MagicMock()
    pipeline.run.side_effect = RuntimeError("Anthropic API 500")

    decision = TutorAgentAdapter(pipeline=pipeline).decide(_backend_ctx())

    assert decision.action is AgentAction.WAIT
    assert decision.state == "STUCK"  # 그래도 backend 어휘는 유지
    assert decision.activity is None
    assert decision.reason


def test_adapter_falls_back_to_wait_when_result_is_garbage() -> None:
    pipeline = MagicMock()
    pipeline.run.return_value = "PipelineResult가 아님"

    decision = TutorAgentAdapter(pipeline=pipeline).decide(_backend_ctx())

    assert decision.action is AgentAction.WAIT


def test_adapter_falls_back_to_wait_when_context_is_unusable() -> None:
    """ctx 필드 접근 자체가 터지는 경우에도 WAIT으로 떨어진다 (파이프라인 미호출)."""

    class ExplodingContext:
        def __getattr__(self, name: str):
            raise RuntimeError(f"필드 접근 실패: {name}")

    pipeline = MagicMock()
    pipeline.run.return_value = _intervening_result()

    decision = TutorAgentAdapter(pipeline=pipeline).decide(ExplodingContext())

    assert decision.action is AgentAction.WAIT
    assert decision.state == ""
    pipeline.run.assert_not_called()


def test_adapter_tolerates_none_context() -> None:
    """ctx가 None이어도 (필드 없는 컨텍스트와 동일하게) 예외 없이 결정을 낸다."""
    pipeline = MagicMock()
    pipeline.run.return_value = PipelineResult(
        student_state=StudentState(state_summary="", should_intervene=False)
    )

    decision = TutorAgentAdapter(pipeline=pipeline).decide(None)

    assert decision.action is AgentAction.WAIT


def test_adapter_falls_back_to_wait_when_pipeline_cannot_be_built(monkeypatch) -> None:
    """strands 미설치/키 누락 등으로 TutorPipeline 생성이 실패하는 경우."""
    adapter = TutorAgentAdapter()
    monkeypatch.setattr(
        adapter, "_get_pipeline", MagicMock(side_effect=ImportError("No module named 'strands'"))
    )

    decision = adapter.decide(_backend_ctx())

    assert decision.action is AgentAction.WAIT


def test_adapter_never_raises_on_empty_context() -> None:
    pipeline = MagicMock()
    pipeline.run.return_value = PipelineResult(
        student_state=StudentState(state_summary="", should_intervene=False)
    )

    decision = TutorAgentAdapter(pipeline=pipeline).decide({})

    assert decision.action is AgentAction.WAIT
    assert decision.state == ""


# --- backend 계약 미러 드리프트 검사 (backend를 import하지 않고 소스만 읽는다) ----


def _parse_backend(relative: str) -> ast.Module:
    path = BACKEND_APP / relative
    if not path.exists():
        pytest.skip(f"backend 소스가 없는 환경입니다: {path}")
    return ast.parse(path.read_text(encoding="utf-8"))


def _class_def(tree: ast.Module, name: str) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    pytest.fail(f"backend 소스에서 class {name}을 찾지 못했습니다.")


def test_agent_action_mirror_matches_backend_enum() -> None:
    cls = _class_def(_parse_backend("enums.py"), "AgentAction")
    backend_members = {
        node.targets[0].id: node.value.value
        for node in cls.body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
    }

    assert backend_members == {a.name: a.value for a in AgentAction}


def test_agent_context_mirror_matches_backend_fields() -> None:
    cls = _class_def(_parse_backend("agent/interface.py"), "AgentContext")
    backend_fields = [
        node.target.id for node in cls.body if isinstance(node, ast.AnnAssign)
    ]

    assert backend_fields == [f.name for f in AgentContext.__dataclass_fields__.values()]


def test_agent_decision_mirror_matches_backend_fields() -> None:
    cls = _class_def(_parse_backend("agent/interface.py"), "AgentDecision")
    backend_fields = [
        node.target.id for node in cls.body if isinstance(node, ast.AnnAssign)
    ]

    assert backend_fields == [f.name for f in AgentDecision.__dataclass_fields__.values()]
