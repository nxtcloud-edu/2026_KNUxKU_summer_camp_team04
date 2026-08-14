"""회원가입 · 로그인 · 닉네임 정책."""
from __future__ import annotations

import re

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session as DbSession
from sqlmodel import col, func, select

from app.auth.security import create_access_token, hash_password, verify_password
from app.clock import utcnow
from app.config import get_settings
from app.enums import EnrollmentStatus, UserRole
from app.errors import (
    EmailAlreadyRegistered,
    InvalidCredentials,
    InvalidInviteCode,
    InvalidNickname,
    NicknameTaken,
)
from app.models import Course, Enrollment, Organization, User


def normalize_email(email: str) -> str:
    """소문자 + 공백 제거. **저장 전에 반드시 통과시킨다.**

    정규화 없이 UNIQUE만 걸면 Foo@x.com 과 foo@x.com 이 별개 계정이 된다.
    """
    return email.strip().lower()


def get_by_email(db: DbSession, email: str) -> User | None:
    return db.exec(select(User).where(User.email == normalize_email(email))).first()


def _nickname_exists(db: DbSession, nickname: str, *, exclude_user_id: str | None = None) -> bool:
    stmt = select(func.count()).select_from(User).where(
        func.lower(col(User.nickname)) == nickname.lower()
    )
    if exclude_user_id:
        stmt = stmt.where(User.id != exclude_user_id)
    return int(db.exec(stmt).one()) > 0


def validate_nickname(db: DbSession, nickname: str, *, exclude_user_id: str | None = None) -> str:
    """길이 · 문자 · 금지어 · 중복을 전부 검사하고 정리된 닉네임을 돌려준다."""
    s = get_settings()
    cleaned = nickname.strip()

    if len(cleaned) < s.nickname_min_length or len(cleaned) > s.nickname_max_length:
        raise InvalidNickname(
            f"닉네임은 {s.nickname_min_length}~{s.nickname_max_length}자여야 합니다."
        )
    # 한글/영문/숫자/밑줄만. 공백과 특수문자는 사칭과 렌더링 문제를 만든다.
    if not re.fullmatch(r"[0-9A-Za-z가-힣_]+", cleaned):
        raise InvalidNickname("닉네임에는 한글, 영문, 숫자, 밑줄만 쓸 수 있습니다.")

    lowered = cleaned.lower()
    if any(banned in lowered for banned in s.banned_nickname_list):
        raise InvalidNickname("사용할 수 없는 닉네임입니다.")

    if _nickname_exists(db, cleaned, exclude_user_id=exclude_user_id):
        raise NicknameTaken(cleaned)

    return cleaned


def _unique_nickname_from_name(db: DbSession, name: str) -> str:
    """가입 시 기본 닉네임. 이름이 겹치면 뒤에 숫자를 붙인다."""
    s = get_settings()
    base = re.sub(r"[^0-9A-Za-z가-힣_]", "", name.strip()) or "학습자"
    base = base[: s.nickname_max_length]
    if len(base) < s.nickname_min_length:
        base = (base + "학습자")[: s.nickname_max_length]

    candidate = base
    suffix = 1
    while _nickname_exists(db, candidate):
        tail = str(suffix)
        candidate = base[: s.nickname_max_length - len(tail)] + tail
        suffix += 1
    return candidate


def resolve_organization(
    db: DbSession, *, role: UserRole, invite_code: str | None, email: str
) -> Organization | None:
    """가입 시 소속 기관을 정한다.

    **EDUCATOR는 기관 초대 코드가 필수다.** 없으면 누구나 role="EDUCATOR"로
    가입해서 남의 강의 API를 두드릴 수 있다 -- 역할을 요청 body로 받는 이상
    가입 자체에 게이트가 있어야 한다.

    학생은 코드가 있으면 쓰고, 없으면 이메일 도메인으로 자동 연결한다.
    """
    if invite_code:
        org = db.exec(
            select(Organization).where(Organization.invite_code == invite_code.strip())
        ).first()
        if org is None or not org.is_active:
            raise InvalidInviteCode()
        if org.domain and not normalize_email(email).endswith("@" + org.domain.lower()):
            raise InvalidInviteCode(f"{org.name} 는 @{org.domain} 이메일만 가입할 수 있습니다.")
        return org

    if role is UserRole.EDUCATOR:
        raise InvalidInviteCode("교수자 가입에는 기관 초대 코드가 필요합니다.")

    # 학생: 이메일 도메인이 제휴 기관과 맞으면 자동 연결
    domain = normalize_email(email).split("@")[-1]
    return db.exec(
        select(Organization)
        .where(Organization.domain == domain)
        .where(Organization.is_active == True)  # noqa: E712
    ).first()


def signup(
    db: DbSession,
    *,
    name: str,
    email: str,
    password: str,
    role: UserRole = UserRole.STUDENT,
    invite_code: str | None = None,
    course_invite_code: str | None = None,
) -> tuple[User, str]:
    """회원가입. 반환값 (user, access_token). commit은 호출자가 한다."""
    normalized = normalize_email(email)
    if get_by_email(db, normalized) is not None:
        raise EmailAlreadyRegistered()

    # ADMIN은 API로 만들 수 없다. 필요하면 DB에서 직접 승격한다.
    if role is UserRole.ADMIN:
        raise InvalidInviteCode("관리자 계정은 가입으로 만들 수 없습니다.")

    course = None
    if course_invite_code:
        if role is not UserRole.STUDENT:
            raise InvalidInviteCode("강의 초대 코드는 학생 계정에만 사용할 수 있습니다.")
        course = db.exec(
            select(Course).where(Course.invite_code == course_invite_code.strip())
        ).first()
        if course is None or not course.is_active:
            raise InvalidInviteCode("강의 초대 코드가 올바르지 않습니다.")

    org = resolve_organization(db, role=role, invite_code=invite_code, email=normalized)
    if course is not None:
        org = db.get(Organization, course.organization_id)

    user = User(
        email=normalized,
        password_hash=hash_password(password),
        name=name.strip(),
        nickname=_unique_nickname_from_name(db, name),
        role=role,
        organization_id=org.id if org else None,
        last_login_at=utcnow(),
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        # 동시 가입 경합. UNIQUE 제약이 최종 방어선이다.
        db.rollback()
        raise EmailAlreadyRegistered() from None

    if course is not None:
        db.add(Enrollment(course_id=course.id, student_id=user.id, status=EnrollmentStatus.ACTIVE))
        db.flush()

    return user, create_access_token(user.id)


def login(db: DbSession, *, email: str, password: str) -> tuple[User, str]:
    user = get_by_email(db, email)
    # 사용자가 없어도 해시 검증을 수행해 응답 시간 차이로 계정 존재가 드러나지 않게 한다.
    dummy = "$2b$12$" + "x" * 53
    if user is None:
        verify_password(password, dummy)
        raise InvalidCredentials()
    if not user.is_active or not verify_password(password, user.password_hash):
        raise InvalidCredentials()

    user.last_login_at = utcnow()
    user.updated_at = utcnow()
    db.add(user)
    db.flush()
    return user, create_access_token(user.id)
