"""INTERNAL_ERROR(채점 인프라 고장)는 학생의 오류가 아니다.

원래 버그
--------
judge 가 Docker 데몬 연결 실패 · 컨테이너 실행 실패 · 무출력 · 로그 파싱 실패를
전부 `RUNTIME_ERROR` 로 보고했고, backend 의 `ERROR_STATUSES` 가 그걸 학생 에러로
집계했다. 결과적으로 **도커가 죽어 있으면 학생이 Run 을 세 번 누르는 것만으로
`consecutive_error_count == 3` 이 되어 REPEATED_FAILURE 트리거가 발화**했다.
학생은 아무 잘못도 하지 않았는데 "반복 실패" 판정을 받고 agent 가 개입한다.

여기 있는 테스트가 그 경로를 양쪽에서 고정한다:
  - 분류: INTERNAL_ERROR 는 SYSTEM_STATUSES 이고 ERROR_STATUSES 가 아니다
  - feature: 세지도 않고 streak 을 끊지도 않는다 (투명)
  - monitor: 트리거를 만들지 않는다
  - timeline: 그래도 화면에는 남는다 (채점기가 죽었다는 사실은 보여야 한다)
"""
from __future__ import annotations

from app.enums import (
    ERROR_STATUSES,
    SCORED_STATUSES,
    SYSTEM_STATUSES,
    EventType,
    JudgeStatus,
    ProcessStatus,
    TriggerType,
)
from sqlmodel import select

from app.judge import get_judge
from app.judge.interface import JudgeResult
from app.judge.stub import FakeJudge
from app.main import app
from app.models import Event
from app.trace import monitor, service as trace_service
from app.trace.features import extract_features
from app.trace.timeline import build_timeline
from tests.factories import T0, TraceBuilder
from tests.fixtures_code import LOOP_V2, LOOP_V3, LOOP_V4


def f(b: TraceBuilder):
    return extract_features(b.db, b.session_id, now=b.t)


def ev(b: TraceBuilder):
    return monitor.evaluate(b.db, b.session_id, now=b.t)


# --------------------------------------------------------------------- 분류


def test_internal_error_is_system_not_student_error():
    assert JudgeStatus.INTERNAL_ERROR in SYSTEM_STATUSES
    assert JudgeStatus.INTERNAL_ERROR not in ERROR_STATUSES
    assert JudgeStatus.INTERNAL_ERROR not in SCORED_STATUSES


def test_three_sets_partition_all_statuses():
    """세 집합이 겹치지 않고 전체를 덮는다.

    새 status 를 추가하면서 어느 집합에도 넣지 않으면 feature 집계에서 조용히
    사라진다. 그 실수를 여기서 잡는다.
    """
    assert SCORED_STATUSES | ERROR_STATUSES | SYSTEM_STATUSES == frozenset(JudgeStatus)
    assert not (SCORED_STATUSES & ERROR_STATUSES)
    assert not (SCORED_STATUSES & SYSTEM_STATUSES)
    assert not (ERROR_STATUSES & SYSTEM_STATUSES)


def test_student_errors_stay_in_error_statuses():
    """회귀 가드: 학생 코드 실패는 계속 학생 에러로 센다."""
    assert JudgeStatus.SYNTAX_ERROR in ERROR_STATUSES
    assert JudgeStatus.RUNTIME_ERROR in ERROR_STATUSES
    assert JudgeStatus.TIME_LIMIT in ERROR_STATUSES


# --------------------------------------------------------------------- feature


def test_internal_errors_do_not_count_as_student_errors(db):
    """도커가 죽은 채로 Run 3번 -> consecutive_error_count 는 0이어야 한다.

    이게 원래 버그의 핵심이다. 예전에는 3이 나왔다.
    """
    b = (
        TraceBuilder.start(db, at=T0)
        .tick(20).error(JudgeStatus.INTERNAL_ERROR)
        .tick(20).error(JudgeStatus.INTERNAL_ERROR)
        .tick(20).error(JudgeStatus.INTERNAL_ERROR)
    )
    r = f(b)

    assert r.consecutive_error_count == 0
    assert r.recent_error_types == []
    # 학생이 Run 을 누른 건 사실이므로 시도 횟수는 센다.
    assert r.attempt_count == 3
    # 마지막 결과는 숨기지 않는다 -- agent context 와 화면이 이유를 알아야 한다.
    assert r.last_result is not None
    assert r.last_result.status is JudgeStatus.INTERNAL_ERROR


def test_internal_error_does_not_break_a_real_error_streak(db):
    """채점기가 중간에 한 번 딸꾹질해도 학생의 3연속 에러는 3연속이다.

    시스템 오류를 '세지 않는' 것만으로는 부족하다. streak 을 '끊지도' 않아야
    한다 -- 끊으면 정작 필요한 개입을 놓친다.
    """
    b = (
        TraceBuilder.start(db, at=T0)
        .tick(20).error(JudgeStatus.RUNTIME_ERROR)
        .tick(20).error(JudgeStatus.RUNTIME_ERROR)
        .tick(20).error(JudgeStatus.INTERNAL_ERROR)  # 채점기 고장
        .tick(20).error(JudgeStatus.RUNTIME_ERROR)
    )
    assert f(b).consecutive_error_count == 3


def test_internal_error_does_not_break_scored_streak(db):
    """동일 결과 streak 도 시스템 오류에 영향받지 않는다.

    scored 리스트는 원래 에러를 전부 제외하므로 이미 성립하지만, 계약으로 고정한다.
    """
    b = (
        TraceBuilder.start(db, at=T0)
        .tick(20).run(3)
        .tick(20).error(JudgeStatus.INTERNAL_ERROR)
        .tick(20).run(3)
        .tick(20).run(3)
    )
    assert f(b).same_result_count == 3


# --------------------------------------------------------------------- monitor


def test_judge_outage_does_not_trigger_repeated_failure(db):
    """**원래 버그의 재현 테스트.**

    도커가 죽은 상태에서 학생이 코드를 고치며 세 번 실행한다.
    예전에는 REPEATED_FAILURE 가 발화해 agent 가 "반복 실패네요" 라고 개입했다.
    """
    b = (
        TraceBuilder.start(db, at=T0)
        .tick(30).edit(LOOP_V2).tick(10).error(JudgeStatus.INTERNAL_ERROR)
        .tick(25).edit(LOOP_V3).tick(10).error(JudgeStatus.INTERNAL_ERROR)
        .tick(25).edit(LOOP_V4).tick(10).error(JudgeStatus.INTERNAL_ERROR)
    )
    s = ev(b)

    assert s.trigger is None
    assert "채점 서버" in s.reason


def test_judge_outage_does_not_trigger_no_progress(db):
    """R1s 가 R7 을 막는다.

    채점기가 죽어 있으면 진전이 없는 게 당연하다. feature 쪽 SYSTEM_STATUSES
    분리만으로는 R7(90초 무진전 + 실행 2회)이 막히지 않아서 별도 게이트가 있다.
    """
    b = (
        TraceBuilder.start(db, at=T0)
        .tick(30).error(JudgeStatus.INTERNAL_ERROR)
        .tick(200).error(JudgeStatus.INTERNAL_ERROR)
        .tick(30)
    )
    s = ev(b)

    assert s.features.seconds_without_progress >= 90
    assert s.features.attempt_count >= 2
    assert s.trigger is None


def test_help_request_still_answered_during_outage(db):
    """채점기가 죽어도 학생이 직접 물으면 답한다. R0 는 R1s 보다 위다."""
    b = (
        TraceBuilder.start(db, at=T0)
        .tick(30).error(JudgeStatus.INTERNAL_ERROR)
        .tick(10).hint()
    )
    s = ev(b)

    assert s.trigger is TriggerType.HELP_REQUESTED
    assert s.status is ProcessStatus.HELP_REQUESTED


def test_real_student_errors_still_trigger(db):
    """회귀 가드: R1s 를 넣었다고 R6 이 죽으면 안 된다."""
    b = (
        TraceBuilder.start(db, at=T0)
        .tick(20).error(JudgeStatus.RUNTIME_ERROR)
        .tick(20).error(JudgeStatus.RUNTIME_ERROR)
        .tick(20).error(JudgeStatus.RUNTIME_ERROR)
    )
    s = ev(b)

    assert s.trigger is TriggerType.REPEATED_FAILURE
    assert s.status is ProcessStatus.STUCK
    assert s.features.consecutive_error_count == 3


def test_outage_then_recovery_resumes_normal_judgement(db):
    """채점기가 복구되면 판단도 복구된다. R1s 는 '마지막 결과'만 본다."""
    b = (
        TraceBuilder.start(db, at=T0)
        .tick(20).error(JudgeStatus.INTERNAL_ERROR)
        .tick(30).edit(LOOP_V2).tick(10).run(3)
        .tick(25).edit(LOOP_V3).tick(10).run(3)
        .tick(25).edit(LOOP_V4).tick(10).run(3)
    )
    s = ev(b)

    assert s.trigger is TriggerType.REPEATED_FAILURE
    assert s.status is ProcessStatus.STUCK


# --------------------------------------------------------------------- timeline


def test_timeline_still_shows_the_outage(db):
    """feature 에서 빼는 것과 화면에서 숨기는 것은 다르다.

    발표 중에 채점기가 죽었다는 사실 자체는 타임라인에 보여야 한다.
    """
    b = TraceBuilder.start(db, at=T0).tick(20).error(JudgeStatus.INTERNAL_ERROR)
    entries = build_timeline(
        b.session, trace_service.all_events(b.db, b.session_id), collapse=False
    ).entries

    labels = [e.label for e in entries]
    assert "INTERNAL ERROR" in labels
    assert [e.kind for e in entries if e.label == "INTERNAL ERROR"] == ["ERROR"]


# --------------------------------------------------------------------- 파이프라인 전체


def _internal(total: int = 5) -> JudgeResult:
    """judge 가 인프라 장애를 보고한 결과 (도커가 죽어 있을 때 실제로 오는 모양)."""
    return JudgeResult(
        status=JudgeStatus.INTERNAL_ERROR,
        passed=0,
        total=total,
        message="Docker 데몬에 연결할 수 없습니다.",
    )


def test_judge_outage_writes_no_agent_trigger_end_to_end(client, db):
    """**원래 버그의 end-to-end 재현.**

    도커가 죽은 상태에서 학생이 Run 을 세 번 누른다. 예전에는 세 번째에
    AGENT_TRIGGER 행이 쓰이고 cooldown 까지 소진됐다.

    `evaluate_and_record` 가 실제로 행을 쓰는 경로이므로, feature 계산이 아니라
    **DB 에 남은 결과**로 확인한다.
    """
    judge = FakeJudge([_internal(), _internal(), _internal()])
    app.dependency_overrides[get_judge] = lambda: judge

    sid = client.post("/sessions", json={"problem_id": "func_sum_list"}).json()["session_id"]
    for code in (LOOP_V2, LOOP_V3, LOOP_V4):
        r = client.post(f"/sessions/{sid}/run", json={"code": code})
        assert r.status_code == 201
        body = r.json()
        assert body["event"]["payload"]["status"] == "INTERNAL_ERROR"
        # 학생에게는 채점기 문제임이 전달되고, agent 는 개입하지 않는다.
        assert body["process_state"]["trigger"] is None
        assert body["agent_decision"] is None

    triggers = [
        e
        for e in db.exec(select(Event).where(Event.session_id == sid)).all()
        if EventType(e.type) is EventType.AGENT_TRIGGER
    ]
    assert triggers == []


def test_outage_does_not_award_acorns_or_mark_solved(client, db):
    """부수 효과 가드: 시스템 오류가 진행 상태를 SOLVED 로 만들지 않는다."""
    judge = FakeJudge([_internal()])
    app.dependency_overrides[get_judge] = lambda: judge

    sid = client.post("/sessions", json={"problem_id": "func_sum_list"}).json()["session_id"]
    assert client.post(f"/sessions/{sid}/run", json={"code": LOOP_V2}).status_code == 201

    progress = client.get("/users/me/progress/func_sum_list").json()
    assert progress["status"] != "SOLVED"
    assert progress["last_judge_status"] == "INTERNAL_ERROR"
    assert client.get("/users/me/acorns").json()["balance"] == 0
