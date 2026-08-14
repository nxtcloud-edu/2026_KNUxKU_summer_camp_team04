"""복습 문제 생성 오케스트레이션.

흐름 (실시간 개입과 같은 "즉시 응답 + 백그라운드 + 폴링" 패턴):

    POST /users/me/review-problems
        -> PENDING 행 생성, 즉시 201 반환
        -> BackgroundTasks: agent 호출(~25초) -> JSON 파일 저장 -> READY/FAILED
    GET  /users/me/review-problems   (프런트가 폴링)
        -> 상태가 READY로 바뀌면 problem_id로 세션 시작 가능
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.engine import Engine
from sqlmodel import Session as DbSession
from sqlmodel import col, select

from app.clock import utcnow
from app.enums import GeneratedProblemStatus
from app.errors import ProblemNotFound
from app.models import GeneratedProblem, User
from app.problems.service import ProblemRecord, ProblemRepository
from app.review.interface import ProblemGeneratorProtocol

log = logging.getLogger(__name__)

#: 한 학생이 동시에 돌릴 수 있는 생성 요청 수. 생성 1건이 LLM + 도커 실행이라
#: 버튼 연타로 큐가 쌓이면 그대로 비용이 된다. 이미 PENDING이 있으면 새로 만들지 않고
#: 그 행을 그대로 돌려준다 (멱등에 가깝게).
MAX_PENDING_PER_USER = 1

#: 목록 조회 기본 개수. 복습 문제는 계속 쌓이므로 최근 것만 보여준다.
DEFAULT_LIST_LIMIT = 20


def _source_problem_payload(record: ProblemRecord) -> dict[str, Any]:
    """agent `SourceProblem` 모양. **hidden test case는 절대 넣지 않는다.**

    문제 본문/형식만 넘긴다 — LLM은 "같은 유형의 새 문제"를 만들면 되고,
    원본의 정답 케이스는 알 필요가 없다.
    """
    return {
        "problem_id": record.problem_id,
        "title": record.title,
        "description": record.description,
        "concepts": list(record.concepts),
        "check_type": record.check_type,
        "function_name": record.function_name,
    }


def build_review_request(user: User, source: ProblemRecord) -> dict[str, Any]:
    """agent `ReviewRequest` 모양의 dict.

    `concept`은 원본의 첫 개념을 쓰되, 비어 있으면 문제 제목으로 대신한다 —
    judge 문제 26개 중 23개가 `concept: []`이라 이 폴백이 실제로 대부분의
    경우에 쓰인다. (개념 태그를 채우는 건 별개 작업이다.) 어느 쪽이든
    `source_problems`에 원본 본문이 통째로 실려 가므로 LLM은 무슨 문제였는지
    정확히 안다 — `concept`은 보조 힌트일 뿐이다.
    """
    concepts = [c for c in source.concepts if c]
    return {
        "student_id": user.id,
        "concept": concepts[0] if concepts else source.title,
        "missed_problem_ids": [source.problem_id],
        "difficulty_hint": "same",
        "source_problems": [_source_problem_payload(source)],
    }


def find_pending(db: DbSession, user_id: str) -> GeneratedProblem | None:
    return db.exec(
        select(GeneratedProblem)
        .where(GeneratedProblem.user_id == user_id)
        .where(GeneratedProblem.status == GeneratedProblemStatus.PENDING)
        .order_by(col(GeneratedProblem.created_at).desc())
    ).first()


def request_generation(
    db: DbSession, user: User, repo: ProblemRepository, source_problem_id: str
) -> tuple[GeneratedProblem, bool]:
    """PENDING 행을 만든다. 실제 생성은 호출자가 백그라운드로 돌린다.

    Returns:
        `(행, 새로 만들었는지)`. 이미 PENDING이 있으면 그걸 그대로 돌려주고
        False다 — 버튼 연타로 LLM 호출이 쌓이는 걸 막는다.
    """
    if not repo.exists(source_problem_id):
        raise ProblemNotFound(source_problem_id)

    existing = find_pending(db, user.id)
    if existing is not None:
        return existing, False

    row = GeneratedProblem(
        user_id=user.id,
        source_problem_id=source_problem_id,
        status=GeneratedProblemStatus.PENDING,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, True


def run_generation(
    engine: Engine,
    generator: ProblemGeneratorProtocol,
    repo: ProblemRepository,
    *,
    request_id: str,
    review_request: dict[str, Any],
) -> None:
    """백그라운드 본체. **어떤 경우에도 예외를 밖으로 내지 않는다.**

    여기서 예외가 새면 BackgroundTasks가 조용히 삼키고, 학생의 요청 행은
    PENDING인 채로 영원히 남아 프런트가 무한 폴링한다. 그래서 모든 실패를
    FAILED 행으로 **반드시 기록**한다.

    **새 DB 세션을 직접 연다.** 요청 스코프 세션(`Depends(get_db)`)은 응답이
    나가면 닫히므로 백그라운드에서 재사용할 수 없다 (trace/router.py의
    `_run_agent_in_background`와 같은 이유이며, `engine`을 주입받는 이유도
    같다 — 테스트가 `get_engine`을 override해서 인메모리 DB로 격리할 수 있게).
    """
    try:
        result = generator.generate(review_request)
    except Exception as exc:  # noqa: BLE001 - 프로토콜이 금지하지만 방어한다
        log.exception("문제 생성 호출이 예외를 던졌습니다 (request=%s)", request_id)
        _finish_failed(engine, request_id, f"문제 생성 중 오류가 발생했습니다: {exc}")
        return

    if not result.is_valid or not result.problem_json:
        _finish_failed(
            engine, request_id, result.error_message or "문제 생성에 실패했습니다."
        )
        return

    # 파일 쓰기가 실패하면(권한/디스크) 학생에게는 "생성됐다"고 해놓고 정작
    # 문제를 못 여는 상태가 되므로, 저장까지 성공해야 READY로 넘어간다.
    try:
        problem_id = f"review_{request_id}"
        repo.add_generated(result.problem_json, problem_id)
    except Exception as exc:  # noqa: BLE001
        log.exception("생성 문제 저장 실패 (request=%s)", request_id)
        _finish_failed(engine, request_id, f"생성한 문제를 저장하지 못했습니다: {exc}")
        return

    with DbSession(engine) as db:
        row = db.get(GeneratedProblem, request_id)
        if row is None:
            log.warning("생성 요청 행이 사라졌습니다 (request=%s)", request_id)
            return
        row.problem_id = problem_id
        row.status = GeneratedProblemStatus.READY
        row.completed_at = utcnow()
        db.add(row)
        db.commit()
    log.info("복습 문제 생성 완료: %s (request=%s)", problem_id, request_id)


def _finish_failed(engine: Engine, request_id: str, message: str) -> None:
    try:
        with DbSession(engine) as db:
            row = db.get(GeneratedProblem, request_id)
            if row is None:
                return
            row.status = GeneratedProblemStatus.FAILED
            row.error_message = message
            row.completed_at = utcnow()
            db.add(row)
            db.commit()
    except Exception:  # noqa: BLE001 - 실패 기록조차 실패하면 로그가 마지막 수단이다
        log.exception("생성 실패 기록에도 실패했습니다 (request=%s)", request_id)


def list_for_user(
    db: DbSession, user_id: str, limit: int = DEFAULT_LIST_LIMIT
) -> list[GeneratedProblem]:
    return list(
        db.exec(
            select(GeneratedProblem)
            .where(GeneratedProblem.user_id == user_id)
            .order_by(col(GeneratedProblem.created_at).desc())
            .limit(limit)
        ).all()
    )
