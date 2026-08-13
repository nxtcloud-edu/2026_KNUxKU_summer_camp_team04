from __future__ import annotations

from app.enums import JudgeStatus, TriggerType
from app.judge import get_judge
from app.judge.interface import JudgeResult
from app.judge.stub import FakeJudge
from app.main import app
from app.trace.timeline import build_timeline
from app.trace import service as trace_service
from tests.factories import T0, TraceBuilder
from tests.fixtures_code import LOOP_V2, LOOP_V3, LOOP_V4


def timeline(b: TraceBuilder, *, collapse: bool = True):
    return build_timeline(
        b.session, trace_service.all_events(b.db, b.session_id), collapse=collapse
    )


def test_ordering_is_by_seq_not_timestamp(db):
    """배치 이벤트는 server_timestamp가 동일하다 (microsecond 절삭).

    timestamp로 정렬하면 순서가 무작위가 된다. seq가 유일한 순서 권위다.
    """
    b = TraceBuilder.start(db, at=T0)
    b.undo().reset().hint()  # tick 없음 -> 전부 같은 초
    entries = timeline(b).entries
    assert [e.seq for e in entries] == sorted(e.seq for e in entries)
    assert len({e.at for e in entries}) == 1  # 실제로 timestamp가 같다


def test_labels(db):
    b = (
        TraceBuilder.start(db, at=T0)
        .tick(10).edit(LOOP_V2)
        .tick(5).run(3)
        .tick(5).submit(4, 5)
        .tick(5).error(JudgeStatus.SYNTAX_ERROR)
        .tick(5).trigger(TriggerType.REPEATED_FAILURE)
    )
    labels = [e.label for e in timeline(b).entries]
    assert "START" in labels
    assert "RUN 3/5" in labels
    assert "SUBMIT 4/5" in labels
    assert "SYNTAX ERROR" in labels  # TEST_RESULT{SYNTAX_ERROR} -> kind=ERROR
    assert "AGENT TRIGGER: REPEATED_FAILURE" in labels
    assert any("반복문 영역 수정" in ln for ln in labels)


def test_syntax_error_renders_as_error_kind(db):
    """이벤트는 TEST_RESULT 하나지만 화면에서는 ERROR로 보인다.

    데이터의 진실은 하나, 데모 화면은 그대로.
    """
    b = TraceBuilder.start(db).tick(10).error(JudgeStatus.SYNTAX_ERROR)
    kinds = [e.kind for e in timeline(b).entries]
    assert "ERROR" in kinds
    assert "RUN" not in kinds


def test_collapse_merges_consecutive_edits(db):
    """debounce가 두 Run 사이에 스냅샷을 ~10개 만든다.

    합치지 않으면 데모 타임라인을 읽을 수가 없다.
    """
    b = (
        TraceBuilder.start(db)
        .tick(5).edit(LOOP_V2)
        .tick(5).edit(LOOP_V3)
        .tick(5).edit(LOOP_V4)
        .tick(5).run(3)
    )
    collapsed = timeline(b, collapse=True).entries
    full = timeline(b, collapse=False).entries

    assert sum(1 for e in collapsed if e.kind == "EDIT") == 1
    assert sum(1 for e in full if e.kind == "EDIT") == 3

    merged = next(e for e in collapsed if e.kind == "EDIT")
    assert merged.detail["snapshot_count"] == 3
    assert merged.detail["from_version"] == 2
    assert merged.detail["to_version"] == 4
    assert "×3" in merged.label


def test_collapse_does_not_merge_across_a_run(db):
    b = (
        TraceBuilder.start(db)
        .tick(5).edit(LOOP_V2).tick(5).run(3)
        .tick(5).edit(LOOP_V3).tick(5).run(3)
    )
    kinds = [e.kind for e in timeline(b).entries]
    assert kinds == ["START", "EDIT", "RUN", "EDIT", "RUN"]


def test_summary_counts(db):
    b = (
        TraceBuilder.start(db, at=T0)
        .tick(10).edit(LOOP_V2).tick(5).run(2)
        .tick(10).edit(LOOP_V3).tick(5).run(4)
        .tick(10).submit(4, 5)
        .tick(5).trigger(TriggerType.NO_PROGRESS)
    )
    s = timeline(b).summary
    assert s.edit_count == 2
    assert s.run_count == 2
    assert s.submit_count == 1
    assert s.trigger_count == 1
    assert s.best_passed == 4
    assert s.total_seconds == 45


def test_timeline_endpoint(client):
    sid = client.post("/sessions", json={"problem_id": "func_sum_list"}).json()[
        "session_id"
    ]
    client.post(
        f"/sessions/{sid}/events",
        json={"events": [{"type": "CODE_SNAPSHOT", "payload": {"code": LOOP_V2}}]},
    )
    app.dependency_overrides[get_judge] = lambda: FakeJudge(
        [JudgeResult(status=JudgeStatus.WRONG_ANSWER, passed=3, total=5)]
    )
    try:
        client.post(f"/sessions/{sid}/run", json={"code": LOOP_V2})
    finally:
        app.dependency_overrides.pop(get_judge, None)

    body = client.get(f"/sessions/{sid}/timeline").json()
    assert body["problem_id"] == "func_sum_list"
    assert [e["kind"] for e in body["entries"]] == ["START", "EDIT", "RUN"]
    assert body["summary"]["run_count"] == 1


def test_timeline_unknown_session_returns_404(client):
    assert client.get("/sessions/sess_missing/timeline").status_code == 404
