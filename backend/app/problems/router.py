from __future__ import annotations

from fastapi import APIRouter, Depends

from app.problems.schemas import ProblemDetail, ProblemSummary
from app.problems.service import ProblemRepository, get_problem_repository

router = APIRouter(tags=["problems"])


@router.get("/problems", response_model=list[ProblemSummary])
def list_problems(
    repo: ProblemRepository = Depends(get_problem_repository),
) -> list[ProblemSummary]:
    return [ProblemSummary.from_record(r) for r in repo.list()]


@router.get("/problems/{problem_id}", response_model=ProblemDetail)
def get_problem(
    problem_id: str,
    repo: ProblemRepository = Depends(get_problem_repository),
) -> ProblemDetail:
    return ProblemDetail.from_record(repo.get(problem_id))
