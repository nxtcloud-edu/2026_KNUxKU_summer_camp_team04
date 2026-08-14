"""복습 문제 API 스키마."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.enums import GeneratedProblemStatus
from app.models import GeneratedProblem
from app.schemas_common import UtcDatetime


class ReviewProblemCreate(BaseModel):
    #: 복습의 바탕이 될 문제. 보통 학생이 방금 틀린/막힌 문제다.
    source_problem_id: str = Field(min_length=1, max_length=64)


class ReviewProblemRead(BaseModel):
    """생성 요청 1건의 상태.

    문제 **내용은 담지 않는다.** READY가 되면 `problem_id`로 기존
    `GET /problems/{problem_id}`를 부르면 된다 — 큐레이션 문제와 완전히 같은
    경로로 풀리는 것이 이 설계의 요점이다 (models.GeneratedProblem 주석 참고).
    """

    id: str
    status: GeneratedProblemStatus
    source_problem_id: str
    problem_id: str | None
    error_message: str | None
    created_at: UtcDatetime
    completed_at: UtcDatetime | None

    @classmethod
    def from_row(cls, row: GeneratedProblem) -> "ReviewProblemRead":
        return cls(
            id=row.id,
            status=GeneratedProblemStatus(row.status),
            source_problem_id=row.source_problem_id,
            problem_id=row.problem_id,
            error_message=row.error_message,
            created_at=row.created_at,
            completed_at=row.completed_at,
        )


class ReviewProblemListResponse(BaseModel):
    items: list[ReviewProblemRead]
