"""교육자 API.

**모든 엔드포인트가 두 겹으로 막힌다.**
  1. `require_educator` -- EDUCATOR(또는 ADMIN) 역할
  2. `require_course`   -- 그 강의의 담당 교수자인지

프런트에서 버튼을 숨기는 것은 보안이 아니다.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlmodel import Session as DbSession
from sqlmodel import col, select

from app.auth import service as auth_service
from app.auth.deps import get_current_user, require_educator
from app.db import get_db
from app.educator import service
from app.educator.schemas import (
    AttentionItem,
    AttentionListRead,
    CourseBrief,
    CourseCreate,
    CourseJoinRequest,
    CourseRead,
    DashboardMetrics,
    DashboardRead,
    EnrollRequest,
    ProblemActivity,
    StudentBrief,
    StudentCourseRead,
    StudentDetailRead,
    StudentListRead,
    StudentRow,
    StudentSummary,
    WeakConcept,
)
from app.enums import CodeVisibility, LearningStatus, ProgressStatus
from app.errors import StudentNotInCourse, UserNotFound
from app.models import Course, Enrollment, StudentCourseStats, User, UserProblemProgress
from app.enums import EnrollmentStatus, UserRole
from app.problems.service import ProblemRepository, get_problem_repository

router = APIRouter(tags=["educator"])


# --------------------------------------------------------------------- 학생의 강의 참여


@router.get("/student/courses", response_model=list[StudentCourseRead], tags=["student"])
def student_courses(
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
    repo: ProblemRepository = Depends(get_problem_repository),
) -> list[StudentCourseRead]:
    if UserRole(user.role) is not UserRole.STUDENT:
        return []
    enrollments = db.exec(
        select(Enrollment)
        .where(Enrollment.student_id == user.id)
        .where(Enrollment.status == EnrollmentStatus.ACTIVE)
    ).all()
    out: list[StudentCourseRead] = []
    for enrollment in enrollments:
        course = db.get(Course, enrollment.course_id)
        if course is None or not course.is_active:
            continue
        educator = db.get(User, course.educator_id)
        out.append(StudentCourseRead(
            id=course.id,
            title=course.title,
            term=course.term,
            educator_name=educator.name if educator else "교수자",
            assigned_problem_count=len(service.assigned_problem_ids(db, course, repo)),
        ))
    return out


@router.post("/student/courses/join", response_model=StudentCourseRead, status_code=status.HTTP_201_CREATED, tags=["student"])
def join_course(
    body: CourseJoinRequest,
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
    repo: ProblemRepository = Depends(get_problem_repository),
) -> StudentCourseRead:
    if UserRole(user.role) is not UserRole.STUDENT:
        raise StudentNotInCourse(user.id)
    course = db.exec(select(Course).where(Course.invite_code == body.invite_code.strip())).first()
    if course is None or not course.is_active:
        from app.errors import InvalidInviteCode
        raise InvalidInviteCode("강의 초대 코드가 올바르지 않습니다.")
    service.enroll_student(db, course, user)
    service.recalculate_stats(db, course=course, student=user, repo=repo)
    db.commit()
    educator = db.get(User, course.educator_id)
    return StudentCourseRead(
        id=course.id, title=course.title, term=course.term,
        educator_name=educator.name if educator else "교수자",
        assigned_problem_count=len(service.assigned_problem_ids(db, course, repo)),
    )


def _stats_map(db: DbSession, course_id: str) -> dict[str, StudentCourseStats]:
    rows = db.exec(
        select(StudentCourseStats).where(StudentCourseStats.course_id == course_id)
    ).all()
    return {r.student_id: r for r in rows}


def _students_of(db: DbSession, course_id: str) -> list[User]:
    ids = [e.student_id for e in service.list_enrollments(db, course_id)]
    if not ids:
        return []
    return list(db.exec(select(User).where(col(User.id).in_(ids))).all())


# --------------------------------------------------------------------- 강의


@router.get("/educator/courses", response_model=list[CourseRead])
def list_courses(
    educator: User = Depends(require_educator),
    db: DbSession = Depends(get_db),
    repo: ProblemRepository = Depends(get_problem_repository),
) -> list[CourseRead]:
    out = []
    for c in service.list_courses(db, educator):
        out.append(
            CourseRead.build(
                c,
                educator_name=educator.name,
                student_count=len(service.list_enrollments(db, c.id)),
                assigned=len(service.assigned_problem_ids(db, c, repo)),
            )
        )
    return out


@router.post(
    "/educator/courses", response_model=CourseRead, status_code=status.HTTP_201_CREATED
)
def create_course(
    body: CourseCreate,
    educator: User = Depends(require_educator),
    db: DbSession = Depends(get_db),
    repo: ProblemRepository = Depends(get_problem_repository),
) -> CourseRead:
    course = service.create_course(
        db,
        educator,
        title=body.title,
        term=body.term,
        organization_id=body.organization_id,
        code_visibility=body.code_visibility.value,
        start_at=body.start_at,
        end_at=body.end_at,
        problem_ids=body.problem_ids,
    )
    db.commit()
    db.refresh(course)
    return CourseRead.build(
        course,
        educator_name=educator.name,
        student_count=0,
        assigned=len(service.assigned_problem_ids(db, course, repo)),
    )


@router.get("/educator/courses/{course_id}", response_model=CourseRead)
def get_course(
    course_id: str,
    educator: User = Depends(require_educator),
    db: DbSession = Depends(get_db),
    repo: ProblemRepository = Depends(get_problem_repository),
) -> CourseRead:
    course = service.require_course(db, course_id, educator)
    return CourseRead.build(
        course,
        educator_name=educator.name,
        student_count=len(service.list_enrollments(db, course.id)),
        assigned=len(service.assigned_problem_ids(db, course, repo)),
    )


@router.post(
    "/educator/courses/{course_id}/students", status_code=status.HTTP_201_CREATED
)
def add_student(
    course_id: str,
    body: EnrollRequest,
    educator: User = Depends(require_educator),
    db: DbSession = Depends(get_db),
    repo: ProblemRepository = Depends(get_problem_repository),
) -> dict:
    course = service.require_course(db, course_id, educator)
    student = auth_service.get_by_email(db, body.email)
    if student is None:
        raise UserNotFound(body.email)

    service.enroll_student(db, course, student)
    # 등록 즉시 통계를 만들어둔다. 안 그러면 목록에서 이 학생만 빈 행이 된다.
    service.recalculate_stats(db, course=course, student=student, repo=repo)
    db.commit()
    return {"student_id": student.id, "name": student.name, "email": student.email}


@router.delete(
    "/educator/courses/{course_id}/students/{student_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
def remove_student(
    course_id: str,
    student_id: str,
    educator: User = Depends(require_educator),
    db: DbSession = Depends(get_db),
) -> Response:
    """수강 취소. 행을 지우지 않고 DROPPED 로 바꾼다 --
    그 학생이 남긴 진행 상태와 통계는 기록으로 남아야 한다."""
    service.require_course(db, course_id, educator)
    service.drop_student(db, course_id, student_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------- 대시보드


@router.get("/educator/courses/{course_id}/dashboard", response_model=DashboardRead)
def dashboard(
    course_id: str,
    educator: User = Depends(require_educator),
    db: DbSession = Depends(get_db),
    repo: ProblemRepository = Depends(get_problem_repository),
) -> DashboardRead:
    """상단 지표 4개.

    지표 정의 (요구사항 §3이 팀 결정으로 남겨둔 것 -- 여기서 확정한다):
      * average_progress  = 학생별 진도율의 평균
      * completion_rate   = (전체 학생 × 배정 문제) 중 해결한 칸의 비율
      * total_attempts    = 채점 실행 횟수 합 (run + submit 모두)
      * needs_attention   = learning_status 가 NEEDS_HELP 또는 INACTIVE 인 학생 수

    average_progress 와 completion_rate 는 학생마다 배정 문제 수가 같으면
    수치가 같아진다. 다른 건 학생별 배정이 갈릴 때뿐이다.
    """
    course = service.require_course(db, course_id, educator)
    students = _students_of(db, course.id)
    stats = _stats_map(db, course.id)
    assigned = len(service.assigned_problem_ids(db, course, repo))

    rows = [stats.get(u.id) for u in students]
    present = [r for r in rows if r is not None]

    average_progress = round(sum(r.progress_rate for r in present) / len(present)) if present else 0
    total_cells = len(students) * assigned
    solved_cells = sum(r.solved_count for r in present)
    completion_rate = round(100 * solved_cells / total_cells) if total_cells else 0
    total_attempts = sum(r.attempt_count for r in present)
    needs_attention = sum(
        1
        for r in present
        if LearningStatus(r.learning_status)
        in (LearningStatus.NEEDS_HELP, LearningStatus.INACTIVE)
    )

    return DashboardRead(
        course=CourseBrief(
            id=course.id, title=course.title, term=course.term, educator_name=educator.name
        ),
        metrics=DashboardMetrics(
            student_count=len(students),
            # 델타는 과거 스냅샷이 있어야 계산된다. 지금은 0으로 고정하고
            # 프런트가 "+2" 뱃지를 감출 수 있게 명시적으로 내려준다.
            student_count_delta=0,
            average_progress=average_progress,
            weekly_progress_delta=0,
            completion_rate=completion_rate,
            total_attempts=total_attempts,
            needs_attention_count=needs_attention,
        ),
    )


# --------------------------------------------------------------------- 학생 목록


_SORTS = {
    "progress_asc": (lambda r: r[1].progress_rate if r[1] else 0, False),
    "progress_desc": (lambda r: r[1].progress_rate if r[1] else 0, True),
    "risk_desc": (lambda r: r[1].risk_score if r[1] else 0, True),
    "name_asc": (lambda r: r[0].name, False),
}


@router.get("/educator/courses/{course_id}/students", response_model=StudentListRead)
def list_students(
    course_id: str,
    q: str | None = Query(default=None, max_length=64),
    status_filter: LearningStatus | None = Query(default=None, alias="status"),
    sort: str = Query(default="risk_desc"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=30, ge=1, le=100),
    educator: User = Depends(require_educator),
    db: DbSession = Depends(get_db),
) -> StudentListRead:
    course = service.require_course(db, course_id, educator)
    stats = _stats_map(db, course.id)
    pairs = [(u, stats.get(u.id)) for u in _students_of(db, course.id)]

    if q:
        needle = q.strip().lower()
        pairs = [p for p in pairs if needle in p[0].name.lower() or needle in p[0].email.lower()]
    if status_filter is not None:
        pairs = [
            p
            for p in pairs
            if p[1] is not None and LearningStatus(p[1].learning_status) is status_filter
        ]

    key, reverse = _SORTS.get(sort, _SORTS["risk_desc"])
    pairs.sort(key=key, reverse=reverse)

    total = len(pairs)
    start = (page - 1) * size
    window = pairs[start : start + size]

    return StudentListRead(
        items=[StudentRow.build(u, s) for u, s in window],
        total=total,
        page=page,
        size=size,
    )


@router.get("/educator/courses/{course_id}/attention", response_model=AttentionListRead)
def attention(
    course_id: str,
    limit: int = Query(default=10, ge=1, le=50),
    educator: User = Depends(require_educator),
    db: DbSession = Depends(get_db),
) -> AttentionListRead:
    """지금 확인해야 할 학생. risk_score 높은 순."""
    course = service.require_course(db, course_id, educator)
    stats = _stats_map(db, course.id)
    students = {u.id: u for u in _students_of(db, course.id)}

    rows = [
        s
        for s in stats.values()
        if s.student_id in students
        and LearningStatus(s.learning_status)
        in (LearningStatus.NEEDS_HELP, LearningStatus.WATCH, LearningStatus.INACTIVE)
    ]
    rows.sort(key=lambda s: s.risk_score, reverse=True)

    return AttentionListRead(
        items=[
            AttentionItem(
                student_id=s.student_id,
                name=students[s.student_id].name,
                status=LearningStatus(s.learning_status),
                progress=s.progress_rate,
                risk_score=s.risk_score,
                weak_concept=s.primary_weak_concept,
                reasons=list(s.reasons or []),
            )
            for s in rows[:limit]
        ]
    )


# --------------------------------------------------------------------- 학생 상세


@router.get(
    "/educator/courses/{course_id}/students/{student_id}", response_model=StudentDetailRead
)
def student_detail(
    course_id: str,
    student_id: str,
    educator: User = Depends(require_educator),
    db: DbSession = Depends(get_db),
    repo: ProblemRepository = Depends(get_problem_repository),
) -> StudentDetailRead:
    course = service.require_course(db, course_id, educator)
    service.require_enrolled(db, course.id, student_id)

    student = db.get(User, student_id)
    if student is None:
        raise StudentNotInCourse(student_id)

    stats = db.exec(
        select(StudentCourseStats)
        .where(StudentCourseStats.course_id == course.id)
        .where(StudentCourseStats.student_id == student_id)
    ).first()

    rows = db.exec(
        select(UserProblemProgress)
        .where(UserProblemProgress.user_id == student_id)
        .where(UserProblemProgress.course_id == course.id)
        .order_by(col(UserProblemProgress.last_attempted_at).desc())
    ).all()

    visibility = CodeVisibility(course.code_visibility)

    activity: list[ProblemActivity] = []
    for r in rows[:20]:
        title = repo.get(r.problem_id).title if repo.exists(r.problem_id) else r.problem_id
        # **교수자가 강의별로 정한 정책에 따라 코드를 채운다.**
        code: str | None = None
        kind: str | None = None
        if visibility is CodeVisibility.LATEST_SNAPSHOT and r.current_code:
            code, kind = r.current_code, "LATEST_SNAPSHOT"
        elif visibility is CodeVisibility.SUBMITTED_ONLY and r.last_submitted_code:
            code, kind = r.last_submitted_code, "SUBMITTED"

        activity.append(
            ProblemActivity(
                problem_id=r.problem_id,
                title=title,
                status=str(r.status),
                best_passed=r.best_passed,
                total_tests=r.total_tests,
                attempt_count=r.attempt_count,
                last_judge_status=r.last_judge_status,
                last_attempted_at=r.last_attempted_at,
                code=code,
                code_kind=kind,
            )
        )

    concept, failed = service._weak_concept(db, student_id, course.id, repo)
    weak = (
        [WeakConcept(concept=concept, score=max(0, 100 - failed * 10), failed_attempts=failed)]
        if concept
        else []
    )

    recommendations: list[str] = []
    if concept:
        recommendations.append(f"{concept} 개념 기초 문제 재배정")
    unsolved = [r for r in rows if r.status != ProgressStatus.SOLVED and r.attempt_count >= 3]
    if unsolved:
        worst = max(unsolved, key=lambda r: r.attempt_count)
        title = repo.get(worst.problem_id).title if repo.exists(worst.problem_id) else worst.problem_id
        recommendations.append(f"'{title}' 개별 힌트 전송")
    if stats and LearningStatus(stats.learning_status) is LearningStatus.INACTIVE:
        recommendations.append("장기 미접속 — 개별 연락 필요")

    return StudentDetailRead(
        student=StudentBrief(
            id=student.id, name=student.name, email=student.email, avatar_url=student.avatar_url
        ),
        summary=StudentSummary(
            progress=stats.progress_rate if stats else 0,
            solved_count=stats.solved_count if stats else 0,
            attempt_count=stats.attempt_count if stats else 0,
            last_active_at=stats.last_active_at if stats else None,
            risk_score=stats.risk_score if stats else 0,
            learning_status=LearningStatus(stats.learning_status)
            if stats
            else LearningStatus.INACTIVE,
        ),
        weak_concepts=weak,
        recent_activity=activity,
        recommendations=recommendations,
        code_visibility=visibility,
    )
