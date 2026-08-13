from __future__ import annotations

from datetime import timedelta

from sqlmodel import select

from app.agent import get_agent
from app.agent.interface import AgentDecision
from app.agent.stub import FakeAgent
from app.enums import AgentAction, EventType, JudgeStatus, TriggerType
from app.judge import get_judge
from app.judge.interface import JudgeResult
from app.judge.stub import FakeJudge
from app.main import app
from app.models import Event
from app.trace.features import extract_features
from app.sessions import store
from tests.factories import T0, TraceBuilder
from tests.fixtures_code import LOOP_V2, LOOP_V3, LOOP_V4


def create(client) -> str:
    return client.post("/sessions", json={"problem_id": "func_sum_list"}).json()[
        "session_id"
    ]


def test_run_returns_503_when_judge_is_unavailable(client):
    """404가 아니라 타입 있는 503이어야 한다.

    프론트가 오늘 이 엔드포인트에 코드를 짜고, JUDGE_BACKEND=docker를 켜면
    양쪽 다 코드 수정 없이 켜진다. 404면 프론트가 추측하게 된다.
    """
    sid = create(client)
    for path in ("run", "submit"):
        r = client.post(f"/sessions/{sid}/{path}", json={})
        assert r.status_code == 503, path
        assert r.json()["detail"]["code"] == "JUDGE_UNAVAILABLE"


def test_health_reports_seam_state(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["judge_backend"] == "none"
    assert body["agent_backend"] == "none"


def test_run_with_injected_judge_writes_server_sourced_result(client, db):
    app.dependency_overrides[get_judge] = lambda: FakeJudge(
        [JudgeResult(status=JudgeStatus.WRONG_ANSWER, passed=3, total=5, runtime_ms=12)]
    )
    try:
        sid = create(client)
        r = client.post(f"/sessions/{sid}/run", json={"code": LOOP_V2})
        assert r.status_code == 201

        event = r.json()["event"]
        assert event["type"] == "TEST_RESULT"
        assert event["source"] == "SERVER"
        assert event["payload"]["judge"] == "fake"
        assert event["payload"]["passed"] == 3
        # body.code로 보냈으므로 스냅샷이 생성되고 그 버전이 붙는다
        assert event["code_version"] == 2
    finally:
        app.dependency_overrides.pop(get_judge, None)


def test_client_and_server_paths_produce_identical_row_shape(db):
    """seam이 실제로 작동하는지에 대한 값싼 보장.

    두 경로가 바이트 동일한 TEST_RESULT payload 키 집합을 쓰고 동일한 feature를
    낳으면, 채점 주체를 바꿔도 하류(features/monitor)는 손대지 않아도 된다.

    **HTTP가 아니라 서비스 계층에서 검증한다.** 클라이언트가 결과를 보고하던
    POST /results 는 제거됐다(도토리 조작 경로였다). 그래도 seam 자체는
    record_judge_result() 라는 단일 작성자에 그대로 살아 있으므로,
    produced_by 만 바꿔 호출해 같은 성질을 확인한다.
    """
    from app.enums import EventSource
    from app.trace import service as trace_service

    def write(produced_by: EventSource, judge_name: str) -> str:
        b = TraceBuilder.start(db)
        session = store.require_session(db, b.session_id)
        trace_service.create_snapshot(db, session_id=b.session_id, code=LOOP_V2)
        db.commit()
        db.refresh(session)
        trace_service.record_judge_result(
            db,
            session,
            mode="run",
            status="WRONG_ANSWER",
            passed=3,
            total=5,
            runtime_ms=12,
            produced_by=produced_by,
            judge_name=judge_name,
        )
        return b.session_id

    a = write(EventSource.CLIENT_JUDGE, "pyodide")
    b = write(EventSource.SERVER, "docker")

    def payload_of(sid: str) -> dict:
        rows = db.exec(select(Event).where(Event.session_id == sid)).all()
        return next(e.payload for e in rows if EventType(e.type) is EventType.TEST_RESULT)

    pa, pb = payload_of(a), payload_of(b)
    assert pa.keys() == pb.keys()
    # judge 이름만 다르다
    assert {k: v for k, v in pa.items() if k != "judge"} == {
        k: v for k, v in pb.items() if k != "judge"
    }

    fa = extract_features(db, a)
    fb = extract_features(db, b)
    assert fa.recent_scores == fb.recent_scores
    assert fa.run_count == fb.run_count == 1
    assert fa.same_result_count == fb.same_result_count


def _two_prior_failures(db, user) -> TraceBuilder:
    """REPEATED_FAILURE의 처음 2/3 (test_monitor.py 시나리오 2와 동일 레시피).
    3번째 3/5는 각 테스트가 실제 /submit 호출로 만든다 -- 그래야 그 응답/기록
    경로 자체를 검증하는 셈이 된다."""
    return (
        TraceBuilder.start(db, user_id=user.id, at=T0)
        .tick(30).edit(LOOP_V2).tick(10).run(3)
        .tick(25).edit(LOOP_V3).tick(10).run(3)
    )


def test_submit_records_agent_intervention_when_agent_actually_intervenes(client, db, user, frozen_now):
    """/run|/submit 경로도 하트비트와 동일하게 WAIT가 아닌 결정을 AGENT_INTERVENTION으로
    남겨야 한다 -- 그래야 build_context()의 previous_interventions가 다음 판단에
    이걸 참고할 수 있고, 프론트가 GET /events 폴링으로 이 힌트를 놓치지 않는다."""
    b = _two_prior_failures(db, user)
    frozen_now["t"] = b.t + timedelta(seconds=25)
    fake_agent = FakeAgent(
        AgentDecision(
            state="STUCK", concept="loop", action=AgentAction.HINT,
            reason="같은 오류 반복", activity={"message": "확인해보세요"},
        )
    )
    app.dependency_overrides[get_agent] = lambda: fake_agent
    # 3번째 3/5 -- 이걸로 same_result_count가 3이 되어 REPEATED_FAILURE가 뜬다.
    app.dependency_overrides[get_judge] = lambda: FakeJudge(
        [JudgeResult(status=JudgeStatus.WRONG_ANSWER, passed=3, total=5)]
    )
    try:
        r = client.post(f"/sessions/{b.session_id}/submit", json={"code": LOOP_V4})
        assert r.status_code == 201
        assert r.json()["process_state"]["trigger"] == TriggerType.REPEATED_FAILURE.value
        assert r.json()["agent_decision"]["action"] == "HINT"  # 응답에는 그대로 실린다 (동기 경로)

        rows = db.exec(
            select(Event).where(Event.session_id == b.session_id).where(Event.type == EventType.AGENT_INTERVENTION)
        ).all()
        assert len(rows) == 1
        assert rows[0].payload["action"] == "HINT"
        assert rows[0].payload["activity"]["message"] == "확인해보세요"
    finally:
        app.dependency_overrides.pop(get_agent, None)
        app.dependency_overrides.pop(get_judge, None)


def test_submit_records_nothing_when_agent_waits(client, db, user, frozen_now):
    b = _two_prior_failures(db, user)
    frozen_now["t"] = b.t + timedelta(seconds=25)
    app.dependency_overrides[get_agent] = lambda: FakeAgent(
        AgentDecision(state="STUCK", concept=None, action=AgentAction.WAIT, reason="대기")
    )
    app.dependency_overrides[get_judge] = lambda: FakeJudge(
        [JudgeResult(status=JudgeStatus.WRONG_ANSWER, passed=3, total=5)]
    )
    try:
        r = client.post(f"/sessions/{b.session_id}/submit", json={"code": LOOP_V4})
        assert r.status_code == 201
        assert r.json()["process_state"]["trigger"] == TriggerType.REPEATED_FAILURE.value
        assert r.json()["agent_decision"]["action"] == "WAIT"

        rows = db.exec(
            select(Event).where(Event.session_id == b.session_id).where(Event.type == EventType.AGENT_INTERVENTION)
        ).all()
        assert rows == []
    finally:
        app.dependency_overrides.pop(get_agent, None)
        app.dependency_overrides.pop(get_judge, None)


def test_agent_decide_returns_wait_today(client):
    sid = create(client)
    r = client.post("/agent/decide", json={"session_id": sid})
    assert r.status_code == 200
    assert r.json()["action"] == "WAIT"
    assert r.json()["reason"]


def test_agent_context_is_actually_buildable(client, db):
    """LLM이 없어도 context builder는 진짜로 동작해야 한다.

    trace 데이터가 실제로 충분한지를 지금 증명한다 -- 그게 이 프로젝트의 논지다.
    """
    from app.agent.context import build_context
    from app.problems.service import get_problem_repository

    app.dependency_overrides[get_judge] = lambda: FakeJudge(
        [JudgeResult(status=JudgeStatus.WRONG_ANSWER, passed=3, total=5)]
    )
    try:
        sid = create(client)
        client.post(f"/sessions/{sid}/run", json={"code": LOOP_V2})
    finally:
        app.dependency_overrides.pop(get_judge, None)

    ctx = build_context(db, sid, get_problem_repository())
    assert ctx.problem["title"] == "리스트 합 구하기"
    assert ctx.problem["concepts"]
    assert ctx.current_code == LOOP_V2
    assert ctx.current_code_version == 2
    assert ctx.judge_result["passed"] == 3
    assert "RUN 3/5" in ctx.recent_trace
    assert ctx.features["run_count"] == 1
    assert ctx.process_status
