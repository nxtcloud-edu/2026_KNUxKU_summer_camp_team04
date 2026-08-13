"""문제 풀이 중 학생의 상태를 파악하는 에이전트.

코드/실행 기록/경과 시간 등을 보고 학생이 어떤 상태인지 요약하고,
지금이 개입시점인지(`should_intervene`)를 결정한다.
"""

from __future__ import annotations

from strands import Agent

from ..models import get_model
from ..schemas import SessionContext, StudentState
from ..tools.code_context import summarize_run_history

ROLE = "state"

SYSTEM_PROMPT = """\
당신은 코딩 학습 튜터 시스템의 '학생 상태 파악 에이전트'입니다.
학생의 코드, 실행/제출 기록, 경과·유휴 시간, 마지막 에러를 보고 다음을 판단하세요.

1. 학생이 현재 어떤 상태인지 (막힘, 순조로움, 개념 오해, 사소한 실수 등) 한두 문장으로 요약
2. 어려움을 겪고 있다는 신호(struggle_signals)를 구체적으로 나열
3. 지금 개입해야 하는지(should_intervene)와 긴급도(urgency)를 결정

같은 오류를 반복하거나 오래 멈춰 있으면 개입 신호로 보되, 학생이 정상적으로
사고 중인 짧은 정적은 개입하지 마세요.
"""


def build_agent() -> Agent:
    return Agent(
        name="student_state_agent",
        model=get_model(ROLE),
        system_prompt=SYSTEM_PROMPT,
        tools=[summarize_run_history],
    )


def assess(ctx: SessionContext, agent: Agent | None = None) -> StudentState:
    agent = agent or build_agent()
    prompt = f"다음 세션 상태를 보고 학생 상태와 개입시점을 판단하세요:\n\n{ctx.model_dump_json(indent=2)}"
    return agent.structured_output(StudentState, prompt)
