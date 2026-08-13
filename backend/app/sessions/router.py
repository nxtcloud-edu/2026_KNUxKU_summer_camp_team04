from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlmodel import Session as DbSession

from app.db import get_db
from app.problems.service import ProblemRepository, get_problem_repository
from app.sessions import service, store
from app.sessions.schemas import SessionCreate, SessionRead

router = APIRouter(tags=["sessions"])


@router.post("/sessions", response_model=SessionRead, status_code=status.HTTP_201_CREATED)
def create_session(
    body: SessionCreate,
    db: DbSession = Depends(get_db),
    repo: ProblemRepository = Depends(get_problem_repository),
) -> SessionRead:
    session = service.create_session(
        db, repo, problem_id=body.problem_id, user_id=body.user_id
    )
    return service.to_read(db, session)


@router.get("/sessions/{session_id}", response_model=SessionRead)
def get_session(session_id: str, db: DbSession = Depends(get_db)) -> SessionRead:
    return service.to_read(db, store.require_session(db, session_id))


@router.post("/sessions/{session_id}/finish", response_model=SessionRead)
def finish_session(session_id: str, db: DbSession = Depends(get_db)) -> SessionRead:
    session = service.finish_session(db, store.require_session(db, session_id))
    return service.to_read(db, session)
