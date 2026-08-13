from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlmodel import Session as DbSession

from app.auth.deps import get_current_user
from app.db import get_db
from app.models import User
from app.problems.service import ProblemRepository, get_problem_repository
from app.sessions import service, store
from app.sessions.schemas import SessionCreate, SessionRead

router = APIRouter(tags=["sessions"])


@router.post("/sessions", response_model=SessionRead, status_code=status.HTTP_201_CREATED)
def create_session(
    body: SessionCreate,
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
    repo: ProblemRepository = Depends(get_problem_repository),
) -> SessionRead:
    """세션은 **로그인한 사용자 소유**로 만들어진다.

    user_id를 요청 body에서 받지 않는다. 받으면 아무나 남의 이름으로 세션을
    만들 수 있고, 그 세션의 채점 결과가 그 사람의 도토리가 된다.
    """
    session = service.create_session(db, repo, problem_id=body.problem_id, user_id=user.id)
    return service.to_read(db, session)


@router.get("/sessions/{session_id}", response_model=SessionRead)
def get_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
) -> SessionRead:
    return service.to_read(db, store.require_session(db, session_id, user_id=user.id))


@router.post("/sessions/{session_id}/finish", response_model=SessionRead)
def finish_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
) -> SessionRead:
    session = service.finish_session(
        db, store.require_session(db, session_id, user_id=user.id)
    )
    return service.to_read(db, session)
