from __future__ import annotations

from pydantic import BaseModel, Field

from app.enums import CodeVisibility, LearningStatus
from app.models import Course, StudentCourseStats, User
from app.schemas_common import UtcDatetime


class CourseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=128)
    term: str = Field(default="", max_length=64)
    organization_id: str | None = None
    code_visibility: CodeVisibility = CodeVisibility.SUBMITTED_ONLY
    start_at: UtcDatetime | None = None
    end_at: UtcDatetime | None = None
    # 진도율의 분모. 비우면 저장소의 전체 문제를 쓴다.
    problem_ids: list[str] = Field(default_factory=list, max_length=200)


class CourseRead(BaseModel):
    id: str
    organization_id: str
    title: str
    term: str
    educator_id: str
    educator_name: str
    invite_code: str
    code_visibility: CodeVisibility
    student_count: int
    assigned_problem_count: int
    start_at: UtcDatetime | None
    end_at: UtcDatetime | None
    is_active: bool

    @classmethod
    def build(
        cls, c: Course, *, educator_name: str, student_count: int, assigned: int
    ) -> "CourseRead":
        return cls(
            id=c.id,
            organization_id=c.organization_id,
            title=c.title,
            term=c.term,
            educator_id=c.educator_id,
            educator_name=educator_name,
            invite_code=c.invite_code,
            code_visibility=CodeVisibility(c.code_visibility),
            student_count=student_count,
            assigned_problem_count=assigned,
            start_at=c.start_at,
            end_at=c.end_at,
            is_active=c.is_active,
        )


class EnrollRequest(BaseModel):
    """학생을 이메일로 등록한다. 이미 가입한 계정만 붙일 수 있다."""

    email: str = Field(max_length=255)


class CourseJoinRequest(BaseModel):
    invite_code: str = Field(min_length=1, max_length=64)


class StudentCourseRead(BaseModel):
    id: str
    title: str
    term: str
    educator_name: str
    assigned_problem_count: int


class AssignmentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=500)
    problem_ids: list[str] = Field(min_length=1, max_length=100)
    due_at: UtcDatetime | None = None


class AssignmentProblemRead(BaseModel):
    problem_id: str
    title: str
    status: str


class AssignmentRead(BaseModel):
    id: str
    course_id: str
    course_title: str
    title: str
    description: str
    due_at: UtcDatetime | None
    problems: list[AssignmentProblemRead]
    completed_students: int
    total_students: int
    completed_problems: int = 0
    total_problems: int = 0


# --------------------------------------------------------------------- 대시보드


class CourseBrief(BaseModel):
    id: str
    title: str
    term: str
    educator_name: str


class DashboardMetrics(BaseModel):
    student_count: int
    student_count_delta: int
    average_progress: int
    weekly_progress_delta: int
    completion_rate: int
    total_attempts: int
    needs_attention_count: int


class DashboardRead(BaseModel):
    course: CourseBrief
    metrics: DashboardMetrics


# --------------------------------------------------------------------- 학생


class StudentRow(BaseModel):
    student_id: str
    name: str
    email: str
    avatar_url: str | None
    progress: int
    solved_count: int
    attempt_count: int
    last_active_at: UtcDatetime | None
    learning_status: LearningStatus
    weak_concepts: list[str]

    @classmethod
    def build(cls, u: User, s: StudentCourseStats | None) -> "StudentRow":
        return cls(
            student_id=u.id,
            name=u.name,
            email=u.email,
            avatar_url=u.avatar_url,
            progress=s.progress_rate if s else 0,
            solved_count=s.solved_count if s else 0,
            attempt_count=s.attempt_count if s else 0,
            last_active_at=s.last_active_at if s else None,
            learning_status=LearningStatus(s.learning_status) if s else LearningStatus.INACTIVE,
            weak_concepts=[s.primary_weak_concept] if s and s.primary_weak_concept else [],
        )


class StudentListRead(BaseModel):
    items: list[StudentRow]
    total: int
    page: int
    size: int


class AttentionItem(BaseModel):
    student_id: str
    name: str
    status: LearningStatus
    progress: int
    risk_score: int
    weak_concept: str | None
    reasons: list[str]


class AttentionListRead(BaseModel):
    items: list[AttentionItem]


# --------------------------------------------------------------------- 학생 상세


class StudentBrief(BaseModel):
    id: str
    name: str
    email: str
    avatar_url: str | None


class StudentSummary(BaseModel):
    progress: int
    solved_count: int
    attempt_count: int
    last_active_at: UtcDatetime | None
    risk_score: int
    learning_status: LearningStatus


class WeakConcept(BaseModel):
    concept: str
    score: int
    failed_attempts: int


class ProblemActivity(BaseModel):
    problem_id: str
    title: str
    status: str
    best_passed: int
    total_tests: int
    attempt_count: int
    last_judge_status: str | None
    last_attempted_at: UtcDatetime | None
    # code_visibility 에 따라 채워지거나 null 이다
    code: str | None = None
    code_kind: str | None = None  # "SUBMITTED" | "LATEST_SNAPSHOT"


class StudentDetailRead(BaseModel):
    student: StudentBrief
    summary: StudentSummary
    weak_concepts: list[WeakConcept]
    recent_activity: list[ProblemActivity]
    recommendations: list[str]
    # 이 강의의 코드 열람 정책. 프런트가 "비공개" 안내를 띄울 때 쓴다.
    code_visibility: CodeVisibility
