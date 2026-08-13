from __future__ import annotations

from fastapi import APIRouter, Depends

from app.problems.schemas import ProblemDetail, ProblemSummary
from app.problems.service import ProblemRepository, get_problem_repository

router = APIRouter(tags=["problems"])

# response_model_exclude_none=True 인 이유:
# check_type에 따라 안 쓰이는 필드(function_call이면 stdin/expected_stdout,
# stdout_match면 input/expected)를 null로 내보내면 안 된다. 프론트가
# `test.stdin !== undefined`로 분기하는데 null은 undefined와 다르므로
# 그 분기를 타고 들어가 null.trim()에서 렌더가 죽는다.
# 키를 아예 빼면 프론트의 optional 타입과 정확히 맞고 judge API 응답과도 같아진다.


@router.get(
    "/problems", response_model=list[ProblemSummary], response_model_exclude_none=True
)
def list_problems(
    repo: ProblemRepository = Depends(get_problem_repository),
) -> list[ProblemSummary]:
    return [ProblemSummary.from_record(r) for r in repo.list()]


@router.get(
    "/problems/{problem_id}",
    response_model=ProblemDetail,
    response_model_exclude_none=True,
)
def get_problem(
    problem_id: str,
    repo: ProblemRepository = Depends(get_problem_repository),
) -> ProblemDetail:
    return ProblemDetail.from_record(repo.get(problem_id))
