"""POST /sessions/{id}/heartbeat — 실시간 유휴 감지 + 백그라운드 agent 호출.

핵심 계약:
  1. 트리거되면 즉시 응답한다 (agent 호출로 안 막힘 -- BackgroundTasks로 넘김).
  2. agent가 WAIT가 아닌 실제 결정을 내면 AGENT_INTERVENTION 이벤트로 남는다.
  3. WAIT면 아무 이벤트도 안 남는다 (기록할 "개입"이 없다).
  4. 트리거 안 되면 agent를 아예 안 부른다.

`TestClient`가 요청/응답 안에서 `BackgroundTasks`를 동기로 실행하므로,
`client.post(...)` 호출이 끝나면 백그라운드 작업도 이미 끝나 있다 (검증에 sleep 불필요).
"""
from __future__ import annotations

from sqlmodel import select

from app.agent import get_agent
from app.agent.interface import AgentDecision
from app.agent.stub import FakeAgent
from app.db import get_engine
from app.enums import AgentAction, EventType, TriggerType
from app.main import app
from app.models import Event
from tests.factories import T0, TraceBuilder
from tests.fixtures_code import LOOP_V2, LOOP_V3, LOOP_V4


def _repeated_failure_session(db, user) -> tuple[str, "TraceBuilder"]:
    """backend_plan §22 시나리오 2와 동일한 레시피 (test_monitor.py 참고):
    3/5 x3 + 같은 영역 반복 수정 -> REPEATED_FAILURE."""
    b = (
        TraceBuilder.start(db, user_id=user.id, at=T0)
        .tick(30).edit(LOOP_V2).tick(10).run(3)
        .tick(25).edit(LOOP_V3).tick(10).run(3)
        .tick(25).edit(LOOP_V4).tick(10).run(3)
    )
    return b.session_id, b


def _wire_agent_and_engine(decision: AgentDecision, engine) -> FakeAgent:
    fake = FakeAgent(decision)
    app.dependency_overrides[get_agent] = lambda: fake
    app.dependency_overrides[get_engine] = lambda: engine
    return fake


def _unwire() -> None:
    app.dependency_overrides.pop(get_agent, None)
    app.dependency_overrides.pop(get_engine, None)


def test_heartbeat_triggers_agent_and_records_intervention(client, db, user, engine, frozen_now):
    sid, b = _repeated_failure_session(db, user)
    frozen_now["t"] = b.t

    decision = AgentDecision(
        state="STUCK",
        concept="loop",
        action=AgentAction.HINT,
        reason="같은 오류를 반복하고 있습니다.",
        activity={"kind": "hint", "message": "리스트를 어떻게 순회할까요?"},
    )
    fake = _wire_agent_and_engine(decision, engine)
    try:
        r = client.post(f"/sessions/{sid}/heartbeat")
        assert r.status_code == 200
        body = r.json()
        assert body["triggered"] is True
        assert body["trigger"] == TriggerType.REPEATED_FAILURE.value

        # 응답 자체에는 agent_decision이 안 실린다 -- 백그라운드로 넘어갔기 때문.
        assert "agent_decision" not in body

        assert len(fake.calls) == 1  # 트리거됐으니 실제로 불렸다

        rows = db.exec(
            select(Event)
            .where(Event.session_id == sid)
            .where(Event.type == EventType.AGENT_INTERVENTION)
        ).all()
        assert len(rows) == 1
        assert rows[0].payload["action"] == "HINT"
        assert rows[0].payload["concept"] == "loop"
        assert rows[0].payload["activity"]["message"] == "리스트를 어떻게 순회할까요?"
        assert rows[0].payload["trigger"] == "REPEATED_FAILURE"
    finally:
        _unwire()


def test_heartbeat_records_nothing_when_agent_waits(client, db, user, engine, frozen_now):
    """WAIT는 "안 함"이라 AGENT_INTERVENTION을 남기지 않는다 (AGENT_TRIGGER만 남음)."""
    sid, b = _repeated_failure_session(db, user)
    frozen_now["t"] = b.t

    decision = AgentDecision(state="STUCK", concept=None, action=AgentAction.WAIT, reason="대기")
    _wire_agent_and_engine(decision, engine)
    try:
        r = client.post(f"/sessions/{sid}/heartbeat")
        assert r.status_code == 200

        rows = db.exec(
            select(Event)
            .where(Event.session_id == sid)
            .where(Event.type == EventType.AGENT_INTERVENTION)
        ).all()
        assert rows == []
    finally:
        _unwire()


def test_heartbeat_skips_agent_entirely_when_not_triggered(client, db, user, engine):
    """방금 시작한 세션(막힘 신호 없음) -- agent를 부를 이유가 없다."""
    b = TraceBuilder.start(db, user_id=user.id, at=T0)
    sid = b.session_id

    decision = AgentDecision(state="x", concept=None, action=AgentAction.HINT, reason="불려선 안 됨")
    fake = _wire_agent_and_engine(decision, engine)
    try:
        r = client.post(f"/sessions/{sid}/heartbeat")
        assert r.status_code == 200
        assert r.json()["triggered"] is False
        assert fake.calls == []  # 트리거 안 됐으니 agent 자체를 안 불렀다

        rows = db.exec(
            select(Event).where(Event.session_id == sid).where(Event.type == EventType.AGENT_INTERVENTION)
        ).all()
        assert rows == []
    finally:
        _unwire()


def test_heartbeat_survives_agent_exception(client, db, user, engine, frozen_now):
    """agent.decide()가 터져도 하트비트 응답 자체는 200이어야 한다 (백그라운드라 이미 나간 뒤지만,
    엔드포인트가 실패를 삼키지 않고 요청 스레드로 새면 안 된다는 걸 확인)."""
    sid, b = _repeated_failure_session(db, user)
    frozen_now["t"] = b.t

    class ExplodingAgent:
        name = "exploding"

        def decide(self, ctx):
            raise RuntimeError("agent 서비스 응답 파싱 실패")

    app.dependency_overrides[get_agent] = lambda: ExplodingAgent()
    app.dependency_overrides[get_engine] = lambda: engine
    try:
        r = client.post(f"/sessions/{sid}/heartbeat")
        assert r.status_code == 200

        rows = db.exec(
            select(Event).where(Event.session_id == sid).where(Event.type == EventType.AGENT_INTERVENTION)
        ).all()
        assert rows == []  # 실패했으니 당연히 안 남음
    finally:
        _unwire()
