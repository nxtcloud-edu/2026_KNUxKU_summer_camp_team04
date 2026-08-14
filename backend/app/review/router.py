"""복습 문제 생성 API.

`/users/me/...` 아래에 두는 이유: 복습 문제는 **그 학생 개인의 것**이다.
문제 목록(`/problems`)은 모두가 같은 것을 보지만 이건 소유자만 본다.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy.engine import Engine
from sqlmodel import Session as DbSession

from app.auth.deps import get_current_user
from app.db import get_db, get_engine
from app.models import User
from app.problems.service import ProblemRepository, get_problem_repository
from app.review import service
from app.review.interface import ProblemGeneratorProtocol, get_problem_generator
from app.review.schemas import (
    ReviewProblemCreate,
    ReviewProblemListResponse,
    ReviewProblemRead,
)

log = logging.getLogger(__name__)
router = APIRouter(tags=["review"])


@router.post(
    "/users/me/review-problems",
    response_model=ReviewProblemRead,
    status_code=status.HTTP_201_CREATED,
)
def create_review_problem(
    body: ReviewProblemCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
    repo: ProblemRepository = Depends(get_problem_repository),
    generator: ProblemGeneratorProtocol = Depends(get_problem_generator),
    engine: Engine = Depends(get_engine),
) -> ReviewProblemRead:
    """복습 문제 생성을 **요청**한다. 생성 자체는 백그라운드에서 돈다.

    LLM 생성 + judge 샌드박스 실행이라 실측 ~25초다. 이걸 동기로 두면 학생이
    로딩 화면을 25초 보게 되고, 프록시/브라우저 타임아웃에도 걸린다. 그래서
    PENDING 행만 만들어 즉시 201로 돌려주고, 프런트는 `GET`으로 폴링한다
    (실시간 개입이 `AGENT_INTERVENTION`을 폴링하는 것과 같은 패턴).

    이미 PENDING인 요청이 있으면 **새로 만들지 않고 그걸 돌려준다** — 버튼을
    연타해도 LLM 호출이 쌓이지 않는다.
    """
    row, created = service.request_generation(db, user, repo, body.source_problem_id)

    if created:
        source = repo.get(body.source_problem_id)
        background_tasks.add_task(
            service.run_generation,
            engine,
            generator,
            repo,
            request_id=row.id,
            review_request=service.build_review_request(user, source),
        )

    return ReviewProblemRead.from_row(row)


@router.get("/users/me/review-problems", response_model=ReviewProblemListResponse)
def list_review_problems(
    limit: int = Query(default=service.DEFAULT_LIST_LIMIT, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
) -> ReviewProblemListResponse:
    """내 복습 문제 요청 목록 (최신순). 프런트가 이걸 폴링한다."""
    return ReviewProblemListResponse(
        items=[
            ReviewProblemRead.from_row(r) for r in service.list_for_user(db, user.id, limit)
        ]
    )
