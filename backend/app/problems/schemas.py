"""문제 응답 스키마.

**ProblemDetail에는 hidden test의 input이나 expected를 담을 수 있는 필드가 없다.**
이게 유출 방지의 전부다. 절차(잊지 말고 지우기)가 아니라 구조(담을 그릇이 없음)라서
어떤 response_model 실수도, 어떤 디버그 엔드포인트도 hidden input을 내보낼 수 없다.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.problems.service import ProblemRecord, TestCase


class TestCasePreview(BaseModel):
    """check_type에 따라 채워지는 필드가 다르다. 원본 키를 그대로 내보낸다.

    프론트(App.tsx의 formatPublicTest)가 `stdin !== undefined`로 렌더링을
    분기하므로, stdout 케이스를 input/expected로 뭉개면 예제가 잘못 표시된다.
    """

    category: str
    # function_call 전용
    input: list[Any] | None = None
    expected: Any = None
    # stdout_match 전용
    stdin: str | None = None
    expected_stdout: str | None = None

    @classmethod
    def from_case(cls, tc: TestCase) -> "TestCasePreview":
        return cls(
            category=tc.category,
            input=tc.input,
            expected=tc.expected,
            stdin=tc.stdin,
            expected_stdout=tc.expected_stdout,
        )


class ProblemSummary(BaseModel):
    # 키 이름은 **단수 `concept`**이다. 문제 JSON 26개 전부, judge API,
    # 프론트 파서가 전부 단수를 쓴다. 여기만 복수였을 때는 프론트의
    # Array.isArray(item.concept)가 항상 false가 되어 개념 태그가
    # 에러도 경고도 없이 빈 배열이 됐다.
    problem_id: str
    title: str
    concept: list[str]
    difficulty: str
    check_type: str
    function_name: str | None = None
    points: int
    acorn_reward: int

    @classmethod
    def from_record(cls, r: ProblemRecord) -> "ProblemSummary":
        return cls(
            problem_id=r.problem_id,
            title=r.title,
            concept=r.concepts,
            difficulty=r.difficulty,
            check_type=r.check_type,
            function_name=r.function_name,
            points=r.points,
            acorn_reward=r.acorn_reward,
        )


class ProblemDetail(ProblemSummary):
    description: str
    code_template: str
    public_test_cases: list[TestCasePreview]  # 공개니까 그대로 나간다
    hidden_test_case_count: int  # 개수만
    hidden_test_categories: list[str]  # 카테고리만
    # judge 문제 23개에 있다. 프론트 타입에도 이미 optional로 선언돼 있다.
    time_limit_sec: float | None = None
    memory_limit_mb: int | None = None

    @classmethod
    def from_record(cls, r: ProblemRecord) -> "ProblemDetail":
        return cls(
            problem_id=r.problem_id,
            title=r.title,
            concept=r.concepts,
            difficulty=r.difficulty,
            check_type=r.check_type,
            function_name=r.function_name,
            points=r.points,
            acorn_reward=r.acorn_reward,
            description=r.description,
            code_template=r.code_template,
            public_test_cases=[
                TestCasePreview.from_case(tc) for tc in r.public_test_cases
            ],
            hidden_test_case_count=len(r.hidden_test_cases),
            hidden_test_categories=r.hidden_test_categories,
            time_limit_sec=r.time_limit_sec,
            memory_limit_mb=r.memory_limit_mb,
        )
