from __future__ import annotations

from app.enums import JudgeStatus, RegionTag
from app.trace.features import extract_features
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


def f(b: TraceBuilder):
    return extract_features(b.db, b.session_id, now=b.t)


def test_zero_events(db):
    """Run 0회 세션에서도 예외 없이, 문서화된 기본값 그대로 나와야 한다."""
    b = TraceBuilder.start(db, at=T0).tick(30)
    r = f(b)

    assert r.elapsed_seconds == 30
    assert r.run_count == 0
    assert r.submit_count == 0
    assert r.attempt_count == 0
    assert r.recent_scores == []
    assert r.same_result_count == 0
    assert r.progress_delta == 0
    assert r.improved_recently is False
    assert r.seconds_without_progress == 30  # started_at에 anchor
    assert r.same_region_edit_count == 0  # v1(템플릿)은 제외된다
    assert r.repeated_edit_region is None
    assert r.large_change_detected is False
    assert r.consecutive_error_count == 0
    assert r.last_result is None
    assert r.snapshot_count == 1


def test_run_and_submit_counts_split_by_mode(db):
    b = TraceBuilder.start(db).tick(10).run(2).tick(10).run(3).tick(10).submit(3, 5)
    r = f(b)
    assert r.run_count == 2
    assert r.submit_count == 1
    assert r.attempt_count == 3


def test_run_count_counts_results_not_intent(db):
    """RUN intent 이벤트가 아니라 TEST_RESULT를 센다.

    Pyodide 로딩 중 Run을 두 번 누른 학생이 attempt_count>=2 가드를 통과하면 안 된다.
    """
    b = TraceBuilder.start(db).tick(5)
    b._simple.__self__  # noqa: B018 - 아래에서 직접 이벤트만 넣는다
    from app.enums import EventType

    b._simple(EventType.RUN)
    b._simple(EventType.RUN)
    r = f(b)
    assert r.run_count == 0
    assert r.attempt_count == 0


def test_recent_scores_exclude_error_results(db):
    b = (
        TraceBuilder.start(db)
        .tick(10).run(2)
        .tick(10).error(JudgeStatus.SYNTAX_ERROR)
        .tick(10).run(3)
    )
    r = f(b)
    assert r.recent_scores == [2, 3]
    assert r.recent_error_types == ["SYNTAX_ERROR"]


def test_error_between_identical_results_does_not_reset_streak(db):
    """[3, syntax, 3]은 same_result_count가 2로 유지된다.

    §22.3 요구사항의 비자명한 반쪽. 에러를 0점으로 세면 streak이 1로 리셋된다.
    """
    b = (
        TraceBuilder.start(db)
        .tick(10).run(3)
        .tick(10).error(JudgeStatus.SYNTAX_ERROR)
        .tick(10).run(3)
    )
    assert f(b).same_result_count == 2


def test_error_does_not_fake_progress(db):
    """3/5 -> syntax -> 3/5가 [3, 0, 3]으로 읽히면 progress_delta=+3이 되어
    monitor가 명백히 막힌 학생을 PROGRESSING으로 방치한다."""
    b = (
        TraceBuilder.start(db)
        .tick(10).run(3)
        .tick(10).error(JudgeStatus.RUNTIME_ERROR)
        .tick(10).run(3)
    )
    r = f(b)
    assert r.progress_delta == 0
    assert r.improved_recently is False


def test_same_result_count_identical(db):
    b = TraceBuilder.start(db).tick(10).run(3).tick(10).run(3).tick(10).run(3)
    assert f(b).same_result_count == 3


def test_same_result_count_breaks_on_change(db):
    b = TraceBuilder.start(db).tick(10).run(3).tick(10).run(3).tick(10).run(4)
    assert f(b).same_result_count == 1


def test_same_result_count_distinguishes_totals(db):
    """run(1/1) -> submit(1/4) -> run(1/1)은 passed가 세 번 1이지만 같은 결과가 아니다.

    가운데 관측은 새 정보다. signature에 total이 들어가야 하는 이유.
    """
    b = (
        TraceBuilder.start(db, total=1)
        .tick(10).run(1, 1)
        .tick(10).submit(1, 4)
        .tick(10).run(1, 1)
    )
    assert f(b).same_result_count == 1


def test_progress_delta_and_improved_recently(db):
    b = TraceBuilder.start(db).tick(10).run(2).tick(10).run(3).tick(10).run(4)
    r = f(b)
    assert r.progress_delta == 1
    assert r.improved_recently is True

    b2 = TraceBuilder.start(db).tick(10).run(3).tick(10).run(3).tick(10).run(3)
    r2 = f(b2)
    assert r2.progress_delta == 0
    assert r2.improved_recently is False


def test_seconds_without_progress_resets_on_new_best(db):
    b = TraceBuilder.start(db).tick(10).run(2).tick(60).run(3).tick(20)
    assert f(b).seconds_without_progress == 20


def test_seconds_without_progress_does_not_reset_on_recovery(db):
    """4/5 -> 3/5 -> 4/5에서 두 번째 4/5는 회복이지 진전이 아니다.

    90초 시계는 첫 4/5부터 계속 흘러야 한다.
    """
    b = (
        TraceBuilder.start(db)
        .tick(10).run(4)
        .tick(40).run(3)
        .tick(40).run(4)
        .tick(10)
    )
    assert f(b).seconds_without_progress == 90


def test_activity_success_counts_as_progress(db):
    b = TraceBuilder.start(db).tick(10).run(3).tick(100).activity_response("CORRECT").tick(5)
    assert f(b).seconds_without_progress == 5


def test_same_region_edit_count_trailing_run(db):
    b = (
        TraceBuilder.start(db)
        .tick(10).edit(LOOP_V2).tick(5).run(3)
        .tick(20).edit(LOOP_V3).tick(5).run(3)
        .tick(20).edit(LOOP_V4).tick(5).run(3)
    )
    r = f(b)
    # v2는 첫 결과(=progress anchor) 이전이라 제외, v3/v4만 센다
    assert r.same_region_edit_count == 2
    assert r.repeated_edit_region == RegionTag.LOOP.value


def test_different_region_edits_do_not_accumulate(db):
    b = (
        TraceBuilder.start(db)
        .tick(10).edit(LOOP_V2).tick(5).run(3)
        .tick(20).edit(LOOP_V3).tick(5).run(3)
        .tick(20).edit(RETURN_EDIT).tick(5).run(3)
    )
    r = f(b)
    assert r.same_region_edit_count == 1
    assert r.repeated_edit_region == RegionTag.RETURN.value


def test_same_region_edit_count_resets_after_progress(db):
    b = (
        TraceBuilder.start(db)
        .tick(10).edit(LOOP_V2).tick(5).run(3)
        .tick(20).edit(LOOP_V3).tick(5).run(3)
        .tick(20).edit(LOOP_V5_CORRECT).tick(5).run(5)
    )
    # 5/5가 새 최고 기록이라 anchor가 이동 -> 그 이후 편집은 0개
    assert f(b).same_region_edit_count == 0


def test_edits_in_result_streak(db):
    """편집 없이 Run만 반복하면 0. R5b가 읽는 값."""
    b = (
        TraceBuilder.start(db)
        .tick(10).edit(LOOP_V2)
        .tick(5).run(3).tick(5).run(3).tick(5).run(3)
    )
    r = f(b)
    assert r.same_result_count == 3
    assert r.edits_in_result_streak == 0


def test_large_change_detected_window_is_since_previous_result(db):
    b = (
        TraceBuilder.start(db)
        .tick(10).edit(LOOP_V2).tick(5).run(3)
        .tick(10).edit(BIG_REWRITE).tick(5).run(5)
    )
    assert f(b).large_change_detected is True


def test_large_change_expires_after_a_later_result(db):
    """한 번 크게 붙여넣은 세션이 영원히 플래그되면 안 된다."""
    b = (
        TraceBuilder.start(db)
        .tick(10).edit(LOOP_V2).tick(5).run(3)
        .tick(10).edit(BIG_REWRITE).tick(5).run(5)
        .tick(10).run(5)
    )
    assert f(b).large_change_detected is False


def test_slow_large_change_is_not_flagged(db):
    """'짧은 시간 내' 대규모 변화만 잡는다. 5분에 걸친 재작성은 해당 없음."""
    b = (
        TraceBuilder.start(db)
        .tick(10).edit(LOOP_V2).tick(5).run(3)
        .tick(300).edit(BIG_REWRITE).tick(5).run(5)
    )
    assert f(b).large_change_detected is False


def test_edit_windows_use_version_not_timestamp(db):
    """편집/실행이 전부 같은 초에 몰려도 창이 넓어지면 안 된다.

    server_timestamp는 microsecond를 자르므로 빠른 조작(또는 curl 스크립트)에서
    모든 이벤트가 동일한 timestamp를 갖는다. created_at으로 창을 자르면
    "직전 결과 이후의 편집"이 그 이전 편집까지 쓸어담아
    large_change_detected가 거짓 양성을 낸다. 창은 code_version으로 잘라야 한다.
    """
    b = TraceBuilder.start(db)  # tick 없음 -> 모든 이벤트가 같은 초
    b.edit(BIG_REWRITE).run(3)  # v2: 대규모 변경 -> 3/5
    b.edit(BIG_REWRITE_TWEAK).run(3)  # v3: 한 줄만 변경 -> 3/5

    r = f(b)
    # 두 번째 결과를 만든 변경(v3)은 한 줄이다. v2의 대규모 변경이 새면 안 된다.
    assert r.large_change_detected is False


def test_large_change_detected_within_same_second(db):
    """반대 방향 확인: 같은 초라도 진짜 대규모 변경은 잡혀야 한다."""
    b = TraceBuilder.start(db)
    b.edit(LOOP_V2).run(3)
    b.edit(BIG_REWRITE).run(5)
    assert f(b).large_change_detected is True


def test_consecutive_error_count(db):
    b = (
        TraceBuilder.start(db)
        .tick(10).error(JudgeStatus.SYNTAX_ERROR)
        .tick(10).error(JudgeStatus.SYNTAX_ERROR)
        .tick(10).error(JudgeStatus.RUNTIME_ERROR)
    )
    assert f(b).consecutive_error_count == 3

    b2 = (
        TraceBuilder.start(db)
        .tick(10).error(JudgeStatus.SYNTAX_ERROR)
        .tick(10).run(3)
    )
    assert f(b2).consecutive_error_count == 0


def test_undo_and_hint_counts(db):
    b = TraceBuilder.start(db).tick(5).undo().tick(5).undo().tick(5).hint()
    r = f(b)
    assert r.undo_count == 2
    assert r.hint_count == 1
