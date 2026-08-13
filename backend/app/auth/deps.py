"""인증 의존성.

**여기서 예외를 던지는 것은 안전하다** -- 라우터 본문 진입 전에 401이 나가고,
그게 정확히 원하는 동작이다. (app/agent/__init__.py 의 get_agent 와 대비된다:
그건 예외를 던지면 안 되는 Depends다.)
"""
from __future__ import annotations

from fastapi import Depends, Request
from sqlmodel import Session as DbSession

from app.auth.security import decode_access_token
from app.db import get_db
from app.errors import NotAuthenticated
from app.models import User


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("Authorization") or request.headers.get("authorization")
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def get_current_user(request: Request, db: DbSession = Depends(get_db)) -> User:
    token = _bearer_token(request)
    if token is None:
        raise NotAuthenticated()

    payload = decode_access_token(token)
    if payload is None:
        raise NotAuthenticated("로그인이 만료되었습니다. 다시 로그인해 주세요.")

    user = db.get(User, payload["sub"])
    if user is None or not user.is_active:
        raise NotAuthenticated()
    return user


def get_current_user_optional(
    request: Request, db: DbSession = Depends(get_db)
) -> User | None:
    """인증이 있으면 사용자를, 없으면 None. 공개/비공개가 섞인 엔드포인트용."""
    try:
        return get_current_user(request, db)
    except NotAuthenticated:
        return None
