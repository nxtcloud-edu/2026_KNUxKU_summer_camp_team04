"""강의 관리 + 학생 통계 계산.

권한 모델:
  * 모든 교육자 API는 EDUCATOR 역할을 요구한다 (auth/deps.require_educator)
  * 그 위에 **강의 소유권**을 다시 본다 -- EDUCATOR라고 남의 강의를 볼 수는 없다
  * 소유하지 않은 강의는 403이 아니라 **404**다. 403은 "그 강의는 존재한다"를
    알려주므로 id를 훑어 타 기관의 강의 목록을 추정할 수 있다.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session as DbSession
from sqlmodel import col, func, select

from app.clock import seconds_between, utcnow
from app.config import get_settings
from app.enums import (
    EnrollmentStatus,
    EventType,
    JudgeStatus,
    LearningStatus,
    ProgressStatus,
    UserRole,
)
from app.errors import (
    AlreadyEnrolled,
    CourseNotFound,
    StudentNotInCourse,
)
from app.models import (
    Course,
    CourseProblem,
    Enrollment,
    Event,
    Session,
    StudentCourseStats,
    User,
    UserProblemProgress,
)
from app.problems.service import ProblemRepository

log = logging.getLogger(__name__)


def new_invite_code() -> str:
    return secrets.token_urlsafe(9)


# --------------------------------------------------------------------- 강의


def require_course(db: DbSession, course_id: str, educator: User) -> Course:
    """강의를 가져오되 **소유권을 함께 본다.**

    ADMIN은 모든 강의를 볼 수 있다. 그 외에는 담당 교수자만이다.
    """
    course = db.get(Course, course_id)
    if course is None:
        raise CourseNotFound(course_id)
    if UserRole(educator.role) is not UserRole.ADMIN and course.educator_id != educator.id:
        raise CourseNotFound(course_id)
    return course


def list_courses(db: DbSession, educator: User) -> list[Course]:
    stmt = select(Course).order_by(col(Course.created_at).desc())
    if UserRole(educator.role) is not UserRole.ADMIN:
        stmt = stmt.where(Course.educator_id == educator.id)
    return list(db.exec(stmt).all())


def create_course(
    db: DbSession,
    educator: User,
    *,
    title: str,
    term: str,
    organization_id: str | None,
    code_visibility: str,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    problem_ids: list[str] | None = None,
) -> Course:
    org_id = organization_id or educator.organization_id
    if not org_id:
        # 교수자는 가입 시 기관 코드를 통과했으므로 보통 여기 오지 않는다.
        raise CourseNotFound("organization")

    course = Course(
        organization_id=org_id,
        title=title.strip(),
        term=term.strip(),
        educator_id=educator.id,
        invite_code=new_invite_code(),
        code_visibility=code_visibility,
        start_at=start_at,
        end_at=end_at,
    )
    db.add(course)
    db.flush()

    for i, pid in enumerate(problem_ids or []):
        db.add(CourseProblem(course_id=course.id, problem_id=pid, order=i))
    db.flush()
    return course


def assigned_problem_ids(db: DbSession, course: Course, repo: ProblemRepository) -> list[str]:
    """진도율의 분모.

    강의에 배정 문제가 없으면 저장소 전체를 쓴다 -- 강의를 막 만들었을 때
    분모가 0이 되어 진도율이 NaN 이 되는 것을 막는다.
    """
    rows = db.exec(
        select(CourseProblem)
        .where(CourseProblem.course_id == course.id)
        .order_by(col(CourseProblem.order))
    ).all()
    if rows:
        return [r.problem_id for r in rows]
    return [p.problem_id for p in repo.list()]


# --------------------------------------------------------------------- 수강


def list_enrollments(db: DbSession, course_id: str) -> list[Enrollment]:
    return list(
        db.exec(
            select(Enrollment)
            .where(Enrollment.course_id == course_id)
            .where(Enrollment.status == EnrollmentStatus.ACTIVE)
        ).all()
    )


def enroll_student(db: DbSession, course: Course, student: User) -> Enrollment:
    if UserRole(student.role) is not UserRole.STUDENT:
        raise StudentNotInCourse(student.id)

    row = Enrollment(
        course_id=course.id, student_id=student.id, status=EnrollmentStatus.ACTIVE
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise AlreadyEnrolled() from None
    return row


def require_enrolled(db: DbSession, course_id: str, student_id: str) -> Enrollment:
    row = db.exec(
        select(Enrollment)
        .where(Enrollment.course_id == course_id)
        .where(Enrollment.student_id == student_id)
    ).first()
    if row is None:
        raise StudentNotInCourse(student_id)
    return row


def drop_student(db: DbSession, course_id: str, student_id: str) -> None:
    row = require_enrolled(db, course_id, student_id)
    row.status = EnrollmentStatus.DROPPED
    db.add(row)
    db.flush()


# --------------------------------------------------------------------- 통계 계산

# risk_score 구간 (요구사항 §5)
RISK_ON_TRACK = 40
RISK_WATCH = 70
# 이 시간 이상 활동이 없으면 INACTIVE
INACTIVE_HOURS = 72


def _weak_concept(
    db: DbSession, student_id: str, course_id: str, repo: ProblemRepository
) -> tuple[str | None, int]:
    """실패가 가장 많이 쌓인 개념. (concept, 실패 시도 수)

    문제의 concept 태그와 진행 상태의 실패 횟수를 곱해서 센다.
    개념 태그가 비어 있는 문제(judge의 stdout_* 23개)는 셀 수 없다 --
    BE1이 concept을 채우면 이 함수가 그대로 좋아진다.
    """
    rows = db.exec(
        select(UserProblemProgress)
        .where(UserProblemProgress.user_id == student_id)
        .where(UserProblemProgress.course_id == course_id)
    ).all()

    tally: dict[str, int] = {}
    for r in rows:
        failures = max(0, r.attempt_count - (1 if r.status == ProgressStatus.SOLVED else 0))
        if failures <= 0 or not repo.exists(r.problem_id):
            continue
        for concept in repo.get(r.problem_id).concepts:
            tally[concept] = tally.get(concept, 0) + failures

    if not tally:
        return None, 0
    best = max(tally.items(), key=lambda kv: kv[1])
    return best[0], best[1]


def recalculate_stats(
    db: DbSession,
    *,
    course: Course,
    student: User,
    repo: ProblemRepository,
    now: datetime | None = None,
) -> StudentCourseStats:
    """한 학생의 강의 통계를 다시 계산한다. commit은 호출자가 한다.

    채점이 끝날 때마다 그 학생 행 하나만 갱신한다. 대시보드가 열릴 때마다
    28명 × 26문제의 events를 훑는 것보다 훨씬 싸다.
    """
    now = now or utcnow()
    assigned = assigned_problem_ids(db, course, repo)
    assigned_set = set(assigned)

    rows = db.exec(
        select(UserProblemProgress)
        .where(UserProblemProgress.user_id == student.id)
        .where(UserProblemProgress.course_id == course.id)
    ).all()

    solved = sum(1 for r in rows if r.status == ProgressStatus.SOLVED and r.problem_id in assigned_set)
    attempts = sum(r.attempt_count for r in rows)
    last_active = max((r.last_attempted_at for r in rows if r.last_attempted_at), default=None)
    progress_rate = round(100 * solved / len(assigned)) if assigned else 0

    concept, failed_attempts = _weak_concept(db, student.id, course.id, repo)

    # ---- risk_score ----------------------------------------------------
    # 0~100. 낮을수록 순조롭다. 각 항목은 독립적으로 더해지고 100에서 자른다.
    score = 0
    reasons: list[str] = []

    if not rows:
        score += 55
        reasons.append("아직 이 강의의 문제를 시작하지 않았습니다")
    else:
        # 1) 진도가 뒤처질수록
        behind = max(0, 60 - progress_rate)
        score += round(behind * 0.5)  # 최대 30
        if progress_rate < 40:
            reasons.append(f"진도율 {progress_rate}%")

        # 2) 시도 대비 통과율이 낮을수록
        if attempts >= 5:
            pass_rate = solved / attempts
            if pass_rate < 0.2:
                score += 20
                reasons.append(f"{attempts}회 시도 중 {solved}문제 해결")

        # 3) 같은 문제를 오래 붙들고 있으면
        stuck = [r for r in rows if r.status != ProgressStatus.SOLVED and r.attempt_count >= 4]
        if stuck:
            score += 15
            worst = max(stuck, key=lambda r: r.attempt_count)
            reasons.append(f"같은 문제를 {worst.attempt_count}회 시도 중")

    # 4) 오래 접속하지 않았으면
    inactive_hours = (
        seconds_between(last_active, now) / 3600 if last_active else INACTIVE_HOURS + 1
    )
    if inactive_hours >= INACTIVE_HOURS:
        score += 25
        if last_active:
            reasons.append(f"{int(inactive_hours)}시간 동안 활동 없음")

    # 5) 개입이 반복적으로 발생했으면 (trace/monitor 가 이미 판단한 것)
    trigger_count = _agent_trigger_count(db, student.id, course.id)
    if trigger_count >= 2:
        score += 10
        reasons.append(f"AI 튜터 개입 {trigger_count}회")

    score = max(0, min(100, score))

    if inactive_hours >= INACTIVE_HOURS and rows:
        status = LearningStatus.INACTIVE
    elif score >= RISK_WATCH:
        status = LearningStatus.NEEDS_HELP
    elif score >= RISK_ON_TRACK:
        status = LearningStatus.WATCH
    else:
        status = LearningStatus.ON_TRACK

    if concept and status in (LearningStatus.WATCH, LearningStatus.NEEDS_HELP):
        reasons.append(f"{concept} 개념에서 {failed_attempts}회 실패")

    stats = db.exec(
        select(StudentCourseStats)
        .where(StudentCourseStats.course_id == course.id)
        .where(StudentCourseStats.student_id == student.id)
    ).first()
    if stats is None:
        stats = StudentCourseStats(course_id=course.id, student_id=student.id, learning_status=status)
        db.add(stats)

    stats.progress_rate = progress_rate
    stats.solved_count = solved
    stats.assigned_count = len(assigned)
    stats.attempt_count = attempts
    stats.last_active_at = last_active
    stats.learning_status = status
    stats.primary_weak_concept = concept
    stats.risk_score = score
    stats.reasons = reasons
    stats.calculated_at = now
    db.add(stats)
    db.flush()
    return stats


def _agent_trigger_count(db: DbSession, student_id: str, course_id: str) -> int:
    """이 학생이 이 강의에서 받은 AGENT_TRIGGER 수.

    세션에는 course_id가 없으므로 사용자 소유 세션 전체를 센다.
    강의별로 나누려면 sessions 에 course_id 를 추가해야 하는데, 지금은
    "이 학생이 얼마나 막혔나"의 근사값으로 충분하다.
    """
    return int(
        db.exec(
            select(func.count())
            .select_from(Event)
            .join(Session, col(Event.session_id) == col(Session.id))
            .where(Session.user_id == student_id)
            .where(Event.type == EventType.AGENT_TRIGGER)
        ).one()
    )


def course_ids_assigned(
    db: DbSession, student_id: str, problem_id: str, repo: ProblemRepository
) -> list[str]:
    """이 학생이 수강 중인 강의 중 **이 문제를 배정한** 강의 id들.

    채점 결과를 어느 강의의 진행 상태에 반영할지 정한다. 배정 목록이 비어 있는
    강의는 전체 문제를 배정한 것으로 본다(assigned_problem_ids 와 같은 규칙).
    """
    out: list[str] = []
    for e in db.exec(
        select(Enrollment)
        .where(Enrollment.student_id == student_id)
        .where(Enrollment.status == EnrollmentStatus.ACTIVE)
    ).all():
        course = db.get(Course, e.course_id)
        if course is None or not course.is_active:
            continue
        if problem_id in set(assigned_problem_ids(db, course, repo)):
            out.append(course.id)
    return out


def recalculate_for_student(
    db: DbSession, *, student: User, problem_id: str, repo: ProblemRepository
) -> None:
    """학생이 속한 **모든 강의**의 통계를 갱신한다.

    채점 직후에 호출된다. 학생이 여러 강의를 들을 수 있고 같은 문제가
    여러 강의에 배정될 수 있으므로 전부 돈다 (보통 1~2개).
    """
    course_ids = [
        e.course_id
        for e in db.exec(
            select(Enrollment)
            .where(Enrollment.student_id == student.id)
            .where(Enrollment.status == EnrollmentStatus.ACTIVE)
        ).all()
    ]
    for cid in course_ids:
        course = db.get(Course, cid)
        if course is None:
            continue
        try:
            recalculate_stats(db, course=course, student=student, repo=repo)
        except Exception:  # noqa: BLE001 - 통계 실패가 채점을 막으면 안 된다
            log.exception("통계 갱신 실패 (course=%s, student=%s)", cid, student.id)
