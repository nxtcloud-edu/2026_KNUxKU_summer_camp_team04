from __future__ import annotations

from app.agent.interface import AgentContext, AgentDecision, AgentReply
from app.enums import AgentAction

#: Agent가 구성되지 않았을 때 학생에게 보내는 문구.
#:
#: `decide()`는 침묵(WAIT)해도 되지만 `respond()`는 안 된다 -- 학생이 직접
#: 입력창에 뭔가를 써서 보낸 상황이라, 응답이 없으면 "튜터가 내 말을 씹었다"가
#: 된다. 그래서 여기서도 정답을 만들어내지는 않되, 말은 건다.
AGENT_UNAVAILABLE_REPLY = (
    "지금은 튜터가 답할 수 없어요. 잠시 뒤에 다시 물어봐 줄래요? "
    "그동안 코드를 한 줄씩 소리 내어 읽어보면 걸리는 지점이 보일 수 있어요."
)


class WaitAgent:
    """오늘 기본값.

    backend_plan §14의 폴백과 같은 모양이다: Agent를 안정적으로 돌릴 수 없으면
    정답을 만들어내지 않고 WAIT한다.
    """

    name = "wait"

    def decide(self, ctx: AgentContext) -> AgentDecision:
        return AgentDecision(
            state=ctx.process_status,
            concept=None,
            action=AgentAction.WAIT,
            reason="Agent backend가 구성되지 않아 학생의 추가 시도를 기다립니다.",
        )

    def respond(self, ctx: AgentContext, answer: str, question: str = "") -> AgentReply:
        return AgentReply(message=AGENT_UNAVAILABLE_REPLY, follow_up_needed=True)


class FakeAgent:
    """테스트 전용. 미리 정한 결정 하나를 매번 돌려준다 (judge/stub.py의 FakeJudge와 같은 패턴).

    `calls`에 받은 `AgentContext`를 순서대로 쌓아두므로, "트리거 안 되면 agent
    자체를 안 부른다"처럼 호출 여부/횟수를 검증하는 테스트에 쓸 수 있다.
    """

    name = "fake"

    def __init__(self, decision: AgentDecision, reply: AgentReply | None = None) -> None:
        self._decision = decision
        self._reply = reply
        self.calls: list[AgentContext] = []
        #: `respond()`가 받은 `(answer, question)` 순서대로. 특히 `question`을
        #: **서버가** 채웠는지(클라이언트 주장이 아닌지) 검증하는 데 쓴다.
        self.replies: list[tuple[str, str]] = []

    def decide(self, ctx: AgentContext) -> AgentDecision:
        self.calls.append(ctx)
        return self._decision

    def respond(self, ctx: AgentContext, answer: str, question: str = "") -> AgentReply:
        """받은 답변을 `replies`에 쌓고 미리 정한 응답을 돌려준다.

        `reply`를 생성자에서 안 받았으면 학생 답변을 되읊는 기본 응답을 만든다 --
        테스트가 "튜터 응답이 학생 답변을 봤는가"를 확인할 수 있게.
        """
        self.replies.append((answer, question))
        return self._reply or AgentReply(
            message=f"답변 확인했어요: {answer}", understanding="partial"
        )
