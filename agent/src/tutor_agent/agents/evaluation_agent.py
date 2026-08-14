"""평가 에이전트 — **학생의 답변**을 평가한다.

무엇이 잘못되어 있었나
----------------------
이 에이전트는 원래 이런 프롬프트를 받았다:

    "방금 실행된 행동이 이 시점의 학생에게 적절했는지 평가하세요.
     effectiveness_score: 0.0(부적절)~1.0(매우 적절)"

즉 **AI가 자기 개입을 자기가 채점**했다. 실제 로그가 그 결과를 잘 보여준다:

    evaluation(백그라운드): score=0.85 follow_up_needed=True
    notes=매우 적절한 개입. 학생이 31분(1879초) 동안 정체되어 있고 ...
          구체적이고 단계별 안내를 제공. ... 격려 톤도 적절.

문제가 세 겹이었다:

1. **평가 대상이 틀렸다.** 튜터가 질문을 던졌으면 평가해야 하는 것은 학생의
   답이다. 학습 루프는 "질문 → 학생의 답 → 이해했는지 판단 → 다음 지도"로
   닫힌다. 자기 개입에 스스로 0.85를 주는 것은 그 루프의 어느 지점도 아니다.
2. **아무 데도 쓰이지 않았다.** 결과는 `log.info` 한 줄로 끝났고 (`service.py`),
   다음 판단에 피드백되지 않았다. 값이 무엇이든 시스템 동작은 같았다.
3. **자기 채점은 구조적으로 후한 점수가 나온다.** 개입을 만든 모델과 평가하는
   모델이 같은 컨텍스트를 보고 같은 기준을 쓰므로, 낮은 점수가 나올 이유가
   거의 없다.

지금 하는 일
------------
튜터가 던진 질문 + 학생이 실제로 쓴 답을 받아, **학생이 이해했는지**를 판단한다
(`schemas.AnswerEvaluation`). 이 결과는 로그로 끝나지 않고
`tutor_message_agent.write_follow_up()`의 입력이 되어 다음 응답을 바꾼다 —
이해했으면 다음 단계로, 절반만 이해했으면 빠진 조각만, 못 했으면 더 쉬운
질문으로. 즉 **평가가 실제로 지도를 바꾸는 경로에 연결되어 있다.**

이 에이전트의 출력은 전부 내부용이다. 학생은 여기서 나온 문장을 읽지 않는다
(`understanding="partial"`을 학생에게 보여주는 것은 도움이 아니다).
학생이 읽는 문장은 언제나 `tutor_message_agent`만 만든다.
"""

from __future__ import annotations

from strands import Agent

from ..llm_runtime import structured_output
from ..models import get_model
from ..prompt_context import student_situation
from ..schemas import AnswerEvaluation, SessionContext, StudentReply

ROLE = "evaluation"

SYSTEM_PROMPT = """\
당신은 코딩 학습 튜터 시스템의 '학생 답변 평가 에이전트'입니다.
튜터가 학생에게 질문을 했고, 학생이 답했습니다. **그 답변을 평가하세요.**

무엇을 판단하는가
- understanding: 학생이 질문의 대상 개념을 이해했는지
  - solid: 핵심을 정확히 짚었다. 표현이 어설퍼도 개념이 맞으면 solid다.
  - partial: 방향은 맞지만 일부가 빠졌거나 부정확하다.
  - none: 이해하지 못했다. 모른다고 답한 경우, 질문과 무관한 답, 찍은 답 포함.
- is_correct: 답변 내용이 사실로서 맞는지 (understanding과 별개로 판단)
- evidence: 그렇게 본 근거. 학생 답변의 어느 부분 때문인지 짧게.
- misconceptions: 답변에서 드러난 오개념. 없으면 빈 배열.
- follow_up_needed: 이 개념을 더 다뤄야 하는지. solid면 보통 false.
- next_focus: 다음 메시지에서 다뤄야 할 것 한 가지.

판단 기준
- **표현이 아니라 개념을 보세요.** 용어를 정확히 쓰지 못해도 원리를 이해했으면
  solid입니다. 초보 학습자에게 정확한 용어를 요구하면 전부 partial이 됩니다.
- 짧은 답을 불리하게 보지 마세요. "0으로요"는 초기값을 묻는 질문에 대한
  완전한 정답일 수 있습니다.
- 학생이 코드로 답했다면 그 코드가 질문에 대한 답으로 성립하는지 보세요.
- 학생이 "모르겠어요"라고 했으면 none이고, 이건 나쁜 신호가 아니라 정직한
  신호입니다. misconceptions는 비워두세요 (오개념이 아니라 미학습입니다).
- 학생이 질문 대신 다른 것을 물었다면(예: "그런데 리스트는 뭐예요?")
  understanding=none, follow_up_needed=true, next_focus에 학생이 물은 것을 넣으세요.

이 출력은 내부용입니다. 학생에게 보여줄 문장은 다른 에이전트가 만듭니다 —
여기서는 학생에게 할 말을 쓰지 말고 판단만 하세요.
"""


def build_agent() -> Agent:
    return Agent(name="evaluation_agent", model=get_model(ROLE), system_prompt=SYSTEM_PROMPT)


def evaluate_answer(
    ctx: SessionContext, reply: StudentReply, agent: Agent | None = None
) -> AnswerEvaluation:
    """학생 답변의 이해도를 평가한다.

    Args:
        ctx: 세션 스냅샷 (문제/코드 맥락 없이 답변만 보면 채점이 불가능하다.
            "0으로요"가 정답인지 아닌지는 질문과 코드를 봐야 안다).
        reply: 튜터가 던진 질문 + 학생의 답변.
        agent: 재사용할 strands Agent. None이면 새로 만든다 (프로세스 내내
            재사용하려면 `orchestrator.TutorPipeline`이 캐시한 것을 넘긴다).
    """
    agent = agent or build_agent()
    prompt = (
        "다음 학생의 답변을 평가하세요.\n\n"
        f"{student_situation(ctx)}\n\n"
        f"[튜터가 던진 질문]\n{reply.question or '(기록 없음 — 학생이 먼저 말을 걸었습니다)'}\n\n"
        f"[학생의 답변]\n{reply.answer}"
    )
    return structured_output(agent, AnswerEvaluation, prompt)
