"""state_agent.py의 규칙 기반 게이트 + assess() 분기 테스트.

`evaluate_entry_signals()`는 LLM을 전혀 쓰지 않는 순수 함수라 mock 없이 검증한다.
`assess()`는 게이트가 막거나(skip) 붙여넣기(paste)를 감지하면 LLM(Agent.
structured_output_async)을 호출하지 않고 바로 StudentState를 반환해야 하므로, 그
호출 여부를 MagicMock으로 검증한다. LLM 자체 품질은 검증 대상이 아니다.

아래 값들은 state_agent.py의 기본 임계값(환경변수 미설정 시)을 기준으로 한다:
IDLE=60s, CURSOR_STUCK=90s, CHURN=3, CONSECUTIVE_FAILURE=2, COOLDOWN=300s,
MIN_STRUGGLE_SIGNALS=2.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tutor_agent.agents import state_agent  # noqa: E402
from tutor_agent.schemas import SessionContext, StudentState  # noqa: E402


def _ctx(**overrides) -> SessionContext:
    defaults = dict(student_id="s1", problem_id="p1", code="pass")
    defaults.update(overrides)
    return SessionContext(**defaults)


# --- evaluate_entry_signals() (규칙만, LLM 없음) ------------------------------


def test_session_ended_always_skips() -> None:
    ctx = _ctx(session_ended=True, idle_seconds=999, edit_churn_count=99, paste_detected=True)
    gate = state_agent.evaluate_entry_signals(ctx)

    assert gate.should_enter is False
    assert gate.branch == "skip"


def test_cooldown_blocks_even_with_strong_signals() -> None:
    ctx = _ctx(seconds_since_last_intervention=30, idle_seconds=999, edit_churn_count=99)
    gate = state_agent.evaluate_entry_signals(ctx)

    assert gate.should_enter is False
    assert gate.branch == "skip"


def test_single_signal_is_not_enough() -> None:
    ctx = _ctx(idle_seconds=120)  # idle 신호 하나뿐
    gate = state_agent.evaluate_entry_signals(ctx)

    assert gate.should_enter is False
    assert gate.signals == ["idle"]


def test_two_signals_pass_the_struggle_gate() -> None:
    ctx = _ctx(idle_seconds=120, edit_churn_count=5)
    gate = state_agent.evaluate_entry_signals(ctx)

    assert gate.should_enter is True
    assert gate.branch == "struggle"
    assert set(gate.signals) == {"idle", "edit_churn"}


def test_non_identical_failures_do_not_count_as_repeated() -> None:
    ctx = _ctx(idle_seconds=120, run_history=["0/5 tests passed", "AssertionError: x", "TypeError: y"])
    gate = state_agent.evaluate_entry_signals(ctx)

    assert "repeated_failure" not in gate.signals
    assert gate.should_enter is False  # idle 신호 하나뿐이라 통과 못 함


def test_paste_detected_bypasses_signal_combination_requirement() -> None:
    ctx = _ctx(paste_detected=True)  # 다른 막힘 신호는 전혀 없음
    gate = state_agent.evaluate_entry_signals(ctx)

    assert gate.should_enter is True
    assert gate.branch == "paste"


# --- assess() (게이트 결과에 따라 LLM 호출 여부가 갈림) ------------------------


def test_assess_skips_llm_when_gate_blocks() -> None:
    mock_agent = MagicMock()
    ctx = _ctx(idle_seconds=120)  # 신호 1개뿐, 게이트 통과 못 함

    result = state_agent.assess(ctx, mock_agent)

    mock_agent.structured_output_async.assert_not_called()
    assert result.should_intervene is False
    assert result.entry_branch == "skip"


def test_assess_skips_llm_on_paste_and_routes_to_comprehension_check() -> None:
    mock_agent = MagicMock()
    ctx = _ctx(paste_detected=True)

    result = state_agent.assess(ctx, mock_agent)

    mock_agent.structured_output_async.assert_not_called()
    assert result.should_intervene is True
    assert result.entry_branch == "paste"
    assert result.struggle_signals == ["paste_detected"]


def test_assess_calls_llm_when_gate_passes_with_struggle_signals() -> None:
    mock_agent = MagicMock()
    mock_agent.structured_output_async.return_value = StudentState(
        state_summary="같은 오류 반복", should_intervene=True, urgency="high"
    )
    ctx = _ctx(idle_seconds=120, edit_churn_count=5)  # 신호 2개, 게이트 통과

    result = state_agent.assess(ctx, mock_agent)

    mock_agent.structured_output_async.assert_called_once()
    assert result.entry_branch == "struggle"
    assert result.should_intervene is True


# --- skip_gate=True (backend Monitor가 이미 호출 시점을 판단한 경우) --------------


def test_skip_gate_calls_llm_even_without_any_local_signal() -> None:
    """게이트라면 막았을 신호 0개짜리 ctx도, skip_gate=True면 곧장 LLM으로 간다."""
    mock_agent = MagicMock()
    mock_agent.structured_output_async.return_value = StudentState(
        state_summary="Monitor가 STUCK으로 판단", should_intervene=True, urgency="high"
    )
    ctx = _ctx()  # idle/churn/cursor_stuck 전부 0 -- 일반 게이트라면 스킵됐을 상태

    result = state_agent.assess(ctx, mock_agent, skip_gate=True)

    mock_agent.structured_output_async.assert_called_once()
    assert result.entry_branch == "struggle"


def test_skip_gate_ignores_cooldown_and_session_ended() -> None:
    mock_agent = MagicMock()
    mock_agent.structured_output_async.return_value = StudentState(
        state_summary="Monitor가 판단", should_intervene=True
    )
    ctx = _ctx(session_ended=True, seconds_since_last_intervention=1)

    result = state_agent.assess(ctx, mock_agent, skip_gate=True)

    mock_agent.structured_output_async.assert_called_once()
    assert result.should_intervene is True


def test_skip_gate_still_routes_paste_to_comprehension_check_without_llm() -> None:
    mock_agent = MagicMock()
    ctx = _ctx(paste_detected=True)

    result = state_agent.assess(ctx, mock_agent, skip_gate=True)

    mock_agent.structured_output_async.assert_not_called()
    assert result.entry_branch == "paste"


# --- help_requested (SOS) ----------------------------------------------------
#
# `paste_detected`와 달리 이 분기는 should_intervene을 LLM에게 다시 묻지
# 않는다 — "학생이 직접 요청했다"가 이미 "지금 개입해야 한다"는 결론이다.
# (배경: backend `app/agent/router.py`의 SOS 라우트가 body.trigger를 실제로
# 쓰기 전까지, 신호가 적은 세션에서 LLM이 WAIT을 골라 SOS 버튼이 눌러도
# 반응 없는 것처럼 보이는 문제가 실제로 있었다.)


def test_help_requested_bypasses_llm_and_forces_intervention() -> None:
    """LLM을 부르지 않고 should_intervene=True로 고정한다."""
    mock_agent = MagicMock()
    ctx = _ctx(help_requested=True)

    result = state_agent.assess(ctx, mock_agent, skip_gate=True)

    mock_agent.structured_output.assert_not_called()
    assert result.should_intervene is True
    assert result.entry_branch == "help_requested"
    assert result.urgency == "high"


def test_help_requested_ignores_the_struggle_gate_too() -> None:
    """skip_gate=False(게이트 경로)에서도 동일하게 우선한다 — 신호가 하나도
    없어도(=게이트라면 skip으로 떨어질 상황) 개입을 강제해야 한다."""
    mock_agent = MagicMock()
    ctx = _ctx(help_requested=True)  # idle/churn 등 다른 신호 전혀 없음

    result = state_agent.assess(ctx, mock_agent, skip_gate=False)

    mock_agent.structured_output.assert_not_called()
    assert result.should_intervene is True
    assert result.entry_branch == "help_requested"


def test_help_requested_takes_priority_over_paste_detected() -> None:
    """드물게 둘 다 참이면(붙여넣은 직후 바로 SOS) 명시적 요청이 우선한다."""
    mock_agent = MagicMock()
    ctx = _ctx(help_requested=True, paste_detected=True)

    result = state_agent.assess(ctx, mock_agent, skip_gate=True)

    assert result.entry_branch == "help_requested"
