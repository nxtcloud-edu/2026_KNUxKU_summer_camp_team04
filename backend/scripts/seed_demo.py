"""데모용 세션 3개를 만든다.

tests/factories.py의 TraceBuilder를 그대로 재사용한다 -- 산출물 하나, 용도 둘.
테스트가 검증하는 것과 데모가 보여주는 것이 같은 코드에서 나온다.

    python -m scripts.seed_demo
"""
from __future__ import annotations

from datetime import datetime

from sqlmodel import Session

from app.db import get_engine, init_db
from app.enums import JudgeStatus
from app.trace import monitor
from tests.factories import TraceBuilder
from tests.fixtures_code import (
    BIG_REWRITE,
    LOOP_V2,
    LOOP_V3,
    LOOP_V4,
    LOOP_V5_CORRECT,
)

T0 = datetime(2026, 8, 13, 12, 0, 0)


def scenario_progressing(db: Session):
    """시나리오 1: 2/5 -> 3/5 -> 4/5. 개입하지 않는다."""
    b = (
        TraceBuilder.start(db, problem_id="func_sum_list", at=T0)
        .tick(25).edit(LOOP_V2).tick(12).run(2)
        .tick(30).edit(LOOP_V3).tick(11).run(3)
        .tick(28).edit(LOOP_V4).tick(10).run(4)
    )
    return b, monitor.evaluate_and_record(db, b.session, now=b.t)


def scenario_stuck(db: Session):
    """시나리오 2: 3/5 x3 + 같은 loop 영역 반복 수정 -> REPEATED_FAILURE."""
    b = (
        TraceBuilder.start(db, problem_id="func_sum_list", at=T0)
        .tick(32).edit(LOOP_V2).tick(14).run(3)
        .tick(29).edit(LOOP_V3).tick(12).run(3)
        .tick(31).edit(LOOP_V4).tick(11).run(3)
    )
    # 실제 파이프라인과 동일하게 AGENT_TRIGGER까지 기록하고, 그때 내려진 판단을 돌려준다.
    # (기록 후 다시 evaluate하면 cooldown이 trigger를 가린다 -- 그게 정상 동작이다.)
    return b, monitor.evaluate_and_record(db, b.session, now=b.t)


def scenario_understanding_uncertain(db: Session):
    """시나리오 C: 대규모 재작성 -> 즉시 통과 -> UNDERSTANDING_UNCERTAIN."""
    b = (
        TraceBuilder.start(db, problem_id="func_find_max", at=T0)
        .tick(40).edit(LOOP_V2).tick(15).run(3)
        .tick(20).edit(BIG_REWRITE).tick(8).run(5)
    )
    return b, monitor.evaluate_and_record(db, b.session, now=b.t)


def scenario_recovered(db: Session):
    """막혔다가 개입 후 회복. 타임라인 데모용.

    최종 상태는 PROGRESSING이지만 타임라인에는 AGENT TRIGGER 마커가 남아 있다.
    """
    b = (
        TraceBuilder.start(db, problem_id="func_count_positive", at=T0)
        .tick(30).edit(LOOP_V2).tick(12).run(3)
        .tick(25).edit(LOOP_V3).tick(10).run(3)
        .tick(28).edit(LOOP_V4).tick(11).run(3)
    )
    monitor.evaluate_and_record(db, b.session, now=b.t)
    (
        b.tick(20)
        .activity_response("CORRECT")
        .tick(35).edit(LOOP_V5_CORRECT)
        .tick(9).run(5)
    )
    return b, monitor.evaluate(db, b.session_id, now=b.t)


SCENARIOS = [
    ("PROGRESSING  (개입 없음)", scenario_progressing),
    ("STUCK        (REPEATED_FAILURE)", scenario_stuck),
    ("UNCERTAIN    (대규모 변경 후 통과)", scenario_understanding_uncertain),
    ("RECOVERED    (개입 후 회복)", scenario_recovered),
]


def main() -> None:
    init_db()
    with Session(get_engine()) as db:
        print()
        for label, build in SCENARIOS:
            b, state = build(db)
            print(f"{label}")
            print(f"  session_id : {b.session_id}")
            print(f"  status     : {state.status.value}")
            print(f"  trigger    : {state.trigger.value if state.trigger else '-'}")
            for e in state.evidence:
                print(f"               · {e}")
            print()

        print("확인:")
        print("  curl localhost:8000/sessions/<id>/process-state | python -m json.tool")
        print("  curl localhost:8000/sessions/<id>/timeline | python -m json.tool")
        print()


if __name__ == "__main__":
    main()
