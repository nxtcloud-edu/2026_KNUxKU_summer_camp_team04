"""backend_plan §22의 필수 시나리오. **여기가 데모 게이트다.**

이게 틀리면 하류의 어떤 것도 의미가 없다.
"""
from __future__ import annotations

from sqlmodel import select

from app.config import MonitorConfig
from app.enums import EventType, JudgeStatus, ProcessStatus, TriggerType
from app.models import Event
from app.trace import monitor
from tests.factories import T0, TraceBuilder
from tests.fixtures_code import (
    BIG_REWRITE,
    BIG_REWRITE_TWEAK,
    LOOP_V2,
    LOOP_V3,
    LOOP_V4,
    LOOP_V5_CORRECT,
    RETURN_EDIT,
)

#: R7d(완전 무활동)를 끈 설정. 무활동과 무관한 규칙을 검증하는 테스트가 쓴다 --
#: 시간을 길게 흘려야 하는 시나리오는 전부 R7d에 먼저 걸리기 때문이다.
NO_IDLE_RULE = MonitorConfig(idle_no_activity_seconds=0)


def ev(b: TraceBuilder, cfg=None):
    return monitor.evaluate(b.db, b.session_id, now=b.t, cfg=cfg)


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
    # R7d를 끈다 -- 89초를 흘리려면 그 사이 학생이 아무것도 하지 않으므로
    # 무활동 규칙이 먼저 발화한다. 여기서 보려는 것은 R7의 임계값이다.
    b = TraceBuilder.start(db, at=T0).tick(10).run(3).tick(10).run(3).tick(79)
    s = ev(b, NO_IDLE_RULE)
    assert s.features.seconds_without_progress == 89
    assert s.trigger is None


def test_no_progress_requires_two_attempts(db):
    """실행을 한 번밖에 안 한 학생에게는 개입하지 않는다.

    아직 그에 대한 증거가 없고, 아무것도 안 한 학생에게 LLM을 쏘는 건
    계획서가 경고하는 바로 그 안티패턴이다.
    (무활동 규칙 R7d는 별개다 -- 그건 '실행 1회 + 침묵'을 의도적으로 잡는다.)
    """
    b = TraceBuilder.start(db).tick(10).run(3).tick(300)
    assert ev(b, NO_IDLE_RULE).trigger is None


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


# ------------------------------------------- 편집만으로 발화하는 규칙 (R7b/R7c)
#
# R7까지의 규칙은 전부 TEST_RESULT를 요구한다 -- attempt_count조차 클라이언트의
# RUN/SUBMIT 이벤트가 아니라 서버가 채점하며 쓴 결과만 센다. 그래서 실행을 한 번도
# 누르지 않은 학생에게는 R0(도움 요청) 말고 어떤 규칙도 발화하지 못했다.


def test_wholesale_replacement_without_running_triggers_comprehension_check(db):
    """쓰던 코드를 통째로 갈아치우고 실행조차 안 한 채 멈추면 이해도 확인 (R7b).

    실행/제출이 0회라 attempt_count 기반 규칙(R5~R7)은 전부 침묵한다.
    """
    b = (
        TraceBuilder.start(db)
        .tick(10).edit(LOOP_V2)      # 학생이 직접 쓴 초안
        .tick(10).edit(BIG_REWRITE)  # 그걸 통째로 대체
        .tick(30)                    # 그리고 손을 놓았다
    )
    s = ev(b)
    assert s.trigger is TriggerType.UNDERSTANDING_UNCERTAIN
    assert s.status is ProcessStatus.UNDERSTANDING_UNCERTAIN
    assert s.features.attempt_count == 0, "실행 없이 발화하는 것이 이 규칙의 존재 이유다"
    assert s.features.large_change_unverified


def test_first_draft_over_template_is_not_treated_as_paste(db):
    """템플릿에서 첫 초안을 쓰는 것은 붙여넣기가 아니다.

    3줄짜리 `pass` 템플릿에서 실제 코드로 가는 변경은 change_ratio/size 기준을
    거의 항상 넘긴다. 이걸 붙잡으면 모든 학생이 첫 코드를 쓸 때마다 개입당한다.
    (첫 행동이 진짜 붙여넣기인 학생은 그걸 실행해 통과하는 순간 R2가 잡는다.)
    """
    b = TraceBuilder.start(db).tick(10).edit(BIG_REWRITE).tick(60)
    s = ev(b, NO_IDLE_RULE)  # 여기서 보려는 것은 붙여넣기 판정이다 (R7d는 별개)
    assert s.trigger is None
    assert not s.features.large_change_unverified


def test_paste_still_typing_does_not_trigger(db):
    """대규모 변경만으로는 안 된다. '그리고 손을 놓았다'가 겹쳐야 한다.

    신호 하나로 발화하면 빠르게 타이핑하는 학생이 매번 붙잡힌다.
    """
    b = (
        TraceBuilder.start(db)
        .tick(10).edit(LOOP_V2)
        .tick(10).edit(BIG_REWRITE)
        .tick(2)  # 아직 손을 놓지 않았다
    )
    s = ev(b)
    assert s.trigger is None


def test_large_edit_that_was_actually_run_does_not_trigger_r7b(db):
    """큰 편집을 하고 **실행해서 결과를 본** 학생은 R7b 대상이 아니다.

    회귀 테스트: large_change_detected(창 = '현재 결과를 만든 변경')를 그대로
    쓰면 '큰 편집 -> 실행(문법 오류)' 한 번에도 R7b가 발화한다. 실제로 겪었고,
    그래서 창이 다른 large_change_unverified('결과 이후의 편집')를 따로 만들었다.
    """
    b = TraceBuilder.start(db).tick(30).edit(BIG_REWRITE).tick(30).error(JudgeStatus.SYNTAX_ERROR)
    s = ev(b)
    assert s.trigger is None
    assert not s.features.large_change_unverified


def test_churn_then_idle_triggers_no_progress(db):
    """같은 영역을 반복해서 고치다 손을 놓으면 발화한다 (R7c). 실행은 0회다."""
    b = (
        TraceBuilder.start(db)
        .tick(10).edit(LOOP_V2)
        .tick(10).edit(LOOP_V3)
        .tick(10).edit(LOOP_V4)
        .tick(60)
    )
    s = ev(b)
    assert s.trigger is TriggerType.NO_PROGRESS
    assert s.features.attempt_count == 0
    assert s.features.same_region_edit_count >= 3


def test_churn_while_still_editing_does_not_trigger(db):
    """churn만으로는 안 된다 -- 아직 활발히 고치는 중이면 스스로 해결할 여지가 있다."""
    b = (
        TraceBuilder.start(db)
        .tick(10).edit(LOOP_V2)
        .tick(10).edit(LOOP_V3)
        .tick(10).edit(LOOP_V4)
        .tick(3)
    )
    s = ev(b)
    assert s.trigger is None


def test_editing_rules_do_not_refire_without_new_edits(db):
    """지난번에 찔렀는데 학생이 코드를 건드리지도 않았으면 또 찌르지 않는다.

    cooldown(30초 **또는** 다음 Run)만으로는 못 막는다 -- 편집만 하는 세션에는
    Run이 영영 오지 않아서 30초마다 같은 트리거가 반복된다.
    """
    b = (
        TraceBuilder.start(db)
        .tick(10).edit(LOOP_V2)
        .tick(10).edit(BIG_REWRITE)
        .tick(30)
    )
    first = monitor.evaluate_and_record(db, b.session, now=b.t)
    assert first.trigger is TriggerType.UNDERSTANDING_UNCERTAIN

    # cooldown이 풀릴 만큼 시간이 지나도, 편집이 없었으므로 다시 발화하지 않는다
    b.tick(120)
    again = ev(b)
    assert again.features.edits_since_last_trigger == 0
    assert again.trigger is None

    # 학생이 다시 손대면 그때는 발화할 수 있다
    b.edit(BIG_REWRITE_TWEAK).tick(60)
    assert ev(b).features.edits_since_last_trigger >= 1


# ------------------------------------------------- 완전 무활동 규칙 (R7d)
#
# R7c는 "같은 영역 churn 3회 + 편집 멈춤"이라 **고치다가** 멈춘 학생만 잡는다.
# 한 줄 쓰고 멍하니 있거나, 실행 한 번 하고 결과만 보다 멈춘 학생은 어디에도
# 걸리지 않았다. R7d가 그 구멍을 메운다.


def test_idle_with_no_activity_triggers(db):
    """편집 1회 후 10초 동안 아무 활동이 없으면 막힘으로 간주한다 (R7d).

    churn(3회)도 붙여넣기도 실행도 없어서 R7a~R7c는 전부 침묵한다.
    """
    b = TraceBuilder.start(db).tick(5).edit(LOOP_V2).tick(10)
    s = ev(b)
    assert s.trigger is TriggerType.NO_PROGRESS
    assert s.status is ProcessStatus.POSSIBLE_STUCK
    assert s.features.attempt_count == 0
    assert s.features.same_region_edit_count < 3, "churn 규칙(R7c)이 아닌 경로여야 한다"
    assert s.features.seconds_since_last_activity >= 10


def test_idle_below_threshold_does_not_trigger(db):
    """임계값(10초) 이전에는 침묵한다."""
    b = TraceBuilder.start(db).tick(5).edit(LOOP_V2).tick(9)
    s = ev(b)
    assert s.trigger is None


def test_run_resets_the_activity_clock(db):
    """실행은 편집이 아니지만 활동이다 -- 결과를 읽는 중인 학생을 유휴로 보지 않는다.

    회귀 가드: 무활동 시계를 seconds_since_last_edit으로 구현하면 이 케이스가
    바로 오발화한다(편집은 40초 전이지만 방금 Run을 눌렀다).
    """
    b = TraceBuilder.start(db).tick(5).edit(LOOP_V2).tick(40).run(2).tick(3)
    s = ev(b)
    assert s.features.seconds_since_last_edit >= 40
    assert s.features.seconds_since_last_activity == 3
    assert s.trigger is None


def test_idle_fires_once_per_idle_period(db):
    """계속 가만히 있어도 유휴 구간당 한 번만 찌른다.

    cooldown만으로는 못 막는다 -- 무활동 세션에는 Run도 편집도 영영 오지 않아서
    cooldown이 풀리는 순간마다 같은 트리거가 반복된다(하트비트가 3초마다 온다).
    activity_since_last_trigger 가드가 그걸 막는다.
    """
    b = TraceBuilder.start(db).tick(5).edit(LOOP_V2).tick(10)
    first = monitor.evaluate_and_record(db, b.session, now=b.t)
    assert first.trigger is TriggerType.NO_PROGRESS

    b.tick(300)  # cooldown이 한참 지났지만 학생은 여전히 아무것도 안 했다
    again = ev(b)
    assert again.features.activity_since_last_trigger == 0
    assert again.trigger is None

    # 다시 뭐라도 하면(여기서는 편집) 그 다음 유휴 구간에는 발화한다
    b.edit(LOOP_V3).tick(10)
    assert ev(b).trigger is TriggerType.NO_PROGRESS


def test_untouched_session_is_not_nagged(db):
    """문제를 열어놓고 아직 아무것도 시작하지 않은 학생은 유휴가 아니라 독해 중이다."""
    b = TraceBuilder.start(db).tick(120)
    s = ev(b)
    assert s.features.activity_since_last_trigger == 0
    assert s.trigger is None


def test_idle_does_not_override_solved(db):
    """이미 통과한 학생은 10초 침묵으로 찌르지 않는다 (R4가 R7d보다 위).

    통과 결과가 2개다 -- 하나면 '큰 편집 직후 통과'라 R2(이해도 확인)가 먼저 잡는다.
    """
    b = (
        TraceBuilder.start(db)
        .tick(5).edit(LOOP_V5_CORRECT).tick(5).run(5)
        .tick(5).run(5)
        .tick(60)
    )
    s = ev(b)
    assert s.trigger is None
    assert s.status is ProcessStatus.PROGRESSING


def test_idle_rule_can_be_disabled(db):
    """MONITOR_IDLE_NO_ACTIVITY_SECONDS=0 이면 무활동 개입을 끈다.

    "아주 크게 잡기"로는 끌 수 없다 -- 값이 크면 오래 자리를 비운 학생이 돌아오는
    순간 뒤늦은 개입이 튀어나온다.
    """
    b = TraceBuilder.start(db).tick(5).edit(LOOP_V2).tick(600)
    assert ev(b).trigger is TriggerType.NO_PROGRESS
    assert ev(b, NO_IDLE_RULE).trigger is None


def test_idle_does_not_override_progress_guard(db):
    """개선 중인 학생도 보호한다 (R3가 R7d보다 위)."""
    b = (
        TraceBuilder.start(db)
        .tick(10).edit(LOOP_V2).tick(5).run(2)
        .tick(10).edit(LOOP_V3).tick(5).run(3)
        .tick(60)
    )
    s = ev(b)
    assert s.trigger is None
    assert s.status is ProcessStatus.PROGRESSING


def test_idle_beats_productive_struggle(db):
    """실행을 2번 이상 한 학생에게도 무활동 규칙이 살아 있어야 한다 (R7d가 R8 위).

    R8은 trigger 없이 PRODUCTIVE_STRUGGLE로 끝내버리므로, R7d를 아래에 두면
    실행 이력이 있는 학생에게는 이 규칙이 죽는다.
    """
    b = (
        TraceBuilder.start(db)
        .tick(10).edit(LOOP_V2).tick(5).run(2)
        .tick(10).edit(RETURN_EDIT).tick(5).run(2)
        .tick(30)
    )
    s = ev(b)
    assert s.features.attempt_count >= 2
    assert s.trigger is TriggerType.NO_PROGRESS
