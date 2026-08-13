"""지도 방법 + 구체적 행동을 한 번의 LLM 호출로 함께 결정하는 에이전트.

`guidance_agent`(어떻게 가르칠지) + `action_agent`(뭘 할지)를 합친 것이다.
왜 합쳤는지, 무엇을 트레이드오프했는지는 `schemas.GuidedAction`의 docstring과
`agent/README.md`의 "지연 시간" 절 참고 — 요약하면 파이프라인의 순차 LLM
호출을 4번에서 2번으로 줄여 실측 지연 시간을 낮추기 위함이다.

`guidance_agent.py`/`action_agent.py`는 이제 `orchestrator.TutorPipeline`이
쓰지 않는다. 모듈 자체는 남겨뒀다 — 별도로 재사용하거나(예: 두 판단을 다시
분리해야 할 때), 이 병합이 되돌려질 경우를 위해서다.
"""

from __future__ import annotations

from strands import Agent

from ..models import get_model
from ..schemas import GuidedAction, SessionContext, StudentState

#: 두 역할이 합쳐졌으므로 role 문자열도 하나로 묶는다. `.env`에서
#: `MODEL_PROVIDER_GUIDED_ACTION`으로 개별 지정 가능 (`models.get_model` 참고).
ROLE = "guided_action"

SYSTEM_PROMPT = """\
당신은 코딩 학습 튜터 시스템의 '지도 방법 + 행동 결정 에이전트'입니다.
학생 상태 파악 결과를 받아, 어떻게 가르칠지와 그걸 위해 시스템이 실행할
구체적인 행동을 한 번에 결정하세요.

- approach: 어떤 접근을 쓸지 (예: 소크라테스식 질문, 직접 힌트, 개념 재설명, 예시 제공)
- hint_level: nudge(가벼운 주의 환기) / hint(구체적 힌트) / explain(개념 설명) 중 선택
- message_draft: 학생에게 보여줄 메시지 초안 (짧고 격려하는 톤)
- action_type: 다음 중 하나
  - send_message: 학생에게 메시지를 보낸다 (payload.message에 message_draft와 같은 내용을 넣으세요)
  - highlight_code: 코드의 특정 줄/구간을 강조한다 (payload.line_start, payload.line_end, payload.reason)
  - show_example: 관련 예시를 보여준다 (payload.example)
  - no_op: 아무 행동도 하지 않는다 (드물게, 이미 충분히 개입했다고 판단될 때)
- payload: action_type에 맞는 필드를 담은 객체

정답을 그대로 알려주지 말고, 학생이 스스로 다음 단계를 밟도록 유도하는 것을
우선하세요.

예외: struggle_signals에 'paste_detected'가 있으면 이것은 "막힘"이 아니라
외부에서 코드를 그대로 붙여넣었을 수 있다는 신호입니다. 이 경우 힌트를 주지
말고, approach를 "이해도 확인"으로 하고 hint_level은 nudge로 두되,
message_draft는 학생이 방금 작성/붙여넣은 코드가 왜 그렇게 동작하는지
스스로 생각해보도록 작성하세요 (예: "이 코드가 왜 이렇게 동작하는지
생각해볼래요?"). action_type은 send_message로 하세요.
"""


def build_agent() -> Agent:
    return Agent(name="guided_action_agent", model=get_model(ROLE), system_prompt=SYSTEM_PROMPT)


def plan(ctx: SessionContext, student_state: StudentState, agent: Agent | None = None) -> GuidedAction:
    agent = agent or build_agent()
    prompt = (
        "다음 세션 상태와 학생 상태 판단 결과를 보고, 지도 방법과 구체적인 행동을 "
        "한 번에 결정하세요:\n\n"
        f"[세션 상태]\n{ctx.model_dump_json(indent=2)}\n\n"
        f"[학생 상태 판단]\n{student_state.model_dump_json(indent=2)}"
    )
    return agent.structured_output(GuidedAction, prompt)
