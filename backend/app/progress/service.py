"""사용자별 문제 진행 상태 + 정답 보상.

여기가 "서버 권한으로 처리한다"의 핵심이다:
채점 결과는 **서버가 실행한 judge**에서만 온다. 프런트가 보낸 status를
근거로 도토리를 주지 않는다.
"""
from __future__ import annotations

import logging

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session as DbSession
from sqlmodel import col, select

from app.acorns import service as acorns
from app.clock import utcnow
from app.config import get_settings
from app.enums import AcornTransactionType, JudgeStatus, ProgressStatus
from app.models import UserProblemProgress
from app.problems.service import ProblemRecord

log = logging.getLogger(__name__)


def get(db: DbSession, user_id: str, problem_id: str) -> UserProblemProgress | None:
    return db.exec(
        select(UserProblemProgress)
        .where(UserProblemProgress.user_id == user_id)
        .where(UserProblemProgress.problem_id == problem_id)
    ).first()


def list_all(db: DbSession, user_id: str) -> list[UserProblemProgress]:
    return list(
        db.exec(
            select(UserProblemProgress)
            .where(UserProblemProgress.user_id == user_id)
            .order_by(col(UserProblemProgress.updated_at).desc())
        ).all()
    )


def list_solved(db: DbSession, user_id: str) -> list[UserProblemProgress]:
    return list(
        db.exec(
            select(UserProblemProgress)
            .where(UserProblemProgress.user_id == user_id)
            .where(UserProblemProgress.status == ProgressStatus.SOLVED)
            .order_by(col(UserProblemProgress.solved_at).desc())
        ).all()
    )


def ensure(db: DbSession, user_id: str, problem_id: str) -> UserProblemProgress:
    """행이 없으면 만든다. 동시 요청은 UNIQUE 제약이 막고 재조회로 수습한다."""
    found = get(db, user_id, problem_id)
    if found is not None:
        return found

    row = UserProblemProgress(
        user_id=user_id,
        problem_id=problem_id,
        status=ProgressStatus.IN_PROGRESS,
        first_started_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = get(db, user_id, problem_id)
        if existing is None:  # pragma: no cover - 제약 위반인데 행이 없을 수는 없다
            raise
        return existing
    return row


def save_checkpoint(db: DbSession, user_id: str, problem_id: str, code: str) -> UserProblemProgress:
    """작성 중인 코드를 계정에 저장한다. 기기가 바뀌어도 이어서 풀 수 있다."""
    row = ensure(db, user_id, problem_id)
    row.current_code = code
    row.updated_at = utcnow()
    if row.status is ProgressStatus.NOT_STARTED:
        row.status = ProgressStatus.IN_PROGRESS
    db.add(row)
    db.flush()
    return row


def record_judge_result(
    db: DbSession,
    *,
    user_id: str,
    problem: ProblemRecord,
    status: JudgeStatus,
    passed: int,
    total: int,
    code: str,
    mode: str,
) -> tuple[UserProblemProgress, int]:
    """채점 결과를 진행 상태에 반영하고, 조건에 맞으면 도토리를 지급한다.

    반환값 (progress, 지급된 도토리). commit은 호출자가 한다.

    **호출자는 서버 judge 경로여야 한다.** 클라이언트가 보고한 결과로
    이 함수를 부르면 도토리를 조작할 수 있다.

    지급 규칙 (문서 §6 권장 MVP):
      - 문제 **최초** ACCEPTED 에만 지급. 재통과는 0
      - 난이도별 10/15/20 (judge 문제엔 difficulty가 없어 현재 전부 10)
      - submit 뿐 아니라 run 으로 통과해도 인정한다 -- run 은 public 만 채점하므로
        hidden 까지 통과한 게 아니지만, judge 는 ACCEPTED 를 passed==total 로
        판정하므로 run 의 ACCEPTED 는 "공개 테스트 전부 통과"를 뜻한다.
        정책상 submit 만 인정하려면 아래 한 줄을 바꾼다.
    """
    row = ensure(db, user_id, problem.problem_id)
    now = utcnow()

    row.attempt_count += 1
    row.last_attempted_at = now
    row.last_judge_status = status.value
    row.updated_at = now
    if code:
        row.current_code = code
    if total > 0 and passed > row.best_passed:
        row.best_passed = passed
    if total > 0:
        row.total_tests = total

    awarded = 0
    if status is JudgeStatus.ACCEPTED:
        first_solve = row.status is not ProgressStatus.SOLVED
        row.status = ProgressStatus.SOLVED
        if row.solved_at is None:
            row.solved_at = now

        if first_solve:
            amount = get_settings().acorn_reward_for(problem.difficulty)
            tx = acorns.post(
                db,
                user_id=user_id,
                amount=amount,
                transaction_type=AcornTransactionType.PROBLEM_SOLVED,
                description=f"{problem.title} 최초 해결",
                reference_type="problem",
                reference_id=problem.problem_id,
                # 멱등성 키가 진짜 방어선이다. first_solve 판정이 경합으로
                # 두 번 True가 되어도 원장은 한 줄만 남는다.
                idempotency_key=acorns.problem_solved_key(user_id, problem.problem_id),
            )
            awarded = tx.amount if tx else 0

    db.add(row)
    db.flush()
    return row, awarded


def award_trace_completion(db: DbSession, *, user_id: str, problem_id: str) -> int:
    """TRACE 학습 최초 완료 보상. 프런트가 ACTIVITY_RESPONSE 를 붙이면 호출된다."""
    tx = acorns.post(
        db,
        user_id=user_id,
        amount=get_settings().acorn_reward_trace_completed,
        transaction_type=AcornTransactionType.TRACE_COMPLETED,
        description="TRACE 학습 완료",
        reference_type="problem",
        reference_id=problem_id,
        idempotency_key=acorns.trace_completed_key(user_id, problem_id),
    )
    return tx.amount if tx else 0
