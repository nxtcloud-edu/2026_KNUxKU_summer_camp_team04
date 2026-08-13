"""문제 풀이 중 학생의 상태를 파악하는 에이전트.

**규칙 기반 진입 게이트(LLM 없음, 공짜)를 먼저 통과한 경우에만** LLM을 호출해
코드/실행 기록/경과 시간 등을 보고 학생이 어떤 상태인지 요약하고, 지금이
개입시점인지(`should_intervene`)를 결정한다.

과거에는 별도의 EntryAgent(LLM)가 "지금 뭔가 해야 하나?"를 먼저 묻고, 통과하면
이 StateAgent가 사실상 같은 질문을 또 LLM으로 물었다 — 체크 한 번에 LLM 호출이
2번 들었다는 뜻이다. EntryAgent의 판단 기준("마지막 개입 이후 충분한 시간이
지났는가", "세션이 끝났는가")을 계산할 필드 자체가 SessionContext에 없어 실제로는
판단이 불가능하기도 했다. 그래서 진입 판단을 이 모듈의 규칙 기반 게이트로 흡수했다:
게이트를 통과한 경우에만 LLM을 호출하므로, 체크 주기마다 대부분 "아직 개입
아님"으로 끝나는 실제 사용 패턴에서 LLM 호출을 크게 절감한다.

붙여넣기(`paste_detected`)는 "막힘" 신호와 성격이 달라(외부에서 답을 그대로
복사했을 수도 있음), 다른 신호와 조합해 판단하지 않고 게이트에서 그 자체로
`paste` 분기로 통과시킨다. 이 경우도 "지금 막혔는가"를 LLM에게 묻는 게 아니라
바로 "이해도 확인" 상태로 처리하므로 LLM을 호출하지 않는다 (실제 힌트 문구는
다음 단계인 GuidanceAgent가 만든다).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Literal

from strands import Agent

from ..models import get_model
from ..schemas import SessionContext, StudentState
from ..tools.code_context import summarize_run_history

ROLE = "state"

SYSTEM_PROMPT = """\
당신은 코딩 학습 튜터 시스템의 '학생 상태 파악 에이전트'입니다.
지금 이 시점은 이미 규칙 기반 게이트를 통과해 "막힘 신호가 여러 개 겹쳤다"고
판단된 상태입니다. 학생의 코드, 실행/제출 기록, 경과·유휴 시간, 마지막 에러를
보고 다음을 판단하세요.

1. 학생이 현재 어떤 상태인지 (막힘, 순조로움, 개념 오해, 사소한 실수 등) 한두 문장으로 요약
2. 어려움을 겪고 있다는 신호(struggle_signals)를 구체적으로 나열
3. 지금 개입해야 하는지(should_intervene)와 긴급도(urgency)를 결정

같은 오류를 반복하거나 오래 멈춰 있으면 개입 신호로 보되, 학생이 정상적으로
사고 중인 짧은 정적은 개입하지 마세요. 규칙 게이트를 통과했다고 해서 무조건
개입해야 하는 것은 아닙니다 — 실제로는 순조로운 상태일 수도 있습니다.
"""


# --- 규칙 기반 진입 게이트 (LLM 없음) ----------------------------------------
#
# 신호 하나만으로 트리거하면 오탐이 많다 (예: 유휴 60초는 그냥 문제를 읽는
# 중일 수도 있음). 아래 신호 중 2개 이상이 겹칠 때만 LLM 평가로 넘어간다.
# 임계값은 모두 환경변수로 조정할 수 있다 (.env.example 참고).


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value else default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default


#: 키 입력 없이 이 정도 멈추면 유휴 신호 (초). 스펙 권장 범위: 60~90초.
IDLE_THRESHOLD_SECONDS = _env_float("STATE_GATE_IDLE_THRESHOLD_SECONDS", 60.0)
#: 커서가 같은 함수/블록을 벗어나지 못한 시간 (초). 줄 단위보다 블록 단위가 정확.
CURSOR_STUCK_THRESHOLD_SECONDS = _env_float("STATE_GATE_CURSOR_STUCK_THRESHOLD_SECONDS", 90.0)
#: 같은 부분을 여러 번 작성→삭제(churn)한 횟수 임계값.
EDIT_CHURN_THRESHOLD = _env_int("STATE_GATE_EDIT_CHURN_THRESHOLD", 3)
#: Run/Submit이 연속으로 같은 실패 결과를 낸 횟수 임계값. 스펙 권장 범위: 2~3회.
CONSECUTIVE_FAILURE_THRESHOLD = _env_int("STATE_GATE_CONSECUTIVE_FAILURE_THRESHOLD", 2)
#: 마지막 개입 이후 이 시간(초) 안이면 너무 자주 개입하지 않도록 스킵한다.
INTERVENTION_COOLDOWN_SECONDS = _env_float("STATE_GATE_INTERVENTION_COOLDOWN_SECONDS", 300.0)
#: "struggle" 분기로 LLM까지 넘기는 데 필요한 최소 신호 개수. 오탐 방지를 위해 2 이상 권장.
MIN_STRUGGLE_SIGNALS = _env_int("STATE_GATE_MIN_STRUGGLE_SIGNALS", 2)

_TEST_RESULT_RE = re.compile(r"(\d+)\s*/\s*(\d+)")


def _is_failure(entry: str) -> bool:
    """실행/제출 로그 한 줄이 실패였는지 판단한다.

    `run_history`는 자유 텍스트 요약(예: "0/5 tests passed")이라 완벽한 파싱은
    불가능하다. "N/M" 패턴이 있으면 N==M일 때만 성공으로 보고, 패턴이 없으면
    "error"/"fail" 류 키워드로 판단한다 (최선 노력 휴리스틱).
    """
    match = _TEST_RESULT_RE.search(entry)
    if match:
        passed, total = int(match.group(1)), int(match.group(2))
        return passed < total
    lowered = entry.lower()
    return "error" in lowered or "fail" in lowered


def _consecutive_failures(run_history: list[str]) -> int:
    """가장 최근 기록부터 세어, 연속으로 같은 실패 결과가 반복된 횟수를 센다."""
    streak = 0
    last_failed_entry: str | None = None
    for entry in reversed(run_history):
        if not _is_failure(entry):
            break
        if last_failed_entry is not None and entry != last_failed_entry:
            # 실패이긴 하지만 결과가 달라졌다면(예: 에러 종류가 바뀜) 새로운 시도로 본다.
            break
        streak += 1
        last_failed_entry = entry
    return streak


def _collect_struggle_signals(ctx: SessionContext) -> list[str]:
    signals: list[str] = []
    if ctx.idle_seconds >= IDLE_THRESHOLD_SECONDS:
        signals.append("idle")
    if ctx.cursor_stuck_seconds >= CURSOR_STUCK_THRESHOLD_SECONDS:
        signals.append("cursor_stuck")
    if ctx.edit_churn_count >= EDIT_CHURN_THRESHOLD:
        signals.append("edit_churn")
    if _consecutive_failures(ctx.run_history) >= CONSECUTIVE_FAILURE_THRESHOLD:
        signals.append("repeated_failure")
    return signals


@dataclass
class _EntryGate:
    """규칙 기반 게이트의 내부 판단 결과. LLM 호출 여부를 결정하는 데만 쓰인다."""

    should_enter: bool
    reason: str
    branch: Literal["struggle", "paste", "skip"] = "skip"
    signals: list[str] = field(default_factory=list)


def evaluate_entry_signals(ctx: SessionContext) -> _EntryGate:
    """SessionContext만 보고 LLM 호출 여부를 규칙으로 결정한다 (LLM 미사용)."""
    if ctx.session_ended:
        return _EntryGate(should_enter=False, reason="세션이 이미 종료되었습니다.", branch="skip")

    if (
        ctx.seconds_since_last_intervention is not None
        and ctx.seconds_since_last_intervention < INTERVENTION_COOLDOWN_SECONDS
    ):
        return _EntryGate(
            should_enter=False,
            reason=(
                f"마지막 개입 후 {ctx.seconds_since_last_intervention:.0f}초 밖에 지나지 않아 "
                f"쿨다운({INTERVENTION_COOLDOWN_SECONDS:.0f}초) 중입니다."
            ),
            branch="skip",
        )

    # 붙여넣기는 "막힘" 신호와 성격이 달라 다른 신호와 조합할 필요 없이 그 자체로 통과시킨다.
    if ctx.paste_detected:
        return _EntryGate(
            should_enter=True,
            reason="붙여넣기가 감지되어 이해도 확인 분기로 진입합니다.",
            branch="paste",
            signals=["paste_detected"],
        )

    signals = _collect_struggle_signals(ctx)
    if len(signals) >= MIN_STRUGGLE_SIGNALS:
        return _EntryGate(
            should_enter=True,
            reason=f"막힘 신호 {len(signals)}개가 겹쳐 감지되었습니다: {', '.join(signals)}.",
            branch="struggle",
            signals=signals,
        )

    return _EntryGate(
        should_enter=False,
        reason=f"막힘 신호가 {len(signals)}개뿐이라({', '.join(signals) or '없음'}) 개입하지 않습니다.",
        branch="skip",
        signals=signals,
    )


def _comprehension_check_state() -> StudentState:
    """붙여넣기 분기 전용 StudentState. LLM 호출 없이 규칙으로 구성한다."""
    return StudentState(
        state_summary="붙여넣기가 감지되어, 막힘이 아닌 이해도 확인이 필요한 상황입니다.",
        struggle_signals=["paste_detected"],
        should_intervene=True,
        urgency="medium",
        entry_branch="paste",
    )


# --- Agent 배선 ---------------------------------------------------------------


def build_agent() -> Agent:
    return Agent(
        name="student_state_agent",
        model=get_model(ROLE),
        system_prompt=SYSTEM_PROMPT,
        tools=[summarize_run_history],
    )


def _assess_via_llm(ctx: SessionContext, agent: Agent | None, signals: list[str]) -> StudentState:
    agent = agent or build_agent()
    signal_note = ", ".join(signals) if signals else "(backend Monitor가 이미 개입 시점으로 판단함)"
    prompt = (
        f"다음 신호로 LLM 평가로 넘어왔습니다: {signal_note}.\n\n"
        f"다음 세션 상태를 보고 학생 상태와 개입시점을 판단하세요:\n\n{ctx.model_dump_json(indent=2)}"
    )
    state = agent.structured_output(StudentState, prompt)
    state.entry_branch = "struggle"
    return state


def assess(ctx: SessionContext, agent: Agent | None = None, *, skip_gate: bool = False) -> StudentState:
    """규칙 게이트를 통과한 경우에만 LLM을 호출해 학생 상태를 판단한다.

    Args:
        skip_gate: True면 유휴/churn/쿨다운 등 이 모듈 자체의 규칙 게이트를 건너뛰고
            곧장 LLM 평가로 간다 (붙여넣기 분기는 그대로 확인한다). backend
            Monitor가 이미 독립적인 규칙으로 "지금 Agent를 부를 시점"이라고
            판단해 호출한 경우(`backend_adapter.TutorAgentAdapter`)에 쓴다 — 서로 다른
            기준으로 만든 신호(예: backend의 `same_region_edit_count` vs 이 모듈의
            `edit_churn_count`)가 우연히 이 모듈의 임계값을 못 넘겨 Monitor의
            판단을 무시하고 조용히 WAIT 처리해버리는 걸 막기 위해서다.
    """
    if skip_gate:
        if ctx.paste_detected:
            return _comprehension_check_state()
        return _assess_via_llm(ctx, agent, signals=[])

    gate = evaluate_entry_signals(ctx)

    if not gate.should_enter:
        return StudentState(
            state_summary=gate.reason,
            struggle_signals=gate.signals,
            should_intervene=False,
            entry_branch="skip",
        )

    if gate.branch == "paste":
        return _comprehension_check_state()

    return _assess_via_llm(ctx, agent, signals=gate.signals)
