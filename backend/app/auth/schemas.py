"""인증 · 프로필 스키마. 전부 snake_case.

**password_hash를 담을 수 있는 응답 스키마가 하나도 없다.** 유출 방지가
절차가 아니라 구조여야 한다는 원칙은 여기에도 그대로 적용된다.
"""
from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from app.enums import UserRole
from app.models import User
from app.schemas_common import UtcDatetime

# 뱃지 기준 (문서 §9). 서버가 계산해 내려준다 -- 정책을 한 곳에서 관리하기 위해.
BADGE_THRESHOLDS: list[tuple[int, str, str]] = [
    (0, "SEED", "씨앗 뱃지"),
    (50, "SPROUT", "새싹 뱃지"),
    (150, "SAPLING", "묘목 뱃지"),
    (300, "OAK", "참나무 뱃지"),
    (600, "FOREST_KEEPER", "숲지기 뱃지"),
    (1000, "LEGENDARY_ACORN", "전설의 도토리 뱃지"),
]


class Badge(BaseModel):
    code: str
    name: str
    required_acorns: int


def current_badge(total_earned: int) -> Badge:
    chosen = BADGE_THRESHOLDS[0]
    for threshold in BADGE_THRESHOLDS:
        if total_earned >= threshold[0]:
            chosen = threshold
    return Badge(code=chosen[1], name=chosen[2], required_acorns=chosen[0])


def next_badge(total_earned: int) -> Badge | None:
    for threshold in BADGE_THRESHOLDS:
        if total_earned < threshold[0]:
            return Badge(code=threshold[1], name=threshold[2], required_acorns=threshold[0])
    return None


class SignupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    email: EmailStr
    # 역할은 요청으로 받되 **가입 게이트를 통과해야 한다** --
    # EDUCATOR 는 기관 초대 코드가 필수다 (auth/service.resolve_organization).
    role: UserRole = UserRole.STUDENT
    invite_code: str | None = Field(default=None, max_length=64)
    # 학생이 교수자에게 받은 강의 코드. 가입 성공과 수강 등록을 한 트랜잭션으로 처리한다.
    course_invite_code: str | None = Field(default=None, max_length=64)
    # 8자 미만은 거부한다. 상한은 bcrypt pre-hash 때문에 기술적으로는 불필요하지만
    # 비정상적으로 긴 입력을 해싱하는 비용을 막는다.
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserRead(BaseModel):
    id: str
    name: str
    nickname: str
    email: str
    avatar_url: str | None
    role: UserRole
    organization_id: str | None
    acorn_balance: int
    total_acorns_earned: int

    @classmethod
    def from_user(cls, u: User) -> "UserRead":
        return cls(
            id=u.id,
            name=u.name,
            nickname=u.nickname,
            email=u.email,
            avatar_url=u.avatar_url,
            role=UserRole(u.role),
            organization_id=u.organization_id,
            acorn_balance=u.acorn_balance,
            total_acorns_earned=u.total_acorns_earned,
        )


class AuthResponse(BaseModel):
    user: UserRead
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class ProfileRead(UserRead):
    current_badge: Badge
    next_badge: Badge | None
    created_at: UtcDatetime
    last_login_at: UtcDatetime | None

    @classmethod
    def from_user(cls, u: User) -> "ProfileRead":
        return cls(
            id=u.id,
            name=u.name,
            nickname=u.nickname,
            email=u.email,
            avatar_url=u.avatar_url,
            role=UserRole(u.role),
            organization_id=u.organization_id,
            acorn_balance=u.acorn_balance,
            total_acorns_earned=u.total_acorns_earned,
            current_badge=current_badge(u.total_acorns_earned),
            next_badge=next_badge(u.total_acorns_earned),
            created_at=u.created_at,
            last_login_at=u.last_login_at,
        )


class NicknameUpdateRequest(BaseModel):
    nickname: str = Field(min_length=1, max_length=32)


class NicknameUpdateResponse(BaseModel):
    nickname: str
    acorn_balance: int
    acorns_spent: int
