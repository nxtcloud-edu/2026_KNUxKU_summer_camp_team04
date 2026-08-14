"""붙여넣기 분기의 규칙 기반 질문 생성 테스트.

이 모듈은 **LLM을 전혀 안 쓰므로** mock이 필요 없다 — 그게 이 모듈의 존재 이유다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tutor_agent.agents import comprehension_check  # noqa: E402
from tutor_agent.schemas import SessionContext  # noqa: E402


def _anchor_kind(code: str) -> str | None:
    anchor = comprehension_check.find_anchor(code)
    return anchor.kind if anchor else None


# --- 앵커 탐지 --------------------------------------------------------------


def test_finds_while_loop() -> None:
    assert _anchor_kind("i = 0\nwhile i < 5:\n    i += 1\n") == "while"


def test_finds_for_loop() -> None:
    assert _anchor_kind("for n in [1, 2, 3]:\n    print(n)\n") == "for"


def test_finds_comprehension() -> None:
    assert _anchor_kind("xs = [n * 2 for n in range(10)]\n") == "comprehension"


def test_finds_recursion() -> None:
    code = "def fact(n):\n    if n <= 1:\n        return 1\n    return n * fact(n - 1)\n"
    assert _anchor_kind(code) == "recursion"


def test_finds_plain_function() -> None:
    assert _anchor_kind("def add(a, b):\n    return a + b\n") == "function"


def test_finds_branch_without_function() -> None:
    assert _anchor_kind("x = 3\nif x > 2:\n    print('big')\n") == "branch"


@pytest.mark.parametrize(
    "code, expected",
    [
        # 재귀는 단순 함수 정의보다 우선한다.
        ("def helper():\n    pass\n\ndef go(n):\n    return go(n - 1)\n", "recursion"),
        # while은 for보다 우선한다 (종료 조건 설명이 더 어렵다).
        ("for a in x:\n    pass\nwhile True:\n    break\n", "while"),
        # 반복문은 if보다 우선한다.
        ("if a:\n    pass\nfor b in c:\n    pass\n", "for"),
    ],
)
def test_priority_between_structures(code: str, expected: str) -> None:
    """우선순위는 '설명하기 어려운 순'이다 (모듈의 _PRIORITY 주석 참고)."""
    assert _anchor_kind(code) == expected


def test_picks_first_occurrence_by_line() -> None:
    """같은 종류가 여러 개면 줄 번호가 가장 작은 것. ast.walk는 소스 순서가 아니다."""
    code = "for a in x:\n    for b in y:\n        pass\n"
    anchor = comprehension_check.find_anchor(code)
    assert anchor is not None
    assert anchor.line == 1


def test_no_anchor_when_syntax_is_broken() -> None:
    """붙여넣기 직후엔 들여쓰기가 안 맞을 수 있다. 그건 이 모듈이 판단할 일이 아니다."""
    assert comprehension_check.find_anchor("def f(:\n  ???\n") is None


def test_no_anchor_for_flat_code() -> None:
    assert comprehension_check.find_anchor("x = 1\ny = x + 2\nprint(y)\n") is None


# --- 문구 생성 --------------------------------------------------------------


def test_message_names_the_function_for_recursion() -> None:
    code = "def fact(n):\n    if n <= 1:\n        return 1\n    return n * fact(n - 1)\n"
    message, anchor = comprehension_check.build_message(code)
    assert anchor is not None and anchor.kind == "recursion"
    assert "fact" in message


def test_message_cites_the_line_number() -> None:
    message, anchor = comprehension_check.build_message("x = 0\nwhile x < 3:\n    x += 1\n")
    assert anchor is not None
    assert f"{anchor.line}번째 줄" in message


def test_message_falls_back_without_anchor() -> None:
    message, anchor = comprehension_check.build_message("def f(:\n")
    assert anchor is None
    assert message.strip()


def test_message_never_accuses_the_student_of_pasting() -> None:
    """대규모 변경 탐지에는 오탐이 있다. 정직하게 작성한 학생에게 '복사했죠?'로
    읽히면 안 되므로 문구는 관측 사실에만 머물러야 한다."""
    for code in ("for n in x:\n    pass\n", "def f(:\n", "x = 1\n"):
        message, _ = comprehension_check.build_message(code)
        assert "붙여넣" not in message
        assert "복사" not in message


# --- plan() / write() 계약 --------------------------------------------------


def test_plan_returns_guided_action_shape() -> None:
    """`guided_action_agent.plan()`과 같은 타입이라야 하류가 이 분기를 몰라도 된다."""
    ctx = SessionContext(
        student_id="s1", problem_id="p1", code="for n in [1]:\n    print(n)\n"
    )
    guided = comprehension_check.plan(ctx)

    assert guided.approach == comprehension_check.APPROACH
    assert guided.hint_level == "nudge"
    assert guided.action_type == "send_message"
    assert guided.payload["line_start"] == 1
    # 이해도 확인은 답을 받아야 의미가 있다. 이 값이 프런트의 입력창을 열고,
    # 학생 답변을 응답 파이프라인(evaluation_agent)으로 들여보낸다.
    assert guided.expects_student_reply is True


def test_plan_without_anchor_omits_line_payload() -> None:
    ctx = SessionContext(student_id="s1", problem_id="p1", code="x = 1\n")
    guided = comprehension_check.plan(ctx)

    assert guided.payload["message"]
    assert "line_start" not in guided.payload


def test_write_returns_the_student_facing_message() -> None:
    """작문은 `TutorMessage`가 담당한다 (판단/작문 분리 이후).

    `payload["message"]`와 어긋나면 학생이 보는 문구가 경로에 따라 달라진다 —
    backend_adapter가 전자를 폴백으로 쓰기 때문이다.
    """
    ctx = SessionContext(
        student_id="s1", problem_id="p1", code="i = 0\nwhile i < 3:\n    i += 1\n"
    )
    guided = comprehension_check.plan(ctx)
    message = comprehension_check.write(ctx)

    assert message.message == guided.payload["message"]
    assert message.expects_reply is True
    # question은 도입부 없는 질문 한 문장이다 (평가 단계가 "무엇을 물었나"로 쓴다).
    assert message.question
    assert message.question in message.message
    assert not message.question.startswith("코드가 한 번에 많이 바뀌었네요")
