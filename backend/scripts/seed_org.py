"""기관 · 교수자 · 강의 · 학생을 만드는 부트스트랩.

주의: 이메일 도메인은 **실제로 존재하는 형식**이어야 한다. @demo.local 같은
예약 TLD 는 EmailStr(email-validator)이 거부하므로, 시드로 만든 계정이
로그인 API 를 통과하지 못한다 -- 모델을 직접 쓰는 이 스크립트는 통과하고
로그인만 막히므로 조용히 틀린다.

**이게 없으면 EDUCATOR 로 가입할 수 없다.** 교수자 가입은 기관 초대 코드를
요구하는데(auth/service.resolve_organization), Organization 을 만드는 API 가
아직 없기 때문이다. 관리자 화면이 생기기 전까지 이 스크립트가 그 자리를 메운다.

실행:
    cd backend && python -m scripts.seed_org

출력된 초대 코드로 교수자가 가입하거나, 함께 만들어진 데모 계정으로 바로 로그인한다.
"""
from __future__ import annotations

import sys

from sqlmodel import Session, select

from app.auth.security import hash_password
from app.clock import utcnow
from app.db import get_engine, init_db
from app.educator import service as educator_service
from app.enums import UserRole
from app.models import Organization, User
from app.problems.service import get_problem_repository

ORG_NAME = "강원대학교"
ORG_INVITE_CODE = "KNU-2026"
EDUCATOR_EMAIL = "educator@example.com"
STUDENT_EMAILS = ["student1@example.com", "student2@example.com"]
PASSWORD = "password123"


def _get_or_create_user(
    db: Session, *, email: str, name: str, nickname: str, role: UserRole, org_id: str | None
) -> User:
    found = db.exec(select(User).where(User.email == email)).first()
    if found is not None:
        return found
    user = User(
        email=email,
        password_hash=hash_password(PASSWORD),
        name=name,
        nickname=nickname,
        role=role,
        organization_id=org_id,
        last_login_at=utcnow(),
    )
    db.add(user)
    db.flush()
    return user


def main() -> int:
    init_db()
    repo = get_problem_repository()

    with Session(get_engine()) as db:
        org = db.exec(
            select(Organization).where(Organization.invite_code == ORG_INVITE_CODE)
        ).first()
        if org is None:
            # domain 을 비워둔다 -- 데모 계정이 @example.com 이라 도메인 검사를 켜면 막힌다.
            org = Organization(name=ORG_NAME, domain="", invite_code=ORG_INVITE_CODE)
            db.add(org)
            db.flush()

        educator = _get_or_create_user(
            db,
            email=EDUCATOR_EMAIL,
            name="김튜토리",
            nickname="김튜토리",
            role=UserRole.EDUCATOR,
            org_id=org.id,
        )

        students = [
            _get_or_create_user(
                db,
                email=em,
                name=f"학생{i}",
                nickname=f"학생{i}",
                role=UserRole.STUDENT,
                org_id=org.id,
            )
            for i, em in enumerate(STUDENT_EMAILS, start=1)
        ]

        courses = educator_service.list_courses(db, educator)
        if courses:
            course = courses[0]
        else:
            course = educator_service.create_course(
                db,
                educator,
                title="Python 기초 01",
                term="2026 여름학기",
                organization_id=org.id,
                code_visibility="SUBMITTED_ONLY",
            )

        for s in students:
            try:
                educator_service.enroll_student(db, course, s)
            except Exception:  # noqa: BLE001 - 이미 등록됨
                db.rollback()
                continue
            educator_service.recalculate_stats(db, course=course, student=s, repo=repo)

        db.commit()
        db.refresh(org)
        db.refresh(course)

        print()
        print("=" * 62)
        print("기관 · 교수자 · 강의 부트스트랩 완료")
        print("=" * 62)
        print(f"  기관        {org.name}")
        print(f"  기관 초대코드 {org.invite_code}   <- 교수자 가입에 쓴다")
        print()
        print(f"  교수자      {EDUCATOR_EMAIL} / {PASSWORD}")
        for em in STUDENT_EMAILS:
            print(f"  학생        {em} / {PASSWORD}")
        print()
        print(f"  강의        {course.title} ({course.term})")
        print(f"  강의 초대코드 {course.invite_code}")
        print(f"  코드 열람    {course.code_visibility}")
        print()
        print("  확인:")
        print("    TOKEN=$(curl -s -X POST localhost:8000/auth/login -H 'Content-Type: application/json' \\")
        print(f"      -d '{{\"email\":\"{EDUCATOR_EMAIL}\",\"password\":\"{PASSWORD}\"}}' | python3 -c 'import json,sys;print(json.load(sys.stdin)[\"access_token\"])')")
        print(f"    curl -s localhost:8000/educator/courses/{course.id}/dashboard -H \"Authorization: Bearer $TOKEN\" | python3 -m json.tool")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
