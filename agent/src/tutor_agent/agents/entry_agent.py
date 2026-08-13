"""진입시점 결정 에이전트.

파이프라인 전체를 가동할 시점인지 가장 먼저 판단한다. 과도하게 자주 개입하지
않도록 보수적으로 판단하는 것이 기본 방향.
"""

from __future__ import annotations

from strands import Agent

from ..models import get_model
from ..schemas import EntryDecision, SessionContext

ROLE = "entry"

SYSTEM_PROMPT = """\
당신은 코딩 학습 튜터 시스템의 '진입시점 결정 에이전트'입니다.
학생의 세션 정보를 보고, 지금 이 시점에 튜터링 파이프라인
(상태 파악 → 지도 방법 결정 → 행동 → 평가)을 가동해야 하는지 결정하세요.

판단 기준 예시:
- 학생이 방금 코드를 실행/제출했거나, 일정 시간 이상 멈춰 있는가
- 마지막 개입 이후 충분한 시간/이벤트가 지났는가
- 세션이 이미 끝났거나 튜터링이 불필요한 상태인가

너무 자주 개입하면 학습을 방해합니다. 판단이 애매하면 개입하지 않는 쪽(False)을
선택하세요.
"""


def build_agent() -> Agent:
    return Agent(name="entry_decision_agent", model=get_model(ROLE), system_prompt=SYSTEM_PROMPT)


def decide(ctx: SessionContext, agent: Agent | None = None) -> EntryDecision:
    agent = agent or build_agent()
    prompt = f"다음 세션 상태를 보고 파이프라인 진입 여부를 결정하세요:\n\n{ctx.model_dump_json(indent=2)}"
    return agent.structured_output(EntryDecision, prompt)
