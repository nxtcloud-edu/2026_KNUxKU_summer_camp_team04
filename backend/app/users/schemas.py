from __future__ import annotations

from pydantic import BaseModel, Field

from app.enums import ProgressStatus
from app.models import AcornTransaction, UserProblemProgress
from app.schemas_common import UtcDatetime


class AcornTransactionRead(BaseModel):
    id: str
    amount: int
    balance_after: int
    type: str
    description: str
    problem_id: str | None
    created_at: UtcDatetime

    @classmethod
    def from_row(cls, tx: AcornTransaction) -> "AcornTransactionRead":
        return cls(
            id=tx.id,
            amount=tx.amount,
            balance_after=tx.balance_after,
            type=str(tx.transaction_type),
            description=tx.description,
            # reference_type 이 problem 일 때만 problem_id 로 노출한다.
            problem_id=tx.reference_id if tx.reference_type == "problem" else None,
            created_at=tx.created_at,
        )


class AcornBalanceRead(BaseModel):
    balance: int
    total_earned: int


class AcornTransactionListRead(BaseModel):
    balance: int
    total_earned: int
    transactions: list[AcornTransactionRead]
    total: int


class ProgressRead(BaseModel):
    problem_id: str
    status: ProgressStatus
    best_passed: int
    total_tests: int
    attempt_count: int
    last_judge_status: str | None
    first_started_at: UtcDatetime
    last_attempted_at: UtcDatetime | None
    solved_at: UtcDatetime | None
    updated_at: UtcDatetime
    # 목록 응답에서는 코드를 빼서 26개 조회가 무거워지지 않게 한다.
    current_code: str | None = None

    @classmethod
    def from_row(cls, r: UserProblemProgress, *, include_code: bool) -> "ProgressRead":
        return cls(
            problem_id=r.problem_id,
            status=ProgressStatus(r.status),
            best_passed=r.best_passed,
            total_tests=r.total_tests,
            attempt_count=r.attempt_count,
            last_judge_status=r.last_judge_status,
            first_started_at=r.first_started_at,
            last_attempted_at=r.last_attempted_at,
            solved_at=r.solved_at,
            updated_at=r.updated_at,
            current_code=r.current_code if include_code else None,
        )


class ProgressListRead(BaseModel):
    items: list[ProgressRead]
    total: int


class CheckpointRequest(BaseModel):
    student_code: str = Field(max_length=100_000)


class SolvedProblemRead(BaseModel):
    problem_id: str
    title: str
    solved_at: UtcDatetime | None
    attempt_count: int
    acorns_earned: int


class SolvedProblemListRead(BaseModel):
    items: list[SolvedProblemRead]
    total: int
