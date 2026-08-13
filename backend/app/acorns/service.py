"""도토리 원장.

**잔액을 직접 증감하는 코드는 이 파일 바깥에 있으면 안 된다.**
모든 변동은 post()를 거치고, 원장 한 줄과 users.acorn_balance 갱신이
같은 트랜잭션 안에서 함께 일어난다.

멱등성:
  idempotency_key에 UNIQUE 제약이 걸려 있다. "이 사용자가 이 문제를 처음 풀었다"를
  애플리케이션 로직(조회 후 판단)이 아니라 **DB 제약**이 보장한다. 조회-후-삽입은
  동시 요청 둘이 같은 시점에 조회하면 둘 다 통과해 중복 지급이 난다.
"""
from __future__ import annotations

import logging

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session as DbSession
from sqlmodel import col, func, select

from app.clock import utcnow
from app.enums import AcornTransactionType
from app.errors import InsufficientAcorns, UserNotFound
from app.models import AcornTransaction, User

log = logging.getLogger(__name__)


def problem_solved_key(user_id: str, problem_id: str) -> str:
    """문제 최초 정답 보상의 멱등성 키. 같은 문제를 다시 풀어도 재지급되지 않는다."""
    return f"problem_solved:{user_id}:{problem_id}"


def trace_completed_key(user_id: str, problem_id: str) -> str:
    return f"trace_completed:{user_id}:{problem_id}"


def _locked_user(db: DbSession, user_id: str) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise UserNotFound(user_id)
    return user


def post(
    db: DbSession,
    *,
    user_id: str,
    amount: int,
    transaction_type: AcornTransactionType,
    description: str = "",
    reference_type: str | None = None,
    reference_id: str | None = None,
    idempotency_key: str | None = None,
    allow_negative_balance: bool = False,
) -> AcornTransaction | None:
    """원장에 한 줄 쓰고 잔액을 갱신한다. commit은 **호출자가** 한다.

    반환값이 None이면 "멱등성 키가 이미 있어서 아무 일도 하지 않았다"는 뜻이다.
    이건 오류가 아니라 정상 경로다 -- 같은 문제를 두 번 통과한 경우가 그렇다.

    잔액이 모자라면 InsufficientAcorns(402)를 던진다.
    **차감량 계산과 잔액 검사는 전부 서버에서 한다.** 프런트가 보낸 금액을 믿지 않는다.
    """
    if amount == 0:
        return None

    user = _locked_user(db, user_id)

    if amount < 0 and not allow_negative_balance and user.acorn_balance + amount < 0:
        raise InsufficientAcorns(required=-amount, balance=user.acorn_balance)

    new_balance = user.acorn_balance + amount
    tx = AcornTransaction(
        user_id=user_id,
        amount=amount,
        balance_after=new_balance,
        transaction_type=transaction_type,
        reference_type=reference_type,
        reference_id=reference_id,
        description=description,
        idempotency_key=idempotency_key,
        created_at=utcnow(),
    )
    db.add(tx)

    user.acorn_balance = new_balance
    if amount > 0:
        user.total_acorns_earned += amount
    user.updated_at = utcnow()
    db.add(user)

    try:
        db.flush()
    except IntegrityError:
        # idempotency_key UNIQUE 위반 = 이미 지급됨. 정상 경로다.
        db.rollback()
        log.info("도토리 중복 지급 차단: key=%s", idempotency_key)
        return None

    return tx


def balance(db: DbSession, user_id: str) -> tuple[int, int]:
    """(현재 잔액, 누적 획득)."""
    user = _locked_user(db, user_id)
    return user.acorn_balance, user.total_acorns_earned


def transactions(
    db: DbSession, user_id: str, *, limit: int = 50, offset: int = 0
) -> list[AcornTransaction]:
    return list(
        db.exec(
            select(AcornTransaction)
            .where(AcornTransaction.user_id == user_id)
            .order_by(col(AcornTransaction.created_at).desc(), col(AcornTransaction.id).desc())
            .offset(offset)
            .limit(limit)
        ).all()
    )


def transaction_count(db: DbSession, user_id: str) -> int:
    return int(
        db.exec(
            select(func.count()).select_from(AcornTransaction).where(
                AcornTransaction.user_id == user_id
            )
        ).one()
    )


def earned_for_problem(db: DbSession, user_id: str, problem_id: str) -> int:
    """특정 문제로 획득한 도토리 합계. 풀이 완료 목록에 쓴다."""
    total = db.exec(
        select(func.coalesce(func.sum(AcornTransaction.amount), 0))
        .where(AcornTransaction.user_id == user_id)
        .where(AcornTransaction.reference_type == "problem")
        .where(AcornTransaction.reference_id == problem_id)
        .where(AcornTransaction.amount > 0)
    ).one()
    return int(total)
