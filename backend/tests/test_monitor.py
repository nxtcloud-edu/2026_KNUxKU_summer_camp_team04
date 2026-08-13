"""backend_plan §22의 필수 시나리오. **여기가 데모 게이트다.**

이게 틀리면 하류의 어떤 것도 의미가 없다.
"""
from __future__ import annotations

from sqlmodel import select

from app.enums import EventType, JudgeStatus, ProcessStatus, TriggerType
from app.models import Event
from app.trace import monitor
from tests.factories import T0, TraceBuilder
from tests.fixtures_code import (
    BIG_REWRITE,
    LOOP_V2,
    LOOP_V3,
    LOOP_V4,
    LOOP_V5_CORRECT,
    RETURN_EDIT,
)


def ev(b: TraceBuilder):
    return monitor.evaluate(b.db, b.session_id, now=b.t)


def _trigger_events(db, session_id: str) -> list[Event]:
    rows = db.exec(select(Event).where(Event.session_id == session_id)).all()
    return [e for e in rows if EventType(e.type) is EventType.AGENT_TRIGGER]


# ------------------------------------------------------------- §22 시나리오 1


def test_scenario_1_improving_does_not_trigger(db):
    """2/5 -> 3/5 -> 4/5 는 Agent를 호출하지 않는다.

    R2(진전 가드)가 R5/R7보다 **위에** 있다는 사실이 핵심이다.
    나중에 누가 공격적인 규칙을 아래에 추가해도 R2가 개선 중인 학생을 계속 보호한다.
    """
    b = (
        TraceBuilder.start(db, at=T0)
        .tick(20).edit(LOOP_V2).tick(10).run(2)
        .tick(20).edit(LOOP_V3).tick(10).run(3)
        .tick(20).edit(LOOP_V4).tick(10).run(4)
    )
    s = ev(b)
    assert s.trigger is None
    assert s.status is ProcessStatus.PROGRESSING


def test_progress_guard_survives_long_elapsed_time(db):
    """개선 중이면 90초가 넘어도 NO_PROGRESS가 뜨지 않는다 (R2가 R7보다 위)."""
    b = (
        TraceBuilder.start(db)
        .tick(200).run(2)
        .tick(200).run(3)
        .tick(200).run(4)
        .tick(200)
    )
    assert ev(b).trigger is None


# ------------------------------------------------------------- §22 시나리오 2


def test_scenario_2_repeated_failure_triggers(db):
    """3/5 x3 + 같은 loop 영역 반복 수정 ⇒ REPEATED_FAILURE / STUCK."""
    b = (
        TraceBuilder.start(db, at=T0)
        .tick(30).edit(LOOP_V2).tick(10).run(3)
        .tick(25).edit(LOOP_V3).tick(10).run(3)
        .tick(25).edit(LOOP_V4).tick(10).run(3)
    )
    s = ev(b)

    assert s.trigger is TriggerType.REPEATED_FAILURE
    assert s.status is ProcessStatus.STUCK
    assert s.features.same_result_count == 3
    assert s.features.same_region_edit_count >= 2
    assert s.features.repeated_edit_region == "loop"
    assert any("동일 결과 3/5 ×3" in e for e in s.evidence)
    assert any("반복문 영역" in e for e in s.evidence)


def test_different_region_edits_are_productive_struggle(db):
    """서로 다른 전략을 시도 중이면 STUCK이 아니라 PRODUCTIVE_STRUGGLE이다.

    agent_plan §3.1의 정의 그대로. 이건 올바른 동작이지 놓친 케이스가 아니다.
    """
    b = (
        TraceBuilder.start(db)
        .tick(20).edit(LOOP_V2).tick(10).run(3)
        .tick(20).edit(LOOP_V3).tick(10).run(3)
        .tick(20).edit(RETURN_EDIT).tick(10).run(3)
    )
    s = ev(b)
    assert s.trigger is None
    assert s.status is ProcessStatus.PRODUCTIVE_STRUGGLE


def test_r5b_repeated_runs_without_editing(db):
    """편집 없이 Run만 3번. §12의 문자 그대로의 규칙이 놓치는 케이스."""
    b = (
        TraceBuilder.start(db)
        .tick(20).edit(LOOP_V2)
        .tick(10).run(3).tick(10).run(3).tick(10).run(3)
    )
    s = ev(b)
    assert s.trigger is TriggerType.REPEATED_FAILURE
    assert s.status is ProcessStatus.STUCK
    assert s.features.same_region_edit_count == 0  # R5가 아니라 R5b가 잡았다


# ------------------------------------------------------------- §22 시나리오 3


def test_scenario_3_single_syntax_error_does_not_trigger(db):
    """syntax error 1회는 Agent를 호출하지 않는다.

    특례 규칙이 아니라 구조적 결과다: 에러 결과가 scored_results에서 제외되므로
    관련 feature가 전부 불변이고, attempt_count도 guard를 통과 못 한다.
    """
    b = TraceBuilder.start(db).tick(30).edit(LOOP_V2).tick(10).error(JudgeStatus.SYNTAX_ERROR)
    s = ev(b)
    assert s.trigger is None
    assert s.status is ProcessStatus.PROGRESSING


def test_syntax_error_between_identical_results_keeps_streak(db):
    """[3, syntax, 3] ⇒ same_result_count == 2. 요구사항의 비자명한 반쪽."""
    b = (
        TraceBuilder.start(db)
        .tick(20).run(3)
        .tick(20).error(JudgeStatus.SYNTAX_ERROR)
        .tick(20).run(3)
    )
    assert ev(b).features.same_result_count == 2


def test_three_consecutive_errors_do_trigger(db):
    """파싱조차 세 번 연속 실패한 학생은 도움이 필요하다 (R6)."""
    b = (
        TraceBuilder.start(db)
        .tick(20).error(JudgeStatus.SYNTAX_ERROR)
        .tick(20).error(JudgeStatus.SYNTAX_ERROR)
        .tick(20).error(JudgeStatus.SYNTAX_ERROR)
    )
    s = ev(b)
    assert s.trigger is TriggerType.REPEATED_FAILURE
    assert s.status is ProcessStatus.STUCK


# ------------------------------------------------------------- NO_PROGRESS


def test_no_progress_fires_at_threshold(db):
    """anchor는 마지막 실행이 아니라 **첫 3/5**(개인 최고 기록 갱신)다.

    T0+10에 첫 3/5 -> anchor. now가 T0+100이면 정확히 90초.
    """
    b = TraceBuilder.start(db, at=T0).tick(10).run(3).tick(10).run(3).tick(80)
    s = ev(b)
    assert s.features.seconds_without_progress == 90
    assert s.trigger is TriggerType.NO_PROGRESS
    assert s.status is ProcessStatus.POSSIBLE_STUCK


def test_no_progress_does_not_fire_below_threshold(db):
    b = TraceBuilder.start(db, at=T0).tick(10).run(3).tick(10).run(3).tick(79)
    s = ev(b)
    assert s.features.seconds_without_progress == 89
    assert s.trigger is None


def test_no_progress_requires_two_attempts(db):
    """실행을 한 번밖에 안 한 학생에게는 개입하지 않는다.

    아직 그에 대한 증거가 없고, 아무것도 안 한 학생에게 LLM을 쏘는 건
    계획서가 경고하는 바로 그 안티패턴이다.
    """
    b = TraceBuilder.start(db).tick(10).run(3).tick(300)
    assert ev(b).trigger is None


def test_staring_at_problem_without_running_does_not_trigger(db):
    b = TraceBuilder.start(db).tick(600)
    assert ev(b).trigger is None


# ------------------------------------------------------------- 시나리오 C


def test_big_change_then_accepted_is_understanding_uncertain(db):
    b = (
        TraceBuilder.start(db)
        .tick(20).edit(LOOP_V2).tick(10).run(3)
        .tick(20).edit(BIG_REWRITE).tick(10).run(5)
    )
    s = ev(b)
    assert s.trigger is TriggerType.UNDERSTANDING_UNCERTAIN
    assert s.status is ProcessStatus.UNDERSTANDING_UNCERTAIN


def test_small_change_then_accepted_does_not_trigger(db):
    b = (
        TraceBuilder.start(db)
        .tick(20).edit(LOOP_V2).tick(10).run(3)
        .tick(20).edit(LOOP_V5_CORRECT).tick(10).run(5)
    )
    s = ev(b)
    assert s.trigger is None
    assert s.status is ProcessStatus.PROGRESSING


# ------------------------------------------------------------- cooldown


def _stuck(db) -> TraceBuilder:
    return (
        TraceBuilder.start(db, at=T0)
        .tick(30).edit(LOOP_V2).tick(10).run(3)
        .tick(25).edit(LOOP_V3).tick(10).run(3)
        .tick(25).edit(LOOP_V4).tick(10).run(3)
    )


def test_cooldown_suppresses_trigger_but_not_status(db):
    """데모에서 중요한 성질: 시스템이 stuck임을 *알면서도* 끼어들지 않기로 *선택*했다."""
    b = _stuck(db).trigger(TriggerType.REPEATED_FAILURE).tick(10)
    s = ev(b)
    assert s.trigger is None
    assert s.status is ProcessStatus.STUCK  # 여전히 STUCK으로 분류된다
    assert s.cooldown_active is True
    assert s.cooldown_remaining_seconds == 20


def test_cooldown_released_after_timeout(db):
    b = _stuck(db).trigger(TriggerType.REPEATED_FAILURE).tick(31)
    s = ev(b)
    assert s.cooldown_active is False
    assert s.trigger is TriggerType.REPEATED_FAILURE


def test_cooldown_released_by_new_result(db):
    """'30초 **또는** 다음 Run까지' -- 둘 중 먼저 오는 쪽이 푼다."""
    b = _stuck(db).trigger(TriggerType.REPEATED_FAILURE).tick(5).run(3)
    s = ev(b)
    assert s.cooldown_active is False
    assert s.trigger is TriggerType.REPEATED_FAILURE


def test_help_request_bypasses_cooldown(db):
    """도움을 요청했는데 침묵하는 건 데모 킬러다."""
    b = _stuck(db).trigger(TriggerType.REPEATED_FAILURE).tick(5).hint()
    s = ev(b)
    assert s.trigger is TriggerType.HELP_REQUESTED
    assert s.status is ProcessStatus.HELP_REQUESTED
    assert s.cooldown_active is True  # cooldown은 살아 있지만 R0가 무시한다


def test_served_hint_does_not_refire(db):
    """힌트 클릭 한 번이 이후 모든 평가에서 영원히 재발화하면 안 된다."""
    b = _stuck(db).tick(5).hint()
    assert ev(b).trigger is TriggerType.HELP_REQUESTED

    b.tick(1).trigger(TriggerType.HELP_REQUESTED).tick(40)
    s = ev(b)
    assert s.trigger is not TriggerType.HELP_REQUESTED


# ------------------------------------------------------------- pure/recording 분리


def test_evaluate_writes_nothing(db):
    """GET /process-state를 다섯 번 폴링해도 AGENT_TRIGGER는 0개다.

    GET이 cooldown을 소진하면 trigger 직후 첫 폴링이 그걸 먹고,
    정작 agent를 불러야 할 실제 Run이 cooldown에 걸린다.
    """
    b = _stuck(db)
    for _ in range(5):
        s = monitor.evaluate(b.db, b.session_id, now=b.t)
        assert s.trigger is TriggerType.REPEATED_FAILURE

    triggers = _trigger_events(db, b.session_id)
    assert triggers == []


def test_evaluate_and_record_writes_exactly_one_trigger(db):
    b = _stuck(db)
    state = monitor.evaluate_and_record(db, b.session, now=b.t)
    assert state.trigger is TriggerType.REPEATED_FAILURE

    triggers = _trigger_events(db, b.session_id)
    assert len(triggers) == 1
    payload = triggers[0].payload
    assert payload["trigger"] == "REPEATED_FAILURE"
    assert payload["status"] == "STUCK"
    # feature 스냅샷이 통째로 들어 있어야 사후에 "왜 이 숫자로 호출됐는지" 설명 가능하다
    assert payload["features"]["same_result_count"] == 3
    assert payload["evidence"]


def test_evaluate_and_record_is_noop_without_trigger(db):
    b = TraceBuilder.start(db).tick(10).run(2).tick(10).run(3)
    monitor.evaluate_and_record(db, b.session, now=b.t)
    triggers = _trigger_events(db, b.session_id)
    assert triggers == []
