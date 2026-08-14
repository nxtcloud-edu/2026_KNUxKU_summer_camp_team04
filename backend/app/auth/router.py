"""인증 API.

토큰 전략: **access token 하나만** (Authorization: Bearer). 데모 범위에서
refresh 쿠키를 도입하면 CORS credentials 설정이 까다로워지고 localhost에서
Secure 쿠키가 안 붙는 예외 처리가 따라온다. /auth/refresh는 스키마만 열어두고
나중에 켠다 -- 프런트는 지금 그 경로를 몰라도 된다.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlmodel import Session as DbSession

from app.auth import service
from app.auth.deps import get_current_user
from app.auth.schemas import AuthResponse, LoginRequest, SignupRequest, UserRead
from app.config import get_settings
from app.db import get_db
from app.models import User

router = APIRouter(tags=["auth"])


def _auth_response(user: User, token: str) -> AuthResponse:
    return AuthResponse(
        user=UserRead.from_user(user),
        access_token=token,
        expires_in=get_settings().access_token_expire_minutes * 60,
    )


@router.post("/auth/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def signup(body: SignupRequest, db: DbSession = Depends(get_db)) -> AuthResponse:
    user, token = service.signup(
        db,
        name=body.name,
        email=body.email,
        password=body.password,
        role=body.role,
        invite_code=body.invite_code,
        course_invite_code=body.course_invite_code,
    )
    db.commit()
    db.refresh(user)
    return _auth_response(user, token)


@router.post("/auth/login", response_model=AuthResponse)
def login(body: LoginRequest, db: DbSession = Depends(get_db)) -> AuthResponse:
    user, token = service.login(db, email=body.email, password=body.password)
    db.commit()
    db.refresh(user)
    return _auth_response(user, token)


@router.post(
    "/auth/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
def logout(_: User = Depends(get_current_user)) -> Response:
    """서버는 access token을 저장하지 않으므로 무효화할 상태가 없다.

    그래도 엔드포인트를 두는 이유: 프런트가 "로그아웃 했다"를 서버에 알리는
    지점이 있어야 나중에 토큰 블랙리스트나 refresh 쿠키 삭제를 붙일 때
    **프런트를 고치지 않아도 된다.** 지금은 토큰을 지우는 건 클라이언트 몫이다.
    """
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/auth/me", response_model=UserRead)
def me(user: User = Depends(get_current_user)) -> UserRead:
    """새로고침 후 로그인 상태와 프로필을 복구할 때 쓴다."""
    return UserRead.from_user(user)
