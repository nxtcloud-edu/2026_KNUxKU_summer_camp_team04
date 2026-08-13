"""문제 응답 스키마.

**ProblemDetail에는 hidden test의 input이나 expected를 담을 수 있는 필드가 없다.**
이게 유출 방지의 전부다. 절차(잊지 말고 지우기)가 아니라 구조(담을 그릇이 없음)라서
어떤 response_model 실수도, 어떤 디버그 엔드포인트도 hidden input을 내보낼 수 없다.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.problems.service import ProblemRecord


class TestCasePreview(BaseModel):
    input: list[Any]
    expected: Any
    category: str


class ProblemSummary(BaseModel):
    problem_id: str
    title: str
    concepts: list[str]
    difficulty: str
    function_name: str

    @classmethod
    def from_record(cls, r: ProblemRecord) -> "ProblemSummary":
        return cls(
            problem_id=r.problem_id,
            title=r.title,
            concepts=r.concepts,
            difficulty=r.difficulty,
            function_name=r.function_name,
        )


class ProblemDetail(ProblemSummary):
    description: str
    code_template: str
    check_type: str
    public_test_cases: list[TestCasePreview]  # 공개니까 그대로 나간다
    hidden_test_case_count: int  # 개수만
    hidden_test_categories: list[str]  # 카테고리만

    @classmethod
    def from_record(cls, r: ProblemRecord) -> "ProblemDetail":
        return cls(
            problem_id=r.problem_id,
            title=r.title,
            concepts=r.concepts,
            difficulty=r.difficulty,
            function_name=r.function_name,
            description=r.description,
            code_template=r.code_template,
            check_type=r.check_type,
            public_test_cases=[
                TestCasePreview(input=tc.input, expected=tc.expected, category=tc.category)
                for tc in r.public_test_cases
            ],
            hidden_test_case_count=len(r.hidden_test_cases),
            hidden_test_categories=r.hidden_test_categories,
        )
