"""프로필 · 도토리 · 진행 상태 API. 전부 로그인 필요."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session as DbSession

from app.acorns import service as acorns
from app.auth import service as auth_service
from app.auth.deps import get_current_user
from app.auth.schemas import NicknameUpdateRequest, NicknameUpdateResponse, ProfileRead
from app.clock import utcnow
from app.config import get_settings
from app.db import get_db
from app.enums import AcornTransactionType, JudgeStatus
from app.educator import service as educator_service
from app.errors import ProblemNotFound
from app.models import User
from app.problems.service import ProblemRepository, get_problem_repository
from app.progress import service as progress_service
from app.users.schemas import (
    AcornBalanceRead,
    AcornTransactionListRead,
    AcornTransactionRead,
    CheckpointRequest,
    LocalJudgeResultRequest,
    ProgressListRead,
    ProgressRead,
    SolvedProblemListRead,
    SolvedProblemRead,
)

router = APIRouter(tags=["users"])


# --------------------------------------------------------------------- 프로필


@router.get("/users/me/profile", response_model=ProfileRead)
def get_profile(user: User = Depends(get_current_user)) -> ProfileRead:
    return ProfileRead.from_user(user)


@router.patch("/users/me/nickname", response_model=NicknameUpdateResponse)
def update_nickname(
    body: NicknameUpdateRequest,
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
) -> NicknameUpdateResponse:
    """닉네임 변경. 도토리 5개를 차감한다.

    **검증 → 차감 → 변경이 한 트랜잭션이다.** 나눠서 커밋하면
    "도토리는 빠졌는데 닉네임은 그대로"가 생긴다. 차감액도 서버가 정한다 --
    프런트가 보낸 금액을 믿지 않는다.
    """
    cost = get_settings().acorn_cost_nickname
    validated = auth_service.validate_nickname(db, body.nickname, exclude_user_id=user.id)

    if validated == user.nickname:
        # 같은 닉네임으로 바꾸는 건 과금하지 않는다.
        return NicknameUpdateResponse(
            nickname=user.nickname, acorn_balance=user.acorn_balance, acorns_spent=0
        )

    # 잔액 부족이면 여기서 402가 나고 아무것도 바뀌지 않는다.
    acorns.post(
        db,
        user_id=user.id,
        amount=-cost,
        transaction_type=AcornTransactionType.NICKNAME_CHANGED,
        description=f"닉네임 변경: {user.nickname} → {validated}",
    )
    user.nickname = validated
    user.updated_at = utcnow()
    db.add(user)
    db.commit()
    db.refresh(user)

    return NicknameUpdateResponse(
        nickname=user.nickname, acorn_balance=user.acorn_balance, acorns_spent=cost
    )


# --------------------------------------------------------------------- 도토리


@router.get("/users/me/acorns", response_model=AcornBalanceRead)
def get_acorns(user: User = Depends(get_current_user)) -> AcornBalanceRead:
    return AcornBalanceRead(balance=user.acorn_balance, total_earned=user.total_acorns_earned)


@router.get("/users/me/acorns/transactions", response_model=AcornTransactionListRead)
def list_acorn_transactions(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
) -> AcornTransactionListRead:
    rows = acorns.transactions(db, user.id, limit=limit, offset=offset)
    return AcornTransactionListRead(
        balance=user.acorn_balance,
        total_earned=user.total_acorns_earned,
        transactions=[AcornTransactionRead.from_row(t) for t in rows],
        total=acorns.transaction_count(db, user.id),
    )


# --------------------------------------------------------------------- 진행 상태


@router.get("/users/me/progress", response_model=ProgressListRead)
def list_progress(
    user: User = Depends(get_current_user), db: DbSession = Depends(get_db)
) -> ProgressListRead:
    """홈 화면이 26개 문제 상태를 한 번에 받는 경로. 코드 본문은 빼고 준다."""
    rows = progress_service.list_all(db, user.id)
    return ProgressListRead(
        items=[ProgressRead.from_row(r, include_code=False) for r in rows], total=len(rows)
    )


@router.get("/users/me/progress/{problem_id}", response_model=ProgressRead)
def get_progress(
    problem_id: str,
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
    repo: ProblemRepository = Depends(get_problem_repository),
) -> ProgressRead:
    if not repo.exists(problem_id):
        raise ProblemNotFound(problem_id)
    row = progress_service.get(db, user.id, problem_id)
    if row is None:
        # 아직 손대지 않은 문제. 404 대신 빈 상태를 준다 -- 프런트가
        # "없음"과 "에러"를 구분하는 분기를 만들지 않아도 된다.
        row = progress_service.UserProblemProgress(
            user_id=user.id,
            problem_id=problem_id,
            status=progress_service.ProgressStatus.NOT_STARTED,
        )
    return ProgressRead.from_row(row, include_code=True)


@router.put("/users/me/progress/{problem_id}/checkpoint", response_model=ProgressRead)
def save_checkpoint(
    problem_id: str,
    body: CheckpointRequest,
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
    repo: ProblemRepository = Depends(get_problem_repository),
) -> ProgressRead:
    """작성 중인 코드를 계정에 저장한다. localStorage 대체."""
    if not repo.exists(problem_id):
        raise ProblemNotFound(problem_id)
    row = progress_service.save_checkpoint(db, user.id, problem_id, body.student_code)
    for course_id in educator_service.course_ids_assigned(db, user.id, problem_id, repo):
        progress_service.save_checkpoint(db, user.id, problem_id, body.student_code, course_id)
    educator_service.recalculate_for_student(db, student=user, problem_id=problem_id, repo=repo)
    db.commit()
    db.refresh(row)
    return ProgressRead.from_row(row, include_code=True)


@router.post("/users/me/progress/{problem_id}/local-result", response_model=ProgressRead)
def sync_local_result(
    problem_id: str,
    body: LocalJudgeResultRequest,
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
    repo: ProblemRepository = Depends(get_problem_repository),
) -> ProgressRead:
    """개발 모드의 Pyodide 폴백 결과를 강의 진도에도 반영한다.

    운영 환경에서는 클라이언트 채점 결과를 절대 신뢰하지 않는다. 서버 judge가
    없는 로컬 데모에서만 학생/교수자 화면의 진도를 일치시키기 위한 경로다.
    """
    settings = get_settings()
    if settings.app_env != "dev" or settings.judge_backend != "none":
        raise HTTPException(status_code=404, detail="Not Found")
    if not repo.exists(problem_id):
        raise ProblemNotFound(problem_id)
    problem = repo.get(problem_id)
    existing = progress_service.get(db, user.id, problem_id)
    if existing is not None and existing.status == progress_service.ProgressStatus.SOLVED:
        return ProgressRead.from_row(existing, include_code=True)
    course_ids = educator_service.course_ids_assigned(db, user.id, problem_id, repo)
    row, _ = progress_service.record_judge_result(
        db, user_id=user.id, problem=problem, status=JudgeStatus(body.status),
        passed=body.passed, total=body.total, code=body.student_code,
        mode=body.mode, course_ids=course_ids,
    )
    educator_service.recalculate_for_student(db, student=user, problem_id=problem_id, repo=repo)
    db.commit()
    db.refresh(row)
    return ProgressRead.from_row(row, include_code=True)


# --------------------------------------------------------------------- 풀이 완료


@router.get("/users/me/solved-problems", response_model=SolvedProblemListRead)
def list_solved_problems(
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
    repo: ProblemRepository = Depends(get_problem_repository),
) -> SolvedProblemListRead:
    rows = progress_service.list_solved(db, user.id)
    items: list[SolvedProblemRead] = []
    for r in rows:
        title = r.problem_id
        if repo.exists(r.problem_id):
            title = repo.get(r.problem_id).title
        items.append(
            SolvedProblemRead(
                problem_id=r.problem_id,
                title=title,
                solved_at=r.solved_at,
                attempt_count=r.attempt_count,
                acorns_earned=acorns.earned_for_problem(db, user.id, r.problem_id),
            )
        )
    return SolvedProblemListRead(items=items, total=len(items))
