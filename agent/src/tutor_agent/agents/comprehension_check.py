"""붙여넣기(이해도 확인) 분기의 질문을 **LLM 없이** 만드는 모듈.

왜 LLM을 안 쓰는가
------------------
이 분기에서 LLM에게 남아 있던 자유도는 사실상 문장 표현 하나뿐이었다.
`guided_action_agent`의 시스템 프롬프트가 이미 approach는 "이해도 확인",
hint_level은 `nudge`, action_type은 `send_message`로 못박아 두었기 때문이다.
그 한 줄을 받으려고 학생을 5~6초 더 기다리게 했다 — 붙여넣기부터 화면 표시까지
실측 ~16초 중 LLM이 5~6초였다.

`state_agent`는 이 분기를 이미 LLM 없이 판정한다(`_comprehension_check_state`).
그런데 바로 뒤에 붙은 `guided_action_agent`가 LLM을 부르는 바람에, "붙여넣기는
규칙만으로 처리한다"는 설계 의도가 파이프라인 전체로는 지켜지지 않고 있었다.
이 모듈이 그 마지막 구멍을 막는다.

무엇으로 대신하는가
-------------------
붙여넣은 코드를 `ast`로 파싱해 **설명을 가장 요구할 만한 구조** 하나를 찾아
질문에 끼운다. "이 코드가 왜 이렇게 동작하는지 설명해볼래요?"는 코드를 안 읽고도
얼버무릴 수 있지만, "`while` 반복문이 **언제 끝나는지** 말해볼래요?"는 그럴 수
없다. 이해도 확인의 목적이 바로 그것이다.

학생을 **붙여넣기로 단정하지 않는다.** 대규모 변경 탐지에는 오탐이 있고
(빠르게 타이핑한 초안도 걸린다), "복사했죠?"로 읽히는 문구는 정직하게 작성한
학생에게 모욕이 된다. 그래서 문구는 관측 사실("코드가 한 번에 많이 바뀌었다")에
머문다.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from ..schemas import GuidedAction, SessionContext, TutorMessage

#: 이 분기의 지도 방식. LLM이 고르던 값을 상수로 고정한다 (모듈 docstring 참고).
APPROACH = "이해도 확인"

#: `GuidancePlan.focus` — 이번 개입에서 다룰 대상. 앵커를 찾으면 그 구조로 채운다.
_FOCUS_FALLBACK = "붙여넣은 코드의 실행 순서"

#: 내부 지시문. 이 분기는 작문 LLM을 부르지 않으므로 실제로 문장에 반영되는 건
#: 아니고, 교육자 타임라인/로그에 "무슨 의도의 개입이었나"를 남기는 몫이다.
_TALKING_POINTS = ["학생이 코드의 동작을 자기 말로 설명하게 만든다"]
_AVOID = ["코드 수정 제안", "정답 코드", "붙여넣기라는 단정"]


@dataclass(frozen=True)
class CodeAnchor:
    """질문이 가리킬 코드 구조 한 곳."""

    kind: str
    #: 질문 문구에 그대로 박히는 이름 (함수명 등). 구조 자체를 가리킬 땐 키워드.
    label: str
    line: int


#: 앵커 우선순위. **앞에 있을수록 설명하기 어려운 구조**다.
#: 재귀 > 컴프리헨션 > while > for > 분기 > 함수 정의 순인 이유: 학생이 코드를
#: 실제로 읽었는지 가르는 힘이 이 순서대로 세다. 함수 정의는 이름만 보고도
#: 답할 수 있어서 마지막이다.
_PRIORITY = ("recursion", "comprehension", "while", "for", "branch", "function")

_QUESTIONS = {
    "recursion": "`{label}` 함수가 자기 자신을 다시 부르고 있어요. 어떤 조건에서 더 이상 부르지 않고 멈추나요?",
    "comprehension": "{line}번째 줄에 한 줄로 압축된 식이 있어요. 이걸 `for` 문으로 풀어쓰면 어떤 모양이 될까요?",
    "while": "{line}번째 줄 `while` 반복문은 **언제** 끝나나요? 끝나게 만드는 게 무엇인지 짚어볼래요?",
    "for": "{line}번째 줄 `for` 반복문이 한 바퀴 돌 때마다 어떤 값이 어떻게 바뀌나요?",
    "branch": "{line}번째 줄 `if` 조건이 참이 되는 경우와 거짓이 되는 경우를 각각 예로 들어볼래요?",
    "function": "`{label}` 함수가 무엇을 받아서 무엇을 돌려주는지 한 문장으로 말해볼래요?",
}

#: 앵커를 못 찾았을 때(문법이 깨져 있거나, 파싱은 됐지만 짚을 구조가 없을 때).
_FALLBACK_QUESTION = "이 코드가 어떤 순서로 실행되는지 한 문장으로 설명해볼래요?"

#: 모든 질문 앞에 붙는 도입부. 관측한 사실만 말하고 붙여넣기로 단정하지 않는다.
_LEAD = "코드가 한 번에 많이 바뀌었네요. 넘어가기 전에 하나만 확인할게요 — "


def _calls_itself(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """함수 본문이 자기 이름을 호출하는가 (= 재귀).

    `getattr(x, name)()` 같은 간접 호출은 못 잡지만, 학습용 재귀 코드는 거의 전부
    직접 이름 호출이라 이걸로 충분하다.
    """
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == fn.name
        for node in ast.walk(fn)
    )


def find_anchor(code: str) -> CodeAnchor | None:
    """코드에서 질문이 가리킬 구조 하나를 고른다. 없으면 None.

    `ast.walk`는 소스 순서가 아니라 BFS라 "먼저 나온 것"을 보장하지 않는다.
    그래서 같은 종류가 여럿이면 **줄 번호가 가장 작은 것**을 남긴다 — 학생은
    코드를 위에서부터 읽으므로 첫 등장을 가리켜야 대화가 자연스럽다.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        # 붙여넣기 직후라 아직 문법이 깨져 있을 수 있다(들여쓰기만 안 맞는 경우 등).
        # 그건 이 모듈이 판단할 일이 아니다 — 앵커 없이 일반 질문으로 간다.
        return None

    found: dict[str, CodeAnchor] = {}

    def remember(kind: str, label: str, line: int) -> None:
        current = found.get(kind)
        if current is None or line < current.line:
            found[kind] = CodeAnchor(kind=kind, label=label, line=line)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            remember("function", node.name, node.lineno)
            if _calls_itself(node):
                remember("recursion", node.name, node.lineno)
        elif isinstance(node, ast.While):
            remember("while", "while", node.lineno)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            remember("for", "for", node.lineno)
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            remember("comprehension", "컴프리헨션", node.lineno)
        elif isinstance(node, ast.If):
            remember("branch", "if", node.lineno)

    for kind in _PRIORITY:
        anchor = found.get(kind)
        if anchor is not None:
            return anchor
    return None


def build_question(code: str) -> tuple[str, CodeAnchor | None]:
    """도입부 없는 **질문 한 문장**과 그 질문이 가리키는 앵커.

    `TutorMessage.question`에 그대로 들어간다 — 학생이 답을 보내오면 평가
    에이전트가 "무엇을 물었는지"로 이 값을 다시 쓴다. 그래서 도입부
    (`_LEAD`)는 여기에 붙이지 않는다: 평가에 필요한 건 질문뿐이다.
    """
    anchor = find_anchor(code)
    if anchor is None:
        return _FALLBACK_QUESTION, None
    return _QUESTIONS[anchor.kind].format(label=anchor.label, line=anchor.line), anchor


def build_message(code: str) -> tuple[str, CodeAnchor | None]:
    """학생에게 보낼 문구와, 그 문구가 가리키는 앵커를 함께 돌려준다."""
    question, anchor = build_question(code)
    return _LEAD + question, anchor


def plan(ctx: SessionContext) -> GuidedAction:
    """`guided_action_agent.plan()`과 같은 자리에 꽂히는, LLM 없는 대체 구현.

    반환 타입이 같으므로 `orchestrator`의 하류(= `backend_adapter`,
    `PipelineResult` 소비자)는 이 분기를 몰라도 된다.

    **작문은 여기서 하지 않는다** — 파이프라인이 3단계가 된 뒤(판단/작문 분리,
    `schemas.GuidancePlan` docstring 참고) 학생이 읽는 문장은 `TutorMessage`에만
    담긴다. 이 분기의 그 몫은 아래 `write()`가 맡는다.

    `expects_student_reply=True`인 이유: 이해도 확인은 답을 받아야 의미가 있다.
    이 값이 True면 프런트가 입력창을 열고, 학생이 답하면 그 답이 응답
    파이프라인(`evaluation_agent`)으로 들어간다 — 붙여넣기 분기가 학생 답변
    평가 루프를 쓰는 대표 경로다.
    """
    message, anchor = build_message(ctx.code)
    payload: dict = {"message": message}
    if anchor is not None:
        # 지금 프런트는 payload를 렌더하지 않지만, 나중에 해당 줄을 에디터에서
        # 강조하려면(action_type="highlight_code") 이 값이 그대로 필요하다.
        payload["anchor_kind"] = anchor.kind
        payload["line_start"] = anchor.line
        payload["line_end"] = anchor.line

    return GuidedAction(
        approach=APPROACH,
        hint_level="nudge",
        focus=f"{anchor.label} ({anchor.kind})" if anchor else _FOCUS_FALLBACK,
        talking_points=_TALKING_POINTS,
        avoid=_AVOID,
        expects_student_reply=True,
        action_type="send_message",
        payload=payload,
    )


def write(ctx: SessionContext) -> TutorMessage:
    """`tutor_message_agent.write_intervention()`과 같은 자리에 꽂히는 대체 구현.

    `plan()`과 같은 `build_message()`에서 문구를 만들므로 두 값이 어긋날 수
    없다 (순수 함수 + 같은 입력). 그래서 `payload["message"]`와
    `TutorMessage.message`는 항상 같다 — backend_adapter가 전자를 폴백으로
    쓰는데, 둘이 다르면 학생이 보는 문구가 경로에 따라 달라진다.
    """
    message, _ = build_message(ctx.code)
    question, _ = build_question(ctx.code)
    return TutorMessage(message=message, question=question, expects_reply=True)
