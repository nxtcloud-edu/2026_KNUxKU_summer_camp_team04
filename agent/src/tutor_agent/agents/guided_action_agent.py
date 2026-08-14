"""지도 방법 + 구체적 행동을 한 번의 LLM 호출로 결정하는 에이전트.

원래 `guidance_agent`(어떻게 가르칠지) + `action_agent`(뭘 할지)로 나뉘어
있던 두 LLM 호출을 합친 것이다. 왜 합쳤는지는 `schemas.GuidedAction`의
docstring과 `agent/README.md`의 "지연 시간" 절 참고. (합쳐진 뒤로 한 번도
쓰이지 않던 두 모듈은 삭제했다 — 스키마가 바뀌어 더 이상 동작하지도 않았고,
남겨두면 "지도 결정"과 "작문"의 새 경계를 흐린다.)

**이 에이전트는 학생에게 보낼 문장을 쓰지 않는다.** 예전에는 여기서
`message_draft`까지 만들었는데, 판단과 작문을 한 프롬프트에 섞은 대가로
계획용 어휘("지도 방식: ...")가 학생 화면에 새어 나갔다. 지금은 내부
지시문(`focus` / `talking_points` / `avoid` / `expects_student_reply`)만
만들고, 실제 문장은 `tutor_message_agent`가 그 지시문을 읽고 쓴다.
경위와 역할 분리 표는 `agents/tutor_message_agent.py` docstring 참고.
"""

from __future__ import annotations

from strands import Agent

from ..llm_runtime import structured_output
from ..models import get_model
from ..schemas import GuidedAction, SessionContext, StudentState

#: 두 역할이 합쳐졌으므로 role 문자열도 하나로 묶는다. `.env`에서
#: `MODEL_PROVIDER_GUIDED_ACTION`으로 개별 지정 가능 (`models.get_model` 참고).
ROLE = "guided_action"

SYSTEM_PROMPT = """\
당신은 코딩 학습 튜터 시스템의 '지도 방법 + 행동 결정 에이전트'입니다.
학생 상태 파악 결과를 받아, **어떻게 가르칠지에 대한 계획**과 시스템이 실행할
행동을 결정하세요.

중요: 당신은 **학생에게 보낼 문장을 쓰지 않습니다.** 당신의 출력은 다음
단계의 '응답 생성 에이전트'가 읽는 내부 지시문입니다. 그 에이전트가 실제
문장을 씁니다. 그러니 여기서는 "무엇을 어떻게 다룰지"만 정하세요.

- approach: 어떤 접근을 쓸지 (예: 소크라테스식 질문, 직접 힌트, 개념 재설명, 예시 제공)
- hint_level: nudge(가벼운 주의 환기) / hint(구체적 힌트) / explain(개념 설명) 중 선택
- focus: 이번 개입에서 다룰 대상 **하나** (예: "카운터 변수 초기화", "while 조건식").
  여러 개를 한 번에 다루면 학생이 무엇부터 할지 몰라 아무것도 못 합니다.
- talking_points: 메시지에 담아야 할 내용을 1~3개. 각 항목은 응답 생성
  에이전트에게 주는 지시문입니다 (예: "count = 0을 반복문 앞에 두어야 하는
  이유를 스스로 떠올리게 할 것").
- avoid: 이번에 알려주면 안 되는 것 (예: "완성된 for문 코드", "return 위치의 정답").
  학생이 스스로 밟을 다음 한 걸음을 남겨두기 위한 항목입니다.
- expects_student_reply: 학생의 답을 받아 이해도를 확인해야 하면 true.
  질문을 던지는 접근(소크라테스식 질문, 이해도 확인)이면 true로 두세요.
  학생이 답하면 그 답을 평가 에이전트가 채점하고 대화가 이어집니다.
- action_type: 다음 중 하나
  - send_message: 학생에게 메시지를 보낸다 (payload는 비워두세요 — 문장은
    응답 생성 에이전트가 만들고 시스템이 알아서 싣습니다)
  - highlight_code: 코드의 특정 줄/구간을 강조한다 (payload.line_start, payload.line_end)
  - show_example: 관련 예시를 보여준다 (payload.example)
  - no_op: 아무 행동도 하지 않는다 (드물게, 이미 충분히 개입했다고 판단될 때)
- payload: action_type에 맞는 필드를 담은 객체. send_message면 빈 객체.

정답을 그대로 알려주지 말고, 학생이 스스로 다음 단계를 밟도록 유도하는 것을
우선하세요.
"""

# 프롬프트에 있던 'paste_detected' 예외 절은 **일부러 지웠다.**
#
# 그 절은 approach/hint_level/action_type을 전부 값까지 지정하고 있어서 LLM에
# 남는 자유도가 문장 표현뿐이었는데, 그 한 줄 때문에 학생이 5~6초를 더 기다렸다.
# 지금은 `orchestrator`가 그 분기를 아예 여기로 보내지 않고 `comprehension_check`
# (LLM 없음)가 처리한다. 남겨두면 영영 발화하지 않을 지시가 프롬프트에 쌓여
# "이 분기는 어디서 처리되나"를 헷갈리게 만든다.


def build_agent() -> Agent:
    return Agent(name="guided_action_agent", model=get_model(ROLE), system_prompt=SYSTEM_PROMPT)


def plan(ctx: SessionContext, student_state: StudentState, agent: Agent | None = None) -> GuidedAction:
    agent = agent or build_agent()
    prompt = (
        "다음 세션 상태와 학생 상태 판단 결과를 보고, 지도 계획과 구체적인 행동을 "
        "결정하세요:\n\n"
        f"[세션 상태]\n{ctx.model_dump_json(indent=2)}\n\n"
        f"[학생 상태 판단]\n{student_state.model_dump_json(indent=2)}"
    )
    return structured_output(agent, GuidedAction, prompt)
