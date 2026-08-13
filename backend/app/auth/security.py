"""비밀번호 해싱과 access token.

**원문 비밀번호는 어디에도 저장하지 않고 로그에도 남기지 않는다.**
해시는 bcrypt를 쓴다 (요구사항: Argon2 또는 bcrypt).
"""
from __future__ import annotations

import hashlib
import hmac
from datetime import timedelta
from typing import Any

import bcrypt
import jwt

from app.clock import utcnow
from app.config import get_settings

# bcrypt는 72바이트를 넘는 입력을 조용히 자른다. 긴 비밀번호의 뒷부분이
# 무시되면 서로 다른 비밀번호가 같은 해시를 갖는다 -- 먼저 sha256으로 압축해
# 길이를 고정한다(널리 쓰이는 pre-hash 관행).
_BCRYPT_MAX_BYTES = 72


def _prehash(password: str) -> bytes:
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return digest  # 32바이트 -- bcrypt 한계 안


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_prehash(password), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        # 해시가 손상됐거나 형식이 다르면 인증 실패로 처리한다. 예외를 위로
        # 올리면 500이 나고, 그 자체가 "이 계정은 존재한다"는 신호가 된다.
        return False


def create_access_token(user_id: str, *, expires_in: timedelta | None = None) -> str:
    s = get_settings()
    now = utcnow()
    exp = now + (expires_in or timedelta(minutes=s.access_token_expire_minutes))
    payload = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "typ": "access",
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any] | None:
    """유효하면 payload, 아니면 None. **예외를 밖으로 흘리지 않는다.**

    만료/서명불일치/형식오류를 호출부가 구분할 필요가 없다 -- 전부 401이다.
    구분해서 알려주면 공격자에게 정보를 준다.
    """
    s = get_settings()
    try:
        payload = jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != "access" or not payload.get("sub"):
        return None
    return payload


def hash_reset_token(raw_token: str) -> str:
    """비밀번호 재설정 토큰은 원문이 아니라 해시를 저장한다."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    """타이밍 공격을 피하는 비교."""
    return hmac.compare_digest(a, b)
